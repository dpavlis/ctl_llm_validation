# Idea: RL (GRPO) with compiler and judge rewards, LoRA, thinking on

**Status: design note only, not scheduled.** Written on 2026-10-04 to record the idea and the
reasoning behind it. Revisit when SFT recipe fixes stop paying off, or when the answer-less
(unclosed `</think>`) problem, or a lack of gain over base, persists.

## Why

Every SFT-side approach so far ended within noise of base, or broke thinking mode:

| attempt | result |
|---|---|
| self-distillation sd1, sd2 / sd2b | no measurable gain |
| DPO dpo1 (on-policy pairs), dporep (targeted repairs) | no measurable gain |
| retrain on the corrected corpus (rb1003) | thinking broke: answers end inside an unclosed `<think>` on ~10% of runs |
| thinking-phase patch (rb1003 + sd1) | answer-less runs only cut by a third; validate worse |

The memory notes cover these: rb1003-retrain-unclosed-think, dpo1-results,
dporep-targeted-repairs-results, gen2-selfdistill-sd2-results.

RL addresses the root causes directly:

- **On-policy.** The model trains on its own samples. There are no authored traces, so the style
  mismatch is gone; authored traces scored a per-token NLL of 1.77, against 0.13 for the model's
  own.
- **Forgets less than SFT.** It stays close to the starting model under a KL penalty, which is the
  failure we keep hitting.
- **Penalises a failure mode explicitly.** An unclosed `</think>` or a missing answer gets reward 0.
- **LoRA is enough for RL,** even at low rank, because RL updates carry little information per
  step.
- **The reward pieces already exist** in this repo: the compiler, the library check, the belief
  scan and the judge.

## Method (GRPO)

For each prompt, sample a group of G answers (G = 8, thinking on, the same sampling as the evals).
Score each one. Its advantage is its reward minus the group mean, divided by the group standard
deviation. Raise the likelihood of answers above the mean and lower it for those below, with a KL
penalty to the starting model (base `qwen38_fix6_sftdpo`). Use a LoRA, rank 16–32, on the merged
base.

## Reward

Check the cheap, deterministic parts first and only send survivors to the judge:

| stage | check | effect |
|---|---|---|
| 1 | format: a closed `</think>`, a non-empty answer, the requested output shape (code block / `ISSUES:` + `VERDICT:`); `self_distill.format_check` | fail = reward 0, stop |
| 2 | compile: the main CTL block via CloverDX MCP (`self_distill.compile_check`), for generate/fix | fail = reward 0, stop |
| 3 | library: unknown functions (`library_check`) | −0.2 each |
| 4 | belief scan: `KNOWN_FALSE_BELIEFS`, which now covers owner rulings 1–6 | −0.3 per hit |
| 5 | judge: gpt-6-sol against the corpus reference (`Judge.grade`, plus `check_claims` for false claims) | main score in [0, 1]: generate rubric; validate CAUGHT/MISSED/WRONG with WRONG weighted heavier than MISSED (precision over recall); fix: bugs fixed, no broken requirements |
| 6 | length: thinking tokens over a budget | small linear penalty |

The judge is noisy: about 15% of single judgements flip on boundary prompts. Mitigations:
- let the deterministic stages decide wherever possible;
- consider two judge calls on samples near the decision boundary;
- watch the reward variance within groups.

## Data

- **Prompts:** the self-distillation prompt pool (`self_distill.build_pool`), excluding the eval
  sets, the suite and `KNOWN_WRONG_REFERENCES`.
- **Prefer mixed-success prompts.** Choose prompts where base succeeds on some but not all samples
  (1–3 of 4 in the pilot yields). Prompts where every sample scores 0, or every sample scores 1,
  give no group signal. fix_this_code and validate with 3 or more findings were mostly 0/4 for base,
  so they come later.
- **References:** the corpus reference answers, now corrected for rulings 1–6.

## Infrastructure

- **Training stack:** LlamaFactory has no practical GRPO. Use TRL `GRPOTrainer` (or verl /
  OpenRLHF) with vLLM generation, in a separate venv like `~/venv-ds`, so `~/venv` is untouched.
- **GPUs (4× ~96 GB):** vLLM generation on 1–2 GPUs, the LoRA trainer on the others. 27B in bf16
  is about 54 GB of weights per copy.
- **Reward server:** a function wrapping `self_distill` checks, the MCP compiler at
  localhost:8083 and the judge client (`OPENAI_API_KEY`, gpt-6-sol, medium effort).
- **Launch** through a `#!/bin/bash -l` script with `setsid nohup` (memory:
  launch-jobs-via-login-shell).

## Staged plan

1. **Feasibility, deterministic rewards only** (no judge, so cheap). About 200 generate prompts
   with the stage 1–4 rewards; a few hundred steps.
   - *Success:* zero answer-less runs, compile rate up, suite generate not below base, and KL
     bounded.
2. **Add the judge reward** on about 300 mixed-success prompts across generate, validate and fix.
   Monitor reward and KL, and read samples for reward hacking.
3. **Evaluate** on the frozen suite snapshot: generate first, validate WRONG rate (at least 3 runs,
   because validate n=5 swings about ±0.05), fix at n=20.

## Costs and risks

- **Generation time:** 8 thinking samples × prompts × epochs on a 27B model means hours per
  epoch.
- **Judge cost:** tens of thousands of gpt-6-sol calls for stage 2. The deterministic stages cut
  this down.
- **Reward hacking:** vague answers the judge can't fault, flagging everything to avoid MISSED, or
  padding. Penalise WRONG and length, and inspect samples during training.
- **Judge bias becomes model bias:** wherever the judge or the reference is wrong, RL amplifies
  it. The rulings-corrected references and judge reference (`resources/ctl2-basics.md`) reduce
  this, but don't eliminate it.
- **No group signal on prompts the model can't solve** at all, so curriculum and prompt
  selection matter.

## Sources

- Qwen3 Technical Report §4.3 (hybrid thinking, on-policy thinking data):
  https://arxiv.org/html/2505.09388
- RL forgets less, KL-to-base: "RL's Razor" https://arxiv.org/abs/2509.04259; "Retaining by
  Doing" https://arxiv.org/abs/2510.18874
- LoRA for RL / LoRA hyperparameters: https://thinkingmachines.ai/blog/lora/
- On-policy distillation (an alternative or companion step):
  https://thinkingmachines.ai/blog/on-policy-distillation/
- Off-policy traces hurt students: https://arxiv.org/html/2509.22230,
  https://arxiv.org/abs/2502.12143
- Unclosed `</think>` after direct-answer SFT (OraclePhys App. E):
  https://arxiv.org/html/2608.17162
- Self-improvement needs a generation-verification gap ("Mind the Gap"):
  https://arxiv.org/abs/2412.02674
