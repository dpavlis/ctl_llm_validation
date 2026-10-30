# Retry-loop distillation (retry1): findings

Brief: `spec/retry_distill_brief.md`. Question: does training c13c on its own corrected answers from the agentic harness
(attempt 0 failed on the server, a later attempt passed, feedback stripped) raise the **first-attempt** execution pass
rate, without buying it with the usual regressions (T54 `$out.1`, accumulator belief, validate precision)?

Status: training done 2026-10-29 (67 rounds, `data/opcd/retry1/`); gates done 2026-10-30 00:28 against c13c on the same
vLLM path (`scripts/retry_distill/gates.sh`, table `results/retry_distill/gates_retry1.md`).

**Verdict: not adopted.** retry1 raises the first-attempt pass rate on the fresh-domain pool (thinking off +0.10) but
lowers the gap-test execution pass rate in both modes (off −0.06, on −0.15), returns the accumulator belief, and
starts answering without code thinking on. c13c with the inference-time compile-and-retry loop stays the deployment.

## 1. Data (step 1 of the brief)

Two training pools, neither overlapping pool 1, pool_tweak, the suite, the hard sets or the exec-RFT holdout:

| pool | prompts | origin |
|---|---|---|
| `data/agent_harness/pool_retry.jsonl` | 160 | exec-RFT prompts not in pool 1 (holdout excluded) |
| `data/agent_harness/pool_retry_tweak.jsonl` | 190 | LLM-rewritten tasks, seeds 201–205, no overlap with pool_tweak |

c13c sampled both pools in both thinking modes, k = 4, two rows-feedback rounds (`scripts/retry_distill_tweak.sh`,
`scripts/retry_distill_sample_on.sh`; the thinking-on prompts were re-sampled once the harness kept the thinking text,
`agent_harness.py` `think` field). A **triple** is one (prompt, run) whose attempt 0 failed on the CloverDX server and a
later attempt passed.

| mode | triples | kept as targets | dropped | median target tokens (max) |
|---|---|---|---|---|
| thinking off | 281 | 281 | 0 | 378 (1953) |
| thinking on | 232 | 172 | 60 | 1274 (5239) |

453 triples over 396 distinct prompts (`data/retry_distill/pool.jsonl`); each becomes one SFT row (the corrected answer
under the original prompt) and one DPO pair (corrected vs. the failed attempt 0), 906 exec rows in all.

**By component** (kept triples, off / on): Reformat 91 / 66, Rollup 77 / 47, DataIntersection 56 / 30, Normalizer 48 / 24,
Denormalizer 5 / 5, ExtHashJoin 2 / 0, Partition 2 / 0. **By set:** syntax pitfalls dominate (104 off / 91 on, both
pools), then DataIntersection (47 / 26), SCD-2 (39 / 25), Rollup accumulator (38 / 15), Normalizer multi-row (36 / 12),
Rollup lifecycle (12 / 0), zero-date (5 / 3).

**Attempt-0 failure cause** (what the corrected answer fixes):

| cause | off | on |
|---|---|---|
| wrong rows (compiles, wrong output) | 101 | 108 |
| compile: wrong arguments | 36 | 19 |
| compile / init: undeclared variable | 49 | 1 |
| init error, other | 30 | 1 |
| compile, other | 23 | 2 |
| runtime error | 15 | 6 |
| compile: output port (`$out.1` etc.) | 5 | 24 |
| compile: regex negation / reserved time unit / ternary constant | 6 / 6 / 1 | 1 / 2 / 0 |
| compile: type mismatch / unknown function / invalid escape | 2 / 5 / 2 | 6 / 1 / 0 |

Thinking off fixes mostly compile errors (180 of 281); thinking on mostly wrong rows (108 of 172) and the DataIntersection
`$out.1` habit (24).

### What was stripped from the targets (`scripts/retry_distill/build_samples.py`)

The target is the passing attempt's answer (and, thinking on, its thinking) with every reference to the feedback removed,
sentence by sentence inside prose only (code blocks are protected; paragraph breaks kept). Patterns: error-message
references, "previous attempt", "the user ran / the run produced", "failed", wrong-output, "fix / corrected", "feedback".
For fix-task prompts, whose legitimate answer talks about errors and fixes, only the run/feedback/error-message/wrong-output
patterns apply.

| mode | sentences removed | fix/corrected | error message | previous attempt | user ran | wrong output | failed |
|---|---|---|---|---|---|---|---|
| off (answers) | 108 | 75 | 13 | 2 | 9 | 0 | 9 |
| on (thinking + answers) | 2307 | 1231 | 389 | 231 | 171 | 160 | 122 |

Drop rules (thinking on): the stripped thinking still matches error/previous/feedback/fail/fix/corrected (47 triples) or
shrank below a third of the original or below 200 characters (13). The drops concentrate on the tweak pool (25) and the
lifecycle set (6): those corrections are long explanations of the error, not a quietly corrected plan. No thinking-off
answer lost its code block.

## 2. Training

`configs/opcd_retry1.yaml`: init from c13c (`data/opcd/c13c/round_015/adapter`), exec_rft1's anchors (dpodef1, dpodef3b
plain, hard cases w1, hard cases 2 w3, hard holdout, contrast, probe, replay 0.4), `prompts.exec` fixed-sample path with
the 906 retry rows (exec_weight 1.0, exec_dpo_weight 0.02, beta 0.1, cutoff_exec 16384), 67 rounds × 32 prompts × 2 steps
(each exec row drawn about once), lr 2e-5, seed 0. GPU 0 training, sampler rb1009 on GPU 1 :3011. 12:51–19:14 on 10-29.

- Exec NLL per token (the corrected answers under the original prompts): 0.25 over the first 20 steps → 0.18 over the
  last 20 (mean 0.20); smoke step 0 was 0.36. DPO margin 0 → 3–9 by the end (accuracy 1.0 on the drawn pairs).
- OPCD side unchanged: KL per token ≤ 0.012, belief rate 0.0 in every round, quote rate 0.03–0.12, no unclosed `<think>`,
  no hit-cap samples. Probes every 4 rounds: belief 0/40 in 16 of 17 probes (1/40 at round 52), unclosed think 0–1.
- One false start: the round count was written empty by the run script (a null weight field); that training was killed
  during its pre-training probe before any round was saved, and the run was relaunched with `rounds: 67` by hand.

## 3. Gates against c13c

Both models on the same vLLM path (rb1009 server :3012, adapters hot-loaded), execution-scored with the record cap and
output cleanup of 10-29. CIs: Newcombe for rates, Welch for means. Full table: `results/retry_distill/gates_retry1.md`.

| gate | c13c | retry1 (round 66) | difference, 95% CI |
|---|---|---|---|
| gap tests off, execution pass (3×n10) | 133/330 (0.403) | 112/330 (0.339) | −0.064 (−0.136, +0.010) |
|   off: wrong_rows / init_error / runtime_error | 0.227 / 0.276 / 0.061 | 0.345 / 0.197 / 0.106 | +0.118 (+0.049, +0.186) / −0.079 / +0.045 (+0.003, +0.089) |
| gap tests off, judge | 0.775 | 0.792 | +0.017 (−0.014, +0.048) |
| gap tests on, execution pass (3×n10) | 251/330 (0.761) | 203/330 (0.615) | **−0.145 (−0.214, −0.075)** |
|   on: wrong_rows / runtime_error / no_code | 0.067 / 0.012 / 0.006 | 0.136 / 0.048 / 0.036 | +0.070 (+0.024, +0.117) / +0.036 (+0.010, +0.066) / +0.030 (+0.008, +0.057) |
| gap tests on, judge | 0.911 | 0.862 | −0.050 (−0.077, −0.023) |
| harness pool 1 off: first attempt / final (2 rounds) | 0.650 / 0.693 (137) | 0.682 / 0.741 (274) | +0.033 (−0.061, +0.131) / +0.047 (−0.042, +0.142) |
| harness pool 1 on: first attempt / final | 0.825 / 0.876 (137) | 0.770 / 0.876 (274) | −0.055 (−0.131, +0.031) / +0.000 (−0.063, +0.074) |
| harness pool_tweak off: first attempt / final | 0.721 / 0.803 (330) | 0.824 / 0.842 (330) | **+0.103 (+0.039, +0.166)** / +0.039 (−0.019, +0.098) |
|   off: first-attempt compile_error | 0.127 | 0.048 | −0.079 (−0.123, −0.036) |
| harness pool_tweak on: first attempt / final | 0.812 / 0.858 (330) | 0.861 / 0.909 (330) | +0.048 (−0.008, +0.105) / +0.052 (+0.002, +0.101) |
| T40 on: below full score (2×n20) | 1/20 | 3/40 | +0.025 (−0.168, +0.155) |
| T42 on: below full score (2×n20) | 7/20 (0.35) | 17/40 (0.425) | +0.075 (−0.183, +0.303) |
| T54 off n20: `$out.1`/`$out.2` | 0/20 | 0/20 | 0 |
| hard set 2: belief claim (k4) | 1/60 | **10/60** | |
| hard sets 1, 3: belief claim | 0/160, 0/160 | 0/160, 0/160 | |
| hard set 3: nullable / non-nullable / default wrong | 0.35 / 0.10 / 0.20 | 0.225 / 0.10 / 0.25 | −0.125 (−0.31, +0.07) / 0 / +0.05 |
| validate off ×9 (excl. T18/T22): mean / WRONG share | 0.935 / 0.022 | 0.932 / 0.017 | −0.003 / −0.005 |
| validate GT B1-tweak, format, off: recall / false alarm | 0.80 / 0.24 | 0.80 / 0.33 | ±0.00 / +0.09 (band ±0.08) |
| validate GT B1-tweak, format, on: recall / false alarm | 0.96 / 0.14 | 0.96 / 0.11 | ±0.00 / −0.03 |
| v4 n5 on: validate / fix / generate | 0.850 / 0.826 / 0.970 | 0.849 / 0.836 / 0.969 | flat |

Details behind the rows (`results/retry_distill/gaps_retry1.json`, `results/agent_harness/retry1_*.jsonl`):

- **Gap tests thinking on:** 12 of 330 answers contain no code at all (explanation-only answers; c13c 2). T63
  (Rollup accumulator) fails at runtime 15/30 with null written to a non-nullable field; T53 `$out.1` init errors 7/30.
- **Gap tests thinking off:** T46 0.70 → 0.30, T67 0.17 → 0.00; the invalid / init-error share fell (the model compiles
  more often) but wrong_rows rose by the same amount and more.
- **pool_tweak thinking off:** the gain is almost all compile errors that stopped happening: wrong_arguments 18 → 2,
  undeclared_variable 7 → 0, regex_negation 5 → 0, other 19 → 10. Wrong rows are unchanged (31 → 37).
- **pool_tweak thinking on, DataIntersection:** first attempts writing `$out.1`/`$out.2` 20 → 6 of 102, first-attempt
  pass 79 → 86. The `$out.1` habit was 24 of the 172 thinking-on targets.
- **pool 1:** inside noise both ways; the §3.29 habit causes (reserved time unit, regex negation, ternary constant) are
  unchanged in both pools and both modes, so the training did not remove the syntax habits the triples corrected.
- **Validate ground truth** (`results/retry_distill/gt_tweak_retry1_fmt.md`, `gt_b1_retry1_fmt.md`): recall identical,
  thinking-off false alarm up by 0.09 on B1-tweak (just outside the ±0.08 band), down by 0.03 thinking on.

## 4. Hand check of 10 changed first attempts

Pool 1, both retry1 runs agree, against c13c's first attempt to the same prompt (14 prompts worse in both runs, 9
better; material in the gate files). Five of each:

**Worse**

1. **T71 on, DataGenerator** (reservoir recurrence): retry1 calls `createDate(y, m, d)` without the time-zone string,
   so every timestamp is shifted; c13c passes the zone. Same on **T70 on**. Not copied from the targets: 12 of the 13
   `createDate` calls in the retry targets carry a zone. On the thinking-off gap tests retry1 omits it in 10 of 11 calls
   (c13c 1 of 4); thinking on both models omit it on most of the full suite, so it is drift, not a learned fact.
2. **rollup_acc_sft_007 off, Rollup fix task:** retry1 resets the accumulator to 0 instead of null and emits 9 where 0
   is expected: the old accumulator belief in code form. Matches hard set 2 (1 → 10 of 60 belief claims) and T63.
3. **scd2_sft_050 off, SCD-2 Reformat:** writes the literal "RETIRED" where "RETIRE" is specified. Literal drift.
4. **normalizer_sft_002 off, Normalizer:** hoists the per-record state into globals and names one `boolean trace;`,
   a reserved token, so it no longer compiles; c13c keeps the locals.

**Better**

5. **normalizer_sft_033 off:** the sign of a RELEASE leg (−40 vs 40) is right; retry1 precomputes the legs list once.
6. **normalizer_sft_004 off:** the CANCEL bucket row is no longer skipped (15 rows, c13c 14).
7. **syntax_r2_02 off:** the parity label is computed with the generic rule instead of a hard-coded case.
8. **syntax_r3_01 on:** the correct label for the boundary case.
9. **rollup_acc_sft_011 off, Rollup fix:** emits null for a group with no eligible rows instead of dropping it.

The improvements are logic slips of exactly the kind the retry loop corrects in the targets (a missed branch, a sign, a
label). The regressions are new habits that the targets do not contain: dropped time zone, accumulator reset to 0,
field hoisting into globals, answers without code.

## 5. Indications

1. **The corrected answers are learnable** (NLL 0.25 → 0.18, DPO accuracy 1.0) and transfer to the fresh-domain pool
   thinking off: first-attempt pass 0.72 → 0.82, compile errors 0.13 → 0.05, through fewer wrong-argument and
   undeclared-variable errors. That is the brief's primary target, and it is met on that pool.
2. **It does not transfer to the gap tests,** which are the primary objective: execution pass off −0.06 (CI includes
   0) and on −0.15 (CI excludes 0), judge on −0.05. Wrong-row and runtime failures rise in both modes; the model compiles
   more and computes less correctly.
3. **Thinking on is damaged in a new way:** 12 of 330 gap answers (and 1–2 per harness pool) contain no code. The
   stripped thinking-on targets, whose explanations were cut sentence by sentence, are the likely source: 60 of 232
   were dropped for still referring to the feedback, and the kept ones are explanation-heavy. The thinking-on triples
   should not be used again in this form.
4. **The accumulator belief returns** (hard set 2 1 → 10 of 60; T63 runtime nulls 15/30) although the OPCD side's
   belief rate stayed 0.0 and the probes 0/40. Exec SFT/DPO rows on Rollup fix tasks (38 off / 15 on) carry the belief
   in code, where the belief probes and the OPCD teacher do not see it. Same mechanism as §3.33 (exec-RFT) and the
   rb1012 SFT records (§3.32).
5. **Verdict: not adopted.** The pool_tweak gain (+0.10 off) does not compensate for a generate regression on the
   suite, no-code answers thinking on and the belief regression; validate ground truth is flat to slightly worse (B1-tweak
   false alarm +0.09 off). c13c stays the candidate, deployed with the inference-time loop, which already recovers most
   of what retry1 learns (pool_tweak final: c13c 0.80 / 0.86 vs retry1 0.84 / 0.91).
   - If the idea is tried again: thinking-off triples only, exec rows restricted to compile-error corrections (where the
     gain is), Rollup accumulator rows excluded or paired with the belief anchors at full weight, and a gap-test
     execution gate after every 20 rounds.
