# Findings: validate-precision OPCD, round 2 (valprec2)

- **Brief:** `spec/validate_precision2_brief.md`.
- **Round 1:** `spec/validate_precision_findings.md`, findings §3.37.
- **Run:** `data/opcd/valprec2/`, 156 rounds; round 155 evaluated.
- **Dates:** 2026-10-28..29.
- **Comparisons:** every gate against c13c and valprec1 (round 122), same vLLM path, same judge.

## Setup

### Fact probes, round 2 (`results/validate_precision/fact_probes_v2.json`)

Each probe was a graph run on the CloverDX server in sandbox MiscExamples.

| probe | claim it tests | server result |
|---|---|---|
| `dow_sunday_tz` | getDayOfWeek(date, tz) numbers Sunday 1 | Sunday 2026-03-29 → **7** |
| `dow_monday_utc` / `dow_saturday_utc` | numbering | Monday → **1**, Saturday → **6** |
| `dow_sunday_plus1` | dateAdd(…, 1, day) across DST | lands on Sunday 23:00 UTC (dateAdd works in the server zone) → 7 |
| `minute_tz` / `hour_tz` | getMinute / getHour have no time-zone overload | both compile and run |
| `else_if_true_return` | a statement after an if / else if (true) chain that returns in every branch is unreachable and does not compile | compiles and runs |

FACTS2 (`build_context.py --round2`) adds three lines to the round-1 fact sheet:
- getDayOfWeek returns 1 = Monday … 7 = Sunday;
- the date-part functions take an optional time zone;
- the else-if (true) case above.

CLEAN2 adds one sentence to the clean-code teacher context, before "If nothing qualifies":
> It compiled, so nothing in it is a compile error, an undeclared function or a wrong signature. A null in a nullable
> field that neither the fixture nor the requirements mention is at most a [WARNING], never an [ERROR].

### Review prompts (`data/validate_precision/review_prompts_v2.jsonl`, `.report.json`)

- **Totals:** 459 prompts, 1238 rows, weight 1893. Clean is 1295, or 68% of the review weight (round 1: 22%).
- **Clean reviews:**
  - 160 references, each in 4 conditions (format / plain × off / on);
  - clean / plain / off counts ×2.
- **Claim controls** (×2 more, by construct, regex over code and metadata):

| construct | prompts |
|---|---|
| ordered comparison on a nullable field | 61 |
| initGroup counts or resets state | 40 |
| DataIntersection writing `$out.0` | 22 |
| millisecond date arithmetic | 1 |
| date part with a time zone | 0 |

- **Planted reviews:**
  - unconnected port and unknown field were down-sampled to 30 each (stratified, seed 13);
  - missing lifecycle (51), wrong return (92), inverted condition (42) and null guard removed (54) were kept whole.
- **Weights:**
  - The dpodef1 target had weight 3, so reviews are 0.631 of the non-replay weight.
  - `opcd.py` multiplies each record's weight by its `row_weight`.
- **Not used:** the retry-distill tweak pool (81 origins shared with B1-tweak).

### Run

- **Config:** `configs/opcd_valprec2.yaml`; init from c13c; 156 rounds, about 5.6 min each.
- **Hardware:** trained on GPU 2; sampler on GPU 3 at :3013.
- **Interruption:** `/home` filled up on 10-28, and the trainer died in round 10 without a traceback.
  - I pruned valprec1 rounds 000–121 (adapter and optimizer only), and the run resumed after round 9. No data was lost.
  - `scripts/validate_precision/prune_rounds.sh` now keeps only the newest 2 finished rounds' weights while a run trains.

## Results

### Training (`results/validate_precision/round_stats_valprec2.md`)

| slot | samples | KL/token, first 10 rounds | last 10 |
|---|---|---|---|
| clean / format / off | 510 | 0.050 | −0.006 |
| clean / format / on | 512 | 0.045 | 0.018 |
| **clean / plain / off** | 1016 | **0.168** | **0.005** |
| clean / plain / on | 512 | 0.070 | 0.014 |
| planted / format / off | 296 | 0.165 | 0.013 |
| planted / format / on | 294 | 0.074 | 0.028 |
| planted / plain / off | 296 | 0.203 | 0.050 |
| planted / plain / on | 296 | 0.120 | 0.045 |

- **The slot that failed in round 1 now converged.** Clean / plain / off reached 0.005; in round 1 it went 0.190 → 0.095.
- **Anchors:**
  - target 0.037 → 0.013; hard 0.057 → 0.019;
  - contrast and replay ≤ 0.010;
  - belief rate 0.000 at the end; the probe was 0 in every round except 000 and 148 (0.025 each).
- **Skipped samples:** 0 context quotes; 3 cutoffs; 36 truncated.

### Validate ground truth (no judge; `results/validate_precision/gt_*valprec2*.md`)

Method:
- 2 runs per record.
- Each cell is the rate with its Wilson 95% CI.
- Differences are paired bootstrap with a 95% CI.

**With the output format** (the suite's prompt, which the gate uses):

| set | mode | metric | c13c | valprec1 | valprec2 | valprec2 − c13c | valprec2 − valprec1 |
|---|---|---|---|---|---|---|---|
| B1-tweak | off | **false alarm** (n 100) | 0.24 | 0.23 | **0.15** [0.09, 0.23] | −0.09 [−0.19, +0.01] | −0.08 [−0.17, 0.00] |
| B1-tweak | off | defect recall (n 292) | 0.80 | 0.91 | 0.88 | +0.08 [+0.03, +0.13] | −0.03 [−0.06, −0.00] |
| B1-tweak | off | lifecycle recall (n 32) | 0.31 | 0.75 | 0.72 | | |
| B1-tweak | on | false alarm | 0.08 | 0.04 | **0.02** [0.01, 0.07] | −0.06 [−0.12, −0.01] | −0.02 [−0.05, 0.00] |
| B1-tweak | on | defect recall | 0.89 | 0.97 | 0.96 | +0.07 [+0.03, +0.11] | −0.01 [−0.03, +0.01] |
| B1 | off | **false alarm** (n 100) | 0.41 | 0.35 | **0.25** [0.18, 0.34] | **−0.16 [−0.27, −0.06]** | **−0.10 [−0.19, −0.03]** |
| B1 | off | defect recall (n 338) | 0.75 | 0.85 | 0.88 | +0.12 [+0.07, +0.18] | +0.03 [−0.01, +0.06] |
| B1 | off | lifecycle recall (n 60) | 0.18 | 0.67 | 0.73 | | |
| B1 | on | false alarm | 0.14 | 0.01 | 0.03 [0.01, 0.08] | −0.11 [−0.20, −0.04] | +0.02 [−0.02, +0.06] |
| B1 | on | defect recall | 0.86 | 0.96 | 0.96 | +0.11 [+0.07, +0.15] | 0.00 [−0.02, +0.02] |
| B1 | on | lifecycle recall | 0.35 | 0.83 | 0.83 | | |

**Without the format (the test.py path), B1.**
- **The parser misreads valprec2's plain answers.** It needs the `ISSUES:` / `[ERROR]` / `VERDICT:` layout:
  - with no format in the prompt, valprec2 uses it in only 74% of thinking-off answers (c13c 100%, valprec1 97%);
  - with thinking on, it uses it in 26% (c13c 24%);
  - the other answers write `**ERROR** —` or `ERROR:` prose.
- **What the parser reports:** valprec2 plain thinking-on recall of 0.02, and thinking-off recall of 0.58 with 20% of
  answers having no verdict line.
- **Both numbers are format artifacts, not misses.**
- **The re-score below is format-independent** (`scripts/validate_precision/lenient_score.py`):
  - a control counts as a false alarm if the answer marks any ERROR in any form or says FAIL;
  - a mutant counts as caught if it marks an ERROR and names the anchor.
  - This recall is stricter than the parser's: c13c with the format scores 0.65 here, 0.75 on the parser.

| mode | metric | c13c | valprec1 | valprec2 |
|---|---|---|---|---|
| off | **false alarm** (n 100) | 0.30 [0.21, 0.39] | 0.61 [0.51, 0.71] | **0.31** [0.22, 0.41] |
| off | recall, ERROR + anchor (n 338) | 0.60 [0.55, 0.66] | 0.78 [0.73, 0.82] | 0.64 [0.59, 0.69] |
| on | false alarm | 0.04 [0.01, 0.08] | – | **0.00** [0.00, 0.00] |
| on | recall, ERROR + anchor | 0.29 [0.24, 0.34] | – | **0.87** [0.83, 0.90] |

Paired difference on the parser for plain thinking-off false alarm:
- valprec2 − c13c: +0.01 [−0.09, +0.10];
- valprec2 − valprec1: **−0.30 [−0.40, −0.20]**.

valprec1 was not run plain with thinking on.

### Generate, belief and judge gates

Source: `results/validate_precision/gates_valprec2.md` and `gates_valprec1.md`. CIs are Newcombe / Welch 95%.

| gate | c13c | valprec1 | valprec2 | valprec2 − c13c |
|---|---|---|---|---|
| gap tests off: execution pass rate (3 × n10 × 11 tests, n 330) | 0.403 | 0.406 | 0.382 | −0.021 (−0.095, +0.053) |
| gap tests on: execution pass rate | 0.761 | 0.715 | 0.736 | −0.024 (−0.090, +0.042) |
| harness pool 1, first attempt, off (n 137 / 274) | 0.650 | 0.650 | 0.617 | −0.033 (−0.128, +0.067) |
| off: first-attempt compile_error | 0.131 | 0.164 | 0.201 | +0.069 (−0.010, +0.139) |
| harness pool 1, first attempt, on | 0.825 | 0.788 | 0.785 | −0.040 (−0.116, +0.045) |
| T40 on, below full (n 20 / 40) | 1/20 | 0/40 | 2/40 | 0.000 |
| T42 on, below full | 7/20 | 10/40 | 9/40 | −0.125 (−0.365, +0.101) |
| T54 off, writes `$out.1`/`$out.2` | 0/20 | 0/20 | 0/20 | |
| hard sets 1 / 2 / 3, belief claims (k4) | 0/160, 1/60, 0/160 | 0, 0, 0 | 0/160, 1/60, 0/160 | |
| hard set 3, by direction: nullable / non-nullable / metadata default / sentinel | 14/40, 2/20, 4/20, 0/80 | 10/40, 0/20, 0/20, 2/80 | 10/40, 0/20, 1/20, 1/80 | |
| judge validate off ×9 excl. T18/T22, mean (n 495) | 0.935 | 0.920 | 0.923 | −0.012 (−0.032, +0.008) |
| judge validate off, **WRONG share** of findings | 2.2% (25/1135) | 3.8% (44/1148) | **2.6%** (30/1147) | +0.004 (−0.009, +0.017) |
| full v4 on n5: validate / fix / generate | 0.850 / 0.826 / 0.970 | 0.843 / 0.814 / 0.978 | 0.850 / 0.922 / 0.974 | fix +0.096 (−0.004, +0.196) |

### Hand check: the 10 B1 plain thinking-off controls valprec1 flagged in 2/2 runs and c13c passed

| control | valprec1 (2/2), quoted | valprec2 | what changed |
|---|---|---|---|
| `rollup_acc_…_016` Rollup | "The accumulator is not reset before the next group … initGroup() again only after transform()" | 0/2: "The accumulator starts at zero for each group … VERDICT: PASS" | gone |
| `scd2_…_007` DataIntersection | "CTL2 throws on an ordered comparison with a null operand" (as ERROR, on `!=`) | 0/2: "[WARNING] The changed flag uses `!=`, which is null-safe" | gone; the remark is a WARNING |
| `scd2_…_014` DataIntersection | "The VERSION branch writes the proposal effective_at to close_to … corrupts the existing interval" | 0/2: "[WARNING] The equality branches do not guard nullable exposure values" | gone (WARNING) |
| `scd2_…_028` DataIntersection | "The close boundary uses the replacement's scheduled_at instead of batch_at" | 0/2: "the current version remains open until that time … VERDICT: PASS" | gone |
| `suite_T68` Standalone | "that argument is nullable: when gross or discount is null … budget" | 0/2: "ISSUES: none" | gone |
| `suite_T46` Reformat | "The unit-value grammar rejects a valid eight-integer-digit value" | 1/2: "`qty * str2decimal(v)` is integer times decimal, which CTL2 evaluates as number (double)" | halved; **replaced** by a type claim that has not been probed |
| `suite_T66` Partition | "The date branch returns defective for every invoice before 2026-01-01" | 1/2: "returns port 5 for a malformed date before the amount branch" | halved, still a requirement misreading |
| `syntax_r1_02` Reformat | "CTL2 returns Sunday=1 through Saturday=7" | 1/2: "CTL2 returns 1 for Sunday and 7 for Saturday" | halved; **server-refuted** claim kept despite FACTS2 |
| `suite_T53` DataIntersection | "written to $out.0, which is the DataIntersection removal port" | 2/2, same claim | unchanged (22 di_out0 claim controls did not fix it) |
| `suite_T56` Denormalizer | "The retained winner fields are not reset in clean()" | 2/2, same claim | unchanged |

Five of the 10 are gone and three are halved; two are unchanged.

Over all 50 controls in 2 runs, plain thinking off, by count of flagged runs per control:
- of the 20 controls valprec1 flagged and c13c passed, valprec2 passes 13 in both runs, flags 5 in one run, and flags 2
  (T53, T56) in both;
- the persistent false alarms are the ones c13c already had:
  - Rollup initGroup / accumulator state on `rollup_acc_004/007/038/042/043`;
  - "DataIntersection `$out.0` is the removal port" on scd2_021 and T53;
  - T55 port 0;
  - T67 baseline rule;
  - millisecond DST arithmetic on scd2_045.

**Claims by category on control [ERROR] lines** (keyword-classified, 100 control answers per cell, parser-read):

| claim | c13c fmt off | valprec1 fmt off | valprec2 fmt off | c13c plain off | valprec1 plain off | valprec2 plain off |
|---|---|---|---|---|---|---|
| answers with any [ERROR] | 41 | 35 | **25** | 30 | 61 | **31** |
| requirement misreadings | 28 | 18 | **9** | 8 | 18 | 7 |
| null "throws" | 12 | 7 | 10 | 8 | 10 | 9 |
| Rollup / group state | 9 | 6 | 8 | 11 | 17 | 8 |
| DataIntersection / ExtMergeJoin `$out.0` port | 2 | 2 | 3 | 2 | 4 | 3 |
| DST / time zone | 2 | 0 | 2 | 2 | 3 | 2 |
| decimal / integer type | 1 | 3 | 1 | 1 | 4 | 1 |
| compile / signature | 0 | 0 | 0 | 0 | 5 | 1 |

B1-tweak with the format, thinking off: any [ERROR] 24 → 23 → **15**; null "throws" 14 → 12 → 9; misreadings 8 → 8 → 4.

**Null findings on controls by severity** (format, thinking off, ERROR / WARNING):

| set | c13c | valprec1 | valprec2 |
|---|---|---|---|
| B1 | 12 / 1 | 7 / 0 | 10 / 0 |
| B1-tweak | 14 / 4 | 12 / 0 | 9 / 4 |

## Indications

1. **Did the thinking-off false alarm fall in both conditions?** Yes on the format path; it is back to c13c on the plain
   path.
   - **Format path:**
     - B1 0.41 → **0.25** (−0.16 [−0.27, −0.06] vs c13c; −0.10 [−0.19, −0.03] vs valprec1);
     - B1-tweak 0.24 → **0.15**, which meets the hypothesis (≤ 0.16), though the paired CI vs c13c, −0.09
       [−0.19, +0.01], just touches 0.
   - **Plain path:** valprec1's doubling is gone. It is 0.31, at c13c's 0.30 (the gate is ≤ 0.38, and ≤ format + 0.08 =
     0.33).
   - **Where the gain came from:** requirement misreadings fell (28 → 9 on B1 with the format), and compile / signature
     claims went.
   - **What stayed:** null "throws", Rollup group state, and the DataIntersection `$out.0` port claim. The claim controls
     for `$out.0` (22) and initGroup (40) were not enough to remove them thinking off.
2. **Were valprec1's thinking-on and lifecycle gains kept?** Yes.
   - **With the format, thinking on:** false alarm 0.03 / 0.02 (B1 / B1-tweak; valprec1 0.01 / 0.04); recall 0.96.
   - **Lifecycle recall:** 0.83 on, 0.73 / 0.72 off.
   - **New, plain thinking on:** false alarm 0.00 and recall 0.87 (c13c 0.04 / 0.29). This is the best plain reviewer
     so far.
   - **Thinking-off recall with the format vs valprec1:** B1 +0.03 [−0.01, +0.06], B1-tweak −0.03 [−0.06, −0.00]. The
     B1-tweak loss is in inverted condition (0.77 → 0.67).
3. **Did the null-comparison findings move to WARNING?** No.
   - Null findings on controls are still ERRORs: 10 / 0 on B1, 9 / 4 on B1-tweak, against c13c's 12 / 1 and 14 / 4.
   - The CLEAN2 severity sentence moved a few on the plain path (scd2_007 and scd2_014 are now WARNINGs) but not the
     format-path count.
   - The server-refuted "getDayOfWeek Sunday = 1" claim survives in 1 of 2 runs even with FACTS2 in the teacher.
4. **Generate and belief regressions?** No significant regression; every gate is inside its band. But all four generate
   point estimates are below c13c:
   - gap tests −0.021 / −0.024;
   - harness first attempt −0.033 / −0.040;
   - thinking-off first-attempt compile errors +0.07 (−0.01, +0.14).

   valprec1 had the same direction (−0.045 gap on, −0.036 harness on). Each estimate is inside its noise band
   (±0.06–0.07); together they hint at a small generate cost from review training, which these n cannot confirm or
   rule out.

   Belief, T40/T42, T54 and hard sets 1–3 are at c13c or better. The judge WRONG share is 2.6% (gate ≤ 2.5%; c13c 2.2%,
   difference +0.004 [−0.009, +0.017]); it misses the gate by about one finding, inside noise. Fix rose 0.826 → 0.922
   (+0.096, CI just touches 0).

   **Output-format drift:** without a format instruction, 26% of thinking-off answers drop the `ISSUES:` / `VERDICT:`
   layout (c13c 0%). The suite and B1 gates are unaffected because both give the format. A deployment prompt without one
   would see prose findings.
5. **Verdict:** valprec2 passes every gate in the brief except the judge WRONG share, which it misses by 0.1 point,
   inside noise. It is a better reviewer than c13c in every validate condition. The one condition valprec1 broke
   (plain, thinking off) is back at c13c's level, and thinking on is the best reviewer measured.

   Because generate is the primary objective and every generate estimate is slightly below c13c, I recommend:
   - **Make valprec2 the successor candidate, but do not ship it until generate is confirmed.**
   - The confirmation is the fresh-domain harness (pool_tweak, `--runs 2`, both modes) against c13c's §3.36 numbers,
     which adds n so that a −0.03 effect would show.
   - If that holds within ±0.03, adopt valprec2.
   - Leave the remaining thinking-off false alarms (null as ERROR, initGroup state, DataIntersection `$out.0`) to the
     system prompt or the retry loop. A third round of the same method would buy little: the claim controls already
     targeted them.

## Generate confirmation: fresh-domain harness (2026-10-29..30)

`scripts/validate_precision/harness_tweak.sh` → `results/agent_harness/valprec2_pool_tweak.jsonl` (+ `.summary.md`).
- **Setup:** pool_tweak (165 LLM-rewritten, server-verified tasks), both modes, 2 feedback rounds, `--runs 2`, errors-only
  feedback, exactly as c13c in §3.36. Same vLLM path; rb1009 is served on GPU 2 :3014 with the round-155 adapter.
- **Comparison:** paired by task / mode / run against `c13c_pool_tweak.jsonl`. The 95% CI is a task-cluster bootstrap.

| mode | metric | c13c | valprec2 | difference |
|---|---|---|---|---|
| off (n 330) | first-attempt pass | 0.721 | 0.730 | +0.009 [−0.024, +0.042] |
| off | pass after 2 feedback rounds | 0.803 | 0.818 | +0.015 [−0.018, +0.048] |
| on (n 330) | first-attempt pass | 0.812 | 0.815 | +0.003 [−0.036, +0.045] |
| on | pass after 2 feedback rounds | 0.858 | 0.882 | +0.024 [−0.006, +0.058] |

- **First-attempt failure mix**, thinking off, valprec2 vs c13c:
  - compile_error 47 vs 42;
  - wrong_rows 26 vs 31;
  - init_error 12 vs 17;
  - runtime_error 4 vs 2.
- **Thinking on:** the mix is the same as c13c's within ±2 per class.
- **Generate holds.** Both first-attempt differences are inside ±0.03, and their CIs exclude a loss larger than 0.04.
  - The small dips on the gap tests and pool 1 (Indication 4) do not show on these 660 paired runs.
  - The criterion set in Indication 5 is met.

**Decision: adopt valprec2 (`data/opcd/valprec2/round_155`, on the rb1009 base) as c13c's successor.**

## Files

- **Brief and findings:** `spec/validate_precision2_brief.md`, this file.
- **Config:** `configs/opcd_valprec2.yaml`.
- **Eval configs:** `configs/eval_vp_*valprec2*`.
- **Data:** `data/validate_precision/review_prompts_v2.jsonl` and `.report.json`.
- **Code:**
  - `opcd.py` (`row_weight`);
  - `scripts/validate_precision/`:
    - `build_context.py --round2`;
    - `probe_facts.py`;
    - `run.sh` / `gates.sh` (GPU, port, plain-mode and CMP parameters);
    - `vllm_sampler_3011.sh`;
    - `prune_rounds.sh`;
    - `gates_table.py` (LAST argument);
    - `lenient_score.py` (format-independent re-score).
- **Harness check:** `scripts/validate_precision/harness_tweak.sh`, `results/agent_harness/valprec2_pool_tweak*`.
- **Results:** `results/validate_precision/{gates_valprec2.md, gt_*valprec2*, round_stats_valprec2.md, fact_probes_v2.json}`.
- **Answers:** `results/agent_harness/validate_gt_*valprec2*`, `valprec2_pool1_first_*`.
