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

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TextIO

from .generator import normalize_ctl
from .judge import _CTL2_REFERENCE, infer_component_type
from .function_catalog import (
    FUNCTION_INFO_TOOL_NAME, CatalogQueryError, FunctionCatalog, get_function_catalog,
)


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

_LITERAL_PREFERENCE_NOTE = """\

## Constant string parsed into a type — always WARNING, never ERROR or a mere SUGGESTION
CTL2 has native literal syntax for every non-string type: date/date-time
(`2005-01-01`, `2023-06-15 08:45:00`), decimal (`103.10D`), long (`123L`),
integer/number/boolean (plain literals). A `str2date`/`str2decimal`/
`str2long`/`str2integer`/`str2double`/`str2bool`-family conversion function is
meant for parsing a value that is genuinely a runtime string — external data,
a field read from `$in.*`, a variable, a concatenation, anything not fully
known at the point the code is written. Calling one of these functions on a
STRING LITERAL CONSTANT is valid, correct CTL2 (it compiles and produces the
right value) but is always suboptimal: the same constant should be written
directly as a native literal instead.

Report this as a WARNING (a real ISSUE, not merely a style SUGGESTION —
unlike the "Optimization hints" category below, which only covers patterns
that are pure efficiency polish with no bearing on how the value was
authored). Two worked examples:
  - `str2date("2005-01-01", "yyyy-MM-dd")` -> should be written as the native
    date literal `2005-01-01` directly.
  - `str2decimal("103.10")` -> should be written as the native decimal
    literal `103.10D` directly.
The same applies to `str2long("123")` (-> `123L`), `str2integer("5")` (->
`5`), `str2double("1.5")` (-> `1.5`), `str2bool("true")` (-> `true`), and any
other conversion function in this family applied to a literal string.

Do NOT flag this when the string argument is not a literal constant — e.g.
`str2date($in.0.dateStr, "yyyy-MM-dd")`, `str2decimal(someVar)`, or a
computed/concatenated string are all legitimate, necessary parsing of
runtime data and must never be flagged under this rule.
"""

_ONERROR_HANDLING_NOTE = """\

## No-op *OnError functions — silently swallowing a runtime error (ERROR)
Every component type has one or more optional `*OnError` counterpart
functions — `transformOnError`, `updateTransformOnError`, `appendOnError`,
`countOnError`, `updateGroupOnError`, `initGroupOnError`,
`finishGroupOnError`, `generateOnError`, `getOutputPortOnError`, and other
per-component variants (see the component contract for the exact set) — that
only run when their non-`OnError` counterpart (`transform`, `append`,
`count`, `updateGroup`, …) throws an uncaught RUNTIME exception.

- A component with NO `*OnError` function at all is correct by default: the
  graph aborts on that record, which is the right behavior unless the user
  prompt explicitly asks for runtime-error tolerance (e.g. "skip invalid
  records", "log and continue", "don't fail the graph on a bad row"). Do NOT
  flag the mere ABSENCE of an `*OnError` function.
- An `*OnError` function whose body does nothing but return a "continue as
  if nothing happened" code — `{ return OK; }`, `{ return 0; }`, an empty
  body, or equivalent — WITHOUT doing anything with the `errorMessage`/
  `stackTrace` it received (at minimum a `printLog`/`printErr` call, or some
  other real corrective action) IS a defect: report it as an ERROR. It tells
  the runtime the record was handled successfully while its actual
  contribution (e.g. an aggregate accumulator update, an emitted record) was
  silently dropped — the graph reports success while producing wrong or
  incomplete output, with no indication anywhere that anything went wrong.
  Canonical example: `function integer appendOnError(string errorMessage,
  string stackTrace) { return OK; }` on a Denormalizer — `append()`'s
  contribution to the running accumulator never happened, but nothing about
  the run signals that.
- An `*OnError` function that DOES something meaningful — logs the error,
  genuinely discards the record (e.g. `return SKIP;` where SKIP is a valid
  return for that function), or routes it to an error port — is legitimate
  and must NOT be flagged.
"""

_TRY_CATCH_FIX_NOTE = """\

## When writing the fix: prefer try-catch over *OnError functions
The `*OnError` function family (`transformOnError`, `updateTransformOnError`,
`appendOnError`, `countOnError`, `updateGroupOnError`, `generateOnError`,
`getOutputPortOnError`, etc.) pre-dates CTL2's `try { ... } catch
(CTLException ex) { ... }` construct. When your corrected code needs to add
or fix runtime-error handling, wrap the risky expression(s) in a `try-catch`
block INSIDE the existing function body instead of introducing or keeping a
no-op `*OnError` function. Only keep an `*OnError` function in your rewrite
if it already does something meaningful (see the rule above) or the
component contract requires the function to exist at all (check the
component contract) — do not newly introduce an empty/no-op one as a
"fix" for a compile or missing-function error.
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

_MISSING_CONTEXT_NOTE = """\

## Missing task context is NEVER an issue
The task supplies whatever context it supplies. A gap in the TASK is not a defect
in the CANDIDATE CODE, and reporting one turns the review into a complaint about
the question instead of feedback on the answer. Never report an issue of any
severity — ERROR, WARNING, or INFO — whose actual subject is one of these:
- Input or output port metadata the task did not include.
- An accumulator / group-accumulator record type the task never declared.
- A lookup, sequence, or dictionary the code references but the task does not define.
- A field the code uses that the task's metadata does not declare (when metadata for
  that port was not supplied at all).
- Which output ports are connected, when the code routes to more than one.
- A `Record`/`Field` attribute (a missing `type`, `nullable`, `format`, ...) absent
  from the metadata XML the task itself provided.
- A component configuration value that lives in the graph, not in CTL (record counts,
  group keys, port connections, charset, ...).

Judge the code against the context the task DOES carry. When a claim would need
context the task never supplied, the claim is unsupported — drop it silently.

## Built-in placeholder types are not undeclared types
CTL2 has built-in metadata types that need no declaration anywhere and legitimately
stand in where a real record type would otherwise go — `VoidMetadata` as a Rollup
group accumulator when no accumulator metadata is supplied is the canonical case
(see the component contract). A built-in placeholder is never "undefined", "not
supplied", "not among the provided metadata", or "must be declared". Before writing
any issue that says a type name is undeclared, confirm it is not one of these
built-ins.

## An invented issue is worse than a missed one
This review drives training data. A missed real defect costs one example; an issue
claiming that valid CTL2 is invalid teaches the model a false rule, and it will
reproduce that rule. When you are weighing whether a borderline concern is real,
resolve the doubt by dropping it, not by reporting it at a lower severity.
"""

_FUNCTION_LOOKUP_NOTE = """\

## `ctl_function_info` — the authoritative built-in function catalog
You have a tool, `ctl_function_info`, backed by a deterministic local catalog of
every CTL2 built-in (generated from the CloverDX CTL2 documentation plus runtime
probes). It does not compile anything and costs nothing to call. It returns, per
OVERLOAD: the canonical signature, each parameter's type and position, arity
bounds, the return type and its nullability, documented runtime errors, and
PARAMETER-SPECIFIC null behavior (`returns_null`, `runtime_error`, ...).

CALL IT — do not answer from memory — whenever an issue you are about to write
depends on any of:
- whether a built-in with that exact, case-sensitive name exists at all;
- which overloads/arities exist, or which one a specific call resolves to;
- a parameter's documented type, whether it is optional, or its default;
- the return type of a specific overload (this settles most numeric-type claims);
- what a specific PARAMETER position does when it receives null.

How to use it:
- Batch every function you need into ONE call: `{"queries": [{"name": "..."}, ...]}`.
  Only `name` is required. Add `arity`, `argument_types`, or `overload_id` to pin
  down one overload; omit any selector you cannot establish, and pass `"unknown"`
  as an argument type when the static type of that argument is not clear.
- Use `"detail": "full"` only when the compact result is genuinely not enough.
- Do not look the same function/overload up twice, and do not look up functions
  that are not relevant to a finding you are actually considering.

How to read the result:
- `not_found` is AUTHORITATIVE: no built-in has that exact name. Report the call
  as a nonexistent function (an ERROR), and remember CTL2 names are
  case-sensitive.
- `exact_overload` / `function_found` give you the documented behavior — use it
  verbatim; do not generalize from the return type, from another overload, or
  from a different parameter of the same overload.
- `no_matching_overload` means the name exists but nothing matches your filters —
  check `available_overload_ids` before concluding the CALL is wrong; your filter
  may simply have been too narrow.
- `ambiguous_overload` means several overloads match; decide from the returned
  candidates rather than guessing.
- If the catalog marks something `undocumented` or its `data_quality` shows
  issues, that is UNKNOWN — not "safe" and not "fails". Do not report an ERROR
  or WARNING that depends on behavior the catalog does not document.

The catalog outranks your own recollection of CTL2. Where a catalog result and
your intuition disagree, the catalog wins; where the catalog and the inline CTL2
reference disagree about a specific overload, prefer the catalog and do not
report the discrepancy as a defect in the candidate code.
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
    (
        '`x = {};` to reset a previously-declared `map` variable back to empty',
        '`clear(x);`',
    ),
    (
        '`x = [];` to reset a previously-declared `list`/array variable back to empty',
        '`clear(x);`',
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
    _REVIEW_RULES + _EVIDENCE_DISCIPLINE_NOTE + _MISSING_CONTEXT_NOTE
    + _NULL_HANDLING_NOTE
    + _NUMERIC_WIDENING_NOTE + _LITERAL_PREFERENCE_NOTE + _ONERROR_HANDLING_NOTE
    + _OPTIMIZATION_HINTS_NOTE
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

In particular, never "resolve" an issue by inventing context the task never
supplied — do not declare metadata records, accumulator record types, lookups,
or sequences that the task does not define, and do not replace a built-in
placeholder type (e.g. a Rollup's `VoidMetadata` group accumulator, correct
whenever no accumulator metadata is supplied) with a made-up record name or a
different type. An issue whose real subject is missing task context is not a
code defect: leave the code alone.

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
# Business domain hint (--tweak / --tweak-random)
#
# The tweak model previously invented its own "different business scenario"
# and reliably converged on the same few domains (e.g. sensor telemetry) for
# similarly-shaped originals — a direct result of (a) _TWEAK_SYSTEM's own
# example list below biasing it, and (b) the tweak call running at
# temperature=0.0, i.e. fully deterministic decoding with zero sampling
# diversity of its own. Rather than ask the model to pick a domain, an
# external (industry, process, region) triple is picked from these curated
# lists and handed to it as a hard constraint — see pick_business_domain().
#
# Caller controls the actual randomness source:
#   --tweak         : deterministic per example (seed the rng from a stable
#                      example identifier) — reproducible across re-runs of
#                      the same input file, but varied across examples.
#   --tweak-random  : caller passes an unseeded/entropy-seeded rng instead,
#                      so repeated runs land on different domains.
# This module only picks from a given rng; it does not decide which kind.
# ---------------------------------------------------------------------------

_TWEAK_INDUSTRIES = [
    "banking", "telecommunications", "airline", "insurance", "healthcare",
    "pharmaceutical research", "retail", "e-commerce", "manufacturing",
    "logistics and freight", "energy and utilities", "government and public sector",
    "higher education", "hospitality and hotels", "real estate",
    "media and streaming", "agriculture", "automotive", "public transit",
    "food and beverage", "construction", "legal services", "non-profit and NGO",
    "sports and entertainment", "mining and natural resources",
]

_TWEAK_PROCESSES = [
    "order taking", "claims processing", "customer onboarding", "fraud detection",
    "billing and invoicing", "inventory management", "HR and payroll",
    "supply chain management", "research and development", "marketing analytics",
    "compliance and audit", "customer support", "procurement", "quality assurance",
    "network operations", "reservation and booking", "returns processing",
    "asset maintenance", "loyalty program management", "dispatch and scheduling",
    "underwriting", "warehouse management", "payment processing",
    "employee scheduling", "incident management",
]

_TWEAK_REGIONS = [
    "North America", "Latin America", "Western Europe", "Eastern Europe",
    "Nordics", "United Kingdom and Ireland", "Iberia", "Benelux",
    "DACH (Germany, Austria, Switzerland)", "Balkans", "Middle East",
    "North Africa", "Sub-Saharan Africa", "South Asia", "Southeast Asia",
    "East Asia", "Greater China", "Australia and New Zealand",
    "Pacific Islands", "Central Asia", "Caribbean", "Andean region",
    "Southern Cone", "Gulf Cooperation Council states", "Central America",
]


def pick_business_domain(rng: random.Random) -> str:
    """Pick one (industry, process, region) triple from the curated lists
    above using the given rng, and format it as the hint block injected into
    _TWEAK_USER. Whether rng is deterministic (--tweak) or entropy-seeded
    (--tweak-random) is entirely the caller's choice — this function just
    draws from it."""
    industry = rng.choice(_TWEAK_INDUSTRIES)
    process = rng.choice(_TWEAK_PROCESSES)
    region = rng.choice(_TWEAK_REGIONS)
    return f"Business domain: {industry} {process}\nRegion: {region}"


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
1. Business domain: the task below specifies an EXACT business domain and
   region to use — adopt it precisely. Do NOT invent a different domain, do
   NOT fall back to a generic example of your own (sensor telemetry,
   warehouse inventory, employee shifts, flight bookings, etc. are NOT valid
   choices unless they are literally the domain given below), and do not
   ignore the region. Let the region inform natural local flavor where it
   fits (currency, units, terminology, local business norms) — it does not
   need to change the CTL2 structure itself.
2. Field names: every field gets a new name fitting the new domain. Do not
   reuse the original field names.
3. Field types / nullability: vary at least some field types and nullable
   attributes from the original (e.g. swap integer <-> long, add or remove
   nullable="false", change a string to decimal where it still makes sense).
4. Business logic — STRUCTURAL change required, not parameter substitution.
   The most common failure here is producing the same expression tree with
   new names/thresholds swapped in (e.g. original: "`status` is A or B, AND
   `amount` <= 5000, AND `flag` is false" -> bad rewrite: "`status2` is C or
   D, AND `amount2` >= 50, AND `flag2` is true" — same shape: one set-
   membership check, one numeric threshold, one boolean check, joined by AND.
   That is NOT acceptable; renaming a threshold or flipping an operator
   direction/boolean value is not a structural change.
   Do AT LEAST ONE of the following, chosen to fit the new domain naturally
   (do not force all of them):
     - Change the condition COUNT (one fewer or one more than the original).
     - Change how conditions COMBINE: flat AND-of-N -> nested grouping like
       (A OR B) AND (C OR D); AND-dominant -> OR-dominant; add a NOT.
     - Introduce a condition TYPE absent from the original: a null/missing-
       value check, a string prefix/contains/pattern match, a date or
       date-range comparison, a derived/computed value (e.g. a ratio, a sum
       of two fields, a length), or a comparison BETWEEN two input fields
       instead of a field against a constant.
     - Swap which field plays the "categorical set membership" role vs. the
       "numeric threshold" role vs. the "boolean flag" role, or drop one of
       those roles and add a different one instead.
   Also rewrite the instruction to use the new field names throughout.
   The correct CTL2 code for the new task must be structurally different
   from the correct code for the original task, not just a relabeling of the
   same conditions.

## What to keep
- Component type: the new task MUST be for the exact same CTL2 component
  type as the original — do not change which component this is for, only
  what it does. (The original's component type is named in the task given
  below, under "Original task".)
- Overall shape: roughly the same number of input/output fields and about
  the same difficulty level.
- Metadata FORMAT: match the original EXACTLY — do not switch formats.
    - If the original describes ports as XML `<Metadata>` blocks, the new
      task must also use XML `<Metadata>` blocks (see the required XML
      structure below).
    - If the original describes ports as plain prose/a bullet list (e.g.
      "Input metadata (port 0):\n- field_name: type\n- ..." with no XML at
      all), the new task must ALSO use that same plain prose/bullet-list
      style — do NOT introduce `<Metadata>`/`<Record>`/`<Field>` XML where
      the original had none.

## Required XML structure — ONLY when the original itself uses XML metadata
A `<Metadata>` element always wraps EXACTLY ONE `<Record>` element, which in
turn wraps the `<Field>` elements. `<Field>` must NEVER appear directly
under `<Metadata>` — omitting the `<Record>` wrapper produces invalid
CloverDX metadata that cannot be parsed, even though it looks plausible:
```xml
<Metadata id="SomeId">
  <Record name="SomeRecordName" fieldDelimiter="," recordDelimiter="\\n" type="delimited">
    <Field name="field_one" type="string"/>
    <Field name="field_two" type="integer" nullable="true"/>
  </Record>
</Metadata>
```
  WRONG (missing `<Record>` — do not do this):
```xml
<Metadata name="SomeId">
  <Field name="field_one" type="string"/>
</Metadata>
```
This applies whenever you output XML metadata, regardless of whether the
original prompt phrased its port headers as "Given Input Metadata on Port 0:",
"Input metadata (port 0):", or any other wording — the `<Record>` wrapper
inside `<Metadata>` is a hard CloverDX schema requirement, never optional.

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

## Required business domain for the new task
{business_domain}

---
Rewrite this into a new task per the rules above. Remember: use the EXACT
business domain and region given above (do not substitute your own), give it
different field names, at least one changed field type/nullability, and a
STRUCTURALLY different business rule (different condition count, combination,
or condition type — not the same expression shape with renamed fields and
swapped thresholds/operators) — while staying the same component type and
roughly the same shape/difficulty. Match the ORIGINAL TASK's metadata format
exactly as it appears above — if it has no `<Metadata>`/`<Record>`/`<Field>`
XML, do not introduce any; if it does use that XML, every `<Metadata>` must
wrap a `<Record>` that wraps the `<Field>`s (never `<Field>` directly under
`<Metadata>`).
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


def _build_review_system(component_type: str, function_lookup: bool = False) -> str:
    """Assemble the review system prompt with the stable content first (rules,
    then the large CTL2 reference) and the variable, per-example component
    contract last — maximizes the byte-identical shared prefix across calls
    for prompt-cache reuse. No section here manages hidden reasoning; the
    hardening note only asks the model to verify its own final output."""
    rules = _REVIEW_RULES_FULL + (_FUNCTION_LOOKUP_NOTE if function_lookup else "")
    parts = [_REVIEW_SYSTEM_INTRO, f"\n<REVIEW_RULES>\n{rules}</REVIEW_RULES>\n"]
    if _CTL2_REFERENCE:
        parts.append(f"\n<CTL2_REFERENCE>\n{_CTL2_REFERENCE}\n</CTL2_REFERENCE>\n")
    note = _component_note(component_type)
    if note:
        parts.append(f"\n<COMPONENT_CONTRACT>\n{note}\n</COMPONENT_CONTRACT>\n")
    parts.append(_FINAL_VERIFICATION_NOTE)
    return "".join(parts)


def _build_fix_system(component_type: str, function_lookup: bool = False) -> str:
    parts = [
        _FIX_SYSTEM_BASE, _NULL_HANDLING_NOTE, _NUMERIC_WIDENING_NOTE, _LITERAL_PREFERENCE_NOTE,
        _ONERROR_HANDLING_NOTE, _TRY_CATCH_FIX_NOTE,
    ]
    if function_lookup:
        parts.append(_FUNCTION_LOOKUP_NOTE)
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

# Extra attempts (beyond the first) when a reasoning-tier model burns its
# entire token budget on hidden reasoning and returns empty visible content
# (finish_reason == "length"). Confirmed non-deterministic on a local
# reasoning model (laguna-s-2.1-fp8): an identical request failed once at
# max_completion_tokens=16000, then succeeded moments later using under 4000
# tokens — sampling variance in reasoning length, not a real error. No
# backoff delay: unlike moderation flags, this isn't a rate/volume signal,
# just re-sampling the same request against a local server.
_LENGTH_EXHAUSTION_RETRIES = 2


class _SwitchToResponsesAPI(RuntimeError):
    """Raised when /v1/chat/completions refuses the request in a way that the
    Responses API is documented to handle — currently OpenAI's "Function tools
    with reasoning_effort are not supported ... in /v1/chat/completions. To use
    function tools, use /v1/responses" (seen on gpt-5.6-terra). Caught by
    _call_openai, which re-issues the same call through the Responses API and
    keeps the ctl_function_info tool instead of silently dropping it."""


def _is_response_exhausted(resp) -> bool:
    """Responses-API counterpart of _is_length_exhausted: a reasoning-tier
    model that spent max_output_tokens on hidden reasoning and returned no
    visible text."""
    if (getattr(resp, "output_text", "") or "").strip():
        return False
    if getattr(resp, "status", None) != "incomplete":
        return False
    details = getattr(resp, "incomplete_details", None)
    return getattr(details, "reason", None) == "max_output_tokens"


def _is_length_exhausted(resp) -> bool:
    """True if `resp` is the empty-content/finish_reason='length' signature
    of a reasoning-tier model exhausting its token budget on hidden
    reasoning before producing any visible answer (see
    _LENGTH_EXHAUSTION_RETRIES)."""
    if not resp.choices:
        return False
    content = resp.choices[0].message.content or ""
    finish_reason = getattr(resp.choices[0], "finish_reason", None)
    return not content.strip() and finish_reason == "length"


# ---------------------------------------------------------------------------
# Deterministic numeric-claim adjudication (catalog-first)
#
# check_numeric_claim() used to spend an LLM call on every reported ISSUE that
# mentioned a numeric type. For any claim that names a BUILT-IN, the function
# catalog already holds the fact the claim stands or falls on — that built-in's
# documented return type per overload — so the claim can be settled in-process
# for free. The LLM call is kept for what the catalog genuinely cannot answer:
# claims about bare operators, assignments, and ternaries where no built-in is
# involved, and claims whose function resolves to several possible return types.
# In that second case the catalog evidence is still handed to the model, so the
# fallback reasons from documented signatures instead of recollection.
# ---------------------------------------------------------------------------

# integer -> long -> number -> decimal (see _NUMERIC_WIDENING_NOTE). `double`
# is an alias of `number` and shares its rank.
_NUMERIC_RANKS = {"integer": 1, "long": 2, "number": 3, "double": 3, "decimal": 4}


def _numeric_rank(type_name: str) -> Optional[int]:
    return _NUMERIC_RANKS.get(type_name.strip().lower())


# A name written as a call (`round(`) or quoted as a bare identifier
# (`` `round` ``) in an issue description.
_DESCRIPTION_NAME_RE = re.compile(r"`?\b([A-Za-z_][A-Za-z0-9_]*)\b`?\s*\(|`([A-Za-z_][A-Za-z0-9_]*)`")

# "returns decimal", "returns a decimal", "returning decimal", "result is decimal",
# "evaluates to decimal" — the claim's assertion about what a call produces.
_ASSERTED_RETURN_RE = re.compile(
    r"\b(?:returns?|returning|returned|result\s+(?:is|type\s+is)|evaluates?\s+to|produces?|yields?)"
    r"\s+(?:a|an|the)?\s*`?(integer|long|number|double|decimal)`?",
    re.IGNORECASE,
)

# The claim demands a conversion / calls the code invalid on numeric grounds.
_DEMANDS_CONVERSION_RE = re.compile(
    r"\b(?:explicit(?:ly)?\s+conversion|explicit(?:ly)?\s+cast|must\s+be\s+converted|"
    r"needs?\s+(?:an?\s+)?(?:explicit\s+)?conversion|requires?\s+(?:an?\s+)?(?:explicit\s+)?conversion|"
    r"no\s+implicit\s+conversion|not\s+implicitly\s+convert|cannot\s+be\s+assigned|"
    r"type\s+mismatch|narrow(?:s|ing|ed)?\s+(?:into|to)|loses?\s+precision\s+implicitly|"
    r"decimal2\w+|double2\w+|long2\w+|num2\w+)\b",
    re.IGNORECASE,
)


def _call_arities(code: str, name: str) -> set[int]:
    """Every distinct argument count `name` is called with in `code`.

    Counts top-level commas inside the call's own parentheses, so nested calls
    and parenthesised expressions do not inflate the count. A definition
    (`function integer name(...)`) is skipped — a Denormalizer's own
    `append()` must not be read as the catalog's list `append`."""
    arities: set[int] = set()
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", code):
        before = code[max(0, match.start() - 40):match.start()]
        if re.search(r"\bfunction\s+[A-Za-z_][A-Za-z0-9_\[\]]*\s*$", before):
            continue
        depth, args, seen_token, index = 0, 0, False, match.end() - 1
        while index < len(code):
            char = code[index]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
                if depth == 0:
                    arities.add(args + 1 if seen_token else 0)
                    break
            elif depth == 1:
                if char == ",":
                    args += 1
                elif not char.isspace():
                    seen_token = True
            index += 1
    return arities


def _catalog_evidence(
    description: str, code: str, catalog: "FunctionCatalog"
) -> tuple[dict[str, set[str]], list[str]]:
    """Resolve every built-in the description names against the catalog.

    Returns ({function name: documented return types}, [signature lines]).
    A name is only considered when it is also called in the code with an arity
    the catalog recognizes, which is what keeps a component entry point that
    happens to share a built-in's name (`append`, `count`) out of the result."""
    names: list[str] = []
    for match in _DESCRIPTION_NAME_RE.finditer(description):
        name = match.group(1) or match.group(2)
        if name and name not in names and catalog.has(name):
            names.append(name)
    returns: dict[str, set[str]] = {}
    lines: list[str] = []
    for name in names:
        arities = _call_arities(code, name)
        arity = next(iter(arities)) if len(arities) == 1 else None
        types = catalog.return_types(name, arity)
        if not types:
            continue
        returns[name] = types
        function = catalog.functions[name]
        signatures = [
            overload["canonical_signature"]
            for overload in function["overloads"]
            if arity is None or overload["arity"]["minimum"] <= arity
            and (overload["arity"]["maximum"] == "unbounded" or arity <= overload["arity"]["maximum"])
        ]
        lines.append(f"{name}: " + " | ".join(signatures))
    return returns, lines


def _catalog_numeric_verdict(
    returns: dict[str, set[str]], description: str
) -> Optional[bool]:
    """Settle a numeric claim from catalog facts alone, or None when the
    catalog cannot settle it (in which case the caller asks the LLM).

    True = the claim survives; False = it contradicts the documented signature.
    Only fires where the documented return type is unambiguous, so a genuinely
    generic function (`round`, whose four overloads return four different
    types) always falls through rather than being decided on a coin flip."""
    if not returns:
        return None
    settled = {name: next(iter(types)) for name, types in returns.items() if len(types) == 1}
    if not settled:
        return None

    # Where each resolved built-in is named, so a "returns decimal" phrase is
    # attributed to the function it actually follows and not to some other
    # built-in mentioned elsewhere in the same sentence.
    mentions: list[tuple[int, str]] = []
    for match in _DESCRIPTION_NAME_RE.finditer(description):
        name = match.group(1) or match.group(2)
        if name in returns:
            mentions.append((match.start(), name))

    # (a) The claim states what a specific call returns, and the catalog
    #     disagrees for that same function.
    for match in _ASSERTED_RETURN_RE.finditer(description):
        owners = [name for pos, name in mentions if pos < match.start()]
        if not owners:
            continue
        documented = settled.get(owners[-1])
        if documented is None:
            continue
        claimed = match.group(1).lower()
        claimed = "number" if claimed == "double" else claimed
        if _numeric_rank(claimed) is not None and claimed != documented:
            return False

    # (b) The claim demands a conversion, exactly one built-in with a known
    #     return type is in play, and the only other numeric type mentioned is
    #     WIDER than it — the automatic widening direction, where there is no
    #     missing conversion to report. With two such built-ins the claim's
    #     subject is ambiguous, so it goes to the model instead.
    if len(settled) == 1 and _DEMANDS_CONVERSION_RE.search(description):
        documented = next(iter(settled.values()))
        mentioned = {
            "number" if m.lower() == "double" else m.lower()
            for m in _NUMERIC_TYPE_MENTION_RE.findall(description)
        }
        if documented in mentioned and len(mentioned) == 2:
            other = next(t for t in mentioned if t != documented)
            source, target = _numeric_rank(documented), _numeric_rank(other)
            if source is not None and target is not None and source <= target:
                return False
    return None


_CATALOG_EVIDENCE_BLOCK = """

<CATALOG_EVIDENCE>
Documented signatures for the built-ins this issue names, from the
authoritative CTL2 function catalog. These are FACTS — prefer them over your
own recollection, and resolve a generic return type from the argument actually
passed at the call site in the code above:
{evidence}
</CATALOG_EVIDENCE>"""


class ReviewJudgeClient:
    """
    Judge prompt caching: the review/fix system prompts are large (~25K
    tokens: rules + the full CTL2 reference + a component contract) and
    almost fully stable across calls, but consecutive judge calls are spaced
    out by however long local MUT generation takes in between (tens of
    seconds or more) — long enough that OpenAI's default ("in_memory", short
    TTL) prompt cache retention often expires before the next call arrives.
    _call_openai sends `prompt_cache_key` (a stable per-purpose string, so
    OpenAI can bucket repeat requests to the same warm backend) and
    `prompt_cache_retention: "24h"` (extends how long the cached prefix stays
    active) to address this — both configurable via the "prompt_cache_key"/
    "prompt_cache_retention" cfg keys. Confirmed via a real run's per-call
    logs that cache hits were sparse and inconsistent even for back-to-back
    calls reviewing the SAME candidate, consistent with retention expiring
    between calls rather than a prefix-construction bug.
    """

    def __init__(self, cfg: dict, log_file: Optional[TextIO] = None):
        self._cfg = cfg
        self._llm = None
        self.usage = UsageStats()
        # One client instance is reused across genuinely different prompt
        # "families" (e.g. the judge client handles both review() and fix()
        # calls; the tweak_llm client handles both tweak() and
        # check_numeric_claim() calls) that have DIFFERENT system prompts
        # and therefore very different caching behavior — review's ~25K
        # token, near-fully-shared prompt caches well; fix()'s distinct
        # system prompt shares nothing with it; numeric-check's tiny prompt
        # is under the 1024-token minimum and can never cache at all.
        # Aggregating them into self.usage alone dilutes the visible cache
        # hit rate and hides which prompt family is actually caching.
        # Keyed by the same `purpose` string passed to _call().
        self.usage_by_purpose: dict[str, UsageStats] = {}
        # Newer OpenAI models (gpt-5.x) require max_completion_tokens instead of
        # max_tokens, and some reject a non-default temperature or reasoning_effort.
        # Auto-detected on first call and cached so we don't eat a failed
        # round-trip every time.
        self._openai_token_param: Optional[str] = None
        self._openai_supports_temperature: bool = True
        self._openai_supports_reasoning_effort: bool = True
        # prompt_cache_key/prompt_cache_retention are OpenAI-specific fields a
        # local/self-hosted OpenAI-compatible server (e.g. the vLLM-served
        # tweak_llm) will very likely reject outright — same auto-detect-and-
        # drop treatment as the flags above.
        self._openai_supports_prompt_cache_key: bool = True
        self._openai_supports_prompt_cache_retention: bool = True
        # Same treatment for `tools`/`tool_choice`: a local OpenAI-compatible
        # server may not implement function calling at all, in which case the
        # `ctl_function_info` tool is dropped and the judge falls back to the
        # inline CTL2 reference for that run.
        self._openai_supports_tools: bool = True
        # Which OpenAI endpoint to use: "chat_completions", "responses", or
        # "auto" (resolved on first use — see _resolve_openai_api). Newer
        # reasoning models reject function tools on /v1/chat/completions when
        # reasoning_effort is set and require /v1/responses instead, which is
        # what "auto" exists to get right without per-model config.
        self._openai_api_cfg: str = (cfg.get("api") or "auto").strip().lower()
        if self._openai_api_cfg not in ("auto", "chat_completions", "responses"):
            raise ValueError(
                f"judge api must be 'auto', 'chat_completions' or 'responses', "
                f"got {cfg.get('api')!r}"
            )
        self._openai_api: Optional[str] = (
            None if self._openai_api_cfg == "auto" else self._openai_api_cfg
        )
        # Responses-API counterparts of the auto-detected chat flags above.
        self._responses_supports_reasoning: bool = True
        self._responses_supports_temperature: bool = True
        self._responses_supports_prompt_cache_key: bool = True
        self._responses_supports_prompt_cache_retention: bool = True
        self._responses_supports_tools: bool = True
        # Optional run-log file — receives full, untruncated diagnostics
        # (unparseable raw responses, flagged prompts) that console output
        # only shows a short preview of.
        self._log_file = log_file
        # Deterministic CTL2 built-in function catalog, exposed to the model as
        # the `ctl_function_info` tool (see function_catalog.py and
        # _FUNCTION_LOOKUP_NOTE). Loaded eagerly so a bad path/library fails at
        # startup rather than mid-run, and shared process-wide across clients.
        self.catalog: Optional[FunctionCatalog] = None
        lookup_cfg = cfg.get("function_lookup") or {}
        if lookup_cfg.get("enabled"):
            self.catalog = get_function_catalog(
                lookup_cfg.get("library"),
                max_queries_per_call=int(lookup_cfg.get("max_queries_per_call", 20)),
            )
        # Tool-call rounds allowed per judge call. Each round is one model turn
        # that may batch up to max_queries_per_call lookups, so the default is
        # deliberately small: the model is told to batch, and an unbatched
        # one-function-per-round crawl is exactly what this cap should stop.
        self._max_lookup_rounds = int(lookup_cfg.get("max_rounds_per_call", 3))
        # Purposes that get the tool. review/fix are the calls that reason about
        # built-in behavior; tweak() only rewrites a task prompt, and
        # check_numeric_claim() is itself a verification step with a tiny
        # prompt, so neither needs (or should pay for) the tool.
        self._lookup_purposes = frozenset(
            lookup_cfg.get("purposes") or ("review", "fix")
        )

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
            # A local/self-hosted OpenAI-compatible server (vLLM, etc.) never
            # checks this value, but the OpenAI SDK's client constructor
            # still requires a non-empty string or it raises before any
            # request is even sent — so an omitted api_key + no
            # OPENAI_API_KEY env var breaks local usage even though the
            # actual HTTP call would have worked fine.
            self._llm = OpenAI(
                api_key=key or "not-needed",
                base_url=self._cfg.get("base_url"),
                timeout=self._cfg.get("request_timeout_s", 180),
            )
        else:
            raise ValueError(f"Unknown judge provider: {provider!r}")
        return self._llm

    def _call(self, system: str, user_message: str, purpose: str = "") -> str:
        provider = self._cfg.get("provider", "anthropic")
        if provider == "anthropic":
            return self._call_anthropic(system, user_message, purpose)
        elif provider == "openai":
            return self._call_openai(system, user_message, purpose)
        else:
            raise ValueError(f"Unknown judge provider: {provider!r}")

    def lookup_enabled_for(self, purpose: str) -> bool:
        """Whether `ctl_function_info` is offered on calls with this purpose —
        also what the prompt builders key their tool-policy section off, so the
        system prompt never advertises a tool the request will not carry."""
        return self.catalog is not None and purpose in self._lookup_purposes

    def _run_lookup(self, raw_arguments: Any, call_label: str) -> str:
        """Execute one `ctl_function_info` tool call and return the JSON string
        to hand back to the model.

        A malformed query is answered with a structured error the model can act
        on (upstream's `retry_allowed` / `next_action` convention) rather than
        an exception — a bad tool argument is a recoverable turn, not a reason
        to lose a whole review."""
        try:
            arguments = (
                json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            )
        except json.JSONDecodeError as exc:
            arguments = None
            error: Optional[str] = f"invalid argument JSON: {exc.msg}"
        else:
            error = None
        if error is None:
            try:
                payload = self.catalog.call(arguments)
            except CatalogQueryError as exc:
                error = str(exc)
        if error is not None:
            self._log_full(f"[function-lookup] {call_label} rejected: {error}")
            return json.dumps({
                "status": "error",
                "retry_allowed": True,
                "error": error,
                "next_action": (
                    "Correct the query against the tool schema and retry once. Only "
                    "`name` is required; omit selectors you cannot establish. Do not "
                    "invent documentation the catalog did not return."
                ),
            })
        statuses = ", ".join(
            f"{r['query']['name']}={r['status']}" for r in payload["results"]
        )
        # Console gets a one-line indication that the judge actually reached for
        # the catalog (and what came back); the run log keeps the full detail.
        names = ", ".join(r["query"]["name"] for r in payload["results"])
        flagged = [
            f"{r['query']['name']}={r['status']}"
            for r in payload["results"]
            if r["status"] in ("not_found", "no_matching_overload", "ambiguous_overload")
        ]
        print(f"[review-judge] ctl_function_info -> {len(payload['results'])} lookup(s): {names}"
              + (f"  [{', '.join(flagged)}]" if flagged else ""))
        self._log_full(f"[function-lookup] {call_label}: {statuses}")
        return json.dumps(payload)

    def _record_usage(self, purpose: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> None:
        self.usage.add(input_tokens=input_tokens, cached_tokens=cached_tokens, output_tokens=output_tokens)
        self.usage_by_purpose.setdefault(purpose or "unknown", UsageStats()).add(
            input_tokens=input_tokens, cached_tokens=cached_tokens, output_tokens=output_tokens,
        )

    def _call_anthropic(self, system: str, user_message: str, purpose: str = "") -> str:
        llm = self._get_llm()
        model = self._cfg.get("model", "claude-opus-4-20250514")
        max_tokens = self._cfg.get("max_tokens", 2048)
        use_tool = self.lookup_enabled_for(purpose)
        messages: list[dict] = [{"role": "user", "content": user_message}]
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "system": system,
        }
        if use_tool:
            kwargs["tools"] = [self.catalog.anthropic_tool()]

        # One turn per iteration; a turn that ends in tool_use gets its results
        # appended and the model is called again. The +1 is the final,
        # tool-free turn that produces the answer.
        for round_index in range(self._max_lookup_rounds + 1 if use_tool else 1):
            resp = llm.messages.create(messages=messages, **kwargs)
            u = resp.usage
            # cache_read_input_tokens is the portion of input_tokens served from
            # Anthropic's prompt cache — a subset of input_tokens, not additional.
            self._record_usage(
                purpose,
                input_tokens=u.input_tokens,
                cached_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                output_tokens=u.output_tokens,
            )
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses or getattr(resp, "stop_reason", None) != "tool_use":
                return "".join(b.text for b in resp.content if hasattr(b, "text"))
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in tool_uses:
                if block.name != FUNCTION_INFO_TOOL_NAME:
                    content = json.dumps({
                        "status": "error", "retry_allowed": False,
                        "error": f"unknown tool {block.name!r}",
                    })
                else:
                    content = self._run_lookup(
                        block.input, f"{purpose} round {round_index + 1}"
                    )
                results.append({
                    "type": "tool_result", "tool_use_id": block.id, "content": content,
                })
            messages.append({"role": "user", "content": results})
            # Last allowed round: drop the tool so the next turn must answer.
            if round_index + 1 >= self._max_lookup_rounds:
                kwargs.pop("tools", None)
                self._log_full(
                    f"[function-lookup] {purpose}: lookup round cap "
                    f"({self._max_lookup_rounds}) reached — answering without the tool"
                )
        raise RuntimeError("unreachable")  # loop always returns or raises

    def _disable_tools_after_rejection(self, kwargs: dict, msg: str, endpoint: str) -> None:
        """Drop the ctl_function_info tool from an in-flight request after the
        provider refused it, and say so loudly.

        The run still completes, but the judge is now working from the inline
        reference alone — exactly the setup that produced hallucinated function
        claims — so this must not slip by unnoticed in the scrollback."""
        kwargs.pop("tools", None)
        kwargs.pop("tool_choice", None)
        self._log_full(
            f"[function-lookup] {endpoint} rejected `tools` ({msg[:500]}) "
            f"— continuing without ctl_function_info"
        )
        banner = "!" * 78
        if endpoint == "/v1/responses":
            # Nothing left to switch to — this is already the endpoint that
            # supports tools for reasoning-tier models.
            fix_line = (
                "!! Fix: point `judge` at a model that supports function calling, or set\n"
                "!! judge.function_lookup.enabled: false to make this deliberate.\n"
            )
        elif self._openai_api_cfg == "chat_completions" and "/v1/responses" in msg:
            fix_line = (
                "!! Fix: remove judge.api: chat_completions so the run can switch to\n"
                "!! /v1/responses (this model supports tools only there), point `judge` at\n"
                "!! a model that supports tools, or set judge.function_lookup.enabled: false.\n"
            )
        else:
            fix_line = (
                "!! Fix: set judge.api: responses (this model may support tools only on\n"
                "!! /v1/responses), point `judge` at a model that supports tools, or set\n"
                "!! judge.function_lookup.enabled: false to make this deliberate.\n"
            )
        print(
            f"\n{banner}\n"
            f"!! WARNING: this provider/model REJECTED function calling on {endpoint}.\n"
            f"!! model={self._cfg.get('model')!r} base_url={self._cfg.get('base_url') or 'default (OpenAI)'}\n"
            f"!! The ctl_function_info catalog tool is DISABLED for the rest of this run;\n"
            f"!! the judge falls back to the inline CTL2 reference for function facts,\n"
            f"!! so hallucinated function/overload/null-behavior claims become more likely.\n"
            f"!! Provider said: {msg[:200]}\n"
            + fix_line +
            f"{banner}\n",
            flush=True,
        )

    def _create_openai_chat_completion(self, llm, kwargs: dict, max_flag_retries: Optional[int] = None):
        """Call chat.completions.create(), transparently working around two
        provider quirks: (1) newer OpenAI models need max_completion_tokens
        instead of max_tokens, or reject a non-default temperature,
        reasoning_effort, prompt_cache_key, or prompt_cache_retention —
        detected once and cached on self (the last two matter for a
        local/self-hosted OpenAI-compatible server that doesn't recognize
        OpenAI-specific caching fields); (2) OpenAI's moderation classifier
        can flag a completely benign prompt intermittently (confirmed:
        identical request, different outcome on repeat) — retrying the
        identical request a few times resolves it more often than not."""
        from openai import BadRequestError

        if max_flag_retries is None:
            max_flag_retries = len(_MODERATION_BACKOFF_S) + 1
        max_tokens_value = kwargs.get(self._openai_token_param or "max_tokens")
        for attempt in range(max_flag_retries):
            try:
                return llm.chat.completions.create(**kwargs)
            except BadRequestError as e:
                msg = str(e)
                # FIRST: is this the endpoint's own limitation rather than a
                # bad parameter? gpt-5.6-terra answers a tools request with
                # "Function tools with reasoning_effort are not supported for
                # <model> in /v1/chat/completions. To use function tools, use
                # /v1/responses or set reasoning_effort to none". That message
                # also mentions reasoning_effort, so it MUST be matched before
                # the generic parameter handlers below — otherwise the run
                # silently loses the configured reasoning_effort (a deliberate
                # quality setting) when the actual fix is to change endpoint
                # and keep it.
                if (
                    "tools" in kwargs
                    and ("tool" in msg or "function" in msg)
                    and "/v1/responses" in msg
                ):
                    if self._openai_api_cfg != "chat_completions":
                        raise _SwitchToResponsesAPI(msg[:400])
                    # Endpoint pinned by config: honour that, and give up the
                    # optional capability rather than the configured
                    # reasoning_effort the generic handler below would strip.
                    self._openai_supports_tools = False
                    self._disable_tools_after_rejection(kwargs, msg, "/v1/chat/completions")
                    continue
                if "max_completion_tokens" in msg and self._openai_token_param != "max_completion_tokens":
                    self._openai_token_param = "max_completion_tokens"
                    kwargs.pop("max_tokens", None)
                    kwargs["max_completion_tokens"] = max_tokens_value
                    continue
                if "temperature" in msg and "temperature" in kwargs:
                    self._openai_supports_temperature = False
                    kwargs.pop("temperature")
                    continue
                if "reasoning_effort" in msg and "reasoning_effort" in kwargs:
                    self._openai_supports_reasoning_effort = False
                    kwargs.pop("reasoning_effort")
                    continue
                if "prompt_cache_key" in msg and "prompt_cache_key" in kwargs:
                    self._openai_supports_prompt_cache_key = False
                    kwargs.pop("prompt_cache_key")
                    continue
                if "prompt_cache_retention" in msg and "prompt_cache_retention" in kwargs:
                    self._openai_supports_prompt_cache_retention = False
                    kwargs.pop("prompt_cache_retention")
                    continue
                if ("tool" in msg or "function" in msg) and "tools" in kwargs:
                    # Reached when the endpoint switch above did not apply:
                    # the provider named no alternative endpoint.
                    self._openai_supports_tools = False
                    self._disable_tools_after_rejection(kwargs, msg, "/v1/chat/completions")
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

    def _resolve_openai_api(self, use_tool: bool) -> str:
        """Pick the endpoint for this call when `api: auto` is configured.

        Tools are the whole reason this matters: a reasoning-tier OpenAI model
        rejects function tools on /v1/chat/completions, so a call that wants
        the ctl_function_info tool goes to /v1/responses. Anything else stays
        on chat.completions, which is what every prompt-cache and quirk
        workaround in this file was tuned against. A custom base_url (a local
        vLLM/self-hosted server) also stays on chat.completions: those servers
        commonly implement /v1/chat/completions only, and the tools-rejection
        path below still degrades cleanly there.
        """
        if self._openai_api is not None:
            return self._openai_api
        if use_tool and not self._cfg.get("base_url"):
            resolved = "responses"
        else:
            resolved = "chat_completions"
        self._log_full(
            f"[review-judge] OpenAI api=auto resolved to {resolved!r} "
            f"(tools={'on' if use_tool else 'off'}, "
            f"base_url={self._cfg.get('base_url') or 'default (OpenAI)'})"
        )
        # Cached per client: the resolution depends only on config + whether
        # this client ever offers the tool, so it cannot flip mid-run except
        # via the explicit fallbacks below.
        self._openai_api = resolved
        return resolved

    def _call_openai(self, system: str, user_message: str, purpose: str = "") -> str:
        use_tool = self.lookup_enabled_for(purpose)
        api = self._resolve_openai_api(use_tool)
        if api == "responses":
            return self._call_openai_responses(system, user_message, purpose)
        try:
            return self._call_openai_chat(system, user_message, purpose)
        except _SwitchToResponsesAPI as exc:
            # chat.completions cannot serve this model WITH tools; the provider
            # itself pointed at /v1/responses. Switch for the rest of the run
            # rather than losing the catalog tool.
            print(f"[review-judge] Switching to the OpenAI Responses API "
                  f"(/v1/responses) — chat.completions refused function tools for "
                  f"model={self._cfg.get('model')!r}. Set judge.api explicitly to "
                  f"pin this.", flush=True)
            self._log_full(f"[review-judge] auto-switch to responses API: {exc}")
            self._openai_api = "responses"
            return self._call_openai_responses(system, user_message, purpose)

    def _call_openai_chat(self, system: str, user_message: str, purpose: str = "") -> str:
        llm = self._get_llm()
        model = self._cfg.get("model", "claude-opus-4-20250514")
        # "max_completion_tokens" is the config key going forward (matches the
        # OpenAI request field name for reasoning-tier models); "max_tokens"
        # is kept as a fallback so existing configs that only set the older
        # key keep working. Which wire parameter NAME is actually sent
        # ("max_tokens" vs "max_completion_tokens") is a separate, runtime-
        # detected concern — see self._openai_token_param above.
        max_tokens = self._cfg.get("max_completion_tokens", self._cfg.get("max_tokens", 4096))
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }
        kwargs[self._openai_token_param or "max_tokens"] = max_tokens
        temperature = self._cfg.get("temperature")
        if self._openai_supports_temperature and temperature is not None:
            kwargs["temperature"] = temperature

        effort = self._cfg.get("reasoning_effort", self._cfg.get("effort"))
        if self._openai_supports_reasoning_effort and effort:
            kwargs["reasoning_effort"] = effort

        # Prompt caching hints (see "Judge prompt caching" note near the top
        # of this class): our system prompts are large (~25K tokens) and
        # near-fully stable across calls, but calls are spaced out by
        # however long local MUT generation takes in between — long enough
        # that the SHORT default ("in_memory") cache retention often expires
        # before the next call arrives, and with no cache key set, OpenAI has
        # no extra hint to route repeat requests back to the same warm
        # backend. Both together are what was producing near-0% cache hits
        # even for back-to-back calls in the same review() retry loop.
        if self._openai_supports_prompt_cache_key:
            base_key = self._cfg.get("prompt_cache_key") or "ctl-reviewer:v1"
            kwargs["prompt_cache_key"] = f"{base_key}-{purpose}" if purpose else base_key
        if self._openai_supports_prompt_cache_retention:
            retention = self._cfg.get("prompt_cache_retention", "24h")
            if retention:
                kwargs["prompt_cache_retention"] = retention

        # `ctl_function_info` (see _FUNCTION_LOOKUP_NOTE and function_catalog.py)
        # is offered only on the purposes configured for it, so a call whose
        # system prompt does not document the tool never carries it either.
        use_tool = self.lookup_enabled_for(purpose) and self._openai_supports_tools
        if use_tool:
            kwargs["tools"] = [self.catalog.openai_tool()]
            kwargs["tool_choice"] = "auto"

        def one_turn():
            """One model turn, with the existing reasoning-exhaustion retries,
            and its usage recorded."""
            resp = self._create_openai_chat_completion(llm, kwargs)
            retry = 0
            while _is_length_exhausted(resp) and retry < _LENGTH_EXHAUSTION_RETRIES:
                retry += 1
                self._log_full(
                    f"[review-judge] purpose={purpose!r} model={model!r} exhausted its token budget "
                    f"on hidden reasoning with no visible answer (retry {retry}/{_LENGTH_EXHAUSTION_RETRIES}) "
                    f"-- retrying identical request"
                )
                print(f"[review-judge] Reasoning-token exhaustion (purpose={purpose!r}) "
                      f"-- retry {retry}/{_LENGTH_EXHAUSTION_RETRIES} …")
                resp = self._create_openai_chat_completion(llm, kwargs)
            if resp.usage:
                u = resp.usage
                # prompt_tokens_details.cached_tokens is the portion of prompt_tokens
                # served from OpenAI's prompt cache — a subset, not additional. Local
                # / self-hosted servers (e.g. vLLM) often leave this null.
                details = getattr(u, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", 0) if details else 0
                self._record_usage(
                    purpose,
                    input_tokens=u.prompt_tokens,
                    cached_tokens=cached or 0,
                    output_tokens=u.completion_tokens,
                )
            return resp

        resp = one_turn()

        # Tool-call rounds: each round is one model turn that may batch up to
        # max_queries_per_call lookups. On the last allowed round the tool is
        # withdrawn so the following turn has to produce the answer instead of
        # asking for more lookups.
        for round_index in range(self._max_lookup_rounds if use_tool else 0):
            if not self._openai_supports_tools:
                break
            tool_calls = getattr(resp.choices[0].message, "tool_calls", None)
            if not tool_calls:
                break
            kwargs["messages"].append(resp.choices[0].message.model_dump(exclude_none=True))
            for call in tool_calls:
                fn = getattr(call, "function", None)
                name = getattr(fn, "name", None)
                if name != FUNCTION_INFO_TOOL_NAME:
                    content = json.dumps({
                        "status": "error", "retry_allowed": False,
                        "error": f"unknown tool {name!r}",
                    })
                else:
                    content = self._run_lookup(
                        getattr(fn, "arguments", None), f"{purpose} round {round_index + 1}"
                    )
                kwargs["messages"].append({
                    "role": "tool", "tool_call_id": call.id, "content": content,
                })
            if round_index + 1 >= self._max_lookup_rounds:
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                self._log_full(
                    f"[function-lookup] {purpose}: lookup round cap "
                    f"({self._max_lookup_rounds}) reached — answering without the tool"
                )
            resp = one_turn()

        content = resp.choices[0].message.content or ""
        # Reasoning-tier models can spend the ENTIRE max_completion_tokens
        # budget on hidden reasoning tokens on a hard task, leaving nothing
        # for the visible answer — finish_reason=="length" with empty
        # content is the unambiguous signature (confirmed: two real
        # judge_corrected.jsonl records ended up with an empty
        # ```ctl\n\n``` fix() result, and one self_corrected.jsonl record
        # ended up with a completely empty tweak()ed prompt, both traced to
        # a call that reported generated tokens == max_completion_tokens
        # exactly, i.e. cut off mid-reasoning). The caller above already
        # retries a few times on this exact signature (_LENGTH_EXHAUSTION_RETRIES)
        # since it's been confirmed non-deterministic; raising here — rather
        # than returning "" silently — only fires once retries are
        # exhausted, and routes into each caller's EXISTING exception
        # handling: review()/fix() calls are wrapped by mut_validate.py's
        # skip-and-log except-blocks, tweak() calls now stop the whole run
        # (see mut_validate.py), and check_numeric_claim() calls fail open.
        finish_reason = getattr(resp.choices[0], "finish_reason", None)
        if not content.strip() and finish_reason == "length":
            reasoning_tokens = None
            if resp.usage:
                ctd = getattr(resp.usage, "completion_tokens_details", None)
                reasoning_tokens = getattr(ctd, "reasoning_tokens", None) if ctd else None
            raise RuntimeError(
                f"OpenAI call (purpose={purpose or 'unknown'!r}, model={model!r}) returned empty "
                f"content with finish_reason='length' — the model exhausted its "
                f"max_completion_tokens={max_tokens} budget"
                + (f" ({reasoning_tokens} reasoning tokens)" if reasoning_tokens is not None else "")
                + " before producing a visible answer. Consider raising max_completion_tokens "
                "or lowering reasoning_effort in the config."
            )
        return content

    # ------------------------------------------------------------------
    # OpenAI Responses API (/v1/responses)
    #
    # Needed for reasoning-tier models that reject function tools on
    # /v1/chat/completions (gpt-5.6-terra: "Function tools with
    # reasoning_effort are not supported ... use /v1/responses"). Same
    # behavior as the chat path — one tool loop, the same reasoning-exhaustion
    # retries, the same usage accounting and prompt-cache hints — expressed in
    # the Responses vocabulary:
    #
    #   system prompt        -> `instructions` (still the cached prefix)
    #   messages             -> `input` list of items
    #   max_completion_tokens-> `max_output_tokens`
    #   reasoning_effort     -> `reasoning={"effort": ...}`
    #   tool declaration     -> flat {"type":"function","name",...}, not nested
    #   assistant tool call  -> an output item with type == "function_call"
    #   tool result          -> {"type":"function_call_output","call_id",...}
    #   finish_reason=length -> status == "incomplete" + incomplete_details
    #
    # `store=False` keeps OpenAI from retaining the exchange server-side; the
    # documented consequence is that reasoning state must travel in the request
    # instead, which is why every output item (reasoning items included) is
    # appended back into `input` before the next turn.
    # ------------------------------------------------------------------

    def _create_openai_response(self, llm, kwargs: dict, max_flag_retries: Optional[int] = None):
        """responses.create() with the same provider-quirk handling as
        _create_openai_chat_completion: drop a parameter this model/server
        rejects (once, cached on self), and retry an intermittently
        moderation-flagged request."""
        from openai import BadRequestError

        if max_flag_retries is None:
            max_flag_retries = len(_MODERATION_BACKOFF_S) + 1
        for attempt in range(max_flag_retries):
            try:
                return llm.responses.create(**kwargs)
            except BadRequestError as e:
                msg = str(e)
                if "reasoning" in msg and "reasoning" in kwargs:
                    self._responses_supports_reasoning = False
                    kwargs.pop("reasoning")
                    continue
                if "temperature" in msg and "temperature" in kwargs:
                    self._responses_supports_temperature = False
                    kwargs.pop("temperature")
                    continue
                if "prompt_cache_key" in msg and "prompt_cache_key" in kwargs:
                    self._responses_supports_prompt_cache_key = False
                    kwargs.pop("prompt_cache_key")
                    continue
                if "prompt_cache_retention" in msg and "prompt_cache_retention" in kwargs:
                    self._responses_supports_prompt_cache_retention = False
                    kwargs.pop("prompt_cache_retention")
                    continue
                if ("tool" in msg or "function" in msg) and "tools" in kwargs:
                    self._responses_supports_tools = False
                    self._disable_tools_after_rejection(kwargs, msg, "/v1/responses")
                    continue
                if "invalid_prompt" in msg or "flagged as potentially violating" in msg:
                    flagged = "--- START flagged input ---\n" + json.dumps(
                        kwargs.get("input"), indent=2, default=str
                    ) + "\n--- END flagged input ---"
                    self._log_full(
                        f"[review-judge] /v1/responses request flagged by moderation "
                        f"(attempt {attempt + 1}/{max_flag_retries}):\n{msg}\n\n"
                        f"instructions:\n{kwargs.get('instructions')}\n\n{flagged}\n"
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

    def _call_openai_responses(self, system: str, user_message: str, purpose: str = "") -> str:
        llm = self._get_llm()
        model = self._cfg.get("model", "gpt-5.6-terra")
        max_tokens = self._cfg.get("max_completion_tokens", self._cfg.get("max_tokens", 4096))
        use_tool = self.lookup_enabled_for(purpose) and self._responses_supports_tools

        input_items: list = [{"role": "user", "content": user_message}]
        kwargs: dict = {
            "model": model,
            "instructions": system,
            "input": input_items,
            "max_output_tokens": max_tokens,
            "store": False,
        }
        temperature = self._cfg.get("temperature")
        if self._responses_supports_temperature and temperature is not None:
            kwargs["temperature"] = temperature
        effort = self._cfg.get("reasoning_effort", self._cfg.get("effort"))
        if self._responses_supports_reasoning and effort:
            kwargs["reasoning"] = {"effort": effort}
        # Same caching rationale as the chat path (see the class docstring).
        if self._responses_supports_prompt_cache_key:
            base_key = self._cfg.get("prompt_cache_key") or "ctl-reviewer:v1"
            kwargs["prompt_cache_key"] = f"{base_key}-{purpose}" if purpose else base_key
        if self._responses_supports_prompt_cache_retention:
            retention = self._cfg.get("prompt_cache_retention", "24h")
            if retention:
                kwargs["prompt_cache_retention"] = retention
        if use_tool:
            kwargs["tools"] = [self.catalog.responses_tool()]
            kwargs["tool_choice"] = "auto"

        def one_turn():
            resp = self._create_openai_response(llm, kwargs)
            retry = 0
            while _is_response_exhausted(resp) and retry < _LENGTH_EXHAUSTION_RETRIES:
                retry += 1
                self._log_full(
                    f"[review-judge] purpose={purpose!r} model={model!r} exhausted its token budget "
                    f"on hidden reasoning with no visible answer (retry {retry}/{_LENGTH_EXHAUSTION_RETRIES}) "
                    f"-- retrying identical request"
                )
                print(f"[review-judge] Reasoning-token exhaustion (purpose={purpose!r}) "
                      f"-- retry {retry}/{_LENGTH_EXHAUSTION_RETRIES} …")
                resp = self._create_openai_response(llm, kwargs)
            u = getattr(resp, "usage", None)
            if u:
                # input_tokens_details.cached_tokens is the portion of
                # input_tokens served from the prompt cache — a subset.
                details = getattr(u, "input_tokens_details", None)
                cached = getattr(details, "cached_tokens", 0) if details else 0
                self._record_usage(
                    purpose,
                    input_tokens=getattr(u, "input_tokens", 0) or 0,
                    cached_tokens=cached or 0,
                    output_tokens=getattr(u, "output_tokens", 0) or 0,
                )
            return resp

        resp = one_turn()

        for round_index in range(self._max_lookup_rounds if use_tool else 0):
            if not self._responses_supports_tools:
                break
            output = list(getattr(resp, "output", None) or [])
            tool_calls = [item for item in output if getattr(item, "type", None) == "function_call"]
            if not tool_calls:
                break
            # Every output item goes back, reasoning items included — required
            # for reasoning continuity with store=False.
            for item in output:
                kwargs["input"].append(
                    item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
                )
            for call in tool_calls:
                name = getattr(call, "name", None)
                if name != FUNCTION_INFO_TOOL_NAME:
                    content = json.dumps({
                        "status": "error", "retry_allowed": False,
                        "error": f"unknown tool {name!r}",
                    })
                else:
                    content = self._run_lookup(
                        getattr(call, "arguments", None), f"{purpose} round {round_index + 1}"
                    )
                kwargs["input"].append({
                    "type": "function_call_output",
                    "call_id": getattr(call, "call_id", None) or getattr(call, "id", None),
                    "output": content,
                })
            if round_index + 1 >= self._max_lookup_rounds:
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                self._log_full(
                    f"[function-lookup] {purpose}: lookup round cap "
                    f"({self._max_lookup_rounds}) reached — answering without the tool"
                )
            resp = one_turn()

        content = getattr(resp, "output_text", "") or ""
        # Same exhaustion-after-retries failure as the chat path: raise rather
        # than hand an empty review/fix back to the caller (see the long note
        # in _call_openai_chat).
        if not content.strip() and _is_response_exhausted(resp):
            reasoning_tokens = None
            u = getattr(resp, "usage", None)
            if u:
                otd = getattr(u, "output_tokens_details", None)
                reasoning_tokens = getattr(otd, "reasoning_tokens", None) if otd else None
            raise RuntimeError(
                f"OpenAI Responses call (purpose={purpose or 'unknown'!r}, model={model!r}) returned "
                f"no visible output with status='incomplete' (reason=max_output_tokens) — the model "
                f"exhausted its max_output_tokens={max_tokens} budget"
                + (f" ({reasoning_tokens} reasoning tokens)" if reasoning_tokens is not None else "")
                + " before producing a visible answer. Consider raising max_completion_tokens "
                "or lowering reasoning_effort in the config."
            )
        return content

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
        review_system = _build_review_system(
            effective_type, function_lookup=self.lookup_enabled_for("review")
        )
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
            raw = self._call(review_system, msg, purpose="review")
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
        """Fact-check ONE reported issue against CTL2's numeric widening chain
        (integer -> long -> number -> decimal). Returns True to keep the issue,
        False to drop it as a hallucination.

        Two stages, cheapest first:

        1. THE CATALOG. When the claim names a built-in whose documented return
           type is unambiguous, the claim stands or falls on a fact the catalog
           holds — no model call needed (see _catalog_numeric_verdict). This is
           free, deterministic, and identical across runs.
        2. THE MODEL, for what the catalog cannot answer: claims about bare
           operators, assignments and ternaries with no built-in involved, and
           claims whose function has several possible return types. Any catalog
           evidence gathered in stage 1 rides along, so the fallback reasons
           from documented signatures rather than recollection.

        Ambiguous or malformed model output fails open (keeps the issue) rather
        than silently discarding real signal."""
        evidence_block = ""
        if self.catalog is not None:
            try:
                returns, lines = _catalog_evidence(description, code, self.catalog)
                verdict = _catalog_numeric_verdict(returns, description)
            except Exception as e:  # a claim-parsing bug must never lose a review
                self._log_full(f"[numeric-check] catalog stage raised ({e}) — falling back to the model")
                returns, lines, verdict = {}, [], None
            if verdict is not None:
                summary = ", ".join(f"{n} -> {'/'.join(sorted(t))}" for n, t in returns.items())
                print(f"[review-judge] numeric claim settled by the function catalog "
                      f"(no model call): {'HALLUCINATION' if verdict is False else 'VALID'} — {summary}")
                self._log_full(
                    f"[numeric-check] catalog verdict={'VALID' if verdict else 'HALLUCINATION'} "
                    f"({summary}) for issue: {description}"
                )
                return verdict
            if lines:
                evidence_block = _CATALOG_EVIDENCE_BLOCK.format(
                    evidence="\n".join(f"- {line}" for line in lines)
                )
                self._log_full(
                    "[numeric-check] catalog could not settle the claim — asking the model "
                    f"with evidence: {'; '.join(lines)}"
                )
        raw = self._call(
            _NUMERIC_CLAIM_CHECK_SYSTEM,
            _NUMERIC_CLAIM_CHECK_USER.format(code=code, description=description)
            + evidence_block,
            purpose="numeric-check",
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
        fix_system = _build_fix_system(
            effective_type, function_lookup=self.lookup_enabled_for("fix")
        )
        user_msg = _FIX_USER.format(
            component_type=effective_type or "unknown",
            prompt=prompt,
            candidate=code,
            review_text=review.render(),
        )
        raw = self._call(fix_system, user_msg, purpose="fix")
        # Defensive cleanup: strip anything before a stray "===FINAL ANSWER==="
        # marker if the model emits one unprompted, then extract just the
        # fenced code — covers models that ramble in prose right up to the
        # code fence despite the instructions. Re-wrap in a fence so the
        # stored assistant turn matches the MUT's own fenced style regardless
        # of what the judge model actually produced.
        code = normalize_ctl(_extract_final_answer(raw))
        return f"```ctl\n{code}\n```"

    def tweak(self, prompt: str, component_type: str = "", business_domain: str = "") -> str:
        """Rewrite an SFT example's prompt into a different-but-structurally-
        similar task (new domain, new field names/types, a genuinely different
        business rule) so the MUT is tested on something it wasn't trained on
        verbatim. component_type is the type detected on the ORIGINAL prompt —
        passed in as the constraint the rewrite must preserve. business_domain
        is the externally-picked "Business domain: ...\\nRegion: ..." hint from
        pick_business_domain() — passed in as a hard constraint rather than
        left for the model to invent, since it otherwise reliably converges on
        the same few domains (see the module comment above pick_business_domain)."""
        # _TWEAK_SYSTEM is now a fixed string with no per-call interpolation
        # (component_type lives only in _TWEAK_USER) — maximizes the
        # byte-identical shared prefix across every tweak() call regardless
        # of component type, the same way _build_review_system orders its
        # stable content first for prompt-cache reuse.
        user_msg = _TWEAK_USER.format(
            component_type=component_type or "unknown",
            original_prompt=prompt,
            business_domain=business_domain or "(not specified — pick any business domain and region distinct from the original)",
        )
        raw = self._call(_TWEAK_SYSTEM, user_msg, purpose="tweak")
        return _extract_tweaked_prompt(raw)
