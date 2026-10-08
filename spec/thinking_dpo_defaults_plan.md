# Plan: thinking-on DPO against the "declared variables start null" belief

Status: plan, 2026-10-08. Owner decision pending on the base model (step 0).

## Why DPO, and why this round is different

Three SFT routes have not moved the belief in thinking mode. In each case T40.FP1 and T42.FP6 fired
in **20/20** runs with thinking on:

| model | data |
|---|---|
| rb1006 | 120 answer-only fix-explained records, with the declaration as a silent trap |
| rb1007 | + 80 answer-only fix-defaults records that name the declaration "Left unchanged" |
| rb1008 | + 184 thinking traces with correct reasoning (rb1006's own, plus repairs). Validate WRONG also rose to 13–15% |

On the defaults prompts, rb1006 states the belief in **48%** of its thinking samples, even on
prompts it was trained on (pilot fixpilot1007). SFT only raises the likelihood of correct traces.
It does not push down the false one, which keeps winning when the model reasons freely. DPO
penalises the false trace directly.

Two earlier DPO rounds also ran with thinking on and had no measurable effect:
- dpo1: 187 self-distilled pairs;
- dporep: 88 repaired pairs.

Both were broad: many task types, many different faults per pair, and no target behaviour to
measure. This round is the opposite:
1. **One target:** only the declaration-default belief.
2. **Minimal-difference pairs:** chosen and rejected differ mainly in the false claim and its
   consequences. The preference signal then points at the belief, not at style or length.
3. **A direct probe:** the belief rate on held-out prompts, measured before the suite, so we know
   whether the DPO did anything.

## Steps

### 0. Base model (decision)

**Recommended: rb1006** (`/home/pavlisd/exports/qwen38_rb1006_sftdpo`):
- best fix (0.863);
- validate WRONG 4.4%;
- generate at par;
- no `roundHalfUp` hallucination;
- every pilot sample and repair so far came from it, so those are on-policy.

Alternative: **rb1007** (current corpus, WRONG 3.5%). It carries the `roundHalfUp`
hallucination (T43 0.78), and its pairs would have to be sampled fresh.

### 1. Prompt pool and hold-out

The pool is the 256 corpus prompts whose code declares a non-null-default variable (date, scalar,
list or map) without an initializer and then uses it. Counts from `build_pool` plus the two fix
sets:

| task | prompts | date | list/map | scalar |
|---|---|---|---|---|
| fix | 208 | 45 | 73 | 118 |
| validate | 48 | 8 | 19 | 30 |

By source: fix_defaults 80, fix_explained 76, reasoning_v2 40, fix_this_code 29, validate_thinking
25, others 6.

**Hold out 50 prompts as the belief probe,** stratified by source and task. That's about 15 from
fix-defaults, 15 fix-explained, and 20 others including 8 validate. The probe prompts are never
used for pairs.

### 2. Sampling (base model, thinking on, k=4)

- The 156 fix-set prompts already have rb1006 samples (fixpilot1007), so they are reused.
- About 100 other prompts need new samples, about 1.5 hours on two GPUs.
- The probe also gets k=4 base samples. That is the before-DPO belief rate.

### 3. Labelling

The existing `self_distill.py filter` runs format, library, compile, judge and claims checks.
Each sample is then labelled with the belief scan plus the judge's `false_claims` / `wrong_fixes`
that concern a declaration default:
- **belief:** states or relies on the false default;
- **clean-accepted:** passes every check and has no belief;
- **other:** everything else.

### 4. Pairs

| type | chosen | rejected | source |
|---|---|---|---|
| A. natural | a clean-accepted sample | a belief sample of the **same prompt** | prompts with both (about 20 so far) |
| B. repair | a minimal repair of the rejected sample (`repair_traces.py`, extended to validate), re-checked: format, library, belief, compile, judge, claims, similarity ≥ 0.6 | the belief sample | every belief sample; up to 2 per prompt |
| C. contrast | the sample that correctly guards a **real** null (variant/byte/cbyte, nullable input, nullable accumulator, missing map key, unmatched slave) | a sample that wrongly calls that real null safe | fix-defaults contrast prompts; small, only if the samples show this error |

- **Target:** 150–250 pairs over 100+ prompts. At most 2 pairs per prompt, so no single scenario
  dominates; rb1008 showed what over-weighting a few prompts does.
- **Pair hygiene:**
  - both sides close `</think>`;
  - the length ratio of chosen to rejected is between 0.7 and 1.4, so the pair doesn't teach
    length;
  - the rejected side must actually contain the belief, by scan or judge.
- **Pair type C** stops DPO from overshooting into "nothing is ever null".
- **Moderation:** OpenAI blocked about 15% of repair calls in the pilot. Accept the loss; don't
  rephrase to evade it.

### 5. Training

LoRA DPO on the merged base export, single GPU, using the existing chunked-logps patch:
- `enable_thinking: true` (both sides carry `<think>…</think>`);
- `pref_loss: sigmoid`, `pref_beta: 0.1`, `pref_ftx: 0.1`;
- lr 5e-6, cosine schedule, warmup 0.1, 2 epochs;
- rank 64;
- `dpo_logps_chunk_size: 1024`, `cutoff_len` 6144;
- save every epoch and evaluate the last.

### 6. Evaluation, gated

1. **Probe** (cheap, about 1 hour): the DPO model at k=4 on the 50 held-out prompts, labelled as
   in step 3.
   - Gate: the belief rate falls by at least half against the base model's rate on the same
     prompts.
   - Contrast prompts in the probe must not start calling real nulls safe.
   - If the gate fails, stop here; no suite evals.
2. **Suite**, on the snapshot `eval_snapshot_20261003`:
   - fix, thinking on, n=20: T40.FP1 and T42.FP6 fire in ≤ 25% of runs, and fix ≥ 0.83;
   - validate, thinking off, 3 runs: WRONG ≤ 5%;
   - generate, thinking off and on, full n=5: ≥ 0.975 (generate comes first).

## Cost and time

- **Sampling:** about 1.5 hours (2 GPUs).
- **Filter and judge:** about 30 minutes.
- **Repairs:** about 30 minutes, gpt-6-sol.
- **DPO:** about 1–2 hours (one GPU, a few hundred pairs × 2 epochs).
- **Probe:** about 1 hour; suite about 5 hours.

The judge and repair work runs to roughly 1,500 gpt-6-sol calls.

## Risks

- **Overshoot:** the model starts denying real nulls. Pair type C and the probe's contrast check
  guard against it.
- **Narrow gain:** the belief falls on fix-like prompts but persists elsewhere (validate,
  generate). The probe includes validate prompts. T40 and T42 are fix tests, so the suite measures
  the main case.
- **Side effects on validate / generate:** the guardrail evals cover this. DPO touches only
  thinking-mode behaviour on few prompts, and `pref_ftx` keeps the chosen side's likelihood up.
- **No transfer to T40/T42:** if the probe improves but T40/T42 don't, the remaining lever is the
  parked GRPO idea (`spec/grpo_rl_idea.md`), with the belief scan as a reward term.
