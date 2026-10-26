# rb1012 DPO isolation: the accumulator regression is not in the DPO pairs

Experiment for `spec/rb1012_dpo_isolation_brief.md`, run 2026-10-25/26. Summary in findings §3.32.

**Verdict:** the regression is **not** in the DPO phase. Re-running only the DPO phase on rb1011's SFT adapter reproduces
rb1011 (arm A), and adding the lifecycle pairs (B) or rb1012's whole DPO set (C) does not raise T22.B1 or lower T41.
rb1012's regression therefore sits in its SFT phase: either the 130 new SFT records or the SFT run's own variance. A
cheap check and an SFT ablation are proposed at the end.

## Setup

- **SFT adapter (all arms):** `~/LlamaFactory/saves/qwen38-27B-rb1011/2026-10-18-21-50-38_sft/checkpoint-2240`, the
  adapter rb1011's own DPO phase started from (its `training_config.yaml`).
- **DPO phase:** rb1011's DPO block unchanged: lr 5e-6 cosine, warmup 0.1, 1 epoch, batch 1 × accum 4, LoRA r64/α64,
  pref_beta 0.1, pref_ftx 0.1, sigmoid, cutoff 4160, seed 42, `enable_thinking: false`. Eval split
  `clover_dpo_eval_rb1011` (identical to rb1012's), sha256 `acc7824d…`.
- **Configs:** `configs/qwen38_rb1011_dpoiso_{A,B,C,D}.yaml`, which are rb1011's config except `run_name`, the DPO
  dataset and `export_dir` (`~/exports/qwen38_rb1011_dpoiso_<arm>_sftdpo`).
- **Command per arm** (from `~/LlamaFactory`, one GPU each; `scripts/dpoiso_run.sh` runs it):

  ```
  CUDA_VISIBLE_DEVICES=<g> ~/venv/bin/python ~/llama_train/train.py ~/llama_train/configs/qwen38_rb1011_dpoiso_<arm>.yaml \
      --sft-adapter /home/pavlisd/LlamaFactory/saves/qwen38-27B-rb1011/2026-10-18-21-50-38_sft/checkpoint-2240 --skip-post-sft
  ```

  `train.py` with `--sft-adapter` reproduces the DPO phase directly: it merges the SFT adapter, trains a fresh DPO LoRA
  and exports base + SFT + DPO. No direct LlamaFactory command was needed.

- **DPO data** (`data/build_dpoiso.py` → `data/sft_rebuild_20261025_dpoiso/`, `build_report.json`; registered as
  `clover_dpo_dpoiso_<arm>`). rb1012's built DPO file is exactly rb1011's 2083 pairs plus the 65 new ones, with the old
  pairs in the same order (asserted by the build script). Arms are cut from it:

  | arm | pairs | lifecycle | syntax | sha256 | steps | train loss |
  |---|---|---|---|---|---|---|
  | rb1011 (original run) | 2083 | 0 | 0 | `4218d293…` | 521 | 0.3643 |
  | **A** control | 2083 | 0 | 0 | `4218d293…` (rb1011's file, byte-identical) | 521 | 0.3670 |
  | **B** | 2108 | 25 | 0 | `24a40e87…` | 527 | 0.3659 |
  | **C** | 2148 | 25 | 40 | `4a92bfe4…` (= rb1012's file) | 537 | 0.3751 |
  | D | 2088 | 5 | 0 | — | not run | — |

  D (A + the 5 lifecycle pairs `source_index` 4, 5, 12, 13, 19, category `nullable_accumulator_claimed_zero`) was built
  and configured but **not run**. The brief makes it conditional on B showing an effect, and B showed none.

- **Evaluation:** each export served by vLLM on its training GPU (`scripts/vllm_eval_serve.sh` rewritten per arm, ports
  3021–3023); `test.py` vLLM path, judge gpt-6.1-sol at 127.0.0.1:9001, as for the stored rb1011/rb1012 runs, so those
  are reused.
  - thinking off: `--validate-only --runs 5` × 9, which gives T22 n45 and validate n495;
  - thinking on: T41 `--runs 25`; T40, T42 `--runs 20`;
  - hard set 3: `data/opcd/eval_hard_cases.py <run>_set3 --file hard_cases3.jsonl --k 4` (thinking off, student role).

  The configs are `configs/eval_rb1011_dpoiso_<arm>_vllm_{on,off}.yaml` and `configs/opcd_hardeval_rb1011_dpoiso_<arm>.yaml`.
  The table is from `data/dpoiso_table.py`, which also writes `results/dpoiso/table.json`. Raw results are in
  `results/results_qwen38_rb1011_dpoiso_*` and `data/opcd/hard_eval/rb1011_dpoiso_*_set3/`.

## Results

Count or mean (n). Every arm row gives the difference against arm A with its 95% CI: Newcombe for proportions, Welch for
means. The validate WRONG share is a share of findings, which cluster by answer, so its CI is optimistic.

| measure | rb1011 | rb1012 | rb1012s2 | **A** | **B** | **C** |
|---|---|---|---|---|---|---|
| T22 off: B1 WRONG "starts at zero / has a default" | 20/45 | **36/45** +.38 [+.18, +.54] | **36/45** +.38 [+.18, +.54] | **19/45** | 15/45 −.09 [−.28, +.11] | 18/45 −.02 [−.22, +.17] |
| T22 off: B4 caught | 43/45 | 32/45 −.29 [−.43, −.15] | 29/45 −.36 [−.50, −.21] | 45/45 | 45/45 +.00 [−.08, +.08] | 44/45 −.02 [−.12, +.06] |
| T22 off: B5 caught | 40/45 | 32/45 −.07 [−.24, +.11] | 34/45 −.02 [−.19, +.15] | 35/45 | 42/45 +.16 [+.01, +.30] | 42/45 +.16 [+.01, +.30] |
| T41 on: mean | 0.824 (25) | 0.756 −.08 [−.18, +.02] | 0.720 −.11 [−.18, −.04] | **0.832 (25)** | 0.794 −.04 [−.14, +.06] | 0.852 +.02 [−.06, +.10] |
| T41 on: B2 WRONG | 16/25 | 17/25 +.08 [−.18, +.32] | 25/25 +.40 [+.19, +.59] | 15/25 | 17/25 +.08 [−.18, +.32] | 13/25 −.08 [−.33, +.18] |
| hard 3: nullable field said to start at zero | 14/40 | 16/40 +.05 [−.16, +.25] | 11/40 −.07 [−.27, +.13] | 14/40 | 17/40 +.08 [−.13, +.27] | 14/40 +.00 [−.20, +.20] |
| hard 3: non-nullable said to start null | 3/20 | 0/20 −.15 [−.36, +.04] | 3/20 +.00 [−.23, +.23] | 3/20 | 1/20 −.10 [−.31, +.11] | 2/20 −.05 [−.27, +.17] |
| hard 3: metadata default wrong | 5/20 | 4/20 −.10 [−.35, +.17] | 8/20 +.10 [−.18, +.36] | 6/20 | 7/20 +.05 [−.23, +.32] | 5/20 −.05 [−.31, +.22] |
| validate off ×9 excl. T18/T22 | 0.941 (495) | 0.926 −.01 [−.03, +.01] | 0.944 +.01 [−.01, +.03] | 0.935 (495) | 0.952 +.02 [−.00, +.04] | 0.957 +.02 [+.00, +.04] |
| validate off: WRONG findings | 26/1149 (2.3%) | 23/1151 (2.0%) | 39/1145 (3.4%) | 24/1155 (2.1%) | 15/1143 (1.3%) | 11/1142 (1.0%) |
| T40 on below full | 8/20 | 4/20 | 3/20 | 8/20 | 9/20 | 6/20 |
| T42 on below full | 17/20 | 12/20 | 20/20 | 18/20 | 13/20 | 17/20 |

Also: B1 WRONG answers that state an explicit zero/default value (regex over the answer text), against those that only
omit the null mechanism. The remainder say "uninitialized" or "undefined" without naming null, which the rubric also
counts WRONG.
- rb1011 13 of 20;
- rb1012 17 of 36;
- rb1012s2 29 of 36;
- A 15 of 19;
- B 10 of 15;
- C 15 of 18.

## Hand check: arm B, the first 10 T22 thinking-off answers with B1 WRONG

The sentence quoted is the one that carries the mechanism.

| # | quote | kind |
|---|---|---|
| 1 | "`acc.count = acc.count + 1` reads an accumulator field that `initGroup()` does not initialize." (no mechanism) | omission |
| 2 | "`count` starts at the metadata default of `0`, so this particular group happens to accumulate correctly" | zero claim |
| 3 | "reads an accumulator field that `initGroup()` does not initialize" (calls it undefined) | omission |
| 4 | "`initGroup()` does not initialise `acc.count`" (the judge reads the body as claiming zero) | zero claim |
| 5 | "the first `updateGroup()` call for a group reads an uninitialized `count` value" | omission |
| 6 | "The metadata does not supply a default, so the first `acc.count + 1` reads an uninitialized accumulator field." | omission |
| 7 | "`count` is an `integer`, whose default is `0`, so the first group can run; later groups retain the previous group's count" | zero claim + no reset |
| 8 | "The accumulator field is not reset implicitly, so the first `updateGroup()` call increments an uninitialized count" | no reset |
| 9 | "starts at its type default" (judge's note; recommends `acc.count = 0`) | zero claim |
| 10 | "`count` is an integer field, so its metadata default is `0`; this is not a null addition" | zero claim |

**Comparison with the rejected answers of the 5 minimal lifecycle pairs**, for example:
- "starts at zero before every group, using the integer-variable default";
- "starts at zero for each group because a numeric accumulator uses its type baseline even when nullable metadata…";
- "its per-group reset value is zero";
- "Its metadata reset value is zero".

Two of B's answers (2, 10) use similar words ("metadata default of 0"). But arm A, which never saw these pairs, makes the
same claim at the same rate: 15 of its 19 B1 WRONG answers state a zero/default value, against B's 10 of 15. There is no
likelihood-displacement signature. The zero claim is rb1011's own pre-existing habit, and the pairs neither raise it nor
copy their wording into the model.

## Indications

1. **Arm A reproduces rb1011.** Every measure is within a few points: B1 WRONG 19 against 20/45, B4 45 against 43, T41
   0.832 against 0.824, hard set 3 14/3/6 against 14/3/5, validate 0.935 against 0.941. The training loss is 0.3670
   against 0.3643, so the run is not bit-identical (nondeterministic kernels), but the outcome is.
   - The largest A-to-rb1011 gap is B5 caught (35 against 40/45, +0.11 [−0.05, +0.26]).
   - The DPO phase adds far less noise than the ±0.06–0.07 seed variance of a full rebuild, which therefore comes
     mainly from SFT.
2. **The lifecycle DPO pairs alone (B) do not reproduce the regression.** T22.B1 is 15/45 against A's 19, not ~36. T41
   is −0.04 [−0.14, +0.06], inside noise, against rb1012's −0.08 / −0.11. B's B5 catching rises (+0.16 [+0.01, +0.30]),
   the one effect in the direction the set was meant to teach.
3. **The syntax set's DPO adds nothing (C against B).** C, which is rb1012's exact DPO data, is at A's level on every
   accumulator measure: B1 18/45, T41 0.852, hard set 3 14/2/5. The thinking-off validate WRONG share is lowest in C
   (1.0%, against A's 2.1%, CI −0.02 to −0.00).
4. **D was not run.** B showed no effect, so the 5 minimal pairs cannot be the cause.
5. **Verdict: not in the DPO pairs, so in the SFT phase.**
   - The minimal-pair DPO recipe is not implicated here and needs no change on this evidence. Separately, offline DPO
     still shows no measurable gain on its own target (B4/B5 are unchanged; only B5 moves).
   - The remaining question is whether rb1012's SFT phase regressed because of its 130 new SFT records or by SFT-seed
     luck:
     - rb1011 is a single SFT seed;
     - both rb1012 seeds (42, 7) land at 36/45, which argues for the records;
     - but the two rb1012 seeds share the data, so they cannot separate the two.

## What would settle it (proposed, not run)

GPU-hour figures from rb1012's runs: SFT 17,276 s ≈ 4.8 h, DPO ≈ 0.65 h, export ≈ 0.1 h, these evals ≈ 0.5 h, all on
one GPU.

1. **Cheap confirmation, about 1.3 GPU-h:** rb1012's SFT adapter plus rb1011's DPO data (arm A on rb1012's SFT). If
   T22.B1 stays around 36/45, the regression is carried by the SFT adapter, as this experiment implies.
2. **rb1011 seed control, about 6 GPU-h:** a full rb1011 rebuild with seed 7.
   - If it lands near 36/45, rb1011 (20/45) was the lucky seed, and the lifecycle/syntax sets are not to blame.
   - If it stays near 20, the SFT records are the cause.
3. **SFT ablation, only if item 2 points at the records, about 24 GPU-h:**
   - rb1011 + lifecycle SFT only;
   - rb1011 + syntax SFT only;
   - two seeds each: 4 runs × ~6 GPU-h, roughly 12 h wall on two GPUs.

Items 1 and 2 together cost about 7 GPU-h and decide whether the ablation is needed at all.

## Operational notes

- `scripts/dpoiso_run.sh` first hung after arms A/B for about 1.5 h. Its `wait` also waited for the vLLM server it had
  started. It now waits only for the evaluation jobs. This is the same trap as the earlier rb-run scripts; any new eval
  script that starts a server must not use a bare `wait`.
- **The shared run-history log `logs/Qwen3.8-27B.yaml` was torn by concurrent writers** (two `train.py` runs and several
  `test.py` runs appending at once, about 21:16).
  - From then on, every `train.py` and `test.py` run failed at its final log append (results were already saved).
  - The leftover tail was cut and the backup kept as `logs/Qwen3.8-27B.yaml.bak_20261025_torn`.
  - Arm C's history entry is missing from the log; its numbers are in this file.
  - `train.py`/`test.py` rewrite this file without a lock, so parallel runs will tear it again.
