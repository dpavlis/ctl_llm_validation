#!/usr/bin/env python3
"""
LlamaFactory two-phase training pipeline: SFT → DPO → Export

Usage:
    python train.py <config_file> [options]

Options:
    --dry-run             Print generated configs and commands without executing
    --skip-sft            Skip the SFT phase
    --skip-dpo            Skip the DPO phase
    --skip-export         Skip model export
    --sft-adapter PATH    Path to a pre-existing SFT adapter; implies --skip-sft
    --timestamp TS        Reuse a previous run timestamp to resume a mid-pipeline run
                          (format: YYYY-MM-DD-HH-MM-SS)

Environment:
    LLAMAFACTORY_DIR      Root of the LlamaFactory installation.  All training
                          commands are run with this as the working directory so
                          that relative paths (dataset_dir: data, output_dir:
                          saves/...) resolve correctly.
                          Default: ~/LlamaFactory

Config layout:
    run_name:    my_run          # Subfolder under output_base
    output_base: saves           # Root directory for all outputs

    # Common params inherited by both training phases
    model_name_or_path: Qwen/Qwen3-8B
    ...

    sft:          # SFT-specific overrides (single round)
      dataset: sft_data
      ...

    # Or, to run multiple SFT rounds back-to-back (e.g. small examples first,
    # then a second round with a larger cutoff_len and "thinking" examples),
    # give sft: a list instead of a mapping. Rounds run in order; each round
    # after the first chains from the previous round's best checkpoint via
    # adapter_name_or_path (continuing the same LoRA weights by default —
    # override create_new_adapter: true per-round to start a fresh adapter
    # instead). Output dirs are suffixed _sft, _sft2, _sft3, ...
    #
    # sft:
    #   - dataset: sft_data_small
    #     cutoff_len: 1024
    #   - dataset: sft_data_large_thinking
    #     cutoff_len: 4096
    #     enable_thinking: true

    dpo:          # DPO-specific overrides
      dataset: dpo_data
      ...

    export:       # Export settings
      export_size: 5
      ...

Checkpoint strategy:
    After SFT: uses best_model_checkpoint from trainer_state.json (set when
    load_best_model_at_end is true), falling back to the latest checkpoint dir,
    then to the output dir itself.  That path is fed to DPO as adapter_name_or_path.

    DPO merges the SFT LoRA into the base weights in-memory (merge_and_unload),
    then trains a fresh LoRA adapter for preference alignment.  Because the DPO
    adapter is relative to the SFT-merged base, the export step supplies both
    adapters as a comma-separated pair so LlamaFactory merges them sequentially:
    base → SFT → DPO → final weights.

Run log:
    After each real run (not --dry-run), results are appended to
    llama_train/logs/<model_name>.yaml.  Each entry records SFT best losses,
    DPO final losses and quality metrics, and a diff of hyperparameters
    that changed vs. the previous run of the same model.
"""

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# LlamaFactory installation directory
# All subprocess calls use this as cwd so that relative paths in configs
# (dataset_dir: data, output_dir: saves/...) resolve correctly.
# ---------------------------------------------------------------------------
LLAMAFACTORY_DIR = Path(
    os.environ.get("LLAMAFACTORY_DIR", "~/LlamaFactory")
).expanduser().resolve()


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def write_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def read_trainer_state(output_dir: str) -> Optional[dict]:
    path = Path(output_dir) / "trainer_state.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def find_best_checkpoint(output_dir: str, state: Optional[dict]) -> str:
    """
    Return the best checkpoint path in priority order:
      1. best_model_checkpoint from trainer_state.json  (set by load_best_model_at_end)
      2. Latest checkpoint-N subdirectory
      3. output_dir itself (final model saved there by LlamaFactory)
    """
    if state:
        best = state.get("best_model_checkpoint")
        if best and Path(best).is_dir():
            return best

    checkpoints = sorted(
        Path(output_dir).glob("checkpoint-*"),
        key=lambda p: int(p.name.split("-")[1]) if p.name.split("-")[1].isdigit() else 0,
    )
    if checkpoints:
        return str(checkpoints[-1])

    return output_dir


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------

def is_training_complete(output_dir: str) -> bool:
    """True if training finished — the final epoch summary entry is present."""
    state = read_trainer_state(output_dir)
    if not state:
        return False
    history = state.get("log_history", [])
    # HF Trainer writes a final entry with train_loss + train_runtime when done
    return bool(history) and "train_loss" in history[-1]


def last_checkpoint_in(output_dir: str) -> Optional[str]:
    """Return path to the highest-numbered checkpoint-N dir, or None."""
    p = Path(output_dir)
    if not p.is_dir():
        return None
    ckpts = sorted(
        [d for d in p.glob("checkpoint-*") if d.is_dir()],
        key=lambda d: int(d.name.split("-")[1]) if d.name.split("-")[1].isdigit() else 0,
    )
    return str(ckpts[-1]) if ckpts else None


def is_export_complete(export_dir: str) -> bool:
    """True if the export directory contains at least one safetensors shard."""
    p = Path(export_dir)
    return p.is_dir() and any(p.glob("*.safetensors"))


_SFT_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_sft\d*$")
_PHASE_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})_(?:sft\d*|dpo|export)$")


def find_latest_sft_checkpoint(run_dir: Path) -> Optional[str]:
    """
    Find the best checkpoint from the most recent completed SFT round under
    run_dir (the last round of a multi-round SFT config, if applicable).
    Returns the checkpoint path, or None if no SFT run exists.

    Rounds within a run are named _sft, _sft2, _sft3, ... and always created
    in order, so the directory with the newest mtime is the last round of the
    most recently run SFT pipeline.
    """
    if not run_dir.is_dir():
        return None
    sft_dirs = [d for d in run_dir.iterdir() if d.is_dir() and _SFT_DIR_RE.match(d.name)]
    if not sft_dirs:
        return None
    latest_sft = max(sft_dirs, key=lambda d: d.stat().st_mtime)
    state = read_trainer_state(str(latest_sft))
    return find_best_checkpoint(str(latest_sft), state)


def find_latest_run_timestamp(run_dir: Path) -> Optional[str]:
    """
    Scan run_dir for timestamped phase directories and return the most recent
    timestamp string (YYYY-MM-DD-HH-MM-SS), or None if none exist.
    """
    if not run_dir.is_dir():
        return None
    timestamps: set = set()
    for d in run_dir.iterdir():
        if not d.is_dir():
            continue
        m = _PHASE_DIR_RE.match(d.name)
        if m:
            timestamps.add(m.group(1))
    return max(timestamps) if timestamps else None  # lexicographic == chronological


# ---------------------------------------------------------------------------
# Metrics extraction
# ---------------------------------------------------------------------------

_DPO_QUALITY_KEYS = [
    "rewards/accuracies",
    "rewards/margins",
    "rewards/chosen",
    "rewards/rejected",
    "logps/chosen",
    "logps/rejected",
]


def _series(history: list, key: str) -> list:
    return [e[key] for e in history if key in e]


def extract_sft_results(state: dict, best_checkpoint: str) -> dict:
    history = state.get("log_history", [])
    result: dict = {}

    train_losses = _series(history, "loss")
    if train_losses:
        result["best_train_loss"] = round(min(train_losses), 5)
    else:
        summary = _series(history, "train_loss")
        if summary:
            result["best_train_loss"] = round(summary[-1], 5)

    best_metric = state.get("best_metric")
    if best_metric is not None:
        result["best_eval_loss"] = round(best_metric, 5)
    else:
        eval_losses = _series(history, "eval_loss")
        if eval_losses:
            result["best_eval_loss"] = round(min(eval_losses), 5)

    result["best_checkpoint"] = best_checkpoint
    return result


def extract_dpo_results(state: dict, best_checkpoint: str) -> dict:
    history = state.get("log_history", [])
    result: dict = {}

    train_losses = _series(history, "loss")
    if train_losses:
        result["final_train_loss"] = round(train_losses[-1], 5)
    else:
        summary = _series(history, "train_loss")
        if summary:
            result["final_train_loss"] = round(summary[-1], 5)

    for key in _DPO_QUALITY_KEYS:
        values = _series(history, key)
        if values:
            result[key.replace("/", "_")] = round(values[-1], 5)

    result["best_checkpoint"] = best_checkpoint
    return result


# ---------------------------------------------------------------------------
# Metrics summary (console)
# ---------------------------------------------------------------------------

def print_phase_summary(label: str, state: dict, output_dir: str) -> None:
    print(f"\n{'─'*70}")
    print(f"  {label} — Training Summary")
    print(f"{'─'*70}")

    history = state.get("log_history", [])

    train_losses = _series(history, "loss")
    if train_losses:
        print(f"  Train loss  : start={train_losses[0]:.4f}  "
              f"final={train_losses[-1]:.4f}  min={min(train_losses):.4f}")
    else:
        summary = _series(history, "train_loss")
        if summary:
            print(f"  Train loss  : {summary[-1]:.4f}  (epoch summary only)")

    eval_losses = _series(history, "eval_loss")
    if eval_losses:
        print(f"  Eval loss   : start={eval_losses[0]:.4f}  "
              f"final={eval_losses[-1]:.4f}  min={min(eval_losses):.4f}")

    best_metric = state.get("best_metric")
    best_ckpt   = state.get("best_model_checkpoint")
    if best_metric is not None:
        print(f"  Best metric : {best_metric:.4f}  (eval_loss)")
    if best_ckpt:
        print(f"  Best ckpt   : {best_ckpt}")

    dpo_data = {k: _series(history, k) for k in _DPO_QUALITY_KEYS}
    dpo_data = {k: v for k, v in dpo_data.items() if v}
    if dpo_data:
        print()
        print("  DPO quality metrics (final value  ←→  start):")
        for key, values in dpo_data.items():
            trend = "↑" if values[-1] > values[0] else ("↓" if values[-1] < values[0] else "→")
            print(f"    {key:<28}: {values[-1]:+.4f}  (start: {values[0]:+.4f}  {trend})")

    resolved = find_best_checkpoint(output_dir, state)
    print(f"\n  → Using for next phase: {resolved}")
    print(f"{'─'*70}")


def print_pipeline_summary(
    *,
    run_name: str,
    base_model: str,
    timestamp: str,
    sft_results: Optional[list],
    dpo_results: Optional[dict],
    export_dir: Optional[str],
    skipped_sft: bool,
    skipped_dpo: bool,
    skipped_export: bool,
    dry_run: bool,
) -> None:
    W = 70
    print(f"\n{'═' * W}")
    print(f"  Pipeline complete")
    print(f"{'═' * W}")
    print(f"  Run       : {run_name}")
    print(f"  Base model: {base_model}")
    print(f"  Timestamp : {timestamp}")

    # ── SFT ──────────────────────────────────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  SFT")
    print(f"  {'─' * (W - 2)}")
    if dry_run:
        print("  (dry-run — no training performed)")
    elif skipped_sft:
        print("  skipped")
    elif sft_results:
        multi = len(sft_results) > 1
        for i, result in enumerate(sft_results):
            if multi:
                print(f"  Round {i + 1}/{len(sft_results)}:")
            best_train = result.get("best_train_loss")
            best_eval  = result.get("best_eval_loss")
            best_ckpt  = result.get("best_checkpoint", "—")
            is_last = i == len(sft_results) - 1
            if best_train is not None:
                print(f"  Best train loss : {best_train:.5f}")
            if best_eval is not None:
                suffix = "  ← checkpoint selected for DPO" if is_last else ""
                print(f"  Best eval  loss : {best_eval:.5f}{suffix}")
            print(f"  Checkpoint used : {best_ckpt}")
            if multi and not is_last:
                print()
    else:
        print("  No trainer state found — metrics unavailable")

    # ── DPO ──────────────────────────────────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  DPO")
    print(f"  {'─' * (W - 2)}")
    if dry_run:
        print("  (dry-run — no training performed)")
    elif skipped_dpo:
        print("  skipped")
    elif dpo_results:
        final_loss = dpo_results.get("final_train_loss")
        if final_loss is not None:
            print(f"  Final train loss : {final_loss:.5f}")

        quality_keys = [
            ("rewards/accuracies", "Reward accuracy  "),
            ("rewards/margins",    "Reward margin    "),
            ("rewards/chosen",     "Reward chosen    "),
            ("rewards/rejected",   "Reward rejected  "),
            ("logps/chosen",       "LogP  chosen     "),
            ("logps/rejected",     "LogP  rejected   "),
        ]
        # dpo_results stores keys with / replaced by _
        printed_any = False
        for raw_key, label in quality_keys:
            stored_key = raw_key.replace("/", "_")
            val = dpo_results.get(stored_key)
            if val is not None:
                print(f"  {label}: {val:+.5f}")
                printed_any = True
        if not printed_any:
            print("  (no DPO quality metrics recorded)")
    else:
        print("  No trainer state found — metrics unavailable")

    # ── Export ────────────────────────────────────────────────────────────────
    print(f"\n  {'─' * (W - 2)}")
    print(f"  Export")
    print(f"  {'─' * (W - 2)}")
    if dry_run:
        print("  (dry-run — no export performed)")
    elif skipped_export:
        print("  skipped")
    elif export_dir:
        print(f"  Location : {export_dir}")
        export_path = Path(export_dir)
        shards = sorted(export_path.glob("*.safetensors")) if export_path.is_dir() else []
        if shards:
            total_gb = sum(s.stat().st_size for s in shards) / 1024**3
            print(f"  Shards   : {len(shards)}  ({total_gb:.1f} GB total)")
        else:
            print("  (no safetensors shards found — export may have failed)")
    else:
        print("  No export directory recorded")

    print(f"\n{'═' * W}\n")


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------

# Keys excluded from the config diff — pure infrastructure / reproducibility
# settings that don't affect model quality.
_DIFF_EXCLUDE = {
    "run_name", "output_base",
    "report_to", "plot_loss", "include_num_input_tokens_seen",
    "ddp_timeout", "preprocessing_num_workers", "dataset_dir",
    "trust_remote_code", "flash_attn",
    "use_swanlab", "swanlab_project", "swanlab_run_name", "swanlab_mode",
    "logging_steps", "save_steps", "save_strategy", "save_total_limit",
    # export section never affects training quality
}


def _flatten(cfg: dict, prefix: str = "") -> dict:
    """Flatten nested config to dot-separated keys."""
    out: dict = {}
    for k, v in cfg.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, full))
        else:
            out[full] = v
    return out


def _config_for_diff(raw: dict) -> dict:
    """Return a flattened config with infrastructure keys and export section removed."""
    flat = _flatten(raw)
    return {
        k: v for k, v in flat.items()
        if k not in _DIFF_EXCLUDE
        and not k.startswith("export.")
        and k.split(".")[0] not in _DIFF_EXCLUDE
    }


def _compute_diff(prev: dict, curr: dict) -> dict:
    diff: dict = {}
    for key in sorted(set(prev) | set(curr)):
        old = prev.get(key, "<absent>")
        new = curr.get(key, "<absent>")
        if str(old) != str(new):
            diff[key] = f"{old} → {new}"
    return diff


def _load_log(log_path: Path) -> list:
    if not log_path.exists():
        return []
    with open(log_path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def _save_log(log_path: Path, model_name_or_path: str, runs: list) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        f.write(f"# Run log for {model_name_or_path}\n")
        f.write(f"# Written by train.py (type: training) and test.py (type: eval) — newest first\n")
        f.write(f"# config_diff: hyperparameter changes vs. previous training run\n\n")
        yaml.dump(runs, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def append_run_log(
    log_dir: Path,
    model_name_or_path: str,
    timestamp: str,
    run_name: str,
    raw_config: dict,
    sft_results: Optional[list],
    dpo_results: Optional[dict],
    export_dir: Optional[str] = None,
) -> Path:
    slug = Path(model_name_or_path).name  # e.g. "Qwen3-8B" from "Qwen/Qwen3-8B"
    log_path = log_dir / f"{slug}.yaml"

    runs = _load_log(log_path)

    curr_flat = _config_for_diff(raw_config)
    if runs:
        prev_flat = _config_for_diff(runs[0].get("config_snapshot", {}))
        diff = _compute_diff(prev_flat, curr_flat)
        diff_value: object = diff if diff else "(no changes vs. previous run)"
    else:
        diff_value = "(first run)"

    entry: dict = {
        "timestamp":   timestamp,
        "type":        "training",
        "run_name":    run_name,
        "config_diff": diff_value,
    }
    if sft_results:
        entry["sft"] = sft_results
    if dpo_results:
        entry["dpo"] = dpo_results
    if export_dir:
        entry["export_dir"] = export_dir
    # Full snapshot at the end — used for future diffs, not for human scanning
    entry["config_snapshot"] = raw_config

    runs.insert(0, entry)  # newest first
    _save_log(log_path, model_name_or_path, runs)
    return log_path


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def _print_header(label: str, yaml_path: Path) -> None:
    print(f"\n{'═'*70}")
    print(f"  Phase : {label}")
    print(f"  Config: {yaml_path}")
    print(f"{'═'*70}\n")


def run_train_phase(label: str, config: dict, yaml_path: Path, dry_run: bool) -> None:
    write_yaml(config, yaml_path)
    _print_header(label, yaml_path)

    abs_yaml = yaml_path.resolve()
    if dry_run:
        print(yaml.dump(config, default_flow_style=False, sort_keys=False))
        print(f"[dry-run] Would run (cwd={LLAMAFACTORY_DIR}):")
        print(f"  llamafactory-cli train {abs_yaml}")
        return

    result = subprocess.run(
        ["llamafactory-cli", "train", str(abs_yaml)],
        cwd=LLAMAFACTORY_DIR,
    )
    if result.returncode != 0:
        print(f"\nERROR: {label} phase failed (exit code {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def run_export_phase(config: dict, yaml_path: Path, dry_run: bool) -> None:
    write_yaml(config, yaml_path)
    _print_header("Export", yaml_path)

    abs_yaml = yaml_path.resolve()
    if dry_run:
        print(yaml.dump(config, default_flow_style=False, sort_keys=False))
        print(f"[dry-run] Would run (cwd={LLAMAFACTORY_DIR}):")
        print(f"  llamafactory-cli export {abs_yaml}")
        return

    result = subprocess.run(
        ["llamafactory-cli", "export", str(abs_yaml)],
        cwd=LLAMAFACTORY_DIR,
    )
    if result.returncode != 0:
        print(f"\nERROR: Export phase failed (exit code {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LlamaFactory SFT → DPO → Export pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", help="Path to master YAML config file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print configs and commands without executing")
    parser.add_argument("--skip-sft", action="store_true",
                        help="Skip SFT phase (requires --sft-adapter or dpo.adapter_name_or_path in config)")
    parser.add_argument("--skip-dpo", action="store_true", help="Skip DPO phase")
    parser.add_argument("--skip-export", action="store_true", help="Skip model export")
    parser.add_argument("--sft-adapter", metavar="PATH",
                        help="Path to a pre-existing SFT adapter; implies --skip-sft")
    parser.add_argument("--timestamp", metavar="TS",
                        help="Reuse a previous run timestamp (YYYY-MM-DD-HH-MM-SS)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume the most recent interrupted run: reuse its output "
                             "directories, skip completed phases, and continue from the "
                             "last checkpoint in any unfinished phase")
    args = parser.parse_args()

    if args.sft_adapter:
        args.skip_sft = True

    # ── Load config — keep a pristine copy for the run log ───────────────
    raw_config_orig = load_config(args.config)
    cfg = copy.deepcopy(raw_config_orig)

    run_name       = cfg.pop("run_name", "run")
    output_base    = cfg.pop("output_base", "saves")
    sft_section_raw = cfg.pop("sft", {})
    dpo_section    = cfg.pop("dpo", {})
    export_section = cfg.pop("export", {})
    common         = cfg

    # sft: may be a single mapping (one round) or a list of mappings (multiple
    # rounds run in order, each chaining from the previous round's checkpoint).
    sft_stages_cfg = sft_section_raw if isinstance(sft_section_raw, list) else [sft_section_raw]

    def _sft_stage_suffix(i: int) -> str:
        return "_sft" if i == 0 else f"_sft{i + 1}"

    timestamp  = args.timestamp or datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    # output_base is relative to LLAMAFACTORY_DIR (LlamaFactory's cwd), so resolve
    # all phase output paths the same way to ensure read_trainer_state etc. find files.
    run_dir    = LLAMAFACTORY_DIR / output_base / run_name
    sft_stage_outputs = [
        str(run_dir / f"{timestamp}{_sft_stage_suffix(i)}") for i in range(len(sft_stages_cfg))
    ]
    dpo_output    = str(run_dir / f"{timestamp}_dpo")
    export_output = str(run_dir / f"{timestamp}_export")

    log_dir = Path(__file__).parent / "logs"

    if not LLAMAFACTORY_DIR.is_dir():
        print(f"ERROR: LLAMAFACTORY_DIR does not exist: {LLAMAFACTORY_DIR}", file=sys.stderr)
        print("Set the LLAMAFACTORY_DIR environment variable to the correct path.", file=sys.stderr)
        sys.exit(1)

    # ── Resume logic ─────────────────────────────────────────────────────
    # sft_precomplete[i] holds the best checkpoint for stage i if that round's
    # training already finished in a previous invocation; None otherwise.
    sft_precomplete = [None] * len(sft_stages_cfg)

    if args.resume:
        found_ts = find_latest_run_timestamp(run_dir)
        if not found_ts:
            print(f"\n[resume] No previous run found under {run_dir} — starting fresh.")
        else:
            timestamp = found_ts
            # Recompute paths for the found run
            sft_stage_outputs = [
                str(run_dir / f"{timestamp}{_sft_stage_suffix(i)}") for i in range(len(sft_stages_cfg))
            ]
            dpo_output    = str(run_dir / f"{timestamp}_dpo")
            export_output = str(run_dir / f"{timestamp}_export")

            print(f"\n[resume] Found run {timestamp}")

            # ── SFT status (per round; stops at the first non-complete round) ──
            n_stages = len(sft_stage_outputs)
            for i, stage_out in enumerate(sft_stage_outputs):
                label = "SFT" if n_stages == 1 else f"SFT[{i + 1}/{n_stages}]"
                if is_training_complete(stage_out):
                    stage_state = read_trainer_state(stage_out)
                    stage_best  = find_best_checkpoint(stage_out, stage_state)
                    sft_precomplete[i] = stage_best
                    print(f"[resume] {label}: complete — best checkpoint: {stage_best}")
                elif last_checkpoint_in(stage_out):
                    ckpt = last_checkpoint_in(stage_out)
                    print(f"[resume] {label}: interrupted — resuming from {ckpt}")
                    # LlamaFactory auto-resumes when output_dir has checkpoints and
                    # overwrite_output_dir is not set; no config change needed.
                    # Do NOT force create_new_adapter since the adapter already exists.
                    sft_stages_cfg[i].pop("create_new_adapter", None)
                    break
                else:
                    print(f"[resume] {label}: not started — running fresh")
                    break

            if all(c is not None for c in sft_precomplete):
                args.sft_adapter = sft_precomplete[-1]   # implies --skip-sft
                args.skip_sft    = True

            # ── DPO status (only meaningful once SFT is complete) ──
            if args.skip_sft:   # SFT confirmed complete above
                if is_training_complete(dpo_output):
                    args.skip_dpo = True
                    print(f"[resume] DPO    : complete — skipping")
                elif last_checkpoint_in(dpo_output):
                    ckpt = last_checkpoint_in(dpo_output)
                    print(f"[resume] DPO    : interrupted — resuming from {ckpt}")
                else:
                    print(f"[resume] DPO    : not started — will run after SFT")

            # ── Export status ──
            if is_export_complete(export_output):
                args.skip_export = True
                print(f"[resume] Export : complete — skipping")
            else:
                print(f"[resume] Export : not done — will run")

    print(f"\nPipeline start")
    print(f"  LlamaFactory  : {LLAMAFACTORY_DIR}")
    print(f"  Run name      : {run_name}")
    print(f"  Timestamp     : {timestamp}")
    for i, stage_out in enumerate(sft_stage_outputs):
        tag = "SFT out" if len(sft_stage_outputs) == 1 else f"SFT out[{i + 1}]"
        print(f"  {tag:<10}: {stage_out}")
    print(f"  DPO out   : {dpo_output}")
    print(f"  Export    : {export_output}")

    sft_results: list = []
    dpo_results: Optional[dict] = None

    # ── SFT ─────────────────────────────────────────────────────────────
    if not args.skip_sft:
        n_stages = len(sft_stages_cfg)
        prev_ckpt = None
        for i, (stage_section, stage_output) in enumerate(zip(sft_stages_cfg, sft_stage_outputs)):
            label = "SFT" if n_stages == 1 else f"SFT[{i + 1}/{n_stages}]"

            if sft_precomplete[i] is not None:
                print(f"\n[skip] {label} phase (already complete)")
                prev_ckpt = sft_precomplete[i]
                continue

            stage_config = {**common, **stage_section}
            stage_config.update({
                "stage": "sft",
                "do_train": True,
                "output_dir": stage_output,
            })
            if i == 0:
                stage_config.setdefault("create_new_adapter", True)
            else:
                # Chain from the previous round's checkpoint. By default this
                # continues training the same LoRA weights (create_new_adapter
                # left False); a stage can override create_new_adapter: true
                # to merge the previous round in and start a fresh adapter.
                stage_config.setdefault("adapter_name_or_path", prev_ckpt)
                stage_config.setdefault("create_new_adapter", False)

            run_train_phase(
                label,
                stage_config,
                Path(stage_output) / "training_config.yaml",
                args.dry_run,
            )

            if not args.dry_run:
                stage_state = read_trainer_state(stage_output)
                if stage_state:
                    print_phase_summary(label, stage_state, stage_output)
                    stage_best_ckpt = find_best_checkpoint(stage_output, stage_state)
                    result = extract_sft_results(stage_state, stage_best_ckpt)
                    result["round"] = i + 1
                    sft_results.append(result)
                    prev_ckpt = stage_best_ckpt
                else:
                    print(f"\n[warn] trainer_state.json not found in {stage_output}")
                    prev_ckpt = stage_output
            else:
                prev_ckpt = stage_output

        sft_best_ckpt = prev_ckpt
    else:
        print("\n[skip] SFT phase")
        sft_best_ckpt = sft_stage_outputs[-1]  # placeholder; overwritten below

    # ── Resolve SFT adapter for DPO ──────────────────────────────────────
    if args.sft_adapter:
        # Explicitly provided on the command line
        sft_adapter = args.sft_adapter
        print(f"\n  SFT adapter (provided)  : {sft_adapter}")
    elif not args.skip_sft:
        # Just finished SFT — use the best checkpoint from the final round
        sft_adapter = sft_best_ckpt if not args.dry_run else sft_stage_outputs[-1]
        print(f"\n  SFT adapter (this run)  : {sft_adapter}")
    else:
        # --skip-sft with no --sft-adapter: resolve in priority order:
        #   1. adapter_name_or_path in the dpo config section (explicit override)
        #   2. Best checkpoint from the latest SFT run in run_dir (auto-discovery)
        sft_adapter = dpo_section.get("adapter_name_or_path")
        if sft_adapter:
            print(f"\n  SFT adapter (from config): {sft_adapter}")
        else:
            sft_adapter = find_latest_sft_checkpoint(run_dir)
            if not sft_adapter:
                print(
                    "\nERROR: --skip-sft requires one of:\n"
                    "  • --sft-adapter <path>\n"
                    "  • 'adapter_name_or_path' in the dpo config section\n"
                    f"  • a completed SFT run under {run_dir}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"\n  SFT adapter (auto-found) : {sft_adapter}")

    # ── DPO ─────────────────────────────────────────────────────────────
    if not args.skip_dpo:
        dpo_config = {**common, **dpo_section}
        dpo_config.update({
            "stage": "dpo",
            "do_train": True,
            "output_dir": dpo_output,
            # LlamaFactory sees create_new_adapter=True + adapter_name_or_path and
            # routes ALL supplied adapters through merge_and_unload() into the base
            # weights, then initialises a FRESH LoRA for DPO training.  This means:
            #   • SFT knowledge is baked into the base before DPO begins
            #   • DPO can use a different lora_rank / lora_alpha than SFT
            #   • The DPO adapter captures only preference-alignment signal
            "adapter_name_or_path": sft_adapter,
            "create_new_adapter": True,
        })

        run_train_phase(
            "DPO",
            dpo_config,
            Path(dpo_output) / "training_config.yaml",
            args.dry_run,
        )

        if not args.dry_run:
            dpo_state = read_trainer_state(dpo_output)
            if dpo_state:
                print_phase_summary("DPO", dpo_state, dpo_output)
                dpo_best_ckpt = find_best_checkpoint(dpo_output, dpo_state)
                dpo_results = extract_dpo_results(dpo_state, dpo_best_ckpt)
            else:
                print(f"\n[warn] trainer_state.json not found in {dpo_output}")
                dpo_best_ckpt = dpo_output
    else:
        print("\n[skip] DPO phase")
        dpo_best_ckpt = dpo_output

    # ── Resolve adapter chain for export ─────────────────────────────────
    # Because DPO trained on the SFT-merged base, the DPO adapter is relative
    # to that merged base.  We must merge both adapters sequentially:
    #   base model  →  merge SFT adapter  →  merge DPO adapter  →  final weights
    # LlamaFactory splits adapter_name_or_path on "," and merges each in order.
    if not args.skip_dpo:
        dpo_final = dpo_best_ckpt if not args.dry_run else dpo_output
        final_adapter = f"{sft_adapter},{dpo_final}"
    else:
        # DPO was skipped — only the SFT adapter needs merging
        final_adapter = sft_adapter

    # ── Export ───────────────────────────────────────────────────────────
    if not args.skip_export:
        export_config = {
            "model_name_or_path":   common["model_name_or_path"],
            "adapter_name_or_path": final_adapter,
            "template":             common["template"],
            "finetuning_type":      common.get("finetuning_type", "lora"),
            "trust_remote_code":    common.get("trust_remote_code", True),
            "export_dir":           export_output,
            "export_size":          5,
            "export_device":        "cpu",
            "export_legacy_format": False,
        }
        export_config.update(export_section)
        # Capture the final export path (may have been overridden by export_section)
        export_output = export_config["export_dir"]

        print(f"\n  Exporting from: {export_config['adapter_name_or_path']}")
        print(f"  Exporting to  : {export_output}")

        run_export_phase(
            export_config,
            Path(export_config["export_dir"]) / "export_config.yaml",
            args.dry_run,
        )
    else:
        print("\n[skip] Export phase")

    # ── Append to run log ────────────────────────────────────────────────
    if not args.dry_run and (sft_results or dpo_results):
        log_path = append_run_log(
            log_dir=log_dir,
            model_name_or_path=common["model_name_or_path"],
            timestamp=timestamp,
            run_name=run_name,
            raw_config=raw_config_orig,
            sft_results=sft_results,
            dpo_results=dpo_results,
            export_dir=export_output if not args.skip_export else None,
        )
        print(f"\n  Run log: {log_path}")

    print_pipeline_summary(
        run_name=run_name,
        base_model=common["model_name_or_path"],
        timestamp=timestamp,
        sft_results=sft_results,
        dpo_results=dpo_results,
        export_dir=export_output if not args.skip_export else None,
        skipped_sft=args.skip_sft,
        skipped_dpo=args.skip_dpo,
        skipped_export=args.skip_export,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
