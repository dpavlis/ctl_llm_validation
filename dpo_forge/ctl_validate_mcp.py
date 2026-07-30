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
  - If the feature is disabled, the prompt's metadata can't be extracted as
    .fmt XML (e.g. the newer prose-format prompts with no <Record> XML at
    all), the component type has no tool mapping we're confident in, or the
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
# input/output/accumulator. Two-pass classification:
#   1. Proximity: a Record preceded (anywhere earlier in the prompt) by the
#      nearest "Input"/"Output"/"Accumulator" keyword gets that label —
#      covers phrasings like "Given Input Metadata on Port 0:", "Input
#      metadata (port 0):", "Accumulator metadata (to be used as ...):".
#   2. Positional fallback for any Record left unlabeled by pass 1 — many
#      real prompts give bare <Metadata id="..."> blocks with no input/
#      output keyword anywhere near them, relying purely on order (first
#      block = input, later blocks = output; confirmed against real dataset
#      examples, e.g. "We need to aggregate freight movements..." followed
#      directly by two unlabeled <Metadata> blocks then an explicitly
#      labeled "Accumulator metadata" block). The first unlabeled block
#      becomes input only if no input has been found yet at all (labeled or
#      not); every other unlabeled block becomes output. This assumes a
#      single input port, which holds for every component type here except
#      joiner — multi-input join prompts in this dataset consistently label
#      each port explicitly (needed to tell the ports apart at all), so pass
#      1 already handles that case before the fallback ever applies.
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


def _build_review_result(data: dict[str, Any]) -> ReviewResult:
    """Convert the tool's {overall, problems[]} output into a ReviewResult,
    so it slots into mut_validate.py's review loop exactly like a judge
    review — same rendering, same PASS/FAIL handling, same prior_issues
    carry-forward on the next attempt if this one fails."""
    issues: list[ReviewIssue] = []
    for p in data.get("problems", []):
        severity = (p.get("severity") or "WARNING").upper()
        if severity not in ("ERROR", "WARNING"):
            severity = "WARNING"
        bits = [f"[{p.get('stage', '?')}]", (p.get("message") or "").strip()]
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
    config, no <Record> XML found in the prompt, a Rollup candidate whose
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

    url = cfg.get("url", "http://localhost:8083/clover/mcp/mcp")
    timeout = cfg.get("timeout_s", 30)

    no_input_port = (component_type_bucket or "").upper() == "DATA_GENERATOR"
    input_records, output_records, accumulator_record = extract_ports_metadata(prompt, no_input_port=no_input_port)
    if not input_records and not output_records:
        if log_fn:
            log_fn("  [ctl-validate] skipped: no <Record> metadata XML found in the prompt "
                   "(likely a prose-metadata-format example)")
        return None

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
