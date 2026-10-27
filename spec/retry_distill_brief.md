# Brief: retry-loop distillation — teach the first attempt what the second attempt knows

**For the executing agent.** Read `CLAUDE.md` and `WORKLOG.md`, then findings §3.19 (OPCD, the method), §3.29 and §3.31
(the retry loop), §3.33 (exec-RFT, the null result this builds on) and §3.34/§4.7 (noise bands) in
`spec/ctl2_training_findings.md`. Follow the shared-machine, git and correctness rules in `CLAUDE.md`. Do not commit.

## Why

- c13c's first attempt passes 0.65 of the harness tasks thinking off and 0.82 thinking on; after the server's error is
  fed back it passes 0.69 / 0.88, and 0.80 / 0.92 when the wrong rows are shown too (§3.31). The model can produce the
  correct answer — it needs the error in context to do so.
- Training on its own passing first attempts (exec-RFT, §3.33) taught nothing: 68% of prompts had no signal, and a
  passing answer to a prompt that never invites the habit says nothing about the habit.
- The one method that has moved a pretrained habit here is on-policy context distillation (§3.19): the teacher is the
  same model with something extra in context, and the student learns to answer as if it had it. Here the extra context
  is the compiler error / row diff and the model's own corrected answer. The samples that carry signal are exactly the
  ones exec-RFT could not use: prompts where the first attempt fails and the retry passes.

**Hypothesis:** distilling the corrected second attempt into the first attempt raises the first-attempt execution pass
rate, in particular on the §3.29 compile habits, without touching the belief gates. **Expectation:** modest; this is the
last training idea with a mechanism behind it, so the result decides whether training continues at all.

## Data

1. **Triples.** Run `agent_harness.py` on c13c with `--runs 4` (k = 4 samples per prompt) in both modes, with
   `--rows-feedback`, on a **training pool** that is not pool 1 and not pool_tweak: build it with `agent_harness.py pool
   --corpus` from the corpus DPO prompts and any SFT generate/fix records not already in pool 1 (the exec-RFT pool,
   `data/exec_rft/pool.jsonl`, has 297 fixture-backed prompts and is a ready source; its 40-prompt holdout stays held
   out), plus a second `--tweak` batch with a different seed than Part A of `spec/harness_measurement_brief.md`. Keep
   every record where **attempt 0 failed and a later attempt passed**: (prompt, failed answer, error text, corrected
   answer, mode). Expect a few hundred.
2. **Targets.** For each triple the student prompt is the original prompt alone; the target is the corrected answer.
   Thinking on: keep the thinking text of the corrected attempt but strip any sentence that refers to the feedback
   ("the error says", "as reported", "the previous attempt") — list the patterns you removed and count them; a target
   that still talks about an error it cannot have seen is dropped. Thinking off: the corrected answer as is.
3. **Contrast pairs.** (corrected answer, failed answer) per triple as DPO pairs, the same way exec-RFT built them
   (`opcd.py` `prompts.exec`, `exec_dpo_weight`), weighted as there (DPO ≈ 0.3 of the gradient).
4. **Anchors.** c13c's belief prompts at ≥ 30% of the non-replay weight with the rulev6 teacher, and the replay share,
   exactly as `configs/opcd_exec_rft1.yaml` did; the exec-RFT run showed this keeps T40/T42 and the hard sets.

## Training

- Fresh run name, `configs/opcd_retry1.yaml`, continue from `data/opcd/c13c/round_015`, c13c's per-step hyperparameters,
  enough rounds to draw every triple once (as exec-RFT did, 57 rounds for 705 rows). One GPU for training, one for the
  sampler; check `nvidia-smi` first.
- Smoke first (`opcd.py smoke --exec`) and record the gradient norms per loss kind as §3.33 did.

## Gates (against c13c, same vLLM path, same judge)

| gate | how | pass |
|---|---|---|
| gap tests execution pass rate | 3 × n10 both modes, `exec_score.py` (c13c's three runs of 10-26 are stored: 0.403 off / 0.761 on) | above c13c's run spread (±0.03) — i.e. ≥ +0.06 |
| harness pool 1, first attempt | `agent_harness.py run --rounds 0 --runs 2`, both modes | above c13c's 0.65 / 0.82 beyond CI |
| harness pool_tweak, first attempt | same, if Part A of the measurement brief has delivered it | same |
| §3.29 compile causes, first attempt | the harness summary's cause table | time-unit names, regex negation, `$out.1`, argument order each not higher |
| T54 off `$out.1` | n20 + the gap runs pooled | ≤ 1/20 (exec-RFT failed this: 8/40) |
| T40 / T42, hard sets 1–3 by direction | 2 × n20, k4 | as c13c |
| validate off ×9 excl. T18/T22, WRONG share | | within ±3 points of c13c (the §4.7 band) |
| thinking on full suite n5 | validate / fix / generate | within ±0.06 / ±0.04 / ±0.04 |

Also report the **retry gain after training**: run the harness with 2 rounds on the trained adapter — if the first
attempt improved but the final pass rate did not, the model moved its errors rather than removing them.

## Deliverables

1. `spec/retry_distill_findings.md`: triple statistics (by mode, component, failure cause of attempt 0); what was stripped
   from thinking targets; the gate table with n and 95% CIs; a hand check of 10 first attempts that changed status either
   way against c13c's answers to the same prompt; **Indications**: (1) did the first-attempt pass rate rise, in which
   mode, and from fewer compile errors or fewer wrong rows; (2) did the targeted habits move (counts); (3) did pool 1,
   pool_tweak and the gap tests agree; (4) regressions; (5) verdict — adopt as the new candidate, run a second round, or
   stop training on this line and keep c13c with the inference-time loop.
2. Configs and scripts in the repo; raw data under `data/opcd/retry1/`, `results/`; a WORKLOG entry and a findings §3.36
   stub.

## Do not

- Train on pool 1, pool_tweak, the suite, the hard sets or the exec-RFT holdout.
- Reuse a run folder; `opcd.py` resumes silently.
- Change rubrics, references or `ctl2-basics.md`.
- Touch `~/venv`, other users' processes, or other sessions' uncommitted files.
