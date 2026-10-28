# Work log

Important progress and decisions, newest first. Details and numbers: `spec/ctl2_training_findings.md` (section in brackets).

## Where we are (2026-10-28)

- **Ship candidate: c13c**, the rb1009 base plus OPCD adapter `data/opcd/c13c/round_015`. Confirmed by 20-sample checks
  and by running the generated code on the server.
- **Deploy with thinking on and a compile-and-retry loop.** In the agentic harness (§3.31) c13c passes 88% of 137
  execution-scored tasks thinking on with error feedback, 92% when the failing test rows are fed back too (28/30 real-world
  suite tests); thinking off 69% / 80%. It holds on 165 fresh-domain prompts nobody here wrote (§3.36): 86% / 91%
  thinking on, within ±0.08 of pool 1's corpus tasks.
- **Biggest real gap:** generate without thinking. Only 44% of c13c's answers run correctly (§3.28).
- **Validate is gated on ground truth now** (§3.35, §4.8): planted server-confirmed defects, parser-scored, sets B1 and
  B1-tweak. Thinking-off validate flags 24–41% of clean code with an [ERROR]; c13c misses a removed Rollup lifecycle
  function 7 times in 10; the judge's 0.04 seed gaps are not reproduced. **valprec1 (§3.37) not adopted:** OPCD with
  the server's verdict in the teacher's context makes thinking-on reviews the best yet (B1 false alarm 0.14 → 0.01,
  lifecycle recall 0.35 → 0.83) and lifts thinking-off lifecycle recall (0.18 → 0.67) at no generate cost. But the
  thinking-off false-alarm rate did not fall, and on the plain test.py path it doubled (0.30 → 0.61). Next: valprec2
  with ≥ 50% clean reviews.
- **Training on the model's own server-verified answers (exec-RFT) did not help** (§3.33): one round moved neither the
  gap-test pass rate nor a held-out pool, and pushed T54 thinking off back to `$out.1`. Not adopted.
- **rb1012 not adopted** (§3.30). The two new corpus sets showed no gain in two seeds, and both seeds regressed on the
  Rollup accumulator explanation. Neither set is in the default rebuild recipe. The regression is in the SFT records (§3.32, §3.34), not in the DPO pairs
  (§3.32); rb1011 seed 7 shows it is the new SFT records, not seed luck (§3.34).

## 2026-10-28

- **valprec1 gates** (`spec/validate_precision_findings.md`, findings §3.37). **Not adopted; a second round with a
  rebalanced review set is next.**
  - **Thinking on:** better than c13c on both ground-truth sets.
    - B1: false alarm 0.14 → 0.01 (−0.13 [−0.23, −0.05]), recall 0.86 → 0.96, lifecycle 0.35 → 0.83.
    - B1-tweak: false alarm 0.08 → 0.04, recall 0.89 → 0.97.
  - **Thinking off, with the format:** lifecycle recall 0.18 → 0.67 (B1) and 0.31 → 0.75 (B1-tweak), and recall
    +0.10. The false alarm did not move: B1 0.41 → 0.35, B1-tweak 0.24 → 0.23, both within noise. The gate needed −0.08.
  - **Thinking off, plain (the test.py path):** false alarm 0.30 → **0.61** (+0.31 [+0.20, +0.42]); judge WRONG 2.2% →
    3.8%.
    - New false claims: DataIntersection `$out.0` "wrong port", getDayOfWeek / getMinute signatures, "unreachable
      return", more requirement misreadings.
    - Kept: initGroup ordinal, UTC-millisecond DST, null-compare as ERROR.
    - The clean / plain / off review slot is the only one whose KL did not converge (0.19 → 0.095). It had 160 samples
      against about 550 per planted slot (78% of reviews were planted).
  - **Fact sheet:** it removed the claims it refutes (decimal / integer "truncates" / "does not compile", null to a
    local). The §7 severity sentence moved nothing: null-compare findings are still ERROR.
  - **Generate and belief hold:**
    - gap tests off 0.406 vs 0.403; on 0.715 vs 0.761 (−0.045, inside ±0.06 but at its edge);
    - harness first attempt 0.65 / 0.79 vs 0.65 / 0.82;
    - T40/T42, hard sets, T54 0/20: as c13c or better;
    - context guard never fired.
  - **valprec2 proposal:**
    - clean reviews ≥ 50% of review weight, clean / plain / off over-sampled;
    - compile-type mutants down-sampled;
    - controls for the surviving claims;
    - a teacher line that names [WARNING] for data-dependent nulls;
    - add B1 plain thinking on to the gates.

## 2026-10-27 (night)

- **valprec1 started** (`spec/validate_precision_brief.md`, `spec/validate_precision_findings.md`, findings §3.37): OPCD on
  c13c with validate reviews whose teacher sees the CloverDX server's verdict on the code under review.
  - **Fact probes first** (29 runs, `results/validate_precision/fact_probes.json`): an unguarded `>`/`<`, arithmetic, `!`
    or `if` on a null **does throw** (NullPointerException); `==`/`!=` with null and assigning null to a local do not;
    decimal / integer is a decimal (7.50 / 2 = 3.75) and a decimal compared with an integer literal compiles; UTC
    millisecond arithmetic has no DST shift. So B1-tweak's "nullable compared without a guard can throw" is true, but
    data-dependent: the teacher's fact sheet calls it a WARNING (§7), never an ERROR. The decimal claims are false.
  - **Data:** 160 exec-RFT references (pool minus the 97 B1 references; holdout unread) → 160 clean + 553 server-confirmed
    planted reviews (seed 13, every confirmed mutant), each in both modes with the output format in one of them: 1426
    rows. Exclusions checked against pool 1, pool_tweak, B1, B1-tweak and the holdout (3 `c13b_keep` DI prompts were
    holdout prompts and were dropped from the anchor).
  - **Run:** c13c's anchors at ×2 weight so reviews are 61% of the non-replay weight; 123 rounds (each review row once),
    ~7 min per round; `opcd.py` gained a per-prompt system addition, a context-quote guard and per-tag stats. Smoke: KL
    falls; review samples start at KL 0.09–0.15 per token against ≤ 0.03 for the anchors. Gates run automatically after
    training (`scripts/validate_precision/run.sh` → `gates.sh`).

## 2026-10-28 (early) — retry-distill data step 1 done

- Sampling run for `spec/retry_distill_brief.md` finished (c13c, GPU 2, 23:02–04:29): training pool
  `data/agent_harness/pool_retry.jsonl` (160 exec-RFT prompts not in pool 1, holdout excluded) × 4 runs × 2 modes, 2
  feedback rounds with `--rows-feedback` → `results/agent_harness/c13c_pool_retry_rows.jsonl` (1,280 records, 0 model
  errors; summary `.summary.md`; script `scripts/retry_distill_sample.sh`).
- First attempt 0.51 off / 0.65 on, final 0.75 / 0.89 (this pool is harder than pool 1: 0.65 / 0.82 first there).
- **Triples (attempt 0 failed, later attempt passed): 150 off (66 distinct prompts) + 149 on (80 prompts) = 299.**
  By attempt-0 cause: wrong_rows 56/62 (off/on), undeclared_variable 28/9, wrong_arguments 18/23, out_port 1/14,
  regex_negation 4/10, other 31/13, runtime 7/8. By set: syntax_pitfalls 54/59, scd2 23/26, rollup_accumulator 19/19,
  normalizer_multirow 19/20, dataintersection 18/11, rollup_lifecycle 12/5, zerodate 5/9.
- Note: thinking on is *worse* than off on DataIntersection here (first 0.53 vs 0.59, final 0.72 vs 0.90; 23 compile
  errors, mostly `$out.1`), consistent with §3.36.
- **Step 1b, the second `--tweak` batch (same day, 10:00–17:28):** seeds 201–202 on the six sets + 203–205 Rollup-only
  (`scripts/retry_distill_tweak.sh`; `merge_pools.py --dir/--exclude`) → `data/agent_harness/pool_retry_tweak.jsonl`,
  190 tasks (acceptance 0.66; DI 49, Reformat 47, Normalizer 49, Rollup 42; zerodate kept none, 22 prose-origin
  dropped), no overlap with pool_tweak by id. c13c sampled the same way → `results/agent_harness/c13c_pool_retry_tweak_rows.jsonl`
  (1,520 records, 0 model errors). First 0.64 off / 0.70 on, final 0.81 / 0.85. **Triples 131 off (57 prompts) + 120 on
  (63 prompts) = 251.** Causes: wrong_rows 45/64, other compile 22/4, out_port 4/22, undeclared_variable 21/3,
  wrong_arguments 18/8, reserved_time_unit 6/13. Thinking on again loses most on DataIntersection (`$out.1`).
- **Training pool total: 550 triples** (281 off / 269 on) over 350 prompts; the §3.29 habits (`$out.1`, time-unit names,
  argument order, undeclared variables) are all present. Training waits for the validate-precision run (valprec1) and
  starts from the winning adapter.

## 2026-10-27 (evening)

- **Validate gate adopted: the planted-defect ground truth, not the judge** (`CLAUDE.md` measurement rules, findings §4.8).
  Both modes, format prompt, 2 runs; report defect recall and the clean-code false-alarm rate; bands recall ±0.05, false
  alarm ±0.08, one kind ±0.15. Judge validate differences below 0.04 are seed noise. The judge suite stays for what the
  parser cannot see.
- **B1-tweak built and c13c measured** (`data/agent_harness/validate_mutants_tweak.jsonl`, 146 server-confirmed defects +
  50 controls from the pool_tweak references, which no model was trained on). Reason: B1's references are pool-1 corpus
  code; 27 of its 30 lifecycle mutants come from the Rollup-accumulator set that rb1011/rb1012 saw in SFT and c13c did
  not, so cross-model claims on B1 are confounded.
  - c13c thinking off: recall 0.80, false alarm 0.24 (B1: 0.75 / 0.41); thinking on 0.89 / 0.08 (B1: 0.86 / 0.14).
  - **The lifecycle gap is real** (0.31 / 0.28 recall on code it never saw).
  - **The false-alarm rate depends on the reference style:** B1's corpus Rollup controls are flagged 0.80 of the time
    thinking off, B1-tweak's LLM-written Rollups 0.09; on B1-tweak the false alarms are null-guard "can throw" claims,
    decimal/integer arithmetic claims and rule misreadings instead (not probed).
- **Checked the two harness-measurement findings** (§3.35, §3.36): the headline numbers reproduce from the raw files
  (pool_tweak pass rates; c13c control false alarms 41/100 off, 14/100 on; lifecycle recall 11/60). The lifecycle misses
  are "ISSUES: none, VERDICT: PASS" on Rollups the server rejects at init. One caveat added (the B1 familiarity confound
  above).
- **Next experiment: `spec/validate_precision_brief.md`** — OPCD on validate-shaped prompts where the teacher has the
  server's verdict on the code under review in context (clean references and planted mutants from the exec-RFT pool
  minus pool 1 and the holdout), gated on B1 / B1-tweak and the generate gates. Motivation: c13c's T40/T42 belief fix
  did not transfer to reviews (it still writes "never initialized" on clean Rollup code), and the recurring false claims
  are a short, refuted list. `spec/retry_distill_brief.md` stays queued behind it; its sampling phase can run on the
  other free GPU meanwhile.

## 2026-10-27

- **Fresh-domain pool (Part A of the harness-measurement brief): c13c holds.** (§3.36,
  `spec/harness_measurement_findings.md`)
  - **Pool:** gpt-6.1-sol rewrote the generate prompts of the runtime-harness corpus sets into new domains and wrote
    fixtures. Tasks were kept only if their reference reproduced the expected rows on the server: 190 of 322 (59%).
    - One fixture-prompt fix, for Rollup: 0 of 20 accepted before it.
    - Hand check: 12 of 15 passed; the 3 failures were prose questions. The pool-wide drop of prose questions removed 25.
    - Final pool 165 tasks (`data/agent_harness/pool_tweak.jsonl`, evaluation only).
  - **Run:** c13c as pool 1 was run, both modes, 2 runs per task.
  - **Result, against pool 1's 107 corpus tasks (95% CI):**
    - thinking on: 0.81 / 0.86 / 0.91 (first / error feedback / rows feedback), differences −0.02 / −0.01 / −0.01
      (±0.07–0.09);
    - thinking off: 0.72 / 0.80 / 0.89, differences −0.01 / +0.06 / +0.07 (±0.09–0.11).
  - **Weak spots:** DataIntersection 0.83 / 0.85; thinking on writes `$out.1`/`$out.2` in 13 of 51 DataIntersection
    tasks; SCD-2 rewrites 0.68 / 0.76; thinking off `isDate`/`str2date` argument order.
  - **Caveats:**
    - 19 prompts carry a contradictory component header; the result is the same without them.
    - The acceptance filter under-samples pitfall-inviting tasks.
  - **Incident:** the first run was killed at 23:24 by Part B's `run_models.sh` cleanup, which kills any server named
    rb1009. The failed records were rerun; `run_c13c.sh` now serves the base as `rb1009_hm`.

- **Validate ground truth (Part B of the harness-measurement brief).** (§3.35, `spec/harness_measurement_findings.md`)
  - **Setup:**
    - 169 single defects planted in pool-1 references, each confirmed failing on the CloverDX server, plus 50 clean
      controls;
    - answers scored by a parser, no judge;
    - c13c, rb1011, rb1011s2 and rb1012, both modes, with the suite's output-format system prompt.
  - **Recall:** rb1011 0.82 / 0.88 (off / on), rb1011s2 0.81 / 0.86, rb1012 0.81 / 0.91, c13c 0.75 / 0.86.
    - c13c's gap is missing Rollup lifecycle functions (0.18 off).
    - rb1012, trained on that set, is best there (0.73).
  - **Seed spread:** recall ±0.02, false alarm ±0.04; the judge put the same pair 0.04 apart. The judge's rb1011s2
    deficit is not reproduced.
  - **Largest finding:** thinking off puts an [ERROR] on 28–41% of clean, server-passing code (thinking on 7–14%). All
    19 flagged controls are false claims: 11 by §7 facts, 8 by server probe (32 probes, all as required).
  - **Format:** test.py's validate path sends no output format; then 44–71% of thinking-on answers have no VERDICT line,
    so parser scores need the format prompt.
  - **Proposal:** gate validate on planted-defect recall and clean-code false alarm (format prompt, both modes, about
    25 min per model), and stop reading 0.04-level judge validate differences.

## 2026-10-26

- **Exec-RFT pilot on c13c: no gain, not adopted.** (§3.33, `spec/exec_rft_pilot_findings.md`)
  - **Setup:** 297 corpus generate/fix prompts with server-verified fixtures (40 held out). c13c sampled 8 answers per
    prompt in both modes, each run on the server. Its passing answers (375, by NLL) and passer-vs-failure pairs (331, light
    DPO) were trained for one round, with c13c's belief and replay anchors in the mix.
  - **Result:** execution pass rate on the gap tests −0.03 off, +0.04 on; on the held-out pool +0.02 / +0.01. All inside
    the 95% CIs and inside c13c's own ±0.03 run-to-run spread. The compile habits did not move (`month` as a variable name
    not at all).
  - **Side effects:** belief gates unchanged; thinking-off validate WRONG 2.2% → 0.9%; T54 thinking off regressed
    (`$out.1` 8/40 against 0/50), which fails its gate.
  - **Why little could move:** 57–68% of prompts were all-pass or all-fail for c13c, so only 200 prompt-modes gave
    signal; the habits occur in ~12% of samples.
  - **Decision:** no second round. A full run would need harder prompts (c13c at 1–4 of 8, gap-test-like), prompts that
    invite each habit, and a token-level signal.
  - **Tooling kept:** `scripts/exec_rft/` (pool builder, k-sample execution scorer, cause tally, gates), `opcd.py`
    `prompts.exec` (fixed NLL/DPO samples next to OPCD anchors).

- **rb1012 DPO isolation:** the accumulator regression is not caused by DPO. (§3.32, `spec/rb1012_dpo_isolation_findings.md`)
  - **Setup:** the DPO phase alone, rerun on rb1011's SFT adapter.
  - **Results:** rb1011's pairs (A) reproduce rb1011: T22 "starts at zero" 19 against 20/45, T41 0.83 against 0.82.
    Adding the 25 lifecycle pairs (B: 15/45, 0.79), or all of rb1012's DPO pairs (C: 18/45, 0.85), does not bring back
    rb1012's 36/45.
  - **Conclusions:**
    - the DPO phase adds little noise;
    - the regression comes from rb1012's SFT phase, either the 130 new SFT records or SFT-seed luck.
  - **Check 1 done: rb1012's SFT adapter plus rb1011's DPO pairs** reproduces most of rb1012's profile:
    - T22 B1 WRONG 28/45;
    - B4 caught 33 against 45/45 (CI excludes zero);
    - T41 0.77;
    - the same T40/T42 pattern.

    The regression comes with rb1012's SFT adapter.
  - **Still open:** the SFT records or the seed. It needs the rb1011 seed-7 rebuild (about 5.5 h; config and run script
    ready, not started). That decides whether an SFT ablation (about 24 GPU-h) is needed.
- **The shared run-history log `logs/Qwen3.8-27B.yaml` was torn** by concurrent `train.py`/`test.py` writes on 10-25
  around 21:16. From then on, every run's final log append failed; results were not affected. The log was repaired, and
  a backup kept. Parallel runs will tear it again until the writers take a lock.

## 2026-10-26 (evening)

- **rb1011 seed 7 (rb1011s2):** T22.B1 13/45 — the rb1012 accumulator regression is in its 130 new SFT records, not seed
  luck (§3.34). Neither set goes into the recipe; the SFT ablation is not run (no gain to recover).
- **Second variance pair.** Between seeds of one recipe: generate/fix/gap judge ±0.01–0.05, thinking-off validate 0.04–0.13,
  execution pass rate up to 0.14, single tests up to 1.0 (T22.B4 2 → 45). §4.7 now carries per-gate noise bands; a
  single-test result of one rebuild is never a property of the corpus.
- CloverDX server hung (listening, not answering) and was restarted by hand.

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
