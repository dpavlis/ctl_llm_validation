"""Stage 6 — Output writers.

Writes DPO JSONL, provenance JSONL, and a dataset_info.json snippet
in the format that matches the existing CTL_LoRA_DPO_data.jsonl and
LLaMA Factory's dataset_info.json expectations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .loader import SourceExample
from .pairing import DPOPair


# ---------------------------------------------------------------------------
# DPO JSONL
# ---------------------------------------------------------------------------

def write_dpo_jsonl(pairs: list[DPOPair], path: Path):
    """
    Append DPO pairs to path in the format matching CTL_LoRA_DPO_data.jsonl:
      {"prompt": ..., "system": ..., "chosen": ..., "rejected": ...}
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for pair in pairs:
            record: dict = {
                "prompt":        pair.prompt,
                "chosen":        pair.chosen,
                "rejected":      pair.rejected,
                "source_file":   pair.source_file,
                "source_index":  pair.source_index,
            }
            if pair.system:
                record["system"] = pair.system
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Generic multi-turn SFT conversation JSONL (used by mut_validate.py)
# ---------------------------------------------------------------------------

def write_conversation_jsonl(messages: list[dict], path: Path, extra: Optional[dict] = None):
    """
    Append one multi-turn SFT record: {"messages": [...], **extra}.

    Matches the shape of the input SFT files (see data/sft_input/*.json),
    so the output can be dropped straight back in as training data.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict = {"messages": messages}
    if extra:
        record.update(extra)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Invalid examples JSONL
# ---------------------------------------------------------------------------

def write_invalid_jsonl(
    example: SourceExample,
    reason: str,
    path: Path,
    log_excerpt: str = "",
):
    """
    Append one record to the invalid-examples file for human review/correction.

    Written when setup fails or the reference CTL produced unusable golden output.
    Fields are chosen to make it easy to locate the example in the source SFT file
    and understand why it was rejected.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "example_id":   example.id,
        "source_file":  example.source_file,
        "source_index": example.source_index,
        "reason":       reason,
        "prompt":       example.prompt,
        "reference":    example.reference,
    }
    if log_excerpt:
        record["log_excerpt"] = log_excerpt
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Provenance JSONL
# ---------------------------------------------------------------------------

def write_provenance_jsonl(pairs: list[DPOPair], path: Path):
    """Append per-pair provenance records (not used for training)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for pair in pairs:
            record = {
                "example_id":             pair.example_id,
                "rejected_exec_level":    pair.rejected_exec_level,
                "rejected_failure_modes": pair.rejected_failure_modes,
                "pairing_strategy":       pair.pairing_strategy,
                "provenance":             pair.provenance,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# dataset_info.json snippet
# ---------------------------------------------------------------------------

def write_dataset_info(dpo_path: Path, output_dir: Path) -> Path:
    """
    Emit or update the dataset_info.json entry so the DPO file can be
    dropped straight into a LLaMA Factory training run.
    """
    name = dpo_path.stem
    entry = {
        name: {
            "file_name": str(dpo_path),
            "ranking": True,
            "columns": {
                "prompt":   "prompt",
                "system":   "system",
                "chosen":   "chosen",
                "rejected": "rejected",
            },
        }
    }
    info_path = output_dir / "dataset_info.json"
    existing: dict = {}
    if info_path.exists():
        try:
            with open(info_path) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(entry)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(info_path, "w") as f:
        json.dump(existing, f, indent=2)
    return info_path


# ---------------------------------------------------------------------------
# Run report
# ---------------------------------------------------------------------------

def build_report(
    n_prompts: int,
    n_candidates: int,
    n_pairs: int,
    n_setup_failed: int,
    n_all_correct: int,
    exec_level_counts: dict,
    failure_mode_counts: dict,
    judge_cost_tokens: int,
    wall_clock_s: float,
    temp_stats: dict | None = None,
) -> dict:
    return {
        "prompts_processed":      n_prompts,
        "candidates_generated":   n_candidates,
        "pairs_emitted":          n_pairs,
        "setup_failed":           n_setup_failed,
        "all_correct_discarded":  n_all_correct,
        "exec_level_distribution": exec_level_counts,
        "failure_mode_histogram":  failure_mode_counts,
        "temperature_stats":       temp_stats or {},
        "judge_cost_tokens":      judge_cost_tokens,
        "wall_clock_s":           round(wall_clock_s, 1),
    }


def print_report(report: dict):
    print("\n" + "=" * 60)
    print("DPO Forge — Run Report")
    print("=" * 60)
    print(f"  Prompts processed:     {report['prompts_processed']}")
    print(f"  Candidates generated:  {report['candidates_generated']}")
    print(f"  Pairs emitted:         {report['pairs_emitted']}")
    print(f"  Setup failed:          {report['setup_failed']}")
    print(f"  All-correct discarded: {report['all_correct_discarded']}")
    print(f"\n  Exec level distribution:")
    for level, count in sorted(report["exec_level_distribution"].items()):
        print(f"    {level:<16} {count}")
    temp_stats = report.get("temperature_stats") or {}
    if temp_stats:
        levels = ["L3_pass", "L3_mismatch", "L2_fail", "L1_fail"]
        header = f"    {'temp':>6}  " + "  ".join(f"{l:<14}" for l in levels) + "  total  pass%"
        print(f"\n  Temperature stats:")
        print(header)
        for temp in sorted(temp_stats, key=lambda t: float(t)):
            counts = temp_stats[temp]
            total = sum(counts.values())
            n_pass = counts.get("L3_pass", 0)
            pct = f"{100*n_pass/total:.0f}%" if total else "—"
            row = "  ".join(f"{counts.get(l, 0):<14}" for l in levels)
            print(f"    {temp:>6}  {row}  {total:<6}  {pct}")
    if report["failure_mode_histogram"]:
        print(f"\n  Failure mode histogram (top 10):")
        top = sorted(report["failure_mode_histogram"].items(), key=lambda x: -x[1])[:10]
        for mode, count in top:
            print(f"    {mode:<40} {count}")
    print(f"\n  Judge cost tokens:     {report['judge_cost_tokens']}")
    print(f"  Wall clock:            {report['wall_clock_s']}s")
    print("=" * 60)
