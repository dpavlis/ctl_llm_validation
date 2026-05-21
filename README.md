# LlamaFactory Training Pipeline

A config-driven script that runs **SFT → DPO → Export** using
[LlamaFactory](https://github.com/hiyouga/LLaMA-Factory), then appends the
results to a per-model run log so you can track what each config change
produced.

---

## Directory layout

```
llama_train/
├── train.py          # Pipeline driver
├── README.md         # This file
├── configs/          # One YAML file per model / experiment family
│   └── example.yaml
└── logs/             # Auto-created; one YAML log file per base model
    └── Qwen3-8B.yaml
```

All training outputs (checkpoints, loss curves, exported weights) are written
under `saves/` inside the LlamaFactory directory, **not** inside `llama_train/`.

---

## Prerequisites

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

## Quick start

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

## Config file reference

Each config file is a single YAML document with four logical sections.

### Top-level (pipeline meta)

| Key | Required | Description |
|-----|----------|-------------|
| `run_name` | yes | Becomes a subfolder under `output_base`. Use something descriptive like `qwen3-clover-v2`. |
| `output_base` | yes | Root directory for all run outputs, relative to where you invoke the script. Typically `saves`. |

### Common section

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

### `sft:` section

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

### `dpo:` section

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

### `export:` section

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

## What the script does

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

### Why both adapters are supplied at export

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

## Command-line reference

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

### SFT adapter resolution for DPO

When `--skip-sft` is used, the script finds the SFT adapter in this order:

| Priority | Source | How to trigger |
|----------|--------|----------------|
| 1 | `--sft-adapter PATH` on the command line | Explicit path — use when pointing at a different run or a specific checkpoint |
| 2 | `adapter_name_or_path` in the `dpo:` config section | Fixed adapter baked into the config file |
| 3 | Best checkpoint from the latest `*_sft` directory under `run_dir` | **Default** — just pass `--skip-sft` with nothing else |

---

## Output directory structure

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

## Recipes

### Full pipeline (default)

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml
```

### Preview without running anything

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml --dry-run
```

### Experimenting with DPO — reusing an SFT run

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

### Resuming an interrupted run

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

### Skipping both SFT and DPO — export only

```bash
python ~/llama_train/train.py ~/llama_train/configs/my_run.yaml \
    --sft-adapter saves/qwen3-clover/2026-05-10-14-30-00_sft/checkpoint-800 \
    --skip-dpo \
    --timestamp 2026-05-10-14-30-00
```

### Running on a remote server — disconnecting and reconnecting

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

## Run log

After every real run (skipped when `--dry-run` is used), results are appended
to `llama_train/logs/<ModelName>.yaml`, one file per base model.  The log is
ordered newest-first.

### Log entry format

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

### DPO quality metrics

The DPO metrics (`rewards_*`, `logps_*`) only appear when the run is long
enough to hit at least one `logging_steps` boundary.  For short test runs they
will be absent.

| Metric | What to look for |
|--------|-----------------|
| `rewards_accuracies` | Fraction of pairs where the model assigns higher reward to the chosen response. Values above `0.5` and rising across runs indicate the model is learning preferences. |
| `rewards_margins` | Mean gap between chosen and rejected rewards. Positive and growing is good; very large values may indicate reward hacking. |
| `logps_chosen` | Log-probability of chosen responses. Should increase (become less negative) or stay stable as training progresses. |
| `logps_rejected` | Log-probability of rejected responses. Should decrease relative to chosen. |

### Excluded from config_diff

The following keys never appear in `config_diff` because they do not affect
model quality — they are infrastructure, logging, or checkpointing settings:

`report_to`, `plot_loss`, `logging_steps`, `save_steps`, `save_strategy`,
`save_total_limit`, `ddp_timeout`, `preprocessing_num_workers`,
`trust_remote_code`, `flash_attn`, `include_num_input_tokens_seen`,
`use_swanlab` and related keys, the entire `export:` section, `run_name`,
`output_base`, `dataset_dir`.

---

## Adding a new model config

1. Copy `configs/example.yaml` to `configs/<descriptive_name>.yaml`
2. Change `model_name_or_path`, `template`, `run_name`
3. Update dataset names in `sft.dataset`, `sft.eval_dataset`, `dpo.dataset`
4. Adjust `lora_rank`, learning rates, and epoch counts as needed
5. Run with `--dry-run` first to verify the generated configs look correct

The run log is keyed on the **base model name** (the last path component of
`model_name_or_path`), so all runs for `Qwen/Qwen3-8B` share
`logs/Qwen3-8B.yaml` regardless of which config file was used.
