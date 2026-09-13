"""ctl_validate MCP client — a real CTL2 compiler/metadata check, used as a
fast, deterministic pre-filter in front of the LLM judge.

Talks to an external MCP server (Streamable HTTP transport) that exposes a
`ctl_validate` tool: given a componentType, a CTL2 code string, and the
input/output/accumulator port metadata as CloverDX .fmt <Record> XML docs,
it actually parses the metadata and compiles the CTL2 code — no logic/
semantic review, just "does this parse and compile against these ports".

Design, per how this is wired into mut_validate.py's review loop:
  - If the MCP tool reports any ERROR-severity problem (overall == "FAIL"),
    that result IS the review for this attempt — the LLM judge is not
    called at all. A real compile error is unambiguous; there's nothing an
    LLM re-review adds, and skipping it saves a call.
  - If it reports overall == "PASS" (compiles cleanly, though it may still
    list WARNINGs), the LLM judge runs as normal for logic/semantic review.
    The compiler check and the LLM's own review are kept as separate
    concerns; ctl_validate's PASS result is not merged into the LLM's.
  - Extracted <Record> XML missing a `type` attribute (~23% of this
    dataset's examples use this terser style — confirmed live against the
    real server: "Attribute 'name' or 'type' not defined within Record!")
    is auto-repaired with a default `type="delimited"` before the call, so
    these still get real compiler validation instead of being skipped — see
    _ensure_type_attribute(). If every reported problem is still
    stage=="metadata" after that (some other gap we don't auto-repair),
    that's a gap in the PROMPT's own metadata, not something the MUT's code
    could ever satisfy — it does not count as a candidate defect, and falls
    through to the LLM judge like any other skip below.
  - Prompts that describe their ports in prose rather than .fmt XML (75% of
    the batch2 SFT file, and all of CTL_LoRA_join_complex_prompts.json) have
    that prose converted to <Record> XML so they get real compiler validation
    too — see synthesize_ports_metadata(), which is all-or-nothing: it yields
    nothing unless every port could be rebuilt with confidence, leaving the
    prompt on the skip path below exactly as before.
  - A task or candidate involving a lookup table is skipped before the call
    is made: a lookup is a graph-level object the tool cannot resolve, so it
    would fail such a candidate however correct it is. The LLM judge gives
    the verdict instead.
  - If the feature is disabled, the prompt's metadata can't be extracted as
    .fmt XML and can't be reconstructed from prose either, the component type
    has no tool mapping we're confident in, or the
    MCP call itself fails (server down, network error, protocol error) —
    this is a best-effort feature, so all of these fall through to the
    LLM-only judge exactly as if this feature didn't exist. Nothing here
    ever hard-fails the pipeline.

Requires the `mcp` package (`pip install mcp`) — imported lazily inside the
actual call, so it's only needed when ctl_validate_mcp.enabled is true in
the config; nothing else in mut_validate.py depends on it.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Optional

from .review_judge import ReviewIssue, ReviewResult

# ---------------------------------------------------------------------------
# Component type mapping — our internal bucket keys (see review_judge.py's
# _normalize_component_type / infer_component_type) to the tool's
# componentType enum (reformat, joiner, normalizer, denormalizer, partition,
# filter, rollup, expression, generic). Anything unmapped (DATA_GENERATOR,
# AI_OPENAI_CLIENT, REST_CONNECTOR, unresolved/empty) falls back to
# "generic" — the tool's own catch-all for "any other CTL2 code ... checks
# only that the code is compilable".
# ---------------------------------------------------------------------------

_COMPONENT_TYPE_TO_TOOL = {
    "REFORMAT": "reformat",
    "JOIN": "joiner",
    "NORMALIZER": "normalizer",
    "DENORMALIZER": "denormalizer",
    "PARTITION": "partition",
    "FILTER": "filter",
    "ROLLUP": "rollup",
}

# Per the tool description: output metadata is ignored for these two
# (partition only routes, filter is a bare boolean expression — neither
# writes $out), so we never send it even if something got extracted.
_NO_OUTPUT_METADATA_TYPES = {"partition", "filter"}


def map_component_type(bucket: str) -> str:
    return _COMPONENT_TYPE_TO_TOOL.get((bucket or "").upper(), "generic")


# ---------------------------------------------------------------------------
# Metadata extraction — prompts embed one <Record>...</Record> (a CloverDX
# .fmt XML document, usually wrapped in a <Metadata id="..."> tag we don't
# need) per port. There's no structured field marking a given Record as
# input/output/accumulator. Three-pass classification:
#   1. Proximity: a Record preceded (anywhere earlier in the prompt) by the
#      nearest "Input"/"Output"/"Accumulator" keyword gets that label —
#      covers phrasings like "Given Input Metadata on Port 0:", "Input
#      metadata (port 0):", "Accumulator metadata (to be used as ...):".
#   2. Bare port headers — "Port 0 metadata:", "Port 1 metadata:", "Input
#      port 1:" — which name a port WITHOUT saying input or output, so pass
#      1 never sees them (see _PORT_HEADER_RE). A bare port is an input
#      port; only an explicit "Output port N:" is an output.
#   3. Positional fallback for any Record left unlabeled by passes 1-2 — many
#      real prompts give bare <Metadata id="..."> blocks with no input/
#      output keyword anywhere near them, relying purely on order (first
#      block = input, later blocks = output; confirmed against real dataset
#      examples, e.g. "We need to aggregate freight movements..." followed
#      directly by two unlabeled <Metadata> blocks then an explicitly
#      labeled "Accumulator metadata" block). The first unlabeled block
#      becomes input only if no input has been found yet at all (labeled or
#      not); every other unlabeled block becomes output. This assumes a
#      single input port, which holds for every component type here except
#      joiner — so a multi-input join prompt MUST get its ports labeled by
#      pass 1 or pass 2 before the fallback is reached, or every port after
#      the master silently becomes an "output" record. That is exactly what
#      pass 2 exists to prevent: the bare "Port N metadata:" join prompts
#      match no input/output keyword at all, and under the fallback alone
#      the slave ports were misfiled as outputs — making $out.0 resolve
#      against the slave schema and $in.1 unreadable, so a correct candidate
#      failed to compile with dozens of bogus errors.
# ---------------------------------------------------------------------------

_RECORD_RE = re.compile(r"<Record\b.*?</Record>", re.IGNORECASE | re.DOTALL)
# Requires "metadata" to actually follow within a short character window —
# plain "input"/"output" show up constantly as ordinary English (e.g. "roll
# up daily machine output into a summary") and must NOT be mistaken for a
# metadata section label; only "Input/Output/Accumulator Metadata"-style
# headers (in either word order, e.g. "Metadata input has fields:") should
# count. Character-distance (not word-count) on purpose: headers like
# "Input port 1:\n<Metadata id=\"S1\">" have "metadata" glued directly to a
# preceding "<" with no whitespace in between (the XML tag itself, not prose)
# — a word-boundary-only \b still matches there (since "<" is a non-word
# char), but a stricter "must be preceded by whitespace" check does not, so
# this must NOT require whitespace immediately before "metadata". The
# {0,30} character budget (not crossing a sentence end) covers "input"/
# "output" followed by a port label ("port 1:") before the tag starts.
_KEYWORD_RE = re.compile(
    r"\b(input|output|accumulator)\b(?=[^.!?]{0,30}?\bmetadata\b)"
    r"|\bmetadata\b(?=[^.!?]{0,30}?\b(input|output|accumulator)\b)",
    re.IGNORECASE,
)

# Port headers that name a port but never the word input/output — "Port 0
# metadata:", "Port 1 metadata:" (the newer join prompt style), "Input port
# 1:", "Output port 0 metadata:". _KEYWORD_RE cannot label these: the bare
# ones contain no input/output token to match on at all. Anchored to the
# start of a line so it only fires on an actual section header, never on
# prose like "routes records to port 1" or on an inline "(port 0)" inside
# an "Output metadata, port 0:" header (already handled by _KEYWORD_RE, and
# left to it — this must not relabel those as inputs). An unqualified port
# header means an INPUT port; a component's own output ports are spelled out
# explicitly ("Output port 0:") in every prompt style seen in this dataset.
_PORT_HEADER_RE = re.compile(
    r"^[^\S\n]*(?:(input|output|accumulator)\s+)?port\s+\d+(?:\s+metadata)?\s*:",
    re.IGNORECASE | re.MULTILINE,
)


_RECORD_OPEN_TAG_RE = re.compile(r"<Record\b[^>]*>", re.IGNORECASE)


def _ensure_type_attribute(record_xml: str) -> str:
    """Some prompts describe <Record> metadata with no `type` attribute at
    all (~23% of this dataset — confirmed live against the real server:
    "Attribute 'name' or 'type' not defined within Record!"). Default to
    type="delimited" (matching the delimited-text style every one of these
    terser examples otherwise implies) rather than treating a large chunk of
    the dataset as unvalidatable purely over a missing default attribute."""
    def _inject(m: re.Match) -> str:
        tag = m.group(0)
        if re.search(r"\btype\s*=", tag, re.IGNORECASE):
            return tag
        if tag.endswith("/>"):
            return tag[:-2].rstrip() + ' type="delimited"/>'
        return tag[:-1].rstrip() + ' type="delimited">'
    return _RECORD_OPEN_TAG_RE.sub(_inject, record_xml, count=1)


def extract_ports_metadata(
    prompt: str, no_input_port: bool = False,
) -> tuple[list[str], list[str], Optional[str]]:
    """Returns (input_records, output_records, accumulator_record) — each a
    raw <Record>...</Record> XML string, in the order they appear in the
    prompt. Returns ([], [], None) if no <Record> XML is present at all
    (e.g. a prose-metadata-format prompt) — callers should treat that as
    "can't validate, skip".

    no_input_port: for component types that structurally have no input port
    at all (DataGenerator) — an unlabeled block would otherwise default to
    "input" under the general single-input assumption, when it's actually
    always output here."""
    records = [(m.start(), _ensure_type_attribute(m.group(0))) for m in _RECORD_RE.finditer(prompt)]
    if not records:
        return [], [], None
    keywords = [(m.start(), (m.group(1) or m.group(2)).lower()) for m in _KEYWORD_RE.finditer(prompt)]
    keywords += [(m.start(), (m.group(1) or "input").lower()) for m in _PORT_HEADER_RE.finditer(prompt)]
    keywords.sort()  # both passes feed one position-ordered list: nearest-preceding label wins

    labels: list[Optional[str]] = []
    for pos, _xml in records:
        label = None
        for kpos, kw in keywords:
            if kpos >= pos:
                break
            label = kw
        labels.append(label)

    accumulator_record = next((xml for label, (_pos, xml) in zip(labels, records) if label == "accumulator"), None)

    input_records: list[str] = []
    output_records: list[str] = []
    for label, (_pos, xml) in zip(labels, records):
        if label == "accumulator":
            continue
        elif label == "input":
            input_records.append(xml)
        elif label == "output":
            output_records.append(xml)
        elif no_input_port:
            output_records.append(xml)
        elif not input_records:
            input_records.append(xml)  # positional fallback: first unlabeled -> input
        else:
            output_records.append(xml)  # positional fallback: later unlabeled -> output
    return input_records, output_records, accumulator_record


# ---------------------------------------------------------------------------
# Prose metadata synthesis — a large and growing share of prompts describe
# their ports in prose instead of .fmt XML (75% of the batch2 SFT file, and
# every example in CTL_LoRA_join_complex_prompts.json). Those used to be
# skipped outright for want of a <Record> to send. Three prose shapes occur:
#
#   inline, labelled     "Port 0 metadata: PurchaseOrder(po_id:string, ...)."
#   inline, run-together "Port 0 Invoice(a:string). Port 1 Customer(b:date)."
#   bulleted block       "Input metadata (port 0):\n- cust_id: string\n- ..."
#
# Correctness bar: synthesis must be ALL-OR-NOTHING per prompt. Half-built
# metadata is worse than none — a port we failed to find makes perfectly good
# code fail to compile ("Cannot read from input port '1'"), and because a
# ctl_validate FAIL suppresses the LLM judge entirely, that bogus verdict
# would stand as the whole review. So every helper below raises _Bail on the
# first thing it cannot pin down, and _Bail discards the entire prompt back to
# the pre-existing skip path. Validated against ground truth: the 10 prose
# prompts in CTL_LoRA_join_complex_prompts.json restate the same scenarios as
# the hand-written XML in CTL_LoRA_join_complex_prompts_with_meta.json, and
# synthesis reproduces all 10 exactly — same record names, same port roles,
# same field names and types.
# ---------------------------------------------------------------------------

_CTL_TYPES = {"string", "integer", "long", "number", "decimal", "boolean",
              "date", "byte", "cbyte", "variant"}

_INLINE_RECORD_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(([^()]*(?:\[[^\]]*\][^()]*)*)\)")
_BULLET_FIELD_RE = re.compile(
    r"^[^\S\n]*[-*][^\S\n]*(?P<name>[A-Za-z_]\w*)[^\S\n]*:[^\S\n]*(?P<spec>.+?)[^\S\n]*$")
_FIELD_PAIR_RE = re.compile(r"^\s*[A-Za-z_]\w*\s*:\s*\S.*$")


class _Bail(Exception):
    """Raised on anything that cannot be pinned down with full confidence;
    aborts synthesis for the whole prompt (see the section comment above)."""


def _split_top_level_commas(body: str) -> list[str]:
    """Split on commas outside [] — 'a:map[string, decimal], b:integer'."""
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p for p in parts if p.strip()]


def _parse_prose_type(spec: str) -> tuple[str, Optional[str], Optional[str]]:
    """'integer[] (nullable)' -> ('integer', 'list', 'true').

    Takes the base type from the first token and reads nullability only from
    recognised markers, so trailing prose a prompt tacks on ("string  (the
    file name without extension)", "integer (0=normal, 1=high)") is ignored
    rather than confusing the parse. containerType spellings per
    resources/ctl2-basics.md: type[] -> list, map[string, type] -> map."""
    s = spec.split("//")[0].strip().rstrip(".").strip()
    low = s.lower()
    nullable = None
    if re.search(r"\bnot\s*null\b", low) or 'nullable="false"' in low:
        nullable = "false"
    elif re.search(r"\bnullable\b", low):
        nullable = "true"

    container = None
    m = re.match(r"^map\s*\[\s*string\s*,\s*(\w+)\s*\]", s, re.IGNORECASE)
    if m:
        base, container = m.group(1).lower(), "map"
    elif re.match(r"^\w+\s*\[\s*\]", s):
        base, container = re.match(r"^(\w+)", s).group(1).lower(), "list"
    elif re.match(r"^\w+\s+list\b", s, re.IGNORECASE):
        base, container = re.match(r"^(\w+)", s).group(1).lower(), "list"
    else:
        m = re.match(r"^(\w+)", s)
        if not m:
            raise _Bail(f"unparseable type spec: {spec!r}")
        base = m.group(1).lower()

    if base not in _CTL_TYPES:
        raise _Bail(f"unknown CTL2 type {base!r} in {spec!r}")
    return base, container, nullable


def _classify_prose_header(hdr: str, seen_labelled_input: bool) -> tuple[str, Optional[str], bool]:
    """Header text -> (role, record name or None, role_was_explicit).

    Only the header's final clause is considered: these headers are often the
    tail of a prose sentence ("...and port 1 to receive everything else.
    Metadata:"), and role or port words from the sentence body must not be
    read as a label for the block that follows."""
    clause = re.split(r"[.?!]\s+", hdr.strip())[-1].strip().rstrip(":").strip()
    if re.search(r"\blookup\b", clause, re.IGNORECASE):
        # A lookup is a graph-level object, not a port — sending its schema as
        # a port would invent an edge the component doesn't have.
        raise _Bail(f"lookup block, not a port: {clause!r}")

    roles = set()
    for w in re.findall(r"\b(input|output|left|right|master|slave|accumulator)\b", clause, re.IGNORECASE):
        w = w.lower()
        # a joiner's right/slave IS an input port
        roles.add({"output": "output", "accumulator": "accumulator"}.get(w, "input"))
    if len(roles) > 1:
        raise _Bail(f"header names more than one role: {clause!r}")

    rec = None
    m = (re.search(r"[`\"']([A-Za-z_]\w*)[`\"']", clause)
         or re.search(r"\(\s*(?:port\s*\d+\s*,\s*)?(?:name\s*:\s*)?([A-Za-z_]\w*)\s*\)", clause, re.IGNORECASE))
    if m and m.group(1).lower() not in (
            "port", "name", "metadata", "master", "slave", "nullable", "lookup", "record"):
        rec = m.group(1)

    if roles:
        return roles.pop(), rec, True
    # No role word at all. A bare "Port N ..." header names an INPUT port —
    # unless an explicitly labelled input block already appeared, in which case
    # the bare port headers are enumerating this component's OUTPUT ports:
    #   "Port 0 metadata: PurchaseOrder(..)" / "Port 1 metadata: Vendor(..)"
    #        -> a joiner's two INPUT ports (no explicit input header anywhere)
    #   "Input metadata: PaymentIn(..)" / "Port 0 metadata: MatchedPaymentOut(..)"
    #        -> a Reformat's two OUTPUT ports, after an explicit input header
    if re.search(r"\bport\s*\d+", clause, re.IGNORECASE):
        return ("output" if seen_labelled_input else "input"), rec, False
    raise _Bail(f"unclassifiable metadata header: {clause!r}")


def _emit_record(rec_name: str, fields) -> str:
    out = [f'<Record name="{rec_name}" type="delimited">']
    for fname, ftype, container, nullable in fields:
        attrs = f'<Field name="{fname}" type="{ftype}"'
        if container:
            attrs += f' containerType="{container}"'
        if nullable:
            attrs += f' nullable="{nullable}"'
        out.append(attrs + "/>")
    out.append("</Record>")
    return "".join(out)


def _collect_prose_blocks(prompt: str) -> list[tuple[int, str, Optional[str], list]]:
    """-> [(offset, header text, record name or None, [(field, type spec)])]"""
    blocks: list[tuple[int, str, Optional[str], list]] = []
    consumed_lines: set[int] = set()

    for m in _INLINE_RECORD_RE.finditer(prompt):
        parts = _split_top_level_commas(m.group(2))
        if not parts or not all(_FIELD_PAIR_RE.match(p) for p in parts):
            continue  # ordinary prose or a function call, not a field list
        pairs = [tuple(x.strip() for x in p.split(":", 1)) for p in parts]
        line_start = prompt.rfind("\n", 0, m.start()) + 1
        hdr_start = max(line_start, prompt.rfind(". ", line_start, m.start()) + 1)
        blocks.append((m.start(), prompt[hdr_start:m.start()], m.group(1), pairs))
        consumed_lines.add(prompt.count("\n", 0, m.start()))

    lines = prompt.split("\n")
    i = 0
    while i < len(lines):
        fields, j = [], i
        while j < len(lines) and _BULLET_FIELD_RE.match(lines[j]):
            b = _BULLET_FIELD_RE.match(lines[j])
            fields.append((b.group("name"), b.group("spec")))
            j += 1
        if fields and i not in consumed_lines:
            k = i - 1
            while k >= 0 and not lines[k].strip():
                k -= 1
            if k >= 0:
                blocks.append((sum(len(x) + 1 for x in lines[:k]), lines[k], None, fields))
            i = j
        else:
            i = max(j, i + 1)

    blocks.sort(key=lambda b: b[0])
    return blocks


def synthesize_ports_metadata(
    prompt: str, component_type_bucket: str = "",
) -> tuple[list[str], list[str], Optional[str]]:
    """Build .fmt <Record> XML from a prompt that describes its ports in prose.

    Same return shape as extract_ports_metadata. Returns ([], [], None) unless
    every port in the prompt could be reconstructed with full confidence —
    callers treat that exactly as "no metadata found" and skip, as before."""
    try:
        return _synthesize_ports_metadata(prompt, component_type_bucket)
    except _Bail:
        return [], [], None


def _synthesize_ports_metadata(
    prompt: str, component_type_bucket: str,
) -> tuple[list[str], list[str], Optional[str]]:
    blocks = _collect_prose_blocks(prompt)
    if not blocks:
        raise _Bail("no prose metadata blocks found")

    ins: list[str] = []
    outs: list[str] = []
    acc: Optional[str] = None
    seen_labelled_input = False
    for _off, hdr, rec, pairs in blocks:
        role, hdr_rec, explicit = _classify_prose_header(hdr, seen_labelled_input)
        parsed = [(fname,) + _parse_prose_type(spec) for fname, spec in pairs]
        if not parsed:
            raise _Bail("empty field list")
        name = rec or hdr_rec or (f"In{len(ins)}" if role == "input" else f"Out{len(outs)}")
        xml = _emit_record(name, parsed)
        if role == "accumulator":
            if acc is not None:
                raise _Bail("more than one accumulator record")
            acc = xml
        elif role == "input":
            ins.append(xml)
            seen_labelled_input = seen_labelled_input or explicit
        else:
            outs.append(xml)

    # Completeness guard. Plenty of prompts spell out one side and leave the
    # other to prose ("Output needs a normalized name field where..."), which
    # would otherwise yield metadata missing a port the code legitimately uses.
    bucket = (component_type_bucket or "").upper()
    if bucket != "DATA_GENERATOR" and not ins:
        raise _Bail("no input port recovered")
    if bucket not in ("PARTITION", "FILTER") and not outs:
        raise _Bail("no output port recovered")
    return ins, outs, acc


# Detects the accumulator TYPE NAME a Rollup candidate's group functions
# declare (e.g. `function void initGroup(Acc acc)` -> "Acc"), so we can tell
# whether the code actually needs an accumulator schema we don't have. Per
# the tool: omitting accumulatorMetadata is only correct when the code uses
# the built-in VoidMetadata type (i.e. no real group accumulator).
_ROLLUP_GROUP_FN_RE = re.compile(
    r"function\s+(?:void|boolean|integer)\s+(?:initGroup|updateGroup|finishGroup)\s*\(\s*(\w+)\s+\w+\s*\)",
    re.IGNORECASE,
)


def _rollup_needs_accumulator_metadata(code: str) -> bool:
    """True if the candidate's group functions reference a named (non-Void)
    accumulator type — meaning we'd need a matching <Record> to validate it,
    and calling ctl_validate without one would likely misreport a missing-
    schema problem as a candidate defect."""
    m = _ROLLUP_GROUP_FN_RE.search(code)
    if not m:
        return False
    return m.group(1).strip().lower() != "voidmetadata"


# ---------------------------------------------------------------------------
# MCP call
# ---------------------------------------------------------------------------

async def _call_ctl_validate_async(
    url: str,
    timeout: float,
    component_type: str,
    code: str,
    input_metadata: list[str],
    output_metadata: list[str],
    accumulator_metadata: Optional[str],
) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    arguments: dict[str, Any] = {"componentType": component_type, "code": code}
    if input_metadata:
        arguments["inputMetadata"] = input_metadata
    if output_metadata and component_type not in _NO_OUTPUT_METADATA_TYPES:
        arguments["outputMetadata"] = output_metadata
    if accumulator_metadata:
        arguments["accumulatorMetadata"] = accumulator_metadata

    async with streamablehttp_client(url, timeout=timeout) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("ctl_validate", arguments=arguments)

    if result.isError:
        raise RuntimeError(f"ctl_validate tool call returned isError=True: {result.content!r}")
    if result.structuredContent is not None:
        return result.structuredContent
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    raise RuntimeError("ctl_validate returned neither structuredContent nor a parseable text block")


# ctl_validate compiles the candidate CTL2 code in isolation, without the
# rest of the graph — it therefore can never resolve a sequence or lookup
# table by name (those are graph-level objects defined outside the CTL being
# checked). "Unable to resolve sequence/lookup '...'" is a known limitation
# of the tool itself, not a real defect in the candidate code: still surface
# it (kept in the issue list, visible in the log) but never let it fail
# compilation. Lookup-using candidates are now skipped before the call is
# ever made (see _LOOKUP_IN_PROMPT_RE), so this is a backstop for whatever
# slips past that — an unmentioned lookup reached by some other spelling,
# or a sequence, which is not pre-filtered — downgraded to INFO regardless of what severity the tool
# reported, and excluded from has_error/has_warning/verdict.
# Allows for filler words between the keyword and the quoted name — the tool
# has been observed phrasing this both as "Unable to resolve lookup 'X'" and
# "Unable to resolve lookup table 'X'" (likewise "sequence" / "sequence
# object" etc.), so match up to a short run of non-quote characters rather
# than requiring the quote immediately after the keyword.
# A lookup table is a graph-level object: its own metadata, key and data
# source all live outside the CTL being checked, and none of that is in the
# prompt's port metadata. ctl_validate therefore cannot resolve one, so a
# candidate that uses a lookup can never be fairly compiled here — the tool
# would report "Unable to resolve lookup" (or reject field access on the
# lookup result) no matter how correct the code is. Skip the tool entirely
# for these and let the LLM judge give the verdict.
#
# Detected from BOTH sides: the prompt (the task is specified in terms of a
# lookup table, so a correct answer is bound to use one) and the candidate
# code (`lookup(Name).get(...)` — the CTL2 lookup syntax per
# resources/ctl2-basics.md). "lookup" as part of a longer identifier
# (lookup_key) is not a match, since \b requires a non-word character.
#
# One exception on the prompt side: a joiner's slave port is often DESCRIBED
# as a lookup while being an ordinary input port — "Right metadata (port 1,
# lookup):", "Slave input on Port 1 (lookup table for client details):". The
# code for those reads $in.1 and never calls lookup(), so the tool validates
# them perfectly well and skipping would lose real coverage. A lookup given a
# port number is therefore read as a port, not a lookup object; a real lookup
# table never has one, since the component has no port for it. The code-side
# check backstops the residual case of a genuine lookup that the prompt only
# ever mentions in the same breath as a port.
_LOOKUP_WORD_RE = re.compile(r"\blookups?\b", re.IGNORECASE)
_PORT_REF_RE = re.compile(r"\bport\s*\d", re.IGNORECASE)
_LOOKUP_IN_CODE_RE = re.compile(r"\blookup\s*\(", re.IGNORECASE)


def _prompt_uses_lookup_table(prompt: str) -> bool:
    """True if the prompt specifies a real lookup table, as opposed to merely
    calling an input port a 'lookup'.

    A single clause naming both a lookup and a port ("Right metadata (port 1,
    lookup):") settles it for the whole prompt: this task's "lookup" IS a
    port, so the loose prose around it ("the right side is a lookup table of
    document templates") is describing that port too, and the code will read
    $in.1 rather than call lookup(). A genuine lookup table is never given a
    port number, because the component has no port for it."""
    clauses = re.split(r"[\n.?!]+", prompt)
    if any(_LOOKUP_WORD_RE.search(c) and _PORT_REF_RE.search(c) for c in clauses):
        return False
    return any(_LOOKUP_WORD_RE.search(c) for c in clauses)


_UNVERIFIABLE_REF_RE = re.compile(r"Unable to resolve (?:sequence|lookup)\b[^']{0,20}'", re.IGNORECASE)


def _build_review_result(data: dict[str, Any]) -> ReviewResult:
    """Convert the tool's {overall, problems[]} output into a ReviewResult,
    so it slots into mut_validate.py's review loop exactly like a judge
    review — same rendering, same PASS/FAIL handling, same prior_issues
    carry-forward on the next attempt if this one fails."""
    issues: list[ReviewIssue] = []
    for p in data.get("problems", []):
        message = (p.get("message") or "").strip()
        severity = (p.get("severity") or "WARNING").upper()
        if severity not in ("ERROR", "WARNING"):
            severity = "WARNING"
        if _UNVERIFIABLE_REF_RE.search(message):
            severity = "INFO"
        bits = [f"[{p.get('stage', '?')}]", message]
        loc_bits = []
        if p.get("line") is not None:
            loc = f"line {p['line']}"
            if p.get("column") is not None:
                loc += f":{p['column']}"
            loc_bits.append(loc)
        if p.get("portType") is not None:
            loc_bits.append(
                f"{p['portType']} port {p['port']}" if p.get("port") is not None else str(p["portType"])
            )
        if loc_bits:
            bits.append(f"({', '.join(loc_bits)})")
        if p.get("hint"):
            bits.append(f"— hint: {p['hint']}")
        issues.append(ReviewIssue(severity=severity, description=" ".join(x for x in bits if x)))

    verdict = "FAIL" if any(i.severity == "ERROR" for i in issues) else "PASS"
    return ReviewResult(
        issues=issues,
        suggestions=[],
        verdict=verdict,
        raw_text=json.dumps(data),
        has_error=any(i.severity == "ERROR" for i in issues),
        has_warning=any(i.severity == "WARNING" for i in issues),
    )


def validate_ctl(
    cfg: dict,
    component_type_bucket: str,
    prompt: str,
    code: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Optional[ReviewResult]:
    """Best-effort compile/metadata check via the ctl_validate MCP tool.

    Returns None whenever this step can't run or doesn't apply — disabled in
    config, a task or candidate that uses a lookup table (unresolvable here),
    no port metadata recoverable from the prompt, a Rollup candidate whose
    accumulator type we can't supply metadata for, or any MCP-level failure
    (server unreachable, timeout, protocol error). Callers should treat None
    as "skip this step, proceed to the LLM judge exactly as before" — this
    is a pre-filter, never a hard dependency.

    Returns a real ReviewResult (PASS or FAIL) on a successful call —
    the caller is responsible for skipping the LLM judge when it's FAIL,
    per this feature's whole point (a compile error needs no LLM opinion).
    """
    if not cfg.get("enabled"):
        return None

    if _prompt_uses_lookup_table(prompt) or _LOOKUP_IN_CODE_RE.search(code):
        if log_fn:
            where = "the prompt" if _prompt_uses_lookup_table(prompt) else "the candidate code"
            log_fn(f"  [ctl-validate] skipped: {where} involves a lookup table, which the tool "
                   f"cannot resolve (its metadata and data source live outside the CTL) — "
                   f"falling back to the LLM judge")
        return None

    url = cfg.get("url", "http://localhost:8083/clover/mcp/mcp")
    timeout = cfg.get("timeout_s", 30)

    no_input_port = (component_type_bucket or "").upper() == "DATA_GENERATOR"
    input_records, output_records, accumulator_record = extract_ports_metadata(prompt, no_input_port=no_input_port)
    synthesized = False
    if not input_records and not output_records:
        # No .fmt XML in the prompt — try to rebuild the ports from a prose
        # description of them instead. All-or-nothing: this yields nothing at
        # all unless every port could be reconstructed with full confidence.
        input_records, output_records, accumulator_record = synthesize_ports_metadata(
            prompt, component_type_bucket)
        synthesized = bool(input_records or output_records)
    if not input_records and not output_records:
        if log_fn:
            log_fn("  [ctl-validate] skipped: no <Record> metadata XML in the prompt, and its "
                   "prose metadata could not be reconstructed with confidence")
        return None
    if synthesized and log_fn:
        log_fn(f"  [ctl-validate] metadata synthesized from the prompt's prose description "
               f"({len(input_records)} input, {len(output_records)} output"
               f"{', 1 accumulator' if accumulator_record else ''})")

    tool_component_type = map_component_type(component_type_bucket)
    if tool_component_type == "rollup" and not accumulator_record and _rollup_needs_accumulator_metadata(code):
        if log_fn:
            log_fn("  [ctl-validate] skipped: Rollup candidate references a named accumulator type "
                   "but no accumulator <Record> was found in the prompt to validate it against")
        return None

    try:
        data = asyncio.run(_call_ctl_validate_async(
            url, timeout, tool_component_type, code, input_records, output_records, accumulator_record,
        ))
    except Exception as e:
        if log_fn:
            log_fn(f"  [ctl-validate] ERROR calling MCP tool ({e}) — falling back to the LLM judge")
        return None

    # A metadata-stage problem means the PROMPT's own <Record> XML doesn't
    # meet the real .fmt schema. The most common cause (missing `type=`, seen
    # on ~23% of this dataset's examples) is already auto-repaired above by
    # _ensure_type_attribute before we ever get here, so this is now a rarer
    # fallback for whatever else the metadata might be missing — still a gap
    # in the task's own metadata, not something the MUT's code could ever
    # satisfy, so it must not count as a candidate defect. Per the tool's own
    # staged, fail-fast design, a real compile-stage batch is never mixed
    # with metadata-stage problems in the same response (metadata parsing
    # runs first and blocks anything later), so checking "every problem is
    # metadata-stage" is a safe, sufficient test.
    problems = data.get("problems", [])
    if problems and all((p.get("stage") or "").lower() == "metadata" for p in problems):
        if log_fn:
            log_fn("  [ctl-validate] skipped: all reported problems are metadata-stage "
                   "(the prompt's own <Record> XML doesn't meet the real .fmt schema — "
                   "not a code defect) — falling back to the LLM judge")
        return None

    return _build_review_result(data)
