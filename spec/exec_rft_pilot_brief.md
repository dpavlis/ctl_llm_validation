# Brief: execution-verified on-policy training pilot on c13c (exec-RFT)

**For the executing agent.** Read `CLAUDE.md` and `WORKLOG.md` first, then findings §3.28–§3.30 in
`spec/ctl2_training_findings.md`. Follow the shared-machine, git and correctness rules in `CLAUDE.md` exactly. Do not
commit; list what should be committed at the end.

## Why

- The largest real gap is generate without thinking: c13c's answers run correctly on the CloverDX server in 44 of 110
  gap-test samples (78 of 110 with thinking on); plain rebuilds 15–23% (§3.28, `results/exec/exec_scores.json`).
- The failures split evenly between code that does not compile or crashes (36) and code that runs but gives wrong rows
  (26). 89% of compile failures are 11 pretraining habits (`!~`, `raise`, `month` as a variable, `$out.1` in
  DataIntersection, `str2date` argument order, …; §3.29).
- Corpus sets of correct examples did not move these habits in two seeds (rb1012, §3.30). The only method that has
  moved a prior in this project is on-policy training against a signal (OPCD, `opcd.py`, §3.19).
- We now have a deterministic signal: `data/suite_v5/exec_score.py` runs an answer in a graph against a fixture and
  checks every output row. It has only been used for measurement. **This pilot uses it as the training signal:** sample
  the model's own answers, keep the ones that run correctly, train on them (rejection-sampling fine-tuning), and measure
  whether the execution pass rate rises without breaking the belief gates.

## Starting point

- **Model:** c13c = rb1009 export plus the OPCD adapter `data/opcd/c13c/round_015` (config `configs/opcd_c13c.yaml`,
  which also shows the replay/belief prompt mix and the teacher setup).
- **Server:** CloverDX MCP at `http://localhost:8083/clover/mcp/mcp`. Use the tool arguments exactly as
  `exec_score.py` does (`sandboxPath`, `sandboxCode="MiscExamples"`); the old `jobFile`/`filename` API is gone. Graphs go
  under `suite_v5/` in sandbox `MiscExamples`, never `DPOForge`. `exec_score.guard` enforces this; keep it.
- **Sampling:** vLLM, `scripts/vllm_eval_serve.sh` style, on a free GPU (check `nvidia-smi`; another user's vLLM sits
  on GPUs 0 and 2). Suite sampling: T 0.4, top_p 0.95, top_k 20, no penalties, no `max_tokens` (the 16k context
  minus the prompt; §3.29 hit a 400 error with `max_tokens` 16384).
- **Scorer:** `exec_score.score_one(call, manifest, code, label)` → `(status, detail)`; statuses `pass`, `wrong_rows`,
  `runtime_error`, `init_error`, `invalid`, `no_code`. Manifests come from `data/suite_v5/round2/graph_harness.build(test,
  spec)`; `data/corpus_authoring/verify_zerodate.py` shows how to build one from a component spec plus a fixture and
  write its input files to the sandbox.

## Step 1 — build an executable prompt pool that is not the evaluation suite

**Sources, in this order of preference:**
1. The corpus authors' runtime harnesses under `ctl_lora_training/sft_training_data/logs/*_runtime/` (about 1,100
   `.grf` graphs with input files and expected outputs for the SCD-2, Rollup accumulator, Rollup lifecycle, Normalizer
   multi-row, syntax pitfalls and zeroDate sets). Each set's `logs/CTL_LoRA_<set>_validation.json` and
   `logs/corpus_runtime_harness.py` document how a graph links to its SFT/DPO record and expected rows. Each such record
   gives a prompt (its user turn, unchanged — do not add hints), a component type, metadata and a fixture.
2. Any other corpus SFT record whose answer is one CTL block with declared metadata and a known component type, for
   which you can build a fixture by running the **reference** answer in a harness graph and recording its output rows
   as the expected output. Record which prompts got their fixture this way; a reference that fails to run is dropped.

**Rules:**
- Generate and fix-to-spec prompts only (the answer is code that can be run). Validate prompts are out.
- No suite overlap: drop any prompt with 5-gram Jaccard ≥ 0.30 (field names masked) against the prompts in
  `resources/ctl2_test_suite_v5.json`, `data/suite_v5/generate_rw.json` and `data/opcd/hard_cases*.jsonl`. Report the
  number dropped.
- Target 200–400 prompts after filtering. Hold out 40 at random, stratified by component type, as `holdout.jsonl`; they
  are never trained on.
- Write `data/exec_rft/pool.jsonl`, `data/exec_rft/holdout.jsonl` (fields: `id`, `source_file`, `source_id`,
  `component`, `task`, `prompt`, `manifest`), and `data/exec_rft/build_report.json` (counts by source, component and
  task; drops by reason).

## Step 2 — sample and score

- Sample **k = 8** answers per prompt from c13c in **both** thinking modes (same system prompt as the suite, see
  `configs/eval_vllm_opcd*` / `test.py`'s prompt path).
- Execution-score every answer. Keep the raw results: `results/exec_rft/samples_<mode>.jsonl` with prompt id, sample
  index, thinking text, answer, status, detail.
- Report, per mode: the status distribution over all samples; the per-prompt pass-count histogram (0..8); how many
  prompts are 0/8 and 8/8 (no signal); and the init-error causes tallied against the 11 causes of §3.29 (grep patterns
  are in `spec/ctl2_syntax_pitfalls_brief.md`).

## Step 3 — train one round

- **Data:** for each prompt with 1–7 passers in a mode, take up to 2 passing answers as SFT records in that mode (keep
  the model's own thinking text for thinking-on samples; thinking-off records get the empty thinking block, as
  `data/build_sft_rebuild.py` does). Build DPO pairs (passer vs a non-passing sample of the same prompt and mode,
  preferring `init_error` rejects) if at least 100 pairs exist; otherwise SFT only, and say so.
- **Replay:** keep c13c's belief prompts in the mix at ≥ 30% of the non-replay prompt weight, scored as in
  `configs/opcd_c13c.yaml` (the anchor rule, findings §5 step 3). Without it the belief gates regress (c11–c13).
- **Mechanics:** prefer extending `opcd.py` with an `exec` scorer so `prepare`/`train` work as before (fresh run name,
  `data/opcd/exec_rft1/`, config `configs/opcd_exec_rft1.yaml`, continue from the c13c adapter). If that does not fit,
  train with LlamaFactory through `train.py`-style configs and document the exact command. Do not reuse any existing
  run folder.
- Train one round (c13c's per-round hyperparameters). Optionally a second round sampled from the round-1 adapter if
  round 1 passes the gates.

## Step 4 — gates, against c13c on the same vLLM path

| gate | how | pass condition |
|---|---|---|
| execution pass rate, 11 suite-v5 gap tests | n10 both modes, **run twice** (continuation variance is unmeasured); `exec_score.py` | higher than c13c (0.44 off / 0.78 on) beyond the pooled CI |
| held-out pool pass rate | 40 prompts × 8 samples, both modes | higher than c13c on the same prompts |
| judge score on the same gap tests | `test.py` as usual | not lower |
| T40 / T42 below full | n20, twice | ≤ c13c (1/20, 7/20) |
| hard sets 1–3 | `data/opcd/eval_hard_cases.py`, hard set 3 split by error direction | no belief claims; set 3 nullable-wrong ≤ 14/40 |
| thinking-off validate ×9 | WRONG excluding T18/T22 | ≤ 2.5% |
| thinking on validate / fix / generate | n5 | within noise of c13c (0.850 / 0.826 / 0.970) |
| T54 thinking off | n20 | `$out.1`/`$out.2` ≤ 1/20 |

State n and a 95% confidence interval for every difference. Compare only within one judge and the vLLM path.

## Deliverables — write them so the findings can be checked

1. `spec/exec_rft_pilot_findings.md`, with these sections in this order:
   - **Pool:** the build_report numbers; how many fixtures came from corpus harnesses vs reference runs.
   - **Yield:** the Step-2 tables. Include the cause tally of init errors, so it can be compared with §3.29.
   - **Training data:** record counts by mode and task, DPO pair count, replay share, the exact config.
   - **Gates:** one table, the round-1 (and round-2) adapter against c13c, with n and CIs; the gap tests also broken down
     by status (`pass` / `wrong_rows` / `init_error` / …) per mode, as `results/exec/exec_scores.json` allows.
   - **Hand check:** read 10 random passing and 10 random failing round-1 answers from the gap tests and say what
     changed against c13c's answers to the same tests (fewer prior-habit errors? different logic? shorter thinking?).
   - **Indications**, answering these explicitly:
     1. Did the pass rate rise in the mode(s) trained, and did the gain come from fewer compile errors, fewer wrong rows,
        or both?
     2. Did any of the 11 compile causes move (counts before/after)?
     3. Did the held-out pool and the suite gap tests agree? If the pool rose and the suite did not, say so — it means
        the gain is pool-specific.
     4. Did anything regress (belief gates, validate WRONG, T54)?
     5. Is a second round worth running, and what would a full run need (more prompts, a different mix, GRPO)?
2. Raw data under `results/exec_rft/` and `data/exec_rft/` (not committed); configs and scripts in the repo.
3. A WORKLOG entry (result, decision, open points) and a one-paragraph §3.31 stub in the findings, numbers only, no
   recommendation beyond what the gates show.

## Do not

- Train on anything from suite v4/v5, `generate_rw.json` or the hard-case sets.
- Use the judge as the training signal in this pilot; it is for measurement only.
- Change rubrics, references or `ctl2-basics.md` (an owner ruling or live verification is needed, and every copy must be
  updated — see `CLAUDE.md`).
- Touch `~/venv`, other users' processes, or other sessions' uncommitted files.
