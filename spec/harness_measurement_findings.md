# Harness measurement findings (brief: `spec/harness_measurement_brief.md`)

Two parts, both judge-free:
- **Part A, the fresh-domain pool** (2026-10-26/27): does c13c hold its pool-1 pass rate in the agentic harness on
  prompts nobody here wrote?
- **Part B, ground truth for validate** (2026-10-26/27): answers scored by a parser against defects whose failure the
  CloverDX server confirmed.

## Part A — setup

**Pool** (`agent_harness.py pool --tweak`, `scripts/harness_measurement/{tweak_pool.sh, tweak_rollup.sh, merge_pools.py}`
→ `data/agent_harness/pool_tweak.jsonl` + `.report.json`).
- **Source:** every generate record of the corpus sets with runtime harnesses: SCD-2, syntax pitfalls, Rollup accumulator,
  Normalizer multi-row, DataIntersection, zeroDate.
- **Rewrite:** gpt-6.1-sol (`tweak_llm`) rewrites each prompt into a new business domain (`pick_business_domain`, by
  `--seed`) with new field names and a structurally different rule.
- **Fixture:** a second gpt-6.1-sol call writes the fixture (metadata, input rows, expected output rows) and a reference
  solution.
- **Acceptance:** the reference is run in the graph on the CloverDX server; the task is kept only if it reproduces the
  LLM's own expected rows.
- **Seeds:** 101 and 102 on all six sets, then 103–105 on Rollup accumulator only (see the fixture fix below).

**Harness changes made for this pool** (`agent_harness.py`):
- Rewritten tweak loop: several SFT files, `--tweak-n`, concurrent LLM calls (`--tweak-concurrency`), a separate fixture
  budget (`--fixture-tokens`, 32k, since the fixture plus reasoning did not fit the 8k `tweak_llm` budget), and a
  rejection log (`<out>.rejected.jsonl`) with the reason.
- Record names in LLM-written metadata are sanitized (`"Middle result"` gave "This edge has no metadata assigned").
- The tweak LLM is told the exact component name for DataIntersection / ExtHashJoin / ExtMergeJoin prompts; EXT_HASH_JOIN
  was added to the fixture component list.
- **The one fixture-prompt fix:** Rollup tasks, 0 of 20 accepted in seeds 101–102. All 20 references failed at init:
  `$acc.field` access, missing lifecycle functions, and reserved words (`record`, `input`, date units) as names.
  `FIXTURE_SYSTEM` now spells out the five Rollup functions with a typed accumulator parameter and `acc.field` access, and
  forbids those names. Rollup-only seeds 103–105 then kept 16 of 30.
- The run scripts take `POOL` and `RUNS` (`scripts/agent_harness_run.sh`, `scripts/agent_harness_rows_run.sh`).

**Run** (`scripts/harness_measurement/run_c13c.sh`): c13c (rb1009 + `data/opcd/c13c/round_015/adapter`) on its own vLLM
server.
- Exactly as pool 1: both thinking modes, 2 feedback rounds, once with error feedback only and once with
  `--rows-feedback`.
- `--runs 2`: 330 runs per mode and pass (165 tasks × 2).
- Pool 1 had `--runs 1` (137 per mode).

**Comparison** (`scripts/harness_measurement/tweak_table.py` → `results/agent_harness/pool_tweak_vs_pool1.md`):
- The unit is the task: per-task pass rate (mean of its runs), then the difference of the two pool means with a Welch
  95% CI.
- **Main comparison: pool 1's 107 corpus tasks.** pool_tweak is rewritten from the same corpus sets. Pool 1 whole (137,
  including 30 suite-v5 real-world tasks) is shown too.

## Part A — results

### Pool statistics

| | |
|---|---|
| prompts tried | 322 |
| accepted by the server | 190 (0.59) |
| rejected: reference fails to compile or init | 94 |
| rejected: reference rows disagree with the LLM's expected rows | 14 |
| rejected: reference runtime error | 14 |
| rejected: no JSON | 6 |
| rejected: graph invalid | 4 |
| dropped after the hand check (prose questions, see below) | 25 |
| **final pool** | **165** |

- **By set:** DataIntersection 41, syntax pitfalls 42, SCD-2 36, Normalizer multi-row 30, Rollup accumulator 16,
  zeroDate 0.
- **By component:** DataIntersection 51, Reformat 48, Normalizer 47, Rollup 16, Partition 2, ExtMergeJoin 1.
- **Where the rejections come from:**
  - syntax-pitfall rewrites: 30 compile/init failures out of 80 tried; the reference falls into the pitfall the task
    was written around;
  - Rollup: 20 of 20 before the fixture fix;
  - Normalizer: 19 compile/init failures out of 50 tried.
- **zeroDate is missing.** Its SFT file has 10 records; `task_kind` labels 9 of them fix or validate, including three
  generate prompts that embed metadata XML. The one record labelled generate was a prose question and was dropped. At
  most 3 tasks are lost.

### Hand check (`data/agent_harness/pool_tweak.handcheck.json`)

15 seed-101 tasks, stratified by component (5 DataIntersection, 5 Reformat, 4 Normalizer, 1 Partition). For each:
- is the prompt self-contained;
- is the component right;
- do the expected rows follow from the prompt's rules? Traced row by row.

- **12 pass.** One (tweak_f040825482) never names DataIntersection; its port layout identifies it.
- **3 fail: not code tasks.** They are rewrites of corpus prompts filed as generate whose answer is prose: "Explain how to
  route physical output 2", "No code: list exact fields and types", "Does this design meet the requirement?". The
  harness still demands code, so these tasks are unfair.
- **Consequence:** `merge_pools.py` drops every task whose corpus answer contains no CTL code, unless the rewrite asks for
  CTL. That removed 25 tasks across the seeds (13 of 86 in seed 101).

**Found after the run (not caught by the hand check):**
- **Contradictory headers:** 19 of the 165 prompts carry a `component type: …` header that contradicts the task.
  - SCD-2 rewrites say DATA_INTERSECTION over a downstream Normalizer or Reformat;
  - DataIntersection rewrites say JOIN;
  - the tweak LLM copies the source set's bucket.
- **A missing sequence:** one of them (tweak_dba012e9f6) also asks for keys from "the sequence", which the graph does not
  define.
- **Effect:** these 19 score lower thinking on (0.71 against 0.88 for the rest). The pool was run as built; the headline
  without them is given below.

### Does c13c hold its pool-1 pass rate? (per-task means, 95% CI)

| mode | measure | pool 1 corpus (107) | pool_tweak (165) | tweak − pool 1 corpus | pool 1 whole (137) | tweak − pool 1 whole |
|---|---|---|---|---|---|---|
| off | first attempt | 0.729 | 0.721 | −0.008 (−0.114, +0.099) | 0.650 | +0.072 (−0.032, +0.175) |
| off | after error feedback | 0.748 | 0.803 | +0.055 (−0.045, +0.156) | 0.693 | +0.110 (+0.013, +0.206) |
| off | after rows feedback | 0.813 | 0.885 | +0.072 (−0.014, +0.158) | 0.796 | +0.089 (+0.009, +0.170) |
| on | first attempt | 0.832 | 0.812 | −0.020 (−0.108, +0.069) | 0.825 | −0.013 (−0.096, +0.070) |
| on | after error feedback | 0.869 | 0.858 | −0.012 (−0.091, +0.068) | 0.876 | −0.018 (−0.091, +0.055) |
| on | after rows feedback | 0.916 | 0.909 | −0.007 (−0.073, +0.059) | 0.920 | −0.011 (−0.071, +0.050) |

- **Without the 19 flawed prompts (146 tasks):**
  - thinking on 0.836 / 0.877 / 0.921, differences +0.004 / +0.008 / +0.005;
  - thinking off 0.716 / 0.801 / 0.894, differences −0.013 / +0.054 / +0.081;
  - every CI includes 0.
- **Against pool 1 whole:** pool_tweak looks better thinking off only because pool 1 includes the 30 real-world suite
  tasks, which are harder (pool 1 corpus vs whole: 0.75 vs 0.69).
- **Run-to-run agreement on pool_tweak** (errors-only, final, task × 2 runs):

  | mode | both runs pass | both fail | split |
  |---|---|---|---|
  | off | 126 | 26 | 13 |
  | on | 133 | 15 | 17 |

- **Unsolved in every run:** 4 tasks fail in all 8 of their runs (2 runs × 2 modes × 2 passes).
  - Two are prompt defects: a contradictory header, and the missing sequence.
  - Two are real misses: a 7-condition issue count, and an SCD-2 backfill with an undeclared variable.

### By set and component (final pass rate, off / on)

| set | tasks | first attempt | after error feedback | after rows feedback |
|---|---|---|---|---|
| Normalizer multi-row | 30 | 0.87 / 0.95 | 0.92 / 1.00 | 0.95 / 1.00 |
| Rollup accumulator | 16 | 0.91 / 0.97 | 0.94 / 1.00 | 0.97 / 1.00 |
| DataIntersection | 41 | 0.72 / 0.72 | 0.82 / 0.82 | 0.89 / 0.79 |
| syntax pitfalls | 42 | 0.63 / 0.80 | 0.76 / 0.82 | 0.89 / 0.96 |
| SCD-2 | 36 | 0.62 / 0.75 | 0.68 / 0.76 | 0.78 / 0.86 |

| component (after error feedback, off / on) | pool 1 corpus | pool_tweak |
|---|---|---|
| DataIntersection | 1.00 / 0.90 (10 tasks) | 0.83 / 0.85 (51 tasks) |
| Rollup | 0.82 / 0.89 (28) | 0.94 / 1.00 (16) |
| Normalizer | 0.77 / 0.94 (35) | 0.81 / 0.89 (47) |
| Reformat | 0.61 / 0.79 (33) | 0.71 / 0.77 (48) |

**Final status mix (errors-only, 330 runs per mode).** In both modes most of the remaining failures are wrong rows:

| mode | pass | wrong rows | compile error | init error | runtime error |
|---|---|---|---|---|---|
| off | 265 | 42 | 15 | 7 | 1 |
| on | 283 | 21 | 20 | 6 | – |

### Compile / init causes (all attempts of the errors-only run)

| cause | pool 1 off | pool 1 on | pool_tweak off | pool_tweak on |
|---|---|---|---|---|
| writes to an unconnected output port (`$out.1`/`$out.2`) | 0 / 167 | 0 / 160 | 7 / 417 | **41 / 402** |
| wrong arguments | 1 / 167 | 2 / 160 | **22 / 417** | 3 / 402 |
| date-unit keyword as a variable name | **25 / 167** | 13 / 160 | 12 / 417 | 4 / 402 |
| `!~` regex negation | 3 / 167 | 4 / 160 | 11 / 417 | 0 / 402 |
| unknown field | 1 / 167 | 1 / 160 | 5 / 417 | 10 / 402 |
| undeclared variable | 0 / 167 | 3 / 160 | 9 / 417 | 5 / 402 |
| other | 2 / 167 | 4 / 160 | 38 / 417 | 33 / 402 |

- **`$out.1`/`$out.2` in DataIntersection, thinking on:**
  - 13 of the 51 DataIntersection tasks drew at least one "Cannot write to output port '1'/'2'" (39 attempts);
  - 2 tasks thinking off;
  - pool 1's 10 DataIntersection tasks: none.
  - The rewritten prompts name the consumer of each port ("ReconciliationPairs receives output 1"), which pool 1's do
    not, and that invites writing `$out.1`.
  - It is the T54 habit (§3.33, where it is thinking off), here thinking on.
  - Error feedback recovers most of it (the tasks end 3 of 4 runs pass).
- **Wrong arguments, thinking off:** almost all are `isDate` / `str2date` with 4–5 arguments in the wrong order
  (`(string, string, boolean, string)`).
- **"Other":**
  - "transform function must be defined" (a DataIntersection answer without `transform`);
  - `Unable to resolve sequence` (the flawed task above);
  - unknown metadata names used as record types.
- **Date-unit names:** pool 1's most frequent habit falls from 15% of thinking-off attempts to 3%. Rewrites that invite
  the pitfall are the ones the server rejects most: the reference falls into it too (see the rejections above). So
  pool_tweak under-samples the habit pool 1 measures.

## Part B — setup

**B1, planted defects** (`scripts/harness_measurement/make_mutants.py` → `data/agent_harness/validate_mutants.jsonl`).
- **Mutants:** each pool-1 task's reference CTL (the Test node of its acceptance graph, which passes) gets one defect.
  The mutant is run in the task's acceptance graph(s) and kept only if it fails there; equivalent mutants are dropped
  and the next site is tried (up to 4).
- **Prompt:** "Validate this <component> transform against its metadata and requirements." + the task text, with the
  generate/fix instructions and code blocks removed (and fix-prompt sentences that describe the old bug, e.g. "The only
  reported defect is …") + the code. No hint about the defect.
- **Anchor:** what a finding must name: the function, field, `$out.N` or the compared operand.
- **Expected severity (§7):** compile / init failure and a broken stated requirement → ERROR; removed null guard →
  WARNING; inverted condition accepts either (the brief says WARNING, §7 says a violated stated requirement is ERROR).
- **Function libraries:** the 3 mutants on the two function-library tasks were dropped, because their transform is the
  harness wrapper, not the specified code.

| kind | mutants | server verdict on the mutant | candidate (task, kind) pairs → failing |
|---|---|---|---|
| missing Rollup lifecycle function | 30 (Rollup) | init error ("Required function(s) … are missing") | 31 → 31 |
| output to an unconnected port | 29 (Reformat 11, Rollup 8, Normalizer 7, DataIntersection 3) | init error ("Cannot write to output port") | 131 → 131 |
| field not in metadata | 30 (Reformat 11, Normalizer 8, Rollup 7, DataIntersection 3, ExtMergeJoin 1) | graph validation fails | 131 → 131 |
| `return ALL/OK` → `SKIP` in transform | 28 (Normalizer 16, Reformat 8, DataIntersection 3, Denormalizer 1) | wrong rows (nothing emitted) | 70 → 70 |
| boundary `>=`↔`>`, `<=`↔`<` on a stated threshold | 30 (Reformat 14, Normalizer 10, Rollup 3, Partition 2, DI 1) | wrong rows 29, runtime error 1 | 63 → 43 (41 site tries were equivalent) |
| null guard removed (`nvl`, `!isnull(f) &&`) | 22 (Rollup 9, Reformat 8, Normalizer 3, Partition 1, Denormalizer 1) | runtime error 15, wrong rows 7 | 26 → 22 |
| **controls** (reference unchanged) | 50 (Reformat, Rollup, Normalizer, DataIntersection 10 each, 10 other) | passes | – |

The threshold of each inverted-condition mutant is stated in its prompt (checked for all 30; one, `hr >= 6`, only
implicitly).

**B2, corpus validate records** (`scripts/harness_measurement/corpus_validate.py` → `data/agent_harness/validate_corpus.jsonl`).
- **Source:** the validate records of the seven runtime-harness sets (SCD-2, syntax pitfalls, Rollup accumulator,
  Normalizer multi-row, DataIntersection, zeroDate, Rollup lifecycle). Truth = the reference VERDICT.
- **Anchors:** each reference [ERROR]/[WARNING] line becomes an anchor set: the backticked identifiers and declared
  names it mentions, its first Rollup lifecycle name, and `$out.N`.
- **Kept:** 93 records, 45 FAIL (81 issue lines, 70 ERROR / 11 WARNING) and 48 PASS. 11 were dropped because an issue
  line names no identifier (10 syntax-pitfall lines such as "the ternary return constant", 1 lifecycle).
- **Not a fair model comparison: B2 is training data, and the models saw different parts of it.** Checked against the
  LlamaFactory training files:
  - rb1009 (c13c's base) contains SCD-2 and DataIntersection;
  - rb1011 adds Rollup accumulator and Normalizer;
  - rb1012 adds syntax pitfalls and the 39 lifecycle records.

  B2 is reported but not used for ranking.

**Answers** (`scripts/harness_measurement/gen_answers.py`, `run_models.sh`).
- **Models and sampling:** c13c (rb1009 + `round_015/adapter_vllm`), rb1011, rb1011s2 and rb1012, each on its own vLLM
  server. Both thinking modes, 2 runs per record, the suite's validate sampling (temperature 0.4, top_p 0.95, top_k 20,
  reasoning_effort medium).
- **Plain condition:** the plain system prompt, which is what test.py sends: its eval configs override the suite's
  per-test system prompt.
- **`_fmt` condition:** the suite-v5 validate tests' own system prompt, i.e. plain plus the ISSUES / SUGGESTIONS /
  VERDICT output format. This is the parser-readable condition.
- **Size:** 1,248 answers per model and condition; rb1011s2 plain lost 8 to request errors.

**Scoring** (`scripts/harness_measurement/score_validate.py`, parser only).
- **What is parsed:** the last `VERDICT: PASS|FAIL` (when missing: a bare PASS/FAIL line, else FAIL if there is any
  [ERROR]/[WARNING]), and the [ERROR]/[WARNING] lines before SUGGESTIONS.
- **Defect recall:** a finding line names the anchor.
- **Lenient recall:** the anchor appears anywhere in the prose outside code blocks.
- **False alarm:** any [ERROR] on a control.
- **CIs:** Wilson per answer (optimistic, since the 2 runs of a record are not independent). Model differences use a
  paired bootstrap over records (2,000 resamples), which keeps runs together.
- **Tables:** `results/agent_harness/validate_gt_table{,_fmt}.md`.

## Part B — results

### Format first: without the output-format prompt, thinking-on answers cannot be scored by a parser

| | c13c | rb1011 | rb1011s2 | rb1012 |
|---|---|---|---|---|
| plain, thinking on: no VERDICT line | 0.70 | 0.54 | 0.44 | 0.71 |
| plain, thinking on: defect recall (tagged finding) | 0.35 | 0.57 | 0.67 | 0.32 |
| plain, thinking on: anchor named anywhere in the prose | 0.88 | 0.90 | 0.89 | 0.91 |
| `_fmt`, thinking on: no VERDICT line | 0.00 | 0.00 | 0.00 | 0.00 |

- **Untagged prose:** thinking on with the plain prompt writes "**BUG — undeclared output field `policynumber`**" or
  "Issues: 1. …" without [ERROR] tags or a VERDICT line. rb1012 names the defect in 185 of its 229 "misses".
- **The plain-condition recall gap measures format, not detection:** rb1012 / c13c −0.25 / −0.22 against rb1011. Gone
  with the format prompt.
- **The judge-based suite path has the same mix:** it sends the plain prompt, and the judge reads prose. The ranking
  below therefore uses the `_fmt` condition.

### Validate ground truth per model and mode (`_fmt` condition; n = 338 mutant answers, 100 control answers per cell)

| model | mode | defect recall | mutant verdict FAIL | control: any [ERROR] (false alarm) | control verdict PASS | findings / mutant answer | findings not naming the anchor / mutant |
|---|---|---|---|---|---|---|---|
| c13c | off | 0.75 [0.71, 0.80] | 0.96 | 0.41 [0.32, 0.51] | 0.59 | 1.43 | 0.63 |
| c13c | on | 0.86 [0.81, 0.89] | 0.91 | 0.14 [0.09, 0.22] | 0.86 | 1.09 | 0.20 |
| rb1011 | off | 0.82 [0.78, 0.86] | 0.95 | 0.35 [0.26, 0.45] | 0.65 | 1.38 | 0.49 |
| rb1011 | on | 0.88 [0.84, 0.91] | 0.93 | 0.11 [0.06, 0.19] | 0.89 | 1.15 | 0.24 |
| rb1011s2 | off | 0.81 [0.77, 0.85] | 0.93 | 0.34 [0.25, 0.44] | 0.66 | 1.20 | 0.36 |
| rb1011s2 | on | 0.86 [0.82, 0.89] | 0.92 | 0.07 [0.03, 0.14] | 0.93 | 1.07 | 0.19 |
| rb1012 | off | 0.81 [0.77, 0.85] | 0.97 | 0.28 [0.20, 0.37] | 0.73 | 1.51 | 0.64 |
| rb1012 | on | 0.91 [0.87, 0.93] | 0.93 | 0.08 [0.04, 0.15] | 0.92 | 1.10 | 0.15 |

Defect recall by kind (`_fmt`, off / on, n60 except null guard n44 and wrong return n56):

| model | inverted condition | missing lifecycle | null guard removed | unconnected port | unknown field | wrong return |
|---|---|---|---|---|---|---|
| c13c | 0.70 / 0.92 | **0.18 / 0.35** | 0.84 / 0.98 | 1.00 / 0.97 | 1.00 / 1.00 | 0.84 / 0.96 |
| rb1011 | 0.55 / 0.85 | 0.60 / 0.48 | 0.84 / 1.00 | 1.00 / 0.98 | 0.98 / 1.00 | 0.98 / 1.00 |
| rb1011s2 | 0.62 / 0.90 | 0.40 / 0.32 | 0.91 / 0.98 | 1.00 / 1.00 | 0.98 / 1.00 | 1.00 / 1.00 |
| rb1012 | 0.52 / 0.87 | **0.73 / 0.60** | 0.77 / 1.00 | 0.91 / 1.00 | 1.00 / 1.00 | 0.95 / 1.00 |

**Severity.**
- **Compile/init and wrong-return defects:** called ERROR (≥ 98%).
- **Removed null guards:** also called ERROR (34–44 of 34–44 per cell), never the WARNING the table expects. All 22 guards
  protect nullable fields whose handling the task states, so §7's "violated stated requirement → ERROR" fits as well as
  "data-dependent → WARNING". The severity measure is ill-posed for this kind and is not used.

**Differences (paired bootstrap over records, 95% CI), `_fmt`:**

| comparison | mode | defect recall | mutant verdict FAIL | control false alarm |
|---|---|---|---|---|
| rb1011s2 − rb1011 (seed pair) | off | −0.012 [−0.056, +0.033] | −0.012 [−0.047, +0.021] | −0.01 [−0.09, +0.06] |
| rb1011s2 − rb1011 (seed pair) | on | −0.021 [−0.053, +0.009] | −0.009 [−0.024, +0.006] | −0.04 [−0.09, +0.01] |
| rb1012 − rb1011 | off | −0.009 [−0.053, +0.036] | +0.021 [−0.009, +0.053] | −0.07 [−0.16, +0.02] |
| rb1012 − rb1011 | on | +0.027 [−0.006, +0.062] | +0.006 [−0.012, +0.024] | −0.03 [−0.08, +0.02] |
| c13c − rb1011 | off | **−0.068 [−0.121, −0.015]** | +0.012 [−0.021, +0.047] | +0.06 [−0.04, +0.16] |
| c13c − rb1011 | on | −0.024 [−0.059, +0.012] | −0.018 [−0.044, +0.009] | +0.03 [−0.04, +0.10] |

**Plain condition, thinking off** (the test.py path; parseable, 2–4% without VERDICT):
- **Recall:** c13c 0.69, rb1011 0.74, rb1011s2 0.73, rb1012 0.75.
- **Control false alarm:** 0.30 / 0.28 / 0.16 / 0.27.
- **Seed pair:**
  - recall moves −0.003 [−0.044, +0.038];
  - the mutant verdict moves −0.145 [−0.198, −0.095] and the false alarm −0.12 [−0.21, −0.04];
  - with no format instruction, the verdict line and the threshold for writing [ERROR] are the seed-sensitive parts.

**B2 corpus records** (`_fmt`, off / on; training data, see above):
- **FAIL-record verdict:** 0.91–0.97 / 0.79–0.92.
- **Issue recall:** c13c 0.73 / 0.65, rb1011 0.81 / 0.76, rb1011s2 0.79 / 0.77, rb1012 0.87 / 0.84.
- **[ERROR] on PASS records:** 0.38–0.58 / 0.29–0.40.

rb1012, the only model trained on the lifecycle records, is highest, as expected.

### Hand check of the control false alarms (thinking off, plain, rb1011 / rb1011s2 / rb1012)

19 of the 50 controls drew at least one [ERROR] from at least one model.

**11 are clearly false.** They contradict §7 or the server run:
- DataIntersection "must write output 1" (scd2_021, T53: `$out.0` is correct);
- accumulator fields that "throw" or are "never initialized" (rollup_acc 038/042/043; non-nullable fields start at zero,
  and the reference passed);
- "DST" errors in pure UTC millisecond arithmetic (scd2_045, rollup_acc_003);
- a literal `'Z'` parse (scd2_050);
- "`updateGroup` returning false stops `initGroup`" (T62);
- an efficiency remark (syntax_r2_01);
- a contract-guaranteed delimiter flagged as ERROR (syntax_r3_05).

**The other 8 are false too, by server probe (2026-10-27).** These were precedence or edge-case claims (T46, T55, T56,
T58, T67, T69, rollup_acc 007/018) on inputs the fixture might not cover.
- **Method:** `scripts/harness_measurement/probe_controls.py` gave each reference a small input built to trigger one
  recurring claim (32 probes, results in `results/agent_harness/control_probes.json`). Each run's output was compared
  with what the task's requirements prescribe.
- **Result:** all 32 runs finished OK and every output matched the requirements, so no claimed defect exists.

| control | claims probed (how often they recur in the [ERROR] lines) | server result |
|---|---|---|
| T46 | sign rule applied to an unknown movement (6); zero quantity; 9-digit or comma unit value passes; malformed value throws | unknown movement gets only MOVEMENT; zero gets QTY; 9 digits and `1,234.50` get VALUE; a malformed value is rejected without an exception |
| T55 | VOID garbage parsed (4); bank-only context empty or from the invoice (4); bare `-` / `.` accepted (3); null or ` VOID ` state; repair row's expected_amount should be 0 | VOID contributes 0 (bank-only: UNPLANNED, matched: omitted); bank-only rows carry bank context; `-` and `.` get AMOUNT_TEXT; null and ` VOID ` get REPAIR as stated; the repair row keeps the invoice's null |
| T56 | winner fields leak into the next key (4); null `==` null false or throws (5); complete loses to incomplete (3); pre-epoch | each key emits its own row; null/null reaches the revision tie-break; mixed null/real never throws and real wins; complete outranks; pre-epoch ordered correctly |
| T58 | REMOVE retracts only the first or last duplicate (12); next group keeps old context | all duplicates retracted, a later ADD survives; each group takes its own first record |
| T67 | baseline not reset at trip change (6); duplicate after a gap compared with the wrong sample (4); `7.5` rejected | a new trip ignores the old baseline; the duplicate is compared with the gap sample as requirement 7 says; `7.5` accepted, `7.` and `50.1` faulty |
| T69 | NEW_BAD/OLD_BAD precedence reversed; unit label keeps a space | NEW_BAD (requirement 4: it outranks); ` kw ` → `KW:12.34`, blank unit → `:12.34` |
| rollup_acc 007 / 018 | `initGroup` ordinal starts at 2 or skips groups (27); accumulators carry over between groups | batch_group 1, 2, 3 including an all-null group; counts, peaks and positions reset per group |

- **Not probed:** the T67 claims about `getOutputPortOnError`. No input reaches an exception, since grammar is checked
  before parsing. By reading, state is updated only after every statement that could throw. Compile and port-style
  claims (T55 "bulk copy does not compile", "`return 0`") are already refuted, because the reference passed on the server.

So **all 19 flagged controls are false alarms**: the control false-alarm rate is the true precision failure, not an upper
bound. The commonest single claim, "an `initGroup` counter numbers the first group 2", is wrong on the server, as is the
belief that Rollup or Denormalizer state leaks between groups. Both are candidates for the corpus.

## Indications

1. **Does c13c hold on fresh prompts? Yes, within ±0.1.**
   - **Thinking on:** pool_tweak − pool 1 corpus is −0.02 / −0.01 / −0.01 (first attempt / after error feedback /
     after rows feedback), with 95% CIs about ±0.08.
   - **Thinking off:** −0.01 / +0.06 / +0.07, with CIs about ±0.10.
   - Removing the 19 flawed prompts does not change this.
   - So the pool-1 pass rates (0.87 / 0.92 thinking on with feedback) are not an artifact of corpus prompts the model
     was trained on.
   - **Where it does not hold:**
     - **DataIntersection:** 0.83 / 0.85 against 1.00 / 0.90 on pool 1's 10 tasks. Thinking on, prompts that name each
       port's consumer draw `$out.1`/`$out.2` writes in 13 of 51 tasks.
     - **SCD-2 rewrites are the weakest set:** 0.68 / 0.76 after error feedback.
     - **Thinking off:** `isDate`/`str2date` argument order is a new compile habit (22 of 417 attempts).
   - **Limit:** the CIs exclude a drop of about 0.1, not one of 0.05.
   - **Selection bias:** the pool keeps only tasks whose LLM-written reference passes, so tasks that are hard for a
     strong model, and pitfall-inviting ones, are under-represented. "Holds" means on tasks of that difficulty.
2. **Does the ground-truth measure agree with the judge ranking? No, it does not reproduce it.**
   - **Judge (thinking-off validate ×9, excluding T18/T22):**
     - c13c 0.935 (WRONG 2.2%), rb1011 0.941 (2.3%), rb1011s2 0.898 (4.0%), rb1012 0.926 (2.0%);
     - it puts rb1011s2 last by 0.04 and 1.7 WRONG points.
   - **Ground truth (`_fmt`):** rb1011s2 equals rb1011 in recall (−0.01), verdict (−0.01) and false alarm (−0.01); all
     CIs within ±0.06.
   - **The one difference it does show:** c13c finds fewer planted defects thinking off (−0.07 [−0.12, −0.02]), almost
     all on removed Rollup lifecycle functions (0.18 against 0.60). The judge suite has no item for that.
   - **It also picks up a training effect:** rb1012, trained on the lifecycle set, is best on that kind (0.73 / 0.60). So
     the measure can see a corpus effect where one exists.
   - **Read:** the judge's seed gap between rb1011 and rb1011s2 is not a validation-skill difference the planted defects
     can see; that fits §3.34's reading of it as seed/judge noise.
3. **Clean-code false-alarm rate (the "precision over recall" number):**
   - **Thinking off:** at least one [ERROR] on 28–41% of clean, server-passing controls (format prompt), 16–30% (plain).
   - **Thinking on:** 7–14% (format prompt).
   - The verdict follows: thinking off says FAIL on 27–41% of clean code. The judge's WRONG share (2–4% of findings)
     hides this, because a review usually has one finding and the false alarm is that finding.
   - **This is the largest validate defect measured so far, larger than any recall gap:** thinking off flags a third of
     correct code, and every flagged control is a false alarm: 11 by §7 facts or the server run (DataIntersection
     `$out.0`, accumulator defaults, UTC arithmetic), 8 by server probe (32 probes, all as required).
4. **Which measure should gate validate from now on:** B1 in the `_fmt` condition, both modes.
   - **Gate on:** defect recall (n338 per mode) and control false alarm (n100 per mode).
   - **Seed spread:** recall ±0.02, verdict ±0.01, false alarm ±0.04 (rb1011 pair); compare the judge's 0.04–0.13.
   - **Cost:** about 25 min per model on one GPU, no judge.
   - **Proposed noise bands:**
     - recall ±0.05;
     - false alarm ±0.08 (100 control answers; the control set should grow to 100+ records for a tighter band);
     - lifecycle-kind recall ±0.15 at n60.
   - **Keep the judge suite** for what B1 does not cover (explanation quality, multi-finding reviews, T18/T22 rubric
     items), but stop reading its 0.04-level aggregate differences.
   - **B2 is training data and differs per model:** use it only as a training-recall check.

## Caveats

**Part A:**
- **Acceptance filter:** a task is kept only if gpt-6.1-sol's own reference passes (59% of rewrites). Hard tasks and
  pitfall-inviting tasks are rejected more often; date-unit-name errors are 3% of thinking-off attempts on pool_tweak
  against 15% on pool 1.
- **Prompt defects in the run pool:** 19 of 165 (a contradictory component header; one also needs a missing sequence). They are reported
  with and without; strip the header in `merge_pools.py` before reusing the pool.
- **Unequal runs:** pool 1 had 1 run per task and mode, pool_tweak 2. The per-task-mean CI accounts for this; the pool-1
  side is the noisier one.
- **zeroDate:** it contributed no tasks (see Pool statistics).
- **Infrastructure:** the first pool_tweak run (10-26, 22:39) lost its vLLM server at 23:24. Part B's `run_models.sh`
  cleanup kills any of the user's servers named `rb1009`. 1,085 runs ended in connection errors.
  - Those records were removed and rerun on 10-27; nothing else changed.
  - The originals are kept as `results/agent_harness/c13c_pool_tweak{,_rows}.killed_20261026.jsonl`.
  - `run_c13c.sh` now serves the base as `rb1009_hm`.

**Part B:**

- **Pool 1's prompts are corpus prompts:** 83–107 of the 156 tasks are in the models' training files (SCD-2, accumulator,
  Normalizer, syntax). The mutated code is new, but the requirement text is familiar.
- **Six defect kinds, all single-site:** multi-defect reviews, lookup/dictionary and date-format defects are not covered.
- **Anchor matching is lexical:** a finding that names the right field but claims the wrong problem counts as a hit.
  Lenient-vs-tagged recall agree within 0.02–0.06 thinking off, so tagged findings rarely name the anchor by accident,
  but "right reason" is not checked.
- **Controls pass their fixtures, not every possible input:** 8 of the flagged controls are unverified, see the hand
  check.
- **Stored artifacts:** the plain-condition run of c13c was redone after a wrong adapter path (all 404s, rows deleted).
  The first c13c start on GPU 1 failed for memory (the previous server was still releasing); it ran on GPU 3.

## Files

- **Part A scripts:**
  - `agent_harness.py` (tweak pool);
  - `scripts/agent_harness_run.sh`, `scripts/agent_harness_rows_run.sh` (`POOL`, `RUNS`);
  - `scripts/harness_measurement/{tweak_pool.sh, tweak_rollup.sh, merge_pools.py, run_c13c.sh, tweak_table.py}`.
- **Part A data:**
  - `data/agent_harness/pool_tweak.jsonl` (+ `.report.json`, `.handcheck.json`); evaluation set, never into training
    data;
  - per-seed pools and rejection logs in `data/agent_harness/tweak/`.
- **Part A results:** `results/agent_harness/c13c_pool_tweak{,_rows}.jsonl`, `pool_tweak_vs_pool1.md`.
- **Part B scripts:** `scripts/harness_measurement/{make_mutants.py, corpus_validate.py, gen_answers.py, score_validate.py,
  run_models.sh}`.
- **Data:** `data/agent_harness/validate_mutants.jsonl` (+ `.report.json`), `data/agent_harness/validate_corpus.jsonl`
  (+ `.report.json`). Evaluation sets: never into training data.
- **Results:** `results/agent_harness/validate_gt_<model>{,_fmt}.jsonl`, `validate_gt_table{,_fmt}.md/.json`.

Reproduce:

```bash
# Part A
setsid nohup scripts/harness_measurement/tweak_pool.sh > logs/harness_measurement/tweak_pool.log 2>&1 &
setsid nohup scripts/harness_measurement/tweak_rollup.sh > logs/harness_measurement/tweak_rollup.log 2>&1 &
~/venv/bin/python scripts/harness_measurement/merge_pools.py
setsid nohup scripts/harness_measurement/run_c13c.sh > logs/harness_measurement/run_c13c.log 2>&1 &
# Part B
~/venv/bin/python scripts/harness_measurement/make_mutants.py
~/venv/bin/python scripts/harness_measurement/corpus_validate.py
GPU=1 FMT=1 MODELS="c13c rb1011" setsid nohup scripts/harness_measurement/run_models.sh > logs/harness_measurement/run.log 2>&1 &
~/venv/bin/python scripts/harness_measurement/score_validate.py c13c_fmt rb1011_fmt rb1011s2_fmt rb1012_fmt \
    --diff rb1011s2_fmt:rb1011_fmt --out results/agent_harness/validate_gt_table_fmt.md
```
