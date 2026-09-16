# Specification — Section 16: Graph-Execution Validation via CloverDX MCP

> Extends the CTL2 DPO Example Generator spec (`dpo_data_generator_spec.md`).
> This section replaces the abstract "Tier-1 deterministic validator" of §5 with a
> concrete, runtime-grade validation tier built on the `clover-server` MCP, and
> defines how the LLM judge orchestrates it.

---

## 16.1 Why runtime execution beats static validation

The original spec validated a candidate by compiling it. Compilation only proves
the CTL *parses and type-checks* — it says nothing about whether the logic is
correct. A Reformat that compiles cleanly can still map the wrong field, a RollUp
can emit per-record instead of per-group, a Filter can invert its condition. These
are exactly the CTL2 failure modes worth mining for DPO, and none of them are
caught by a compiler.

CloverDX graphs give us a stronger oracle: inject the candidate CTL into a
**skeleton graph** that feeds it deterministic synthetic input through real
metadata, run it on the server, and inspect the actual output records. A candidate
is "correct" only if it (a) validates, (b) executes without runtime error, and
(c) produces output that matches the expected result for the known input.

This turns validation into a three-level signal, each level a better `rejected`
than the last:

| Level | Detects | DPO contrast quality |
|---|---|---|
| L1 compile (detected at run-init; §18.5) | syntax, types, entry points | weak — model rarely emits this |
| L2 runtime (`job_run` + `job_get_log`) | null deref, type coercion, bad date tokens, lifecycle misuse | strong |
| L3 output mismatch (`job_get_tracking` + `job_get_edge_debug_data`) | wrong logic that runs cleanly | strongest — compiles, runs, still wrong |

L3 is the prize. A candidate that passes L1+L2 but fails L3 is the hardest, most
informative `rejected` we can manufacture.

---

## 16.2 Architecture: the judge as orchestrator

The LLM judge is no longer a one-shot grader. It becomes an **agent** that drives
the clover-server MCP through the validate→run→verify loop, then renders a verdict
backed by execution evidence. The local policy model still only *generates* the
candidate CTL; all orchestration is the judge's job, because it requires multi-step
tool reasoning and access to the full CTL2 reference.

```
                 ┌─────────────────────────────────────────────┐
                 │  Judge agent (Anthropic/OpenAI, full CTL ref)│
                 │  orchestrates clover-server MCP tools         │
                 └───────────────┬─────────────────────────────┘
   candidate CTL ───────────────►│
   (from local model)            │ 1. pick skeleton for component type
                                 │ 2. inject CTL into skeleton graph
                                 │ 3. job_validate          → L1
                                 │ 4. job_run + job_await   → L2
                                 │ 5. job_get_tracking      → L3 counts
                                 │ 6. job_get_edge_debug_data → L3 values
                                 │ 7. compare vs expected oracle
                                 ▼
                       verdict + failure_modes + evidence
```

> The diagram is conceptual. The **current** mechanism is file-driven (§16.3 / §18):
> the judge writes the candidate to `work/ctl/<TYPE>/transform.ctl` and calls `job_run`
> with params — it does **not** edit the graph or call a separate `job_validate`.

### 16.2.1 Execution-host model — SUPERSEDED by §18

> **Superseded.** The two options below (shared-skeleton property injection, and
> per-candidate graph clone) were the original design. Section 18 replaced both with
> **immutable, parameterized skeletons driven by external files + `job_run` params** —
> no graph editing, no per-candidate clone, concurrency-safe via a per-candidate
> `WORK_DIR`. The only surviving use of graph editing is the optional EXT_FILTER
> fallback (Externalization Brief §3.1 / §18.7). Historical text, for context:
>
> - *Option A — shared skeleton, `graph_edit_properties` injection:* fast, not
>   concurrency-safe.
> - *Option B — per-candidate clone + inject:* concurrency-safe but churny.
>
> Both are obsolete; the file-driven model is both edit-free and concurrency-safe.

---

## 16.3 CloverDX MCP operations — authoritative reference

Verified `clover-server` tool signatures and the exact call sequence for the
**file-driven** model (§18). All operations run against the **`DPOForge`** sandbox;
skeletons are immutable, so there is **no graph editing and no per-candidate clone**
(the lone exception is the optional EXT_FILTER fallback, §18.7). `job_run` returns an
integer `runId`; every follow-up tool takes that `runId`.

### 16.3.1 Setup (once per run, cached)
- `task_workflow_get(task="validate_and_run")` — load the authoritative procedure.
- `knowledge_list_resources()` → `knowledge_read_resource(uri="cloverdx://reference/ctl2")`
  — full CTL2 ref into the judge context (cache it). Optionally `…/graph-xml`.
- `sandbox_get_workspace_parameters(sandboxCode="DPOForge")` — resolve `${DATATMP_DIR}`
  so `WORK_DIR` paths are known.
- `sandbox_list_files(sandboxCode="DPOForge", sandboxPath="graph/skeletons")` — confirm
  skeletons; read the manifest from project knowledge for each component's file list,
  accepted params, output edge id(s), and diff comparison mode.

### 16.3.2 Per-example setup run — reference gate + oracle (§18.4)
- `sandbox_write_file(...)` the bundle into the live work tree:
  `work/meta/<TYPE>/*.fmt`, `work/ctl/<TYPE>/generate.ctl`, and
  `work/ctl/<TYPE>/transform.ctl` = the reference answer (CTL-normalized per §3.3).
- `job_run(jobFile="graph/skeletons/<TYPE>_skeleton.grf", sandboxCode="DPOForge",
  debug=true, params={"WORK_DIR":"${DATATMP_DIR}/forge/work", "JOIN_KEY":…,
  "JOIN_TYPE":…, "GROUP_KEY":…, "RECORDS_NUMBER":…, "SORTED_INPUT":…})` → `{runId, message}`.
  **`debug=true` is required** for edge data. `params` is a flat key→value object.
- `job_await(runId=<runId>, timeoutSeconds=60)`:
    - status != FINISHED_OK → `job_get_log(runId=<runId>)` → "setup_failed", discard.
    - FINISHED_OK → capture golden:
      `job_get_tracking(runId=<runId>, detailed=true)` (counts / port splits) and
      `job_get_edge_debug_data(runId=<runId>, edgeId="EdgeOut", recordCount=N)`
      (golden records). Then run the §18.4 oracle sanity assertion.

### 16.3.3 Per-candidate run (§18.5)
- `sandbox_write_file(... "work/ctl/<TYPE>/transform.ctl")` = candidate CTL, normalized
  per §3.3. Metadata + generator stay in place; only this file changes.
- `job_run(... same jobFile/sandboxCode, debug=true, params=<same as setup>)` → `runId`.
- `job_await(runId, timeoutSeconds=60)`:
    - status != FINISHED_OK → `job_get_log(runId)`; classify **L1** (CTL compile error at
      init) vs **L2** (runtime exception) by matching the log → rejected.
    - FINISHED_OK → `job_get_edge_debug_data(runId, edgeId="EdgeOut")` (or
      `"EdgeOut0"`/`"EdgeOut1"`/`"EdgeOut2"` for multi-port skeletons) and diff vs golden
      per §18.5.1 → **L3_mismatch** (rejected) or **L3_pass** (correct).

### 16.3.4 Edge-debug return shape (drives the diff)
`job_get_edge_debug_data` returns records as an array of field-name → **string** maps
(nulls as JSON null) plus a `metadata` array (name, type, nullable, format) per field.
Because every value is a string, the §18.5.1 diff must parse by type/`format`
(decimals/dates arrive as text) before comparing — never raw string equality. Page with
`fromRecord` / `recordCount`. There is **no** separate edge-metadata tool — the field
schema is already in this response.

### 16.3.5 Diagnosis tools (populate `failure_modes`)
- `job_get_log(runId)` — stack trace, failing component, exception class.
- `job_get_tracking(runId, detailed=true)` — where record counts diverge.
- `think(...)` — record root-cause reasoning (feeds the verdict `explanation`).
- `note_add(...)` / `note_read()` — accumulate findings across multi-edge checks.

### 16.3.6 Cleanup
The work tree is overwritten in place per example (no clones). Clear the component
subtree before the next example (§18.4 step 0). EXT_FILTER clone fallback only:
`sandbox_delete_file(...)` the scratch clone in a `finally`.

---

## 16.4 Skeleton graph catalogue

One skeleton per target component. Every skeleton follows the same shape:

```
DATA_GENERATOR (deterministic input)  →  <COMPONENT UNDER TEST>  →  TRASH(debugPrint) [+ extra ports]
```

Design rules common to all skeletons:
- **Deterministic input only.** The DATA_GENERATOR uses fixed arrays + index
  arithmetic (no `random*`), exactly like the existing `PersonGeneratorToTrash.grf`
  pattern already in MCPDemo. Determinism is what makes the oracle in §16.5 possible.
- **Terminal is TRASH with `debugPrint="true"`** so output is inspectable via edge
  debug without writing files. The judge reads the output edge, not a file.
- **The component-under-test has a fixed `id`** (e.g. `TRANSFORMER`, `FILTER0`,
  `ROLLUP0`) so the injection target is stable across candidates.
- **Metadata is explicit and small** — a handful of fields covering the types the
  failure modes touch (string, integer, decimal, date) so date-format and decimal
  upcasting bugs surface.
- The candidate CTL is injected into the one component's CTL attribute; the rest of
  the skeleton never changes.

### 16.4.1 Per-component skeleton specs

For each, the table gives: input the generator produces, the CTL attribute the
candidate is injected into, required CTL entry point(s) (per the `create_graph`
workflow §2.2), output ports to inspect, and the failure modes the skeleton is
designed to expose.

**FILTER** — *(note: there is no FILTER component; use `EXT_FILTER`)*
- Input: 100 records, integer `amount` spanning a known range, some nulls.
- Inject into: `EXT_FILTER` `filterExpression` (CTL boolean expression).
- Ports to inspect: Port 0 (accepted), Port 1 (rejected). Oracle asserts
  accepted + rejected = 100 and the accepted set matches the predicate.
- Failure modes: inverted condition, null-handling (`isnull` missing), off-by-one
  boundary, wrong field.

**DataGenerator** — `DATA_GENERATOR`
- This is the only component where the candidate *is* the generator itself.
- Inject into: `DATA_GENERATOR` `generate` — entry `function integer generate()`,
  returns `OK`/`STOP`.
- Skeleton: candidate generator → TRASH. Set `recordsNumber` to the count the
  task specifies.
- Ports to inspect: Port 0 (out). Oracle asserts row count == requested and field
  values follow the task's rule.
- Failure modes: wrong return code (never `STOP` → infinite/over-count), date token
  errors, off-by-one indices, wrong `recordsNumber` interaction.

**Reformat / Map** — `REFORMAT`
- Input: 50 records with string, integer, decimal, date fields.
- Inject into: `REFORMAT` `transform` — entry `function integer transform()`.
- Ports to inspect: Port 0 (out). Oracle asserts each output field equals the
  expected transform of the input.
- Failure modes: wrong `$out` field assignment, decimal/integer upcasting,
  date-format tokens, dropped records (wrong return value), null propagation.

**Join** — `EXT_HASH_JOIN` (unsorted, in-memory; the common case)
- Input: two generators — master (Port 0) with `id` 1..30, slave (Port 1) with a
  subset of matching keys plus some non-matching, to exercise inner/outer behaviour.
- Inject into: `EXT_HASH_JOIN` `transform` — entry `function integer transform()`;
  `joinKey` fixed in the skeleton (e.g. `$0.id=$1.id`).
- Ports to inspect: Port 0 (out). Oracle asserts matched count and merged field
  values; explicitly tests the "join produces 0 records" failure (key type mismatch).
- Failure modes: wrong `$in.0` vs `$in.1` field source, key-type mismatch
  awareness, null on unmatched outer side.

**Partition** — `PARTITION`
- Input: 90 records with a field designed to route into 3 buckets.
- Inject into: `PARTITION` `partitionSource` — entry
  `function integer getOutputPort()`.
- Ports to inspect: Ports 0,1,2. Oracle asserts the sum across ports == 90 and each
  bucket's membership matches the routing rule.
- Failure modes: returning out-of-range port index, wrong modulus/branch logic,
  records silently dropped.

**Normalizer** — `NORMALIZER` (1 record → N records)
- Input: 20 records each carrying a delimited/array field to explode.
- Inject into: `NORMALIZER` `normalize` — entries `function integer count()` and
  `function integer transform(integer idx)`.
- Ports to inspect: Port 0 (out). Oracle asserts total output == sum of per-record
  `count()` and exploded values are correct.
- Failure modes: `count()`/`transform(idx)` mismatch, idx off-by-one, returning
  wrong control code.

**Denormalizer** — `DENORMALIZER` (N records → 1 per group; requires sorted input)
- Input: 60 records pre-grouped by a key the generator emits in sorted order
  (no upstream SORT needed because the generator is deterministic and ordered —
  document this in `risks[]` so `job_plan` doesn't false-warn).
- Inject into: `DENORMALIZER` `denormalize` — entries `append()`, `transform()`,
  `clean()`.
- Ports to inspect: Port 0 (out). Oracle asserts one output row per group and
  aggregated fields are correct.
- Failure modes: lifecycle misuse (state not reset in `clean()`), wrong group
  boundary handling, emitting in `append` instead of `transform`.

**RollUp** — `ROLLUP` (group accumulation; a known CTL2 weak spot)
- Reference the existing `ROLLUP_Demo.grf` in MCPDemo as the canonical skeleton shape.
- Input: 60 records, sorted by group key, numeric field to aggregate.
- Inject into: `ROLLUP` `transform` — **all five** entries required:
  `initGroup(g)`, `updateGroup(g)`, `updateTransform(counter, g)`,
  `finishGroup(g)`, `transform(counter, g)`, with
  `groupAccumulatorMetadataId` wired to an accumulator `<Record>` whose name the
  CTL references via `<<AccMetaName>>`.
- Ports to inspect: Port 0 (out). Oracle asserts one row per group with correct
  aggregates.
- Failure modes (the high-value targets): accumulator metadata name mismatch
  (`"Error loading job file"` at validate), missing `updateTransform`, emitting
  per-record instead of per-group, group state not initialised in `initGroup`.

### 16.4.2 Skeleton provisioning

Build these once, validate each to a clean PASS, and commit them to the **`DPOForge`**
sandbox under `graph/skeletons/` (read-only source). They are then externalized per the
Externalization Brief (parameterized `WORK_DIR`, external `.fmt`/`.ctl`). Store a
manifest as a project-knowledge entry (`knowledge_project_store`, project `dpo-forge`)
mapping component type → skeleton path → injection id → entry points → output edge id(s)
→ accepted params → **diff comparison mode** (§18.5.1) → oracle id.

```
graph/skeletons/EXT_FILTER_skeleton.grf       (EXT_FILTER0)
graph/skeletons/DATAGEN_skeleton.grf          (DATA_GENERATOR0)
graph/skeletons/REFORMAT_skeleton.grf         (TRANSFORMER)
graph/skeletons/EXT_HASH_JOIN_skeleton.grf    (EXT_HASH_JOIN0)
graph/skeletons/PARTITION_skeleton.grf        (PARTITION0)
graph/skeletons/NORMALIZER_skeleton.grf       (NORMALIZER0)
graph/skeletons/DENORMALIZER_skeleton.grf     (DENORMALIZER0)
graph/skeletons/ROLLUP_skeleton.grf           (ROLLUP0)
```
Execution clones are not used; per-candidate variation is files + `job_run` params
(§18). The scratch sandbox is `DPOForge`; never run against `wrangler_shared_home` or
the demo graphs in `MCPDemo`.

---

## 16.5 The expected-output oracle

Runtime success (L2) is binary and easy. L3 — "is the output *correct*?" — needs an
expected result to compare against. Three strategies, in decreasing order of rigour:

1. **Reference-CTL oracle (preferred where a known-good answer exists).** The SFT
   `reference` answer is itself injected into the same skeleton and executed once;
   its output edge becomes the golden record set. The candidate's output is compared
   record-by-record against it. This reuses the very asset the DPO pipeline already
   has (the ground-truth `chosen`) and needs no hand-written expectations.
2. **Declarative assertion oracle.** For each skeleton, store a small assertion spec
   alongside the manifest: expected row count, port-split totals, and per-field
   predicates (e.g. "out.full_name == in.first + ' ' + in.last"). The judge checks
   `job_get_tracking` + sampled `job_get_edge_debug_data` against it. Cheaper to run,
   but the assertions must be authored per task family.
3. **Judge-as-oracle (fallback).** When neither exists, the judge inspects the input
   (deterministic, known) and the candidate's actual output and decides correctness
   using the full CTL2 reference. Weakest — it reintroduces judge subjectivity — but
   still grounded in *real executed output*, not the judge imagining what the code does.

Default: strategy 1 when `reference` is present (it almost always is in this
pipeline), falling back to 3. The comparison itself is deterministic set/row
equality, computed in the utility, not by the LLM, to avoid the judge mis-comparing.

---

## 16.6 Mapping execution outcomes to DPO labels

Extends §7 of the base spec. The judge's structured verdict now carries an
execution-evidence block:

```json
{
  "verdict": "correct | incorrect | partially_correct",
  "exec_level_reached": "L1_fail | L2_fail | L3_mismatch | L3_pass",
  "failure_modes": ["rollup_lifecycle", "date_format_token"],
  "evidence": {
    "validate": "PASS | <stage/error summary>",
    "run_status": "FINISHED_OK | ERROR | ABORTED",
    "tracking": "in=60 out=12 (expected 12 groups)",
    "log_excerpt": "<= 200 chars, first ERROR if any",
    "output_diff": "row 3: full_name expected 'A B' got 'B A'"
  },
  "confidence": 0.0,
  "explanation": "<= 60 words"
}
```

Rejection quality ranking for `best_vs_worst` pairing (§7.2) is refined to prefer
**`L3_mismatch` > `L2_fail` > `L1_fail`** — a candidate that compiled, ran, and
still produced wrong records is the most informative `rejected` of all.

The `failure_modes` enum stays fixed (existing CTL2 taxonomy) and is now
*evidence-backed*: a `rollup_lifecycle` tag is only emitted when the run log or
output diff actually demonstrates it, not when the judge merely suspects it from
reading the code.

---

## 16.7 Cost, isolation, and safety

- **Execution is the new cost center**, not just judge tokens. Each candidate is one
  server round-trip (`job_run` + `job_await` + tracking + edge-debug fetch). There is no
  separate `job_validate` per candidate — L1 compile errors surface at run init (§18.5),
  saving a round-trip. Cap `job_await` timeouts low (skeletons process ≤100 records, so
  30–60 s is generous).
- **Concurrency:** per-candidate `WORK_DIR` (file-driven model, §18.8) — no clones to
  leak. Sequential overwrite by default; optional worker-tree pool for parallelism.
- **Never run against `wrangler_shared_home`** (workflow rule) or the demo graphs in
  `MCPDemo` — all DPO execution happens in the dedicated `DPOForge` sandbox.
- **Resumability:** persist per-candidate `exec_level_reached` so an interrupted run
  doesn't re-execute already-judged candidates on the server.
- **Determinism caveat:** record the skeleton revision + server deployment
  (`server_deployment`) in the provenance file; a skeleton or engine change can move
  the oracle.

---

## 16.8 Implementation milestones (additive to §15)

8. Provision and validate the 8 skeleton graphs in the scratch sandbox; write the
   manifest as a project knowledge entry.
9. Build the injection+execute driver (shared and clone modes) over clover-server.
10. Implement the reference-CTL oracle (strategy 1) and deterministic row-compare.
11. Give the judge the orchestration system prompt (validate→run→verify) + CTL2 ref.
12. Wire `exec_level_reached` into pair construction and the refined rejection
    ranking.
13. Add execution metrics (per-level counts, timeouts, mean round-trip) to the W&B
    report.
