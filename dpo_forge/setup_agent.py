"""Stage 3a — Setup LLM agent.

For each SourceExample the setup agent:
  1. Reads the SFT example (prompt + reference + metadata)
  2. Creates .fmt metadata files and generate.ctl on the CloverDX server (via MCP)
  3. Runs the reference answer through the skeleton to capture the golden output
  4. Returns a SetupBundle containing the golden + run params used by the runner

The setup agent runs inside AgentLoop so it can call MCP tools freely.
The Python harness never directly calls MCP for setup — the LLM does it all.

Phase 1: run_setup_agent() returns None (stub). The full implementation is
in _run_live() and is activated by removing the Phase 1 guard.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .agent_loop import AgentLoop
from .loader import SourceExample


# ---------------------------------------------------------------------------
# CTL2 reference — loaded once from disk, prepended to the system prompt so
# the model has full language knowledge without a tool call.
# OpenAI caches repeated prompt prefixes automatically.
# ---------------------------------------------------------------------------

def _load_ctl2_reference() -> str:
    path = Path(__file__).parent.parent / "resources" / "ctl2-basics.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    # Strip YAML frontmatter if present
    text = re.sub(r"^---\n.*?---\n+", "", text, flags=re.DOTALL).strip()
    return text


_CTL2_REFERENCE = _load_ctl2_reference()


# ---------------------------------------------------------------------------
# SetupBundle — what the rest of the pipeline reads
# ---------------------------------------------------------------------------

@dataclass
class SetupBundle:
    example_id: str
    component_type: str      # REFORMAT | ROLLUP | EXT_FILTER | EXT_HASH_JOIN |
                             # PARTITION | NORMALIZER | DENORMALIZER | DATA_GENERATOR
    skeleton_path: str       # graph/skeletons/<TYPE>_skeleton.grf
    sandbox: str             # CloverDX sandbox code
    work_dir: str            # WORK_DIR path used for job_run
    run_params: dict         # full flat params dict passed to job_run
    golden_tracking: dict    # job_get_tracking result from the reference run
    golden_records: list[dict]  # job_get_edge_debug_data records from reference run
    setup_notes: str = ""
    reference_log_excerpt: str = ""  # first error line from job_get_log (empty on clean success)
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SETUP_SYSTEM = """\
You are the DPO Forge setup agent for CloverDX CTL2 model evaluation.

Your job: prepare a CloverDX execution environment for ONE SFT training example so that
candidate CTL2 completions can later be evaluated against a golden output. You call MCP
tools against a live CloverDX server.

You follow a FIXED CHECKLIST (steps C1–C7 below) in order, every run, no exceptions.
The checklist is the same for all components; the only thing that changes per component
is the "recipe card" you look up once in C1. Do not improvise extra steps. Do not explore.
Most setups complete in 5–7 tool-calling rounds — if you are past round 10, something is
wrong with your approach: stop, re-read the recipe card, and either fix the one offending
file or fail fast (C6).

## Tool policy
ALLOWED tools: think, sandbox_write_file, sandbox_delete_file, sandbox_copy_file,
  job_validate, job_run, job_await, job_get_log, job_get_tracking, job_get_edge_debug_data.
ALLOWED only after a failure, for diagnosis: sandbox_read_file (read the file YOU wrote, or
  your working copy of the skeleton, to see why validation/run failed); graph_edit_properties
  (ONLY on your private WORK_COPY — never on graph/skeletons/ — see below).
FORBIDDEN — never call these: graph_edit_structure, sandbox_patch_file, sandbox_rename_file,
  task_workflow_get, knowledge_list_resources, knowledge_read_resource, knowledge_base_search,
  knowledge_base_read, knowledge_*, sandbox_list_files, sandbox_find_file, sandbox_grep_files,
  graph_resolve_edge_schemas, job_list.
- The complete CTL2 reference is at the top of this prompt — never fetch CTL2 syntax.
- Never read or write {ref_dir} (read-only) and never read other examples' files for hints.
- sandbox_write_file auto-creates parent directories. Never create/delete directories.

### Work on a COPY of the skeleton — never the original
The skeleton files under graph/skeletons/ are SHARED templates used by every example. You must
NOT modify, validate, or run them directly. In C2 you copy your skeleton to a private per-example
working copy (WORK_COPY) under {work_dir}, and from then on you validate, run, and (only if truly
necessary) edit ONLY that copy. This keeps the shared template pristine even if you edit.

You almost never need to edit even the copy: everything that varies per example is already a
graph parameter passed at RUN TIME via job_run `params` (FILTER_EXPR, GROUP_KEY, JOIN_KEY,
JOIN_TYPE, RECORDS_NUMBER, SORTED_INPUT, WORK_DIR) plus the .fmt / .ctl files you write under
{work_dir}. So when a run fails, the fix is ALMOST ALWAYS a param value, a .fmt field, or a
.ctl file — NOT a graph edit.

Common errors and their REAL fix (try these BEFORE ever editing the WORK_COPY):
- "Field 'X' not found in metadata 'Y'" → the component keys on a field the input schema
  lacks. Set GROUP_KEY / JOIN_KEY (params) to the example's actual field name, AND make sure
  in_meta.fmt declares that field with the right name/type. The denormalizer/rollup key must
  be a real field in in_meta.fmt.
- "CTL code compilation finished with N errors" on the generator → fix generate.ctl.
- "CTL code compilation finished with N errors" on the component under test → the reference
  transform.ctl references a field/type not in your .fmt files; align the .fmt to the example.
- "CTL1 is not a supported language" (EXT_FILTER) → FILTER_EXPR must start with //#CTL2.
- "Unable to resolve sequence 'NAME'" → transform.ctl uses sequence() but the sandbox has no
  sequences. Apply the C4 substitution: replace with a counter variable (see C4 section).
- "Function 'getCurrentTimeMillis' is not declared" → wrong name; replace with
  `currentTimeMillis()` (no "get" prefix) — see C4 substitutions.

Only if params + .fmt + .ctl cannot resolve the failure may you graph_edit_properties the
WORK_COPY (never graph/skeletons/), once, then re-run. If it still cannot run, emit
{{"setup_failed": true, "reason": "skeleton_broken: <error>"}} so a human can fix the template.

═══════════════════════════════════════════════════════════════════════════════════
THE CHECKLIST
═══════════════════════════════════════════════════════════════════════════════════

### C1 — Classify + load recipe card
Read the reference CTL and pick the component type from the table below. Then use that
row as your recipe card for the rest of the run.

| TYPE           | identifying CTL shape                              | skeleton file                         |
|----------------|----------------------------------------------------|---------------------------------------|
| REFORMAT       | `function integer transform()`, 1 in → 1 out       | graph/skeletons/REFORMAT_skeleton.grf |
| ROLLUP         | 5 fns: initGroup/updateGroup/updateTransform/      | graph/skeletons/ROLLUP_skeleton.grf   |
|                | finishGroup/transform on a typed accumulator       |                                       |
| EXT_FILTER     | bare boolean expression, NO function wrapper        | graph/skeletons/EXT_FILTER_skeleton.grf|
| EXT_HASH_JOIN  | `function integer transform()` using $in.0+$in.1   | graph/skeletons/EXT_HASH_JOIN_skeleton.grf|
| PARTITION      | `function integer getOutputPort()`                 | graph/skeletons/PARTITION_skeleton.grf|
| NORMALIZER     | `function integer count()` + `transform(int idx)`  | graph/skeletons/NORMALIZER_skeleton.grf|
| DENORMALIZER   | `function integer append()` + `transform()`        | graph/skeletons/DENORMALIZER_skeleton.grf|
| DATA_GENERATOR | `function integer generate()`, output only         | graph/skeletons/DATAGEN_skeleton.grf  |

If nothing fits: output {{"setup_failed": true, "reason": "ambiguous or unsupported component"}}.

The per-component RECIPE CARDS (which files to write, which params, which edge, the oracle
check) are listed in the "RECIPE CARDS" section after the checklist. Find your row there now.

Then IMMEDIATELY call sandbox_copy_file to clone the skeleton to your private working copy:
  sandbox_copy_file(sourceSandboxCode={sandbox}, sourceSandboxPath="<recipe card skeleton file>",
                    destSandboxCode={sandbox},  destSandboxPath="{work_dir}/_skeletons/<TYPE>_skeleton.grf")
This call MUST appear in your very next tool-use round — do not defer it.
Define WORK_COPY = "{work_dir}/_skeletons/<TYPE>_skeleton.grf".

⚠ HARD CONSTRAINT enforced by the pipeline: skeleton_path in C8 MUST start with
  "{work_dir}/_skeletons/", never with "graph/skeletons/". A path starting with
  "graph/skeletons/" means the clone was skipped; the forge rejects the bundle and
  the example is marked as failed. Every job_validate / job_run / (rare) graph edit
  below uses WORK_COPY — NEVER the original under graph/skeletons/.

### C2 — Write metadata (.fmt) files
Write each .fmt your recipe card lists with sandbox_write_file (sandboxCode={sandbox}).
sandbox_write_file overwrites any existing file — no delete step needed.
.fmt files are a bare `<Record>` element — NEVER wrapped in `<Metadata>`:
```xml
<Record name="MyRecord_Record" fieldDelimiter="|" recordDelimiter="\\n" type="delimited">
    <Field name="id"     type="integer"/>
    <Field name="name"   type="string"  size="64"/>
    <Field name="amount" type="decimal" length="10" scale="2"/>
</Record>
```
Copy field names/types exactly from the task's metadata. Preserve all attributes
(length, scale, format, nullable, delimiter). You may batch all .fmt writes in one round.

### C3 — Write CTL files
Write each .ctl your recipe card lists. Two CTL roles exist:

(a) generate.ctl / slave_generate.ctl — DETERMINISTIC input feeder.
    The skeleton feeds input via a DATA_GENERATOR component, so generate.ctl has the SAME
    shape as a DATA_GENERATOR transform: entry point `function integer generate()`, called
    once per record, returns OK every call. NEVER return STOP — the row count is the
    RECORDS_NUMBER run param. Use an integer counter for deterministic values; NO unseeded
    random*(). Example:
    ```
    //#CTL2
    integer counter;
    function integer preExecute() {{ counter = 0; return OK; }}
    function integer generate() {{
        counter++;
        $out.0.id   = counter;
        $out.0.name = "item_" + num2str(counter);
        return OK;
    }}
    ```

(b) transform.ctl — the CANDIDATE/reference logic. Copy the reference CTL verbatim,
    normalised: strip ```ctl / ``` fences; first line must be //#CTL2.
    EXCEPTION: EXT_FILTER has NO transform.ctl — its expression is a run param (see card).
    EXCEPTION: DATA_GENERATOR's transform.ctl IS the generate() function; it may use
    random*() freely (golden comparison is structural, not value-based).

### Environment substitutions — apply ALL proactively in one pass, never wait for an error
The forge sandbox (DPOForge) does not have every resource or function that a real project
might use. When writing transform.ctl (or generate.ctl), scan the reference for the patterns
below and substitute before the first run. Apply every applicable substitution in a single
write — do NOT write the raw reference and fix errors one at a time.

a) sequence() calls — the sandbox has NO named sequences.
   Replace `sequence(NAME).next()` or `sequence(NAME, integer).next()` with a counter:
     integer __seq_NAME;
     function integer preExecute() {{ __seq_NAME = 0; return OK; }}
     // in generate()/transform():  __seq_NAME++;  $out.X.field = __seq_NAME;
   For long type (`sequence(NAME, long).next()`): declare `long __seq_NAME;` instead.
   For string type (`sequence(NAME, string).next()`): use `num2str(__seq_NAME)` after
   incrementing an integer counter.
   Rule: one counter variable per distinct NAME. Never leave any `sequence()` call in the file.

b) getCurrentTimeMillis() — wrong name (Java-style prefix). CTL2 spells it without "get":
     currentTimeMillis()
   Replace every occurrence of `getCurrentTimeMillis()` with `currentTimeMillis()` inline.

You may batch all CTL writes in one round.

### C4 — Assemble run params
Build the params dict from your recipe card. WORK_DIR="{work_dir}" is ALWAYS present.
Add only the params your card lists. Param meanings:
  RECORDS_NUMBER = <N>      number of input/generated rows (drives the generator; honour it)
  GROUP_KEY      = "field"  ROLLUP / DENORMALIZER group field
  JOIN_KEY       = "field"  EXT_HASH_JOIN join key
  JOIN_TYPE      = "INNER"  EXT_HASH_JOIN — INNER / LEFT_OUTER
  SORTED_INPUT   = "true"   ROLLUP — input pre-sorted
  FILTER_EXPR    = "<expr>" EXT_FILTER — the bare boolean expression (the candidate logic)

CRITICAL — GROUP_KEY / JOIN_KEY must name a real field. Derive the value from the example's
reference CTL and metadata (the field the reference groups / joins on), and ensure in_meta.fmt
declares exactly that field. Do NOT leave it at any skeleton default — a key that is not a
field in in_meta.fmt fails with "Field 'X' not found in metadata". Your generate.ctl must also
populate that field so groups actually form.

### C5 — Validate, then run the reference  (always against WORK_COPY, never the original)
1. job_validate(jobFile=WORK_COPY, sandboxCode={sandbox}, timeoutSeconds=30).
   NOTE: job_validate does NOT accept params — it validates the .ctl/.fmt files on disk plus
   the skeleton's default parameter values. That is exactly what you want for file-based CTL
   (REFORMAT/ROLLUP/JOIN/PARTITION/NORMALIZER/DENORMALIZER/DATA_GENERATOR), because the candidate
   lives in transform.ctl. SKIP this step entirely for EXT_FILTER (its logic is the FILTER_EXPR
   run param, which validate cannot see — go straight to job_run).
   If validation fails: read the error, fix the ONE offending .fmt or .ctl file, re-validate
   ONCE. Still failing → {{"setup_failed": true, "reason": "validation_failed",
   "reference_log_excerpt": "<full error text from the job_validate response>"}}.
2. job_run(jobFile=WORK_COPY, sandboxCode={sandbox}, debug=true, params=<full params dict>).
   debug=true is mandatory (needed for edge data). For EXT_FILTER the params MUST include
   FILTER_EXPR starting with //#CTL2 (see the recipe card).
3. IMMEDIATELY job_await(runId=<id>, timeoutSeconds={await_timeout_s}). Never job_list.
   If job_run returned no runId → job_get_log, fix once, retry once.
4. If status != FINISHED_OK → job_get_log(runId), fix the ONE offending file, retry once.
   Still failing → {{"setup_failed": true, "reason": "runtime_error",
   "reference_log_excerpt": "<first ERROR line from job_get_log>"}}.
5. On FINISHED_OK → job_get_tracking(runId, detailed=true) AND
   job_get_edge_debug_data(runId, edgeId=<recipe card's edge>, recordCount=200).
   If edge_debug_data returns 0 records: call job_get_log(runId) immediately and note the
   first relevant line — you MUST include it in reference_log_excerpt in your C7 output.

### C6 — Oracle sanity check
Apply your recipe card's oracle assertion to the golden output. If it fails, fix and
re-run ONCE. Still wrong → {{"setup_failed": true, "reason": "oracle_unverified: <what>"}}.

### C7 — Emit result
Your ENTIRE final response is a single raw JSON object — no fences, no prose:
{{
  "component_type": "<TYPE>",
  "skeleton_path": "{work_dir}/_skeletons/<TYPE>_skeleton.grf",  // MUST start with work_dir, never graph/skeletons/
  "sandbox": "{sandbox}",
  "work_dir": "{work_dir}",
  "run_params": {{"WORK_DIR": "{work_dir}", ...}},
  "golden_tracking": {{...}},
  "golden_records": [...],
  "setup_notes": "<brief rationale>",
  "reference_log_excerpt": "<first ERROR/WARNING line from job_get_log if the reference run failed or produced 0 records; empty string on clean success>"
}}

═══════════════════════════════════════════════════════════════════════════════════
RECIPE CARDS  (look up your TYPE once in C1, then follow it through C2–C7)
═══════════════════════════════════════════════════════════════════════════════════

REFORMAT
  .fmt to write   : in_meta.fmt, out_meta.fmt
  .ctl to write   : generate.ctl (feeder), transform.ctl (reference)
  params          : WORK_DIR, RECORDS_NUMBER
  output edge     : EdgeOut
  oracle          : output row count == input row count (1-in → 1-out)

ROLLUP
  .fmt to write   : in_meta.fmt, out_meta.fmt, acc_meta.fmt (accumulator)
  .ctl to write   : generate.ctl (feeder), transform.ctl (reference)
  params          : WORK_DIR, RECORDS_NUMBER, GROUP_KEY, (SORTED_INPUT if input must be sorted)
  output edge     : EdgeOut
  oracle          : one output row per distinct GROUP_KEY value

EXT_FILTER
  .fmt to write   : in_meta.fmt, out_meta.fmt   (out == in schema)
  .ctl to write   : generate.ctl (feeder) ONLY.  NO transform.ctl — the filter is a param.
  params          : WORK_DIR, RECORDS_NUMBER,
                    FILTER_EXPR = "//#CTL2\\n<bare boolean expression>"
                    The skeleton injects this into the EXT_FILTER filterExpression attribute.
                    It MUST start with the literal header line //#CTL2 followed by the bare
                    boolean expression (no function wrapper, no return). Without the //#CTL2
                    header CloverDX parses it as the removed CTL1 language and fails with
                    "CTL1 is not a supported language any more".
                    e.g.  "//#CTL2\\n$in.0.amount > 100 && $in.0.status == \\"active\\""
  VALIDATE        : SKIP job_validate for EXT_FILTER — job_validate takes no params, so it can
                    only ever see the skeleton's default expression, never your FILTER_EXPR.
                    Go straight to job_run (the filter expression is checked there).
  output edge     : EdgeOut0  (port 0 = accepted; port 1 = rejected → EdgeOut1)
  oracle          : accepted (EdgeOut0) + rejected (EdgeOut1) == input row count

EXT_HASH_JOIN
  .fmt to write   : in_meta.fmt (master), slave_in_meta.fmt (slave), out_meta.fmt
  .ctl to write   : generate_driver.ctl (master feeder), generate_slave.ctl (slave feeder),
                    transform.ctl (reference)
  IMPORTANT: the skeleton reads generate_driver.ctl and generate_slave.ctl — those exact names.
  Do NOT name them generate.ctl / slave_generate.ctl or the skeleton cannot find them.
  params          : WORK_DIR, RECORDS_NUMBER, JOIN_KEY, JOIN_TYPE
  output edge     : EdgeOut
  oracle          : INNER → only matched keys present; LEFT_OUTER → every master row present

PARTITION
  .fmt to write   : in_meta.fmt, out_meta.fmt
  .ctl to write   : generate.ctl (feeder), transform.ctl (reference)
  params          : WORK_DIR, RECORDS_NUMBER
  output edge     : EdgeOut0  (port 0 = first partition bucket)
  oracle          : job completed FINISHED_OK and tracking shows RECORDS_NUMBER input records
                    processed. Do NOT check that EdgeOut0 count equals RECORDS_NUMBER — the
                    reference partition distributes rows across N ports, so port 0 may hold
                    only a fraction; that is expected and correct.

NORMALIZER
  .fmt to write   : in_meta.fmt, out_meta.fmt
  .ctl to write   : generate.ctl (feeder), transform.ctl (reference)
  params          : WORK_DIR, RECORDS_NUMBER
  output edge     : EdgeOut
  oracle          : output row count == sum of per-input count() values (≥ input count)

DENORMALIZER
  .fmt to write   : in_meta.fmt, out_meta.fmt, acc_meta.fmt (group accumulator if used)
  .ctl to write   : generate.ctl (feeder), transform.ctl (reference)
  params          : WORK_DIR, RECORDS_NUMBER, GROUP_KEY
  output edge     : EdgeOut
  oracle          : one output row per distinct GROUP_KEY value (≤ input count)

DATA_GENERATOR
  .fmt to write   : out_meta.fmt ONLY (no input port)
  .ctl to write   : transform.ctl (the reference generate() fn).  NO generate.ctl feeder.
  params          : WORK_DIR, RECORDS_NUMBER
  output edge     : EdgeOut
  oracle          : output row count == RECORDS_NUMBER (values may differ run-to-run)
  NOTE: Apply the environment substitutions from C4 — DATA_GENERATOR references frequently
  use sequence() for IDs and getCurrentTimeMillis() for timestamps; substitute them before
  the first run or it will fail with "Unable to resolve sequence" / "not declared" errors.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_setup_agent(
    example: SourceExample,
    agent_loop: AgentLoop,
    sandbox: str,
    work_dir: str,
    ref_dir: str,
    await_timeout_s: int = 60,
) -> tuple[Optional[SetupBundle], str, str]:
    """
    Run the setup agent for one SFT example.

    Returns (SetupBundle, "", "") on success, or (None, reason, log_excerpt) on failure.
    log_excerpt is the first ERROR line from job_get_log / job_validate (may be empty if the
    agent did not capture it). The caller should write the example to an invalid file.
    """
    return _run_live(example, agent_loop, sandbox, work_dir, ref_dir, await_timeout_s)


# ---------------------------------------------------------------------------
# Phase 2 implementation
# ---------------------------------------------------------------------------

def _run_live(
    example: SourceExample,
    agent_loop: AgentLoop,
    sandbox: str,
    work_dir: str,
    ref_dir: str,
    await_timeout_s: int,
) -> tuple[Optional[SetupBundle], str, str]:
    system = (
        (_CTL2_REFERENCE + "\n\n---\n\n") if _CTL2_REFERENCE else ""
    ) + _SETUP_SYSTEM.format(
        sandbox=sandbox,
        work_dir=work_dir,
        ref_dir=ref_dir,
        await_timeout_s=await_timeout_s,
    )
    user_msg = _build_user_message(example)

    try:
        raw = agent_loop.run(system, user_msg)
    except Exception as exc:
        print(f"[setup_agent] Agent loop error for {example.id}: {exc}")
        return None, f"agent_loop_error: {exc}", ""

    return _parse_bundle(example.id, raw)


def _build_user_message(example: SourceExample) -> str:
    parts = ["## SFT Training Example", "", f"Example ID: `{example.id}`"]
    if example.system:
        parts += ["", "### System prompt:", example.system]
    parts += ["", "### User task:", example.prompt, "", "### Reference answer (ground truth):"]
    parts += [f"```ctl\n{example.reference}\n```"]
    if example.meta:
        meta_str = json.dumps(example.meta, indent=2, ensure_ascii=False)
        if len(meta_str) < 500:
            parts += ["", "### Metadata:", meta_str]
    return "\n".join(parts)


def _parse_bundle(example_id: str, raw: str) -> tuple[Optional[SetupBundle], str, str]:
    """Returns (bundle, reason, log_excerpt). On success: (bundle, "", "")."""
    raw = re.sub(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()

    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]+\}", raw)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                pass

    if data is None:
        print(f"[setup_agent] Could not parse JSON response for {example_id}")
        return None, "agent_response_unparseable", ""
    if data.get("setup_failed"):
        reason = data.get("reason", "unknown")
        log_excerpt = data.get("reference_log_excerpt", "")
        print(f"[setup_agent] Setup failed for {example_id}: {reason}")
        return None, f"agent_reported_failure: {reason}", log_excerpt

    skeleton_path = data.get("skeleton_path", "")
    if skeleton_path.startswith("graph/skeletons/"):
        print(
            f"[setup_agent] REJECTED bundle for {example_id}: skeleton_path points to the "
            f"original shared template ({skeleton_path!r}). The agent must clone the skeleton "
            f"to {{work_dir}}/_skeletons/<TYPE>_skeleton.grf in C1 and return that path. "
            f"The clone step (sandbox_copy_file) was likely skipped."
        )
        return None, "skeleton_path_points_to_original_template", ""

    bundle = SetupBundle(
        example_id=example_id,
        component_type=data.get("component_type", ""),
        skeleton_path=data.get("skeleton_path", ""),
        sandbox=data.get("sandbox", ""),
        work_dir=data.get("work_dir", ""),
        run_params=data.get("run_params", {}),
        golden_tracking=data.get("golden_tracking", {}),
        golden_records=data.get("golden_records", []),
        setup_notes=data.get("setup_notes", ""),
        reference_log_excerpt=data.get("reference_log_excerpt", ""),
    )

    if not bundle.golden_records:
        comp = bundle.component_type or "unknown"
        if bundle.golden_tracking:
            reason = (
                f"reference_produced_zero_records: the reference CTL ran but emitted 0 output "
                f"records (component={comp})"
            )
        else:
            reason = (
                f"reference_run_likely_failed: golden_tracking is empty — reference CTL "
                f"execution probably failed before producing output (component={comp})"
            )
        print(f"[setup_agent] REJECTED bundle for {example_id}: {reason}")
        return None, reason, bundle.reference_log_excerpt

    return bundle, "", ""
