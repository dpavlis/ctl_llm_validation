# Exec-RFT pilot on c13c: findings (2026-10-26)

Brief: `spec/exec_rft_pilot_brief.md`. One round of rejection-sampling fine-tuning (plus a light DPO term) on c13c's own
answers that ran correctly on the CloverDX server, with c13c's belief and replay anchors kept in the mix.

**Result in one line:** the execution pass rate did not move. Gap tests: thinking off −0.03 [−0.11, +0.05], thinking on
+0.04 [−0.03, +0.11]. Held-out pool: +0.02 [−0.03, +0.07] off, +0.01 [−0.05, +0.06] on. The belief gates held,
thinking-off validate WRONG fell (2.2% → 0.9%), but T54 thinking off regressed (`$out.1` in 8/40 against c13c's 0/50).
No second round.

Scripts: `scripts/exec_rft/` (`build_pool.py`, `sample_score.py`, `causes.py`, `report.py`, `gates.sh`, `gates_table.py`,
`run.sh`, `common.py`); training: `opcd.py` (`prompts.exec`), `configs/opcd_exec_rft1.yaml`. Raw data:
`data/exec_rft/`, `results/exec_rft/`, `data/opcd/exec_rft1/`, logs in `logs/exec_rft/`.

---

## Pool

`scripts/exec_rft/build_pool.py`, report `data/exec_rft/build_report.json`.

**Sources:** the seven server-verified corpus sets with runtime harnesses (SCD-2, DataIntersection, Rollup accumulator,
Rollup lifecycle, Normalizer multi-row, syntax pitfalls, zeroDate). Every SFT record, then every DPO prompt not already
seen, with the gold (or chosen) answer's last CTL block.

| step | count |
|---|---|
| records read (SFT + DPO prompts) | 511 (generate 315, fix 90, validate 106) |
| dropped: validate | 106 |
| dropped: generate/fix answer with no CTL block (explanations) | 52 |
| dropped: suite overlap (5-gram Jaccard ≥ 0.30, field names masked; 198 protected prompts: suite v5, generate_rw, hard sets 1–3) | **0** (max kept 0.26) |
| dropped: no corpus fixture for the record | 56 (mostly DataIntersection generate records; their set fixtures cover 26 cases) |
| dropped: gold answer does not run / reproduce | 0 |
| **kept** | **297** (generate 219, fix 78) |
| training pool / holdout | 257 / 40 |

**Fixtures:**
- **corpus_harness, 266:** the gold answer, run in our graph (`graph_harness.build` with the corpus fixture's inputs),
  reproduces the corpus's own expected rows.
- **reference_run, 31:** no usable corpus expectation (25 syntax-pitfalls records whose fixtures carry inputs only or
  whose gold code was revised after the fixture, and 6 lifecycle fix-to-spec records). The expected rows are the gold answer's own output on the corpus inputs, then re-run
  and checked to pass (source 2 of the brief). No corpus expectation disagreed with our graph.
- Graph and data files: `data/exec_rft/graphs/<label>/`; on the server under `suite_v5/` in MiscExamples.

**By source:** SCD-2 75, syntax pitfalls 75, Rollup accumulator 60, Normalizer multi-row 53, DataIntersection 18,
Rollup lifecycle 10, zeroDate 6. **By component:** Rollup 88, Normalizer 82, Reformat 74, DataIntersection 38,
Denormalizer 9, others 6.

**Holdout:** 40 prompts, stratified by component (Rollup 13, Normalizer 11, Reformat 10, DataIntersection 6).
Near-duplicates (an SFT record and a DPO pair on one scenario, 5-gram Jaccard ≥ 0.30 or the same gold code) form 209
clusters that go to one side whole; the closest held-out prompt to any training prompt is at Jaccard 0.287.

---

## Yield

c13c, k = 8 per prompt, all 297 prompts, suite sampling (T 0.4, top_p 0.95, top_k 20), no `max_tokens` (16k context
minus the prompt). `results/exec_rft/samples_{off,on}.jsonl`, tables `results/exec_rft/yield_c13c.json`.

| | thinking off | thinking on |
|---|---|---|
| samples | 2376 | 2376 |
| **pass rate** | **0.642** | **0.718** |
| wrong_rows | 371 | 289 |
| init_error | 413 | 344 |
| runtime_error / invalid / no_code | 38 / 19 / 9 | 11 / 18 / 9 |
| median length (tokens) | 305 | 1631 |
| hit the 16k cap | 2 | 1 |

**Per-prompt pass count (of 8):**

| passers | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| thinking off (prompts) | 62 | 14 | 7 | 13 | 16 | 13 | 13 | 20 | 139 |
| thinking on (prompts) | 29 | 16 | 9 | 13 | 20 | 21 | 17 | 31 | 141 |

No signal: 201 of 297 prompts off (139 all-pass, 62 all-fail), 170 on (141 / 29). With signal: **96 off, 127 on.**

**Init-error causes** (`scripts/exec_rft/causes.py`). It reads the cause from the code first and from the server message
(cut at 300 characters) second; on the stored suite answers of all models it reproduces §3.29's ranking, though not its
exact counts, which used full messages.

| cause (§3.29) | off | on |
|---|---|---|
| DataIntersection writes `$out.1`/`$out.2` | 7 | 49 |
| field not in the metadata | 7 | 2 |
| regex negation `!~` / `!x ~= re` | 78 | 54 |
| time-unit keyword as a variable name | 63 | 59 |
| invented function (`raise`, …) | 48 | 22 |
| `str2date`/`isDate` argument order | 5 | 0 |
| undeclared variable | 27 | 33 |
| `"\."` invalid escape | 6 | 2 |
| return constant in a ternary | 9 | 11 |
| other wrong arguments | 23 | 47 |
| dictionary access | 0 | 0 |
| **sum of the 11** | **273 / 413** (66%) | **279 / 344** (81%) |
| not in §3.29: missing Rollup lifecycle function | 40 | 26 |
| not in §3.29: type mismatch | 21 | 2 |
| other | 79 | 37 |

Against §3.29 (gap tests, 89% in the 11 causes): the same habits, in a different order. On these corpus prompts the
regex negation, time-unit variable names and invented functions lead thinking off; `$out.1` in DataIntersection leads
thinking on. The lifecycle fix-to-spec prompts add the missing-function failures (§3.29 and §3.30's T22 theme).

---

## Training data

`opcd.py prepare` with `prompts.exec` (`configs/opcd_exec_rft1.yaml`; prompts in `data/opcd/exec_rft1/prompts.jsonl`).
For every (pool prompt, mode) with 1–7 passers (200 prompt-modes, 152 prompts): up to 2 passers as SFT samples, and DPO
pairs passer vs a failing sample of the same prompt and mode, preferring `init_error` rejects. 331 pairs ≥ 100, so DPO
is in.

| | SFT samples (NLL) | DPO pairs |
|---|---|---|
| generate, thinking on | 169 | 152 |
| fix, thinking on | 43 | 36 |
| generate, thinking off | 82 | 73 |
| fix, thinking off | 81 | 70 |
| **total** | **375** | **331** |

- **DPO rejects:** init_error 205, wrong_rows 97, runtime_error 17, invalid 8, no_code 4.
- **SFT samples by component:** Rollup 108, Reformat 108, Normalizer 80, DataIntersection 50, Denormalizer 24, other 5.
  Median length: 1808 tokens on (thinking kept), 346 off (empty thinking block from the chat template).
- **Anchors (findings §5 step 3):** c13c's belief prompts (dpodef1 train 206, dpodef3b 53, hard sets 1 and 2 ×3, contrast
  55) keep the rulev6 teacher; they are **0.348** of the non-replay prompt weight (377 against 706 exec rows). Replay is
  0.4 of every round, scored against the plain model with the adapter off. c13c's gap/DI keep prompts (guide teachers)
  are left out so the generate signal comes from execution only.
- **Mechanics** (`opcd.py`, new `prompts.exec`): exec rows are fixed samples, drawn into the non-replay pool like any
  prompt and not resampled. SFT samples get NLL normalized by their own token count (`exec_weight`); DPO pairs get
  `-logσ(β·margin)` per pair (`exec_dpo_weight`, β = 0.1) against reference log-probs computed once under the initial
  adapter (`data/opcd/exec_rft1/exec_dpo_ref.json`). Teacher-scored samples keep their OPCD loss and normalization.
- **Weights from the smoke** (`opcd.py smoke --exec`, median-length samples, `logs/exec_rft/smoke.log`): gradient norm
  per kind at step 0, OPCD 0.14, NLL 0.17, DPO 16.1. `exec_weight` 1.0; `exec_dpo_weight` 0.02 (DPO ~0.3), because
  unweighted DPO would have set the update direction alone under clipping and Adam. NLL fell, the DPO margin rose and
  the OPCD KL stayed level over 3 steps; peak memory 60 GB.
- **Hyperparameters:** c13c's per-step settings (lr 2e-5, warmup 5, grad clip 1.0, 32 prompts per round, k = 2 for live
  samples, 2 steps per round, LoRA r 32), `cutoff_exec` 16384 (exec samples need no teacher pass). **57 rounds** so that
  every exec row is drawn once: 114 optimizer steps; 705 exec rows trained (1 over the cutoff), plus 643 live belief, 110
  contrast and 1479 replay samples. 4.7 h on one GPU, sampler on a second.

| training (rounds) | NLL / token | DPO margin | grad norm | replay KL / token | target belief rate |
|---|---|---|---|---|---|
| 0–7 | 0.060 | 0.06 | 0.39 | 0.004 | 0.000 |
| 24–31 | 0.062 | 1.00 | 0.40 | 0.010 | 0.018 |
| 48–55 | 0.051 | 0.72 | 0.40 | 0.012 | 0.000 |

Belief probe (20 prompts × 2): 0.025 before, 0.000 at every check after.

---

## Gates

Round 056 against c13c on the same vLLM path (rb1009 + hot-loaded adapter, :3012 thinking on, :3011 off) and judge
(gpt-6.1-sol). Table: `scripts/exec_rft/gates_table.py` → `results/exec_rft/gates.md`. 95% CIs: Newcombe (Wilson) for
proportions, Welch for means, per-prompt paired for the held-out pool. Gap-test samples are treated as independent, so
those CIs are somewhat optimistic.

**c13c gap tests were run twice more today** (`GATES=gaps scripts/exec_rft/gates.sh c13c 015`) and pooled with the
10-17 run: 3 × n10 per mode against exec_rft1's 2 × n10. Run to run, c13c moves 0.373–0.436 thinking off and
0.727–0.782 on: the continuation variance the brief asked for is about ±0.03 per n10 run.

| gate | c13c | exec_rft1 | difference, 95% CI | pass condition | |
|---|---|---|---|---|---|
| **gap tests off: execution pass rate** (runs 0.400, 0.373, 0.436 / 0.355, 0.391) | 133/330 (0.403) | 82/220 (0.373) | −0.030 (−0.112, +0.053) | higher beyond CI | **fail** |
| **gap tests on: execution pass rate** (runs 0.727, 0.773, 0.782 / 0.773, 0.827) | 251/330 (0.761) | 176/220 (0.800) | +0.039 (−0.033, +0.108) | higher beyond CI | **fail** |
| **held-out pool off** (40 × 8) | 215/320 (0.672) | 222/320 (0.694) | +0.022 (−0.028, +0.071) | higher | not beyond noise |
| **held-out pool on** (40 × 8) | 213/320 (0.666) | 215/320 (0.672) | +0.006 (−0.050, +0.062) | higher | not beyond noise |
| gap tests off: judge score | 0.775 (330) | 0.779 (220) | +0.004 (−0.029, +0.037) | not lower | pass |
| gap tests on: judge score | 0.911 (330) | 0.923 (220) | +0.011 (−0.011, +0.033) | not lower | pass |
| T40 on, below full (2 × n20) | 1/20 | 2/40 | +0.000 (−0.190, +0.122) | ≤ c13c | pass |
| T42 on, below full (2 × n20) | 7/20 | 13/40 | −0.025 (−0.275, +0.204) | ≤ c13c | pass |
| hard sets 1 / 2 / 3, belief claims (k4) | 0/160, 1/60, 0/160 | 0/160, 1/60, 0/160 | – | none | pass (as c13c) |
| hard set 3: nullable / non-nullable / metadata default wrong | 14/40, 2/20, 4/20 | 14/40, 1/20, 4/20 | +0.00 / −0.05 / +0.00 | nullable ≤ 14/40 | pass |
| validate off ×9 excl. T18/T22: mean | 0.935 (495) | 0.958 (495) | +0.023 (+0.006, +0.040) | – | better |
| validate off ×9: WRONG share of findings | 25/1135 (2.2%) | 10/1128 (0.9%) | −0.013 (−0.024, −0.003) | ≤ 2.5% | pass |
| thinking on, full v4 n5: validate / fix / generate | 0.850 / 0.826 / 0.970 | 0.814 / 0.844 / 0.968 | −0.036 / +0.018 / −0.002 (all CIs span 0) | within noise | pass |
| **T54 off, `$out.1`/`$out.2`** (gate n20) | 0/20 | 2/20 | +0.10 (−0.08, +0.30) | ≤ 1/20 | **fail** |
| T54 off, `$out.1`/`$out.2`, gate + gap runs pooled | 0/50 | 8/40 | **+0.20 (+0.08, +0.35)** | – | regression |

(The validate mean excludes T18 and T22 in both columns, so the T18 rubric change does not enter it.)

**Gap tests by status:**

| status | c13c off (330) | exec_rft1 off (220) | c13c on (330) | exec_rft1 on (220) |
|---|---|---|---|---|
| pass | 0.403 | 0.373 | 0.761 | 0.800 |
| wrong_rows | 0.227 | 0.200 | 0.067 | 0.041 |
| init_error | 0.276 | 0.291 | 0.155 | 0.141 |
| runtime_error | 0.061 | 0.077 | 0.012 | 0.014 |
| invalid | 0.033 | 0.059 | – | – |
| no_code | – | – | 0.006 | 0.005 |

**Gap tests per test** (passes / samples):

| test | off c13c | off exec_rft1 | on c13c | on exec_rft1 |
|---|---|---|---|---|
| T44 | 12/30 | 11/20 | 29/30 | 16/20 |
| T46 | 21/30 | 10/20 | 28/30 | 18/20 |
| T53 | 30/30 | 20/20 | 30/30 | 20/20 |
| T54 | 28/30 | 13/20 | 22/30 | 16/20 |
| T57 | 1/30 | 3/20 | 6/30 | 7/20 |
| T60 | 2/30 | 2/20 | 27/30 | 19/20 |
| T61 | 1/30 | 0/20 | 10/30 | 13/20 |
| T62 | 10/30 | 1/20 | 30/30 | 19/20 |
| T63 | 0/30 | 0/20 | 25/30 | 15/20 |
| T67 | 5/30 | 7/20 | 24/30 | 18/20 |
| T73 | 23/30 | 15/20 | 20/30 | 15/20 |

---

## Hand check

20 answers drawn at random (seed 7) from exec_rft1's gap-test answers, 10 passing and 10 failing, compared with c13c's
answers to the same tests (all three c13c runs).

**Passing (10):** T73 on/off ×3, T54 on ×2 and off ×2, T46 off, T53 on, T67 off. The code follows c13c's structure for
the same test; T53 and T73 were already passing for c13c. T67 off is the clearest change: c13c's thinking-off T67 answers
had 10 compile failures from regex negation (`!x ~= re`, `!~`) in 30; exec_rft1's 20 have none.

**Failing (10):**
- **T57 off ×4:** three `Index 0 out of bounds` runtime errors (reading an empty accumulator list) and one invented
  `push()`. c13c fails T57 the same way (6 runtime errors in 30).
- **T61 off ×2:** `currentContext = $in.0` into a different record type (type mismatch), as in c13c.
- **T62 off:** `$out.0.acc_ref_no = acc.acc_ref_no`, a field that does not exist; c13c makes the same error in 11 of 30,
  exec_rft1 in 13 of 20.
- **T67 off:** wrong rows on ports 2 and 3 (routing logic), c13c's own most common T67 failure.
- **T46 on, T54 on:** compile errors (a syntax error, and `$out.1` in DataIntersection).

**What changed:**
1. **The failures are c13c's own failures.** Every failing answer repeats a failure c13c already makes on that test.
   No new kind of error appeared, except more `$out.1` on T54.
2. **Compile habits moved per test, not overall.** Thinking off, in 2 runs each: regex negation 19 → 11, time-unit
   variable names 10 → 15, `$out.1` 0 → 6, `str2date` argument order 0 → 5; the 11 causes 55 → 61, all init errors
   62 → 64. Where a habit went (T67, T46's invented `date2month`), the answer usually failed on wrong rows instead.
3. **Thinking length did not change:** thinking on, mean 2155 words against c13c's 2131–2277 across its runs (median
   2019 against 1903–1974); answers 398 against 419–431 words.

---

## Indications

1. **Did the pass rate rise in the trained modes?** No. Both modes were trained; the gap-test differences (−0.03 off,
   +0.04 on) and the held-out pool differences (+0.02 off, +0.01 on) are all inside their 95% CIs and inside c13c's own
   run-to-run spread (±0.03 per n10 run). Thinking on, the small upward shift comes from fewer wrong rows (0.067 →
   0.041) rather than fewer compile errors (0.155 → 0.141); neither is significant.
2. **Did any of the 11 compile causes move?** Not beyond noise. Gap tests thinking off (2 runs each, c13c today against
   exec_rft1): regex negation 19 → 11, time-unit names 10 → 15, invented functions 10 → 10, `$out.1` 0 → 6, `str2date`
   order 0 → 5, ternary return constant 2 → 4; sum 55 → 61. Thinking on: 27 → 26 (field not in metadata 13 → 12,
   `str2date` 2 → 5). Held-out pool: time-unit names 30 → 31 off, 28 → 26 on; sum 47 → 42 off, 50 → 46 on.
   The time-unit habit, the one §3.31 found survives feedback too, did not move at all.
3. **Did the pool and the suite agree?** Yes: neither moved. The gain is not pool-specific; there is no gain.
4. **Did anything regress?**
   - **T54 thinking off:** `$out.1`/`$out.2` in 8/40 answers (gate run 2/20, gap runs 6/20) against c13c's 0/50,
     +0.20 [+0.08, +0.35]. The gate (≤ 1/20) fails. The training data has no DataIntersection passer writing `$out.1`;
     it has 25 thinking-on DataIntersection DPO rejects that do. The cause is not established.
   - Belief gates: unchanged (hard sets, T40/T42, hard set 3 by direction).
   - Thinking-off validate WRONG improved, 2.2% → 0.9% [−2.4, −0.3 points] (optimistic CI); its mean rose 0.935 → 0.958.
     This was not a target; validate prompts were only replay.
   - Thinking-on validate −0.036 at n5, inside noise.
5. **Is a second round worth running?** Not as is. One round moved nothing measurable, and the gate failure on T54 would
   carry over. What limits the method here, and what a full run would need:
   - **Signal is thin.** 57–68% of prompts were all-pass or all-fail for c13c (201/297 off, 170/297 on); 200
     prompt-modes produced the 375 SFT samples. RFT on answers c13c already gives with probability ~0.6 mostly
     re-teaches what it does. A full run needs prompts where c13c sits at 1–4 of 8: harder and more prompts, ideally
     shaped like the gap tests (T57, T60, T61, T63 thinking off are at 0–7%), with verified fixtures. The agent
     harness's `--tweak` pool (§3.31) is one source.
   - **The habits are rare per sample.** The 11 causes are 12% of thinking-off samples; a passing answer for a prompt
     that does not invite `month` as a name teaches nothing about it. Targeted prompts that invite each habit, as the
     syntax set's prompts do, would concentrate the signal.
   - **A per-token signal may be needed.** NLL on passers and a sequence-level DPO term do not say which tokens were
     wrong. GRPO with the execution result as reward has the same limit; a compiler-error-located signal (the failing
     line) or OPCD with the compiler message in the teacher context would localize it.
   - **Measurement for a full run:** at least 3 × n10 gap runs per arm (as here), and the held-out pool at k 8; single
     n10 differences under ±0.06 are noise.

---

## Reproduce

```bash
~/venv/bin/python scripts/exec_rft/build_pool.py                     # pool, holdout, build_report (server runs)
~/venv/bin/python scripts/exec_rft/sample_score.py --mode off --adapter c13c --out results/exec_rft/samples_off.jsonl
~/venv/bin/python scripts/exec_rft/sample_score.py --mode on --adapter c13c --out results/exec_rft/samples_on.jsonl
~/venv/bin/python scripts/exec_rft/report.py yield results/exec_rft/samples_off.jsonl results/exec_rft/samples_on.jsonl
CUDA_VISIBLE_DEVICES="" ~/venv/bin/python opcd.py prepare --config configs/opcd_exec_rft1.yaml
CUDA_VISIBLE_DEVICES=1 ~/venv/bin/python opcd.py smoke --config configs/opcd_exec_rft1.yaml --exec --steps 3 --max-new 1024
setsid nohup scripts/exec_rft/run.sh > logs/exec_rft/run.log 2>&1 &   # train, then gates for exec_rft1 r056 and c13c gaps
~/venv/bin/python scripts/exec_rft/gates_table.py > results/exec_rft/gates.md
```

Sampling needs rb1009 on vLLM at :3011 and :3012 with `c13c` hot-loaded (`scripts/vllm_eval_serve_rb1009.sh`,
`logs/exec_rft/vllm_3011_rb1009.sh`).
