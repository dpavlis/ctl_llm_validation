# CTL2 fine-tuning — findings and recommended pipeline

Qwen3.8-27B + LoRA, evaluated on `resources/ctl2_test_suite_v4.json` (38 tests) with a
gpt-5.6-terra judge. **Every number below is a mean of 3 runs.** Single-run numbers from
earlier in this work are not reliable and are not quoted.

---

## 1. Measurements

| model | phase-1 corpus | phase 3 | suite | sd | generate | validate | think (median chars) |
|---|---|---|---|---|---|---|---|
| `qwen38_p1fix` | 11468 | 3 ep @ 24/step | **0.8961** | 0.020 | **0.9653** | 0.7628 | 872 |
| `qwen38_p3_25` | 11468 | 0.66 ep @ 12/step | 0.8799 | 0.035 | 0.9474 | 0.7500 | 1191 |
| `qwen38_0917` | 11453 (old) | none | 0.8664 | 0.036 | **0.9773** | 0.6530 | 1245 |
| `qwen38_sftdpo` | 11016 | none | 0.8658 | 0.054 | 0.9427 | 0.7179 | 1174 |
| `qwen38_p3_50` | 11468 | 1.3 ep @ 12/step | 0.8585 | 0.045 | 0.9583 | 0.6667 | 703 |
| (3-phase, old p1) | 11016 | 3 ep @ 12/step | 0.8876 | 0.013 | 0.9514 | **0.7650** | 530 |
| `qwen38` | 11468 | 2.6 ep @ 12/step | 0.8374 | 0.006 | 0.9306 | 0.6581 | 444 |

All exports are preserved under `/home/pavlisd/exports/` with a matching
`configs/eval_qwen38_*.yaml`, so any of them can be re-measured without retraining.

**Current best: `qwen38_p1fix`, suite 0.8961.**

---

## 2. What was learned

### 2.1 Splitting the reasoning records out of phase 1 silently cost 437 examples

Giving the `<think>`-bearing records their own dataset removed them from the SFT phase
entirely — phase 1 saw 11016 records instead of 11468. The loss was not uniform:

| topic | phase-1 coverage lost |
|---|---|
| Rollup `updateTransform` | **19%** (all 22 `CTL_LoRAT_rollup_update_transform` records) |
| Rollup lifecycle generally | 18% |
| `lookup(…).get` | 11% |
| Partition `getOutputPort` | 5% |

Those records still trained, but only in phase 3 — at lr 1e-5 / rank 32 instead of
5e-5 / rank 64, competing with 430 others.

**T37 (Rollup per-record output loop) tracked this exactly: 1.00 → 0.50 → 0.87 as its
examples left and returned to phase 1.** It then held at 0.93 in a run where phase 1 was
byte-identical and only later phases changed, which rules out the alternatives.

The fix is one line — phase 1 takes both datasets. With `enable_thinking: false`,
`Template.remove_thought()` strips each block into the *prompt*, so it carries no loss and
the answer trains exactly as it would without reasoning. Verified through LlamaFactory's
own loader: 11468 examples, zero `<think>` under loss.

### 2.2 The thinking phase helps, and mainly by stopping runaway generation

Adding phase 3 moved suite 0.8658 → 0.8876 and cut run-to-run sd **4×** (0.054 → 0.013).

The mechanism is not subtle. Without it, three runs hit `max_new_tokens=16384` mid-thought
and scored zero for never finishing. With it: none, and critical failures fell 6 → 2.
Thinking length dropped from a median 1174 chars with a 9134 max, to bounded output.

That collapse in thinking length looked like damage at first. It was the model learning to
stop.

### 2.3 But applying phase 3 harder trades validation accuracy for terser reasoning

A dose curve at fixed batch size, phase 1 and DPO held byte-identical:

| post-SFT | suite | validate | think |
|---|---|---|---|
| none | 0.8658 | 0.7179 | 1174 |
| 0.66 ep | **0.8799** | **0.7500** | 1191 |
| 1.3 ep | 0.8585 | 0.6667 | 703 |
| 2.6 ep | 0.8374 | 0.6581 | 444 |

Monotonic. Generate barely moves; **validate absorbs the damage**, and validate tracks
thinking length across all points. The 452 traces have a median of **82 tokens** — pushing
them harder compresses reasoning, and compressed reasoning loses validation accuracy.

### 2.4 Batch size matters more than duration here

`qwen38_p1fix` gets a *full* 3 epochs of phase 3 yet keeps 872-char thinking and scores
0.8961, while 2.6 epochs at half the batch collapses to 444 chars and 0.8374. Fewer,
larger, less noisy updates apply the style more gently.

Note both runs saw **identical data** — 1368 post-SFT samples, 1888 DPO samples. They
differed only in update granularity (24 vs 12 samples/step, 8 vs 4 for DPO) at unchanged
learning rates.

### 2.5 `eval_loss` is actively misleading for this work

The 1-GPU rerun reached better losses in *both* phases — DPO 0.2491 → 0.1486, post-SFT
0.7538 → 0.7102 — and produced a **worse** model (0.8961 → 0.8374). Use the judge suite for
selection. Treat `load_best_model_at_end` on phase 3, which selects on a 60-example eval
set, as unreliable.

### 2.6 The corpus change traded generate for validate

Old corpus → new corpus (both SFT+DPO only): suite flat (0.8664 → 0.8658), but generate
0.9773 → 0.9427 and validate 0.6530 → 0.7179. Most of the generate loss was the phase-1
split in §2.1; restoring it recovered 0.9427 → 0.9653.

### 2.7 Measurement noise sets the floor

Three passes over the *same* model span up to 0.127 (the `qwen38_sftdpo` control ran
0.8134 / 0.9407 / 0.8434). Several tests have sd 0.2–0.4. The judge is also
nondeterministic — it enumerated 6 findings for T5 on one run and 5 on another, with the
suite file unchanged.

Consequences: **n=1 evaluation is worthless here**, and differences below ~0.03 at suite
level are not interpretable. An earlier 0.9321 single-run baseline that drove several days
of "regression" analysis turned out to be 1.85 sd above its own model's 3-run mean — it was
never reproducible.

---

## 3. Recommended pipeline

`configs/qwen38.yaml` already encodes this. One invocation runs all phases:

```bash
source ~/venv/bin/activate        # llamafactory-cli must be on PATH
python train.py configs/qwen38.yaml
```

### Phase 1 — SFT, no thinking

```yaml
dataset: clover_ctl_trainign_data,clover_ctl_think_data   # BOTH -- see 2.1
enable_thinking: false
cutoff_len: 3200            # p99 is 1602 tokens; 1 record of 11468 truncates
learning_rate: 5.0e-5
num_train_epochs: 2
per_device_train_batch_size: 2
gradient_accumulation_steps: 6
lora_rank: 64 / lora_alpha: 64 / loraplus_lr_ratio: 2
```

### Phase 2 — DPO, no thinking

```yaml
dataset: clover_dpo_data
enable_thinking: false      # pairs carry no <think>; block goes to the prompt, no loss
learning_rate: 5.0e-6
num_train_epochs: 1.0
per_device_train_batch_size: 1 / gradient_accumulation_steps: 4
pref_beta: 0.1 / pref_ftx: 0.1 / pref_loss: sigmoid
```

DPO runs **between** the two SFT phases, via the `post_dpo_sft:` section. Its pairs contain
no reasoning, so it belongs while the model is still a non-thinking model; running it last
would align it in a context that never occurs at inference.

### Phase 3 — SFT on reasoning, thinking on

```yaml
dataset: clover_ctl_think_data
enable_thinking: true       # the only phase that trains on <think> content
learning_rate: 1.0e-5
num_train_epochs: 3         # at >=24 samples/step. On 1 GPU use ~0.7 -- see 2.3/2.4
lora_rank: 32 / lora_alpha: 32
```

**Keep the effective batch at >=24 samples/step** (e.g. 2 GPUs at bs 2 x accum 6). If
constrained to one GPU, either double `gradient_accumulation_steps` to 12, or cut
`num_train_epochs` to ~0.7. Do not run 3 small-batch epochs — that is the 0.8374 model.

### Operational notes

- **Preserve exports before retraining.** `export_dir` is fixed, so each run overwrites the
  last. Two models were lost this way, one of them the then-best. Rename first.
- `reasoning_effort: medium` must match between `qwen38.yaml` and `eval_qwen38.yaml`.
  Unset defaults to `xhigh`, which prepends a sentence to the training system prompt.
- Evaluate with `--runs 3` minimum (§2.7).
- `test.py` needs `OPENAI_API_KEY`, which lives in `~/.bash_profile` — login-shell only.
  Source it explicitly in non-interactive shells or every judge call 401s.

---

## 4. Known-weak tests, all models

| test | topic | best seen | note |
|---|---|---|---|
| T22 | Rollup lifecycle completeness | 0.69 | weak in every model |
| T18 | `lookup(X).get(k)` syntax | 0.83 (old corpus) | 0.33–0.50 since |
| T24 | date-pattern severity (WARNING vs ERROR) | 0.75 | corpus teaches WARNING; model says ERROR |

These are capability gaps, not regressions — they were never reliably solved. They need
targeted training examples, not configuration changes.
