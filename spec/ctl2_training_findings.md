# CTL2 fine-tuning — findings and recommended pipeline

Qwen3.8-27B + LoRA, evaluated on `resources/ctl2_test_suite_v4.json` (38 tests) with a
gpt-5.6-terra judge.

**Every number is a mean of 3 runs at one sampling config** — T=0.4, top_p 0.95, top_k 20,
no presence or repetition penalty. That uniformity is new, and it overturned several
conclusions drawn from earlier measurements. See §4.

Last updated 2026-10-09 with the declaration-default belief work (§3.16: answer-only data,
thinking traces and offline DPO did not move it on T40/T42; the rule in the system prompt does,
0/20) and the literature on overriding pretrained priors (§3.17). The judge is now local
gpt-6.1-sol (§4.6). Sections §1–§3.15 were measured with gpt-5.6-terra, and the 2026-09-29 to
2026-10-05 work (self-distillation, DPO rounds, rb1003–rb1005) is in the run memory notes, not
yet in this document.

Earlier update, 2026-09-28, with reasoning effort (§3.15 — the knob is weak; thinking off still
wins validate, effort does not move fix), the model×mode 2×2 and the 0917 baseline correction (§3.14 —
**0917's validate 0.8034 does not reproduce; it is 0.6918/0.8164 at n=5**), why phase 3
hurts (§3.13 — the authored traces replaced the
model's own reasoning style), the phase-3 2x2 (§3.12 — phase 3 is a net cost, thinking is a
per-task trade, and the best model to date), fix6 (§3.11 — T37 closed, best generate yet, fix score down
and why), the SFT-checkpoint confound confirmed and the two dose effects
shown non-additive (§3.9, §4.4), the checkpoint-selection defect (§4.4), the phase-3 dose test
(§3.6), the targeted-examples retrain (§3.7), and the words-per-finding result that explains
WRONG findings (§3.8).

**Two suites are in play.** Rows above `fix3` were measured on the 38-test v4 suite; `fix3`
onward include T39/T40, a new `fix` task type. Suite scores are **not** comparable across the
two — compare generate, validate and the like-for-like column instead.

---

## 1. Measurements

| model | phase-1 corpus | phase-1 batch | phase 3 | suite | sd | generate | validate | empty answers |
|---|---|---|---|---|---|---|---|---|
| **0917 — old corpus** | 11453 | 12 | none | **0.9234** | 0.017 | **0.9858** | 0.8034 ⚠ | 0/114 |
| **fix2 — targeted examples** | 11634 | 12 | 2.1 ep @ 12/step | **0.9189** | 0.022 | 0.9568 | **0.8462** | 0/114 |
| **fix1 — fixed corpus** | 11543 | 12 | 2.8 ep @ 12/step | **0.9089** | 0.024 | 0.9715 | 0.7885 | 0/114 |
| fix1 @ p3 ckpt-100 | 11543 | 12 | 1.6 ep @ 12/step | 0.9081 | 0.021 | 0.9661 | 0.7966 | 0/114 |
| fix1 @ p3 ckpt-50 | 11543 | 12 | 0.8 ep @ 12/step | 0.8803 | 0.044 | 0.9492 | 0.7479 | 3/114 |
| p3_50 | 11468 | 24 | 1.3 ep @ 12/step | 0.8980 | 0.004 | 0.9850 | 0.7308 | 0/114 |
| p1fix | 11468 | 24 | 3 ep @ 24/step | 0.8964 | 0.017 | 0.9738 | 0.7474 | 1/114 |
| sftdpo | 11468 | 24 | none | 0.8963 | 0.013 | 0.9779 | 0.7393 | 2/114 |
| p3_25 | 11468 | 24 | 0.66 ep @ 12/step | 0.8872 | 0.015 | 0.9640 | 0.7393 | 0/114 |
| **b12** | 11468 | **12** | none | 0.8847 | 0.034 | 0.9602 | 0.7393 | **14/114** |
| ckpt100 | 11468 | 24 | 2.6 ep @ 12/step | 0.8710 | 0.014 | 0.9564 | 0.7068 | 0/114 |

### 1.1 The 40-test suite (T39/T40 added — `fix` task type)

Not comparable to the table above on **suite**; generate, validate and the like-for-like
column are. Like-for-like is T1–T38 excluding T5, which changed rubric when B5 was retired.

| model | SFT ckpt | phase 3 | **generate** | perfect | T37 | validate | fix | like-for-like | unclosed `<think>` |
|---|---|---|---|---|---|---|---|---|---|
| **0917, no think** (n=5) | — | none | **0.9832** | 93% | **1.00** | 0.8164 | 0.600 | 0.9342 | 0/200 |
| **0917, think** (n=5) | — | none | **0.9853** | 92% | **1.00** | 0.6918 | 0.635 | — | 0/200 |
| 0917 (38-test, n=3) | — | none | 0.9858 | 92% | 0.97 | 0.8034 ⚠ | — | 0.9258 | 0/114 |
| **fix6_sftdpo, no think** (2×n=5) | **1972** | **none** | 0.9815 | 91% | **1.00** | **0.8467** | 0.533 | **0.9386** | 0/200 |
| **fix6_sftdpo, think** | **1972** | **none** | **0.9804** | 87% | **1.00** | 0.7795 | **0.740** | 0.9147 | 1/200 |
| **fix6** | **1972** | 3 ep | **0.9772** | **87%** | **1.00** | 0.7231 | 0.385 | 0.9035 | 1/200 |
| **fix4 @ p3 ckpt-100** | **950** | 1.1 ep | **0.9691** | 84% | **1.00** | 0.6297 | 0.695 | 0.8647 | 0/200 |
| **fix5** | **1950** | 2.8 ep | 0.9592 | 82% | 0.84 | **0.8064** | 0.610 | **0.9139** | 0/200 |
| **fix2** (38-test) | 1800 | 2.1 ep | 0.9568 | 81% | 0.77 | **0.8462** | — | 0.9243 | 0/114 |
| fix3 | 1950 | 2.9 ep | 0.9527 | 80% | 0.57 | 0.7111 | **0.792** | 0.8742 | 0/120 |
| **fix5 @ p3 ckpt-100** | **1950** | 1.1 ep | 0.9500 | 78% | **1.00** | 0.7897 | 0.440 | 0.9099 | **3/200** |
| fix4 | 950 | 2.6 ep | 0.9462 | 77% | 0.94 | 0.5538 | 0.500 | 0.8245 | 0/200 |

fix4, fix4_ck100, fix5 and fix5_ck100 are **n=5**; the rest n=3. T37 is bimodal — it scores
either ~1.0 or ~0.3, never in between — so n=3 cannot separate a fixed model from a broken
one, and every future T37 claim needs n≥5.

**fix5, fix4 and fix4_ck100 share one SFT training run** (`2026-09-25-19-50-25_sft`). fix4
exported checkpoint-950, fix5 checkpoint-1950, with DPO and phase 3 retrained on top of each.
That makes the SFT-dose comparison a genuine one-variable test, not a between-runs one.

**Validate findings, validate tests only** (§4.3 — never pool generate findings into this):

| model | CAUGHT | MISSED+MISSING | **WRONG** | n | traps sprung | median answer |
|---|---|---|---|---|---|---|
| fix2 | 81.7% | 7.5% | 10.8% | 93 | 4/61 | 64w |
| fix6 | 72.8% | 16.3% | **10.9%** | 147 | 10/106 | 52w |
| **fix5 @ ckpt-100** | **80.0%** | 7.9% | **12.1%** | 140 | 9/103 | 61w |
| **fix5** | 79.2% | 6.7% | 14.1% | 149 | 10/106 | 60w |
| 0917 | 78.7% | **5.3%** | 16.0% | 94 | **2/61** | 114w |
| fix3 | 73.3% | 17.8% | **8.9%** | 90 | 6/65 | 53w |
| fix4 @ ckpt-100 | 58.8% | 17.6% | 23.6% | 148 | 16/109 | 56w |
| **fix4** | **48.6%** | **27.0%** | **24.3%** | 148 | 9/106 | **46w** |

The median-answer column tracks everything else in the table, exactly as §3.8 predicts.

> ⚠ **0917's validate 0.8034 does not reproduce.** It is an n=3 measurement on the 38-test
> suite; at n=5 on the current suite the same model scores **0.6918** with thinking on and
> **0.8164** with it off (§3.14). Every validate comparison against 0.8034 in the sections
> below is optimistic by roughly that margin. Generate's 0.9858 *does* reproduce (0.9853 at
> n=5), so only the validate column is affected.

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

> **0917, trained on the OLD corpus before any of this work, led the table for most of
> this project.** As of `fix2` (§3.7) that is finally over on validate — fix2 scores
> **0.8462 against 0917's 0.8034**, the first model to beat it there — though 0917 still
> leads on generate (0.9858 vs 0.9568) and the suite gap is inside the noise floor.
>
> ⚠ **Both halves of that claim need revising at n=5 (§3.14).** 0917's validate is 0.6918
> with thinking on, so fix2 beat it by far more than 0.004 — and 0917 with thinking *off*
> scores 0.8164, which fix2's 0.8462 still beats. The generate lead is real and reproduces.
>
> **As of fix5 (2026-09-27) 0917 still leads on generate, 0.9858 vs 0.9592, and that gap
> is now the main unexplained result.** It is not T37 — fix5 matches 0917 there. It is
> spread thinly across the suite, which is why like-for-like stays close (0.9258 vs
> 0.9139). fix5 is the best model from the new corpus: best generate of the three
> full-SFT variants, best validate (0.8064), and much the best of them on the fix tests.
> Read §3.8 before treating fix2's higher WRONG count as a regression: it is a
> side effect of answering more completely, not of knowing less.

---

## 2. The corpus change made the model worse — since fixed

> **Resolved 2026-09-21 (§3.5).** The cause was 115 prompts carrying two
> different answers, and `qwen38_fix1` closed the gap to statistical noise
> (t = −0.86 against 0917). This section is kept because the diagnosis path
> matters: three wrong explanations were ruled out before the right one.

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

### 3.2 Phase 3 helps, modestly, and mainly on generate — SUPERSEDED by §3.12

> Measured before the corpus fixes. On the current corpus phase 3 is a net cost on every
> axis; see §3.12. Kept for the trail.

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

---

### 3.5 The corpus fixes worked; phase-3 dose is now the binding constraint

`qwen38_fix1` (2026-09-21) applied everything at once: the deduplicated
11543-record phase-1 corpus, the 752-record reasoning set, all three phases, and
0917's effective batch of 12 so the corpus was the only variable left.

| | suite | sem | generate | validate | empty |
|---|---|---|---|---|---|
| 0917 (old corpus) | 0.9234 | 0.0097 | 0.9858 | 0.8034 | 0 |
| **fix1** | **0.9089** | 0.0137 | 0.9715 | 0.7885 | **0** |
| sftdpo (broken corpus) | 0.8963 | 0.0072 | 0.9779 | 0.7393 | 2 |

**fix1 is no longer distinguishable from 0917**: difference −0.0145 against a
standard error of 0.0168, t = −0.86. The −0.027 corpus gap in §2 is gone, and
the model built on the new corpus now matches the one built before this project
started. Two things did it, and the per-test evidence separates them cleanly:

- **The duplicate-answer conflict was real.** 115 prompts had been training a
  wrong answer in phase 1 and the corrected one in phase 3. **T22 went 0.11 →
  0.75** and T18 0.17 → 0.67, the two tests §2 named as the worst regressions.
  Validate overall 0.7393 → 0.7885.
- **Phase 3 eliminated the format failure.** 0 empty answers, against 2 for
  sftdpo and 14 for b12 (§3.4).

**What is now costing the remaining 0.015 is output length, not correctness.**
fix1 answers with a median of **58 words** against 0917's 132 — the tersest of
every model measured. On enumeration tests that is fatal: T5 (six seeded bugs)
scored 0.17 in all three runs, finding exactly one bug and stopping, where 0917
found five in a 333-word answer. T24 is the other loss and a different defect —
the model identifies all three date-pattern issues correctly but marks them
ERROR where the rubric requires WARNING, a severity-calibration problem worth
watching given how many round-3 fixes escalated severity.

The corpus is not the cause: its reasoning-derived answers are the same length
as the rest for validate (41 vs 38 words median) and *longer* for generate (91
vs 53). Phase 3 is, and the dose is the lever (§3.3):

| | phase-3 dose | response words | suite |
|---|---|---|---|
| sftdpo | none | 138 | 0.8963 |
| p3_50 | 1.3 ep | 84 | 0.8980 |
| fix1 | 2.8 ep (ckpt-175/189) | 58 | 0.9089 |

fix1 took checkpoint-175 of 189 — nearly the full 3 epochs, which the dose
experiments found worst at 452 records. `load_best_model_at_end` chose it on
eval_loss, which §2.1 already showed does not track suite score. Checkpoints
25–189 are all preserved under `2026-09-21-13-55-11_postsft`, so testing an
earlier one is an export plus an eval, no retraining.

### 3.6 Backing off the phase-3 dose buys length but not quality — question closed

§3.5 named the phase-3 dose as the one lever left, on the theory that fix1's
58-word answers were an artifact of taking checkpoint-175 of 189. Checkpoints 50
and 100 were exported from the same run — identical phase-1 (ckpt-1750) and DPO
(ckpt-450) adapters, only the phase-3 checkpoint differs — and evaluated at
`--runs 3`:

| | phase-3 dose | median words | suite | generate | validate | empty |
|---|---|---|---|---|---|---|
| ckpt-50 | 0.8 ep | **94** | 0.8803 | 0.9492 | 0.7479 | 3 |
| ckpt-100 | 1.6 ep | 62 | 0.9081 | 0.9661 | 0.7966 | 0 |
| fix1 (ckpt-175) | 2.8 ep | 58 | 0.9089 | 0.9715 | 0.7885 | 0 |

**The dose does control length, and length alone does not buy quality.** ckpt-50
answers in 94 words — most of the way back to 0917's 132 — and is the *worst*
model of the three on suite, generate and validate at once, and the only one to
reintroduce the `</think>` format failure (3 empty answers, the §3.4 mode
returning as the dose drops). ckpt-100 is indistinguishable from fix1 (0.9081 vs
0.9089) while answering four words longer.

So terseness was a symptom, not the cause. The remaining gap is what the model
knows how to say, not how long it is permitted to say it — which is what §3.7
tests directly.

### 3.7 Targeted examples: recall up sharply, generate down slightly

`qwen38_fix2` (2026-09-22) is a full three-phase retrain on the corpus after
adding ~91 records from `spec/targeted_examples_spec.md` — severity ERROR/WARNING
calibration, the Rollup vs Denormalizer `$in.0` contrast pairs, and outer-join
key guards. Both corpora grew: phase 1 11543 → 11634, reasoning 752 → 843. Best
checkpoints ckpt-1800 / ckpt-450 / ckpt-150.

**Validate is up 0.058 and is the best measured on this suite, 0917 included.**
Counting validate tests only:

| validate only | fix1 | fix2 |
|---|---|---|
| CAUGHT | 74.2% | **81.7%** |
| MISSED + MISSING | 19.4% | **7.5%** |
| WRONG | **6.5%** | 10.8% |
| false-positive traps triggered | 8/63 (13%) | **4/61 (7%)** |
| median thinking words | 57 | **123** |

Group by group against what the spec targeted:

- **Group B (Rollup/Denormalizer) worked.** T22 trap triggers 3 → 1. The
  contrast-pair construction — same code shape, two components, opposite
  verdicts — is the format to reuse.
- **Group A worked in one direction only.** T24, the flagship over-escalation
  case, went from 3 WRONG findings to **0**: the factual inversions (`DD` as day
  of week, lowercase `yyyy` as week-based year) and the ERROR escalation are both
  gone. But *under*-escalation is untouched — T16 (unreachable code) and T18
  (null dereference after a lookup miss) still mark a compile/runtime failure
  WARNING where the rubric requires ERROR, 3 occurrences before and 4 after.
  The ~25 WARNING-side records landed; the ~25 ERROR-side records did not.
- **Group C (outer-join key guard) did nothing.** T34 sits at 3 WRONG findings
  before and after.

Generate slipped 0.9715 → 0.9568, driven by T33 and T37; that is inside the noise
floor per-test but worth re-checking on the next run.

### 3.8 WRONG findings are a length budget, not a knowledge gap

fix2's WRONG count rose (6.5% → 10.8% of validate findings) at the same time as
its recall, and T5 accounts for most of the increase: **0 WRONG findings under
fix1, 5 under fix2**. That looks like a regression and is not one.

fix1 scored zero WRONG on T5 because it **found one of the six seeded bugs and
stopped** — 33 words, all three runs. fix2 finds four or five. Every one of its
WRONG findings is attached to a bug it correctly identified, with the correct fix,
and a mangled rationale:

> `[ERROR] isNull($in.0.amount) is not a CTL2 function; use isnull($in.0.amount).`

The fix is right. The reason is false — `isNull` exists, with a two-argument
`(record, field)` signature; the one-argument call is an arity error.

**The corpus is not the source.** Grepping both corpora for the false claims
fix2 produced returns **zero** matches for "isNull is not a declared function",
"conditional-fail is undocumented" and "date literal invalid", while the correct
statements appear 22 and 45 times. The error is already present in the `<think>`
block, which goes telegraphic on multi-bug reviews — one clause per bug.

What predicts a WRONG finding is how many words the answer spends **per finding
it reports**. Pooled across fix1 and fix2, validate runs:

| words per reported finding | runs containing a WRONG |
|---|---|
| < 20 | **45%** |
| 20–25 | 17% |
| 25–35 | 21% |
| ≥ 35 | **3%** |

A 15× swing, and it holds within each model separately: runs with a WRONG average
20–22 words per finding, runs without average 33–36.

The mechanism is that **the correct statement does not fit**. The corpus explains
the `isNull` arity rule in 27–39 words. At six findings the model allots about 20,
truncates, and a qualified true statement collapses into an unqualified false one.
The corpus teaches exactly this habit:

| findings in the record | corpus mean words per issue line |
|---|---|
| 1 | 22.9 |
| 2 | 19.1 |
| 3 | 18.7 |
| 4 | 18.4 |
| 5 | 17.4 |

Median 19 words per `[SEVERITY]` line overall, **shrinking as bug count rises** —
the opposite of what the failure mode needs. And there is almost nothing to learn
multi-bug reviews from: 16 of 1094 validate-format records have ≥5 findings, and
in the reasoning corpus **1 of 300**, with none above five. T5 has six.

> **Consequence for the whole project: improving recall manufactures WRONG
> findings out of knowledge the model already has.** Any change that makes the
> model report more bugs pushes it from the safe ≥35 words-per-finding bucket into
> the <25 danger zone. The lever is a per-finding explanation floor and multi-bug
> examples — see `spec/explanation_budget_spec.md` — not more severity examples.

One genuine false positive did occur, in the most compressed run of all (~14 words
per finding): T5 run 1 flags the valid date literal `1990-01-01` as needing quotes,
a change that would introduce a type error. That is the one failure that matches the
harm model behind the precision-over-recall rule — sending a developer to fix
something that is not broken — and it appeared where compression was worst.

---

### 3.9 The two dose effects are not additive; the safe phase-3 floor scales with SFT dose

fix4 and fix5 come from the **same SFT training run**, exported at checkpoint-950 and
checkpoint-1950. That makes the SFT-dose comparison a one-variable test, and it separates
two things that had been confounded in every earlier run:

| | generate | validate | T37 |
|---|---|---|---|
| SFT 950, phase 3 full (fix4) | 0.9462 | 0.5538 | 0.94 |
| SFT 950, phase 3 ckpt-100 | **0.9691** | 0.6297 | **1.00** |
| SFT 1950, phase 3 full (fix5) | 0.9592 | **0.8064** | 0.84 |
| SFT 1950, phase 3 ckpt-100 | 0.9500 | 0.7897 | **1.00** |

**SFT dose drives validate** (0.55 → 0.81 at matched phase 3; phase-3 dose moves it ~0.06).
**Phase-3 dose drives T37.** But the generate gain from a light phase 3 **did not carry
over**: on the fully-trained SFT it reversed, 0.9592 → 0.9500. ckpt-100 was not adding
generate quality on fix4 — it was compensating for a half-trained SFT adapter, and with a
properly trained one underneath there is nothing left to compensate for.

**This retires fix4's validate collapse as a corpus problem.** fix4 posted the worst
validate score measured (0.5538) on the same corpus that scored 0.8064 at full SFT dose.
Nothing was wrong with the Rollup corpus work; the adapter was half-trained (§4.4).

#### The light dose reintroduced the `</think>` format failure — but only at full SFT

| model | unclosed `<think>` |
|---|---|
| 0917, fix2, fix3, fix4, fix4 @ ckpt-100, fix5 | 0 / 114–200 |
| **fix5 @ ckpt-100** | **3 / 200** (T5 runs 2 & 5, T11 run 1) |

The model wrote its answer inside the thinking channel and emitted EOS after 144–447
tokens — nowhere near the 16384 budget, so this is a format failure, not truncation.

**It is not a corpus defect.** All 1053 phase-3 records have balanced tags in
LlamaFactory's exact `thought_words` spelling, phase 1 has zero `<think>` tags, and the
longest phase-3 record is 3885 tokens against a 4096 `cutoff_len` — nothing is being cut
mid-block.

The mechanism is dose interaction. Phase 3 is the only phase that trains `<think>`
content, and checkpoint-100 of 264 is ~1.1 epochs. On fix4's weak SFT that sufficed; on
fix5's fully-trained SFT there is more non-thinking behaviour underneath to overwrite, and
1.1 epochs no longer reliably installs the closing tag. §3.4 found phase 1 erodes the
`</think>` boundary and phase 3 restores it — this is the quantitative form of that:
**the phase-3 dose needed to restore the boundary scales with the phase-1 dose.** Do not
carry a phase-3 checkpoint across a change in SFT dose without re-checking the format
failure count.

### 3.10 The fix task (T39/T40): 1222 examples, 9 of the right shape, 0 with reasoning

T39/T40 are the weakest tests for every model (0.44–0.79, none above 0.8). The obvious
explanation — no fix-type training data — is **wrong**. The corpus has 1222 fix-like
records, 10.4% of it, including two dedicated files
(`CTL_LoRA_fix_this_code.json`, `CTL_LoRAT_fix_this_code_think.json`).

The gap is shape, not volume. T39/T40 ask for a **compound** answer: *"List every problem
you fix with the reason, then give the complete corrected code."*

| fix-like records | count |
|---|---|
| total | 1222 |
| enumerate **zero** issues — corrected code only | **1069 (87%)** |
| enumerate ≥3 issues | 107 |
| prompt states a specification | 62 |
| **both (the T39/T40 shape)** | **9** |
| **…of which carry `reasoning_content`** | **0** |

So the corpus trains the second half of the task almost exclusively, and **phase 3 — the
phase that runs last and sets answer shape — contains no T39/T40-shaped record at all.**

The failure signature confirms it is not a recall problem. Across fix5 and fix5 @ ckpt-100
every T39/T40 failure is **WRONG, never MISSED**: the model does enumerate, and explains
incorrectly. Words-per-issue tracks the score exactly as §3.8 predicts:

| model | words per issue | fix score |
|---|---|---|
| fix3 | 27 | 0.792 |
| fix5 | 26 | 0.610 |
| fix5 @ ckpt-100 | **17** | **0.440** |

The light phase-3 dose compressed fix explanations below the ~25-word threshold, which is
the mechanism behind that 0.44. **The fix task is a third instance of the length-budget
result, not a separate capability gap** — and the remedy is the same: spec-shaped fix
records that enumerate each defect with a reason at ≥35 words, carrying
`reasoning_content` so they reach phase 3.

---

### 3.11 fix6: T37 closed and the best generator yet, but targeted fix records made the fix score worse

fix6 is the first run with a fully deterministic adapter chain — `load_best_model_at_end:
false` actually took effect on all three phases (checkpoint 1972/1972, 472/472, 270/270,
and **zero** `Loading best model` lines in the log; fix5's run still had two). It also
carries the 24 fix-to-spec records and `cutoff_len` raised to 4096.

**Two results are unambiguously good:**

- **Generate 0.9772, 87% perfect runs** — the best the new corpus has produced, cutting
  the gap to 0917 from 0.027 to 0.009. (§3.14 re-measures 0917 at n=5: the
  remaining generate gap to the best no-phase-3 model is ~0.003, a tie.)
- **T37 is 1.00 across all five runs at FULL phase-3 dose.** Every previous perfect T37
  required the light dose that §3.9 showed costs generate and the `</think>` boundary.
  That trade-off is gone; the Rollup work of §3.9 is closed.

**The fix score fell to 0.385**, against fix5's 0.610 — despite 24 records written
specifically for that task.

#### The §3.10 length mechanism does NOT explain this — retracted for this case

Words-per-issue moved the *right* way, 26 → 29, and the score still dropped. §3.10
correctly identified the length budget as the mechanism behind the fix3/fix5/fix5-ckpt100
ordering, but it is not what is happening here. What changed is the **corrected code**,
not the enumeration:

| | fix5 | fix6 |
|---|---|---|
| defects CAUGHT (of 40) | 31 | 29 |
| words per issue | 26 | 29 |
| **traps + forbidden sprung** | **7** | **15** |

Detection and explanation are flat to slightly better. The traps doubled, and they are all
about the code the model then writes:

| trap | fix5 | fix6 | what it catches |
|---|---|---|---|
| `T40.F3` | 2 | **4** | corrected code will not compile, or adds a new runtime failure |
| `T39.F2` | 0 | **3** | the fix breaks a *different* numbered requirement |
| `T39.FP2` | 0 | **3** | claims `~=` is a partial match (it is a whole-string regex) |
| `T40.FP1` | 5 | 5 | declared-but-unassigned variables "start null" — unchanged |

A judge note states it plainly: *"Three of four seeded defects are correctly fixed. The
date-pattern correction is defective because it changes the required calendar year `yyyy`
to week year `YYYY`, and the response also falsely criticizes the originally correct
whole-string regex."*

#### The cause is in the spec that generated the records

`spec/fix_to_spec_examples_spec.md` weighted the enumeration half heavily — a 35-word
floor per item, reasons before code, requirement-number grounding — and said almost
nothing about the corrected code beyond "the complete transform, every contract function".
Auditing the 24 records against what the benchmark actually penalises:

| property | records having it |
|---|---|
| answer affirms some construct is already correct | 14 / 24 loosely worded, **5 / 24** in the explicit form the amended spec now requires |
| **reasoning** affirms some construct is already correct | **1 / 24** explicit (6 / 24 loose) — the spec asked for this |
| **seeds a construct that LOOKS broken but must be left alone** | **0 / 24** |
| states that the fix must not break another requirement | 0 / 24 |

So the records train enumerate-and-rewrite with no counterweight teaching restraint, and
the corresponding corpus-wide effects are consistent: validate WRONG fell to 10.9% (best
since fix3) while validate MISSED rose to 16.3% and median validate answers shrank to 52w.
The model got better at *stating* things and worse at *leaving things alone*.

**The lesson generalises beyond this task.** Records that teach finding defects also teach
finding defects that are not there, unless the same records demonstrate the negative case.
Every future defect-oriented corpus round should seed correct-but-suspicious constructs and
require the answer to name them as correct.

#### One unclosed `<think>`

1/200 (T5 run 2). Expected 0: §3.9 attributed the failure to a light phase-3 dose over a
full SFT, and this run is full dose on both. So the dose explanation is necessary but not
sufficient — a low background rate exists independently. Too small to act on at n=1; record
it and watch.

---

### 3.12 Phase 3 is a net cost, and inference-time thinking is a per-task trade

A 2×2 on the fix6 weights, n=5 throughout. The SFT+DPO rows share one export
(`qwen38_fix6_sftdpo`, SFT checkpoint-1972 + DPO checkpoint-472, no phase-3 adapter), so the
last two rows differ **only** in the `enable_thinking` flag at inference.

| chain | thinking | generate | perfect | validate | fix | T37 | like-for-like |
|---|---|---|---|---|---|---|---|
| SFT+DPO+phase3 (fix6) | ON | 0.9772 | 87% | 0.7231 | 0.385 | 1.00 | 0.9035 |
| **SFT+DPO** (mean of 2×n=5) | **OFF** | 0.9815 | 91% | **0.8467** | 0.533 | 1.00 | **0.9386** |
| SFT+DPO | ON | 0.9804 | 87% | 0.7795 | **0.740** | 1.00 | 0.9147 |
| *0917 reference* | *—* | ***0.9858*** | *92%* | *0.8034* | *—* | *0.9258* | |

The thinking-OFF row is the mean of **two independent n=5 runs**, because the first was run
twice (see the data-integrity note). Keeping both is worth it — they disagree by more than
the suite sd suggested:

| | run 1 | run 2 | mean |
|---|---|---|---|
| generate | 0.9848 | 0.9781 | 0.9815 |
| validate | 0.8477 | 0.8456 | 0.8467 |
| fix | 0.500 | 0.565 | 0.533 |
| like-for-like | 0.9411 | 0.9361 | 0.9386 |

**Generate at n=5 is not reliable to three decimal places.** The two runs differ by 0.0067,
which is larger than several differences this project has treated as real. Validate, by
contrast, reproduces to 0.002. Treat any generate difference under ~0.01 as unresolved
without a second run.

#### Phase 3 costs accuracy on every axis — this supersedes §3.2

Holding thinking ON and removing only the phase-3 adapter: generate 0.9772 → 0.9804,
validate 0.7231 → 0.7795, **fix 0.385 → 0.740**. §3.2 ("phase 3 helps, modestly, and mainly
on generate") was measured before the corpus fixes and no longer holds. The whole of §3.9's
dose-tuning problem dissolves too: at zero dose there is no dose to tune.

**T37 is 1.00 across five runs with no phase-3 adapter at all.** The Rollup fix lives in the
phase-1 corpus, not the reasoning round — which also retires the §3.9 finding that T37 was
phase-3 dose-sensitive. It was, on the old corpus; it no longer is.

This does not say reasoning data is worthless — those records still train in phase 1 with
their `<think>` blocks stripped, and that is where their content lands. It says the extra
gentle round on the tagged subset, running last, is now a net negative.

#### Inference-time thinking is a genuine trade, not a free win

Same weights, flag flipped:

| | thinking OFF (2×n=5) | thinking ON |
|---|---|---|
| generate | 0.9815 | 0.9804 | 
| validate | **0.8467** | 0.7795 |
| **fix** | 0.533 | **0.740** |
| median validate answer | **65w** | 124w |
| validate CAUGHT / WRONG | **86.8% / 4.6%** | 81.2% / 14.8% |

**Generate is a tie** — 0.9815 against 0.9804, inside the run-to-run spread measured above.
An earlier revision of this section claimed thinking-off won on generate; that rested on a
single run of 0.9848 and did not survive the repeat. Thinking helps the one task that needs
multi-step deliberation — fix-to-spec, +0.21 — and costs 0.067 on validate. On validate it nearly doubles the answer and the extra words
become WRONG findings: **§3.8's length mechanism running in reverse.** Past ~35 words per
finding the budget stops buying correctness and starts buying elaboration, and elaboration
past the point of knowledge is where false claims come from.

**Practical rule: thinking off for generate and validate, on for fix-to-spec.**

#### The current best model

`qwen38_fix6_sftdpo` with thinking off is the best model this project has produced, on the
strength of validate rather than generate. Generate 0.9815 sits below 0917's 0.9858 by about
the run-to-run spread, so the two are not separated; validate 0.8467 beats 0917's 0.8034 and
fix2's 0.8462 — the previous record — and like-for-like 0.9386 beats 0917's 0.9258.

Its second run posted **the lowest WRONG rate ever measured, 4.6%**, with the *highest*
CAUGHT rate, 86.8%. Every earlier low-WRONG model bought it by answering tersely and missing
findings instead (fix3: WRONG 8.9% but MISSED 17.8%). This one does not trade. `configs/mut_validate_qwen38.yaml`
was repointed to it on 2026-09-28, with `enable_thinking: false`.

> **Data-integrity note.** The thinking-OFF results JSON was overwritten. Both configs point
> at the same export, so test.py derived the same model name, and the two runs were launched
> in the same second — identical output filenames. The scores above are reconstructed from
> the 200 per-test rows in the run log and agree exactly with the summary line, but the
> judge-finding detail for that row is lost. A re-run regenerated it and came in at generate
> 0.9781 / validate 0.8456 / fix 0.565, which is why this section reports means of two runs.
> Note also that `logs/Qwen3.8-27B.yaml` had preserved all three runs by model and timestamp,
> so only the per-finding detail of the first run was actually lost, not its scores. **When running two evals against one
> export, give them distinct model names or stagger the launches.**

---

### 3.13 Why phase 3 hurts: the authored traces replaced the model's own reasoning

§3.12 showed phase 3 is a net cost. This section is the mechanism. The key comparison is
already inside §3.12's 2×2: the SFT+DPO model evaluated with thinking ON never had loss on
a reasoning trace — phase 1 and DPO both put an empty `<think>` block in the prompt — so its
thinking is the model's own. It beat the phase-3 model at the same inference setting on
every task type, fix most of all (0.740 against 0.385). So the question is what differs
between the thinking the model does unprompted and the thinking the traces taught it.

#### Four sources of thinking, measured the same way

| | base Qwen3.8-27B, no LoRA | SFT+DPO, thinking ON | after phase 3 (fix6) | training traces |
|---|---|---|---|---|
| median words — generate | 1142 | 268 | 71 | 134 |
| median words — validate | 802 | 239 | 131 | 172 |
| median words — **fix** | **2976** | **1484** | **177** | **146** |
| spread across task types | — | 6.2× | 2.5× | **1.3×** |
| "wait" | 100% | 44% | **0%** | 0.4% |
| "actually" | 100% | 46% | 1.5% | 1.0% |
| "let me" | 100% | 89% | 0.5% | 0.0% |
| check / verify | 82% | 67% | 17% | 11% |
| first person ("I") | 100% | 55% | 1% | 0.4% |
| typical opening | "The user wants a…" | "The user wants a…" | a declarative fact | a declarative fact |

The base column is a style sample (11 tests × 1 run, `configs/eval_T04_base_think.yaml`;
`/home/pavlisd/exports/qwen38_base` symlinks the HF snapshot), not a benchmark; its word
counts are for those 11 tests, where the SFT+DPO model's own medians were 429 / 178 / 1409.
The markers are unambiguous even at that size. Its scores were mostly 0 — genuine CTL2
failures (Java JSON APIs, a Reformat-style Rollup, the `~=` misconception), not format
failures: every answer was complete and fenced.

**Read across the row.** Base and SFT+DPO reason in the same style — same opening, same
self-checking — and SFT on answers alone shortened that thinking 2–4× without changing its
character. Phase 3 then **replaced** the style with the traces': third person, declarative,
forward-only, nearly constant in length.

#### Mechanism 1 — length stopped scaling with difficulty

Natively the model thinks six times longer on a fix task than on a validate task. The
training traces spend *less* on fix (146 words) than on validate (172) — a 1.3× spread
across all three task types. After phase 3, fix thinking fell from 1484 words to 177, and
the fix score from 0.740 to 0.385.

Per test, the more phase 3 compressed a test's thinking, the more score it lost. Split the
40 tests into terciles by compression ratio (native words / phase-3 words):

| tercile | median compression | mean score lost to phase 3 |
|---|---|---|
| least compressed | 1.6× | +0.028 |
| middle | 2.9× | +0.035 |
| most compressed | 5.5× | +0.051 |

The trend is monotone but modest at 40 tests. The large individual losses are concentrated
on the hardest tests: T39 (fix, +0.52 at 10.4× compression), T5 (multi-bug validate,
+0.40), T18 and T22 (+0.40, +0.33 — both long listed as known-weak capability gaps), and
T40 (fix, +0.19). Native thinking scores higher on 12 tests, lower on 8, tied on 20.

#### Mechanism 2 — self-verification was trained out

In native traces, "actually, let me reconsider" is where the model checks itself. Sampled
from the hard tests, these moves re-derive `isnull` casing, whether `~=` is a whole-string
or partial match, and the `lookup()` API — mid-answer, before committing. Only **3.9%** of
the 1077 training traces contain *any* re-check move.

This is not an accident of authoring. `references/CTL2_Reasoning_Trace_Playbook.md`, the
style guide the generating agents followed, bans it explicitly:

> *"Forward motion only. No 'wait', no 'hmm', no 'let me reconsider', no restarts, no
> self-doubt performed for its own sake… This is the rule that buys you the token savings
> over stock Qwen behaviour, so hold it strictly."*

and states the goal as *"a thinking model that reasons accurately about CTL2 in few
tokens"*, with length bands of 12–150 words. The playbook also contradicts itself: its own
rule R3 says *"match what the base model already produces inside `<think>`; the further you
move from it, the more data you need"* — while R7 bans the base model's most characteristic
moves and the bands sit 3–10× below its native length.

#### What that does to validate

| mode | CAUGHT | MISSED | WRONG |
|---|---|---|---|
| no thinking | **86.8%** | 8.6% | **4.6%** |
| native thinking | 81.2% | **4.0%** | 14.8% |
| phase-3 thinking | 72.8% | 16.3% | 10.9% |

Native thinking finds the most defects and pays for it in WRONG findings (§3.8 in reverse:
past ~35 words per finding, extra words buy elaboration, not correctness). Phase-3 thinking
pays **the cost of thinking without the benefit** — WRONG more than twice no-think's, MISSED
four times native's. Native thinking's two largest per-test losses to phase 3 (of eight) point the same way:
T7 and T4 are both traps on *correct* code, where long thinking talks itself into a false
positive. That vice is real, and it is why thinking stays off for validate (§3.12) — but the
remedy is not to train the model to think less on everything.

#### The traces are well-made; the premise is wrong

By the playbook's own standard the execution is good. Only **4%** of validate traces open by
asserting the verdict — the anti-pattern the playbook worked hardest against — templating
was policed (the reasoning fix list, 2026-09-24), and facts were verified under R11. What
failed is the objective: **compress an RL-trained reasoner by SFT on traces written by a
different model.** SFT can move the model's thinking toward any style; it cannot also keep
the accuracy that the native style's length and self-checking were buying.

It was also an expensive way to fail. By a word-count proxy, **62% of phase 3's loss lands on
trace tokens and 38% on answers**, so most of that phase's gradient taught style rather than
CTL2.

For context on what the model was trained on: as I understand the published Qwen3 recipe —
not confirmed for 3.8 — thinking behaviour comes from long-CoT data followed by reasoning
RL, and the later thinking-mode SFT used **the model's own rejection-sampled outputs**
precisely so that additional SFT would not disturb what RL had installed. Phase 3 did the
opposite. The measurements above stand on their own either way.

#### Consequences

1. **Phase 3 stays out** (§3.12), and so does any further authored-trace work. The
   fix-to-spec brief no longer requires `reasoning_content` (`spec/fix_to_spec_examples_spec.md`,
   commit `92ad814`). The playbook's R7 and its length bands should not be applied to any
   future trace.
2. **Authored `reasoning_content` in the corpus is now inert, not harmful** — phase 1 strips
   it, and it only trains if a reasoning round runs. It does not need removing; it needs
   the pipeline not to consume it. Note that `configs/qwen38.yaml` still defines the
   `post_dpo_sft` phase, so a plain full run would train it again.
3. **If reasoning training comes back, it should be self-distilled, not authored.**
   Generate traces with the SFT+DPO model on the training prompts, keep only those whose
   answer is judged correct against the reference, and train on those. The traces are then
   in the model's own distribution, so the gradient goes to CTL2 rather than to style.
   `spec/self_distillation_spec.md` drafts it.
4. **Shorter thinking is an RL problem, not an SFT one.** If thinking length ever matters for
   cost, a length-penalised RL objective is the tool; imposing it through SFT data costs
   accuracy, as measured here.

**Caveats.** The base sample is 11 tests at one run. The native-vs-phase-3 per-test
comparison uses one n=5 run of each, and §3.12 showed generate at n=5 moves by ~0.007
between repeats, so the tercile deltas are directional rather than precise. The fix and
validate differences are far larger than that spread.

---

### 3.14 The complete model×mode 2×2, and the 0917 baseline correction

Four cells, **n=5 each, same suite (v4, 40 tests), same sampling** (T=0.4 / top_p 0.95 /
top_k 20). The `fix6_sftdpo` thinking-OFF row is the mean of three runs.

| model | thinking | generate | perfect | validate | fix | WRONG | traps | like-for-like |
|---|---|---|---|---|---|---|---|---|
| 0917 | OFF | **0.9832** | 93% | 0.8164 | 0.600 | 15.3% | 17 | 0.9342 |
| 0917 | ON | **0.9853** | 92% | 0.6918 | 0.635 | 20.4% | 14 | — |
| **fix6_sftdpo** | OFF | 0.9800 | 91% | **0.8449** | 0.537 | **4.6%** | 13 | **0.9386** |
| fix6_sftdpo | ON | 0.9804 | 87% | 0.7795 | **0.740** | 14.8% | 13 | 0.9147 |

#### 0917's validate baseline of 0.8034 is not reproducible — use 0.6918 (think) / 0.8164 (no think)

**0.8034 appears throughout the sections above and every use of it is optimistic.** It came
from an n=3 run on the 38-test suite. Re-measured at n=5 on the current suite:

| 0917 run | conditions | validate | CAUGHT | WRONG | traps |
|---|---|---|---|---|---|
| 2026-09-20 | n=3, 38 tests, thinking ON | 0.8034 | 78.7% | 16.0% | **2 / 61** |
| **2026-09-28** | **n=5, 40 tests, thinking ON** | **0.6918** | 72.4% | 20.4% | **14** |
| **2026-09-28** | **n=5, 40 tests, thinking OFF** | **0.8164** | 83.3% | 15.3% | 17 |

The trap count is the tell: 2 of 61 at n=3 against 14 at n=5. Traps are rare events and n=3
systematically under-samples them. **Never compare a validate score measured at n=3 with one
measured at n=5** — §2, §3.5 and §3.7 all do, and overstate the older models accordingly.

Generate reproduced almost exactly across the same gap: **0.9858 (n=3) → 0.9853 (n=5)**, a
spread of 0.0005. So the n-sensitivity is asymmetric: **validate needs the higher n because
it is trap-sensitive; generate is stable**, and only differences under ~0.01 there need a
repeat (§4.5).

#### Thinking off helps validate on BOTH models — §3.12's rule generalises

| | thinking ON | thinking OFF | Δ |
|---|---|---|---|
| 0917 | 0.6918 | **0.8164** | **+0.125** |
| fix6_sftdpo | 0.7795 | **0.8449** | **+0.065** |

§3.12 established this on one model. It now holds on a model trained on a completely
different corpus, with no phase-3 round in either, so it is a property of the **task** and
not of a checkpoint. Note this is the *inference-time* flag, a separate question from
§3.13's finding about authored traces — 0917 never saw a trace at all, and thinking still
costs it 0.125 on validate.

#### What the corpus work actually bought — both models in their best mode

| | 0917 (no think) | fix6_sftdpo (no think) |
|---|---|---|
| generate | **0.9832** | 0.9800 |
| validate | 0.8164 | **0.8449** |
| **WRONG** | 15.3% | **4.6%** |
| MISSED | **1.3%** | 8.6% |
| like-for-like | 0.9342 | **0.9386** |

**Generate is a tie** — 0.003 apart, inside the spread. 0917 does not *lose* any generate
pairing, so the honest statement is that the corpus work drew level on generate rather than
surpassing it. Earlier sections describing a large unexplained generate gap to 0917 were
comparing a phase-3 model against a no-phase-3 one; §3.12 and §3.13 account for most of it.

**The gain is on validate and it is specifically a precision gain.** WRONG falls 15.3% →
4.6%, a third of the rate, while MISSED rises 1.3% → 8.6%. 0917 finds nearly everything and
is wrong about a sixth of what it says; fix6_sftdpo finds less and is wrong far less often.
Under this project's stated preference for precision over recall on validation that is the
better trade — but it **is** a trade, and 0917's recall is the stronger.

**T37 is 1.00 for 0917 too**, at n=5. So T37 was never a capability the new corpus added:
the old corpus had it, and the fix2/fix3 scores were a regression that has since been
recovered rather than a gap that was closed.

---

### 3.15 Reasoning effort barely matters — thinking off still wins validate

Every thinking-ON measurement above ran at `reasoning_effort: medium`, which is also what
training used, so train and eval saw the same system prompt. (At `xhigh` the template
prepends *"Reasoning effort is set to xhigh…"* to the system message; no recorded eval prompt
contains it.) Qwen3.8 accepts `low` / `medium` / `xhigh`, so the two other levels were run on
the same weights, `qwen38_fix6_sftdpo`, n=5: `low` on the full suite, `xhigh` on the fix tests
only because it is slow.

| | thinking OFF (3 runs) | low | medium | xhigh (fix only) |
|---|---|---|---|---|
| generate | 0.9800 | 0.9774 | 0.9804 | — |
| **validate** | **0.8449** | 0.8013 | 0.7795 | — |
| fix | 0.537 | 0.785 | 0.740 | 0.740 |
| validate CAUGHT / MISSED / WRONG | **86.8 / 8.6 / 4.6** | 78.9 / 5.9 / 15.1 | 81.2 / 4.0 / 14.8 | — |
| traps sprung (validate) | 13 | **6** | 13 | — |
| median thinking, gen / val / fix (words) | — | 236 / 210 / 1136 | 268 / 239 / 1484 | — / — / 3253 |
| median validate answer | 65w | 104w | 124w | — |
| median seconds per fix sample | — | — | 160 | 286 |

Configs: `configs/eval_T04_fix6_sftdpo_low.yaml`, `configs/eval_T04_fix6_sftdpo_xhigh.yaml`.
Both use symlinked model paths (`/home/pavlisd/exports/qwen38_fix6_sftdpo_{low,xhigh}`) so
their results files get distinct model names — the §3.12 overwrite cannot recur. Only the
MUT's effort changed; the judge stayed at `medium`.

**The knob is weak on this model.** `medium` → `low` cut thinking only 12–23%; `medium` →
`xhigh` doubled it on fix. Length still scales with difficulty at every level (fix ≈ 5×
validate), so the native adaptivity §3.13 describes survives the knob.

**Validate: `low` is not the middle ground.** The hope was that a shorter native trace would
keep thinking's detection gain without its WRONG cost. It did not: WRONG stayed at 15.1%,
because the over-elaboration lives in the *answer* that thinking produces (104w at `low`, 124w
at `medium`, 65w with thinking off), and `low` barely shortens that. It did halve the traps
sprung, 13 → 6. Validate at `low` is still 0.044 below thinking off. **Thinking stays off for
validate** — and §3.14 showed the same holds on 0917, so this is the task, not the model.

**Fix: effort makes no measurable difference.** `low` 0.785 against `medium` 0.740 is one T40
run flipping from 0.3 to 0.75 — noise at 10 samples. `xhigh` matched `medium` run for run
(scores identical across all 10 runs; the answers are all different texts, and the judge
failed the same items in each). T39 is solved at every level. What remains is **T40.FP1 in 10
of 10 runs at both `medium` and `xhigh`**: the model believes declared-but-unassigned
variables start null, where they start at their type defaults. Twice the thinking reasons
longer from the same false premise. That is a knowledge gap, not missing deliberation — and
it is one of the correct-but-suspicious constructs seeded into the amended fix-to-spec
records (`ctl_lora_training` `83c0136`), which no model has been trained on yet.

**Rule:** thinking off for generate and validate; for fix-to-spec, thinking on at `low` — as
good as `medium` and ~25% less thinking. Never `xhigh`: ~80% more time for nothing measured.

**Implication for §3.13's consequence 4.** If thinking length ever matters for cost, the
built-in `low` setting is the first thing to try before any training-based compression, but
it buys little here. A real reduction would still need RL.

### 3.16 The declaration-default belief: a pretrained prior that training would not move

> **Added 2026-10-09.** Covers rb1006–rb1008, the fixpilot1007 pilot, dpodef1/dpodef2 and the
> system-prompt rule test. Eval snapshot `results/eval_snapshot_20261003`. Judge gpt-6-sol until
> 2026-10-08, local gpt-6.1-sol from 2026-10-09 (§4.6). The belief rates below were re-measured
> under both judges and agree.

**The belief.** In CTL2 a variable declared without an initializer starts at its type default:
- `integer`, `long`, `decimal` 0; `number` 0.0;
- `boolean` false;
- `string` `""`;
- `date` the epoch;
- lists and maps empty;
- only `variant`, `byte` and `cbyte` are null.

The model insists, in its chain of thought, that `date prevShip;` "defaults to null". It then
"fixes" correct code. On the fix benchmarks this is T40.FP1 (`date lastOrderDate;`, a list) and
T42.FP6 (`date prevShip;`). They fired in **20/20** runs, thinking on, for every model from base
to rb1008. The pattern matches Java/C# *field* semantics exactly, where a `Date`, `String` or
`List` field is null and an `int` is 0. Nobody ever trained it on a wrong CTL2 example. It is a
prior carried over from Java and C#, not a knowledge gap.

**What was tried, and what it did to T40/T42 (thinking on, n=20):**

| attempt | data | T40.FP1 / T42.FP6 | side effects |
|---|---|---|---|
| rb1006 | 120 answer-only fix-explained records, the declaration a *silent* trap in 69 | 20/20, 20/20 | none: fix 0.70 → **0.863**, validate WRONG 4.4% |
| rb1007 | + 80 answer-only fix-defaults records that *name* the declaration ("Left unchanged: …") | 20/20, 20/20 | new `roundHalfUp()` hallucination (T43 0.95 → 0.78) |
| rb1008 | + 184 of rb1006's own correct fix *thinking traces* ×2 (incl. 30 repairs), ~10% of tokens | 20/20, 20/20 | **validate OFF WRONG 13–15%** (from 3.5%) |
| dpodef1 | thinking-on DPO on rb1006, 92 pairs: rejected = own belief trace, chosen = minimal gpt-6-sol repair | not run: check set 22% → 21% | — |
| dpodef2a | context-distillation DPO, 48 own-voice pairs, lr 5e-6, 2 epochs | not run: check set 22% → 23.5% | — |
| dpodef2b | same 48 pairs, lr 2e-5, 3 epochs | **19/20, 20/20** (check set 22% → **7%**) | **validate OFF WRONG 3.2% → 11.1%** |
| **rule in the system prompt** (no training) | rb1006 + the rule in the fix system prompt | **0/20, 0/20**; T42 PASS 20/20 | being measured on the full suite |

The **check set** is 50 held-out prompts with tempting declarations, 4 samples each, run through
the full self-distill filter. Belief = the belief scan or a judge false-claim about a declaration
default (`data/self_distill/dpodef2/probe_compare2.py`).

**Findings:**
1. **Answer-only data does not reach the thinking.** rb1006 states the belief in 48% of its
   thinking on the very fix-defaults prompts it was trained on, whose reference answers say the
   opposite (pilot fixpilot1007).
2. **Correct thinking traces did not either, and cost validate.** rb1008's 184 traces were about
   10% of training tokens, several per prompt on the defaults set. The belief stayed. Thinking-off
   validate WRONG tripled: the errors were real content errors, at unchanged answer length.
3. **Offline DPO on repaired traces learns the pairs, not the behaviour.** dpodef1 reached 100%
   pair accuracy, but the repaired "chosen" texts were far less likely under the model (logp −560
   vs −95). The belief fell only 71% → 65% on the training prompts themselves.
4. **The model applies the rule perfectly when it is stated.** That makes context distillation
   possible: rb1006 sampled *with* the rule had 5.3% belief on the 71 prompts where it otherwise
   had 71.5%. dpodef2 trained on those own-voice answers under the plain prompt.
5. **Moving the belief by DPO needs a strong update, and the strong update does damage.** At lr
   5e-6 dpodef2 did nothing. At 2e-5 it cut the check set to 7%, but almost entirely on the easier
   prompts: fix-explained 12/60 → 0/60, validate 7/32 → 1/32, while fix-defaults only halved
   (24 → 12 of 60). The benchmark cases did not move. On T42 its thinking still says "`prevShip` is
   initialized to null (default for `date`)". Thinking-off validate WRONG rose 3.2% → 11.1%, the
   same pattern as rb1008.
6. **The hard case is a declared date compared on the first record next to real nullable fields.**
   The model reasons about nulls correctly for the real fields and then extends the same treatment
   to the declaration. Every method that worked on easier prompts failed there.

**Practical rule, until a training method passes T40/T42 without side effects:** state the
declaration rule in the system prompt. Configs:
- `configs/eval_rb1006_rule_on.yaml`: the rule in the fix prompt;
- `configs/eval_rb1006_ruleall_{on,off}.yaml`: the rule and a Java/C# contrast in all prompts.

The full-suite check of the latter was queued on 2026-10-09.

**Data produced along the way, still useful:**
- `CTL_LoRA_fix_defaults_explained.json` (80);
- `CTL_LoRA_declaration_defaults_contrast.json` (55; CTL2 against Java/C#/JS/Python);
- the declaration-defaults audit of the corpus (24 records corrected);
- about 1,000 rule-prompted rb1006 samples (runs `dpodef2`, `dpodef3*`);
- the plain belief samples (`dpodef1`, `dpodef1x`, `dpodef3a_plain`, `dpodef3b_plain`).

The last two are the material for on-policy context distillation or GRPO.

### 3.17 What the literature says about overriding a pretrained prior

> **Added 2026-10-09** from a literature scan. Citations were checked for existence. Details
> marked *(secondary)* were read in summaries, not the paper.

**The failure mode is documented.**
- **Sliding back to familiar semantics.** Wu et al. 2024, *Reasoning or Reciting?*
  ([2307.02477](https://arxiv.org/abs/2307.02477)): "Python with 1-based indexing", stated in the
  prompt, keeps sliding back to normal Python. Miceli-Barone et al. 2023
  ([2305.15507](https://arxiv.org/abs/2305.15507)): with swapped built-ins, larger models fail more.
- **Java and C# specifically.** Moumoula et al. 2025
  ([2503.13620](https://arxiv.org/abs/2503.13620)): models drift systematically between similar
  languages, Java ↔ C# explicitly.
- **Old habits over documented changes.** Wang et al. 2024
  ([2406.09834](https://arxiv.org/abs/2406.09834)): deprecated APIs appear in 25–38% of
  completions. CodeUpdateArena ([2407.06249](https://arxiv.org/abs/2407.06249)) and ReCode
  ([2506.20495](https://arxiv.org/abs/2506.20495)): updated docs in the prompt do not reliably help
  open code models.
- **Why fine-tuning struggles.** Gekhman et al. 2024
  ([2405.05904](https://arxiv.org/abs/2405.05904)): fine-tuning learns facts that contradict the
  model's knowledge slowly and generalises them poorly.

**Why our attempts behaved as they did.**
- **Thinking-trace SFT (§3.16 finding 2).** Long-CoT SFT learns the *structure* of traces more
  than their content. Training on traces with wrong answers cost only 3.2% (Li et al. 2025,
  [2502.07374](https://arxiv.org/abs/2502.07374)).
- **Offline DPO (finding 3).** It makes a policy good at classifying pairs without improving what
  it generates (Tang et al. 2024, [2405.08448](https://arxiv.org/abs/2405.08448)). An NLL term on
  the chosen answer is reported as crucial for reasoning (Pang et al. 2024, IRPO,
  [2404.19733](https://arxiv.org/abs/2404.19733)).
- **The side effects (finding 5).** Forgetting tracks the KL divergence from the base model
  (Shenfeld et al., RL's Razor, [2509.04259](https://arxiv.org/abs/2509.04259)). A strong
  off-policy update drifts far.
- **Knowledge editing** (ROME/MEMIT/AlphaEdit). Edits do not carry over to the facts they imply,
  and an in-context baseline beat them (RippleEdits, [2307.12976](https://arxiv.org/abs/2307.12976)).
  Edited facts are not used inside the chain of thought (ReCoE,
  [2401.17585](https://arxiv.org/abs/2401.17585); CRANE,
  [2606.09033](https://arxiv.org/abs/2606.09033): edits pass under teacher forcing but drop to as
  low as 0% once the reasoning chain is checked). **Unlearning** is undone by about 10 unrelated
  fine-tuning examples ([2409.18025](https://arxiv.org/abs/2409.18025)). Neither fits.

**What has tested support, ranked for this case:**
1. **The rule in context.** It beat weight updates in several controlled comparisons (RippleEdits;
   Ovadia et al. 2024, [2312.05934](https://arxiv.org/abs/2312.05934)). Confirmed here: 0/20.
2. **On-policy context distillation.**
   - **Method:** the student, without the rule, samples its own answers. The same model *with* the
     rule supplies per-token targets, iterated over a few rounds.
   - **Evidence:** Askell et al. 2021 ([2112.00861](https://arxiv.org/abs/2112.00861)); Snell et
     al. 2022 ([2209.15189](https://arxiv.org/abs/2209.15189)); Padmanabhan et al. 2023
     ([2306.09306](https://arxiv.org/abs/2306.09306)), where updates propagated to inferences
     better than fine-tuning or editors, with little damage; SDFT, Shenfeld et al. 2026
     ([2601.19897](https://arxiv.org/abs/2601.19897)), which beat SFT and reduced forgetting
     (reverse-KL loss *(secondary)*); the Thinking Machines blog "On-Policy Distillation".
   - **Relation to our work:** dpodef2 was an offline, whole-sequence approximation of this.
   - **Spec:** `spec/onpolicy_context_distillation_spec.md`.
3. **RL with a checkable reward.**
   - **ReCode:** GRPO on about 2k API-migration examples generalised to unseen tasks and hurt
     general coding less than SFT.
   - **SFT vs RL:** SFT memorises, RL generalises (Chu et al. 2025,
     [2501.17161](https://arxiv.org/abs/2501.17161)).
   - **What RL can amplify:** it only reweights behaviour already present (Yue et al. 2025,
     [2504.13837](https://arxiv.org/abs/2504.13837)). That is fine here, since most samples are
     already correct.
   - **Status:** `spec/grpo_rl_idea.md`, parked.
4. **Train the consequences, not just the rule.** Paraphrase the rule many ways and spell out its
   implications: `== null` on a declared date is always false; `isnull()` there is dead code; "not
   a bug" in reviews.
   - Without paraphrase augmentation, stored facts were extracted at about 0% (Allen-Zhu & Li,
     [2309.14316](https://arxiv.org/abs/2309.14316)).
   - Fine-tuning on the model's own in-context inferences closes the gap to in-context learning
     (Lampinen et al. 2025, [2505.00661](https://arxiv.org/abs/2505.00661)).
   - Synthetic continued pretraining scales log-linearly (EntiGraph,
     [2409.07431](https://arxiv.org/abs/2409.07431)).
   - Training "A is B" does not teach "B is A" (reversal curse,
     [2309.12288](https://arxiv.org/abs/2309.12288)).
5. **Regression control.** Mix in about 30% replay of general and own-task data. Then run a short
   on-policy distillation pass toward the *original* model on unrelated prompts. In the Thinking
   Machines experiment this recovered instruction-following, 79% → 83%.
6. **LoRA.** It learns less and forgets less than full fine-tuning (Biderman et al. 2024,
   [2405.09673](https://arxiv.org/abs/2405.09673)). Target all linear layers including MLP, which
   we already do. Whether this matters for overriding a belief is untested.

**Gap:** no published study corrects a misconception inside text-only long chain-of-thought. The
nearest evidence (CRANE, multimodal) says reasoning chains resist weight edits, consistent with
§3.16.

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

### 4.3 Count WRONG findings on validate tests only

`judge_result.findings[].status` uses the same vocabulary (`CAUGHT` / `MISSED` /
`MISSING` / `WRONG`) for both test types, but on a **generate** test a WRONG finding
describes a defect in the CTL the model wrote — a code-quality signal, not a
review-precision one. Pooling the two inflates the rate and changes conclusions:

| | validate only | generate + validate pooled |
|---|---|---|
| fix1 WRONG rate | **6.5%** | 12.8% |
| fix2 WRONG rate | **10.8%** | 20.2% |

The validate-only figure is the one that reproduces the 6% historically quoted for
fix1. A first pass at the fix2 comparison used the pooled number and concluded fix2
had roughly doubled its wrong findings; on the correct metric the increase is 4.3
points and is explained by §3.8.

### 4.4 `load_best_model_at_end` was picking checkpoints at random — now disabled

The SFT eval_loss curve is flat across the back half of training, so "best checkpoint"
was decided by noise, and the SFT dose reaching DPO swung by 2× between otherwise
identical runs:

| run | SFT checkpoint | through training | best eval_loss |
|---|---|---|---|
| fix1 | 1750 / 1924 | 91% | 0.13478 |
| fix2 | 1800 / 1940 | 93% | 0.13638 |
| fix3 | 1950 / 1962 | 99% | 0.13906 |
| **fix4** | **950 / 1968** | **48%** | 0.13931 |

In the fix4 run **16 of 39 evaluated checkpoints were within 0.002 eval_loss of the
best**, and step 950 beat step 1000 by **0.00004**. fix4 then posted the worst validate
score measured (0.5538 against fix2's 0.8462) — a confound larger than most of the
effects this project has been chasing, and one that silently contaminated every
cross-run comparison before it.

**The eval sets are also mismatched to what the phases teach**, so eval_loss is the
wrong signal twice over:

| | train validate share | eval validate share |
|---|---|---|
| phase 1 | 12.6% | 3.9% |
| **phase 3** | **41.8%** | **5.0%** |

Phase 3 trains 42% validate content and is evaluated on three validate records, two of
them single-finding; of the 47 multi-defect reviews in phase-3 training the eval set
contains one. Eval answers are also shorter than training answers (35w vs 51w in phase
1, 38w vs 62w in phase 3), which pushes loss toward saturation and flattens the curve.

The eval sets are otherwise **clean**: no duplicate prompts, no overlap with the judged
suite, no missing `//#CTL2` headers, and no invalid CTL2 (a library scan flagged 20
records, all false positives — `lookup()`/`sequence()` are syntax constructs, `freq()` is
a helper the prompt asks the model to define, and `toDecimal()` appears in a validate
record that correctly flags it as not existing).

**Confirmed by direct test (§3.9).** fix5 re-exported the *same* SFT run at
checkpoint-1950 instead of 950: validate went 0.5538 → 0.8064, CAUGHT 48.6% → 79.2%,
median validate answer 46w → 60w. The checkpoint accident was the whole of fix4's
collapse.

> **Caveat on the fix5 run itself:** it started before the config change landed, so its
> DPO and postSFT phases still logged `Loading best model` and selected 450/472 and
> 250/264. Both are ≥95% through, so the result is clean — but `load_best_model_at_end:
> false` has not yet actually been exercised end to end. The next full run is the first.

`load_best_model_at_end: false` on all three phases as of 2026-09-26. train.py's
`find_best_checkpoint()` then falls through to the last checkpoint: deterministic and
full-dose. **Set the dose with `num_train_epochs`, or export a specific checkpoint by
hand — never by letting eval_loss choose.** Note this locks phase 3 at its heaviest dose
(3 epochs), which is a real choice rather than a safe default: §3.6 and the fix3
checkpoint tests found a lighter phase-3 dose much better on T37 (ckpt-100 0.97 vs
ckpt-250 0.57).

### 4.5 Noise floor

> **Added 2026-09-28, revised with §3.14.** Two effects, in opposite directions:
>
> *Within one model at fixed n*, generate is the noisier metric: two n=5 runs of
> `fix6_sftdpo` gave 0.9848 and 0.9781 (spread 0.0067) while validate reproduced to 0.002.
> Differences under ~0.01 on generate need a second run.
>
> *Across different n*, **validate is the fragile one.** 0917 measured 0.8034 at n=3 and
> 0.6918 at n=5 on the same mode, because false-positive traps are rare events that n=3
> under-samples — 2 of 61 against 14. Generate over the same gap moved 0.9858 → 0.9853.
> **Never compare validate scores measured at different n.**

Suite sd is 0.004–0.017 at T=0.4 — much tighter than the 0.054 seen under the old configs,
but that improvement came from removing the penalties, not from temperature. Differences
below ~0.02 at suite level are not interpretable at n=3.

Per-test instability is mostly **genuine model uncertainty, not sampling noise**: tests like
T22 and T30 sit near 0.5 with sd ~0.47 at every temperature. More runs is the only remedy.

The judge is **not** a source of noise: 19 byte-identical MUT responses were scored
identically, 19/19. An earlier claim that the judge enumerated findings inconsistently was
based on a `difflib.quick_ratio` screen, which is an upper bound — two responses 98% similar
differed in exactly the token under test.

### 4.6 Judge history — compare only under one judge

| period | judge |
|---|---|
| until 2026-09-29 | gpt-5.6-terra (the tables in §1–§3.15) |
| 2026-09-30 – 2026-10-08 | gpt-6-sol / medium, OpenAI API |
| **from 2026-10-09** | **gpt-6.1-sol / medium, local OpenAI-compatible provider** (`base_url: http://127.0.0.1:9001/v1`, `api_key: local`; commit `f80edcf`) |

On the local provider, the model name `gpt-6` is actually served by **gpt-5.5**. `gpt-6.1-sol`
is served as itself, and unknown names are rejected.

**gpt-6-sol and gpt-6.1-sol agree on the belief rate,** checked on the same 200 stored check-set
samples: rb1006 22.0% vs 22.0%, dpodef1 21.0% vs 21.5%. gpt-6.1-sol accepts slightly fewer
answers (27.5% vs 30.0%) and flags more real-null overshoot (3 vs 1).

**On suite scores the new judge is stricter on fix.** Same stored rb1006 answers:

| | gpt-6-sol | gpt-6.1-sol |
|---|---|---|
| fix, thinking on, n=20 | 0.863 | **0.801** |
| validate, thinking off, 3 runs | 0.885–0.926 | 0.871 / 0.901 / 0.914 |
| generate, thinking off | 0.983 | 0.975 |
| generate, thinking on | — | 0.972 |

Re-judge stored answers before comparing across the switch: `data/rejudge_results.py` for suite results, or the self-distill
`filter` on copied samples. rb1006's suite results were re-judged as `*_rj61.json`.

The code defaults (`self_distill.JUDGE_DEFAULTS`, `test.py`, `review_judge.py`) still name
`gpt-6-sol`. They are only fallbacks; every config sets the judge.

The ctl_validate compile check needs the local CloverDX Server (`~/cloverserver/…/bin/startup.sh`,
port 8083). It does not restart after a reboot, and the self-distill filter then logs "exit 0"
without judging anything, so check the judged count.

---

## 5. Recommended pipeline

`configs/qwen38.yaml` encodes this. One invocation:

```bash
source ~/venv/bin/activate        # llamafactory-cli must be on PATH
python train.py configs/qwen38.yaml
```

**Phase 1 — SFT, no thinking.** `dataset: clover_ctl_trainign_data` — **one dataset, not
both.** `enable_thinking: false`, cutoff_len 3200, lr 5e-5, 2 epochs, bs 2 × accum 6,
rank 64 / alpha 64 / loraplus 2.

> Naming `clover_ctl_think_data` here as well — as this section said until 2026-09-24 —
> trains every reasoning answer twice in phase 1. That dataset is a strict subset: since the
> 2026-09-21 rebuild `clover_ctl_trainign_data` already holds every reasoning prompt with its
> `<think>` block stripped, verified each run by the pre-flight (§5.1). §3.1's finding still
> holds — those records must be in phase 1 — but they get there through the one dataset now.

**Phase 2 — DPO, no thinking.** `enable_thinking: false` (pairs carry no `<think>`), lr 5e-6,
1 epoch, bs 1 × accum 4, pref_beta 0.1 / pref_ftx 0.1. Runs **between** the SFT phases: its
pairs contain no reasoning, so it belongs while the model is still a non-thinking model.

**Phase 3 — SFT on reasoning, thinking on.** `dataset: clover_ctl_think_data`,
`enable_thinking: true`, lr 1e-5, rank 32, 3 epochs, bs 2 × accum 6 — **effective batch 12
on one GPU**, the same as phases 1 and 2.

> An earlier revision of this line said to keep phase 3 at ≥24 samples/step and to double
> `gradient_accumulation_steps` on a single GPU. **Do not.** That came from the p1fix /
> sftdpo / ckpt100 experiments, which ran at 24/step; every model since — 0917, fix1, fix2,
> the best three measured — ran at 12/step on one GPU. Doubling accum also halves the step
> count, which changes the phase-3 dose, a variable §3.6 closed. With `world_size=1` the
> effective batch is just `per_device × accum`, so `configs/qwen38.yaml` needs no edit to
> run on one GPU.

> **Do not skip phase 3 and then evaluate in thinking mode.** It is the only phase that
> trains the model to emit `</think>`; without it 12% of runs answer inside the thinking
> channel and score 0 (§3.4). `--skip-post-sft` is for experiments that will be evaluated
> with `enable_thinking: false`.

**Evaluate** with `configs/eval_T04_*.yaml` at `--runs 3` minimum.

### 5.1 Corpus pre-flight — run before every training run

Two hours of GPU time is worth two minutes of checking. This caught 35 conflicting-answer
prompts on 2026-09-24, the same class of defect that cost 0.027 suite in §2 at 115 prompts.

```python
import json, collections, re, os
D = os.path.expanduser('~/LlamaFactory/data')
THINK = re.compile(r'^<think>\n.*?\n</think>\n\n', re.S)
user = lambda e: next(m['content'] for m in e['messages'] if m['role']=='user').strip()
raw  = lambda e: ''.join(m.get('content','') for m in e['messages'] if m['role']=='assistant')
bare = lambda e: THINK.sub('', raw(e)).strip()

T  = json.load(open(f'{D}/CTL_LoRA_training_data.json'))
TH = json.load(open(f'{D}/CTL_LoRA_training_data_think.json'))
E  = json.load(open(f'{D}/CTL_LoRA_eval_data.json'))
EH = json.load(open(f'{D}/CTL_LoRA_eval_data_think.json'))
print('phase-1', len(T), ' think', len(TH))

tu = collections.defaultdict(list)
for e in T: tu[user(e)].append(bare(e))
thg = collections.defaultdict(list)
for e in TH: thg[user(e)].append(bare(e))

print('phase-1 prompts with conflicting answers (want 0):',
      sum(1 for a in tu.values() if len(set(a)) > 1))
print('duplicate prompts  phase-1/think (want 0/0):',
      sum(1 for a in tu.values() if len(a) > 1), '/', sum(1 for a in thg.values() if len(a) > 1))
print('think prompts absent from phase 1 (want 0):', sum(1 for p in thg if p not in tu))
print('think answers not matching phase 1 (want 0):',
      sum(1 for e in TH if user(e) in tu and bare(e) not in tu[user(e)]))
for nm, ev, tr in [('phase-1', E, T), ('think', EH, TH)]:
    trp = {user(e) for e in tr}
    print(f'eval contamination {nm} (want 0):', sum(1 for e in ev if user(e) in trp))
print('bad thought-word spelling (want 0):',
      sum(1 for e in TH if not ('<think>\n' in raw(e) and '\n</think>\n\n' in raw(e))))
print('unmerged reasoning_content (want 0):',
      sum(1 for e in TH for m in e['messages'] if 'reasoning_content' in m))
print('phase-1 records carrying <think> (want 0):', sum(1 for e in T if '<think>' in raw(e)))
```

**Compare answers with the `<think>` block stripped.** `CTL_LoRA_training_data_think.json` is
the post-`convert_think.py` file, so its `content` still carries the tags; comparing raw
against phase 1 reports all ~1000 records as mismatched when nothing is wrong.

### Operational notes

- **Preserve exports before retraining.** `export_dir` is fixed and each run overwrites the
  last. Two models were lost this way, one of them the then-best. Rename first.
- **One GPU needs no config change.** With `world_size=1` the effective batch is
  `per_device × accum`, which `configs/qwen38.yaml` already sets to 12/12/4 for the three
  phases — what 0917, fix1 and fix2 all used. Do not "correct" it upward.
- `reasoning_effort: medium` must match between the training and eval configs.
- `test.py` needs `OPENAI_API_KEY` from `~/.bash_profile` — login-shell only. Source it
  explicitly in non-interactive shells or every judge call 401s.
- `llamafactory-cli` lives in `~/venv/bin` and is **not** on the default PATH; `train.py`
  invokes it by bare name, so export the path first or the SFT phase dies instantly with
  `FileNotFoundError`.

---

## 6. Open questions, in priority order

> **2026-10-09 — current front (§3.16, §3.17).** Items below predate it.
>
> A. **Does the system-prompt rule cost anything elsewhere?** It is queued as a full suite (rule
>    in all prompts, both modes). If clean, it is the deployable fix for the declaration belief.
>
> B. **On-policy context distillation** (`spec/onpolicy_context_distillation_spec.md`): the
>    method with the best tested record for moving a prior with little forgetting. Gate it on
>    T40/T42 *and* thinking-off validate WRONG, not on the easy check-set prompts.
>
> C. **GRPO with a belief-aware reward** (`spec/grpo_rl_idea.md`), if B fails on T40/T42.
>
> D. **Why does thinking-mode training raise thinking-off validate WRONG?** Seen in rb1008 and
>    dpodef2b. Any method that changes thinking needs replay data and a thinking-off validate gate.

0. **Retrain without phase 3 (§3.12, §3.13).** The 2x2 was run by dropping the phase-3
   adapter from an existing chain, which is not the same as training without it:
   phase 1 and DPO were unchanged, so this shows phase 3 subtracts, not that a
   two-phase pipeline is optimal. Confirm with a run configured as SFT+DPO only —
   `configs/qwen38.yaml` still defines `post_dpo_sft`, so this needs a config change,
   not just a flag at eval time. The same run is the first to train the amended
   fix-to-spec answers (item 1).
1. **Fix-to-spec records — amended, not yet trained (§3.10, §3.11).** The 24 records
   now carry already-correct affirmations and minimal-repair corrections
   (`ctl_lora_training` commit `83c0136`); no model has been trained on them yet.
   Reasoning was withdrawn from that brief (§3.13), so they matter through their
   answers in phase 1 only. Measure on T39/T40 after item 0.
1a. **Self-distilled reasoning, if reasoning training is wanted at all (§3.13).**
   Thinking helps fix-to-spec (+0.21) even untrained. Whether training the think
   channel on the model's *own* correct traces helps further is untested;
   `spec/self_distillation_spec.md` drafts the experiment. Do it after item 0, so
   there is a clean two-phase baseline to compare against.
2. **Per-finding explanation budget — the lever that replaced phase-3 dose.**
   The corpus teaches 19 words per issue line and shrinks to 17.4 on 5-bug
   records, below the ~25 threshold where factual errors start (§3.8). It has
   1 reasoning record with ≥5 findings. Every future recall improvement will
   keep converting into WRONG findings until this is fixed.
   `spec/explanation_budget_spec.md` drafts the amendment.
2. **Severity under-escalation — half of Group A did not land.** fix2 fixed
   over-escalation (T24: 3 WRONG → 0) but not the other direction: T16
   (unreachable code) and T18 (null dereference) still mark certain
   compile/runtime failures WARNING (§3.7). The ~25 ERROR-side records were
   written but had no measurable effect — diagnose why before writing more of
   them. Candidate explanation: those records are single-finding and short,
   so they teach the label without the reasoning that justifies it.
3. ~~**Phase-3 dose.**~~ **Closed twice (§3.6, §3.9).** The dose controls length,
   not quality. §3.9 adds the interaction: a light phase 3 helps only when the SFT
   adapter is under-trained, and at full SFT dose it reintroduces the `</think>`
   format failure (3/200) and compresses fix explanations below the 25-word
   threshold. **Leave phase 3 at full dose**; the one thing it still buys is T37
   (1.00 vs 0.84), which is better addressed in the corpus.
   Untested middle ground: ckpt-150/175, already on disk.
4. ~~**Severity calibration (over-escalation).**~~ **Closed (§3.7).** T24 went
   3 WRONG → 0 after the Group A WARNING-side records.
3. ~~**What in the new corpus costs 0.03?**~~ **Answered (§3.5):** 115 prompts
   training two conflicting answers. Kept here for the trail:
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
