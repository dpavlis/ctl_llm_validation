# Brief: isolate the rb1012 accumulator regression — is it the DPO pairs?

**For the executing agent.** Read `CLAUDE.md` and `WORKLOG.md` first, then findings §3.30 and §3.27 in
`spec/ctl2_training_findings.md`. Follow the shared-machine, git and correctness rules in `CLAUDE.md`. Do not commit;
list what should be committed at the end.

## Why

rb1012 = rb1011's recipe plus two corpus sets: Rollup lifecycle validate (50 SFT + 25 DPO) and CTL2 syntax pitfalls
(80 SFT + 40 DPO). In **both** seeds it regressed on the Rollup accumulator explanation:

| measure | rb1011 | rb1012 | rb1012s2 |
|---|---|---|---|
| T22 thinking off, B1 WRONG "count starts at zero / has a default" (n45) | 20 | 36 | 36 |
| T41 thinking on (n25) | 0.824 | 0.756 | 0.720 |

The lifecycle set's text and code were checked and look correct (§3.30 finding 3). Two hypotheses remain:
- **H1 — the DPO pairs.** The lifecycle set has 5 minimal pairs whose rejected answer explains a nullable accumulator
  field as starting at 0, with the rest of the answer identical to the chosen one. Offline DPO has never shown a
  measurable gain in this project (dpo1, dporep, dpodef1), and near-identical pairs are a known way to raise the
  likelihood of the rejected phrasing (likelihood displacement). Every corpus set ships 25–40 such pairs.
- **H2 — the SFT records.** More endorsed Rollup code doing arithmetic on non-nullable accumulator fields without
  initialisation, which the model generalises to "accumulators start at zero".

A full ablation rebuild costs about 5 h × 2 seeds per arm. The DPO phase alone takes about 30 min, and rb1011's SFT
adapter is on disk, so H1 can be tested first and cheaply.

## Starting point

- rb1011's run: `~/LlamaFactory/saves/qwen38-27B-rb1011/2026-10-18-21-50-38_sft` (SFT adapter) and `…_dpo`.
  Config: `configs/qwen38_rb1011.yaml` (the DPO block is what to reproduce: lr 5e-6, 1 epoch, batch 1 × accum 4,
  pref_beta 0.1, pref_ftx 0.1, same LoRA dims, `seed` as set there).
- `train.py` supports `--sft-adapter PATH` (implies `--skip-sft`) and `--skip-post-sft` (always pass it). The DPO
  data is registered in `~/LlamaFactory/data/dataset_info.json` as `clover_dpo_rb1011` /
  `clover_dpo_eval_rb1011`; the files live in `~/LlamaFactory/data/` and were built into
  `data/sft_rebuild_20261018_rb1011/`. rb1012's DPO data is in `data/sft_rebuild_20261022_rb1012/` (registered as
  `clover_dpo_rb1012`); it is rb1011's pairs plus the 65 new ones.
- The two new sets' DPO files: `ctl_lora_training/sft_training_data/CTL_LoRA_DPO_rollup_lifecycle_validate.jsonl`
  (25) and `CTL_LoRA_DPO_syntax_pitfalls.jsonl` (40).
- Evaluation on the vLLM path (`scripts/vllm_eval_serve.sh`, `test.py` with `mut.mode: vllm`; configs
  `configs/eval_rb1012*_vllm_{on,off}.yaml` show the pattern); judge gpt-6.1-sol at 127.0.0.1:9001. Hard sets:
  `data/opcd/eval_hard_cases.py`.

## Arms

All arms start from the **same rb1011 SFT adapter** and run **only the DPO phase** with rb1011's DPO hyperparameters,
then export.

| arm | DPO data | tests |
|---|---|---|
| **A** control | rb1011's pairs, unchanged | does a re-run of the DPO phase reproduce rb1011's numbers? (This bounds the DPO-phase noise; it is needed to read B–D.) |
| **B** | A + the 25 lifecycle pairs | H1 |
| **C** | A + the 25 lifecycle + 40 syntax pairs (= rb1012's DPO data) | H1 for the full rb1012 DPO set |
| **D** (optional, if B shows an effect) | A + only the 5 lifecycle pairs whose rejected answer says the field starts at 0 (category "explains a nullable accumulator field as starting at 0" in the set's validation log) | narrows H1 to the minimal pairs |

Register each DPO file under a new dataset name; use fresh configs `configs/qwen38_rb1011_dpoiso_{A,B,C,D}.yaml` and
fresh export dirs. If the DPO phase is not reproducible from `train.py` with `--sft-adapter`, run the LlamaFactory DPO
stage directly with the same parameters and document the exact command.

## Measurements, per arm, plus rb1011 and rb1012 (both seeds) from stored results where they exist

| measure | how |
|---|---|
| T22 thinking off | n45; count B1 WRONG ("starts at zero / has a default"), and B4/B5 caught (the missing functions) |
| T41 thinking on | n25; mean, and B2 WRONG count |
| hard set 3 | by error direction: nullable field said to start at zero / non-nullable said to start null / metadata default wrong (§3.27 table) |
| thinking-off validate ×9 | score and WRONG excluding T18/T22 |
| T40 / T42 below full | n20 (one run is enough here; this is a regression check, not a gate) |

Give n and a 95% confidence interval for each difference against arm A. Re-use stored rb1011/rb1012 results only if
they were judged by the same judge on the vLLM path; otherwise rerun.

## Deliverables — write them so the findings can be checked

1. `spec/rb1012_dpo_isolation_findings.md`, with:
   - **Setup:** the adapter path, the exact DPO data per arm (pair counts, file hashes), the commands.
   - **Results:** one table, arms A–D against rb1011, rb1012, rb1012s2, with n and CIs.
   - **Hand check:** for arm B (or the arm that moved), read 10 T22 thinking-off answers with a B1 WRONG finding and
     quote the sentence; say whether the wording resembles the rejected answers of the lifecycle DPO pairs (that is
     the likelihood-displacement signature).
   - **Indications**, answering explicitly:
     1. Does arm A reproduce rb1011 (within what spread)? If not, the DPO phase itself is noisier than assumed; say by
        how much.
     2. Does adding the lifecycle DPO pairs alone (B) reproduce T22.B1 ≈ 36/45 and the T41 drop?
     3. Does the syntax set's DPO (C vs B) add anything?
     4. If D was run: are the 5 minimal pairs sufficient?
     5. Verdict: regression in the DPO pairs (→ recommend dropping minimal-pair DPO from the set recipe and say what
        to replace it with), in the SFT records (→ estimate the SFT ablation: arms and GPU hours), or not reproducible
        (→ rb1011 was the lucky seed; say what evidence would settle it).
2. Raw results under `results/` (not committed); the configs in the repo.
3. A WORKLOG entry and a short §3.31/§3.32 stub in the findings with the table and verdict.

## Do not

- Re-run SFT; the point is the DPO phase alone.
- Change rubrics, references or `ctl2-basics.md`.
- Touch `~/venv`, other users' processes (GPUs 0 and 2 are in use by another user's vLLM), or other sessions'
  uncommitted files.

---

## Addendum (2026-10-26): the rb1011 seed-7 rebuild is a variance control, not only an rb1012 question

The DPO-only arms (`spec/rb1012_dpo_isolation_findings.md`) cleared the DPO pairs and showed the regression travels with
rb1012's SFT adapter. The remaining question, SFT records or SFT seed, is decided by the rb1011 seed-7 rebuild
(`configs/qwen38_rb1011s2.yaml`, `scripts/dpoiso_run.sh` arm S, started 2026-10-26 on GPU 1). Whichever way it lands,
the lifecycle and syntax sets stay out of the recipe (no gain in two seeds, §3.30), and the 24 GPU-h SFT ablation is
**not** to be run on this evidence.

**What the run is for:** the second rebuild-to-rebuild variance pair on the current recipe. Every rebuild comparison
rests on one pair (rb1009 vs rb1009s2, §3.27), which the 10-21 review called weak (one pair; most of its validate gap is
one test). rb1011 vs rb1011s2 doubles that evidence, and §3.32 already showed the DPO phase contributes almost no noise,
so the pair measures SFT-seed variance.

**Report, beyond the arm-S measurements the script runs (T22 n45 off, T41 n25 on, T40/T42 n20, validate off ×9, hard
set 3 by direction):**
1. the suite-v5 gap tests at n10 in both modes with `exec_score.py` (pass rate), and the thinking-on full suite at n5
   (validate / fix / generate), so the pair covers the same gates as the rb1009 pair;
2. a table **rb1011 | rb1011s2 | spread**, next to **rb1009 | rb1009s2 | spread**, for every gate — the spread per gate
   is the number to carry forward;
3. the T22.B1 verdict on the rb1012 question (near 36/45: rb1011 was the lucky seed; near 20: the SFT records), stated
   as a by-product;
4. an update to findings §4.7's variance rule from the two pairs: the per-gate spread to treat as noise for single-seed
   rebuild comparisons, replacing the single "±0.06–0.07".
