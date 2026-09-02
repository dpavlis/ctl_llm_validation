# llama_train — CTL2 / CloverDX model fine-tuning toolkit

Tooling to fine-tune, evaluate, and generate training data for an LLM that
writes **CTL2** (CloverDX's transformation language). The pipeline covers the
full loop:

1. **Train** a base model with SFT and DPO, then export merged weights
   ([train.py](#trainpy--sft--dpo--export-pipeline)).
2. **Evaluate** the exported model against a fixed test suite with an LLM
   judge ([test.py](#testpy--evaluation)).
3. **Talk to** the exported model interactively for manual spot-checks
   ([chat.py](#chatpy--interactive-chat)).
4. **Generate on-policy DPO preference data** by sampling completions from
   the model, executing them for real in CloverDX, and judging the results
   ([dpo_forge.py](#dpo_forgepy--on-policy-dpo-data-generation)).
5. **Generate self-correction SFT data** by having the model retry its own
   mistakes after judge feedback ([mut_validate.py](#mut_validatepy--mut-self-correction-data-generation)).

Everything is config-driven (YAML in `configs/`) so experiments are
reproducible and diffable, and results/metrics are appended to shared,
per-base-model run logs in `logs/`.

---

## Directory layout

```
llama_train/
├── train.py          # SFT → DPO → Export pipeline driver
├── test.py            # Evaluation of an exported model against a test suite (LLM judge)
├── chat.py             # Interactive terminal chat with an exported model
├── dpo_forge.py         # On-policy DPO preference-pair generator (CLI entrypoint)
├── dpo_forge/            # dpo_forge implementation, staged pipeline (loader → generator →
│                           #   setup agent → runner → judge → pairing → output)
├── mut_validate.py     # MUT self-correction / judge-fix SFT data generator
├── debug.py             # Ad-hoc script: per-token top-k logits for a fixed prompt
├── configs/           # One YAML file per model / experiment / eval / chat / forge run
├── resources/         # Test suites (ctl2_test_suite*.json) and CTL2 reference docs
├── spec/              # Design docs / specs for the dpo_forge pipeline
├── data/              # sft_input/ (curated SFT examples), dpo/ (forged DPO output + state db)
├── tests/             # Unit tests (pytest)
├── logs/              # Auto-created; one YAML run log per base model (shared by train.py/test.py)
│   └── Qwen3-8B.yaml
└── results/           # Auto-created by test.py; per-run JSON results + Markdown summaries
```

All training outputs (checkpoints, loss curves, exported weights) are written
under `saves/` inside the LlamaFactory directory, **not** inside `llama_train/`.

---

## train.py — SFT → DPO → Export pipeline

A config-driven script that runs **SFT → DPO → Export** using
[LlamaFactory](https://github.com/hiyouga/LLaMA-Factory), then appends the
results to a per-model run log so you can track what each config change
produced.

### Prerequisites

- LlamaFactory installed somewhere on disk with `llamafactory-cli` on `PATH`
- Python ≥ 3.10 with `pyyaml` available (already present in the LlamaFactory venv)
- The `LLAMAFACTORY_DIR` environment variable pointing to the LlamaFactory
  root (default: `~/LlamaFactory`).  The script runs every training command
  with that directory as the working directory, so relative paths like
  `dataset_dir: data` and `output_base: saves` resolve correctly.

```bash
# Set once in your shell profile, or per-invocation:
export LLAMAFACTORY_DIR=~/LlamaFactory

python ~/llama_train/train.py ~/llama_train/configs/my_config.yaml
```

If `LLAMAFACTORY_DIR` is not set the script defaults to `~/LlamaFactory` and
will exit immediately with a clear error if that directory does not exist.

---

### Quick start

```bash
# 1. Set the LlamaFactory directory (add to ~/.bashrc or ~/.zshrc to make permanent)
export LLAMAFACTORY_DIR=~/LlamaFactory

# 2. Copy the example config and edit it for your model and datasets
cp ~/llama_train/configs/example.yaml ~/llama_train/configs/my_run.yaml
$EDITOR ~/llama_train/configs/my_run.yaml

# 3. Preview every command that would be run (nothing is executed)
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml --dry-run

# 4. Run the full pipeline
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml
```

---

### Config file reference

Each config file is a single YAML document with four logical sections.

#### Top-level (pipeline meta)

| Key | Required | Description |
|-----|----------|-------------|
| `run_name` | yes | Becomes a subfolder under `output_base`. Use something descriptive like `qwen3-clover-v2`. |
| `output_base` | yes | Root directory for all run outputs, relative to where you invoke the script. Typically `saves`. |

#### Common section

Everything at the top level that is **not** one of the four reserved keys
(`run_name`, `output_base`, `sft`, `dpo`, `export`) is merged into both the
SFT and DPO training configs.  Put shared hyperparameters here.

```yaml
model_name_or_path: Qwen/Qwen3-8B
finetuning_type: lora
template: qwen3_nothink
fp16: true
lora_target: "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
lora_dropout: 0.05
loraplus_lr_ratio: 1
optim: adamw_torch
weight_decay: 0.05
max_grad_norm: 1.0
lr_scheduler_type: constant_with_warmup
warmup_steps: 80
per_device_train_batch_size: 2
gradient_accumulation_steps: 6
dataset_dir: data
report_to: wandb
```

#### `sft:` section

Keys here are merged **on top of** the common section for the SFT phase.
They can introduce new keys or override common values.

| Key | Notes |
|-----|-------|
| `dataset` | Comma-separated dataset name(s) from `dataset_dir/dataset_info.json` |
| `eval_dataset` | Dataset used for evaluation loss during SFT |
| `learning_rate` | Typically higher than DPO, e.g. `5.0e-5` |
| `lora_rank` / `lora_alpha` | LoRA dimensions for SFT. `lora_alpha = 2 × lora_rank` is a common starting point. |
| `num_train_epochs` | Number of epochs |
| `cutoff_len` | Token context length |
| `eval_strategy` | `steps` to evaluate every `eval_steps` steps |
| `eval_steps` | How often to evaluate |
| `load_best_model_at_end` | Set `true` to restore the best checkpoint after SFT finishes. The pipeline automatically picks that checkpoint as the DPO starting point. |
| `metric_for_best_model` | Usually `eval_loss` |
| `create_new_adapter` | Forced `true` by the script; listed here only for clarity |

```yaml
sft:
  dataset: "sft_train_data,sft_val_data"
  eval_dataset: sft_eval_data
  cutoff_len: 1860
  learning_rate: 5.0e-5
  num_train_epochs: 2.0
  max_samples: 100000
  per_device_eval_batch_size: 1
  lora_rank: 64
  lora_alpha: 128
  eval_strategy: steps
  eval_steps: 50
  load_best_model_at_end: true
  metric_for_best_model: eval_loss
```

#### `dpo:` section

Keys here are merged on top of the common section for the DPO phase.

| Key | Notes |
|-----|-------|
| `dataset` | DPO preference dataset (chosen / rejected pairs) |
| `learning_rate` | Typically much lower than SFT, e.g. `5.0e-6` |
| `lora_rank` / `lora_alpha` | Can be freely different from SFT — DPO always starts a fresh LoRA on the SFT-merged base. |
| `pref_beta` | KL penalty coefficient (default `0.1`; lower = more deviation from reference) |
| `pref_loss` | Loss type: `sigmoid` (standard DPO), `orpo`, or `simpo` |
| `pref_ftx` | SFT regularisation weight mixed into DPO loss. `0` disables it. |
| `adapter_name_or_path` | Overrides automatic SFT adapter discovery. Rarely needed — see [Experimenting with DPO](#experimenting-with-dpo-reusing-an-sft-run). |

```yaml
dpo:
  dataset: dpo_preference_data
  cutoff_len: 1850
  learning_rate: 5.0e-6
  num_train_epochs: 2.0
  max_samples: 100000
  lora_rank: 64
  lora_alpha: 64
  pref_beta: 0.1
  pref_ftx: 0
  pref_loss: sigmoid
```

#### `export:` section

Controls the final model merge.  The script sets safe defaults for every key,
so this section only needs entries you want to override.

| Key | Default | Description |
|-----|---------|-------------|
| `export_dir` | auto | Override the auto-generated export path |
| `export_size` | `5` | Shard size in GB |
| `export_device` | `cpu` | `cpu` or `auto` |
| `export_legacy_format` | `false` | `false` = safetensors |

```yaml
export:
  export_size: 5
  export_device: cpu
  export_legacy_format: false
  # export_dir: /mnt/models/my-final-model   # optional fixed path
```

---

### What the script does

```
SFT training
  └─ creates a fresh LoRA adapter from scratch
  └─ writes checkpoints to  saves/<run_name>/<timestamp>_sft/
  └─ writes training_config.yaml there (exact config used, for reproducibility)
  └─ picks best checkpoint (lowest eval_loss if load_best_model_at_end: true)

DPO training
  └─ merges SFT adapter permanently into base model weights (in-memory)
  └─ creates a fresh LoRA adapter on the merged base — can use different rank/alpha
  └─ trains that adapter with the DPO preference objective
  └─ writes checkpoints to  saves/<run_name>/<timestamp>_dpo/

Export
  └─ merges both adapters sequentially: base → SFT adapter → DPO adapter
  └─ writes sharded safetensors to  saves/<run_name>/<timestamp>_export/

Run log
  └─ appends results to  llama_train/logs/<ModelName>.yaml
```

#### Why both adapters are supplied at export

DPO trains a **fresh** LoRA on the SFT-merged base (i.e. `create_new_adapter: true`).
This means the DPO adapter is relative to the SFT-merged weights, not to the
original base model.  Exporting with only the DPO adapter would produce an
incorrect model.  The script therefore passes both adapters as a
comma-separated pair — `sft_checkpoint,dpo_checkpoint` — and LlamaFactory
merges them sequentially:

```
original base  →  merge SFT LoRA  →  merge DPO LoRA  →  final weights
```

The benefit of this design: the DPO phase can use a completely different
`lora_rank` and `lora_alpha` from SFT, since it always starts from a clean
slate on the SFT-merged base.

---

### Command-line reference

```
python train.py <config_file> [options]
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Print every config YAML and command that would be executed. Nothing is written or run. |
| `--skip-sft` | Skip the SFT phase and go straight to DPO. The SFT adapter is resolved automatically — see priority order below. |
| `--skip-dpo` | Skip the DPO phase. Export will merge only the SFT adapter. |
| `--skip-export` | Skip merging and exporting the model. |
| `--sft-adapter PATH` | Explicit path to an SFT adapter or checkpoint to use as the DPO starting point. Implies `--skip-sft`. |
| `--timestamp TS` | Reuse a previous run's timestamp (format `YYYY-MM-DD-HH-MM-SS`) to keep output paths consistent when resuming manually. |
| `--resume` | Find the most recent run for this `run_name`, skip completed phases, and continue any unfinished phase from its last checkpoint. |

#### SFT adapter resolution for DPO

When `--skip-sft` is used, the script finds the SFT adapter in this order:

| Priority | Source | How to trigger |
|----------|--------|----------------|
| 1 | `--sft-adapter PATH` on the command line | Explicit path — use when pointing at a different run or a specific checkpoint |
| 2 | `adapter_name_or_path` in the `dpo:` config section | Fixed adapter baked into the config file |
| 3 | Best checkpoint from the latest `*_sft` directory under `run_dir` | **Default** — just pass `--skip-sft` with nothing else |

---

### Output directory structure

For a run with `run_name: qwen3-clover` started at `2026-05-10-14-30-00`:

```
saves/
└── qwen3-clover/
    ├── 2026-05-10-14-30-00_sft/
    │   ├── training_config.yaml   ← exact LlamaFactory config used
    │   ├── trainer_state.json     ← loss history, best checkpoint
    │   ├── checkpoint-50/
    │   ├── checkpoint-100/
    │   └── ...
    ├── 2026-05-10-14-30-00_dpo/
    │   ├── training_config.yaml
    │   ├── trainer_state.json
    │   └── checkpoint-N/
    └── 2026-05-10-14-30-00_export/
        ├── export_config.yaml
        ├── model-00001-of-00003.safetensors
        └── ...
```

---

### Recipes

#### Full pipeline (default)

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml
```

#### Preview without running anything

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml --dry-run
```

#### Experimenting with DPO — reusing an SFT run

Once SFT is done, you can run multiple DPO experiments without repeating SFT.
The simplest form — no extra flags needed, the script finds the latest SFT
checkpoint automatically:

```bash
# First full run
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml

# Vary DPO settings in my_run_dpo_v2.yaml, reuse SFT automatically
python ~/llama_train/train.py ~/llama_train/configs/my_run_dpo_v2.yaml --skip-sft

# Try another DPO variant
python ~/llama_train/train.py ~/llama_train/configs/my_run_dpo_v3.yaml --skip-sft
```

Each DPO experiment gets its own timestamped output directory and its own
entry in the run log with a diff showing exactly what changed.

To target a specific SFT checkpoint rather than the latest one:

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run_dpo_v2.yaml \
    --sft-adapter saves/qwen3-clover/2026-05-10-14-30-00_sft/checkpoint-800
```

#### Resuming an interrupted run

If training was killed mid-run (server restart, OOM, manual Ctrl+C), use
`--resume` to pick up where it left off:

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml --resume
```

The script will:
1. Find the most recent timestamped run directory for this `run_name`
2. Check each phase and print its status:

```
[resume] Found run 2026-05-10-14-30-00
[resume] SFT    : complete — best checkpoint: saves/.../checkpoint-800
[resume] DPO    : interrupted — resuming from checkpoint-50
[resume] Export : not done — will run
```

3. Skip completed phases, continue interrupted ones from the last saved
   checkpoint, and run any phases that hadn't started yet

LlamaFactory detects the existing checkpoints in the output directory
automatically — no extra configuration is needed.  The run log entry is
appended as usual when the pipeline finishes.

If a DPO-only run (started with `--skip-sft`) was interrupted, combine
`--resume` with `--sft-adapter` so the script knows which SFT checkpoint
to use for the in-memory merge:

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run_dpo_v2.yaml \
    --resume \
    --sft-adapter saves/qwen3-clover/2026-05-10-14-30-00_sft/checkpoint-800
```

#### Skipping both SFT and DPO — export only

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml \
    --sft-adapter saves/qwen3-clover/2026-05-10-14-30-00_sft/checkpoint-800 \
    --skip-dpo \
    --timestamp 2026-05-10-14-30-00
```

#### Running on a remote server — disconnecting and reconnecting

Training takes hours. Use **tmux** to keep the session alive after you
disconnect from SSH.

**Starting a run:**

```bash
# Create a named session
tmux new -s training

# Start training inside it
export LLAMAFACTORY_DIR=~/LlamaFactory
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml

# Detach — training keeps running, safe to close the SSH terminal
# Keyboard shortcut:  Ctrl+B  then  D
```

**Reconnecting later:**

```bash
# Reattach to see live output exactly where you left off
tmux attach -t training

# If you forget the session name
tmux ls
```

**Killing a session:**

```bash
# From inside the session — closes the shell and ends the session
exit          # or Ctrl+D

# From any terminal, by name
tmux kill-session -t training

# Kill everything
tmux kill-server
```

**Checking progress without reattaching:**

`trainer_state.json` is updated continuously during training, so you can
inspect current metrics from a separate terminal without touching the tmux
session:

```bash
python3 -c "
import json, pathlib
for f in sorted(pathlib.Path('saves').glob('***/trainer_state.json')):
    s = json.loads(f.read_text())
    last = s['log_history'][-1] if s['log_history'] else {}
    print(f.parent.name, '|', last)
"
```

---

### Run log

After every real run (skipped when `--dry-run` is used), results are appended
to `llama_train/logs/<ModelName>.yaml`, one file per base model.  The log is
ordered newest-first.

#### Log entry format

```yaml
- timestamp: '2026-05-11-14-00-00'
  run_name: qwen3-clover-v2

  config_diff:                        # what changed vs. the previous run
    dpo.num_train_epochs: <absent> → 3.0
    dpo.pref_beta: 0.1 → 0.05
    sft.learning_rate: 5.0e-05 → 3.0e-05
    sft.lora_alpha: 128 → 64

  sft:
    best_train_loss: 0.49361          # minimum over all logged steps
    best_eval_loss:  0.15022          # from load_best_model_at_end checkpoint
    best_checkpoint: saves/qwen3-clover-v2/.../checkpoint-800

  dpo:
    final_train_loss: 0.2525          # last logged step value
    rewards_accuracies: 0.7200        # fraction chosen > rejected  (if logged)
    rewards_margins:    0.3100        # mean(chosen_reward - rejected_reward)
    logps_chosen:      -1.2300        # mean log-prob of chosen responses
    logps_rejected:    -1.8200
    best_checkpoint: saves/qwen3-clover-v2/.../checkpoint-N

  config_snapshot:                    # full config; used to compute the next diff
    ...
```

#### DPO quality metrics

The DPO metrics (`rewards_*`, `logps_*`) only appear when the run is long
enough to hit at least one `logging_steps` boundary.  For short test runs they
will be absent.

| Metric | What to look for |
|--------|-----------------|
| `rewards_accuracies` | Fraction of pairs where the model assigns higher reward to the chosen response. Values above `0.5` and rising across runs indicate the model is learning preferences. |
| `rewards_margins` | Mean gap between chosen and rejected rewards. Positive and growing is good; very large values may indicate reward hacking. |
| `logps_chosen` | Log-probability of chosen responses. Should increase (become less negative) or stay stable as training progresses. |
| `logps_rejected` | Log-probability of rejected responses. Should decrease relative to chosen. |

#### Excluded from config_diff

The following keys never appear in `config_diff` because they do not affect
model quality — they are infrastructure, logging, or checkpointing settings:

`report_to`, `plot_loss`, `logging_steps`, `save_steps`, `save_strategy`,
`save_total_limit`, `ddp_timeout`, `preprocessing_num_workers`,
`trust_remote_code`, `flash_attn`, `include_num_input_tokens_seen`,
`use_swanlab` and related keys, the entire `export:` section, `run_name`,
`output_base`, `dataset_dir`.

---

### Adding a new model config

1. Copy `configs/example.yaml` to `configs/<descriptive_name>.yaml`
2. Change `model_name_or_path`, `template`, `run_name`
3. Update dataset names in `sft.dataset`, `sft.eval_dataset`, `dpo.dataset`
4. Adjust `lora_rank`, learning rates, and epoch counts as needed
5. Run with `--dry-run` first to verify the generated configs look correct

The run log is keyed on the **base model name** (the last path component of
`model_name_or_path`), so all runs for `Qwen/Qwen3-8B` share
`logs/Qwen3-8B.yaml` regardless of which config file was used.

---

## test.py — evaluation

Runs a fixed CTL2 test suite (`resources/ctl2_test_suite*.json`) against a
model under test (MUT), judges each response with a separate, stronger LLM
(Anthropic or an OpenAI-compatible endpoint), scores it, and writes results.

```
resources/ctl2_test_suite.json
    ↓ (system_prompt + user_message + temperature)
[MUT]  — local (transformers, safetensors export dir) OR api (OpenAI-compatible)
    ↓ (raw response)
[Judge] — Anthropic OR OpenAI
    ↓ (structured JSON verdict)
compute_numeric_score + detect_critical_failure
    ↓
results/<model>_<ts>.json  +  results/<model>_<ts>_summary.md
logs/<BaseModel>.yaml        ← shared with train.py's run log
```

Point `training_config:` in the eval config at the same YAML used by
`train.py` and `test.py` will auto-discover the most recent completed export
directory and append eval scores to that model's shared run log.

```bash
python test.py configs/eval_qwen36.yaml
python test.py configs/eval_qwen36.yaml --tests T4,T5,T7   # run a subset of tests
python test.py configs/eval_qwen36.yaml --runs 3           # repeat each test N times
python test.py configs/eval_qwen36.yaml --dry-run          # preview without calling any model
python test.py --compare results/a.json results/b.json     # diff two result sets
```

| Option | Description |
|--------|-------------|
| `--tests T1,T2,…` / `-t` | Only run the listed test IDs |
| `--generate-only` | Only generate MUT responses, skip judging |
| `--validate-only` | Only judge previously generated responses |
| `--runs N` / `-n` | Repeat each test N times (for variance) |
| `--output-dir DIR` / `-o` | Override the results output directory |
| `--suite-file FILE` / `-s` | Use a specific test suite file |
| `--dry-run` | Preview without calling any model |
| `--compare FILE FILE` | Diff two prior result JSON files |
| `--no-llm-summary` | Skip the LLM-written summary paragraph |
| `--no-log` | Don't append to `logs/<BaseModel>.yaml` |
| `--debug` | Verbose per-test streaming output |

---

## chat.py — interactive chat

Loads an exported safetensors model and starts a multi-turn conversation in
the terminal, keeping history across turns for context.

```bash
python chat.py configs/chat_config_qwen36.yaml
python chat.py configs/chat_config_qwen36.yaml --model /home/pavlisd/exports/qwen36
python chat.py configs/chat_config_qwen36.yaml --temperature 0.7 --top-p 0.95
python chat.py configs/chat_config_qwen36.yaml --logfile session.log
```

In-chat commands: `/reset` (clear history), `/history` (show conversation so
far), `/paste` (multiline paste mode until Ctrl-D), `/quit` / `/exit` /
Ctrl-C. Type a prompt across one or more lines, then Ctrl-D to submit.

---

## dpo_forge.py — on-policy DPO data generation

Converts SFT examples into on-policy DPO preference pairs: samples several
completions per prompt from the locally trained model at different
temperatures, executes each candidate for real against a live CloverDX
skeleton graph (via an MCP server), and judges the resulting output with a
stronger LLM to decide which candidates are "chosen" vs. "rejected".

The pipeline (implemented in `dpo_forge/`) runs in stages:

| Stage | Module | Role |
|-------|--------|------|
| 1 | `loader.py` | Ingest + normalize + dedup SFT input files (OpenAI chat or Alpaca format) |
| 2 | `generator.py` | Sample N completions per prompt from the local MUT checkpoint |
| 3a | `setup_agent.py` | LLM agent that builds `.fmt` metadata + a skeleton graph on the CloverDX server via MCP, and captures the "golden" reference output |
| 3b | `runner.py` | Runs each candidate against the skeleton, diffs output vs. golden, classifies outcome (L1/L2/L3) |
| 4 | `judge.py` | One-shot LLM judge — reads task + candidate + execution evidence, returns a structured verdict |
| 5 | `pairing.py` | Builds chosen/rejected DPO pairs from labeled candidates, with dataset-balance controls |
| 6 | `output.py` | Writes DPO JSONL, provenance JSONL, and a `dataset_info.json` snippet |

`state.py` is a SQLite-backed resumability store keyed on
`(example_id, candidate_index)` so an interrupted run can resume without
repeating LLM calls or CloverDX executions. `mcp_client.py` /
`ctl_validate_mcp.py` / `agent_loop.py` are shared infra for talking to the
CloverDX MCP server. See `spec/` for the underlying design docs.

If `clover.endpoint` in the config is left `null`, the pipeline runs in a
generation + judge-only mode with no real CloverDX execution.

```bash
python dpo_forge.py run --config configs/forge.yaml               # generate DPO pairs
python dpo_forge.py run --config configs/forge.yaml --limit 20 --dry-run
python dpo_forge.py cache list --config configs/forge.yaml         # inspect cached setup bundles
python dpo_forge.py cache purge --config configs/forge.yaml        # clear the cache
python dpo_forge.py audit data/dpo/forged.provenance.jsonl         # inspect provenance records
python dpo_forge.py stats data/dpo/forged.provenance.jsonl         # failure-mode histogram
```

Configuration lives in `configs/forge.yaml` — see that file for the full set
of knobs (input files, model checkpoint, generation temperatures, judge
provider/model, pairing strategy, dataset-balance limits, CloverDX
endpoint/sandbox, output paths).

---

## mut_validate.py — MUT self-correction data generation

Generates SFT examples that teach the model to **fix its own mistakes**.
Reads SFT examples (same input formats as `dpo_forge.py`), sends the prompt
to the local model under test (MUT), and has a stronger judge LLM review the
resulting CTL2 code against an ISSUES / SUGGESTIONS / VERDICT format — a
static code review, no CloverDX execution involved.

- If the MUT is right on the first try (PASS, no WARNING) → counted, no output.
- Otherwise the review is fed back to the MUT for another attempt, up to
  `--attempts` total (default `2`, i.e. one retry):
  - A later attempt that passes → a **"MUT self-corrected"** multi-turn SFT
    conversation (the full attempt/feedback history) is appended to
    `output.self_corrected_file`.
  - All attempts exhausted without a PASS → the judge rewrites the last
    attempt's code itself, producing a 4-turn **"judge corrected it"** SFT
    conversation appended to `output.judge_corrected_file`.
- `--tweak`: before any of the above, the judge rewrites the prompt into a
  structurally similar but different task (new domain/fields/business rule,
  same component type), so the MUT is tested on something it hasn't
  memorized verbatim. Deterministic per example by default; `--tweak-random`
  picks a fresh random domain every run.

```bash
python mut_validate.py data/sft_input/some_examples.json --config configs/mut_validate_qwen36.yaml
python mut_validate.py data/sft_input/some_examples.json --limit 20 --attempts 3
python mut_validate.py data/sft_input/some_examples.json --tweak --verbose
```

| Option | Description |
|--------|-------------|
| `--config` / `-c` | Config YAML (default `configs/mut_validate.yaml`) |
| `--index N` | Start at example index N |
| `--limit N` / `-n` | Max number of examples to process |
| `--attempts N` | Max MUT attempts per example (default `2`) |
| `--tweak` | Rewrite the prompt into a fresh, structurally similar task first |
| `--tweak-random` | Same as `--tweak` but picks a random (non-deterministic) domain |
| `--skip-ctl-validate` | Skip the CTL2 compile/metadata pre-filter |
| `--overwrite` | Overwrite existing output files instead of appending |
| `--verbose` / `-v` | Verbose output |
| `--dry-run` | Preview without writing output |

Runs on GPU 1 by default (`CUDA_VISIBLE_DEVICES=1`) so it doesn't collide
with a local judge server typically running on GPU 0; override by exporting
`CUDA_VISIBLE_DEVICES` yourself before invoking.

---

## debug.py

A small ad-hoc script for inspecting model behavior at the token level: runs
a fixed CTL2 prompt through a base and a merged model, and for each position
prints the top-k next-token probabilities alongside the actually-expected
token. Edit `BASE_MODEL`, `MERGED_MODEL`, and `PROMPT` at the top of the
file directly — there's no CLI.

---

## Other directories

| Path | Contents |
|------|----------|
| `resources/` | `ctl2_test_suite*.json` (versioned test suites used by `test.py`), plus CTL2 reference docs (`ctl2-basics.md`, `componet_contracts.md`) and the test-suite spec |
| `spec/` | Design docs for the `dpo_forge` pipeline (skeleton externalization, CloverDX execution, setup/judge orchestration) |
| `data/sft_input/` | Curated SFT examples consumed by `dpo_forge.py` and `mut_validate.py` |
| `data/dpo/` | `dpo_forge.py` output: forged DPO pairs (`forged.jsonl`), provenance (`forged.provenance.jsonl`), and its resumability state DB (`forge_state.db`) |
| `tests/` | Pytest unit tests |
