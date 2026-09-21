# CTL2 fine-tuning — findings and recommended pipeline

Qwen3.8-27B + LoRA, evaluated on `resources/ctl2_test_suite_v4.json` (38 tests) with a
gpt-5.6-terra judge.

**Every number is a mean of 3 runs at one sampling config** — T=0.4, top_p 0.95, top_k 20,
no presence or repetition penalty. That uniformity is new, and it overturned several
conclusions drawn from earlier measurements. See §4.

Last updated 2026-09-21 with the batch-size experiment (§2.1) and the thinking-boundary
failure mode (§3.4).

---

## 1. Measurements

| model | phase-1 corpus | phase-1 batch | phase 3 | suite | sd | generate | validate | empty answers |
|---|---|---|---|---|---|---|---|---|
| **0917 — old corpus** | 11453 | 12 | none | **0.9234** | 0.017 | **0.9858** | **0.8034** | 0/114 |
| p3_50 | 11468 | 24 | 1.3 ep @ 12/step | 0.8980 | 0.004 | 0.9850 | 0.7308 | 0/114 |
| p1fix | 11468 | 24 | 3 ep @ 24/step | 0.8964 | 0.017 | 0.9738 | 0.7474 | 1/114 |
| sftdpo | 11468 | 24 | none | 0.8963 | 0.013 | 0.9779 | 0.7393 | 2/114 |
| p3_25 | 11468 | 24 | 0.66 ep @ 12/step | 0.8872 | 0.015 | 0.9640 | 0.7393 | 0/114 |
| **b12** | 11468 | **12** | none | 0.8847 | 0.034 | 0.9602 | 0.7393 | **14/114** |
| ckpt100 | 11468 | 24 | 2.6 ep @ 12/step | 0.8710 | 0.014 | 0.9564 | 0.7068 | 0/114 |

All exports are under `/home/pavlisd/exports/` with a matching `configs/eval_T04_*.yaml`.

**Empty answers are excluded from the score shown.** A run where the model never emitted
`</think>` has no answer to judge, and test.py scores it 0. That is a *format* failure, not
a CTL2-quality one, and averaging the two together measures nothing. Those runs were
re-judged with the thinking text as the answer (the answer is complete, just on the wrong
side of the tag) — so the suite column is a like-for-like quality comparison and the
`empty answers` column carries the format failure separately. b12 as literally scored by
test.py was 0.7860; 0.8847 is its quality net of the format failure. See §3.4.

> The sftdpo row moved 0.8787 → 0.8963 for the same reason: its 2 empty answers were both
> complete, correct T30 responses. The earlier 0.8787 under-reported it.

> **The best model is the one trained on the OLD corpus, before any of this work.**
> 0917 leads by +0.025 over the next model and wins on generate *and* validate.

---

## 2. The corpus change made the model worse

At equal sampling, old corpus → new corpus (both SFT+DPO, no phase 3):

| | generate | validate | suite |
|---|---|---|---|
| 0917 (old) | 0.9858 | 0.8034 | 0.9234 |
| sftdpo (new) | 0.9779 | 0.7393 | 0.8963 |
| b12 (new, 0917's batch size) | 0.9602 | 0.7393 | 0.8847 |

The gap is −0.027 suite, not the −0.045 reported earlier: that figure came from sftdpo's
2 empty answers being scored 0 (§3.4). Nothing built on the new corpus since has closed it.

**The loss is almost entirely on validate.** Generate moves −0.008 (inside noise); validate
drops 0.8034 → 0.7393, and lands on exactly 0.7393 in both new-corpus runs. Per test,
against 0917:

| test | type | 0917 | sftdpo | b12 |
|---|---|---|---|---|
| T22 Rollup lifecycle | validate | 0.78 | **0.11** | 0.56 |
| T18 `lookup(X).get(k)` | validate | 0.50 | **0.17** | 0.50 |
| T24 date-pattern severity | validate | 0.92 | 0.75 | 0.50 |
| T7 | validate | 0.83 | 0.67 | 1.00 |
| T26 | validate | 0.67 | **1.00** | 0.78 |
| T28 | validate | 0.50 | **0.83** | 0.83 |

Six of the seven tests that moved more than 0.05 are validate tests. That points at the
review-style records rather than the code-generation ones — which is where
`spec/data_fix_spec_round3.md`'s 14 defective records live: all of them validate examples in
`CTL_LoRA_components_contracts.json`, five of which return PASS on code that violates a
documented component contract. A model trained to approve contract violations is exactly a
model that scores badly on T22.

### 2.1 It is not batch size — tested directly

The obvious confound was that 0917 trained phase 1 on one GPU (effective batch 12) while
every new-corpus model trained on two (batch 24), which also halves the DPO step count.
`qwen38_b12` closed that: the new corpus at 0917's exact batch size, one GPU, no phase 3.

| | phase-1 steps | DPO steps | DPO eval_loss | suite |
|---|---|---|---|---|
| 0917 (old corpus, batch 12) | 1910 | 468 | 0.1155 | 0.9234 |
| b12 (new corpus, batch 12) | 1912 | 472 | 0.1279 | 0.8847 |
| sftdpo (new corpus, batch 24) | 956 | 236 | 0.2491 | 0.8963 |

Batch size fully explains the **DPO loss**: at batch 12 the new corpus converges to 0.1279,
within noise of 0917's 0.1155, where batch 24 stalled at 0.2491. It explains **none of the
suite score**: b12 and sftdpo land within noise of each other (0.8847 vs 0.8963), both ~0.03
below 0917.

Two things follow. The corpus difference is real and costs ~0.03 suite. And **DPO eval_loss
does not predict suite score** — a 2× difference in it moved the suite by less than its own
run-to-run sd. Stop using it to rank runs; it was the basis for calling the batch-24 runs
"undertrained", which they were not.

The corpora differ by only +15 records net. What in those records costs 0.03 remains open —
`spec/data_fix_spec_round3.md` documents 14 defective records found since, all in
`CTL_LoRA_components_contracts.json`, which is the first thing to try.

---

## 3. What still holds

### 3.1 Splitting reasoning records out of phase 1 cost 437 examples

Giving the `<think>`-bearing records their own dataset removed them from SFT entirely:
phase 1 saw 11016 instead of 11468. The loss was concentrated — 19% of the corpus's Rollup
`updateTransform` coverage (all 22 `CTL_LoRAT_rollup_update_transform` records), 18% of
Rollup lifecycle, 11% of `lookup(…).get`. They still trained, but only in phase 3 at
lr 1e-5 / rank 32 instead of 5e-5 / rank 64.

**T37 tracked it exactly: 1.00 → 0.50 → 0.87**, then held at 0.93 in a run where phase 1 was
byte-identical and only later phases changed. In the single-config table it is 0.90–1.00
everywhere the records are in phase 1, and 0.77–0.87 where they are not.

Fixed by giving phase 1 both datasets. With `enable_thinking: false`,
`Template.remove_thought()` strips each block into the *prompt*, so it carries no loss.
Verified through LlamaFactory's loader: 11468 examples, zero `<think>` under loss.

### 3.2 Phase 3 helps, modestly, and mainly on generate

sftdpo → p1fix on identical sampling: suite **+0.018**, generate **+0.023**, validate +0.008.
Thinking length drops 1272 → 932 chars and token-exhaustion failures fall.

Earlier this was reported as +0.022 driven by validate, and as cutting variance 4×. Both were
artifacts of the config drift — see §4.

### 3.3 Post-SFT intensity compresses reasoning

Thinking length falls monotonically with post-SFT: 1272 (none) → 1242 (0.66 ep) → 824
(1.3 ep) → 547 (2.6 ep). The dose–suite relationship is **not** monotonic at equal sampling
(0.8872 / 0.8980 / 0.8710), so the earlier "more post-SFT is monotonically worse" claim does
not survive. What survives is that the longest-trained point (ckpt100) is the worst model and
has the shortest reasoning.

---

### 3.4 Phase 1 erodes the `</think>` boundary; phase 3 restores it

`qwen38_b12` failed to close its thinking block on **14 of 114 runs (12%)**. In every case
the model wrote a complete, well-formed answer — correct CTL2, correct `ISSUES:` /
`VERDICT:` structure — *inside* the thinking channel, then emitted EOS without ever writing
`</think>`. test.py saw no answer and scored 0. Re-judged on the thinking text, those 14
runs average 0.80, and four of them are clean PASSes.

The rate tracks phase-1 step count on the new corpus:

| model | phase-1 steps on new corpus | phase 3 | empty answers |
|---|---|---|---|
| 0917 | 1910 (old corpus) | none | 0/114 |
| sftdpo | 956 | none | 2/114 |
| b12 | 1912 | none | **14/114** |
| p3_25 / p3_50 / ckpt100 | 956 | yes | 0/114 |

Why it happens: phases 1 and 2 both run `enable_thinking: false`, which strips each
`<think>` block into the *prompt*, where it carries no loss. So no gradient ever teaches the
model to **emit** `</think>` — it only ever sees the tag as given context. The base model's
own habit supplies it at first and wears off with training. The old corpus had no
reasoning records in phase 1 at all, which is why 0917 never hit this.

**Consequences.**

1. **Phase 3 is not optional if you evaluate or serve in thinking mode.** It is the only
   phase that puts `</think>` inside the loss region. Every model with phase 3 scored
   0/114; both without it (on the new corpus) failed. Its measured quality contribution is
   small (§3.2) — its real job is the output contract.
2. A model trained through phase 1 + 2 only should be served with `enable_thinking: false`,
   matching how it was trained.
3. Watch the empty-answer count as a first-class metric, not an eval glitch. At 12% it moved
   the suite score by 0.099 — more than any training change measured in this project.

**test.py reported this wrongly**, and the message inverted the diagnosis: it blamed
`max_new_tokens` exhaustion for *every* missing `</think>`, recommending "raise
max_new_tokens or lower reasoning_effort". These runs ended after 30–340 tokens against a
16384 budget — they hit EOS, not the cap. Fixed: `LocalMUTClient` now records
`last_new_tokens` / `last_hit_cap`, and the two causes get different messages and land in
the result as `mut_new_tokens` / `mut_hit_token_cap`.

---

## 4. Measurement — read this before trusting any older number

### 4.1 The eval configs were never equivalent

`eval_qwen38.yaml` used top_p 0.95/0.90 with no penalties; five derived configs used
top_p 0.80 with `presence_penalty: 1.5` and `repetition_penalty: 1.05`. Six models were
compared across that boundary before anyone noticed, because nothing in the results
recorded what was sampled with.

The penalties did not affect models equally — same weights, sampling changed:

| model | suite Δ | generate Δ | validate Δ |
|---|---|---|---|
| **0917** | **+0.057** | +0.009 | **+0.150** |
| sftdpo | +0.013 | +0.008 | +0.021 |
| p3_25 | +0.007 | +0.017 | −0.011 |

They cost the old model 0.15 of validate and the others almost nothing — plausibly because
0917 produces the longest reasoning and `presence_penalty` compounds over length, though
that is untested. **This is what hid the old model's superiority for the entire project.**

Fixed: `test.py` now records resolved sampling parameters on every test result and a
run-level `mut_config` block. A results file is now self-describing.

### 4.2 Temperature: use 0.4

Sweep on p1fix, T ∈ {0.4, 0.6, 0.8, 1.0} at top_p 0.95:

| T | suite | generate | tests sd>0.15 |
|---|---|---|---|
| **0.4** | **0.8964** | **0.9738** | **4** |
| 0.6 | 0.8431 | 0.9548 | 8 |
| 0.8 | 0.8700 | 0.9324 | 8 |
| 1.0 | 0.8444 | 0.9382 | 9 |

Suite and validate zigzag, so 0.6/0.8/1.0 cannot be ranked against each other. The only
monotonic metric is the count of unstable tests. T=0.4 wins on suite, generate and stability,
and is the vendor floor for thinking mode — **do not go below it**; the suite's own per-test
defaults (0.1/0.05) predate thinking mode and are stale.

No repetition or presence penalty: code legitimately repeats tokens (`$out.0.` on every
line), so both bias against valid CTL2.

### 4.3 Noise floor

Suite sd is 0.004–0.017 at T=0.4 — much tighter than the 0.054 seen under the old configs,
but that improvement came from removing the penalties, not from temperature. Differences
below ~0.02 at suite level are not interpretable at n=3.

Per-test instability is mostly **genuine model uncertainty, not sampling noise**: tests like
T22 and T30 sit near 0.5 with sd ~0.47 at every temperature. More runs is the only remedy.

The judge is **not** a source of noise: 19 byte-identical MUT responses were scored
identically, 19/19. An earlier claim that the judge enumerated findings inconsistently was
based on a `difflib.quick_ratio` screen, which is an upper bound — two responses 98% similar
differed in exactly the token under test.

---

## 5. Recommended pipeline

`configs/qwen38.yaml` encodes this. One invocation:

```bash
source ~/venv/bin/activate        # llamafactory-cli must be on PATH
python train.py configs/qwen38.yaml
```

**Phase 1 — SFT, no thinking.** `dataset: clover_ctl_trainign_data,clover_ctl_think_data`
(BOTH — §3.1), `enable_thinking: false`, cutoff_len 3200, lr 5e-5, 2 epochs, bs 2 × accum 6,
rank 64 / alpha 64 / loraplus 2.

**Phase 2 — DPO, no thinking.** `enable_thinking: false` (pairs carry no `<think>`), lr 5e-6,
1 epoch, bs 1 × accum 4, pref_beta 0.1 / pref_ftx 0.1. Runs **between** the SFT phases: its
pairs contain no reasoning, so it belongs while the model is still a non-thinking model.

**Phase 3 — SFT on reasoning, thinking on.** `dataset: clover_ctl_think_data`,
`enable_thinking: true`, lr 1e-5, rank 32. Keep the effective batch ≥24 samples/step; on one
GPU either double `gradient_accumulation_steps` or cut epochs to ~1.

> **Do not skip phase 3 and then evaluate in thinking mode.** It is the only phase that
> trains the model to emit `</think>`; without it 12% of runs answer inside the thinking
> channel and score 0 (§3.4). `--skip-post-sft` is for experiments that will be evaluated
> with `enable_thinking: false`.

**Evaluate** with `configs/eval_T04_*.yaml` at `--runs 3` minimum.

### Operational notes

- **Preserve exports before retraining.** `export_dir` is fixed and each run overwrites the
  last. Two models were lost this way, one of them the then-best. Rename first.
- `reasoning_effort: medium` must match between the training and eval configs.
- `test.py` needs `OPENAI_API_KEY` from `~/.bash_profile` — login-shell only. Source it
  explicitly in non-interactive shells or every judge call 401s.

---

## 6. Open questions, in priority order

1. **What in the new corpus costs 0.03?** Still the most valuable question, now narrowed:
   §2.1 ruled out batch size and DPO convergence, so it is the ~15 changed records
   themselves. `spec/data_fix_spec_round3.md` lists 14 defective records (all in
   `CTL_LoRA_components_contracts.json`, 12 of them the same Denormalizer `$in.0`-in-
   `transform()` contract violation) — applying those upstream and retraining is the next
   experiment.
2. **Known-weak tests across every model**: T22 (Rollup lifecycle, best 0.78), T18
   (`lookup(X).get(k)`, best 0.50), T24 (date-pattern severity, best 0.92). Capability gaps,
   not regressions — they need targeted examples (`spec/reasoning_traces_spec.md`).
3. **`prev3phase` has no export** — the "before" point for §3.1. Its adapters survive at
   `2026-09-18-23-46-45`; rebuildable in ~1h if that row is wanted in the table.
