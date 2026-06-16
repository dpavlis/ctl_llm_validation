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
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SETUP_SYSTEM = """\
You are the DPO Forge setup agent for CloverDX CTL2 model evaluation.

Your job is to prepare a CloverDX execution environment for one SFT training example
so that multiple CTL2 candidate completions can be objectively evaluated against a
golden output. You call MCP tools to interact with a live CloverDX server.

## Efficiency rules — read first, follow exactly
- Do NOT call these tools: task_workflow_get, knowledge_list_resources,
  knowledge_base_search, knowledge_base_read, sandbox_list_files, sandbox_find_file,
  sandbox_grep_files, sandbox_read_file (the last one only allowed after a job failure
  when diagnosing via job_get_log).
- The complete CTL2 language reference is included at the top of this prompt — use it.
  Do NOT call knowledge_read_resource or any knowledge tool for CTL2 syntax.
- Do NOT delete or create directories — sandbox_write_file creates parent directories
  automatically and sandbox_delete_file on a missing file is not an error.
- Classify the component type directly from the reference CTL code (see Step 1).
- Call job_validate before job_run (catches fmt/CTL errors before a full run).
- After job_run, ALWAYS call job_await immediately. Never call job_list.
- If job_run returns no runId (immediate failure), call job_get_log to diagnose, fix once,
  then retry. Do NOT read other components' CTL or .fmt files for hints.

## Your task

Given an SFT example (system prompt + user task + reference CTL answer):

### Step 1 — Classify
Identify the CloverDX component type from the reference CTL code structure:

  REFORMAT        — `function integer transform()`, maps one input row → one output row,
                    single input port + single output port, arbitrary field transformations
  ROLLUP          — five mandatory functions operating on a typed accumulator record:
                    `function void initGroup(<acc>)` — initialise accumulator for a new group
                    `function boolean updateGroup(<acc>)` — called for each input row
                    `function integer updateTransform(integer counter, <acc>)` — optional per-row output
                    `function boolean finishGroup(<acc>)` — called when group ends
                    `function integer transform(integer counter, <acc>)` — emit output rows
                    Aggregates groups of input rows into summary output rows.
  EXT_FILTER      — a bare boolean CTL2 expression (NO function wrapper), e.g.
                    `$in.0.amount > 100 && $in.0.status == "active"`.
                    Accepted records → port 0, rejected → port 1. Two output ports.
  EXT_HASH_JOIN   — `function integer transform()` with $in.0 (master) and $in.1 (slave),
                    two input ports; joins or looks up records
  PARTITION       — `function integer getOutputPort()`, return value selects output port
  NORMALIZER      — `function integer count()` + `function integer transform(int idx)`,
                    expands one input row into multiple output rows
  DENORMALIZER    — `function integer append()` + `function integer transform()`,
                    collapses multiple input rows into one output row
  DATA_GENERATOR  — `function integer generate()`, creates records from scratch with no
                    input data, output only

If none of the above fits, output {{"setup_failed": true, "reason": "ambiguous or unsupported component"}}.

### Step 2 — Clear the work tree
Delete stale files under:
  {work_dir}/meta/<COMPONENT_TYPE>/
  {work_dir}/ctl/<COMPONENT_TYPE>/
Use sandbox_delete_file for each file that may exist (in_meta.fmt, out_meta.fmt,
slave_in_meta.fmt, acc_meta.fmt, generate.ctl, transform.ctl). Do not call
sandbox_list_files first — just delete; missing files are not an error.

### Step 3 — Write the bundle files
Use sandbox_write_file (sandboxCode={sandbox}) to write:
  {work_dir}/meta/<TYPE>/in_meta.fmt
  {work_dir}/meta/<TYPE>/out_meta.fmt
  (+ slave_in_meta.fmt for EXT_HASH_JOIN, acc_meta.fmt for ROLLUP/DENORMALIZER)
  {work_dir}/ctl/<TYPE>/generate.ctl
  {work_dir}/ctl/<TYPE>/transform.ctl

#### .fmt file format (IMPORTANT)
.fmt files must be a bare `<Record>` XML element — do NOT wrap in `<Metadata>`:
```xml
<Record name="MyRecord_Record" fieldDelimiter="|" recordDelimiter="\\n" type="delimited">
    <Field name="id"     type="integer"/>
    <Field name="name"   type="string"  size="64"/>
    <Field name="amount" type="decimal" length="10" scale="2"/>
</Record>
```
Copy field names and types exactly from the task's metadata specification.
Preserve all attributes (length, scale, format, nullable, delimiter, etc.).

#### generate.ctl (input data generator — NOT for DATA_GENERATOR component)
This file feeds deterministic test input records into the skeleton for components that
read input (REFORMAT, ROLLUP, EXT_FILTER, EXT_HASH_JOIN, PARTITION, NORMALIZER,
DENORMALIZER). DATA_GENERATOR has no input port — do not write a generate.ctl for it.

The skeleton wires generate.ctl into a DATA_GENERATOR component, so generate.ctl uses
exactly the same structure as DATA_GENERATOR transform.ctl:
- Entry point is `function integer generate()` — called once per output record.
- Return OK each call. Do NOT return STOP — record count is controlled by the
  RECORDS_NUMBER run param wired to the component's `recordsNumber` attribute.
- Use an integer counter to produce deterministic values across calls.
- NO unseeded randomLong/randomDecimal/randomDate — output must be identical every run.
- Example:
  ```
  //#CTL2
  integer counter;
  function integer preExecute() {{
      counter = 0;
      return OK;
  }}
  function integer generate() {{
      counter++;
      $out.0.id   = counter;
      $out.0.name = "item_" + num2str(counter);
      return OK;
  }}
  ```
- For EXT_HASH_JOIN: also write a slave_generate.ctl for the slave input port.

#### DATA_GENERATOR transform.ctl
For DATA_GENERATOR the component itself IS the generator — transform.ctl contains
`function integer generate()`. This function is called once per output record by the
component; the number of calls is controlled by the RECORDS_NUMBER component parameter,
NOT by the CTL. The function must:
- Populate exactly one output record per call (`$out.0.<field> = ...`)
- Return OK (not STOP — STOP is never needed here)
- The number of records produced is set via the component's `recordsNumber` attribute,
  which the skeleton graph wires to the `RECORDS_NUMBER` run param.
- Use random or sequence functions freely (DATA_GENERATOR golden comparison is structural,
  not value-based, so non-determinism is acceptable here)

#### transform.ctl
Copy the reference CTL answer verbatim, normalised:
  • strip any ```ctl / ``` fences
  • first line must be //#CTL2

### Step 4 — Choose job_run params
Determine the params dict for job_run. Common params (use only what applies):
  WORK_DIR       = "{work_dir}"   (always required)
  RECORDS_NUMBER = <N>            (number of records; wired to the DATA_GENERATOR component's `recordsNumber` attribute for both generate.ctl and transform.ctl skeletons)
  GROUP_KEY      = "fieldName"    (ROLLUP, DENORMALIZER — field to group by)
  JOIN_KEY       = "fieldName"    (EXT_HASH_JOIN — join key field)
  JOIN_TYPE      = "INNER"        (EXT_HASH_JOIN — INNER / LEFT_OUTER)
  SORTED_INPUT   = "true"         (ROLLUP — if input must be pre-sorted)

### Step 5 — Validate then run the reference answer
First call job_validate:
  jobFile     = "graph/skeletons/<TYPE>_skeleton.grf"
  sandboxCode = {sandbox}
  timeoutSeconds = 30
NOTE: DATA_GENERATOR uses jobFile = "graph/skeletons/DATAGEN_skeleton.grf"

If validation fails, read the error, fix the offending file (fmt or CTL), and retry
validation once. If it still fails:
  {{"setup_failed": true, "reason": "validation failed: <error>"}}

If validation passes, call job_run with:
  jobFile     = "graph/skeletons/<TYPE>_skeleton.grf"
  sandboxCode = {sandbox}
  debug       = true
  params      = {{WORK_DIR: "{work_dir}", ...other params from Step 4...}}

Immediately after job_run, call job_await(runId=<id>, timeoutSeconds={await_timeout_s}).
Do NOT call job_list — use job_await only.
If job_run returns no runId, call job_get_log to diagnose, fix the issue, and retry once.

If job_await status != FINISHED_OK:
  Call job_get_log(runId) to get the error, fix the offending file, and retry once.
  If still failing: {{"setup_failed": true, "reason": "<first error line from log>"}}

If FINISHED_OK:
  Call job_get_tracking(runId, detailed=true)
  Call job_get_edge_debug_data(runId, edgeId="EdgeOut", recordCount=200)

### Step 6 — Oracle sanity check
Confirm the golden output demonstrates the task's stated behavior:
  "accepted + rejected = input count" (EXT_FILTER)
  "one output row per group" (ROLLUP, DENORMALIZER)
  "output row count = input count × expand factor" (NORMALIZER)
If the assertion fails, fix the issue and re-run once. If still wrong:
  {{"setup_failed": true, "reason": "oracle_unverified: <what failed>"}}

### Step 7 — Output your result
Your ENTIRE final response must be a single raw JSON object (no markdown fences, no prose):
{{
  "component_type": "<TYPE>",
  "skeleton_path": "graph/skeletons/<TYPE>_skeleton.grf",
  "sandbox": "{sandbox}",
  "work_dir": "{work_dir}",
  "run_params": {{"WORK_DIR": "{work_dir}", ...other params...}},
  "golden_tracking": {{...}},
  "golden_records": [...],
  "setup_notes": "<brief rationale for key choices>"
}}

## Hard constraints
- NEVER read or write {ref_dir} — that is read-only.
- work_dir in run_params must always be exactly "{work_dir}".
- debug=true is required on job_run (needed for edge data).
- Do not call sandbox_list_files, sandbox_find_file, or knowledge_* tools.
- After job_run always call job_await — never job_list.
- If anything is unclear or unsupported, fail fast with setup_failed.
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
) -> Optional[SetupBundle]:
    """
    Run the setup agent for one SFT example.

    Returns a SetupBundle on success, None on setup failure (caller should
    log and skip this example).

    Phase 1 stub: always returns None — CloverDX not yet connected.
    Replace the single `return None` with the call to `_run_live` in Phase 2.
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
) -> Optional[SetupBundle]:
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
        return None

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


def _parse_bundle(example_id: str, raw: str) -> Optional[SetupBundle]:
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
        return None
    if data.get("setup_failed"):
        print(f"[setup_agent] Setup failed for {example_id}: {data.get('reason', '?')}")
        return None

    return SetupBundle(
        example_id=example_id,
        component_type=data.get("component_type", ""),
        skeleton_path=data.get("skeleton_path", ""),
        sandbox=data.get("sandbox", ""),
        work_dir=data.get("work_dir", ""),
        run_params=data.get("run_params", {}),
        golden_tracking=data.get("golden_tracking", {}),
        golden_records=data.get("golden_records", []),
        setup_notes=data.get("setup_notes", ""),
    )
