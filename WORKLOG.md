# Work log

Important progress and decisions, newest first. Details and numbers: `spec/ctl2_training_findings.md` (section in brackets).

## Where we are (2026-10-25)

- **Ship candidate: c13c**, the rb1009 base plus OPCD adapter `data/opcd/c13c/round_015`. Confirmed by 20-sample checks
  and by running the generated code on the server.
- **Deploy with thinking on and a compile-and-retry loop.** In the agentic harness (§3.31) c13c passes 88% of 137
  execution-scored tasks thinking on with error feedback, 92% when the failing test rows are fed back too (28/30 real-world
  suite tests); thinking off 69% / 80%.
- **Biggest real gap:** generate without thinking. Only 44% of c13c's answers run correctly (§3.28).
- **rb1012 not adopted** (§3.30). The two new corpus sets showed no gain in two seeds, and both seeds regressed on the
  Rollup accumulator explanation. Neither set is in the default rebuild recipe. The regression is **not** in the DPO pairs
  (§3.32); it sits in rb1012's SFT phase (the new SFT records, or seed luck).

## 2026-10-26

- **rb1012 DPO isolation:** the accumulator regression is not caused by DPO. (§3.32, `spec/rb1012_dpo_isolation_findings.md`)
  - **Setup:** the DPO phase alone, rerun on rb1011's SFT adapter.
  - **Results:** rb1011's pairs (A) reproduce rb1011: T22 "starts at zero" 19 against 20/45, T41 0.83 against 0.82.
    Adding the 25 lifecycle pairs (B: 15/45, 0.79), or all of rb1012's DPO pairs (C: 18/45, 0.85), does not bring back
    rb1012's 36/45.
  - **Conclusions:**
    - the DPO phase adds little noise;
    - the regression comes from rb1012's SFT phase, either the 130 new SFT records or SFT-seed luck.
  - **Proposed next:** rb1012's SFT adapter plus rb1011's DPO (about 1.3 GPU-h) and an rb1011 seed-7 rebuild (about
    6 GPU-h). These decide whether an SFT ablation (about 24 GPU-h) is needed.
- **The shared run-history log `logs/Qwen3.8-27B.yaml` was torn** by concurrent `train.py`/`test.py` writes on 10-25
  around 21:16. From then on, every run's final log append failed; results were not affected. The log was repaired, and
  a backup kept. Parallel runs will tear it again until the writers take a lock.

## 2026-10-25

- **Agentic harness built** (`agent_harness.py`, from `mut_validate.py` + `exec_retry.py`): prompt → model → compile →
  run → error fed back → retry, verdict by output rows. Pool 1: 137 execution-scored tasks (30 suite v5 + 107 corpus
  prompts c13c never trained on).
- **c13c in the loop:** 0.65 → 0.69 thinking off, 0.82 → 0.88 on, after two feedback rounds. Real-world suite tests:
  13/30 off, 25/30 on. The residue is wrong rows; the compile habit that survives is `month`/`year` as a variable name,
  because the server's message does not name it. DataIntersection: 23/24 first try. With the failing test rows fed back
  as well: 0.80 off / 0.92 on; real-world suite 22/30 off, 28/30 on. (§3.31)
- Briefs written for two experiments to hand to another agent: `spec/exec_rft_pilot_brief.md` (execution-verified
  on-policy training) and `spec/rb1012_dpo_isolation_brief.md` (is the rb1012 regression the DPO pairs?).

## 2026-10-23

- **rb1012** (rb1011 + the lifecycle and syntax sets), two seeds: **not adopted**. (§3.30)
  - **Syntax set:** no measurable effect. Compile failures from the targeted rules were 28–40 against 36, inside seed
    noise; the total swings 71–122 between seeds alone.
  - **Lifecycle set:** no gain. Its premise was wrong: the plain rebuilds already catch T22's missing functions thinking
    off (rb1011 43/40 of 45). The miss is specific to rb1009 and its OPCD line.
  - **Regression in both seeds:** T22 "count starts at zero" 20 → 36/45; T41 0.82 → 0.72–0.76. No cause found in the
    lifecycle set; only an ablation would tell.
  - **Decision:** c13c stays the candidate. Syntax habits are handled by thinking on plus compile-and-retry.
- **zeroDate records added to the corpus** (10 SFT, 6 DPO), written and server-verified here.
  - rb1012s2 wrote the bare `zeroDate` 48 times. The corpus code always uses `zeroDate()`, but never explained it.
  - The reference now says it is a function. (§3.30, §7)

## 2026-10-22

- **Syntax pitfalls set** (80 SFT, 40 DPO) delivered and **accepted** after an independent check:
  - all 185 compiler requests replayed with 0 differences;
  - all 216 runtime graphs re-run with 0 differences.

  Two small fixes were made directly: the PASS format, and a duplicated month computation.
- **Rebuild rb1012 started** with both new sets, in two seeds because single-seed differences below ±0.06 are not
  evidence. The corpus differs from rb1011 only by the two sets (+130 SFT, +65 DPO).
  - **Success:** fewer compile failures by cause in the execution scoring, and T22's missing lifecycle functions found
    thinking off.
  - **Must not regress:** belief gates and thinking-off validate WRONG.
- **New measure: run the generated code.** `data/suite_v5/exec_score.py` runs each answer in its test graph and checks
  every output row.
  - Pass rates are far below judge scores: c13c 0.44 off / 0.78 on, against judge 0.77 / 0.92.
  - 151 answers the judge scored 0.9 or higher do not work.
  - **Decision:** rank generate on this pass rate from now on. (§3.28)
- **OPCD c14** (Rollup accumulator set) fixed some wrong explanations but not the T41/T22 scores. **Decision:** keep
  c13c; stop distilling toward the accumulator rule. (§3.28)
- **Compile-and-retry:** feeding the server error back to c13c gives 0.78 → 0.93 thinking on, 0.44 → 0.51 off. (§3.29)
- **Why code does not compile:** 89% of failures come from 11 causes, each confirmed with the compiler. Examples: `$out.1`
  in DataIntersection, invented fields and functions, `!~`, `month` as a variable name, `str2date` argument order.
  - The rules are now in `ctl2-basics.md` and the corpus reference.
  - Corpus brief written: `spec/ctl2_syntax_pitfalls_brief.md`. (§3.29)
- **Facts corrected** (server-verified):
  - a Rollup accumulator's metadata default applies only to non-nullable fields; a nullable field starts null even with
    a default;
  - a missing Rollup lifecycle function fails the component at startup; it does not silently emit nothing.

  The reference, the teachers, and the T41, T6 and T22 rubrics were updated. (§7)
- **Rollup lifecycle validate set** (for T22): requested, delivered, and fixed over 3 rounds. **Accepted** for the next
  rebuild.

## 2026-10-21

- **An independent review withdrew s3b-rb1011 as candidate.** It breaks T54 without thinking (`$out.1` in 20/20) and
  makes compile errors on T40. Most of its "wins" were noise. **Decision: c13c stays.** (§3.27)
- **Found:** the declaration-belief fix overgeneralizes. Models learn "nothing is null" and then misexplain nullable Rollup
  accumulator fields (T41, T22). (§3.27)
- **Your ruling on T18:** any explicit lookup-miss handling counts (SKIP, null, defaults, reject port). All stored answers
  were re-judged. (§7)

## 2026-10-19 / 20

- **Rebuild variance is large.** Retraining rb1009 with another seed moved validate by 0.07 and lost DataIntersection.
  rb1009's DataIntersection result was a lucky seed. Single-seed rebuild comparisons below about ±0.06 are not evidence.
  (§3.27)
- **rb1011** (rb1010a plus the revised Rollup/Normalizer sets): no measurable effect from the new sets.
- **Stage 3 OPCD on rb1011 (s3b-rb1011)** was first called the new candidate, then withdrawn on 10-21.

## 2026-10-18

- **Part B:** putting c13c's own belief-free answers into the SFT corpus (rb1010a) removes most of the declaration belief
  from the base model, without hurting validate. (§3.26)
- **c13d:** OPCD does not fix T41. T41 and T60 went to a corpus brief (Rollup/Normalizer sets). (§3.25)

## 2026-10-16 / 17

- **rb1009 rebuild** with the DataIntersection and SCD-2 sets: T53 without thinking 0.38 → 1.00. (§3.24)
- **OPCD c13 → c13c on rb1009:** a rulev6 teacher fixes T42. **c13c becomes the ship candidate.** (§3.25)

## 2026-10-14 / 15

- **c9/c10:** a component-guide teacher closes most thinking-off generate gaps; c10 (skip truncated samples) is the best of
  that line. (§3.21, §3.22)
- **c11/c12:** the DataIntersection rule does not transfer through OPCD → **decision: fix it in the corpus** (rebuild).
  (§3.22, §3.23)

## 2026-10-13

- **Owner decision:** the recipe is rb1006 plus OPCD c4. The older three-phase recipe is retired. (§5)
- **Suite v5:** 30 real-world generate tests added. The models tie there and share the same gaps. (§3.20)

## 2026-10-06 – 10-09

- **rb1006** (fix-to-spec explained set): fix with thinking 0.70 → 0.86. It becomes the base. (§3.16)
- **The declaration belief** ("uninitialized variables are null") survived SFT, thinking traces and DPO (rb1007, rb1008,
  dpodef1).
- **Putting the rule in the system prompt fixes it,** so we distill that prompt into the model: on-policy context
  distillation (dpodef2, then the OPCD runs c1–c8). (§3.19)
- **Judge switched** to the local gpt-6.1-sol (10-09). Compare only within one judge. (§4.6)

## Before 2026-10-01

- Self-distillation, DPO rounds and targeted repairs gave no measurable gain. The three-phase recipe of that period is
  documented in §1–§3.15 and retired.
