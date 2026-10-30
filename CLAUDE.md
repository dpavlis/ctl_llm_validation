# llama_train — instructions for Claude sessions

Qwen3.8-27B + LoRA fine-tuning for CTL2, the CloverDX transformation language: SFT/DPO rebuilds of a base model, then
on-policy context distillation (OPCD).

## Start here

- **Current candidate: valprec2** (adopted 2026-10-30, findings §3.38): the rb1009 export
  `/home/pavlisd/exports/qwen38_rb1009_sftdpo` plus the OPCD adapter `data/opcd/valprec2/round_155` (served name
  `valprec2`). Deploy with thinking on and the compile-and-retry loop. New lanes compare against it, not c13c.
- **`WORKLOG.md`:** the current state and dated decisions. Read it first. Add an entry when something worth recording
  happens (a result that changes the picture, a candidate or recipe decision, an owner ruling, a corrected fact, a corpus
  set accepted), and refresh "Where we are".
- **`spec/ctl2_training_findings.md`:** the details and numbers.
  - §3.x: runs;
  - §4: measurement;
  - §5: the recommended pipeline;
  - §6: open questions;
  - §7: owner rulings and compiler-verified CTL2 facts.
- **What is correct CTL2:**
  - `resources/ctl2-basics.md` (the judge's reference);
  - the frozen copies in `results/eval_snapshot_20261003/` (suite v4) and `results/eval_snapshot_20261013/` (suite v5),
    which are what evaluations actually use.
- **Corpus:** `ctl_lora_training/` is the training-data repository, a separate git repo on Bitbucket shared with others.
  Requests for new data are written as briefs in `spec/*_brief.md` and handed to the corpus authors by the owner.

## Main tools

| what | where |
|---|---|
| OPCD (prepare / train) | `opcd.py`, configs `configs/opcd_*.yaml`, runs in `data/opcd/<run>/` |
| canonical Stage 3 on a new base | `scripts/opcd_stage3.sh <export> <tag>` |
| OPCD run + standard gates | `scripts/opcd_gaps_run.sh`; rebuild gates `scripts/base_eval.sh` |
| suite evaluation | `test.py <config> [--tests …] [--runs N]`, vLLM mode (`mut.mode: vllm`) |
| re-judge stored answers | `data/rejudge_results.py` |
| run generated code on the server | `data/suite_v5/exec_score.py` (pass rate), `data/suite_v5/exec_retry.py` (compile-and-retry) |
| agentic harness (prompt → model → compile → run → error fed back → retry, execution-scored) | `agent_harness.py` (`pool` / `run` / `summary`), pools in `data/agent_harness/`, results in `results/agent_harness/`, `scripts/agent_harness_run.sh` |

## Shared machine

- **GPUs:** the machine is shared and there are no fixed GPUs. Check `nvidia-smi` first and use what is free.
  - For a job that needs two GPUs, prefer two that are close to each other (e.g. 0+1 or 2+3) if they are free; otherwise
    take what is available.
  - Never use a GPU another user's process is on, and never touch other users' processes.
  - Several scripts default to GPUs 1 and 3 (`opcd_gaps_run.sh`: `TRAIN_GPU` / `SAMPLE_GPU`; the vLLM serve scripts set
    `CUDA_VISIBLE_DEVICES`); override or adapt them to the GPUs you picked.
- **Long jobs:** put them in a `#!/bin/bash -l` script and start it with `setsid nohup … &`. The tool shell does not
  load `OPENAI_API_KEY` or wandb. Check that evaluation logs show `Verdict:` lines.
- **Stopping processes:** kill only your own PIDs, found with `ps -eo pid,user,args | awk …` on the python arguments.
  `pkill -f` patterns can match your own shell.
- **OPCD run names:** always use a fresh name. `opcd.py` silently resumes from existing `round_*` folders; run
  `opcd.py prepare` before `train`.
- **One lane per session:** check `git log` and the running processes before reusing a config or run folder that
  another session may own.
- **Ports:**
  - vLLM sampler: 3011 (script default);
  - vLLM eval server: 3012 (script default);
  - judge (gpt-6.1-sol): 127.0.0.1:9001;
  - CloverDX server (MCP: `ctl_validate`, graph runs): localhost:8083. After a reboot, start it by hand: `bash -lc
    ./bin/startup.sh` in `~/cloverserver/CloverDXServer.7.4.2.Tomcat-10.1.54`.
- **Graph runs:** use sandbox `MiscExamples`, under `suite_v5/` (the scorer's guard), never `DPOForge`.
- **`~/venv`:** do not modify it.

## Measurement rules

- **Generate is the primary objective.** Rank it on the execution pass rate (`exec_score.py`), not the judge score: the
  generate rubrics give partial credit to code that does not run. Validate gains must not cost generate.
- **Validate:** precision over recall. The gate is the judge-free ground truth (§3.35, §4.8): planted server-confirmed
  defects and clean controls, parser-scored with the suite's output-format prompt, both thinking modes
  (`scripts/harness_measurement/{gen_answers.py --format, score_validate.py}`; sets `data/agent_harness/validate_mutants.jsonl`
  and `validate_mutants_tweak.jsonl`). Report defect recall and the clean-code false-alarm rate (any `[ERROR]` on a
  control); the false-alarm rate is the precision number. Noise bands: recall ±0.05, false alarm ±0.08, one kind ±0.15.
  The judge suite stays for what the parser cannot see (explanations, multi-finding reviews); its WRONG rate
  (excluding T18/T22) is reported, but judge validate differences below 0.04 are seed noise (§3.34, §3.35).
- **T40/T42:** n20, run twice, before any gate decision. Report hard set 3 split by error direction.
- **Noise:** state the n and a confidence interval for every claimed difference.
  - Rebuild-to-rebuild (seed) variance is about ±0.06–0.07 on validate and the gap tests.
  - Single-seed rebuild comparisons below that are not evidence.
- **Comparisons:** only within one judge and one evaluation path (vLLM vs HF).

## Correctness rules

- **Source of CTL2 facts:** a fact must be compiler- or server-verified (`ctl_validate`, a graph run) or an owner ruling
  in findings §7. When unsure, probe the server rather than guess.
- **Changing rubrics or references:** needs an owner ruling or a live verification. Then update every copy: the
  `resources/` suites and `ctl2-basics.md`, both eval snapshots, the rule teachers (`configs/eval_rb1006_rulev*`), and the
  corpus reference `ctl_lora_training/references/CTL2_Reference_for_LLM_compact.md`.

## Git

- **Commit and push only when asked.**
- **Other sessions' work:** never commit another session's uncommitted edits (e.g. `self_distill.py`,
  `tests/test_self_distill.py`, `configs/opcd_c2.yaml`, `spec/explanation_budget_spec.md`); stage files explicitly.
- **Run artifacts:** `results/`, `logs/` and the OPCD run folders `data/opcd/<run>/` are not committed; configs, scripts
  and specs are.
- **In `ctl_lora_training/`:**
  - commit as `David Pavlis <david.pavlis@cloverdx.com>`;
  - `sft_training_data/logs/` is git-ignored, but files already tracked there are committed normally. `git add` prints
    a warning and exits non-zero, so don't chain the commit after it with `&&`;
  - DPO files must be named `CTL_LoRA_DPO_*.jsonl`.
