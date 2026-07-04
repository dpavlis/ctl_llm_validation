"""Judge for mut_validate.py — plain-text code review (no execution evidence).

Unlike judge.py's JSON-verdict JudgeClient (used by dpo_forge.py alongside
CloverDX execution evidence), this judge does a static review of the MUT's
CTL2 code against the stated task requirements and CTL2 semantics, and
returns a fixed ISSUES / SUGGESTIONS / VERDICT text format. It also offers a
second mode (fix()) where the judge rewrites the code itself, and a third
(tweak()) that rewrites an SFT prompt into a fresh practice task.

Prompt design here deliberately avoids anything that looks like it is
managing a model's hidden reasoning (a "think" tool, "scratchpad", "working
notes", etc.) — that pattern reads as chain-of-thought manipulation to
OpenAI's moderation classifier and triggered intermittent `invalid_prompt`
rejections on reasoning-tier models. Instead, prompts ask for careful
analysis but only ever request the final output; see
ctl2_reviewer_prompt_safety_mini_spec.md for the full rationale.

The LLM-call plumbing here intentionally mirrors JudgeClient's _get_llm/_call
rather than reusing it, to avoid touching the already-working dpo_forge.py
pipeline.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TextIO

from .generator import normalize_ctl
from .judge import _CTL2_REFERENCE, infer_component_type


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ReviewIssue:
    severity: str        # ERROR | WARNING | INFO
    description: str


@dataclass
class ReviewResult:
    issues: list[ReviewIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    verdict: str = "FAIL"        # PASS | FAIL
    raw_text: str = ""           # judge's raw response, kept for debugging/logging only
    has_error: bool = False
    has_warning: bool = False

    def render(self) -> str:
        """Re-render the ISSUES/SUGGESTIONS/VERDICT text from the parsed,
        filtered fields (not the model's raw response) — this is what gets
        fed back to the MUT and stored in the SFT conversation, so any
        retracted/dropped issues never leak back in via raw_text."""
        lines = ["-------"]
        if not self.issues:
            lines.append("ISSUES: none")
        else:
            lines.append("ISSUES:")
            for issue in self.issues:
                lines.append(f"  [{issue.severity}] {issue.description}")
        if self.suggestions:
            lines.append("")
            lines.append("SUGGESTIONS:")
            for s in self.suggestions:
                lines.append(f"  - {s}")
        lines.append("")
        lines.append(f"VERDICT: {self.verdict}")
        lines.append("-------")
        return "\n".join(lines)




# ---------------------------------------------------------------------------
# Component contracts — resources/componet_contracts.md
#
# Authoritative per-component CTL2 contracts (entry points, lifecycle, port
# access rules, return-code semantics, canonical mistakes). This is kept
# separate from dpo_forge/judge.py's own (execution-oriented) component notes
# rather than shared, so a fix here can't affect the already-working
# dpo_forge.py pipeline.
# ---------------------------------------------------------------------------

def _classify_contract_header(header: str) -> str:
    """Map a '## ...' section header from componet_contracts.md to one of
    the canonical component-type keys used below. Order matters: check
    "denormalizer" before "normalizer" since the former's name contains the
    latter as a substring."""
    h = header.lower()
    if "denormalizer" in h:
        return "DENORMALIZER"
    if "normalizer" in h:
        return "NORMALIZER"
    if "reformat" in h or re.search(r"\bmap\b", h):
        return "REFORMAT"
    if "filter" in h:
        return "FILTER"
    if "partition" in h:
        return "PARTITION"
    if "rollup" in h:
        return "ROLLUP"
    if "join" in h or "intersection" in h or "combine" in h:
        return "JOIN"
    if "datagenerator" in h or "data generator" in h:
        return "DATA_GENERATOR"
    if "openai" in h:
        return "AI_OPENAI_CLIENT"
    if "rest connector" in h:
        return "REST_CONNECTOR"
    return ""


def _load_component_contracts() -> dict[str, str]:
    """Parse resources/componet_contracts.md into {canonical_key: section_text}."""
    path = Path(__file__).parent.parent / "resources" / "componet_contracts.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## (.+)$", text)
    sections: dict[str, str] = {}
    # parts[0] is the preamble before the first "## " header; after that,
    # headers and bodies alternate: [header, body, header, body, ...].
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        key = _classify_contract_header(header)
        if key and body:
            sections[key] = f"## {header}\n\n{body}"
    return sections


_COMPONENT_CONTRACTS = _load_component_contracts()

# Maps the many spellings a component type can arrive in — the SFT source
# data's Title-Case "inferred_component" field (e.g. "Rollup", "DataGenerator"),
# and judge.infer_component_type()'s own canonical strings (e.g. "EXT_HASH_JOIN",
# "EXT_FILTER") — onto the keys _COMPONENT_CONTRACTS is indexed by.
_COMPONENT_TYPE_ALIASES = {
    "REFORMAT": "REFORMAT", "MAP": "REFORMAT", "REFORMAT_MAP": "REFORMAT",
    "FILTER": "FILTER", "EXT_FILTER": "FILTER",
    "PARTITION": "PARTITION",
    "ROLLUP": "ROLLUP",
    "DENORMALIZER": "DENORMALIZER",
    "NORMALIZER": "NORMALIZER",
    "JOIN": "JOIN", "EXT_HASH_JOIN": "JOIN", "EXT_MERGE_JOIN": "JOIN",
    "DATA_INTERSECTION": "JOIN", "CROSS_JOIN": "JOIN", "COMBINE": "JOIN",
    # "Lookup" and "Sequence" (as seen in the SFT dataset's inferred_component
    # field) describe a *function* used inside another component (typically a
    # Reformat), not a distinct component contract — deliberately left
    # unmapped so callers fall back to infer_component_type(code) instead of
    # attaching a misleading Join/other contract.
    "DATA_GENERATOR": "DATA_GENERATOR", "DATAGEN": "DATA_GENERATOR",
    "DATAGENERATOR": "DATA_GENERATOR",
}


def _normalize_component_type(component_type: str) -> str:
    """Normalize a raw component-type label (from the SFT dataset or from
    infer_component_type()) to a canonical key for _COMPONENT_CONTRACTS.
    Unknown/ambiguous labels (e.g. "Sequence") normalize to "" so callers can
    fall back to signature-based inference instead of guessing."""
    if not component_type:
        return ""
    key = re.sub(r"[\s/\-]+", "_", component_type.strip().upper())
    return _COMPONENT_TYPE_ALIASES.get(key, "")


def normalize_component_type(component_type: str) -> str:
    """Public wrapper around _normalize_component_type, for callers (e.g.
    mut_validate.py) that want to log/inspect the resolved contract bucket."""
    return _normalize_component_type(component_type)


# SFT datasets can carry a pre-existing "inferred_component" label that is
# simply wrong (found e.g. several "Denormalizer" tasks mislabeled as
# "Normalizer" — almost certainly from a naive substring match on the source
# data's own labeling pass, the exact same trap _classify_contract_header()
# above guards against). Rather than trust that label, classify directly from
# what the user prompt actually asks for. Order matters: "denormalizer" must
# be checked before "normalizer" since the former contains the latter as a
# literal substring.
_PROMPT_COMPONENT_PATTERNS: list[tuple[str, str]] = [
    (r"\bdenormalizer\b", "DENORMALIZER"),
    (r"\bnormalizer\b", "NORMALIZER"),
    (r"\brollup\b", "ROLLUP"),
    (r"\bpartition(?:ing|er)?\b", "PARTITION"),
    (r"\b(?:ext[_ ]?hash[_ ]?join|ext[_ ]?merge[_ ]?join|data\s*intersection|cross\s*join|combine)\b", "JOIN"),
    (r"\bjoin\b", "JOIN"),
    (r"\b(?:data\s*generator|datagenerator|datagen)\b", "DATA_GENERATOR"),
    (r"\bfilter\b", "FILTER"),
    (r"\b(?:reformat|map/?reformat|reformat/?map)\b", "REFORMAT"),
]


def infer_component_type_from_prompt(prompt: str) -> str:
    """Best-effort component-type classification from the user prompt's own
    wording — NOT from any dataset-provided label. Returns a canonical
    _COMPONENT_CONTRACTS key, or "" if the prompt doesn't name a component
    clearly enough to tell (caller should fall back to infer_component_type()
    on the candidate code, and ideally flag the example for manual review)."""
    for pattern, bucket in _PROMPT_COMPONENT_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            return bucket
    return ""


def describe_component_resolution(prompt_component_type: str, code: str) -> str:
    """Human-readable trace of how a component type was resolved to a
    contract bucket, e.g.:
      resolved='REFORMAT' (inferred from code — prompt didn't name one) -> bucket=REFORMAT (contract attached)
    """
    resolved = prompt_component_type or infer_component_type(code)
    source = "from prompt text" if prompt_component_type else "inferred from code — prompt didn't name one"
    bucket = _normalize_component_type(resolved)
    has_note = bool(_COMPONENT_CONTRACTS.get(bucket))
    return (
        f"resolved={resolved or '(none)'!r} ({source}) "
        f"-> bucket={bucket or '(none)'} "
        f"({'contract attached' if has_note else 'no contract note'})"
    )


# ---------------------------------------------------------------------------
# Prompts — review mode
#
# Structure follows ctl2_reviewer_prompt_safety_mini_spec.md:
#   system:  stable role/rules block, then the (stable, large) CTL2 reference,
#            then the (variable, per-example) component contract last —
#            maximizes the byte-identical shared prefix for prompt caching.
#   user:    the per-example task (component type, original prompt, candidate
#            code) — nothing stable lives here.
# No step of this asks the model to manage or expose hidden reasoning; it
# only ever asks for the final block.
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM_INTRO = """\
You are an expert CTL2 (CloverDX transformation language) code reviewer.

Review the candidate CTL2 code against:
1. The review rules inside <REVIEW_RULES>.
2. The CTL2 reference inside <CTL2_REFERENCE>.
3. The component contract inside <COMPONENT_CONTRACT> (if present).
4. The original task requirements supplied in the user message.
5. The input/output metadata supplied in the user message.

Analyze carefully before answering, but return only the final review block.
Do not include scratch work, intermediate analysis, uncertainty notes,
self-corrections, or reasoning process in the response.
"""

_REVIEW_RULES = """\
## Final-answer discipline
Return only the final ISSUES/SUGGESTIONS/VERDICT block below, in the exact
format shown. Do not include scratch work, intermediate analysis, step-by-step
reasoning, uncertainty notes, self-corrections, or commentary outside the
block.

If a suspected concern does not fully satisfy the evidence discipline below,
omit it entirely from your answer — there is no need to mention or retract a
rejected concern.

## Output format
-------
ISSUES:
  [severity] Description   (severity is ERROR, WARNING, or INFO)
  ...

SUGGESTIONS:
  - improvement hint
  - improvement hint

VERDICT: PASS | FAIL
  (FAIL if any ERROR-severity issue is found; PASS otherwise)

The SUGGESTIONS section is entirely optional — if you have no improvement hints,
omit the whole "SUGGESTIONS:" heading and its bullets. Never write a placeholder
bullet like "no suggestions" or "optional improvement hints" — either give a real,
concrete hint or leave the section out completely.

If no issues are found respond with just:
  ISSUES: none
  VERDICT: PASS
-------

Each issue line must be a single, final, decisive sentence — a plain
statement of the problem, not a narration of how you arrived at it.

## Severity guide
- ERROR: the code will not compile/run, violates a stated requirement, or
  violates the component's execution contract (e.g. reading $in.0 inside a
  DENORMALIZER's transform()).
- WARNING: the code likely works for common cases but carries a real risk
  (missing null guard on a nullable field, fragile assumption, unhandled
  edge case implied by the prompt).
- INFO: style / clarity observations that do not affect correctness.

Only flag what the prompt, metadata, or CTL2 semantics actually demonstrate —
never what you merely suspect. Do not penalise missing explanatory prose;
the expected deliverable is correct code.
"""

_NULL_HANDLING_NOTE = """\

## Null-handling and metadata
Whether a field can carry null is determined by its metadata declaration:
- Field with NO `nullable` attribute, or `nullable="true"` → the field CAN be null.
  Assigning it straight through, or guarding it with `nvl()`/`isnull()`, are BOTH
  correct — neither is a defect.
- Field with `nullable="false"` → the graph enforces non-null at runtime; null cannot
  legitimately reach the CTL. A null guard here is harmless but unnecessary — do not
  require one.

Special case — EXT_HASH_JOIN LEFT OUTER JOIN: when the slave (port 1) has no matching
record, ALL `$in.1.*` fields are null at runtime, regardless of what the slave metadata
declares as `nullable`.

### When a missing null guard is (and is NOT) an issue
Only flag a missing null guard as an issue when BOTH of the following hold:
  - The field CAN be null (no `nullable="false"` on the source, or a LEFT OUTER JOIN
    slave field), AND
  - The user prompt EXPLICITLY states required behavior for null/missing values
    (e.g. "default to 0", "empty string if missing", "skip null records") that the
    candidate does not implement, OR the target output field is declared
    `nullable="false"` so a null assignment would violate the schema.
Do NOT flag a missing null guard just because a field is nullable in the abstract —
propagating null straight through to another nullable field is valid, idiomatic CTL2
and must never be reported as an issue, ERROR, or WARNING.

`nvl(x, default)` ≡ `isnull(x) ? default : x` — do not penalise either form.
"""

_NUMERIC_WIDENING_NOTE = """\

## Numeric widening (auto-upcasting) — MANDATORY pre-flight check
CTL2 has ONE exception to "no implicit conversions": automatic widening along
this rank order (narrowest to widest):

    RANK 1 = integer   RANK 2 = long   RANK 3 = number   RANK 4 = decimal

A value at a LOWER rank is silently promoted to a HIGHER rank wherever a
higher-rank type is expected — mixed-type arithmetic, assignment/output-field
assignment, ternary branch unification, and passing an argument to a function
that documents a higher-rank parameter type. Going from a HIGHER rank to a
LOWER one is NEVER implicit and needs an explicit, documented conversion
function (e.g. `decimal2double`, `decimal2integer`, `double2integer`).

**CTL2's `number`/`decimal` ranking is the OPPOSITE of what Java, C#, Python,
and most other languages train you to expect — do not import that instinct
here.** In those languages, a fixed-point/arbitrary-precision decimal type is
usually treated as the "safer, more specific" type that a floating `double`
must be explicitly, riskily narrowed into — so `double` -> `decimal` looks
like it should need an explicit, precision-losing conversion. CTL2 does NOT
work that way: `decimal` is CTL2's fixed-precision arbitrary-scale type and
sits at the WIDEST end of the chain, above `number` (an ordinary 64-bit
double). So in CTL2, `number` -> `decimal` is WIDENING (automatic, safe,
correct), and `decimal` -> `number` is the NARROWING direction that needs an
explicit function (`decimal2double`). If you catch yourself thinking "this
returns `number` but the field is `decimal`, so it needs an explicit
conversion" — that thought is importing the Java/C#/Python intuition and IS
WRONG for CTL2. `number` -> `decimal` needs nothing. Only `decimal` ->
`number` does.

YOU MUST RUN THIS EXACT PROCEDURE before writing ANY issue that claims a
numeric type mismatch, "no implicit conversion", "narrows ... into", or
similar — for EVERY such candidate issue, in this order:

  STEP 1. Write down the SOURCE value's concrete type and the TARGET's
          concrete type (the two sides of the assignment/argument/branch/
          operator you are questioning).
  STEP 2. If the source value is itself the result of a call to a GENERIC
          function (signature written with `T`, e.g. `T round(T, integer
          precision)`, `T abs(T)`): resolve `T` from the type of the argument
          ACTUALLY PASSED IN THIS CALL — never from the target field's type,
          never from a different overload of the same function name.
          Example: `round(numberVar, 2)` -> T=number -> returns `number`,
          regardless of what field the result is later assigned to.
  STEP 3. Look up both ranks: SOURCE_RANK, TARGET_RANK from the table above.
          (Only `integer`/`long`/`number`/`decimal` have a rank. Anything
          else — `byte`, `string`, `variant`, `boolean`, etc. — is a
          different, non-numeric type and this table does not apply; a
          mismatch there is judged on its own documented rules, not this one.)
  STEP 4. If SOURCE_RANK <= TARGET_RANK: this is valid widening. STOP — do
          NOT report an issue, no matter how the source value was produced
          (plain variable, arithmetic, ternary, or the return value of ANY
          function, generic or not, that already ran a narrowing conversion
          earlier in the same expression).
  STEP 5. If SOURCE_RANK > TARGET_RANK: this is narrowing. Only NOW check
          whether the code already calls a real, documented narrowing
          conversion function to bridge that exact gap. If yes, no issue. If
          no, this is a legitimate ERROR — report it.

Worked examples (apply the 5 steps above to each; do not pattern-match on
surface wording alone):
  - `decimalSum / integerCount` -> integer(1) <= decimal(4) -> valid, NOT an issue.
  - `decimal x = someNumberVar;` -> number(3) <= decimal(4) -> valid, NOT an issue.
  - `cond ? decimalVal : integerVal` -> integer(1) <= decimal(4) -> valid, NOT an issue.
  - `decimal avg = decimal2double(round(sum / count, 2));` -> the FINAL value
    assigned is the `number` returned by `decimal2double` -> number(3) <=
    decimal(4) -> valid, NOT an issue (the redundant round-trip through
    `decimal2double` may be a style SUGGESTION, never an ISSUE).
  - `decimal x = round(numberVar, 2);` -> per STEP 2, `round` returns
    `number` here -> number(3) <= decimal(4) -> valid, NOT an issue.
  - `decimal x = cast(someVariant, number);` -> `cast` returns `number` here
    -> number(3) <= decimal(4) -> valid, NOT an issue (the `cast()` call
    itself is fine — variant to strong-type is exactly what it's for).
  - `integer x = someDecimalVar;` -> decimal(4) > integer(1) -> narrowing; a
    real ERROR unless the code calls a documented decimal->integer function.

Do NOT reason from "this function's signature/return type differs from the
target field's declared type" alone — that is exactly the reasoning that
produces a false positive here. Rank comparison (steps 3-5) is the only valid
basis for a numeric-type ISSUE.
"""

_EVIDENCE_DISCIPLINE_NOTE = """\

## Evidence discipline — do not hallucinate issues
Every issue you report MUST be traceable to one of:
  1. A requirement explicitly stated in the user prompt (a field, rule, format, or
     value the prompt actually asks for), or
  2. The field/record metadata (an explicit `nullable`, `type`, or similar attribute), or
  3. The DOCUMENTED behavior of a specific built-in CTL2 function, found in the
     CTL2 reference.
If you cannot point to one of these three, do not report the issue.

Before flagging anything about how a function behaves on null input:
  - Find that exact function's signature in the reference, e.g.
    `contains(string, string substring)` has TWO positional parameters. Map each
    argument in the ACTUAL CALL to its position in that signature — the 1st argument
    written in the code is the 1st parameter, the 2nd argument written is the 2nd
    parameter. Do not swap them and do not guess which one "must" be the null one.
  - A quoted string literal (e.g. `"urgent"`, `"@company.com"`) can NEVER be null —
    if that is the argument the reference calls null-unsafe, there is no bug.
  - Example: `contains(lowerCase($in.0.subject), "urgent")` — argument 1 is
    `lowerCase($in.0.subject)` (maps to the `string` "input" parameter: nullable, but
    `lowerCase(null)` → `null`, and per the reference `contains` returns `false` when
    its `input` parameter is null — not an error). Argument 2 is the literal
    `"urgent"` (maps to the `substring` parameter, which the reference says fails on
    null — but a literal is never null, so this is also not an error). Nothing here
    is a defect.
  - Many CTL2 string/list functions return `null` or `false` on a null input — they
    do NOT throw. Never assume a function throws on null without the reference
    explicitly saying so for that exact parameter position.
  - If the reference does not document the function, or you are not fully certain,
    do NOT report it as an ERROR or WARNING — omit it entirely.

## Do not write the fix
This review is shown to the developer as feedback to act on themselves, not as a
patch to apply directly. This applies EQUALLY to ISSUES descriptions and to
SUGGESTIONS — suggestions are a common place where an exact fix accidentally slips
in disguised as "advice".
  - State the problem and the required behavior in plain language only.
  - You may name a field or function ALREADY PRESENT in the candidate code, to point
    at where the problem is. NEVER name the corrected function, expression, or
    argument that would solve it — that is the developer's job to work out.
  - If you catch yourself about to write a backtick-quoted function call or any
    CTL2 syntax as part of the fix, stop and rephrase it as a plain-language
    description of the missing/wrong behavior instead.
  - The one exception is the "Optimization hints" list below — those exist
    specifically to name a simpler built-in, on code that is already correct.

  BAD  suggestion (hands over the exact fix): "Use `length(v)` to get the element count."
  GOOD suggestion (describes the gap only):   "Recompute the count from the parsed
                                                value itself, not from one of its
                                                elements."

  BAD  issue (hands over the exact fix): "Missing null guard for `age` — use `nvl($in.0.age, 0)`."
  GOOD issue (describes the gap only):   "The `age` field is nullable but is assigned
                                           straight through, and the prompt asks for a
                                           default value when a field is missing."
"""

# Recognized "this works, but here's the idiomatic built-in for it" patterns —
# pure style/efficiency polish on code that is already CORRECT. Unlike ordinary
# SUGGESTIONS (see "Do not write the fix" above), naming the exact simpler form
# is the whole point here, so these are deliberately exempt from that rule.
# Extend this list as more patterns are identified; each entry is
# (pattern-as-written-in-code, simpler equivalent).
_SIMPLIFICATION_PATTERNS: list[tuple[str, str]] = [
    (
        '`isnull(x) || x == ""` (or `x == "" || isnull(x)`)',
        '`isEmpty(x)`',
    ),
    (
        '`isnull(x) || trim(x) == ""` (or the reverse order)',
        '`isBlank(x)`',
    ),
]


def _build_optimization_hints_note() -> str:
    lines = [
        "",
        "## Optimization hints — a special category of SUGGESTIONS",
        "Some SUGGESTIONS are pure style/efficiency polish on code that is already",
        "CORRECT — not a fix for a flagged issue. This is a narrow, deliberate exception",
        "to \"Do not write the fix\" above: for these specific, recognized patterns only,",
        "name the exact simpler built-in in your suggestion — that IS the hint. This",
        "exception does NOT extend to fixing a real ISSUE; those must still withhold",
        "the fix as described above.",
        "",
        "Rules for using this list:",
        "  - Only offer one of these when the candidate code actually matches the",
        "    described pattern (same logic, any variable name) — never fabricate a",
        "    similar-looking substitution that isn't in this list.",
        "  - These are always SUGGESTIONS, never ISSUES. They carry no severity, are",
        "    never ERROR/WARNING/INFO, and must NEVER affect VERDICT — the code being",
        "    suggested about is already correct.",
        "  - Do not invent new \"simpler form\" patterns beyond what's listed here.",
        "",
        "Known patterns:",
    ]
    for pattern, simpler in _SIMPLIFICATION_PATTERNS:
        lines.append(f"  - {pattern} → simpler as {simpler}")
    return "\n".join(lines) + "\n"


_OPTIMIZATION_HINTS_NOTE = _build_optimization_hints_note()

# Everything stable that belongs inside <REVIEW_RULES> — kept as one constant
# so it stays byte-identical across every review() call regardless of
# component type, maximizing the shared cache prefix.
_REVIEW_RULES_FULL = (
    _REVIEW_RULES + _EVIDENCE_DISCIPLINE_NOTE + _NULL_HANDLING_NOTE
    + _NUMERIC_WIDENING_NOTE + _OPTIMIZATION_HINTS_NOTE
)

# Final, stable hardening check — asks the model to verify its own OUTPUT
# before returning, not to manage any hidden reasoning process. Placed last
# in the system prompt (after the variable component contract) for recency,
# per the mini-spec's recommendation; it's a small, deliberate cache-locality
# trade-off since it's still stable text.
_FINAL_VERIFICATION_NOTE = """

## Before returning
Verify that your response:
1. Contains no reasoning process, scratch work, or narration of how you checked things.
2. Contains no CTL2 patch code (except the "Optimization hints" exception above).
3. Contains only issues supported by the task, metadata, component contract, or CTL2 reference.
4. Uses VERDICT: FAIL if any ERROR exists, otherwise VERDICT: PASS.
"""

_REVIEW_USER = """\
Review the MUT task output below.

<MUT_TASK>
Component type: {component_type}

<ORIGINAL_USER_PROMPT>
{prompt}
</ORIGINAL_USER_PROMPT>

<MUT_CANDIDATE_CTL>
```
{candidate}
```
</MUT_CANDIDATE_CTL>
</MUT_TASK>
{prior_issues_block}
---
Reminder: only report an issue if you can point to an explicit prompt requirement, a
metadata attribute, or documented function behavior from the CTL2 reference. Do not
guess about null behavior — check the function's documented behavior first. Do not
include any CTL2 code in your ISSUES findings or in ordinary SUGGESTIONS — the one
exception is the "Optimization hints" list: if the candidate code matches one of
those exact patterns, add that SUGGESTION naming the simpler built-in. Respond with
ONLY the final ISSUES/SUGGESTIONS/VERDICT block — no other text.
"""

# Appended to _REVIEW_USER only when the caller passes prior_issues (i.e. this
# candidate is a revision made in response to an earlier review). Each
# review() call otherwise has no memory of an earlier round — an issue raised
# then, but never actually fixed, can simply fail to come up again when the
# judge looks at the new code with fresh eyes. This asks the judge to
# explicitly re-check each carried-over issue against the CURRENT candidate
# above, so a still-present problem is reported again instead of silently
# dropped, while a genuinely fixed one is not.
_PRIOR_ISSUES_BLOCK = """
<PRIOR_ROUND_ISSUES>
This candidate is a revision submitted after the developer received the review
below on an EARLIER version of the code (not the version above):
{prior_issues_text}

For each issue listed above: check whether the CURRENT candidate (in
<MUT_CANDIDATE_CTL> above) still has that exact problem.
  - Still present (even if surrounding code changed) -> report it again in your
    ISSUES section, same as any other finding.
  - Actually fixed in the current candidate -> do not mention it.
Do not let this list limit your review — also report any new issue you find in
the current candidate that isn't on this list, using the same rules as always.
</PRIOR_ROUND_ISSUES>
"""


# ---------------------------------------------------------------------------
# Prompts — fix mode
# ---------------------------------------------------------------------------

_FIX_SYSTEM_BASE = """\
You are an expert CTL2 (CloverDX transformation language) developer.

You are given a task, a candidate CTL2 completion that has known issues, and
a code review listing those issues. Rewrite the code so it fully satisfies
the task and resolves every ERROR and WARNING issue listed, while preserving
whatever in the candidate was already correct.

Before applying a listed issue, sanity-check it against the metadata and the
documented behavior of any function it mentions (see the CTL2 reference).
If a listed issue does not actually hold up, leave that part of the code
as-is rather than "fixing" something that was not broken.

Analyze carefully before answering. Return only the corrected CTL2 code in a
single fenced code block — no explanation, no restated issues, no scratch
work, uncertainty notes, or prose before or after the code.
"""

_FIX_USER = """\
<MUT_TASK_TO_FIX>
Component type: {component_type}

<ORIGINAL_USER_PROMPT>
{prompt}
</ORIGINAL_USER_PROMPT>

<MUT_CANDIDATE_CTL>
```
{candidate}
```
</MUT_CANDIDATE_CTL>

<CODE_REVIEW>
{review_text}
</CODE_REVIEW>
</MUT_TASK_TO_FIX>
"""


# ---------------------------------------------------------------------------
# Prompts — tweak mode (--tweak)
#
# Rewrites an SFT example's prompt into a different-but-structurally-similar
# task before it's ever shown to the MUT — new business domain, new field
# names/types, and a genuinely different (not just renamed) business rule —
# so the MUT is tested on something it wasn't trained on verbatim.
# ---------------------------------------------------------------------------

_TWEAK_SYSTEM = """\
You are a CTL2 (CloverDX transformation language) practice-task writer.

You are given an example CTL2 code-generation task: a component type, an
input/output metadata block, and a business-logic instruction. Write a NEW
practice task of the same shape and difficulty, set in a different business
scenario — this gives learners fresh material to practice the same skill on,
instead of everyone working from one fixed example.

## What to change
1. Business domain: pick a different scenario unrelated to the original (e.g.
   if the original is about customer orders, move to something like sensor
   telemetry, warehouse inventory, employee shifts, flight bookings, etc.).
2. Field names: every field gets a new name fitting the new domain. Do not
   reuse the original field names.
3. Field types / nullability: vary at least some field types and nullable
   attributes from the original (e.g. swap integer <-> long, add or remove
   nullable="false", change a string to decimal where it still makes sense).
4. Business logic: rewrite the instruction to use the new field names, AND
   make a genuine small change to what the transformation must do — a
   different condition, threshold, derived value, or edge case — not just a
   find-and-replace of names into the same logic. The correct code for the
   new task must differ from the correct code for the original task.

## What to keep
- Component type: the new task is for the exact same CTL2 component type as
  the original ({component_type}) — do not change which component this is
  for, only what it does.
- Overall shape: roughly the same number of input/output fields, the same
  `<Metadata>` XML structure and phrasing style as the original (e.g. "Given
  Input Metadata on Port 0: ... And Output Metadata on Port 0: ... Write a
  ... that ..."), and about the same difficulty level.

## Valid CTL2 field types
integer, long, number, decimal, string, boolean, date, byte, cbyte

Analyze the original task, then reply with ONLY your new practice task as
plain text, wrapped EXACTLY between these markers and nothing else — no
explanation, notes, or commentary outside them:
<<<TWEAKED_PROMPT_START>>>
(the full new prompt text, including its <Metadata> blocks and instruction)
<<<TWEAKED_PROMPT_END>>>
"""

_TWEAK_USER = """\
## Original task (component type: {component_type})

{original_prompt}

---
Rewrite this into a new task per the rules above. Remember: different domain,
different field names, at least one changed field type/nullability, and a
genuinely different (not just renamed) business rule — while staying the same
component type and roughly the same shape/difficulty.
"""


# ---------------------------------------------------------------------------
# Prompts — numeric-claim fact-check (second-opinion, cheap model)
#
# A deliberately narrow, single-purpose check: does THIS ONE reported issue
# correctly apply CTL2's numeric widening chain? Kept short and self-contained
# (no CTL2_REFERENCE, no component contract) since it only needs the widening
# rule, not the whole language — this is what makes routing it to a cheap/
# local model practical instead of spending another full judge call on it.
# ---------------------------------------------------------------------------

_NUMERIC_CLAIM_CHECK_SYSTEM = """\
You are a narrow CTL2 (CloverDX transformation language) fact-checker,
specialized in ONE rule: numeric type widening.

CTL2 automatically widens (upcasts) a narrower numeric type to a wider one,
along this chain (narrowest to widest):

    integer  ->  long  ->  number  ->  decimal

Widening is AUTOMATIC and needs no conversion: in arithmetic, assignment
(including into an output field), ternary branches, and function arguments.
This holds no matter how the narrower-side value was produced (a plain
variable, an arithmetic expression, or the return value of any function,
including one that already performed an explicit narrowing conversion
earlier in the same expression).

Narrowing — the reverse direction (e.g. `decimal` -> `number`, `number` ->
`long`, `long` -> `integer`, or skipping steps backward) — is NEVER implicit
and DOES require an explicit, real, documented conversion function.

Note: `decimal` sits at the WIDEST end of this chain, above `number` — this
is the opposite of the usual Java/C#/Python intuition that a fixed-point
decimal is "more specific" than a floating double and must be explicitly
narrowed into. In CTL2, `number` -> `decimal` needs nothing; only `decimal`
-> `number` does.

You will be given ONE issue a code reviewer reported about a CTL2 candidate,
plus that candidate's code. Decide whether the issue correctly applies the
widening chain above, or whether it has the direction backwards / invents a
conversion requirement that doesn't exist.

If the issue is not actually about numeric type widening/narrowing at all
(e.g. it's about null-handling, component contracts, business logic, or a
non-numeric type like `byte`/`string`/`variant`), that is outside what you
check — answer VALID; do not judge it.

Respond with EXACTLY one word, nothing else: VALID or HALLUCINATION.
"""

_NUMERIC_CLAIM_CHECK_USER = """\
<CANDIDATE_CODE>
```
{code}
```
</CANDIDATE_CODE>

<REPORTED_ISSUE>
{description}
</REPORTED_ISSUE>

Apply the widening chain to this specific claim. Respond with EXACTLY one
word: VALID or HALLUCINATION.
"""


def _component_note(component_type: str) -> str:
    key = _normalize_component_type(component_type)
    section = _COMPONENT_CONTRACTS.get(key, "")
    if not section:
        return ""
    return (
        "The following is the verified CTL2 contract for this component type "
        "(entry points, lifecycle, port access, return-code semantics, canonical "
        "mistakes). Treat it as ground truth — it takes precedence over general "
        "assumptions about CTL2 components.\n\n"
        + section
    )


def _build_review_system(component_type: str) -> str:
    """Assemble the review system prompt with the stable content first (rules,
    then the large CTL2 reference) and the variable, per-example component
    contract last — maximizes the byte-identical shared prefix across calls
    for prompt-cache reuse. No section here manages hidden reasoning; the
    hardening note only asks the model to verify its own final output."""
    parts = [_REVIEW_SYSTEM_INTRO, f"\n<REVIEW_RULES>\n{_REVIEW_RULES_FULL}</REVIEW_RULES>\n"]
    if _CTL2_REFERENCE:
        parts.append(f"\n<CTL2_REFERENCE>\n{_CTL2_REFERENCE}\n</CTL2_REFERENCE>\n")
    note = _component_note(component_type)
    if note:
        parts.append(f"\n<COMPONENT_CONTRACT>\n{note}\n</COMPONENT_CONTRACT>\n")
    parts.append(_FINAL_VERIFICATION_NOTE)
    return "".join(parts)


def _build_fix_system(component_type: str) -> str:
    parts = [_FIX_SYSTEM_BASE, _NULL_HANDLING_NOTE, _NUMERIC_WIDENING_NOTE]
    if _CTL2_REFERENCE:
        parts.append(f"\n<CTL2_REFERENCE>\n{_CTL2_REFERENCE}\n</CTL2_REFERENCE>\n")
    note = _component_note(component_type)
    if note:
        parts.append(f"\n<COMPONENT_CONTRACT>\n{note}\n</COMPONENT_CONTRACT>\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_ISSUE_LINE_RE = re.compile(r"\[(ERROR|WARNING|INFO)\]\s*(.+)", re.IGNORECASE)
_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)
_SECTION_RE = re.compile(r"^\s*(ISSUES|SUGGESTIONS|VERDICT)\s*:", re.IGNORECASE)

# Defensive cleanup for models with a native, visible <think>...</think>
# channel (unrelated to any tool we ask for — some open-weight "reasoning"
# models emit this natively in plain text regardless of instructions).
_THINK_RE = re.compile(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", re.IGNORECASE)

# Defensive fallback only — nothing in the prompts asks for this marker, but
# if a model spontaneously prefixes its answer with commentary anyway, this
# still lets us recover the tail. A harmless no-op when absent.
_FINAL_ANSWER_RE = re.compile(r"=+\s*FINAL\s+ANSWER\s*=+", re.IGNORECASE)


def _extract_final_answer(raw: str) -> str:
    parts = _FINAL_ANSWER_RE.split(raw)
    return parts[-1].strip() if len(parts) > 1 else raw.strip()


# `{2,}` (not a literal `<<<`/`>>>`) because the local tweak model has been
# observed dropping a bracket on the closing marker (e.g. "...END>>" instead
# of "...END>>>") — a strict 3-bracket match would miss that and fall through
# to _extract_final_answer(), which leaks both raw markers into the "tweaked"
# prompt verbatim.
_TWEAK_MARKER_RE = re.compile(
    r"<{2,}\s*TWEAKED_PROMPT_START\s*>{2,}(.*?)<{2,}\s*TWEAKED_PROMPT_END\s*>{2,}",
    re.DOTALL | re.IGNORECASE,
)

# Fallback for a start marker with a missing/malformed end marker (e.g. cut
# off by max_tokens truncation) -- strips the marker tokens actually present
# instead of leaking them, rather than returning the whole raw response.
_TWEAK_START_RE = re.compile(r"<{2,}\s*TWEAKED_PROMPT_START\s*>{2,}", re.IGNORECASE)
_TWEAK_END_RE = re.compile(r"<{2,}\s*TWEAKED_PROMPT_END\s*>{1,}", re.IGNORECASE)


def _extract_tweaked_prompt(raw: str) -> str:
    m = _TWEAK_MARKER_RE.search(raw)
    if m:
        return m.group(1).strip()
    start_m = _TWEAK_START_RE.search(raw)
    if start_m:
        tail = _TWEAK_END_RE.sub("", raw[start_m.end():])
        return tail.strip()
    return _extract_final_answer(raw)  # fallback if the model skipped the markers entirely


# Safety net for models that narrate their own verification instead of
# writing a clean final line (e.g. "however, this turns out fine — no issue
# here") — an issue whose own text talks itself out of being an issue is
# dropped rather than trusted at face value.
_RETRACTION_RE = re.compile(
    r"\b(no error here|not an issue|no issue here|not a bug|no failure|"
    r"is not a problem|no real issue|not a real issue|no defect|"
    r"this is (?:not an issue|fine|valid|safe|acceptable)|"
    r"no issue|not a failure|"
    r"but wait|re-?checking|re-?evaluating|reconsidering|"
    r"^omit\b|\bomit(?:ted)? it\b|must not flag|cannot confirm (?:a )?defect)\b",
    re.IGNORECASE,
)

# gpt-5.4 has a confirmed, sticky mistake around CTL2's numeric widening
# chain (integer -> long -> number -> decimal) — most often calling a
# `number` value assigned into a `decimal` field a "narrowing" that needs an
# explicit conversion, when it's actually automatic widening. Three rounds of
# prompt clarification (plain rule, mandatory checklist, named Java/C#/Python
# counter-intuition) reduced but did not eliminate it, and a regex-based text
# filter proved to be an unwinnable arms race — the model kept finding new
# phrasings that described the identical false claim without matching any
# fixed set of trigger words. Instead of matching text, ANY issue that
# mentions a numeric type is sent to a second, independent, cheap model (the
# local tweak_llm) with a short, focused prompt asking it to fact-check the
# specific claim against the widening chain — see check_numeric_claim() below
# and review()'s numeric_verifier parameter. This only needs to catch
# candidates broadly; the verifier call itself judges correctness, so a
# harmless false-trigger here just costs one extra cheap call, not a wrong
# drop.
_NUMERIC_TYPE_MENTION_RE = re.compile(
    r"\b(?:integer|long|number|decimal|double)\b", re.IGNORECASE,
)


def _mentions_numeric_type(description: str) -> bool:
    return bool(_NUMERIC_TYPE_MENTION_RE.search(description))


# The format spec's own example text ("- improvement hint") occasionally gets
# echoed back verbatim as a placeholder instead of a real suggestion (or omitted
# entirely) — drop lines that are just the placeholder/none-marker, not content.
_PLACEHOLDER_SUGGESTION_RE = re.compile(
    r"^(?:optional improvement hints?|improvement hints?|no suggestions?|none|n/?a)"
    r"\s*(?:\(.*\))?\.?$",
    re.IGNORECASE,
)


def _parse_review(raw: str) -> Optional[ReviewResult]:
    """Parse the ISSUES/SUGGESTIONS/VERDICT format. Returns None if the
    response is too malformed to contain either a VERDICT or an ISSUES
    section (signals the caller to retry with a stricter instruction)."""
    cleaned = _THINK_RE.sub("", raw).strip()
    cleaned = _extract_final_answer(cleaned)

    vm = _VERDICT_RE.search(cleaned)
    has_issues_section = bool(re.search(r"ISSUES\s*:", cleaned, re.IGNORECASE))
    if vm is None and not has_issues_section:
        return None

    issues: list[ReviewIssue] = []
    suggestions: list[str] = []
    section: Optional[str] = None
    for line in cleaned.splitlines():
        header = _SECTION_RE.match(line)
        if header:
            section = header.group(1).upper()
            continue
        if section == "ISSUES":
            m = _ISSUE_LINE_RE.search(line)
            if m:
                description = m.group(2).strip()
                if _RETRACTION_RE.search(description):
                    continue  # model talked itself out of this one — drop it
                issues.append(ReviewIssue(severity=m.group(1).upper(), description=description))
        elif section == "SUGGESTIONS":
            stripped = line.strip()
            if stripped.startswith(("-", "*")):
                stripped = stripped.lstrip("-* ").strip()
                if stripped and not _PLACEHOLDER_SUGGESTION_RE.match(stripped):
                    suggestions.append(stripped)
            elif stripped and not _PLACEHOLDER_SUGGESTION_RE.match(stripped):
                suggestions.append(stripped)

    # Enforce the stated rule ourselves rather than trusting the model's own
    # VERDICT line — models occasionally tag an issue [ERROR] and then still
    # write "VERDICT: PASS". An ERROR-severity issue always means FAIL.
    if any(i.severity == "ERROR" for i in issues):
        verdict = "FAIL"
    elif vm is not None:
        verdict = vm.group(1).upper()
    else:
        verdict = "PASS"

    return ReviewResult(
        issues=issues,
        suggestions=suggestions,
        verdict=verdict,
        raw_text=cleaned,
        has_error=any(i.severity == "ERROR" for i in issues),
        has_warning=any(i.severity == "WARNING" for i in issues),
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def _resolve_key(configured: Optional[str], env_name: str) -> Optional[str]:
    if configured and not configured.startswith("${"):
        return configured
    return os.environ.get(env_name)


@dataclass
class UsageStats:
    """Cumulative token accounting across all judge calls, for efficiency
    reporting — input vs. cached (prompt-cache reuse) vs. output tokens.
    cached_tokens is a subset of input_tokens, not additional to it."""
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.input_tokens if self.input_tokens else 0.0

    def add(self, input_tokens: int, cached_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.cached_tokens += cached_tokens
        self.output_tokens += output_tokens


# Backoff between retries after OpenAI's moderation classifier flags a request
# (confirmed non-deterministic: identical request, different outcome on repeat,
# with the flag rate escalating under sustained request volume). Short waits
# first, then progressively longer ones to let whatever volume/rate signal
# triggered it cool off. One entry per gap, so len(...) + 1 = total attempts.
_MODERATION_BACKOFF_S = [7.0, 15.0, 30.0, 60.0, 90.0]


class ReviewJudgeClient:

    def __init__(self, cfg: dict, log_file: Optional[TextIO] = None):
        self._cfg = cfg
        self._llm = None
        self.usage = UsageStats()
        # Newer OpenAI models (gpt-5.x) require max_completion_tokens instead of
        # max_tokens, and some reject a non-default temperature. Auto-detected on
        # first call and cached so we don't eat a failed round-trip every time.
        self._openai_token_param: Optional[str] = None
        self._openai_supports_temperature: bool = True
        # Optional run-log file — receives full, untruncated diagnostics
        # (unparseable raw responses, flagged prompts) that console output
        # only shows a short preview of.
        self._log_file = log_file

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        provider = self._cfg.get("provider", "anthropic")
        if provider == "anthropic":
            import anthropic
            key = _resolve_key(self._cfg.get("api_key"), "ANTHROPIC_API_KEY")
            self._llm = anthropic.Anthropic(api_key=key)
        elif provider == "openai":
            from openai import OpenAI
            key = _resolve_key(self._cfg.get("api_key"), "OPENAI_API_KEY")
            self._llm = OpenAI(
                api_key=key,
                base_url=self._cfg.get("base_url"),
                timeout=self._cfg.get("request_timeout_s", 180),
            )
        else:
            raise ValueError(f"Unknown judge provider: {provider!r}")
        return self._llm

    def _call(self, system: str, user_message: str) -> str:
        provider = self._cfg.get("provider", "anthropic")
        if provider == "anthropic":
            return self._call_anthropic(system, user_message)
        elif provider == "openai":
            return self._call_openai(system, user_message)
        else:
            raise ValueError(f"Unknown judge provider: {provider!r}")

    def _call_anthropic(self, system: str, user_message: str) -> str:
        llm = self._get_llm()
        model = self._cfg.get("model", "claude-opus-4-20250514")
        max_tokens = self._cfg.get("max_tokens", 2048)
        resp = llm.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        u = resp.usage
        # cache_read_input_tokens is the portion of input_tokens served from
        # Anthropic's prompt cache — a subset of input_tokens, not additional.
        self.usage.add(
            input_tokens=u.input_tokens,
            cached_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            output_tokens=u.output_tokens,
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    def _create_openai_chat_completion(self, llm, kwargs: dict, max_flag_retries: Optional[int] = None):
        """Call chat.completions.create(), transparently working around two
        provider quirks: (1) newer OpenAI models need max_completion_tokens
        instead of max_tokens, or reject a non-default temperature — detected
        once and cached on self; (2) OpenAI's moderation classifier can flag a
        completely benign prompt intermittently (confirmed: identical request,
        different outcome on repeat) — retrying the identical request a few
        times resolves it more often than not."""
        from openai import BadRequestError

        if max_flag_retries is None:
            max_flag_retries = len(_MODERATION_BACKOFF_S) + 1
        max_tokens_value = kwargs.get(self._openai_token_param or "max_tokens")
        for attempt in range(max_flag_retries):
            try:
                return llm.chat.completions.create(**kwargs)
            except BadRequestError as e:
                msg = str(e)
                if "max_completion_tokens" in msg and self._openai_token_param != "max_completion_tokens":
                    self._openai_token_param = "max_completion_tokens"
                    kwargs.pop("max_tokens", None)
                    kwargs["max_completion_tokens"] = max_tokens_value
                    continue
                if "temperature" in msg and "temperature" in kwargs:
                    self._openai_supports_temperature = False
                    kwargs.pop("temperature")
                    continue
                if "invalid_prompt" in msg or "flagged as potentially violating" in msg:
                    flagged_msgs = "--- START flagged messages ---\n" + "\n\n".join(
                        f"{m['role']}: {m['content']}"
                        for m in kwargs["messages"]
                    ) + "\n--- END flagged messages ---"
                    self._log_full(
                        f"[review-judge] Request flagged by moderation "
                        f"(attempt {attempt + 1}/{max_flag_retries}):\n{msg}\n\n{flagged_msgs}\n"
                    )
                    if attempt < max_flag_retries - 1:
                        wait_s = _MODERATION_BACKOFF_S[min(attempt, len(_MODERATION_BACKOFF_S) - 1)]
                        print(f"[review-judge] Request flagged by moderation "
                              f"(attempt {attempt + 1}/{max_flag_retries}) — waiting {wait_s:.0f}s "
                              f"then retrying (see run log for the full flagged prompt) …")
                        time.sleep(wait_s)
                        continue
                raise
        raise RuntimeError("unreachable")  # loop always returns or raises

    def _call_openai(self, system: str, user_message: str) -> str:
        llm = self._get_llm()
        model = self._cfg.get("model", "claude-opus-4-20250514")
        max_tokens = self._cfg.get("max_tokens", 2048)
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }
        kwargs[self._openai_token_param or "max_tokens"] = max_tokens
        if self._openai_supports_temperature:
            kwargs["temperature"] = 0.0

        resp = self._create_openai_chat_completion(llm, kwargs)

        if resp.usage:
            u = resp.usage
            # prompt_tokens_details.cached_tokens is the portion of prompt_tokens
            # served from OpenAI's prompt cache — a subset, not additional. Local
            # / self-hosted servers (e.g. vLLM) often leave this null.
            details = getattr(u, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            self.usage.add(
                input_tokens=u.prompt_tokens,
                cached_tokens=cached or 0,
                output_tokens=u.completion_tokens,
            )
        return resp.choices[0].message.content or ""

    def _log_full(self, text: str) -> None:
        """Write full, untruncated diagnostic text to the run log file, if one
        is attached — independent of what the (deliberately shorter) console
        output shows."""
        if self._log_file:
            self._log_file.write(text if text.endswith("\n") else text + "\n")
            self._log_file.flush()

    def review(
        self,
        prompt: str,
        code: str,
        component_type: str = "",
        prior_issues: Optional[list[ReviewIssue]] = None,
        numeric_verifier: Optional["ReviewJudgeClient"] = None,
    ) -> Optional[ReviewResult]:
        """Review a candidate and return a ReviewResult, or None if the LLM
        consistently returns an unparseable response.

        prior_issues: issues found on an EARLIER version of this same code
        (e.g. review_1's issues, when reviewing the MUT's pass-2 revision).
        When given, the judge is asked to explicitly re-check each one against
        the current candidate and re-report it if still present — otherwise a
        real, unaddressed issue can simply fail to come up again in a later
        round's independent, fresh-eyes review.

        numeric_verifier: an independent ReviewJudgeClient (typically the
        cheap/local tweak_llm) used to fact-check every ISSUE that mentions a
        numeric type (integer/long/number/decimal/double) against CTL2's
        widening chain before it's kept. gpt-5.4 has a confirmed, sticky
        mistake here — see check_numeric_claim()'s docstring — that survived
        several rounds of prompt clarification and proved unfilterable by
        text pattern alone, since it kept rephrasing the same false claim in
        new ways. Routing each candidate issue to a second model for an
        independent judgment is robust to that in a way regex can't be."""
        effective_type = component_type or infer_component_type(code)
        review_system = _build_review_system(effective_type)
        prior_issues_block = ""
        if prior_issues:
            prior_issues_text = "\n".join(f"  [{i.severity}] {i.description}" for i in prior_issues)
            prior_issues_block = _PRIOR_ISSUES_BLOCK.format(prior_issues_text=prior_issues_text)
        user_msg = _REVIEW_USER.format(
            component_type=effective_type or "unknown",
            prompt=prompt,
            candidate=code,
            prior_issues_block=prior_issues_block,
        )

        max_retries = self._cfg.get("max_retries", 2)
        for attempt in range(max_retries):
            msg = user_msg
            if attempt > 0:
                msg += (
                    "\n\n**Respond with ONLY the ISSUES/SUGGESTIONS/VERDICT "
                    "format described above — no other text.**"
                )
            raw = self._call(review_system, msg)
            result = _parse_review(raw)
            if result is not None:
                if numeric_verifier is not None:
                    result = self._filter_numeric_hallucinations(result, code, numeric_verifier)
                return result
            print(f"[review-judge] Unparseable response on attempt {attempt + 1} "
                  f"({len(raw)} chars) — raw tail:")
            print("  " + raw[-500:].replace("\n", "\n  "))
            self._log_full(f"\n--- unparseable review response, attempt {attempt + 1} (full) ---\n{raw}\n")

        print("[review-judge] Could not parse review after retries — treating as FAIL")
        return None

    def _filter_numeric_hallucinations(
        self, result: ReviewResult, code: str, numeric_verifier: "ReviewJudgeClient",
    ) -> ReviewResult:
        """Drop any ISSUE that mentions a numeric type and that numeric_verifier
        judges to be a hallucination, then recompute verdict/has_error/
        has_warning from what's left — the same rule _parse_review() uses
        (any remaining ERROR -> FAIL, else PASS)."""
        kept: list[ReviewIssue] = []
        for issue in result.issues:
            if not _mentions_numeric_type(issue.description):
                kept.append(issue)
                continue
            try:
                valid = numeric_verifier.check_numeric_claim(issue.description, code)
            except Exception as e:
                self._log_full(f"[numeric-verifier] check raised ({e}) — keeping issue as-is: {issue.description}")
                kept.append(issue)  # fail open: an unrelated error shouldn't silently drop real signal
                continue
            if valid:
                kept.append(issue)
            else:
                self._log_full(f"[numeric-verifier] dropped as hallucination: [{issue.severity}] {issue.description}")
        if len(kept) == len(result.issues):
            return result
        return ReviewResult(
            issues=kept,
            suggestions=result.suggestions,
            verdict="FAIL" if any(i.severity == "ERROR" for i in kept) else "PASS",
            raw_text=result.raw_text,
            has_error=any(i.severity == "ERROR" for i in kept),
            has_warning=any(i.severity == "WARNING" for i in kept),
        )

    def check_numeric_claim(self, description: str, code: str) -> bool:
        """Fact-check ONE reported issue against CTL2's numeric widening
        chain (integer -> long -> number -> decimal) using THIS client's
        model (intended to be a cheap/local model, not the main judge).
        Returns True (keep) unless the model clearly says HALLUCINATION —
        an ambiguous or malformed response fails open (keeps the issue)
        rather than silently discarding real signal."""
        raw = self._call(
            _NUMERIC_CLAIM_CHECK_SYSTEM,
            _NUMERIC_CLAIM_CHECK_USER.format(code=code, description=description),
        )
        return "HALLUCINATION" not in raw.upper()

    def fix(
        self,
        prompt: str,
        code: str,
        review: ReviewResult,
        component_type: str = "",
    ) -> str:
        """Ask the judge to rewrite the code directly, resolving `review`'s findings."""
        effective_type = component_type or infer_component_type(code)
        fix_system = _build_fix_system(effective_type)
        user_msg = _FIX_USER.format(
            component_type=effective_type or "unknown",
            prompt=prompt,
            candidate=code,
            review_text=review.render(),
        )
        raw = self._call(fix_system, user_msg)
        # Defensive cleanup: strip anything before a stray "===FINAL ANSWER==="
        # marker if the model emits one unprompted, then extract just the
        # fenced code — covers models that ramble in prose right up to the
        # code fence despite the instructions. Re-wrap in a fence so the
        # stored assistant turn matches the MUT's own fenced style regardless
        # of what the judge model actually produced.
        code = normalize_ctl(_extract_final_answer(raw))
        return f"```ctl\n{code}\n```"

    def tweak(self, prompt: str, component_type: str = "") -> str:
        """Rewrite an SFT example's prompt into a different-but-structurally-
        similar task (new domain, new field names/types, a genuinely different
        business rule) so the MUT is tested on something it wasn't trained on
        verbatim. component_type is the type detected on the ORIGINAL prompt —
        passed in as the constraint the rewrite must preserve."""
        tweak_system = _TWEAK_SYSTEM.format(
            component_type=component_type or "(not explicitly stated — infer it from the prompt and keep it unchanged)"
        )
        user_msg = _TWEAK_USER.format(
            component_type=component_type or "unknown",
            original_prompt=prompt,
        )
        raw = self._call(tweak_system, user_msg)
        return _extract_tweaked_prompt(raw)
