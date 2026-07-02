#!/usr/bin/env python3
"""
dpo-forge — CTL2 DPO preference-pair generator

Converts SFT examples into on-policy DPO pairs by sampling completions from
the locally trained model, executing them against CloverDX skeleton graphs,
and judging them with a stronger LLM.

Usage:
  python dpo_forge.py run   --config configs/forge.yaml [--limit N] [--dry-run]
  python dpo_forge.py audit data/dpo/forged.provenance.jsonl
  python dpo_forge.py stats data/dpo/forged.provenance.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import yaml

# Load .env from the project root or dpo_forge/ subdir (whichever exists first)
try:
    from dotenv import load_dotenv
    for _env_candidate in (
        Path(__file__).parent / ".env",
        Path(__file__).parent / "dpo_forge" / ".env",
    ):
        if _env_candidate.exists():
            load_dotenv(_env_candidate, override=False)
            break
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent

DEFAULT_CONFIG: dict = {
    "input": {
        "sft_files": [],
        "failure_mode_filter": None,
        "limit": None,
        "shuffle": {"enabled": True, "seed": 42},
    },
    "model": {
        "checkpoint_dir": None,
        "adapter_dir": None,
        "dtype": "bfloat16",
        "attn_impl": "flash_attention_2",
        "enable_thinking": False,
    },
    "generation": {
        "temperatures": [0.0, 0.7, 0.9, 1.0],
        "top_p": 0.95,
        "max_new_tokens": 1024,
        "seed": 42,
        "dedup_candidates": True,
        "resample_if_all_pass": True,
    },
    "judge": {
        "provider": "anthropic",
        "model": "claude-opus-4-20250514",
        "api_key": None,
        "base_url": None,
        "confidence_threshold": 0.6,
        "max_json_retries": 2,
    },
    "pairing": {
        "strategy": "best_vs_worst",
        "max_pairs_per_prompt": 3,
    },
    "balance": {
        "max_share_per_failure_mode": 0.25,
        "max_share_per_component": 0.40,
        "max_share_l1_rejected": 0.20,
        "enforce": "warn",
    },
    "output": {
        "dpo_file": "data/dpo/forged.jsonl",
        "provenance_file": "data/dpo/forged.provenance.jsonl",
        "wandb": {"enabled": False, "project": "llamafactory", "entity": None},
    },
    "clover": {
        "endpoint": None,
        "sandbox": "DPOForge",
        "ref_dir": "data-tmp/forge/ref",
        "work_dir": "data-tmp/forge/work",
        "debug_dir": "data-tmp/forge/_debug",
        "await_timeout_s": 60,
        "workers": 1,
    },
    "setup_llm": {
        "provider": "anthropic",
        "model": "claude-opus-4-20250514",
        "api_key": None,
        "cache": True,
    },
    "state": {
        "db_path": "data/dpo/forge_state.db",
    },
}

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env(v: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), v)


def _expand_recursive(obj: Any) -> Any:
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _expand_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_recursive(v) for v in obj]
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path: Path) -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return _expand_recursive(raw)


# ---------------------------------------------------------------------------
# run subcommand
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace):
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        sys.exit(f"ERROR: config not found: {config_path}")

    cfg = _deep_merge(DEFAULT_CONFIG, load_config(config_path))

    # CLI overrides
    verbose = getattr(args, "verbose", False)
    start_index = getattr(args, "index", 0) or 0
    # Limit is applied AFTER index offset — don't pass it to the loader yet
    cli_limit = args.limit  # None means "use config value"
    if args.dry_run:
        _dry_run(cfg)
        return

    from dpo_forge.loader import load_examples
    from dpo_forge.generator import LocalGenerator
    from dpo_forge.judge import JudgeClient
    from dpo_forge.pairing import (
        label_candidate, build_pairs, CompositionStats,
    )
    from dpo_forge.output import (
        write_dpo_jsonl, write_provenance_jsonl, write_invalid_jsonl,
        write_dataset_info, build_report, print_report,
    )
    from dpo_forge.state import ForgeState

    # ── Load examples ──────────────────────────────────────────────────
    input_cfg = cfg["input"]
    shuffle_cfg = input_cfg.get("shuffle") or {}
    examples = load_examples(
        sft_files=input_cfg["sft_files"],
        failure_mode_filter=input_cfg.get("failure_mode_filter"),
        limit=None,   # applied below, after index offset
        shuffle=shuffle_cfg.get("enabled", True),
        seed=shuffle_cfg.get("seed", 42),
    )
    if not examples:
        sys.exit("No examples found — check input.sft_files in your config.")

    if start_index:
        if start_index >= len(examples):
            sys.exit(f"ERROR: --index {start_index} is out of range (only {len(examples)} examples loaded)")
        examples = examples[start_index:]
        print(f"[dpo-forge] Skipping first {start_index} example(s) (--index {start_index})")

    # Apply limit after offset: CLI overrides config
    effective_limit = cli_limit if cli_limit is not None else input_cfg.get("limit")
    if effective_limit is not None:
        examples = examples[:effective_limit]
    print(f"[dpo-forge] Processing {len(examples)} example(s)"
          + (f" (from index {start_index})" if start_index else "")
          + (f", limit {effective_limit}" if effective_limit is not None else ""))

    # ── Init clients ───────────────────────────────────────────────────
    gen_cfg = cfg["model"]
    if not gen_cfg.get("checkpoint_dir"):
        sys.exit("ERROR: model.checkpoint_dir must be set.")

    generator = LocalGenerator(gen_cfg)
    generator.warm_up()

    judge_client = JudgeClient(cfg["judge"])

    # MCP + setup agent (Phase 2 — None if CloverDX not connected)
    mcp_client = None
    setup_loop = None
    clover_cfg = cfg.get("clover") or {}
    if clover_cfg.get("endpoint"):
        from dpo_forge.mcp_client import MCPClient
        from dpo_forge.agent_loop import AgentLoop
        mcp_client = MCPClient(clover_cfg["endpoint"])
        setup_llm_cfg = cfg.get("setup_llm") or {}
        setup_loop = AgentLoop(
            provider=setup_llm_cfg.get("provider", "anthropic"),
            model=setup_llm_cfg.get("model", "claude-opus-4-20250514"),
            mcp_client=mcp_client,
            api_key=setup_llm_cfg.get("api_key"),
        )
    else:
        print("[dpo-forge] No clover.endpoint configured — running Phase 1 (no execution validation)")

    state_db = ForgeState(Path(cfg["state"]["db_path"]))

    # ── Output paths ───────────────────────────────────────────────────
    dpo_path = Path(cfg["output"]["dpo_file"])
    prov_path = Path(cfg["output"]["provenance_file"])
    invalid_path = dpo_path.with_suffix("").with_suffix(".invalid.jsonl")

    # ── Main loop ──────────────────────────────────────────────────────
    gen_cfg2   = cfg["generation"]
    pair_cfg   = cfg["pairing"]
    bal_cfg    = cfg["balance"]
    judge_cfg  = cfg["judge"]
    temperatures = gen_cfg2.get("temperatures", [0.1, 0.5, 0.8, 1.0])
    # Canonical system prompt — overrides whatever the SFT example carries
    mut_system_prompt: Optional[str] = (cfg.get("model") or {}).get("system_prompt") or None
    if mut_system_prompt:
        mut_system_prompt = mut_system_prompt.strip()

    all_pairs: list = []
    stats = CompositionStats()
    t_start = time.monotonic()

    n_setup_failed  = 0
    n_all_correct   = 0
    n_candidates    = 0
    exec_counts: dict = {}
    fm_counts:   dict = {}
    temp_stats:  dict = {}   # {str(temp): {exec_level: count}}

    for i, example in enumerate(examples):
        print(f"\n[{i+1}/{len(examples)}] example {example.id}")

        # ── Setup (Phase 2) ───────────────────────────────────────────
        bundle = None
        if setup_loop and mcp_client:
            from dpo_forge.setup_agent import run_setup_agent, SetupBundle
            from dpo_forge.runner import run_candidate, ExecResult

            cached = state_db.get_setup_bundle(example.id)
            if cached:
                bundle = SetupBundle(**cached)
                # Re-validate cached bundles (catches entries stored before the
                # golden_records check was introduced).
                if not bundle.golden_records:
                    comp = bundle.component_type or "unknown"
                    fail_reason = (
                        f"reference_produced_zero_records: cached bundle has empty "
                        f"golden_records (component={comp})"
                    )
                    n_setup_failed += 1
                    print(f"  [setup] INVALID cached bundle — {fail_reason}")
                    write_invalid_jsonl(
                        example, fail_reason, invalid_path,
                        log_excerpt=bundle.reference_log_excerpt,
                    )
                    continue
                print("  [setup] Using cached bundle")
            else:
                print("  [setup] Calling setup agent (LLM + MCP) …")
                bundle, fail_reason, fail_log = run_setup_agent(
                    example, setup_loop,
                    sandbox=clover_cfg["sandbox"],
                    work_dir=clover_cfg["work_dir"],
                    ref_dir=clover_cfg["ref_dir"],
                    await_timeout_s=clover_cfg.get("await_timeout_s", 60),
                )
                if bundle is None:
                    n_setup_failed += 1
                    print(f"  [setup] FAILED ({fail_reason}) — skipping example")
                    write_invalid_jsonl(
                        example, fail_reason, invalid_path,
                        log_excerpt=fail_log,
                    )
                    continue
                state_db.save_setup_bundle(example.id, asdict(bundle))

        if bundle:
            print(f"  [setup] component={bundle.component_type}  skeleton={bundle.skeleton_path}")

        # Augment prompt with component type so the MUT knows which entry point to use
        mut_prompt = example.prompt
        if bundle:
            mut_prompt = f"Target component: {bundle.component_type}\n\n{example.prompt}"

        if verbose:
            _log_mut_input(example, component_type=bundle.component_type if bundle else None)

        # ── Generate candidates ────────────────────────────────────────
        print(f"  [MUT] Generating {len(temperatures)} candidate(s) at temps {temperatures} …")
        candidates = generator.generate_candidates(
            source_id=example.id,
            system=mut_system_prompt if mut_system_prompt is not None else example.system,
            prompt=mut_prompt,
            temperatures=temperatures,
            top_p=gen_cfg2.get("top_p", 0.95),
            max_new_tokens=gen_cfg2.get("max_new_tokens", 1024),
            seed=gen_cfg2.get("seed"),
            dedup=gen_cfg2.get("dedup_candidates", True),
        )
        n_candidates += len(candidates)
        print(f"  Generated {len(candidates)} candidate(s)")

        # ── Execute + judge each candidate ─────────────────────────────
        from dpo_forge.runner import run_candidate as _run_candidate, ExecResult
        from dpo_forge.pairing import LabeledCandidate

        labeled: list = []
        for cand in candidates:
            if verbose:
                _log_candidate(cand)

            # Run against CloverDX (or stub)
            if bundle and mcp_client:
                temp = cand.gen_meta.get("temperature", "?")
                print(f"    [exec] cand[{cand.index}] t={temp}  running on CloverDX …")
                exec_result = _run_candidate(
                    cand.text, cand.index, bundle, mcp_client,
                    clover_cfg.get("await_timeout_s", 60),
                )
            else:
                exec_result = ExecResult(
                    candidate_index=cand.index,
                    exec_level="L1_fail",
                    run_status="STUB",
                    log_excerpt="[Phase 1] No CloverDX execution",
                )

            exec_counts[exec_result.exec_level] = exec_counts.get(exec_result.exec_level, 0) + 1
            temp = cand.gen_meta.get("temperature", "?")
            t_key = str(temp)
            if t_key not in temp_stats:
                temp_stats[t_key] = {}
            temp_stats[t_key][exec_result.exec_level] = temp_stats[t_key].get(exec_result.exec_level, 0) + 1
            detail = exec_result.log_excerpt[:120] if exec_result.log_excerpt else ""
            print(f"    cand[{cand.index}] t={temp}  {exec_result.exec_level} ({exec_result.run_status})"
                  + (f"\n    ! {detail}" if detail else ""))

            # Judge (always call, even for L1/L2 — provides failure mode taxonomy)
            print(f"    [judge] cand[{cand.index}] querying judge LLM …")
            verdict = judge_client.judge(
                system=example.system,
                prompt=example.prompt,
                candidate_text=cand.text,
                exec_level=exec_result.exec_level,
                run_status=exec_result.run_status,
                log_excerpt=exec_result.log_excerpt,
                tracking=exec_result.tracking,
                output_diff=exec_result.output_diff,
                component_type=bundle.component_type if bundle else "",
                max_retries=judge_cfg.get("max_json_retries", 2),
            )

            lc = label_candidate(
                cand, exec_result, verdict,
                confidence_threshold=judge_cfg.get("confidence_threshold", 0.6),
            )
            labeled.append(lc)

        # ── Build pairs ────────────────────────────────────────────────
        if not any(lc.is_rejected for lc in labeled):
            n_all_correct += 1
            print("  All candidates correct — no signal")
            continue

        pairs = build_pairs(
            example, labeled,
            strategy=pair_cfg.get("strategy", "best_vs_worst"),
            max_pairs=pair_cfg.get("max_pairs_per_prompt", 3),
        )
        if not pairs:
            print("  No valid pairs constructed")
            continue

        print(f"  → {len(pairs)} pair(s)")
        all_pairs.extend(pairs)

        for pair in pairs:
            comp_type = bundle.component_type if bundle else ""
            stats.add(pair, comp_type)
            for fm in pair.rejected_failure_modes:
                fm_counts[fm] = fm_counts.get(fm, 0) + 1

        # Write pairs
        write_dpo_jsonl(pairs, dpo_path)
        write_provenance_jsonl(pairs, prov_path)
        state_db.save_pairs(example.id, [asdict(p) for p in pairs])

    # ── Composition cap check ──────────────────────────────────────────
    violations = stats.check_caps(
        max_fm_share=bal_cfg.get("max_share_per_failure_mode", 0.25),
        max_comp_share=bal_cfg.get("max_share_per_component", 0.40),
        max_l1_share=bal_cfg.get("max_share_l1_rejected", 0.20),
    )
    if violations:
        msg = "Composition cap violations:\n" + "\n".join(f"  - {v}" for v in violations)
        if bal_cfg.get("enforce") == "fail":
            state_db.close()
            sys.exit("ERROR: " + msg)
        else:
            print("[WARNING] " + msg)

    # ── Write dataset_info + report ────────────────────────────────────
    write_dataset_info(dpo_path, dpo_path.parent)

    report = build_report(
        n_prompts=len(examples),
        n_candidates=n_candidates,
        n_pairs=len(all_pairs),
        n_setup_failed=n_setup_failed,
        n_all_correct=n_all_correct,
        exec_level_counts=exec_counts,
        failure_mode_counts=fm_counts,
        judge_cost_tokens=judge_client.total_tokens,
        temp_stats=temp_stats,
        wall_clock_s=time.monotonic() - t_start,
    )
    print_report(report)

    print(f"\nDPO file:        {dpo_path}")
    print(f"Provenance file: {prov_path}")
    if invalid_path.exists():
        print(f"Invalid file:    {invalid_path}  (review & fix these SFT examples)")

    state_db.close()


def _dry_run(cfg: dict):
    print("[dry-run] Effective config:")
    print(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
    sft_files = cfg["input"].get("sft_files") or []
    print(f"[dry-run] SFT files: {sft_files}")
    ckpt = cfg["model"].get("checkpoint_dir")
    print(f"[dry-run] Checkpoint: {ckpt}")
    endpoint = (cfg.get("clover") or {}).get("endpoint")
    print(f"[dry-run] CloverDX endpoint: {endpoint or '(not set — Phase 1)'}")
    print(f"[dry-run] Judge: {cfg['judge']['provider']} / {cfg['judge']['model']}")
    print(f"[dry-run] Output: {cfg['output']['dpo_file']}")


# ---------------------------------------------------------------------------
# cache subcommand
# ---------------------------------------------------------------------------

def cmd_cache(args: argparse.Namespace):
    from dpo_forge.state import ForgeState

    cfg_path = Path(args.config).resolve() if args.config else None
    db_path: Optional[Path] = None
    if cfg_path and cfg_path.exists():
        raw = load_config(cfg_path)
        db_path = Path(raw.get("state", {}).get("db_path", DEFAULT_CONFIG["state"]["db_path"]))
    else:
        db_path = Path(DEFAULT_CONFIG["state"]["db_path"])

    if not db_path.exists():
        print(f"No state DB found at {db_path}")
        return

    state = ForgeState(db_path)
    conn = state._conn

    if args.cache_cmd == "list":
        rows = conn.execute(
            "SELECT example_id, bundle_json, created_at FROM setup_cache ORDER BY created_at"
        ).fetchall()
        if not rows:
            print(f"Setup cache is empty  ({db_path})")
            state.close()
            return
        print(f"Setup cache — {len(rows)} entry/entries  ({db_path})\n")
        for example_id, bundle_json, created_at in rows:
            try:
                b = json.loads(bundle_json)
            except Exception:
                b = {}
            comp   = b.get("component_type", "?")
            skel   = b.get("skeleton_path", "?")
            n_gold = len(b.get("golden_records", []))
            params = b.get("run_params", {})
            notes  = b.get("setup_notes", "")
            print(f"  {example_id}")
            print(f"    cached     : {created_at}")
            print(f"    component  : {comp}")
            print(f"    skeleton   : {skel}")
            print(f"    golden rows: {n_gold}")
            if params:
                params_str = "  ".join(f"{k}={v}" for k, v in params.items() if k != "WORK_DIR")
                print(f"    run_params : {params_str}" if params_str else "    run_params : (none beyond WORK_DIR)")
            if notes:
                print(f"    notes      : {notes[:120]}" + ("…" if len(notes) > 120 else ""))
            print()

    elif args.cache_cmd == "purge":
        example_id = getattr(args, "example_id", None)
        if example_id:
            cur = conn.execute(
                "DELETE FROM setup_cache WHERE example_id = ?", (example_id,)
            )
            conn.commit()
            if cur.rowcount:
                print(f"Purged setup cache for example {example_id!r}")
            else:
                print(f"No cache entry found for {example_id!r}")
        else:
            count = conn.execute("SELECT COUNT(*) FROM setup_cache").fetchone()[0]
            if count == 0:
                print("Setup cache is already empty")
            else:
                conn.execute("DELETE FROM setup_cache")
                conn.commit()
                print(f"Purged {count} setup cache entry/entries from {db_path}")

    state.close()


# ---------------------------------------------------------------------------
# audit subcommand
# ---------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace):
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"ERROR: file not found: {path}")

    records = _load_provenance(path)
    print(f"Provenance file: {path}  ({len(records)} records)")
    print()

    sample_n = min(args.n, len(records))
    import random
    sample = random.sample(records, sample_n) if sample_n < len(records) else records

    for i, rec in enumerate(sample):
        print(f"─── Record {i+1}/{sample_n} ─── example_id={rec.get('example_id','?')}")
        print(f"  exec_level  : {rec.get('rejected_exec_level','?')}")
        print(f"  failure_modes: {rec.get('rejected_failure_modes','?')}")
        prov = rec.get("provenance") or {}
        v = prov.get("verdict") or {}
        if v:
            print(f"  verdict     : {v.get('verdict','?')}  conf={v.get('confidence','?')}")
            print(f"  explanation : {v.get('explanation','')}")
        diff = prov.get("output_diff","")
        if diff:
            print(f"  output_diff : {diff[:200]}")
        log = prov.get("log_excerpt","")
        if log:
            print(f"  log_excerpt : {log[:200]}")
        print()


# ---------------------------------------------------------------------------
# stats subcommand
# ---------------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace):
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"ERROR: file not found: {path}")

    records = _load_provenance(path)
    total = len(records)
    print(f"Provenance file : {path}")
    print(f"Total pairs     : {total}")

    if total == 0:
        return

    # Exec level distribution
    exec_counts: dict = {}
    fm_counts:   dict = {}
    verdicts:    dict = {}
    for rec in records:
        level = rec.get("rejected_exec_level", "unknown")
        exec_counts[level] = exec_counts.get(level, 0) + 1
        for fm in (rec.get("rejected_failure_modes") or []):
            fm_counts[fm] = fm_counts.get(fm, 0) + 1
        prov = rec.get("provenance") or {}
        v = (prov.get("verdict") or {}).get("verdict", "unknown")
        verdicts[v] = verdicts.get(v, 0) + 1

    print("\nExec level distribution:")
    for level, count in sorted(exec_counts.items()):
        print(f"  {level:<18} {count:>5}  ({100*count/total:.1f}%)")

    print("\nJudge verdict distribution:")
    for v, count in sorted(verdicts.items()):
        print(f"  {v:<22} {count:>5}  ({100*count/total:.1f}%)")

    if fm_counts:
        print("\nFailure mode histogram:")
        for fm, count in sorted(fm_counts.items(), key=lambda x: -x[1]):
            print(f"  {fm:<42} {count:>5}  ({100*count/total:.1f}%)")


def _log_mut_input(example, component_type: Optional[str] = None) -> None:
    """Print the prompt sent to the MUT (system + user)."""
    print("  --- MUT input ---")
    if example.system:
        sys_lines = example.system.splitlines()
        print(f"  [system] ({len(sys_lines)} lines)")
        for line in sys_lines[:6]:
            print(f"  > {line}")
        if len(sys_lines) > 6:
            print(f"  > ... ({len(sys_lines) - 6} more lines)")
    if component_type:
        print(f"  [component hint] Target component: {component_type}")
    user_lines = example.prompt.splitlines()
    print(f"  [user] ({len(user_lines)} lines)")
    for line in user_lines[:40]:
        print(f"  > {line}")
    if len(user_lines) > 40:
        print(f"  > ... ({len(user_lines) - 40} more lines)")
    print()


def _log_candidate(cand) -> None:
    """Print the CTL generated by the MUT for one candidate."""
    temp = cand.gen_meta.get("temperature", "?")
    print(f"    --- cand[{cand.index}]  temp={temp}  ({len(cand.text)} chars) ---")
    lines = cand.text.splitlines()
    for line in lines[:30]:
        print(f"    | {line}")
    if len(lines) > 30:
        print(f"    | ... ({len(lines) - 30} more lines)")
    print()


def _load_provenance(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="dpo_forge",
        description="CTL2 DPO preference-pair generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
subcommands:
  run    Generate DPO pairs from SFT examples
  audit  Inspect a sample of provenance records
  stats  Print failure-mode histogram for a provenance file

examples:
  python dpo_forge.py run --config configs/forge.yaml
  python dpo_forge.py run --config configs/forge.yaml --limit 50 --dry-run
  python dpo_forge.py stats data/dpo/forged.provenance.jsonl
  python dpo_forge.py audit data/dpo/forged.provenance.jsonl --n 10
""",
    )
    sub = parser.add_subparsers(dest="cmd")

    # run
    p_run = sub.add_parser("run", help="Generate DPO pairs")
    p_run.add_argument("--config", "-c", required=True, metavar="YAML",
                       help="Path to forge.yaml config file")
    p_run.add_argument("--limit", "-n", type=int, metavar="N",
                       help="Process at most N examples (overrides config)")
    p_run.add_argument("--index", type=int, default=0, metavar="N",
                       help="Skip first N examples (0-based start index)")
    p_run.add_argument("--verbose", "-v", action="store_true",
                       help="Show MUT input prompt and generated CTL for each candidate")
    p_run.add_argument("--dry-run", action="store_true",
                       help="Print effective config and exit without running")

    # cache
    p_cache = sub.add_parser("cache", help="Inspect or purge the setup-bundle cache")
    p_cache.add_argument("--config", "-c", metavar="YAML", default=None,
                         help="Config file to locate the state DB (default: data/dpo/forge_state.db)")
    cache_sub = p_cache.add_subparsers(dest="cache_cmd")

    cache_list = cache_sub.add_parser("list", help="Show all cached setup bundles")

    cache_purge = cache_sub.add_parser("purge", help="Delete cached setup bundles")
    cache_purge.add_argument("--example-id", metavar="ID", default=None,
                             help="Purge only this example (omit to purge all)")

    # audit
    p_audit = sub.add_parser("audit", help="Inspect provenance records")
    p_audit.add_argument("file", help="Path to .provenance.jsonl file")
    p_audit.add_argument("--n", type=int, default=5, metavar="N",
                         help="Number of records to display (default 5)")

    # stats
    p_stats = sub.add_parser("stats", help="Print failure-mode histogram")
    p_stats.add_argument("file", help="Path to .provenance.jsonl file")

    args = parser.parse_args()

    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "cache":
        if not args.cache_cmd:
            p_cache.print_help()
        else:
            cmd_cache(args)
    elif args.cmd == "audit":
        cmd_audit(args)
    elif args.cmd == "stats":
        cmd_stats(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
