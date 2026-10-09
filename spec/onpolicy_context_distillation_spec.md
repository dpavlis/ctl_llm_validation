# On-policy context distillation (OPCD) against the declaration-default belief

Status: spec, 2026-10-09. Background: `spec/ctl2_training_findings.md` §3.16 (what failed, and
why the rule in the prompt works) and §3.17 (literature).

## Goal

Train rb1006 so that **without** the rule in its prompt it reasons as it does **with** it. A
declared, uninitialised `date` / `string` / list / map / number is not null. That should hold on
the hard benchmark cases, T40.FP1 and T42.FP6, and leave everything else unchanged, in particular
thinking-off validate WRONG.

## Why this method

- **The model has the knowledge.** With the rule stated (`configs/eval_rb1006_rule_on.yaml`) it
  makes the false fix in 0/20 runs on T40 and on T42, against 20/20 without.
- **What failed, and why.** Offline DPO on its own answers (dpodef2) either did nothing (lr 5e-6)
  or moved only the easy prompts while damaging validate (lr 2e-5). The literature explains both:
  - offline preference training learns to separate the pairs, not to change generation (Tang et
    al. 2024);
  - forgetting tracks the KL divergence from the base model (RL's Razor).
- **What this method does instead.** On-policy context distillation (SDFT, Shenfeld et al. 2026;
  Padmanabhan et al. 2023; Thinking Machines "On-Policy Distillation") trains on the student's
  *own current* samples, with a *dense per-token* signal from the same model given the rule.
  - On prompts where the rule is irrelevant, teacher and student already agree, so the loss is
    near zero there. That is the built-in protection against side effects.
  - On a declaration, the teacher puts low probability on "defaults to null". The student is
    pushed off it exactly at that token, in its own context, including the hard case.

## Method

**Models.** One set of weights, two roles:
- **student** π_θ = rb1006 + a new LoRA (trainable), with the **plain** system prompt;
- **teacher** π_T = rb1006 with the LoRA **disabled** (peft `disable_adapter()`), with the **rule**
  system prompt: `configs/eval_rb1006_rulev2_on.yaml` / `_off.yaml`, the rule plus the Java/C#
  contrast for generate, validate and fix, **scoped to declared variables**.
  - The first version (`eval_rb1006_rulectx3_on.yaml` / `ruleall_*`) said "a variable declared
    without an initializer… never null" with no scope.
  - On the suite (2026-10-09) the model carried it over to Rollup accumulator fields: T22 says a
    nullable accumulator field starts at 0.
  - It also missed the main bug more often: T14 and T38 fell from 1.00 to 0.20, with more "No
    issues found".
  - Validate thinking-off fell 0.886 → 0.731, with WRONG 5.2% → 8.5%.
  - rulev2 adds: "This covers declared variables only: record fields (input, output, Rollup
    accumulator) follow their metadata, so a nullable field without a default value is null until
    assigned." A teacher with v1 would have distilled the T22 error.

Base weights: the merged export `/home/pavlisd/exports/qwen38_rb1006_sftdpo`, so the teacher is
exactly the rb1006 that was measured. One 27B copy in bf16 (about 54 GB) serves both roles on one
96 GB GPU.

**Loop, per round:**
1. **Sample.** For a batch of prompts, the student generates k completions with the plain system
   prompt and the eval sampling (T=0.4, top_p 0.95, top_k 20, reasoning_effort medium).
   - Thinking **on** for fix and generate prompts.
   - Thinking **off** for validate prompts. The regression we keep causing is in thinking-off
     validate, so that mode must be in the training distribution.
2. **Score.** For every sampled token y_t:
   - the student log-prob `s_t = log π_θ(y_t | plain prompt, y_<t)`, adapter on;
   - the teacher log-prob `r_t = log π_T(y_t | rule prompt, y_<t)`, adapter off, with the same
     tokens after the rule system prompt.
3. **Loss: per-token reverse KL on the sampled tokens.** This is the Thinking Machines
   formulation, a policy gradient with the per-token advantage
   `A_t = r_t − s_t` (detached; no discounting): `L = −Σ_t A_t · log π_θ(y_t)`, averaged over
   tokens. Train only on completion tokens, never the prompt.
   - **Option B, if A is too noisy:** a full-distribution reverse KL at each sampled position over
     the teacher's top-64 tokens (GKD-style, Agarwal et al. 2024, arXiv 2306.13649). Use chunked
     logits like `dpo_logps_chunk_size`.
4. **Update.** 1–2 optimizer steps per sampled batch, then resample. That keeps it on-policy.

**Hyperparameters (starting point):**
- LoRA rank 32 on all linear layers (q, k, v, o, gate, up, down), alpha 32;
- lr 1e-5, AdamW, no warmup beyond 5 steps, grad clip 1.0;
- batch 32 prompts × k=2 samples per round;
- 6–10 rounds;
- cutoff 6,144 tokens; gradient checkpointing.

Watch the mean per-token reverse KL on target prompts (should fall) and on replay prompts (should
stay near zero; if it grows, lower the lr).

## Prompts (prompts only: the teacher supplies the targets, so no reference answers are needed)

| set | count | source | mode |
|---|---|---|---|
| **target** | ~260 | the dpodef1 train split (206) + the 53 declaration-contrast prompts (`dpodef3b_*`) | thinking on (fix/generate), off (validate) |
| **hard-case** | 40 new | see below | thinking on |
| **replay** | ~40% of every batch | random corpus prompts across all task types and components, excluding the eval sets, the suite and the probe | validate: thinking off; others: thinking on |
| **probe (held out)** | 50 | the dpodef1 probe split, never trained | evaluation only |

**Hard-case prompts.** These are new and authored by an agent: prompts only, no answers. Each one
should match the structure that defeated every method so far:
- a module-level or local `date` (or list) declared without an initializer;
- that variable compared, or used in `dateDiff`, on the first record or group;
- right next to one or more **real** nullable input fields that do need a guard;
- all inside a multi-defect fix-to-spec or review task.

Rules for authoring:
- Vary the component, domain and type.
- Don't reuse the T40 (Denormalizer `lastOrderDate` + `.contains()` statuses) or T42 (Partition
  `prevShip` + service code) scenarios.
- Check the prompt code compiles where the prompt says it should.

Before training, confirm the **teacher** is right on these. Sample the teacher with the rule at
k=4 and check the belief rate is ≤ 5%. A prompt the teacher gets wrong would teach the belief.

**Prompts that never leak the rule.** The student never sees the rule; only the teacher does.
Monitor student samples for rule-quoting phrases (the `REFERS` pattern in
`data/self_distill/dpodef2/build_ctx_pairs.py`, e.g. "per the rules"). That text can still
appear, because the teacher assigns it probability.

## Evaluation (gated; the first gate failing stops the run)

| gate | measure | pass |
|---|---|---|
| per round (cheap) | 20 probe prompts × k=2, belief rate; 8 validate tests thinking-off × 1, WRONG; rule-quoting rate in student samples | belief falling; WRONG not rising; quoting ≤ 2% |
| 1. probe | all 50 probe prompts × k=4 through the self-distill filter (`probe_compare2.py`) | belief ≤ 11% (rb1006 22%), **and fix-defaults group ≤ 12/60**; accepted not below rb1006 (27.5%); overshoot (real nulls called safe) not above rb1006 |
| **2. the real target** | T40, T42 thinking on, n=20 | T40.FP1 and T42.FP6 ≤ 5/20 each |
| 3. side effects | validate thinking-off, 3 × n=5; generate thinking off and on, full n=5; fix thinking on n=20 | WRONG ≤ 5% (rb1006 3.2% under gpt-6.1-sol); generate ≥ 0.97 (rb1006 0.975 / 0.972); fix ≥ 0.79 (rb1006 0.801 re-judged; it was 0.863 under gpt-6-sol) |

All judging uses gpt-6.1-sol. Baselines are re-judged rb1006 results (`*_rj61.json`).

Gate 2 is the one every earlier method failed. **Do not proceed to gate 3 on gate 1 alone.**

## Implementation

- **`opcd.py` (new, repo root).** transformers + peft directly, not LlamaFactory, since it needs
  generation, teacher scoring and the update in one loop. Runs in `~/venv`.
  - Reuse the chat template from `test.py` / `self_distill.SamplingClient`, so prompts are
    byte-identical to evaluation (system prompt, `enable_thinking`, `reasoning_effort: medium`).
  - Per round, write to `data/opcd/<run>/round_<n>/`: `samples.jsonl` (prompt id, mode, tokens,
    text, s_t/r_t summaries), `metrics.json` (mean KL on target/replay, belief scan rate, quoting
    rate, lengths).
  - Save the adapter per round. Export the final one through LlamaFactory export (base +
    adapter → `/home/pavlisd/exports/qwen38_rb1006_opcd<run>`) for the eval configs.
- **Sampling speed.** HF `generate` with the adapter on is the simple path: about 1–2 min per
  prompt at k=4 on one GPU, judging from the self-distill pilots. A round of 32 prompts × 2 takes
  about 30–40 min. If vLLM (`~/vllm-serve.sh`) supports this architecture with LoRA hot-loading,
  use it for sampling on a second GPU and keep the trainer on the first. Check this in step 0;
  don't assume it.
- **Memory.** One 27B bf16 copy plus a rank-32 LoRA with AdamW states, gradient checkpointing,
  sequences up to 6k: within 96 GB on one GPU. Teacher scoring is a no-grad forward with the
  adapter disabled.
- **GPUs.**
  - Trainer and sampler on GPU 0 (or 0 + 3 with vLLM).
  - Per-round probes on a free GPU.
  - GPUs 1 and 2 only at the 450 W power limit (`sudo nvidia-smi -i 1,2 -pl 450`, verified before
    launch).
- **Services.** The CloverDX server (port 8083) and the local judge (`127.0.0.1:9001`) must be
  up. Launch via `#!/bin/bash -l` + `setsid nohup` scripts.

## Step 0 results (2026-10-09)

**Implementation:** `opcd.py` (prepare / smoke / train / export), config `configs/opcd_c1.yaml`,
outputs in `data/opcd/<run>/`.

**Prompts.** Prompts are tokenized through test.py's own `LocalMUTClient` path, with the model
load stubbed.
- The rule appears in the teacher prompts only: +120 tokens.
- The user turn and the generation tail are identical for both roles.
- Validate gets the thinking-off tail.

**Smoke test** (HF, 4 samples, 5 steps at lr 5e-5):
- Per-token KL falls from 0.0195 to 0.0133. Values stay finite.
- Peak memory is 57 GB. A step takes 6 s for 4.8k tokens.
- The most-penalized tokens sit on the declaration passage: "`venueId` is not initialized at
  module level without an explicit…", A = −9.8. So the signal is localized, not spread out.

**vLLM sampling works.**
- vLLM 0.23 (`~/vllm-venv`) serves `Qwen3_5ForConditionalGeneration` with LoRA. Per-token
  log-probs match HF to about 0.001 nat/token on the same sample.
- The adapter needs its keys renamed `model.layers.N` → `model.language_model.layers.N`.
  `VllmSampler.publish` does this each round and hot-loads the result.
- Throughput: one round (32 prompts × 2) takes 2.5 min, against about 50 min with HF generate.
- Server: `logs/evals/opcd_vllm_serve.sh` (port 3011, `VLLM_ALLOW_RUNTIME_LORA_UPDATING=True`).
- The trainer (HF) runs on a second GPU.

**Changed from the plan above:**
- **16 rounds:** one pass over the target prompts, since a round now takes about 8 min.
- **Completion cap 6,144 new tokens, cutoff 8,192 total.** A truncated sample is still a valid
  on-policy prefix.
- **Export** merges the adapter into the base with peft (`opcd.py export`). It writes a text-only
  `Qwen3_5ForCausalLM`, not a LlamaFactory export.

## Steps and cost

| step | what | time (approx.) |
|---|---|---|
| 0 | `opcd.py`; smoke test on 4 prompts, 1 round (KL finite and falling on a target prompt; teacher/student prompts verified); vLLM LoRA check | 0.5–1 day of work |
| 1 | hard-case prompts (agent brief), teacher check on them | 2–3 h agent + 1 h GPU |
| 2 | OPCD run, 6–10 rounds | 4–7 h, one GPU |
| 3 | gates 1 → 2 → 3 | 1 h + 1.5 h + ~5 h |

## Risks and fallbacks

- **The per-token signal is too sparse.** The belief costs only a few tokens per trace, so the
  average KL is dominated by everything else. Fix: weight the loss, or report KL, on high-|A_t|
  tokens, or switch to option B (full-distribution KL).
- **The student learns rule-quoting.** It may say "as per the rules" without a rule. Fix: watch
  the quoting rate. Shorten the teacher's rule (drop the contrast sentence) if it rises.
- **Thinking-off validate drifts anyway.** Raise the replay share and the thinking-off validate
  share. Add a final round on replay prompts only (distillation back toward rb1006, as in §3.17
  item 5).
- **No movement on T40/T42 even here.** Next is GRPO with the belief scan and judge as reward
  (`spec/grpo_rl_idea.md`), whose KL-bounded on-policy updates are the other method with tested
  support. Meanwhile, ship the system-prompt rule.
