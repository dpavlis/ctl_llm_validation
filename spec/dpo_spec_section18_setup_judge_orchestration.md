# Specification — Section 18: Setup & Judge Orchestration with Externalized Skeletons

> Extends the CTL2 DPO Example Generator spec. Supersedes the "clone-and-inject"
> mechanics sketched in §16.2/§16.3 now that skeletons are **immutable and
> file-driven** (see the Externalization Brief). This section tells the Python
> utility builder exactly how the harness and the LLMs set up and execute each
> verification.

---

## 18.1 Execution model: a shared working tree, overwritten in place

Every skeleton `.grf` is immutable and reads its swappable parts from a working tree
resolved by the `WORK_DIR` graph parameter, keyed by asset kind and component type:

```
${WORK_DIR}/meta/<COMPONENT_TYPE>/in_meta.fmt        (+ out_meta, acc_meta, slave_in_meta)
${WORK_DIR}/ctl/<COMPONENT_TYPE>/generate.ctl        input generator
${WORK_DIR}/ctl/<COMPONENT_TYPE>/transform.ctl       the CTL UNDER TEST (reference or candidate)
```

Two trees exist:

- **`…/forge/ref`** — pristine reference bundle for all 8 components, committed to the
  sandbox, **never overwritten**. It is the skeletons' default `WORK_DIR`, so they
  validate/run standalone.
- **`…/forge/work`** — the live area the harness writes to. The harness always passes
  `WORK_DIR=…/forge/work` (or a per-worker tree, §18.8) on `job_run`.

To verify one piece of CTL the harness:
1. writes the metadata + generator into `work/meta/<TYPE>/` and `work/ctl/<TYPE>/` (once per example),
2. writes the CTL under test to `work/ctl/<TYPE>/transform.ctl`,
3. runs the unchanged skeleton: `job_run(..., debug=true, params={WORK_DIR, GROUP_KEY, JOIN_KEY, JOIN_TYPE, RECORDS_NUMBER, SORTED_INPUT})`,
4. reads results via `job_get_tracking` + `job_get_edge_debug_data`.

No `.grf` is edited (EXT_FILTER fallback excepted, §18.7). Because only one component's
subtree is touched per run, and only `transform.ctl` changes between the reference and
each candidate, **the golden output is captured into harness memory after the reference
run and reused** — candidates then overwrite `transform.ctl` in place. No per-example
or per-candidate directories are created.

---

## 18.2 Division of labor

**Mechanical harness — deterministic Python, no LLM:**
write `.fmt`/`.ctl` files into `work/`; call `job_run` with the right params; poll
`job_await`; pull `job_get_tracking` + `job_get_edge_debug_data`; diff candidate output
vs the in-memory golden; overwrite for the next candidate. File I/O via
`sandbox_write_file` / `sandbox_read_file`; execution via the `job_*` tools.

**Setup LLM — once per unique example, cached, amortized over the N candidates:**
produces the **setup bundle**: the `.fmt` files and `generate.ctl`. Its hard part is a
generator whose deterministic output actually *exercises* the transform — boundary
values, nulls, matching & non-matching join keys, multiple group sizes — not type-valid
filler. The generator **must be reproducible**: pure index arithmetic, or a fixed
`setRandomSeed(...)` in `preExecute()` — never unseeded `random*` (an unseeded generator
silently changes the oracle between runs; verify by running the reference twice and
confirming identical output). It also emits the run params (`GROUP_KEY`, `JOIN_KEY`,
`JOIN_TYPE`, `RECORDS_NUMBER`, `SORTED_INPUT`) as **explicit, logged, reviewable fields
with a one-line rationale each** — these live *outside* the candidate's CTL yet define
the oracle (§18.4), so a wrong key/type silently corrupts the example. The candidate
only ever varies `transform.ctl`; the join/group behavior is fixed by these params.

**Judge LLM — per candidate, only when needed:**
adjudicates when there is no reference answer, or when candidate output differs from
golden in a way that may still be correct (multiple valid CTL solutions); classifies
failure modes from execution evidence. Never does file plumbing.

---

## 18.3 Where metadata comes from

- **Mining mode (default):** the example's prompt already declares input/output
  metadata. The setup LLM **transcribes** it into `.fmt` files and infers the key
  params — it does not invent the interface.
- **Synthesis mode:** the setup LLM **designs** metadata + task for variety.

Either way the bundle is internally consistent because one author writes metadata +
generator together, and §18.4 then proves it.

---

## 18.4 Per-example setup sequence (run once, cached)

```
0. CLEAR work/meta/<TYPE>/ and work/ctl/<TYPE>/ (remove stale files from a prior example
   of the same component — e.g. a leftover slave_in_meta.fmt) before writing the bundle.
1. Resolve component type → skeleton path + accepted params + file list  (from manifest)
2. Setup LLM writes into work/ (CTL normalized per §3.3 — fences stripped, //#CTL2 header):
     meta/<TYPE>/in_meta.fmt [, slave_in_meta.fmt, acc_meta.fmt], out_meta.fmt
     ctl/<TYPE>/generate.ctl
   + chooses params (GROUP_KEY, JOIN_KEY, JOIN_TYPE, RECORDS_NUMBER, SORTED_INPUT)
3. Write the REFERENCE answer to work/ctl/<TYPE>/transform.ctl
4. REFERENCE RUN (gate #1 + oracle):
     job_run(skeleton, DPOForge, debug=true, params={WORK_DIR=…/work, <key params>})
     job_await
       → status != FINISHED_OK ⇒ setup is broken (bad generator/metadata, or the
         reference doesn't fit the declared interface). DISCARD the example, log under
         "setup_failed". Do NOT judge candidates against a broken harness.
       → FINISHED_OK ⇒ capture golden INTO MEMORY:
            job_get_tracking         (expected counts / port splits)
            job_get_edge_debug_data  (golden output records on EdgeOut[/0/1/2])
5. ORACLE SANITY ASSERTION (gate #2 — catches runnable-but-wrong setup):
     A reference that *runs* is not proof the setup is *correct* — a mis-inferred
     JOIN_KEY/JOIN_TYPE/GROUP_KEY yields a self-consistent but wrong golden. Confirm the
     golden actually exhibits the task's stated edge-case behavior. Extract literal
     expectations from the prompt ("should be 'unknown'", "one row per group", "drops
     negative amounts") and assert they hold against tracking + golden:
       - task implies a sentinel value → golden contains it (≥1 row);
       - left/outer join → golden row count == driver count;
       - grouping → golden row count == distinct group count in the generated input;
       - filter → accepted + rejected == input count.
     If the implied behavior is absent (e.g. zero "unknown" rows because the generator
     produced no unmatched keys, or JOIN_TYPE was wrong), the example cannot discriminate
     good from bad candidates → log "oracle_unverified", optionally have the setup LLM
     regenerate the generator/params once, else DISCARD.
6. Cache (keyed by example_id): setup bundle contents + params + golden output + the
   asserted expectations.
```

The reference run does double duty — it **validates the setup** and **produces the
golden oracle** in one execution. Nothing downstream trusts a setup the reference
didn't pass.

---

## 18.5 Per-candidate sequence

```
For each candidate k of this example (sequential within the example):
  1. Normalize the candidate CTL (§3.3: strip ```` ```ctl ```` fences, ensure //#CTL2),
     then overwrite work/ctl/<TYPE>/transform.ctl with it.
     (meta/<TYPE>/* and ctl/<TYPE>/generate.ctl are already in place from setup.)
  2. job_run(skeleton, DPOForge, debug=true, params={WORK_DIR=…/work, <same key params>})
  3. job_await(timeout 30–60s)
  4. Classify by outcome:
       a. run fails at init with a CTL compilation error in job_get_log
            → exec_level = L1_fail (compile)   → rejected
       b. run fails later (exception / ABORTED)
            → exec_level = L2_fail (runtime)    → rejected
       c. FINISHED_OK → diff output edge(s) against the in-memory golden (§18.5.1):
            mismatch → exec_level = L3_mismatch → rejected
            match    → exec_level = L3_pass     → correct (chosen-eligible)
  5. Record evidence: tracking counts, first log ERROR (≤200 chars), output diff summary.
```

No cleanup between candidates — the next candidate just overwrites `transform.ctl`.

### L1/L2/L3 note (consequence of externalization)

`job_validate` takes no params, so it cannot point at `work/`; it would validate the
skeleton against the `ref` files, not the candidate. Therefore **L1 (compile) detection
folds into the run step**: CloverDX compiles CTL at graph init, so a malformed
`transform.ctl` makes `job_run` fail immediately with a compile error in the log. The
harness distinguishes L1 (compile-phase: CTL compilation / unresolved field / type
error at init) from L2 (runtime exception during record processing) by matching the
log. Every failure class is still detected; only the tool that surfaces L1 changes
(run-init instead of validate), which also saves a round-trip per candidate.

### 18.5.1 Output diff semantics (component-aware — the main false-mismatch risk)

Naive text equality on edge-debug records produces confidently-wrong `rejected` labels.
`job_get_edge_debug_data` returns every field value as a **string** (nulls as JSON null)
with a per-field `metadata` array (name, type, nullable, format), so the diff must first
parse each value by its declared type/`format`, then canonicalize, component-aware:

- **Row ordering.** EXT_HASH_JOIN output order is **not** guaranteed; unsorted ROLLUP
  likewise. For these, compare as a **multiset keyed on a stable field** (or sort both
  sides by a key before comparing) — never positional. Components with deterministic
  order (REFORMAT, PARTITION per port, NORMALIZER) may compare ordered. Each skeleton
  declares its comparison mode + key field in the manifest.
- **Decimal / numeric fields.** Compare **numerically with scale awareness**, not as
  strings: `1.5`, `1.50`, `1.500` are equal. Doubles compare within a tolerance.
- **Null canonicalization.** Normalize the edge-debug serialization so null vs empty
  string vs a literal sentinel ("unknown") are distinguished consistently on both sides
  before comparing.
- **Field set.** Compare only the output-metadata fields, by name, in a canonical order.

A mismatch is an `L3_mismatch` only after this canonicalization. Borderline cases (the
candidate produced a *different but plausibly valid* output) go to the judge with both
record samples + the task (§18.6); a candidate ruled correct-via-different-output is
dropped from pairing, not labeled rejected (base spec §7.3).

---

## 18.6 Mapping to DPO labels & pairing

- `rejected` quality ranking for `best_vs_worst` pairing: **L3_mismatch > L2_fail > L1_fail**
  (compiles-and-runs-but-wrong is the most informative contrast).
- `failure_modes` are **evidence-backed**: a tag is emitted only when the log or output
  diff demonstrates it (e.g. `rollup_lifecycle` only if per-record emission or an
  uninitialised accumulator is visible in counts/diff), never on suspicion.
- `chosen` = the reference answer (mining), or the judge-preferred correct candidate
  (synthesis / pairwise).
- Verdict object carries the execution evidence block from §16.6
  (`exec_level_reached`, `evidence.{init/compile, run_status, tracking, log_excerpt,
  output_diff}`).

---

## 18.7 EXT_FILTER handling

Per the Externalization Brief §3.1 the harness branches on the manifest:

- **Param-substitution option:** identical to every other component, except the
  candidate boolean is passed as the `FILTER_EXPR` run param instead of being written
  to `transform.ctl`. No graph edit.
- **Clone+inline fallback:** for EXT_FILTER only, the harness copies the skeleton to a
  scratch clone, writes the boolean into `filterExpression` via `graph_edit_properties`,
  runs the clone, deletes it. The single case where the harness touches a `.grf`;
  isolate it behind one code path, out of the generic runner.

Either way the LLM only ever produces a CTL boolean string.

---

## 18.8 Concurrency, debug, isolation, cost, resumability

- **Default = sequential, overwrite in place.** Graph runs are fast (≤~200 ms for
  ≤100-record skeletons); LLM calls (setup + judge) dominate latency and can run
  concurrently at the API level while the single `work/` tree is reused. With 100+
  examples this is simplest and creates no directory sprawl.
- **Optional bounded parallelism for execution:** a fixed worker pool of trees
  `…/forge/work/w0 … wN` (NOT per example). Each worker owns one tree; the dispatcher
  hands an example to a free worker. Still overwrite-in-place within each tree.
- **Debug capture (opt-in, targeted):** `dpo-forge run --example-id <id> --keep` runs
  just that example and writes its full bundle to `…/forge/_debug/<id>/`
  (`meta/<TYPE>/*`, `ctl/<TYPE>/generate.ctl`, `reference.transform.ctl`,
  `cand_0..k.transform.ctl`, `golden.json`, `verdicts.json`) and skips cleanup, so a
  developer can inspect or re-run by hand. No `_debug` dirs are created in normal batch
  runs — only when explicitly requested for a single example.
- **Isolation:** operate only in `DPOForge`; never write to `…/forge/ref`. The `work`
  tree is disposable.
- **Cost:** execution is the cost center — reference run paid once per example,
  candidate runs N per example. No separate validate call (folded into run).
- **Resumability:** persist per-candidate `exec_level_reached` + verdict keyed by
  `(example_id, cand_k)`, and cache the per-example setup bundle + golden output, so a
  resumed run never re-pays the setup LLM or the reference run. (Since `work/` is
  overwritten, resume state lives in the harness's own store / provenance file, not in
  the sandbox tree.)
- **Provenance:** record skeleton revision, `server_deployment`, and the exact params
  passed — a skeleton or engine change can move the oracle.

---

## 18.9 Config additions

```yaml
clover:
  sandbox: "DPOForge"
  skeleton_manifest_project: "dpo-forge"     # project knowledge holding the manifest
  ref_dir: "data-tmp/forge/ref"              # pristine, read-only
  work_dir: "data-tmp/forge/work"            # live, overwritten in place
  debug_dir: "data-tmp/forge/_debug"         # only populated by --keep
  await_timeout_s: 60
  workers: 1                                  # 1 = sequential; N = pool of work/w0..wN trees
  ext_filter_mode: "param"                    # param | clone  (must match the build)
setup_llm:
  provider: "anthropic"                       # authors generate.ctl + .fmt bundles
  model: "<setup model id>"
  cache: true                                 # cache bundle + golden per example_id
oracle:
  strategy: "reference_run"                   # reference_run | assertions | judge
  row_compare: "per_component"                # per_component (from manifest) | ordered | keyed_multiset
  decimal_compare: "numeric"                  # numeric (scale-aware) | string
  float_tolerance: 1.0e-9
  null_canonicalization: true                 # distinguish null / "" / sentinel consistently
  sanity_assert: true                         # enforce the §18.4 oracle sanity assertion (gate #2)
ctl_normalization:
  strip_markdown_fences: true                 # applies to reference AND candidates (§3.3)
  require_ctl2_header: true
run:
  example_id: null                            # set (with --keep) to debug a single example
  keep_artifacts: false                       # true → write full bundle to debug_dir, skip cleanup
```

---

## 18.10 Implementation milestones (replaces §16.8 items 9–12)

9.  Manifest reader → resolve component → skeleton, params, file list (paths under meta/<TYPE>, ctl/<TYPE>).
10. File-bundle writer (`.fmt` + `.ctl`) into `work/`; worker-tree allocator; `--keep` debug writer.
11. Parameterized runner over `job_run` (+ EXT_FILTER branch) and result reader (tracking + edge debug).
12. Reference-run gate + in-memory golden capture + deterministic row/set diff.
13. Outcome classifier (L1-init / L2-runtime / L3-mismatch / L3-pass) from log + diff.
14. Setup-LLM client (generator + metadata authoring, cached) and judge-LLM client (adjudication + evidence-backed failure tagging).
15. Wire `exec_level_reached` into pairing; execution metrics into the W&B report.
