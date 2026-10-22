# CTL2 fine-tuning — findings and recommended pipeline

Qwen3.8-27B + LoRA on the CTL2 test suite (`ctl2_test_suite_v4.json`). Sampling is the same
everywhere: T=0.4, top_p 0.95, top_k 20, no presence or repetition penalty (§4.2). Suite, judge and
sample counts changed over time, so check which era a number comes from:

| sections | suite | judge | samples |
|---|---|---|---|
| §1–§3.15 | 38 tests (v4); 40 from `fix3` on (T39/T40, the `fix` type) | gpt-5.6-terra | mean of 3 runs |
| §3.18 (09-29 – 10-05) | 43 tests (5 fix tests: T39–T43), frozen snapshots `results/eval_snapshot_20261001` / `_20261003` | gpt-6-sol | n=5 per test; fix n=20 |
| §3.16, §3.19 (from 10-06) | snapshot `_20261003` | gpt-6-sol, then gpt-6.1-sol from 10-09 (§4.6) | n=5; fix and T40/T42 n=20; thinking-off validate 9 reps from §4.7 |
| §3.22 (10-15) | as §3.21, plus suite v5 T53/T54 n10 and the c11 holdouts (20 DI/SCD-2 prompts × 4, judged against the verified answer) | gpt-6.1-sol | as §3.21 |
| §3.21 (10-14) | suite v5 gap tests T44 T46 T57 T60–T63 T67 T73 n10 + 12 held-out gap prompts; the c4 gates as in §3.19 | gpt-6.1-sol | n=10 (gap tests), n=4–14 (holdout), gates as §4.7 |
| §3.20 (10-13) | suite v5 = v4 + 30 real-world generate tests T44–T73, scored apart as `generate_rw`; snapshot `_20261013` | gpt-6.1-sol | n=5 on all 30, then n=10 more on 21 discriminating tests (n=15 pooled) |

**The current recipe is in §5:** rb1006 plus OPCD c4 (owner decision 2026-10-13). The three-phase pipeline that sections §1–§3.15
optimise is retired.

Last updated 2026-10-22 (evening) with compile-and-retry and the causes of non-compiling code (§3.29):
- **Thinking on plus a run-and-retry loop:** c13c's gap-test pass rate goes from 0.78 to 0.93. Thinking off: 0.44 → 0.51.
- **89% of compile failures fall into 11 causes**, each compiler-confirmed. Examples: DataIntersection `$out.1`, invented
  fields and functions, `!~`, time-unit names as variables, `str2date` argument order, `ALL` in a ternary.
- **A missing Rollup lifecycle function fails the component at initialization** (live runs).

Earlier the same day, execution-based scoring and OPCD c14 (§3.28):
- **Execution scoring** of the suite-v5 gap tests: the code is run on the server and every output row checked. Pass rates
  are far below judge scores (c13c 0.44 off / 0.78 on vs judge 0.77 / 0.92). 151 answers scored 0.9 or higher by the
  judge fail to run correctly. c13c is the best model by this measure too.
- **c14** (Rollup accumulator set; rulev7 thinking on, plain anchor thinking off) cuts wrong accumulator explanations
  (hard set 3 nullable 14 → 9/40) but not the T41/T22 scores. T22 thinking on drops to 0.30. **c13c stays the candidate.**
- The accumulator metadata default applies to non-nullable fields only (§7, corrected 2026-10-22); T18 accepts any
  explicit lookup-miss handling (§7, 2026-10-21).

Earlier, 2026-10-20/21, rebuild variance, rb1011 and Stage 3 on rb1011 (§3.27):
- **s3b-rb1011 (Stage 3 on rb1011) is not shown better than c13c** (review correction, 2026-10-21). It wins on T42 and
  thinking-off validate; it loses on T54 (`$out.1` in 10/10 thinking-off answers), T40 compile errors and the thinking-on
  gap tests. The rest is noise. The n20 confirmations settle it: **c13c stays the ship candidate** (T54 off 0.98 vs 0.60,
  T40 2/45 vs 10/45 below full, T43 0.87 vs 0.68).
- The belief fix overgeneralizes to Rollup accumulators ("nullable starts at zero"); that is the T41/T22 drop.
- T18 rubric: any explicit lookup-miss handling counts (owner ruling); all stored T18 answers re-judged.
- A seed rerun of rb1009 shows rebuild variance of about ±0.06–0.07 on validate and the gap tests; rb1009's
  DataIntersection result was a lucky seed. The belief-trace effect is far beyond that variance.

Earlier, 2026-10-18 (evening), belief durability Part B (§3.26):
- 230 of c13c's own belief-free answers in the SFT (rb1010a) remove most of the declaration belief from the base:
  T40 0/20, T42 8/20, hard sets 1/38/4%, with no thinking-off validate damage.
- DataIntersection regressed in both arms, so rebuild-to-rebuild variance is now being measured (rb1009 rerun).

Earlier the same day, c13d and the T41/T60 diagnosis (§3.25):
- c13d ≈ c13c; OPCD does not close T41 (0.815 → 0.840).
- T41 and T60 go to a corpus brief for the next rebuild.

Earlier, 2026-10-17 (evening), OPCD c13c (§3.25):
- A rulev6 teacher fixes T42: T40 + T42 at c10's level (8/40), no belief claims on any hard set.
- Best generate and thinking-on validate so far.
- c13c is the recommended ship candidate. Weak spots: T41's accumulator explanation, T60 thinking off.

Earlier the same day, OPCD c13/c13b on rb1009 (§3.25):
- Best generate so far: gap tests 0.726 off / 0.894 on, T53 1.00 in both modes, G4 0.623.
- c13b fixed T40, but T42 (previous-record date) still triggers in 16/20 samples, so fix thinking on is 0.814 against
  c10's 0.924.
- The rulev3 teacher itself fails T42 in 10/20.

Earlier, 2026-10-16, rb1009 (§3.24): the base rebuild with the DataIntersection and SCD-2 SFT/DPO sets.
- T53 thinking off goes 0.38 → 1.00 (no `$out.1`/`$out.2`).
- Thinking on is about half fixed.
- The rest is at rb1006 level, with the declaration belief back at base level until OPCD (c13) re-applies c4/c10.

Earlier, 2026-10-15 (evening), OPCD c12 (§3.23):
- On the revised, unhinted DataIntersection prompts the guide teacher scores 0.88–0.90 and c10 0.16–0.23.
- Distilling it (c12, 20 rounds) still did not teach the `$out.0` rule: held-out DI 0.19 → 0.16 off, `$out.1`/`$out.2`
  in 27 of 28 answers.
- Hard set 2 regressed (3 → 13 of 60).
- Next is the base rebuild with the new DI and SCD-2 SFT/DPO sets.

Earlier the same day, OPCD c10 and c11 (§3.22):
- **c10** (c9 without training on truncated thinking-on samples) is the best model so far: thinking-off gap gains kept,
  thinking-on gap tests 0.852, fix 0.924.
- **c11** added DataIntersection and SCD-2 prompt groups from the owner's SFT sets. It improved same-set holdouts but
  regressed the independent suite tests (T53 off 0.48 → 0.14, T60 off 0.71 → 0.42, T61 on 0.80 → 0.48). The
  DataIntersection prompts all hinted the `$out.0` answer, and that set has since been revised.

Earlier update, 2026-10-14, with OPCD c9 (§3.21: a teacher with the CloverDX component guide in its prompt, on new generate
prompts for four of the shared gaps; thinking-off suite v5 gap tests 0.574 → 0.691 and every c4 gate passes, but
thinking-on SCD answers regress −0.19 — longer thinking that hits the token limit, and weaker completed answers).

Earlier update, 2026-10-13, with suite v5 (§3.20: 30 real-world generate tests, every reference run in a real graph; rb1006, c4
and c7 tie on them within ±0.025 at n=15; shared weak spots are DataIntersection, dictionary state, Rollup per-record
emit and multi-check validation without thinking), the corrected DataIntersection contract and run-verified runtime facts
(§7, `ctl2-basics.md` §8.9 and §13.3), and the decision to keep c4.

Earlier update, 2026-10-12, with on-policy context distillation, runs c1–c8 (§3.19: the declaration belief is
removed, T40 0/20 and T42 about 4–6/20; c4 is the best balance; accumulator training helps thinking-on
answers and hurts thinking-off T22), and evaluation on vLLM with a corrected noise floor (§4.7: a full
suite in 9 min; rb1006 thinking-off validate WRONG is 7.5% ± 1.3%, not 4.5%).

Earlier update, 2026-10-09, with the declaration-default belief work (§3.16: answer-only data,
thinking traces and offline DPO did not move it on T40/T42; the rule in the system prompt does,
0/20) and the literature on overriding pretrained priors (§3.17). The judge is now local
gpt-6.1-sol (§4.6). Sections §1–§3.15 were measured with gpt-5.6-terra. The 2026-09-29 to 2026-10-05
work (self-distillation, DPO rounds, rb1003–rb1005) is in §3.18, added 2026-10-12, and the owner
rulings on CTL2 semantics are in §7.

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
| **rule in the system prompt** (no training) | rb1006 + the rule in the fix system prompt | **0/20, 0/20**; T42 PASS 20/20 | thinking on: none; **thinking off: validate 0.895 → 0.75–0.79** (see below) |

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

**Result of the full-suite check (2026-10-09), and why the rule cannot simply be shipped:**
- **Thinking on, the rule works:** T40/T42 false fix 0/20, fix 0.892 against 0.801, generate 0.980,
  validate 0.767 against 0.791 (within noise).
- **Thinking off, any rule text in the system prompt primes the reviewer:**

  | validate, thinking off | rb1006 | + rule v1 | + rule v2 | + 3-line accumulator note |
  |---|---|---|---|---|
  | score | 0.895 | 0.753 | 0.788 | 0.709 |
  | MISSED | 2.8% | 9.2% | 10.3% | 13.9% |

  The model focuses on declarations and nulls and misses unrelated bugs. T14 answers "ISSUES: none" and
  misses the wrong Partition entry point (1.00 → 0.40). This rules out a prompt-based teacher for
  thinking-off samples in §3.19.
- **Rule v1 also over-applied** "declared → never null" to Rollup accumulator fields (T22). v2 adds the
  scope: declared variables only, record fields follow metadata. v3 adds "metadata fields are nullable
  unless marked `nullable="false"`".

(The 4.5% WRONG baseline used in this section and in §3.19 until 2026-10-11 came from 3 HF reps and
was low; see §4.7.)

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

### 3.18 2026-09-29 – 10-05: self-distillation, two DPO rounds, and the recipe retrains (rb1003–rb1005)

> **Added 2026-10-12** from the run notes. Chronologically this sits between §3.15 and §3.16.
> Judge gpt-6-sol unless stated. Snapshots `results/eval_snapshot_20261001` and `_20261003`.
> The base is `qwen38_fix6_sftdpo` (fix6 without phase 3, §3.12).

#### Self-distillation (sd1): own traces as the thinking data, a small fix gain

Pipeline: `self_distill.py` (`spec/self_distillation_spec.md`). It runs select → sample (k=4) → filter
→ assemble. The filter has five steps:
- format;
- library (unknown functions);
- compile through the CloverDX MCP;
- the reference judge;
- a second **claims pass** that audits the trace and the answer for uncorrected false CTL2 claims.

**Pilots:**
- Validate prompts without an output layout answered in prose (43/60). They now get
  `VALIDATE_FORMAT_INSTRUCTION`.
- The claims pass removed 21 of 111 judge-accepted samples.
- Acceptance by group:
  - fix-to-spec 18/28;
  - fix_this_code 5/28;
  - validate with ≥ 3 findings: 0/20, so excluded;
  - generate on lifecycle components 28/48, other components 4/24.
- Accepted generate traces were 4–14% shorter than rejected ones for the same prompt: a mild
  short-trace bias.

**Full run (full1):** 374 prompts → 213 records (fix 80, validate 69, generate 65) after a trace audit
removed one with a false claim ("`dateAdd` mutates the date"). Dataset `clover_ctl_selfdistill_data`.

**sd1** is that set trained as phase 3 on the base, 2 epochs (`configs/qwen38_selfdistill.yaml`).
- **Fix, thinking on, n=20:** 0.739 → **0.7915** (+0.0525, 95% CI [+0.010, +0.095], p ≈ 0.01).
  The gain is on T39 and T43 (fewer false claims: T43 traps 15 → 5). T40 is flat.
- **Thinking-off generate, validate and fix** all within 0.01 of base.
- **Validate thinking on** stays below thinking off (0.81 vs 0.86).
- **Style unchanged;** fix thinking is 19% shorter than the teacher's.
- The n=5 "T40 gain" was noise.

**What did not help:**

| attempt | result |
|---|---|
| sd1a: + 11 authored, "Qwen-styled" traces | null. Authored-trace NLL under the teacher is 1.77 per token against 0.13 for its own traces; at this dose they are not learned. One authored trace (treasoniae_292) taught the null-list belief and must never be trained. |
| sd2: second generation, sd1 ep2 as teacher, 518 records | generate 0.982, validate 0.780, fix n=20 **0.684** (vs 0.711) |
| sd2b: sd2 rebalanced to thirds, fix ×2 | fix 0.6705 (−0.041, p = 0.05); dilution is not the cause |

**Conclusion:** sd1 ep2 was the incumbent then. No generation-3 self-distillation: scaling own traces
past about 200 bought nothing and cost fix.

#### DPO round 1 and targeted repairs: no measurable effect

| run | data | result |
|---|---|---|
| dpo1 on base | 187 same-prompt accepted/rejected self-distill pairs (≤ 3000 tokens) | generate 0.975 vs 0.985; validate 0.792 vs 0.792; fix n=20 0.681 vs 0.704 |
| dpo1full | 209 pairs at 5248 tokens (ZeRO-3) | fix 0.687 (p = 0.48) |
| dpo1 on sd1 ep2 | — | generate 0.990 → 0.979 on a repeat: the first "gain" was noise |
| dporep | 88 agent-repaired pairs (`spec/dpo_targeted_repairs_spec.md`), lr 5e-6, 2 epochs | fix 0.673 (p = 0.19); validate 4 runs 0.769–0.861 (base 0.768–0.792) |

Reward accuracy reached 1.0 fast in every DPO run; the model learns to separate the pairs, not to
change its behaviour (as in §3.16 and §3.17). These runs set the noise rules then: **one n=5 validate
run swings ±0.05.** §4.7 later found the WRONG rate noisier still.

**Chunked DPO log-probs:** `dpo_logps_chunk_size` in `~/LlamaFactory` (local commit 83fda7c8). The
LM head is applied in checkpointed chunks, so the 248k-vocabulary logits are never materialised. That
fits 7.7k-token pairs on one GPU (75.9 GB peak at chunk 1024); without it, runs OOMed at 4.2k. The
log-probs are bit-identical. Set it whenever DPO pairs are long.

#### The recipe retrains: rb1003–rb1005

Goal: retrain on the corpus corrected for the owner rulings (§7), the 72 belief records and 32 belief
DPO pairs.

| run | recipe | answer-less runs | fix n=20 (on) | notes |
|---|---|---|---|---|
| base (fix6) | thinking-off SFT → DPO | 0/215 | 0.698 | — |
| rb1003 | same recipe, corrected data | **20–25/215** | — | non-thinking SFT erodes thinking: on short tasks the model answers inside `<think>` and stops without `</think>`. DPO partly repairs it. |
| rb1003 + sd1 phase 3 | repair attempt | 14–17/215 | 0.6625 | validate worse (WRONG 16–21%); not a fix |
| ctrl1004 | base recipe, old data, new LlamaFactory | 5/215 | 0.678 | the environment adds ~2.5% fragility (or luck); the corrected data multiplied it |
| rb1004 | mixed-thinking SFT (`enable_thinking: null`) with the 1077 authored traces | 0 | **0.526** | median fix thinking 207 words (base 1120): short authored traces teach shallow thinking |
| **rb1005** | mixed-thinking SFT with **own self-distilled traces** ×2 (464), DPO 1,953 pairs | **0** | 0.719 | thinking length kept (1297 words); T41 0.99 (infix `in` belief learned); generate on 0.988 / off 0.972 |

**Lessons:**
- Whatever thinking data is in the SFT sets the model's reasoning length and style. Use the model's
  own long traces for the thinking share (as the Qwen3 recipe does), never authored short ones.
- Non-thinking SFT is the fragile part of the old recipe. Check the answer-less rate before reading
  any score.
- **Route by task** (base, snapshot 1003, `results/*base*`):

  | | thinking on | thinking off |
  |---|---|---|
  | generate | 0.984 | 0.982 |
  | validate | 0.806 (WRONG 9.3%) | **0.859** (4.7%) |
  | fix n=20 | **0.698** | 0.508 (p < 0.001) |

  Use thinking off for validate, thinking on for fix, either for generate.
- rb1003's T38 collapse (1.00 → 0.00, thinking off) belonged to that one training run. ctrl1004 and
  rb1004 pass it 10/10 on the same data.

rb1005's recipe, with 120 fix-explained records added, became **rb1006** (§3.16), the base for all
later work.

**Data conventions from this period:**
- The 1077 authored traces in `sft_training_data/CTL_LoRAT_*.json` are renamed
  `orig_reasoning_content`. They are kept for reference only and never trained or converted.
- Self-distilled traces use `reasoning_content`.
- `~/LlamaFactory/data/dataset_info.json` carries git `skip-worktree`, so dataset registrations don't
  show in `git status`.

### 3.19 On-policy context distillation removes the declaration belief (runs c1–c8)

> **Added 2026-10-12.** Method: `spec/onpolicy_context_distillation_spec.md`, implementation `opcd.py`,
> configs `configs/opcd_c1…c8.yaml`, hard-case sets and the eval script in `data/opcd/`.
> Judge gpt-6.1-sol. Numbers marked *vLLM* are from the vLLM path (§4.7).

**Method.**
- **Student:** rb1006 + a rank-32 LoRA, with the plain system prompt, sampling its own answers.
  Sampling runs on a vLLM server with the round's adapter hot-loaded: 2.5 min per round, against
  50 min with HF.
- **Teacher:** the same weights with the adapter disabled, and the rule in the system prompt.
- **Loss:** per-token reverse KL on the student's sampled tokens. The advantage is
  `A_t = log π_teacher − log π_student`, and the loss is `L = −Σ A_t log π_student / n_tokens`.
- **Schedule:** 32 prompts × 2 samples per round, 2 optimizer steps per round, lr 1e-5 (c1) or
  2e-5 (c2 onward).
- **Replay prompts (40% of each batch)** are scored by plain rb1006: an on-policy anchor back to
  rb1006. Replay validate runs thinking off.
- **A prompt-based teacher never scores thinking-off samples** (§3.16, priming).
- **Rule-citation guard:** a student sample that credits a declaration rule to "the system prompt"
  is scored against plain rb1006 instead. The student had started to cite a rule it never saw, in
  6–10% of answers.

**Hard-case sets** (agent-written prompts only; the teacher supplies the targets):

| set | prompts | shape | plain rb1006 | rule teacher |
|---|---|---|---|---|
| 1 `hard_cases.jsonl` | 40 | declared trap next to real nullable inputs | 78% belief | 0% |
| 2 `hard_cases2.jsonl` | 15 | T40/T42-shaped date traps: previous-record, latest, earliest | 88% | 0% (claims null) |
| 3 `hard_cases3.jsonl` | 20 A + 20 B | A: generate with a first-record sentinel; B: Rollup accumulator nullability | A 0%; B 27–60% wrong | v3: B 12–65% wrong; **v4: 0%** |

Measure with `data/opcd/eval_hard_cases.py`. It judges each trap: "claims null" for sets 1–2, a
bare-declaration sentinel for 3A, the accumulator start value for 3B. Don't use the regex probe; it
stayed flat while the belief fell.

**Runs.** Each run continues the previous one's adapter unless marked fresh:

| run | change | T40 / T42 false fix (n20) | key result |
|---|---|---|---|
| c1 | pilot, lr 1e-5, 16 rounds | not measured | set 1 belief 78% → 49% held-out; dates 100% → 73% |
| c2 | lr 2e-5, + set 1 (30 trained, 10 held out) | 9 / 15 → 6 / 17 at round 39 | set 1 held-out 0%; first method to move T40/T42 |
| c3 | + set 2 ×3, 55 contrast prompts, citation guard | 5 / 9 | set 2 held-out 1/16 |
| c4 | rule v3 teacher; contrast validate thinking on | 3 / 12 (HF), **0 / 4 (vLLM)** | set 2 0/36; fix ON 0.85 |
| c5 | rule v4 (+ the per-group accumulator reset) on everything | 7 / 15 | belief partly back (set 2 previous-record 9/36): interference |
| c6 | rule v4 on Rollup prompts only (`component_teacher`) | 2 / 15 (vLLM) | set 2 0/36; set 3B improved |
| c7 | **fresh** adapter, all data at once, 40 rounds | 0 / 6 (vLLM) | ≈ c6: chaining runs is not a problem |
| c8 | c6 + top-k soft cross-entropy on Rollup (spec option B) | 0 / 6 (vLLM) | no gain over c6 |

**Same conditions, all on vLLM** (thinking on: full suite n5; thinking off: validate 9 reps × n5):

| model | generate ON | validate ON (WRONG) | fix ON | validate OFF (WRONG) | T22 OFF WRONG / 45 | set 3B wrong (default / non-null / nullable) |
|---|---|---|---|---|---|---|
| rb1006 | 0.963 | 0.786 (14.9%) | 0.760 | 0.886 (7.5%) | 19 | 6 / 12 / 11 |
| **c4** | 0.965 | 0.791 (19.5%) | 0.848 | **0.877 (8.2%)** | 28 | 11 / 8 / 10 |
| c5 | 0.980* | 0.775* (17.2%*) | 0.842* | 0.881 (7.4%) | 34 | 6 / 4 / 8 |
| c6 | 0.973 | 0.794 (16.9%) | 0.842 | 0.864 (8.5%) | 38 | 2 / 1 / 5 |
| c7 | 0.974 | 0.778 (16.2%) | **0.876** | 0.860 (9.5%) | 42 | 4 / 1 / 4 |
| c8 | 0.974 | 0.744 (21.4%) | 0.864 | 0.869 (8.3%) | 37 | 2 / 1 / 8 |

\* c5's thinking-on row is from HF, not vLLM (its vLLM thinking-on suite was not run); its T40/T42 n20 was
7/15 on HF.

**Findings:**
1. **OPCD removes the declaration belief where four earlier methods failed** (§3.16):
   - T40 0/20, T42 roughly 4–6/20;
   - held-out hard cases 0%;
   - fix +0.09 over rb1006;
   - generate unchanged.

   The per-token signal is local. The tokens it penalizes most are the belief itself ("is not
   initialized at module level without an explicit…", A = −9.8).
2. **It works where the student states the belief, not where it omits a fact.** The declaration
   belief is something the student writes, so the teacher can correct it token by token. The
   accumulator fact is mostly an omission: the student fails to mention that an unmarked field starts
   null. KL to the accumulator teacher stayed around 0.02 over 16 rounds (c6). The top-k loss, meant
   for exactly this, did not help (c8).
3. **The accumulator fact goes opposite ways with thinking on and thinking off.** Every run that trained
   on it improves set 3B with thinking on. But thinking-off T22 gets worse: 19 → 37–42 of 45, mostly
   "the accumulator field starts at 0" or "keeps the previous group's value".
4. **One teacher for both facts interferes** (c5): "accumulator fields can be null" relaxes "declared
   variables are never null". Splitting teachers by component (c6) avoids that.
5. **Thinking-on validate WRONG rose in every OPCD run:** rb1006 14.9% → 16.2–21.4% (c4 19.5%, c8 21.4%).
   The validate score mostly held (0.744–0.794 against 0.786). This is the one thinking-on regression. Thinking-on is not the deployed mode for validate (§3.18,
   route by task), but a thinking-on validate deployment would need it fixed. A single n5 run; repeat it
   before acting on it.
6. **Every added rule sentence costs thinking-on validate a little:** v3 0.801, v4 0.742, v5 0.764,
   rb1006 0.791. The format slips too: v4 dropped severity labels on T26. Keep teacher prompts short.
7. **There is no path dependence:** c7, one fresh adapter, matches the chained c6.
8. **Two facts from the teacher checks, both now in the corpus reference:**
   - metadata fields are nullable unless marked `nullable="false"`;
   - the Rollup accumulator is reset from metadata before every group.

   Plain rb1006 gets both wrong. The second one, the reset, is a third belief: that values carry over
   between groups.

**Recommendation: c4 — chosen by the owner on 2026-10-13** (adapter `data/opcd/c4/round_015/adapter`, gitignored; config
`configs/opcd_c4.yaml`).
- It removes the declaration belief, keeps fix +0.09, and holds generate.
- It has the smallest thinking-off cost: 0.877 against 0.886, within about 1 sd.
- **c7 is the alternative if fix matters more:** fix 0.876 and the best generate, at −0.026 thinking-off
  validate.
- **Handle the accumulator fact outside OPCD,** for example thinking-on review for Rollup, or
  thinking-off DPO from c6's correct thinking-on answers. Don't keep adding it to this adapter.

**Practical notes:**
- The c1–c8 adapters are in `data/opcd/c*/round_*/adapter`.
- An adapter is merged for HF with `opcd.py export`, or served directly on vLLM; the
  `adapter_vllm` copy has the renamed keys.
- `scripts/opcd_run.sh RUN TRAIN_GPU LAST_ROUND` trains and evaluates one run end to end in about
  2.5 h (16 rounds) plus 30 min of evaluation.

### 3.20 Suite v5: real-world generate tests — the models tie, and share the same gaps

**Why a new suite part.** The 25 v4 generate tests score 0.96–0.98 for every model since September: they are unit
tests of one CTL2 feature each, in tidy language. Production tasks have 15–40-field metadata, business-language specs,
graph context (lookups, sequences, parameters, dictionary, reject ports) and real edge cases. An agent wrote 30 such
tests (`spec/suite_generate_rw_brief.md`, `data/suite_v5/generate_rw.json`); they are scored apart as `generate_rw`,
so `generate_score` and `suite_score` stay comparable with v4.

**Round 1 did not measure much.** Its 30 tests were 12 scenarios with renamed fields (75–94% shared 5-grams), and 6 of
the 12 scored 0.97–1.00 for every model. rb1006 / c4 / c7 at n=5: thinking off 0.925 / 0.926 / 0.915, on 0.952 /
0.946 / 0.965. Eight references (lookup, sequence, parameters) had never been run.

**Round 2** (`spec/suite_generate_rw2_brief.md`) replaced the clones with distinct scenarios over 8 components
(max cross-prompt 5-gram Jaccard 0.11) and ran **every reference in a real graph** on CloverDX Server (sandbox
`MiscExamples/suite_v5`, 8–20 edge-case records each; `data/suite_v5/run_graphs/`). The runs settled runtime
questions that compile checks miss; they are now `ctl2-basics.md` §13.3. Then, here:
- **The rubrics were rewritten** (`data/suite_v5/round2/rubric_rewrite_rules.md`): 161 of the agent's 259 required
  items were the prompt clause copied verbatim, bundling 3–5 edge cases each with boilerplate rationales. Now 344
  atomic, code-decidable items with every valid CTL2 alternative listed, and 66 forbidden items for runtime defects only.
- **Prompt fixes:** clauses that gave the trap away were removed (null-testing a declared variable, `STOP`, expected
  values), and spec gaps closed. T69 had to be reworded: every model with thinking on read "the shared library exports
  four functions" as already provided and wrote only the caller (0.08 in all three).

**Result** (vLLM, gpt-6.1-sol; the 21 tests that separate anything, n=15 pooled; bootstrap 95% CIs over runs):

| mode | rb1006 | c4 | c7 | c4 − rb1006 | c7 − rb1006 |
|---|---|---|---|---|---|
| thinking off | 0.721 | 0.726 | 0.723 | +0.004 [−0.019, +0.029] | +0.001 [−0.023, +0.025] |
| thinking on | 0.859 | 0.863 | 0.865 | +0.004 [−0.017, +0.024] | +0.006 [−0.015, +0.026] |

All 30 at n=5 (T69 after its fix): off 0.774 / 0.791 / 0.801, on 0.899 / 0.892 / 0.897. **OPCD neither helped nor
hurt generation.** c7's +0.03 thinking-off lead at n=5 disappeared at n=15: at n=5 a single test's score moves by
±0.1, so model comparisons on this part need n≥10 on the discriminating tests (`scripts/suite_v5_rw_run.sh`, `TESTS`
and `RUNS`).

**What it does show is a set of gaps every variant shares** (n=15, thinking off / on, range over the three models):

| test | what it needs | off | on |
|---|---|---|---|
| T53, T54 | DataIntersection: CTL writes `$out.0` (sent out on port 1); matched pairs only | 0.37–0.79 | 0.70–0.76 |
| T73 | dictionary entries as run state, history kept only for accepted rows | 0.52–0.59 | 0.67–0.71 |
| T44, T46 | multi-check validation to two ports, every failed check listed, no parse exception | 0.39–0.63 | 0.81–0.96 |
| T60 | SCD type 2 as a Normalizer (CLOSE/OPEN/audit rows, sequence keys) | 0.45–0.54 | 0.88–0.90 |
| T63 | fiscal-quarter Rollup in UTC on a CET host | 0.54–0.57 | 0.96–0.97 |
| T57 | Rollup with a per-record emit (`updateTransform`) and a group emit | 0.74–0.85 | 0.59–0.77 |
| T67 | Partition with state across records | 0.70–0.74 | 0.69–0.79 |

Thinking closes most of the onboarding, SCD and fiscal gaps but not DataIntersection, dictionary, the Rollup
per-record emit or the stateful Partition. These are corpus gaps, not effects of the OPCD runs.

**Practical notes:**
- Suite `results/eval_snapshot_20261013/ctl2_test_suite_v5.json` (v4 + T44–T73) with the reference of that date.
  The v5rw2 baselines above were judged against `resources/` before §8.9 was corrected and §13.3 added; re-judge
  (`data/rejudge_results.py`) before comparing new runs with them.
- `test.py` and `rejudge_results.py` report `generate_rw` separately; `self_distill.SUITE_FILES` excludes v5.
- Results: `results/results_qwen38_v5rw2*` (n=5) and `results_qwen38_v5rw2n10*` (n=10 on the 21 tests).

### 3.21 OPCD c9: a component-guide teacher closes most of the thinking-off generate gaps

**Why.** Suite v5 (§3.20) found generate gaps that every variant shares. A brief (`spec/opcd_generate_gaps_brief.md`,
fixed in `_fix_brief.md`) had an agent write 120 run-verified generate prompts, 20 for each of six gaps. The first
delivery was templated, with garbled clauses and trap giveaways; the rebuild fixed the text, though the prompts within
a gap still share 2–4 solution skeletons (references 81–95% alike with field names masked).

**Teacher check first** (`data/opcd/build_teacher_check.py`; 36 prompts × 4, both modes). A teacher with the CloverDX
component guide (`component_get_guide`: contract, examples, common mistakes; the dictionary guide for G1) plus
`ctl2-basics.md` §13.3 in its system prompt, against plain c4:

| gap | thinking off | thinking on |
|---|---|---|
| G1 dictionary state | +0.28 | +0.40 |
| G3 stateful routing | +0.18 | +0.04 (c4 already 0.93) |
| G4 SCD versioning | +0.18 | +0.18 |
| G6 UTC calendars | +0.22 | +0.25 |
| G2 Rollup per-record + group emit | −0.04 | −0.06 |
| G5 multi-check validation | +0.06 | −0.03 |

The numbers are for the OPCD teacher itself: rb1006 with the adapter disabled and rulev3 + guide + §13.3 (c4 + guide
gave the same picture). Without rulev3 the base would re-teach the declaration belief c4 removed. **G2 and G5 are not
knowledge gaps:** with thinking on, c4 already scores 0.91 and 0.87, and the guide does not help it apply the knowledge
without thinking. They were left out.

**Run c9** (`configs/opcd_c9.yaml`, `data/opcd/build_c9.py`): from c4 round 15, 20 rounds. The 68 G1/G3/G4/G6
prompts (12 held out) train in both modes, each scored by its component's teacher (`opcd.py`: per-prompt `teacher`
and `mode`); hard-case sets 1–2 and replay 0.4 as in c4. Gap KL per token fell 0.05 → 0.016; replay KL stayed near 0.

**Result** (vLLM, gpt-6.1-sol):

| measure | c4 | c9 |
|---|---|---|
| suite v5 gap tests, thinking off (9 tests, n10) | 0.574 | **0.691** |
| suite v5 gap tests, thinking on | 0.850 | 0.835 |
| held-out gap prompts, thinking off (12 × 4) | 0.370 | **0.518** |
| held-out gap prompts, thinking on | 0.652 | 0.712 |
| validate, thinking off, 9 reps (WRONG) | 0.877 (8.2%) | 0.882 (**6.5%**) |
| validate / fix / generate (v4), thinking on | 0.791 / 0.848 / 0.965 | 0.843 / 0.826 / 0.972 |
| T40 + T42 false fixes (n20 each) | 4/40 | 3/40 |
| hard sets 1 / 2 (declaration belief) | 0/160, 4/60 | 2/160, 5/60 |

- **Thinking off is where it works.** On the suite tests, which were never trained on: T63 fiscal Rollup +0.22, T60 SCD
  +0.20, T61 carried state +0.18, T46 onboarding +0.17, T73 dictionary +0.17. Some gains are outside the trained gaps
  (T46 multi-check), so part of it is general. Every gap improved on the held-out prompts.
- **Every c4 gate holds.** Thinking-off validate WRONG went down, fix stays within −0.03, T40/T42 and the hard sets are
  within noise.
- **Thinking on is mixed.** Confirmation reruns:
  - suite T57 / T61 at n20: −0.03 / −0.10, pooled −0.06 [−0.20, +0.08], not significant;
  - G4 SCD held-out prompts at n14: **−0.19 [−0.29, −0.10], real.** Half of it is length: c9 thinks about 20% longer on
    these tasks (median 43k vs 36k characters) and 9 of 42 answers hit the 16k-token limit (c4: 1 of 42). The other
    half is quality: completed answers score 0.49 against 0.59. On the other gaps c9's median thinking length equals
    c4's, with a longer tail.

**Status:** c9 is the candidate successor to c4 for thinking-off generation; adopting it is the owner's call (§6). A
follow-up should keep the thinking-off gain without the thinking-on SCD loss, for example by training the G4 prompts
thinking-off only, or raising the sampling cap above 6,144 tokens so thinking-on samples are not trained as truncated
prefixes.

**Practical notes:**
- Adapter `data/opcd/c9/round_019/adapter` (gitignored), `adapter_vllm` for vLLM. `scripts/opcd_c9_run.sh` trains on
  GPU 1 with the sampler on GPU 3 (about 3.5 h), then runs all the evaluations above (about 1.5 h).
- Teacher configs: `configs/opcd_c9_teachers/`; prompts `data/opcd/generate_gaps_c9.jsonl`, holdout
  `generate_gaps_c9_holdout.json`; result files `results/results_qwen38_{gapho,v5gaps,confirm_*}_{c4,c9}_*`.

### 3.22 OPCD c10 and c11: skipping truncated samples helps; the DataIntersection/SCD-2 group does not transfer

**c10** (`configs/opcd_c10.yaml`) is c9 with one change: thinking-on samples that hit the 6,144-token sampling cap are
not trained (`train.skip_truncated: ["on"]`). c9 had trained every thinking-on SCD Normalizer answer only as a
truncated thinking prefix (64 of 64 at the cap). From c4 round 15, 20 rounds.

**c11** (`configs/opcd_c11.yaml`, `data/opcd/build_c11.py`) continues from c10 round 19 for 24 rounds and adds two
prompt groups, built from the user turns of the owner's run-verified SFT sets:
- **DataIntersection (50 prompts):** guide-only teacher (DataIntersection guide + `ctl2-basics.md` §8.9 + §13.3).
- **SCD-2 (50 prompts):** guide teacher plus the verified answer to the same request as a worked example in the
  teacher's prompt (SDFT-style, `teacher_context_field`).

The teacher check chose that split: the guide teacher scored T53/T54 1.00 (c10 0.48–0.61), but was below c10 on SCD
T60/T61. 10 prompts per group were held out. The c9/c10 gap prompts stay in at weight 1. Training was clean: target KL
0.12 → 0.03, no cap hits.

**Result** (vLLM, gpt-6.1-sol; T40/T42 counted as samples below full score, so the c9 figure differs from §3.21):

| measure | c9 | c10 | c11 |
|---|---|---|---|
| suite v5 gap tests, thinking off (9 tests, n10) | **0.691** | 0.671 | 0.650 |
| suite v5 gap tests, thinking on | 0.835 | **0.852** | 0.782 |
| c9 held-out gap prompts, off / on (12 × 4) | 0.518 / 0.712 | 0.477 / **0.745** | 0.509 / 0.727 |
| G4 SCD held-out, thinking on (3 × 10) | 0.364 | 0.376 | 0.324 |
| validate, thinking off, 9 reps (WRONG) | 0.882 (6.5%) | 0.872 (6.8%) | 0.879 (6.1%) |
| validate / fix / generate (v4), thinking on | 0.843 / 0.826 / 0.972 | 0.781 / **0.924** / 0.972 | 0.807 / 0.882 / 0.968 |
| T40 + T42 below full score (n20 each) | 5/40 | 8/40 | 6/40 |
| hard set 2, belief claims (60 samples) | 4 | 3 | **10** |
| DataIntersection T53 off / on (n10) | — | 0.48 / 0.50 | **0.14** / 0.58 |
| SCD T60 off, T61 on (n10) | — | 0.71, 0.80 | **0.42**, **0.48** |
| c11 holdouts DI off / on (10 × 4) | — | 0.61 / 0.54 | 0.65 / 0.59 |
| c11 holdouts SCD off / on | — | 0.73 / 0.71 | 0.79 / 0.81 |

**c10 is the best model so far.** It keeps c9's thinking-off gain on the suite (0.671 vs c4's 0.574, within noise of
c9) and recovers the thinking-on side:
- gap tests 0.852 vs c9's 0.835;
- fix 0.924, the highest of any run;
- only 1 of 110 thinking-on gap answers fails to close `<think>`.

Skipping truncated samples removed the thinking-on cost that c9 paid. G4 SCD stays weak in both (thinking on, c9 0.364
vs c10 0.376), so it is a knowledge gap, not a training artefact.

**c11 does not transfer.**
- **The same-set holdouts improved** (SCD +0.06/+0.10, DI +0.04/+0.05).
- **The independent suite tests that measure the same gaps got worse:**
  - T53 thinking off 0.48 → 0.14;
  - T60 thinking off 0.71 → 0.42;
  - T61 thinking on 0.80 → 0.48.
- **Hard set 2 belief claims rose** from 3 to 10 of 60.

A checkpoint check (`scripts/opcd_ckpt_check.sh`, rounds 7/11/15 on T53/T60/T61 at n10) shows that no earlier round is
usable:

| | T53 off | T60 off | T61 on (failed to close `<think>`) |
|---|---|---|---|
| c10 r19 | 0.48 | 0.71 | 0.80 (1) |
| c11 r07 | 0.58 | 0.56 | 0.45 (4) |
| c11 r11 | 0.51 | 0.53 | 0.68 (3) |
| c11 r15 | 0.34 | 0.36 | 0.51 (3) |
| c11 r23 | 0.14 | 0.42 | 0.48 (5) |

- **T53 falls with every round.**
- **T60 thinking off drops by round 7.**
- **T61 thinking on is mostly thinking length:** from round 7, 3–5 of 10 answers don't close `<think>`. Completed
  answers score well (4 × 1.0 and 0.83 at r23).

**Why: the DataIntersection prompts gave the answer away.** All 28 code prompts in the round-1 DI set said where the
result goes ("physical output1 is represented by the single local `$out.0` record"). So neither the student nor the
teacher ever had to decide it, and nothing carried over to an unhinted prompt like T53. On T53 c11 still writes
`$out.1`/`$out.2` in 10 of 10 samples, as c10 does. c10 routes with `getOutputPort()`; c11 instead moves the logic
into invented per-port callbacks (`transformMatched()`, `transformUnmatched()`), which the component never calls.

The SCD-2 set passed the same audit:
- no hints;
- every `$out.1` is in a two-output Reformat;
- every `count()` / `transform(idx)` is in a Normalizer.

Its loss is the c9 pattern again: longer thinking on SCD. The DI set has been revised
(`spec/dataintersection_training_set_fix_brief.md`, `_explanations_fix_brief.md`; ctl_lora_training `d80aaa5`):
- no mechanism hints;
- 14 whole-component prompts in the T53 framing;
- 9 DPO pairs that reject per-port CTL;
- run-verified.

**Lessons:**
- **Judge a prompt group on independent tests, not on holdouts from the same authored set.** The holdouts share the
  set's framing and hints.
- **Check the prompts of an OPCD group for mechanism hints before training,** as for any corpus set.
- **A guide teacher plus a worked example raises thinking length on SCD.** Every SCD group so far (c9 G4, c11 SCD) has
  cost thinking-on answers through `<think>` that does not close.

**Status:** c10 is the recommended ship candidate (the decision is the owner's). c11 is not adopted.

**Practical notes:**
- Adapters: `data/opcd/c10/round_019/adapter`, `data/opcd/c11/round_023/adapter` (gitignored).
- Run scripts:
  - `scripts/opcd_gaps_run.sh RUN LAST` with `HO2=` / `BASE=`: training plus all the evaluations above;
  - `scripts/teacher_check_c11.sh`;
  - `scripts/opcd_ckpt_check.sh`.
- Result files: `results/results_qwen38_{ho2,gapho,v5gaps,confirm_ho,ckpt}_c1[01]*`.

### 3.23 OPCD c12: unhinted DataIntersection prompts, a correct teacher, and the rule still does not transfer

**Teacher check on the revised DI set** (ctl_lora_training `d80aaa5`: no hints, 10 whole-component prompts;
`data/opcd/build_di2_tcheck.py`, 60 prompts × 3, judged against the verified answer):

| | all, off / on | whole-component, off / on |
|---|---|---|
| teacher (rb1006 + rulev3 + DataIntersection guide + §8.9 + §13.3) | 0.88 / 0.90 | 0.95 / 0.95 |
| c10 | 0.23 / 0.16 | 0.00 / 0.00 |
| c11 | 0.28 / 0.24 | 0.03 / 0.00 |

Without the hint, c10 and c11 write `$out.1`/`$out.2` and invent functions for the one-sided records, in both modes.
c11's round-1 training raised only validate (0.42 → 0.65 off).

**Run c12** (`configs/opcd_c12.yaml`, `data/opcd/build_c12.py`): from c10 round 19, 20 rounds:
- the 50 revised DI prompts in both modes, with the guide teacher and no worked example (10 held out, 3 of them
  whole-component);
- the c9 gap prompts and hard sets 1–2 at weight 1;
- no SCD.

DI KL per token fell 0.09–0.11 → 0.04–0.05; the run was otherwise clean.

| measure | c10 | c12 |
|---|---|---|
| DI holdouts, off / on (10 × 4) | 0.19 / 0.24 | 0.16 / 0.28 |
| T53, off / on (n10) | 0.48 / 0.50 | 0.63 / 0.66 |
| T54, off / on | 0.61 / 0.56 | 0.61 / 0.61 |
| suite v5 gap tests, off / on (9 tests, n10) | 0.671 / **0.852** | 0.662 / 0.820 |
| c9 gap holdouts, off / on | 0.477 / 0.745 | **0.563 / 0.797** |
| G4 SCD holdout, thinking on (3 × 10) | 0.376 | **0.417** |
| validate, thinking off, 9 reps (WRONG) | 0.872 (6.8%) | 0.878 (6.2%) |
| validate / fix / generate (v4), thinking on | 0.781 / **0.924** / 0.972 | 0.829 / 0.882 / 0.976 |
| T40 + T42 below full score | 8/40 | 10/40 |
| hard set 2, belief claims (60) | 3 | **13** |

- **The rule did not transfer.** In code answers on the held-out DI prompts, c12 writes `$out.1`/`$out.2` in 27 of 28
  thinking off (c10: 28/28) and 24 of 28 thinking on. On T53 it does so in 10 of 10 samples; the T53 gain is on other
  rubric items.
- **On its own training prompts the student moved halfway.** Code samples with `$out.1`/`$out.2` went from 13 of 14
  (round 0) to 5 of 13 (round 19).
- **Hard set 2 (previous-record dates) regresses with every DI dose:** c10 3/60, c11 10/60, c12 13/60.
- **Thinking-on gap tests dropped 0.852 → 0.820,** mostly T61 −0.10 and T57 −0.08. It is not thinking length: 2 of 110
  answers failed to close `<think>`.
- **Leaving SCD out helped:** the gap holdouts improved in both modes and G4 reached 0.417, the best yet.

**Reading.**
- **The teacher is not the bottleneck** (0.95 on whole-component prompts). Adding an explicit rule to its prompt would
  change little.
- **More dose would** probably move the training prompts further, but held-out transfer lags far behind, and the hard
  set 2 regression grows with the dose.
- **Unlike the declaration belief (§3.16), this is probably not a pretrained prior.** The corpus had no DataIntersection
  examples before the owner's set, so `$out.N` is the obvious guess filling a gap, which SFT and the new DPO pairs
  address directly.

**Decision (owner, 2026-10-15):**
- go straight to the base rebuild with the revised DI and SCD-2 SFT/DPO sets;
- check T53/T54 and the DI holdouts on the new base before any further OPCD;
- c12 is not adopted.

**Practical notes:**
- Adapter: `data/opcd/c12/round_019/adapter`.
- Teacher check: `scripts/teacher_check_di2.sh`.
- Result files: `results/results_qwen38_{tcheck_di2,ho2,gapho,v5gaps,confirm_ho}_c12*` and `*_tcheck_di2_*`.

---

### 3.24 rb1009: the DataIntersection rule is learned through SFT/DPO, where OPCD failed

**Run.** `configs/qwen38_rb1009.yaml` is the rb1006 recipe (§5 steps 1–2) on corpus ctl_lora_training `d80aaa5`.
- **Added:**
  - the run-verified DataIntersection set (60 SFT, 40 DPO; round 2b, unhinted);
  - the SCD-2 set (60 SFT, 40 DPO);
  - the corpus fixes since `a4d8274` (declaration-defaults audit).
- **Excluded on purpose** (owner, 2026-10-15), so that the DI/SCD-2 effect is attributable:
  - `CTL_LoRA_fix_defaults_explained.json` (rb1007: no effect on the belief, fix −0.03, roundHalfUp hallucination);
  - `CTL_LoRA_declaration_defaults_contrast.json` (never trained).
- **Size:** SFT 13,113 records (12,185 + 928 own traces), DPO 2,033 pairs; `build_sft_rebuild.py` now takes the extra
  exclusions as arguments.
- **Training:**
  - SFT 4.3 h, DPO 0.6 h on one GPU;
  - losses as rb1006 (SFT eval 0.1788 vs 0.1801; DPO eval 0.1203 vs 0.1194, eval reward accuracy 95.9% vs 98.0%);
  - pre-flight clean.

**Result vs rb1006** (`scripts/rb1009_eval.sh`, vLLM, gpt-6.1-sol; suite v5 tests n10; v4 n5; validate OFF 9 reps):

| measure | rb1006 | rb1009 |
|---|---|---|
| **T53 DataIntersection, off / on** | 0.38 / 0.66 | **1.00** / 0.75 |
| T54 DataIntersection, off / on | 0.79 / 0.71 | 0.81 / **0.86** |
| T60 SCD Normalizer, off / on | 0.57 / 0.86 | 0.58 / **0.95** |
| T61 SCD change log, off / on | 0.74 / 0.83 | 0.70 / 0.89 |
| suite v5 gap tests (9), off / on | 0.647 / 0.835 | 0.676 / 0.845 |
| v4 generate, off / on | 0.979 / 0.948 | 0.966 / 0.960 |
| v4 validate, off (9 reps) / on | 0.886 / 0.762 | 0.861 / 0.787 |
| validate WRONG, off / on | 7.5% / 14.9% | **5.7%** / 14.7% |
| v4 fix, off / on | 0.564 / 0.760 | 0.544 / **0.826** |
| T40 + T42 below full score (n20 each) | (belief 20/20 each, §3.16) | 40/40 |
| hard sets 1 / 2 / 3, belief claims | 78% / 97% / 0% | 74% / 92% / 0% |

- **T53 thinking off is solved.** `$out.1`/`$out.2` appear in 0 of 10 answers; c12 still had them in 10 of 10 after OPCD.
  Some answers add unused per-port functions, which the judge accepts.
- **Thinking on is half-way.** `$out.1`/`$out.2` remain in 6 of 10 T53 and 3 of 10 T54 answers.
- **SCD thinking on improved** (T60 +0.09, T61 +0.06). Thinking off is flat.
- **Nothing else moved beyond noise.** Thinking-off validate is −0.025 with fewer WRONG findings; fix thinking on +0.07.
- **The declaration belief is at base level,** as expected: rb1009 has no OPCD. That is what c13 re-applies.

**Reading.** One SFT/DPO rebuild taught what two OPCD runs (c11, c12) could not. `$out.N` was a gap in the corpus, not
a pretrained prior, so the declaration-belief lesson (§3.16: SFT cannot move a prior) does not apply to it. Use the
corpus for missing knowledge and OPCD for priors and for carrying knowledge into the other thinking mode.

**Next: run c13** (`configs/opcd_c13.yaml`). It is one fresh adapter on rb1009 with:
- c4's belief data and rulev3 teacher;
- c10's gap prompts with the guide teachers;
- the 50 DI prompts at weight 1;
- 40 rounds.

The gates are c10's plus T53/T54 in both modes. `scripts/opcd_gaps_run.sh` takes `EVAL_SERVE` for a base other than
rb1006.

---

### 3.25 OPCD c13, c13b and c13c on rb1009: the best model so far

**c13** (`configs/opcd_c13.yaml`) is one fresh adapter on rb1009, 40 rounds, with:
- c4's belief prompts with rulev3, hard set 2 at weight 3;
- c10's gap prompts with the guide teachers;
- the 50 revised DataIntersection prompts at weight 1.

**c13b** (`configs/opcd_c13b.yaml`) continues c13 for 16 rounds with the belief prompts dominant, keeping a third of the
gap and DI prompts (`data/opcd/c13b_keep.jsonl`).

| measure | c10 (on rb1006) | c13 | c13b |
|---|---|---|---|
| suite v5 gap tests, off / on (9 tests, n10) | 0.671 / 0.852 | 0.720 / **0.910** | **0.726** / 0.894 |
| c9 gap holdouts, off / on | 0.477 / 0.745 | 0.555 / 0.819 | 0.542 / 0.780 |
| G4 SCD holdout, thinking on | 0.376 | 0.557 | **0.623** |
| T53 DataIntersection, off / on | 0.48 / 0.50 | 1.00 / 0.92 | **1.00 / 1.00** |
| T54, off / on | 0.61 / 0.56 | 0.97 / 0.93 | 0.97 / 0.84 |
| validate, thinking off, 9 reps (WRONG) | 0.872 (6.8%) | 0.858 (5.8%) | 0.863 (**4.7%**) |
| validate / fix / generate (v4), thinking on | 0.781 / **0.924** / 0.972 | 0.804 / 0.742 / 0.974 | 0.800 / 0.814 / 0.969 |
| T40.FP1 / T42.FP6 belief traps (n20 each) | 0 / 2 | 13 / 12 | **1** / 16 |
| hard sets 1 / 2 / 3, belief claims | 0 / 5% / 0 | 0 / 18% / 0.6% | 0 / 10% / 1.3% |
| T60 SCD Normalizer, thinking off | **0.71** | 0.35 | 0.34 |

- **Generate gains stack.** rb1009's DataIntersection knowledge plus c10's gap prompts give the best generate scores so
  far, in both modes. `$out.1`/`$out.2` in T53 code: 0/10 in both modes for c13b.
- **The diluted belief prompts let the belief back in.** In c13 they shared 40 rounds with the gap and DI prompts:
  T40/T42 traps 13 and 12 of 20, fix thinking on 0.742.
- **The focused stage (c13b) fixes T40 but not T42.** T42 is the previous-record date: a date carried from the
  previous record starts at the epoch, so the first comparison is well-defined.
- **The T42 failures are of two kinds.** Some samples still claim the date starts null. Others state the epoch default
  correctly and then "fix" it with a null initializer and a guard, presented as a bug fix.
- **The teacher is the limit.** rb1009 with rulev3 in its prompt triggers T42.FP6 in 10 of 20 samples
  (`configs/eval_tcheck_t42_rulev3_rb1009_on.yaml`). On the training side, the set-2 prompts went to 4 of 38 belief
  samples in c13b, yet T42 did not follow.
- **T60 thinking off** (SCD Normalizer) dropped in both c13 and c13b, against 0.71 for c10. To investigate.

**c13c: a teacher that passes T42.**

**Teacher check.** rulev6 = rulev3 + one paragraph: a global variable that carries a value from the previous record
starts at its default (the epoch, 0, ""). A comparison against it on the first record is well-defined. Do not replace
it with null plus a guard, or list it as a fix, unless the specification's first-record rule needs otherwise (a running
minimum that starts at 0). On rb1009, thinking on (`configs/eval_rb1006_rulev6_*.yaml`):

| teacher | T42 trap (n20) | T40 trap (n20) | v4 fix / generate / validate (n3) | validate WRONG |
|---|---|---|---|---|
| rulev3 | 10/20 | — | 0.870 / 0.989 / 0.793 | 15.4% |
| rulev6 | **0/20** | 0/20 | **0.967** / 0.984 / 0.794 | 16.7% |

Hard set 2 does not separate the two teachers (both 0/60). Its prompts are narrower than T42, a multi-defect
fix-to-spec task where the model adds the guard "to be safe". So rulev6 replaces rulev3 as the main teacher for the
thinking-on belief and hard prompts, not only on set 2. The thinking-off validate prompts stay replay-anchored to the
plain model.

**Run c13c** (`configs/opcd_c13c.yaml`): c13b + 16 rounds, same mix, rulev6 teacher.

| measure | c10 | c13b | **c13c** |
|---|---|---|---|
| T42.FP6 trap (n20) | 2 | 16 | **6** |
| T40 / T42 fix score (n25) | 0.99 / 0.87 | 0.94 / 0.77 | 0.98 / 0.85 |
| T40 + T42 below full score | 8/40 | 20/40 | **8/40** |
| hard sets 1 / 2 / 3, belief claims | 0 / 5% / 0 | 0 / 10% / 1.3% | **0 / 0 / 0** |
| suite v5 gap tests, off / on | 0.671 / 0.852 | 0.726 / 0.894 | **0.727 / 0.909** |
| c9 gap holdouts, off / on | 0.477 / 0.745 | 0.542 / 0.780 | 0.577 / 0.770 |
| G4 SCD holdout, thinking on | 0.376 | 0.623 | **0.649** |
| T53, off / on | 0.48 / 0.50 | 1.00 / 1.00 | **1.00 / 1.00** |
| validate, thinking off, 9 reps (WRONG) | 0.872 (6.8%) | 0.863 (4.7%) | 0.853 (6.6%) |
| validate / fix / generate (v4), thinking on | 0.781 / **0.924** / 0.972 | 0.800 / 0.814 / 0.969 | **0.850** / 0.826 / 0.970 |
| T60 SCD Normalizer, thinking off | **0.71** | 0.34 | 0.38 |

- **The belief is back to c10's level** (T40 + T42 8/40), with no belief claims on any hard set for the first time.
- **c13b's generate and DI gains held;** thinking-on validate is the best so far.
- **The remaining fix gap is T41** (Rollup accumulator). At n20, c13c scores 0.815 and c13b 0.838, each 13/20 below full
  score, so rulev6 did not cause it. The code is fixed correctly, but the explanation calls a nullable accumulator field
  zero-initialised. It is a weakness of the rb1009 line (c10 1.00, n5 only). A Rollup-prompt teacher with rulev4's
  accumulator note, as in c7, is the candidate fix.
- **T60 thinking off** remains low in the c13 line.

**Status:** c13c is the recommended ship candidate. It is ahead of c10 on generate, DataIntersection, the belief hard
sets and thinking-on validate; behind on fix thinking on (T41) and T60 thinking off.

**Diagnosis of the two weak spots (2026-10-17).**
- **T41 is OPCD drift, not a teacher problem.** At n20, thinking on:
  - rb1009 plain 0.988;
  - the rulev6 teacher 0.978;
  - c13c 0.815.

  The student carries "declared variables are never null" over to Rollup accumulator fields, as c2 did. The c13 line
  followed c4's recipe, which leaves out hard set 3.
- **T60 thinking off is a single-test effect.** The G4 thinking-off holdout did not regress (c10 0.18, c13c 0.30). On
  T60 the entry functions are right, but `count()` disagrees with `transform(idx)` across the 12-branch spec without
  thinking (T60.1 missed 9/10). Thinking on scores 0.95.
  - At n20 the drop is real: rb1009 0.584 → c13c 0.380.
  - It builds up over c13's rounds: r9 0.49, r19 0.38, r29 0.40.
  - The guide_NORMALIZER teacher scores 0.57 thinking off, equal to the base, so distilling the Normalizer gap prompts
    thinking-off toward it cannot help.
  - Untested option: train those prompts thinking-on only, with a plain-rb1009 anchor thinking-off
    (`configs/opcd_c13e_draft.yaml`).
- **T41 / T22 teachers, pooled n40** (two independent checks): rulev6 0.96 / 0.69, rulev7 0.97 / 0.69. The teachers are
  equal on T41; rulev7's accumulator note matters only on hard set 3 part B (8/80 → 0/79 errors).

**c13d** (`configs/opcd_c13d.yaml`) is c13c + 10 rounds with:
- hard set 3 (part A weight 1, part B weight 3, as c7);
- thinking-on Rollup prompts scored by **rulev7** = rulev6 + rulev4's accumulator note (`component_teacher`).

Teacher check on set 3 (k4): rulev6 makes 8/80 accumulator errors, rulev7 0/79. rulev7 does not help T41 directly
(0.943 vs 0.978).

| measure | c13c | c13d |
|---|---|---|
| T41 (n20) | 0.815 (13 below full) | 0.840 (10 below full) |
| T22 (n20) | 0.44 | 0.44 (teacher 0.72) |
| hard set 3 accumulator failures | 20/80 | 9/79 |
| T42 trap (n25) | 10 | 7 |
| gap tests, off / on | 0.727 / 0.909 | 0.730 / 0.917 |
| G4 SCD holdout, thinking on | 0.649 | 0.689 |
| validate / fix, thinking on | 0.850 / 0.826 | 0.759 / 0.798 |
| validate thinking off, 9 reps (WRONG) | 0.853 (6.6%) | 0.858 (6.4%) |

The thinking-on validate drop is mostly one test. T18 went 0.90 → 0.20 at n5, but both models give the same answer
(correct findings and fix, without the requested ISSUES/VERDICT format), and the judge scored it inconsistently.

**Conclusion.** c13d ≈ c13c. OPCD has reached its limit on the Rollup accumulator explanation (T41, T22): the teacher is
right, but the student moves slowly. Both gaps go to the corpus for the next rebuild
(`spec/rollup_normalizer_corpus_brief.md`). c13c stays the recommended ship candidate.

---

### 3.26 Belief durability, Part B: the corpus can carry the declaration-belief fix (rb1010a/b)

**Plan:** `spec/belief_durability_plan.md` Part B. c13c's own belief-free answers become SFT traces, so the next base
starts without the belief and OPCD no longer has to remove it after every rebuild.

**Pipeline:** `scripts/partb_run.sh`, resumed by `partb_resume.sh`; tooling in `data/build_belief_traces.py`.
- **Sampling.** c13c sampled with a plain prompt:
  - 358 belief-relevant prompts (dpodef1, dpodef3b, contrast, fix-to-spec), k4 thinking on plus k2 thinking-off validate;
  - 118 gap/DI prompts.
- **Filter.** A belief pre-scan, then the strict `self_distill.py filter` (compile, reference judge, claims audit) and
  `assemble`. Kept:
  - **belief traces: 274 prompts** (155 fix, 91 validate, 28 generate) from 638 accepted of 1,593 samples;
  - **gap/DI traces: 44**. Many thinking-on gap samples hit the 6,144-token cap.
- **Builds.** The rb1009 corpus exactly: 12,185 SFT, 2,033 DPO, the 464 own traces ×2. The new Rollup and Normalizer sets
  are excluded; the builder now applies file exclusions to DPO files too.
  - **rb1010a** = rb1009 + 230 belief traces ×1 (44 were over the 4,096 cutoff);
  - **rb1010b** = rb1010a + 37 gap/DI traces.
- **Gates:** `scripts/base_eval.sh`.

| measure | rb1009 | **rb1010a** | rb1010b |
|---|---|---|---|
| T40 / T42 belief trap (n20) | 20 / 20 | **0 / 8** | 8 / 19 |
| hard sets 1 / 2 / 3, belief claims | 74% / 92% / 11% | **1% / 38% / 4%** | 1% / 47% / 4% |
| validate, thinking off, 9 reps (WRONG) | 0.861 (5.7%) | **0.878 (5.4%)** | 0.839 (7.9%) |
| validate, thinking on (WRONG) | 0.787 (14.7%) | **0.836** (10.3%) | 0.860 (13.8%) |
| fix, off / on | 0.544 / 0.826 | 0.622 / 0.830 | 0.458 / 0.872 |
| generate v4, off / on | 0.966 / 0.960 | 0.961 / 0.969 | 0.962 / 0.961 |
| suite v5 gap tests (9), off / on | 0.676 / 0.845 | 0.677 / **0.894** | 0.595 / 0.874 |
| T53/T54 answers with `$out.1`/`$out.2`, off / on | 4/20 / 9/20 | **17/20 / 18/20** | 16/20 / 2/20 |
| T41 (n20) | 0.988 | 0.845 | 0.900 |

- **The belief transfers through the corpus.** rb1010a meets every success criterion in the plan:
  - T40 and T42 at most 10/20 each;
  - hard sets 1 and 2 at most 30% and 50%;
  - thinking-off validate WRONG did not rise. rb1008's corpus traces raised it to 13–15%. The difference: these traces
    are the model's own natural output, not a repaired minority, at about 2% of SFT records.
- **DataIntersection regressed in both arms,** although its corpus data is identical. T41 slipped too.
- **rb1010b is worse than rb1010a** on the belief and on validate, with only 37 records more.
- **So two runs of the same recipe can differ a lot.** We have never measured that variance; every rebuild has been a
  single run. rb1009's clean DataIntersection result may have been partly lucky.

**Next:** retrain rb1009 unchanged with another seed (`configs/qwen38_rb1009s2.yaml`, seed 7) and run the same gates.
- If the rerun also loses DataIntersection, Part B is a clean success, and rb1010a becomes the base for a shorter
  Stage 3.
- If it keeps DataIntersection, the belief traces interfere, and their content needs a look.


### 3.27 Rebuild variance (rb1009s2), rb1011, and Stage 3 on rb1011 (s3b-rb1011: not shown better than c13c)

**Three runs, 2026-10-19:**
- **rb1009s2:** rb1009 retrained unchanged with seed 7 (`configs/qwen38_rb1009s2.yaml`), the seed control for §3.26.
- **rb1011:** rb1010a + the revised Rollup accumulator and Normalizer sets (`spec/rollup_normalizer_fix_brief.md`).
  rb1010a's single run and the new sets cannot be separated (see variance below).
- **s3b-rb1011:** the canonical Stage 3 (`scripts/opcd_stage3.sh`) on rb1011, 40 + 16 rounds. Stage 3b now also trains
  hard set 3 (part B weight 3) and scores thinking-on Rollup prompts with the rulev7 teacher, as c13d did. The belief
  anchor was 0.50 (3a) and 0.85 (3b).

| measure | rb1009 | rb1009s2 | rb1011 | **s3b-rb1011** | c13c |
|---|---|---|---|---|---|
| T40 / T42 below full (n20) | 20 / 20 | 20 / 20 | 8 / 17 | **0 / 1** | 1 / 7 |
| hard sets 1 / 2 / 3, belief claims | 74% / 92% / 11% | 64% / 95% / 11% | 0% / 57% / 5% | **0% / 0% / 1%** | 0% / 0% / 0% |
| hard set 3 accumulator mistakes (of 80) | – | 28 | 22 | 18 | 20 |
| validate off, 9 reps (WRONG) | 0.861 (5.7%) | 0.789 (7.3%) | **0.891 (6.5%)** | 0.869 (7.7%) | 0.853 (6.6%) |
| on: validate / fix / generate | 0.787 / 0.826 / 0.960 | 0.727 / 0.863 / 0.977 | 0.829 / 0.821 / 0.974 | **0.853** / 0.798 / **0.979** | 0.850 / 0.826 / 0.970 |
| suite v5 gap tests (9), off / on | 0.676 / 0.845 | 0.736 / 0.894 | 0.713 / 0.882 | **0.740** / 0.890 | 0.727 / **0.909** |
| T53 score, off / on (n10) | 1.00 / – | 0.69 / 0.61 | 0.58 / 0.78 | **1.00 / 1.00** | 1.00 / 1.00 |
| T54 score, off / on (n10) | – | 0.65 / 0.65 | 0.59 / 0.64 | 0.63 / 0.73 | **0.97 / 0.89** |
| T60 off (n10) | – | 0.72 | 0.52 | 0.51 | 0.38 |
| gap holdouts off / on; G4 | – | – | – | 0.542 / 0.771; 0.582 | 0.577 / 0.770; **0.649** |
| T41 on (n20) | **0.988** | 0.97 (n25) | 0.82 (n25) | 0.868 | 0.815 |
| T22 on (n20) | – | – | 0.442 | **0.508** | 0.442 |

**Findings:**
1. **Rebuild variance is large.** The same corpus and recipe with another seed moves:
   - thinking-off validate by 0.07 (0.861 → 0.789);
   - the gap tests by 0.06;
   - DataIntersection from clean to `$out.1`/`$out.2` in 19/20 T53/T54 answers.

   rb1009's DataIntersection result was a lucky seed. The rb1010a/b DataIntersection drop (§3.26) is variance, not the
   belief traces. Single-run rebuild comparisons below about ±0.06 are not evidence.
2. **The belief traces' effect is real.** Both rb1009 seeds have T40/T42 20/20 and hard set 1 at 64–74%. All three trace
   builds (rb1010a, rb1010b, rb1011) have hard set 1 at 0–1%. T42 and set 2 still vary by run (8–17/20, 38–57%).
3. **The revised Rollup/Normalizer sets show no measurable effect in one run.** T41 0.82 (rb1010a 0.845), T60 off 0.52,
   hard set 3 mistakes 22/80.
4. **Stage 3 on rb1011 (s3b-rb1011) is the best model so far** on the belief and on DataIntersection:
   - **Belief:** T40 0/20 and T42 1/20, the first model with T42 near 0. Hard sets 1–3 are clean.
   - **DataIntersection:** T53 1.00 in both modes from rb1011's 0.58 / 0.78. OPCD with the DataIntersection prompts makes
     T53 reliable even when the rebuild did not learn it.
   - **Other tests:**
     - thinking-on generate 0.979 and validate 0.853, the best so far;
     - T41 0.868 and T22 0.508 (n20), the best of the OPCD models;
     - T60 off keeps the base's 0.51 (c13c lost it: 0.38).
5. **Its costs against c13c:**
   - G4 0.582 vs 0.649;
   - T54 off 0.63 vs 0.97, inherited from rb1011 (0.59);
   - thinking-on fix 0.798 vs 0.826;
   - thinking-off validate WRONG 7.7% vs 6.6%.

   The fix and validate differences are within run variance.
6. **Hard set 3 and rulev7 in stage 3b barely help Rollup** (22 → 18 of 80 accumulator mistakes; c13d got 9 on rb1009).
   All remaining mistakes are one kind: an uninitialized nullable accumulator field (18/40). The 5-sample T41 of 0.95
   was luck; at n20 it is 0.868, against rb1009's 0.988.

~~Ship candidate: s3b-rb1011, replacing c13c.~~ **Withdrawn 2026-10-21** after an independent review of the raw results
(below). c13c remains the candidate until the step-2 confirmations are in.

#### Review correction, 2026-10-21

An independent review re-read the raw results. Its conclusions, spot-checked (T54 and T40 answers re-read):
- **Within noise, though counted above as wins or costs:**
  - thinking-on generate and validate;
  - T41 (0.868 vs 0.815, n20) and T60 off (CI −0.04 to +0.30);
  - G4 (−0.067, CI −0.165 to +0.041, n30).
- **Real wins for s3b:**
  - T42: 3/25 below full vs 11/25, but 10 of c13c's 11 are harmless extra null guards;
  - thinking-off validate +0.016 (CI +0.002 to +0.031).
- **Real losses for s3b:**
  - **T54:** `$out.1`/`$out.2` in 10/10 thinking-off and 7/10 thinking-on answers (c13c 0/10 and 3/10). The graph fails at
    init, yet the rubric still scores these answers 0.55–0.63. The `$out.0` rule was learned in T53's framing only.
  - **T40:** compile errors such as `lastOrderDate = 0`. Pooled 4/25 below full vs 1/25; the single n20 gate run had 0/20.
    The project's own rule asks for 2 × n20.
  - **The 11 suite-v5 gap tests thinking on** (T53/T54 included): −0.029.
- **Measure:** finding 4's "gap tests" use 9 tests and leave out T53/T54. With all 11, c13c leads in both modes.
- **The T41 drop is the belief fix overgeneralizing:**
  - Bases without belief training get T41.B2 WRONG in 0–3/25 samples.
  - Every belief-trained model gets 8–17/25, whether the training came through SFT traces or OPCD.
  - T22 thinking-off "starts at zero" claims grow with belief dose: rb1009s2 6/45, s3b 37/45.
  - §3.25 called it OPCD drift; that was wrong.
- **Hard set 3 by error direction** (part B accumulator prompts, k4; nullable-field errors are mostly "starts at zero"):

  | model | nullable field wrong | (held out) | non-nullable wrong ("null") | metadata default wrong |
  |---|---|---|---|---|
  | rb1009 | 12/40 | 2/8 | 6/20 | 4/20 |
  | rb1009s2 | 13/40 | 1/8 | 8/20 | 7/20 |
  | rb1011 | 14/40 | 0/8 | 3/20 | 5/20 |
  | c13c | 14/40 | 0/8 | 2/20 | 4/20 |
  | c13d | **8/40** | 0/8 | 0/20 | 1/20 |
  | s3b-rb1011 | **18/40** | 2/8 | 0/20 | 0/20 |

  - Belief training removes the "non-nullable starts null" errors and adds "nullable starts at zero" ones. The single
    mistake count hid that the errors changed direction.
  - c13d (rulev7 on rb1009) is the only run that cut the nullable errors. s3b, with the same set and teacher on a
    trace-trained base at belief anchor 0.85, did not.
- **The variance estimate is weak.**
  - The "±0.06–0.07" rests on one pair of seeds, and most of the validate gap is one test (T38, 1.00 → 0.00).
  - The claim that the rb1010a/b DataIntersection drop is pure variance is overstated: 1 of 2 trace-free seeds was
    clean, against 0 of 3 trace builds.
- **Validate WRONG is dominated by two tests.**
  - Excluding T18 and T22, thinking-off WRONG is 1.7% for s3b and 2.2% for c13c.
  - T22 WRONG findings: s3b 43/135 vs c13c 28/135.
- **T18 rubric** (owner ruling 2026-10-21, §7): any explicit lookup-miss handling now counts. All stored T18 answers were
  re-judged (n45 off and n5 on per model). Thinking-off validate, 9 reps:

  | model | T18 old → new | validate off old → new | WRONG old → new |
  |---|---|---|---|
  | rb1009 | 0.551 → 0.767 | 0.861 → 0.878 | 5.7% → 4.3% |
  | rb1009s2 | 0.633 → 0.689 | 0.789 → 0.793 | 7.3% → 7.0% |
  | rb1010a | 0.551 → 0.622 | 0.878 → 0.884 | 5.4% → 4.9% |
  | rb1011 | 0.533 → 0.900 | 0.891 → **0.919** | 6.5% → **4.1%** |
  | c10 | 0.644 → 0.922 | 0.872 → 0.893 | 6.8% → 5.0% |
  | c13c | 0.589 → 0.789 | 0.853 → 0.869 | 6.6% → 5.3% |
  | c13d | 0.589 → 0.778 | 0.858 → 0.873 | 6.4% → 5.1% |
  | s3b-rb1011 | 0.511 → 0.811 | 0.869 → 0.892 | 7.7% → 5.8% |

  Thinking-on changes are within the re-judge noise (n5).

**Step-2 confirmations (2026-10-21, n20 each, fresh runs; pooled with the earlier runs where noted):**

| test | c13c | s3b-rb1011 |
|---|---|---|
| T54 thinking off | **0.983**, 3/20 below full, `$out.1`/`$out.2` 0/20 | 0.600, 20/20 below full, `$out.1`/`$out.2` **20/20** |
| T54 thinking on | 0.935, 4/20 below full | 0.904, 5/20 below full |
| T40 on (pooled n45) | **0.976**, 2/45 below full | 0.899, 10/45 below full |
| T43 on (pooled n25) | **0.870**, 11/25 below full | 0.684, 21/25 below full |

- **T40:** s3b's failures are compile errors that fail the hard gate: a long or integer assigned to a date in `clean()`,
  and a kept `list.contains()`.
- **T43:** c13c's failures are explanation errors, such as an invented `equals(a, b)`, with correct code.
- **Decision: c13c stays the ship candidate.** s3b-rb1011 loses on the runtime-relevant tests (T54 thinking off, T40, T43)
  and wins only on T42's cosmetic guards and thinking-off validate.
- Then the agentic harness, an accumulator-contrast OPCD with a low belief anchor and T54-framed DataIntersection
  prompts, and execution-based scoring of the v5 generate tests.

**Open:**
- T41/T22: the accumulator nullability explanation is still not learned through the corpus or OPCD.
- T54 and G4 lost ground against c13c.
- T60 off: unchanged (0.51).
- Any further single-seed rebuild comparison needs either a second seed or a larger effect than ±0.06.


### 3.28 Execution-based scoring of generate answers, and OPCD c14 (Rollup accumulator set): c13c stays

#### Execution scoring

**Method.** `data/suite_v5/exec_score.py` scores the 11 suite-v5 gap tests by running the code:
- It puts each stored answer's CTL into the test's acceptance graph (`data/suite_v5/run_graphs/`) in place of the
  reference.
- It runs the graph on the CloverDX server (MiscExamples, `suite_v5/exec/`) and compares every output row with the
  fixture.
- A test with variants passes only if all variants pass.
- Statuses: `pass`, `wrong_rows`, `runtime_error`, `init_error` (the CTL does not compile when the component starts,
  e.g. `$out.1` on an unconnected port), `invalid`, `no_code`.

Results are in `results/exec/exec_scores.json`. 1,980 answers were scored: 9 models × 2 modes × 11 tests × n10, plus the
step-2 T54 runs.

**Spot checks.** I re-read the failures; all were real model errors:
- invented functions (`sendPort`, `date2year`);
- wrong `isDate` arguments and syntax errors;
- `$out.1` in DataIntersection;
- wrong duplicate classification (T57).

| model | pass rate off (judge mean) | pass rate on (judge mean) |
|---|---|---|
| **c13c** | **0.44** (0.77) | **0.78** (0.92) |
| c14 | 0.40 (0.76) | 0.75 (0.91) |
| c13d | 0.35 (0.78) | 0.76 (0.92) |
| s3b-rb1011 | 0.30 (0.75) | 0.65 (0.89) |
| rb1009s2 | 0.23 (0.72) | 0.52 (0.85) |
| rb1009 | 0.19 (0.72) | 0.49 (0.84) |
| rb1010a | 0.19 (0.68) | 0.58 (0.85) |
| rb1011 | 0.15 (0.69) | 0.58 (0.85) |
| c10 | 0.10 (0.65) | 0.53 (0.79) |

(n110 per cell; standard error about ±0.045.)

1. **The judge's partial credit hides failing code.**
   - 151 answers scored 0.9 or higher by the judge fail on the server: 73 `init_error`, 60 `wrong_rows`, 16
     `runtime_error`, 2 `invalid`.
   - The reverse (an answer that passes but scores below 0.6) happened once.
   - Judge means compress the differences: 0.65–0.78 off against pass rates of 0.10–0.44.
2. **OPCD adds a lot of working code.**
   - Thinking on, the rebuilds reach 0.49–0.58 and the c13 line 0.76–0.78.
   - Thinking off, c13c reaches 0.44, against the rebuilds' 0.15–0.23.
3. **Thinking-off generate is the largest real gap.**
   - Even c13c passes only 44% of thinking-off answers.
   - T61 and T63 pass in 0/10 thinking-off answers for every model, but in 6–9/10 thinking-on answers for the c13 line,
     so the fixtures are passable.
   - T57 is low in both modes for all models (0–6/10).
4. **The ranking agrees with the n20 confirmations of §3.27:** c13c > c13d ≈ c14 > s3b-rb1011 > the plain rebuilds.

**Use:** from now on, report the execution pass rate as the primary generate measure for the gap tests, next to the
judge.

#### OPCD c14

**Setup** (`configs/opcd_c14.yaml`): c13c continued on rb1009 for 16 rounds. It uses c13d's mix plus the revised Rollup
accumulator set (`data/opcd/build_c14.py`): 40 SFT and 30 DPO prompts, 10 SFT prompts held out, in both thinking modes.
- **Thinking-on samples** are scored by rulev7. Its accumulator-default wording was corrected beforehand (§7, 2026-10-22).
- **Thinking-off samples** are scored by plain rb1009 with the adapter off. A thinking-off teacher check (n20) showed why:

  | thinking off, n20 | T41 mean | T41.B2 WRONG | T22.B1 caught |
  |---|---|---|---|
  | rulev7 | 0.767 | 2 | **1** |
  | plain rb1009 | 0.688 | 1 | **11** |
  | c13c | 0.588 | **15** | – |

  Thinking off, the rule text suppresses the T22 finding (null `acc.count`); plain rb1009 has neither problem.
- **Belief share:** 55% of the non-replay prompt weight.

| measure | c13c | c14 |
|---|---|---|
| hard set 3: nullable field wrong / non-nullable wrong / metadata default wrong | 14/40, 2/20, 4/20 | **9/40, 0/20, 1/20** |
| T41.B2 WRONG, thinking off / on (n20) | 15 / 12 | **10 / 9** |
| T41 mean off / on (n20) | 0.588 / 0.815 | 0.595 / 0.843 |
| T22 mean off / on (n20) | 0.079 / **0.442** | 0.092 / 0.300 |
| T40 / T42 below full | 1/20 / 7/20 | 1/40 / 11/40 (2 × n20) |
| T54 thinking off (n20) | 0.983 | 0.975 (`$out.1` 0/20) |
| 11 gap tests off / on (n10) | 0.773 / 0.915 | 0.761 / 0.907 |
| gap holdouts off / on; G4 | 0.577 / 0.770; 0.649 | 0.541 / **0.822**; 0.605 |
| validate off ×9 (T18 re-judged); WRONG excluding T18/T22 | 0.869; 2.2% | 0.862; 2.7% |
| on: validate / fix / generate (n5) | **0.850** / 0.826 / 0.970 | 0.791 / 0.854 / 0.983 |
| execution pass rate off / on | **0.44 / 0.78** | 0.40 / 0.75 |
| hard sets 1 / 2, belief claims | 0/160, 0/60 | 0/160, 2/60 |

**Read:**
- c14 cuts the wrong accumulator explanations everywhere they are measured: hard set 3, and T41.B2 in both modes.
- The test scores do not follow. T41 is unchanged within noise, and T22 thinking on drops from 0.44 to 0.30.
- T22's main failure is not a belief: no model notices that the two required lifecycle functions are missing (B4/B5
  missed in nearly every sample).
- Thinking-on validate is 0.06 lower in the n5 full-suite run.
- **c13c stays the ship candidate.** More distillation toward the accumulator rule has diminishing returns.

**Next:**
- Run c13c in the agentic harness.
- Use execution scoring as the generate measure.
- Thinking-off generate is the main gap: T57, T60, T61 and T63.
- T22 needs validate examples where `finishGroup` or `updateTransform` is missing, not more rule distillation.


### 3.29 Compile-and-retry, the causes of non-compiling code, and the Rollup lifecycle facts

#### Compile-and-retry (c13c, 2026-10-22)

**Method** (`data/suite_v5/exec_retry.py`):
- Take every stored c13c gap-test answer that failed with an error an agent would see: `init_error`, `runtime_error` or
  `invalid`. `wrong_rows` failures need the expected output, so they are left out.
- Send the server's full error message back as the next user turn, in the same thinking mode with the same system
  prompt, and execution-score the corrected code.
- Repeat for up to 2 rounds.

Results: `results/exec/retry_c13c.json`.

| | retried | compile after retry | fully correct | pass rate (n110) |
|---|---|---|---|---|
| **thinking on** | 19 | 17 | **16** (14 after 1 round) | **0.78 → 0.93** |
| thinking off | 36 | 26 | 8 | 0.44 → 0.51 |

- **Thinking on:** a run-and-read-the-error loop recovers almost every compile failure. Thinking on plus retry is the
  configuration to test in the agentic harness; it needs no training.
- **Thinking off:** retries mostly turn compile errors into wrong rows (18/36). The non-compiling code was usually wrong
  in its logic too.
- **One misleading message:** T63's error says "Syntax error on token 'integer'". It does not tell the model that `month`
  is a reserved word, so the retry cannot fix it (9 of the 10 that still fail to compile).

#### Why generate code does not compile (all 9 models, 706 `init_error` answers, §3.28 data)

630 of the 706 (89%) fall into 11 causes. Each rule was confirmed with `ctl_validate` on 2026-10-22:

| cause | answers | correct form |
|---|---|---|
| DataIntersection writes `$out.1`/`$out.2` | 213 | `$out.0` only (§7) |
| field not in the given metadata (e.g. `acc.receipt_id` in T57, `acc.first_audit_required` in T63) | 76 | use declared fields only |
| regex negation `x !~ "re"` (no such operator) or `!x ~= "re"` (`!` binds to the string) | 74 | `!(x ~= "re")` |
| time-unit keyword as a variable name: `month`, `year`, `week`, `day`, `hour`, `second` (reserved) | 74 | another name (`mon` compiles) |
| invented functions: `raise`, `sendPort`, `getDictionaryValue`, `date2year` | 70 | `raiseError("…")`, documented functions |
| `str2date`/`isDate(s, fmt, strict, tz)` | 43 | `(s, fmt, locale, tz, strict)` or `(s, fmt, strict)` |
| undeclared variable | 27 | – |
| `"\."` in a string literal (invalid escape) | 16 | `"\\."` |
| `ALL` (or another return constant) as a ternary operand: `return b ? ALL : 1;` | 15 | `if`/`else`; `b ? 0 : 1` compiles |
| other wrong arguments | 9 | – |
| dictionary access `dictionary.X.Y` (nonexistent entries) | 9 | – |

`ctl2-basics.md` covered the function signatures but not the reserved time-unit names, return constants in a ternary,
`!~`, or string escaping in regexes. These four are added to the reference and §7.

#### Rollup lifecycle (live probe, 2026-10-22)

The T57 reference was run with lifecycle functions removed:
- the full reference passes (run 21964);
- with `finishGroup`, `updateTransform`, both of them, or `initGroup` removed, the component **fails at initialization**:
  "Required function(s) finishGroup(), updateTransform() are missing!" (runs 21965–21968).

A missing function does not make the group silently emit nothing. The rubric text of T6.7 and T22.B5 said it did; it was
corrected (scoring unchanged).

**Briefs written:**
- `spec/rollup_lifecycle_validate_brief.md` (T22: missing lifecycle functions in validate, thinking off);
- `spec/ctl2_syntax_pitfalls_brief.md` (the compile causes above).

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

### 4.7 Evaluating on vLLM, and the real noise floor

> **Added 2026-10-12.**

**`test.py` has a vLLM mode** (`mut.mode: vllm`, `vllm_url`, `vllm_model`, `run_label`) and
`--workers N`.
- The prompt is built by `test.py`'s own tokenizer path (LlamaFactory `qwen3_8` template, thinking
  flag, `reasoning_effort`) and sent as token ids to `/v1/completions`. vLLM's chat template never
  applies.
- `vllm_model` selects the base model or a LoRA adapter hot-loaded by name, so no export is needed.
- Server: `scripts/vllm_eval_serve.sh` (port 3012). Configs: `configs/eval_rb1006_vllm_{on,off}.yaml`,
  `configs/eval_vllm_opcd*`.

**Speed, at 32 workers:**

| run | HF | vLLM |
|---|---|---|
| full suite, thinking on (215 runs) | 3.9 h | **9 min** |
| full suite, thinking off | 1.5 h | 3 min |
| validate thinking-off rep | 20 min | < 1 min |

HF ran one generation at a time at about 21 tokens/s; vLLM sustains about 470 tokens/s at 32
concurrent requests.

**Parity with HF on rb1006:**
- Per-token log-probs agree to about 0.001.
- Generate, validate and fix agree within noise.
- T40/T42 agree, and the median thinking length is the same (295 vs 292 words).
- Only the sampling RNG differs.

**The noise floor was underestimated.** Validate thinking off for rb1006, 9 vLLM reps:
- score 0.886 ± 0.012;
- **WRONG 7.5% ± 1.3%**, range 5.9–9.8%.

The 4.5% baseline used as the WRONG ≤ 5% gate came from 3 HF reps (3.2%, 6.5%, 3.9%) and was low.
Several thinking-off "regressions" in §3.19 (c3 8.4%, c4 7.4%) were mostly that.

Other single-run figures are also noisy:
- T42 at n20 gave 12/20 on HF and 4/20 on vLLM for the same model (c4).
- T33 gave 0.93 on HF and 0.73 on vLLM for rb1006.

**Rules:**
- Thinking-off validate: 9 reps (9 min on vLLM).
- T40/T42: at least 2 × n20 before a gate decision.
- Compare models only on the same path, HF or vLLM.
- Re-judge judge parse failures, which score 0 (`data/rejudge_results.py --only-failed`).

The ctl_validate compile check needs the local CloverDX Server (`~/cloverserver/…/bin/startup.sh`,
port 8083). It does not restart after a reboot, and the self-distill filter then logs "exit 0"
without judging anything, so check the judged count.

---

## 5. Recommended pipeline

> **Rewritten 2026-10-12.** The current model is **rb1006 + the OPCD c4 adapter** (§3.16, §3.19). The
> three-phase recipe this section described until then is retired; it is kept at the end of this
> section for the record.

### Step 1 — build the training data

```bash
cd ~/llama_train && PYTHONPATH=~/LlamaFactory/src ~/venv/bin/python data/build_sft_rebuild.py rb1006 data/sft_rebuild_20261006
```

`data/build_sft_rebuild.py` (header: the exact composition) writes four files and a `build_report.json`.

**SFT:**
- every answer-only record in `ctl_lora_training/sft_training_data/` (12,059 at corpus `a4d8274`);
- plus the model's own self-distilled thinking traces, **each twice** (464 kept; §3.18).

**DPO:** all `CTL_LoRA_DPO_*.jsonl` pairs (1,953).

**Prerequisites:**
- The trace inputs, `data/self_distill/{full1,gen2full}/selfdistill_*_train.json` (4.2 MB), are in git,
  so the build can run on another machine.
- Register the files in `~/LlamaFactory/data/dataset_info.json` and copy them to
  `~/LlamaFactory/data/`. The JSON carries git `skip-worktree`.
- Run the pre-flight (§5.1) first.

### Step 2 — SFT + DPO (rb1006)

```bash
cd ~/LlamaFactory && CUDA_VISIBLE_DEVICES=0 ~/venv/bin/python ~/llama_train/train.py ~/llama_train/configs/qwen38_rb1006.yaml --skip-post-sft
```

**SFT, mixed thinking:**
- `enable_thinking: null`: the traces are trained, and answer-only records get the empty
  thinking block;
- cutoff 4096, lr 5e-5 (cosine with 2 restarts), 2 epochs;
- batch 2 × accum 6;
- rank 64 / alpha 64, loraplus 2.

**DPO, thinking off:**
- lr 5e-6, 1 epoch, batch 1 × accum 4;
- pref_beta 0.1, pref_ftx 0.1.

The config exports to `export_dir`. **Always pass `--skip-post-sft`.** The config still carries the
retired phase-3 block (`post_dpo_sft`); without the flag it would run.

### Step 3 — on-policy context distillation (c4)

Run it from the rb1006 export. The teacher is the same weights with the rule v3 prompt
(`configs/eval_rb1006_rulev3_{on,off}.yaml`); the prompt sets are in `data/opcd/`.

```bash
scripts/opcd_run.sh <run> <train GPU> <last round>
```

`scripts/opcd_run.sh` needs:
- the sampler, `logs/evals/opcd_vllm_serve.sh`, on port 3011;
- the eval server, `scripts/vllm_eval_serve.sh`, on port 3012.

There are two ways to get the c4 adapter:
- **Reproduce c4 exactly:** chain `configs/opcd_c2.yaml` → `opcd_c3` → `opcd_c4`. Each config's
  `init_adapter` names the previous run's final round.
- **One run, tested equivalent** (§3.19, finding 7): a fresh-adapter config like `opcd_c7.yaml`.
  c7 itself also has the rule v4 teacher on Rollup prompts. That gave the best fix score, at −0.026
  thinking-off validate.

`opcd.py export --round N` merges an adapter into a full model for HF. vLLM serves the adapter
directly.

**Optional step 3b — c9** (§3.21): continue from c4 with `configs/opcd_c9.yaml` (component-guide teachers for the
generate gaps; `scripts/opcd_c9_run.sh`). It improves thinking-off generation and keeps every c4 gate, but costs
thinking-on SCD answers; whether it replaces c4 is open (§6).

**Step 3 on a new base — the canonical stage** (spec/belief_durability_plan.md A1/A2, from c13 → c13c, §3.25):

```bash
setsid nohup scripts/opcd_stage3.sh <base export> <tag> > logs/evals/stage3_<tag>.log 2>&1 &
```

- It generates `configs/opcd_s3a-<tag>.yaml` and `opcd_s3b-<tag>.yaml` from the templates `configs/opcd_stage3{a,b}.yaml`:
  - stage 3a: c13's mix with the rulev6 teacher, 40 rounds;
  - stage 3b: the belief-focused c13c mix, 16 rounds.
- It checks the belief anchor: belief prompts must be at least 30% of the non-replay prompt weight (rb1009: 0.50 and
  0.82).
- It trains both stages and runs the gates. `--dry-run` writes, prepares and checks without GPU work.
- Since 2026-10-19 stage 3b also trains hard set 3 and scores thinking-on Rollup prompts with rulev7 (as c13d). On
  rb1011 this produced the ship candidate s3b-rb1011 (§3.27); belief anchors 0.50 and 0.85.
- **Anchor rule for any OPCD run:** keep the belief prompts at least 30% of the non-replay pool, scored by rulev6, with
  T40/T42 n20 and hard sets 1–3 as gates. c11–c13 regressed when new groups crowded them out.

**Step 3c — c10** (§3.22), the recommended ship candidate: `configs/opcd_c10.yaml`, c9's recipe with
`train.skip_truncated: ["on"]`, via `scripts/opcd_gaps_run.sh c10`. It keeps c9's thinking-off gain without the
thinking-on cost.

### Step 4 — evaluate

- Use the vLLM path (§4.7): `test.py` `mut.mode: vllm`, `--workers 32`.
- Thinking-on full suite n5, thinking-off full suite n5, and **thinking-off validate 9 reps**.
- T40/T42 at n20, at least twice before a gate decision.
- The hard-case sets: `data/opcd/eval_hard_cases.py`.
- Real-world generate (suite v5, §3.20): `scripts/suite_v5_rw_run.sh ROUND`; for a model comparison, n10 on the
  21 discriminating tests (`TESTS=… RUNS=10`).
- **Execution scoring** of suite-v5 generate answers (§3.28): `python data/suite_v5/exec_score.py <results files>`, which
  needs the CloverDX server on :8083. Report its pass rate next to the judge score. Rank generate on the pass rate,
  because generate rubrics give partial credit to code that cannot run.
- Hard-set-3 accumulator errors: report them split by direction (nullable said to start at zero vs non-nullable said
  to start null; §3.27).
- Compare only within one path (HF or vLLM) and one judge (§4.6).

**Deploy routed by task:**

| task | thinking |
|---|---|
| validate | off |
| fix | on |
| generate | on (execution pass rate 0.78 on vs 0.44 off for c13c, §3.28) |

### The retired three-phase recipe (§1–§3.15), for the record

Phase 1 was SFT with thinking off on `clover_ctl_trainign_data`. Phase 2 was DPO with thinking off.
Phase 3 was SFT with thinking on, on the **authored** reasoning traces (`clover_ctl_think_data`), via
`configs/qwen38.yaml`.

It was retired for three reasons:
- **Phase 3 costs accuracy on every axis** (§3.12). The authored traces replaced the model's own
  reasoning style (§3.13).
- **Without phase 3, thinking-off SFT erodes the `</think>` boundary** (§3.4, §3.18 rb1003).
- **Mixed-thinking SFT with the model's own traces** keeps thinking intact without a phase 3
  (rb1005/rb1006).

The old guidance "do not skip phase 3" applied only within that recipe. Don't use
`configs/qwen38.yaml` for new models.

### 5.1 Corpus pre-flight — run before every training run

Two hours of GPU time is worth two minutes of checking. This caught 35 conflicting-answer
prompts on 2026-09-24, the same class of defect that cost 0.027 suite in §2 at 115 prompts.

> **Rewritten 2026-10-12 for the current build** (`data/build_sft_rebuild.py`, one mixed SFT file). The
> checks for the retired phase-1 and think files are gone with that recipe.

```python
import json, collections, re
TAG, D = 'rb1006', 'data/sft_rebuild_20261006'          # what build_sft_rebuild.py wrote
THINK = re.compile(r'^<think>\n.*?\n</think>\n\n', re.S)
user = lambda e: next(m['content'] for m in e['messages'] if m['role']=='user').strip()
raw  = lambda e: ''.join(m.get('content','') for m in e['messages'] if m['role']=='assistant')
bare = lambda e: THINK.sub('', raw(e)).strip()

T  = json.load(open(f'{D}/CTL_LoRA_training_data_{TAG}.json'))
E  = json.load(open(f'{D}/CTL_LoRA_eval_data_{TAG}.json'))
sd = [e for e in T if str(e.get('source_file', '')).startswith('self_distill')]   # own traces (x2)
an = [e for e in T if e not in sd]                                                 # answer-only corpus
print('answer-only', len(an), ' traces', len(sd))

tu = collections.defaultdict(set)
for e in an: tu[user(e)].add(bare(e))
print('answer-only prompts with conflicting answers (want 0):', sum(1 for a in tu.values() if len(a) > 1))
print('answer-only records carrying <think> (want 0):', sum(1 for e in an if '<think>' in raw(e)))
print('traces without a closed think block (want 0):',
      sum(1 for e in sd if not THINK.match(raw(e))))
print('traces worded differently from the corpus answer (info; rb1006: 624 of 928):',
      sum(1 for e in sd if user(e) in tu and bare(e) not in tu[user(e)]))
trp = {user(e) for e in T}
print('eval contamination (want 0):', sum(1 for e in E if user(e) in trp))
print('orig_reasoning_content leaked (want 0):',
      sum(1 for e in T for m in e['messages'] if 'orig_reasoning_content' in m or 'reasoning_content' in m))
```

A trace answer that differs from the corpus answer for the same prompt is not automatically wrong.
Traces are the model's own accepted answers, so their wording differs. But a different *verdict* or
fix is a conflict to resolve before training (§2: 115 conflicting prompts cost 0.027).

### Operational notes

- **Preserve exports before retraining.** `export_dir` is fixed and each run overwrites the
  last. Two models were lost this way, one of them the then-best. Rename first.
- **One GPU needs no config change.** With `world_size=1` the effective batch is
  `per_device × accum`, which `configs/qwen38.yaml` already sets to 12/12/4 for the three
  phases — what 0917, fix1 and fix2 all used. Do not "correct" it upward.
- `reasoning_effort: medium` must match between the training and eval configs.
- `test.py` needs `OPENAI_API_KEY` from `~/.bash_profile` — login-shell only. Source it
  explicitly in non-interactive shells or every judge call 401s.
- **causal-conv1d** in `~/venv` is a source build patched to sm_120 only. No wheel exists for torch
  2.11, and the stock `setup.py` ignores `TORCH_CUDA_ARCH_LIST`. A torch upgrade breaks it; rebuild the
  same way. The gain is small (about 7% faster prefill), and the "fast path is not available" warning
  is misleading.
- **The CloverDX server** (ctl_validate MCP, port 8083) does not restart after a reboot: run
  `~/cloverserver/…/bin/startup.sh`.
- **Launch long jobs** through `#!/bin/bash -l` scripts with `setsid nohup`. The tool shell lacks
  `OPENAI_API_KEY` and wandb.
- `llamafactory-cli` lives in `~/venv/bin` and is **not** on the default PATH; `train.py`
  invokes it by bare name, so export the path first or the SFT phase dies instantly with
  `FileNotFoundError`.

---

## 6. Open questions, in priority order

> **2026-10-22 (evening) — current front (§3.29).**
>
> AA. **Deploy configuration to test in the agentic harness:** c13c, thinking on, compile-and-run retry (0.93 on the gap
>     tests).
>
> AB. **Syntax pitfalls corpus set** (`spec/ctl2_syntax_pitfalls_brief.md`) and the Rollup lifecycle validate set
>     (`spec/rollup_lifecycle_validate_brief.md`), for the next rebuild.

> **2026-10-22 — front (§3.28).**
>
> W. **Ship candidate c13c**, confirmed by execution scoring. Next: the agentic harness.
>
> X. **Thinking-off generate** is the largest real gap: c13c passes 44% of answers when run. T57, T60, T61 and T63 are
>    near 0 thinking off.
>
> Y. **T22:** the missed lifecycle functions (B4/B5), not the belief. It needs validate examples, not rule distillation.
>
> Z. **Measurement:** report execution pass rates (`data/suite_v5/exec_score.py`) for generate. Generate rubrics give
>    partial credit to code that cannot run.

> **2026-10-20 front (§3.27).**
>
> S. **Ship candidate: c13c** (confirmed 2026-10-21, §3.27). s3b-rb1011 loses T54 thinking off (20/20 `$out.1`), T40
>    (compile errors 10/45 vs 2/45) and T43 (0.68 vs 0.87). Next: the agentic harness.
>
> T. **Rollup accumulator nullability (T41/T22, hard set 3 part B):** the belief fix overgeneralizes to "nullable
>    accumulator starts at zero". Next: an OPCD run with accumulator contrast prompts, thinking-off Rollup validate prompts
>    scored by rulev7, and a much lower belief anchor on trace-trained bases.
>
> U. **T54:** `$out.1` in T54's framing ("emit on the matched stream"); add T54-framed DataIntersection prompts to OPCD.
>    G4 is noise.
>
> V. **Rebuild variance:** compare rebuilds only with two seeds or effects above ±0.06.

> **2026-10-17 front (§3.25).**
>
> M. ~~T42~~ **Done (c13c, rulev6 teacher): T42 trap 6/20, T40 + T42 8/40 as c10.** Was: the rulev3 teacher fails it in 10/20. Test a rule addition for carried-over values
>    (teacher check on T42/T40 and hard set 2), then a short targeted run from c13b with that teacher on the set-2
>    prompts only.
>
> N. **Ship candidate: c13c** (recommended; owner decision open). Next: test it in the real agentic harness.
>
> P. ~~T41 via OPCD~~ **Tried in c13d: 0.815 → 0.840, n.s.** Moved to the corpus, together with the T60 multi-branch
>    Normalizer counts: `spec/rollup_normalizer_corpus_brief.md`.
>
> R. **Part B result (§3.26):** the corpus carries the belief fix (rb1010a). DataIntersection regressed; an rb1009 seed
>    rerun measures rebuild variance before rb1010a is adopted as the next base.
>
> Q. **Belief durability across rebuilds:** `spec/belief_durability_plan.md` covers it (canonical stage-3 configs and
>    self-distilled c13c traces in the next rebuild).
>
> O. **T60 thinking off** dropped in c13/c13b (0.71 → 0.35). Investigate before the next run.

> **2026-10-16 front (§3.24).**
>
> L. **c13 on rb1009:** c4 + c10 + DI in one fresh adapter. If it keeps rb1009's T53 gain, restores c4's belief gates
>    and c10's gap gains, it replaces c10 as the ship candidate.

> **2026-10-15 front (§3.22).**
>
> F. **Adopt c10?** It is the recommended ship candidate (best thinking-on and fix, thinking-off gains kept); c9 is superseded and c11 is not adopted. Owner decision open.
>
> I. ~~DataIntersection via OPCD~~ **Tried in c12 (§3.23): the rule does not transfer.** Decision: base rebuild first
>    (K), then T53/T54 + DI holdouts on the new base. Was: rerun the teacher check on the revised, unhinted DI prompts (ctl_lora_training `d80aaa5`).
>    If the teacher still beats c10 there, rebuild the DI group from c10 and gate on T53/T54 (n10, both modes), not on
>    same-set holdouts.
>
> J. **SCD (G4, T60/T61):** two OPCD groups have each cost thinking-on SCD answers through longer thinking. Options:
>    - train SCD prompts thinking-off only;
>    - a teacher without the worked example;
>    - a length guard;
>    - rely on the SCD-2 SFT/DPO set in the next base rebuild.
>
> K. ~~Fold c10 into the next base rebuild~~ **Done as rb1009 (§3.24) + c13.**

> **2026-10-14 front (§3.21).**
>
> F. **Adopt c9?** It wins thinking-off generate (suite v5 gap tests 0.574 → 0.691) and passes every c4 gate, but loses
>    −0.19 on thinking-on SCD (G4) answers. Options: adopt c9 as is (generate thinking off, or accept the SCD cost); or
>    run c10 = c9's recipe with G4 trained thinking-off only and a higher sampling cap, then decide.
>
> G. **G2 (Rollup per-record + group emit) and G5 (multi-check validation without thinking)** are not knowledge gaps,
>    so a guide teacher does not help. Candidate: distil c4's own correct thinking-on answers into thinking-off answers.
>
> H. **The gap prompt set still has 2–4 solution skeletons per gap** (§3.21). A more varied set (fewer, individually
>    written prompts) may transfer better; measure on the suite, not on the training prompts.

> **2026-10-13 front (§3.20).**
>
> A. ~~Ship decision c4 or c7~~ **Decided: c4** (owner, 2026-10-13). Generate does not separate them (§3.20).
>
> E. **The shared generate gaps** (§3.20): dictionary state, Rollup per-record emit, stateful Partition, SCD as a
>    Normalizer, multi-check validation without thinking, UTC business calendars. Plan: on-policy context
>    distillation with the CloverDX component guide and the run-verified facts in the teacher's prompt, on new
>    run-verified generate prompts (`spec/opcd_generate_gaps_brief.md`). DataIntersection already has dedicated SFT
>    and DPO training files.
>
> B–D below still stand.

> **2026-10-12 front (§3.19, §4.7).**
>
> A. **Ship decision:** c4 (best balance) or c7 (best fix and generate, −0.026 thinking-off validate).
>    Both remove the declaration belief. Confirm T42 with 2 × n20 on vLLM before deciding.
>
> B. **The Rollup accumulator facts** (nullable unless marked; reset before each group): OPCD improves them
>    with thinking on and worsens thinking-off T22. Options:
>    - thinking-off DPO built from c6's correct thinking-on Rollup answers;
>    - thinking-on review for Rollup code at inference;
>    - corpus records that state both facts, trained in a normal SFT round.
>
> C. **Retrain rb1006 with the c4 adapter's behaviour folded in** (or merge c4) before any next corpus
>    round, so new SFT data does not undo it.
>
> D. **GRPO** (`spec/grpo_rl_idea.md`) remains the fallback if B needs an on-policy method that can
>    reward a missing finding.
>
> **2026-10-09 front, now resolved:**
> - A: the rule in the system prompt helps with thinking on and primes thinking-off review, so it is
>   not shippable as is (§3.16).
> - B: on-policy context distillation works (§3.19).
> - D: thinking-off WRONG regressions were partly baseline noise (§4.7).
>
> Items below predate both.
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

0. ~~**Retrain without phase 3 (§3.12, §3.13).**~~ **Done (§3.18):** rb1003–rb1005 trained the two-phase
   recipe (SFT + DPO, no phase 3), and rb1005/rb1006 is now the recipe (§5). Thinking survives only
   when the SFT's thinking share is the model's own traces.
1. ~~**Fix-to-spec records — amended, not yet trained (§3.10, §3.11).**~~ **Done:** trained from rb1003
   on. rb1006 added 120 fix-to-spec explained records; fix n=20 went 0.70 → 0.863 under gpt-6-sol,
   0.801 under gpt-6.1-sol (§3.16).
1a. ~~**Self-distilled reasoning (§3.13).**~~ **Done (§3.18):** sd1 gave fix +0.05 as phase 3; scaling
   it (sd2/sd2b) cost fix. The own traces are now the thinking share of the SFT (rb1005, ×2).
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

---

## 7. Owner rulings and compiler-verified CTL2 facts

These settle what the judge, the corpus and the suite rubrics treat as correct. Where a ruling
changed a rubric or reference, that is noted. Rulings are from the project owner; "compiler" means
checked with ctl_validate on CloverDX Server.

| date | topic | ruling |
|---|---|---|
| 2026-10-02 | `STOP` | returning `STOP` aborts the component. In DataGenerator `generate()` it is an ERROR, not normal termination. |
| 2026-10-02 | Denormalizer `transform()` | may read `$in.0`, which is the group's last input record; reading the group key there is valid |
| 2026-10-02 | `*OnError` callbacks | valid optional hooks, but they must log. A silent `SKIP` is tolerated; a silent `OK` is a defect. |
| 2026-10-02 | unassigned output field | a never-assigned **non-nullable** field is emitted as its type's zero value (`""`, `0`), never null; a nullable one is null |
| 2026-10-03 | Rollup `transform()` | may read `$in.0` (e.g. the group key); no saved copy needed. Contracts saying "only in updateGroup" are stale. |
| 2026-10-03 | Denormalizer `append()` writing `$out.0` | benign, no effect; not a runtime error (suite T2 rationale fixed) |
| 2026-10-06, corrected 2026-10-22 | Rollup accumulator | reset from its metadata **before each group**: no default → null if nullable, zero value if not. A metadata default applies to **non-nullable** fields only; a **nullable** field starts null even when its metadata defines a default (live probe by the accumulator-set authors, run 5465; the 10-06 wording "a metadata default is applied" was incomplete). Omitted nullability means nullable. Live-tested; in `ctl2-basics.md` and the rulev7 teacher; T41.B2 depends on it. Hard set 3's metadata-default prompts use non-nullable fields only, so their expected answers stand. |
| live runs, 2026-10-22 | Rollup lifecycle | all five functions (`initGroup`, `updateGroup`, `finishGroup`, `updateTransform`, `transform`) are mandatory; omitting any fails the component at initialization ("Required function(s) … are missing!", runs 21965–21968). The earlier wording "omitting `finishGroup` means the group emits nothing" was wrong. |
| — | Rollup groups | always have ≥ 1 record, so a divide-by-zero guard on the count is a false positive |
| — | declarations | declared variables start at their type default; only `variant`, `byte`, `cbyte` start null (§3.16) |
| — | review severity | **WARNING** = data-dependent runtime risk (a nullable field that may be null). **ERROR** = compile failure, certain runtime failure, or a violation of a stated requirement. |
| — | validate | precision over recall: a correct but incomplete review beats one with misclassified findings; rank models on WRONG, not on the suite score |
| — | objective | generate is the primary objective; validate gains must not cost generate |
| compiler, 2026-10-05 | object notation | `list.length()`, `str.isEmpty()`, `x.in(list)` are valid. `list.contains/indexOf/size`, `.equals`, `equals(a,b)` and an infix `in` are compile errors. |
| compiler | `++` / `--` | work on any writable l-value, including accumulator and internal record fields; only input fields are read-only |
| compiler | conditional fail `a : b : null` | valid in both `//#CTL2` and `//#CTL2:COMPILE` (T5.B5 retired) |
| compiler, 2026-09-29 | writing `$out.1` on an unconnected port | compile error ("Cannot write to output port '1'"), not dead code; two Rollup references were held out for it |
| compiler | EXT_FILTER | `FILTER_EXPR` needs the `//#CTL2` header; `job_validate` ignores params |
| 2026-10-13 | DataIntersection | input 0 = A, input 1 = B; output 0 = A only, 1 = matches, 2 = B only. **CTL writes `$out.0`, which the component sends out on port 1** (corrects the 10-12 note that said `$out.1`; writing `$out.1` fails at init). `OK`/`0`/`1`/`ALL` emit, `SKIP` drops, `STOP` fails; ports 0 and 2 are pass-through. Live runs; `ctl2-basics.md` §8.9. |
| compiler, 2026-10-22 | syntax pitfalls (§3.29) | the date-unit keywords `millisec` … `year` cannot be variable names (`integer month` fails with "Syntax error on token 'integer'"; metadata fields named `month` are fine); return constants (`ALL`, `OK`, `SKIP`) cannot be ternary operands; there is no `!~`, and `!x ~= re` fails, so use `!(x ~= re)`; `"\."` is an invalid escape (use `"\\."` or a single-quoted string); `str2date`/`isDate` take the strict flag last, `(s, fmt, locale, tz, strict)`, never `(s, fmt, strict, tz)`; there is no `raise`, use `raiseError(msg)`. All in `ctl2-basics.md` §2.2, §2.4, §3.2, §3.6, §7. |
| 2026-10-21 | lookup miss handling (suite T18.B2) | any explicit miss handling is correct: fallback defaults, leaving nullable output fields null, `SKIP`, or routing to an error/reject port. The rubric no longer requires defaults; all stored T18 answers were re-judged (§3.27). |
| live runs, 2026-10-13 | runtime behaviour | `str2decimal("")` throws; strict `isDate`/`str2date` reject `2025-02-30` and `2025-1-1` (strict `str2date` throws); date functions without a time zone use the host's; the Rollup emit functions repeat until `SKIP`; `round` rounds halves away from zero; full-outer ExtMergeJoin transforms one-sided records on output 0; lookup duplicates need `keyDuplicates=true`; `RUN_ID` is reserved. All in `ctl2-basics.md` §13.3 with run ids. |
