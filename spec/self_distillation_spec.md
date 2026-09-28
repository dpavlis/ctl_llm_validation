# Self-distilled reasoning — a phase 3 built from the model's own correct traces

An experiment plan for this repository (`llama_train`), not a data-authoring brief. It
replaces authored `reasoning_content` as the way to train the think channel, if the think
channel is trained at all.

**Do this after the SFT+DPO-only retrain** (findings §6, item 0). That run gives the clean
two-phase baseline this experiment is measured against, and it is also the teacher.

## Why

Findings §3.13: training the think channel on *authored* traces replaced the model's own
reasoning with a short, fixed-length, forward-only style, and cost accuracy on every task
type — fix-to-spec most of all (0.740 → 0.385). The model's native thinking, never trained
on, was better everywhere. Authored traces are the problem, not training the think channel
as such.

Self-distillation keeps the style out of the gradient. The model samples its own traces;
only those that led to a correct answer are kept; the model is then trained on them. Every
trace is already in the model's own distribution, so there is almost nothing to learn about
*how* to think, and the gradient concentrates on the places where the model was unsure and
happened to be right. That is the property authored traces lacked: 62% of the old phase-3
loss went on style.

## Hypotheses

- **H1 (primary).** Self-distilled phase 3 improves fix-to-spec with thinking ON beyond the
  untrained baseline (0.740 on the fix6 weights).
- **H2 (secondary).** Filtering out samples with wrong findings reduces native thinking's
  over-flagging on validate. Native thinking finds the most defects but posts WRONG 14.8%,
  against 4.6% with thinking off, which is why thinking is off for validate today. If
  rejection sampling fixes that, thinking-on becomes viable for validate too.
- **H0 (must hold).** Thinking-OFF answers do not regress. Phase 3 changes shared weights, so
  a think-channel phase can bleed into no-think behaviour.

## Step 1 — the teacher is the student

Generate with **exactly the model that phase 3 will train on top of**: the SFT+DPO merge
from the retrain (until it exists, `qwen38_fix6_sftdpo`). A different model's traces — even
another fine-tune of the same base — reintroduce a style gap, smaller but of the same kind.

Use the inference configuration phase 3 will be evaluated under, so the traces match the
prompt the model will see:

- `enable_thinking: true`, `reasoning_effort: medium`, template `qwen3_8`
- the suite's system prompt (the one in `configs/eval_T04_*.yaml`)
- T=0.4, top_p 0.95, top_k 20 — the eval sampling config
- `max_new_tokens: 16384`; **discard** any sample that hits the cap or never closes
  `</think>`. A truncated trace teaches the model not to close the block.

## Step 2 — prompts

Training prompts only. Exclude every prompt in the phase-1 and phase-3 eval sets and every
suite test prompt, compared after whitespace normalisation — the same check
`spec/eval_sets_spec.md` uses.

| task type | prompts | selection |
|---|---|---|
| fix (including all 24 fix-to-spec records) | 150 | all fix-to-spec, then fix-like records favouring semantic defects over syntax typos |
| validate | 150 | weighted to multi-defect records (≥3 findings); include ~20 PASS-on-clean-code records, since H2 is about false positives |
| generate | 100 | weighted to lifecycle components — Rollup, Denormalizer, Normalizer, Join |

Fix and validate dominate because those are the tasks where thinking is, or may become, on
at inference. Generate is included so the phase does not narrow the think channel onto two
task types.

## Step 3 — sample and filter

**k = 4 samples per prompt.** Then filter each sample, cheapest check first:

1. **Format.** Thinking closed, answer present, not truncated. Code answers have a fenced
   block with a `//#CTL2` header; validate answers use the ISSUES / SUGGESTIONS / VERDICT
   format.
2. **Library.** Every function called exists in `resources/ctl-function-library.json`.
3. **Compile, where available.** `dpo_forge/ctl_validate_mcp.py` needs the CloverDX MCP
   server. It failed to connect in the session that wrote this spec (`npx` not on `PATH`),
   so treat this check as optional; the judge in step 4 is the required gate.
4. **Judge against the reference answer.** The training record's own answer is the
   reference. Unlike suite tests there is no rubric, so this needs a new
   reference-comparison prompt for the judge (gpt-5.6-terra, as for the suite). **Accept only
   if** the candidate reaches the same conclusions as the reference and makes **no false
   claim**:
   - validate: the same findings at the same severities, no extra finding that is not a real
     defect, the same verdict;
   - fix: every reference defect fixed, no requirement broken, nothing correct "fixed", and
     the code compiles on inspection;
   - generate: functionally equivalent to the reference on every requirement in the prompt.

   Precision over recall: a sample that is right but incomplete is rejected, not kept. A
   wrong sample that is kept gets trained with full confidence, which is the worst outcome
   this pipeline can produce.

**Pair each kept trace with the model's own answer, not the reference.** The trace reasons
towards its own answer. Pairing it with a differently worded reference produces a record
whose thinking argues for one answer and is followed by another.

**Keep at most one sample per prompt, chosen at random among the accepted ones.** Never
choose the shortest accepted trace — preferring short traces is a length-compression
pressure, and compression is what §3.13 found costly. Record how many of the 4 samples were
accepted:

| accepted | what it means | use |
|---|---|---|
| 4 / 4 | the model already does this reliably | keep, but little to learn |
| 1–3 / 4 | unreliable — the valuable case | keep |
| 0 / 4 | the model cannot do it | **do not** fall back to an authored trace; list these as corpus gaps |

The 0/4 list is a by-product worth having: it is a measured list of what the model cannot
do yet, by task type.

## Step 4 — audit before training

Two checks on the kept set, before anything trains:

- **Trace audit.** Read a random 10% of kept traces for a false CTL2 claim that is never
  corrected later in the trace. A trace can reach a correct answer through a false belief,
  and self-distillation would then reinforce the belief. If more than 5% of the audited
  traces contain one, add a trace-level judge pass for the whole set.
- **Distribution check.** Thinking-length medians per task type, and "wait" / "let me" /
  check-verify rates, should match the teacher's eval-time thinking (findings §3.13: fix
  ~1480 words, "wait" ~44%, "let me" ~89%). They match by construction unless the filter is
  biased. A filter that accepts short traces disproportionately would show here first.

## Step 5 — format and training

Write the kept records in the corpus format — `messages` plus `reasoning_content` on the
assistant turn — and build the tagged file with `convert_think.py --only-reasoning`. That
reuses the path that produces the exact `thought_words` spelling. Never write `<think>` tags
directly. Store provenance on every record: teacher model path, sample index, sampling
parameters, the accept count out of 4, the judge verdict, and the source record's
`source_id`.

Register the file as a new dataset in `LlamaFactory/data/dataset_info.json` (for example
`clover_ctl_selfdistill_data`), and point a phase-3 entry at it. **No authored trace may be
mixed in.**

Phase-3 settings, differing from the old `post_dpo_sft` block where noted:

- `enable_thinking: true`, learning rate 1.0e-5, rank 32 — as before.
- **`cutoff_len: 8192`** (was 4096). Native fix samples run to ~3000 words of thinking plus
  the prompt and answer, so 4096 would truncate them. Measure the kept set with the chat
  template applied, as in the phase-1 cutoff comment in `configs/qwen38.yaml`, and **drop
  any record that still exceeds the cutoff rather than let it be truncated**.
- **`num_train_epochs: 2`**, with `load_best_model_at_end: false` as everywhere. Choose the
  dose by epochs, never by eval_loss; the phase-3 eval set measures the wrong mix (§4.4).
  Export checkpoints at 1 and 2 epochs and evaluate both.

## Step 6 — evaluate

A 2×2, n=5, against the SFT+DPO baseline:

| model | thinking OFF | thinking ON |
|---|---|---|
| SFT+DPO baseline | ✓ | ✓ |
| + self-distilled phase 3 | ✓ | ✓ |

**Give every eval a distinct model name, and stagger the launches.** §3.12 lost a results
file to two evals of one export, launched in the same second.

Report, beyond the suite scores:

- fix with thinking ON (H1), validate with thinking ON and its CAUGHT / MISSED / WRONG (H2),
  and every thinking-OFF score (H0);
- thinking-length medians per task type, and the marker rates from step 4 — the direct test
  of whether the style moved;
- unclosed-`</think>` count, which must stay at 0.

## Decision rules

Generate at n=5 moves ~0.007 between identical runs (§3.12). Differences under ~0.01 there
are unresolved without a repeat. Fix and validate differences have been much larger than
that.

- **Adopt** if fix with thinking ON improves by ≥ 0.05, no thinking-OFF score falls by more
  than 0.01, and fix-task thinking length stays within ±30% of the teacher's.
- **Adopt for validate too** only if thinking-ON validate reaches the thinking-OFF level
  (0.8467 on the fix6 weights) with WRONG at or below ~6%. Otherwise thinking stays off for
  validate even if H1 holds.
- **Drop** if thinking-OFF validate falls by more than 0.02, or fix does not improve. The
  two-phase pipeline then stands, and the 0/4 list goes to corpus work.

## Budget, and a pilot first

Measured on the fix6 weights with the eval harness (transformers, single stream, ~13.5
tokens/s, no vLLM installed in `~/venv`): a thinking-ON fix sample takes a median ~160 s,
other task types ~45 s.

| | samples | single stream, unbatched |
|---|---|---|
| fix | 150 × 4 = 600 | ~27 h |
| validate + generate | 250 × 4 = 1000 | ~12.5 h |
| **total** | 1600 | **~40 h on one GPU** |

`dpo_forge/generator.py`'s `LocalGenerator.generate_candidates()` takes a list of sampling
temperatures and returns one candidate per entry in a single call. Batching the 4 samples
that way, and splitting prompts across the two free GPUs, should bring this to an overnight
run; the batching speed-up is untested on this model and is the main unknown. Judge cost is
about 1600 calls with reference-comparison prompts.

**Run a pilot of 40 prompts first** (15 fix, 15 validate, 10 generate). It should report:

1. acceptance rate per task type and the 4/4 : 1–3/4 : 0/4 split — if fix acceptance is near
   0, the kept set will be tiny and the experiment needs more fix prompts or a larger k;
2. actual throughput with batched sampling, to size the full run;
3. judge reliability: re-judge 20 decisions independently (a second judge pass, or a manual
   read) and report agreement. A judge that accepts wrong samples invalidates everything
   downstream.

## Implementation

A new script, `self_distill.py`, alongside `mut_validate.py`. It can reuse:

- `dpo_forge/generator.py` — `LocalGenerator` for sampling, and `split_thinking()` for
  separating thinking from the answer (it splits on the last `</think>`, which handles the
  Qwen3 template opening `<think>` inside the generation prompt);
- `dpo_forge/judge.py` and `dpo_forge/review_judge.py` for the judge client — the
  reference-comparison prompt itself is new;
- `dpo_forge/ctl_validate_mcp.py` for the optional compile check.

`mut_validate.py` is the closest existing tool but runs the opposite selection. It discards
correct first tries and keeps corrected failures, and it only takes codegen prompts, so it
cannot be used as is.
