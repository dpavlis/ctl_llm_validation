# Harness measurement findings (brief: `spec/harness_measurement_brief.md`)

Part A (the fresh-domain pool) runs in another session and will be added here. This file holds **Part B: ground truth for
validate** (2026-10-26/27), judge-free: the answers are scored by a parser against defects whose failure the CloverDX
server confirmed.

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

**8 cannot be decided from the code alone.** They are precedence or edge-case claims (T46, T55, T56, T58, T67, T69,
rollup_acc 007/018) on inputs the fixture may not cover. They would need server probes; not done.

So the control false-alarm rate is an upper bound, but most of it is real: at least 11 of the 19 flagged controls are
wrong claims, and they recur across seeds and models.

## Indications

1. **Does c13c hold on fresh prompts?** Part A (other session).
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
     correct code, about half of the claims are verifiably false (§7 facts: DataIntersection `$out.0`, accumulator
     defaults, UTC arithmetic), and the rest are unverified.
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

- **Scripts:** `scripts/harness_measurement/{make_mutants.py, corpus_validate.py, gen_answers.py, score_validate.py,
  run_models.sh}`.
- **Data:** `data/agent_harness/validate_mutants.jsonl` (+ `.report.json`), `data/agent_harness/validate_corpus.jsonl`
  (+ `.report.json`). Evaluation sets: never into training data.
- **Results:** `results/agent_harness/validate_gt_<model>{,_fmt}.jsonl`, `validate_gt_table{,_fmt}.md/.json`.

Reproduce:

```bash
~/venv/bin/python scripts/harness_measurement/make_mutants.py
~/venv/bin/python scripts/harness_measurement/corpus_validate.py
GPU=1 FMT=1 MODELS="c13c rb1011" setsid nohup scripts/harness_measurement/run_models.sh > logs/harness_measurement/run.log 2>&1 &
~/venv/bin/python scripts/harness_measurement/score_validate.py c13c_fmt rb1011_fmt rb1011s2_fmt rb1012_fmt \
    --diff rb1011s2_fmt:rb1011_fmt --out results/agent_harness/validate_gt_table_fmt.md
```
