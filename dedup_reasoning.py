#!/usr/bin/env python3
"""Remove records superseded by the reasoning corpus from the SFT source files.

The reasoning file (CTL_LoRAT_reasoning_v2.json) was built by taking existing
training records and writing a reasoning trace for each. Writing the trace
forced the answer to be verified, and many answers were corrected in the
process -- so for any prompt it covers, the reasoning file holds the CORRECT
version and the original source file holds a superseded one.

Leaving both in place trains the model on the prompt twice with two different
answers, at equal weight. This script deletes the superseded copies, leaving
the reasoning file as the single source of truth for the prompts it covers.

Records are matched on the full user turn(s), which the reasoning file
preserves verbatim from the original.

    # see what would change -- writes nothing
    python3 dedup_reasoning.py --dir ~/sft_sources --reasoning CTL_LoRAT_reasoning_v2.json

    # apply, backing every modified file up to <name>.json.bak
    python3 dedup_reasoning.py --dir ~/sft_sources --reasoning CTL_LoRAT_reasoning_v2.json --apply

The reasoning file is never modified, and is skipped if it sits inside --dir.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path


# --- record access ---------------------------------------------------------
# Source files carry {"id", "messages"}, but accept the sharegpt spelling too
# so this works on any of the corpus files without conversion.
_ROLE = {"role", "from"}
_TEXT = ("content", "value")
_USER = {"user", "human"}
_ASSISTANT = {"assistant", "gpt"}


def _turns(rec: dict) -> list[dict]:
    for field in ("messages", "conversations", "conversation"):
        if isinstance(rec.get(field), list):
            return rec[field]
    return []


def _role_of(msg: dict) -> str:
    for key in _ROLE:
        if key in msg:
            return str(msg[key]).lower()
    return ""


def _text_of(msg: dict) -> str:
    for key in _TEXT:
        if key in msg:
            return msg[key] or ""
    return ""


def prompt_key(rec: dict) -> tuple[str, ...]:
    """Identity of a record: every user turn, whitespace-normalised at the edges.

    All user turns rather than just the first, so a multi-turn record is not
    confused with a different one that happens to open the same way.
    """
    return tuple(_text_of(m).strip() for m in _turns(rec) if _role_of(m) in _USER)


def answer_text(rec: dict) -> str:
    return "\n".join(_text_of(m) for m in _turns(rec) if _role_of(m) in _ASSISTANT)


def load_records(path: Path) -> list[dict] | None:
    """Return the record list, or None if this file is not a training set."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"  ! {path.name}: unreadable ({exc.__class__.__name__}) — skipped")
        return None
    if not isinstance(data, list) or not data:
        return None
    if not isinstance(data[0], dict) or not _turns(data[0]):
        return None
    return data


# --- main ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=Path,
                    help="directory holding the SFT source *.json files")
    ap.add_argument("--reasoning", required=True, type=Path,
                    help="the reasoning corpus; its records win every conflict")
    ap.add_argument("--apply", action="store_true",
                    help="write the files (default: report only)")
    ap.add_argument("--recursive", action="store_true",
                    help="also scan subdirectories of --dir")
    ap.add_argument("--keep-exact-dupes", action="store_true",
                    help="do not remove byte-identical repeats of the same prompt")
    ap.add_argument("--backup-suffix", default=".bak",
                    help="suffix for backups of modified files (default: .bak)")
    args = ap.parse_args()

    if not args.dir.is_dir():
        print(f"error: --dir {args.dir} is not a directory", file=sys.stderr)
        return 2
    if not args.reasoning.is_file():
        print(f"error: --reasoning {args.reasoning} not found", file=sys.stderr)
        return 2

    reasoning = load_records(args.reasoning)
    if reasoning is None:
        print(f"error: {args.reasoning} is not a training-record list", file=sys.stderr)
        return 2

    # How many distinct answers the reasoning file carries per prompt. A prompt
    # can legitimately appear twice with different sample data; if the source
    # has more variants than the reasoning file does, deleting them all would
    # lose one, so that case is reported rather than silently applied.
    reasoning_variants: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for rec in reasoning:
        reasoning_variants[prompt_key(rec)].add(answer_text(rec))
    reasoning_keys = set(reasoning_variants)
    print(f"reasoning corpus : {args.reasoning.name} — {len(reasoning)} records, "
          f"{len(reasoning_keys)} distinct prompts\n")

    pattern = "**/*.json" if args.recursive else "*.json"
    files = sorted(p for p in args.dir.glob(pattern)
                   if p.is_file() and p.resolve() != args.reasoning.resolve())
    if not files:
        print(f"error: no *.json files found under {args.dir}", file=sys.stderr)
        return 2

    seen_exact: dict[tuple[str, ...], set[str]] = defaultdict(set)
    # Distinct answers per superseded prompt, not copy count: two byte-identical
    # copies are one variant and must not read as a variant being lost.
    source_variants: dict[tuple[str, ...], set[str]] = defaultdict(set)
    totals = Counter()
    planned: list[tuple[Path, list[dict]]] = []
    think_files: list[tuple[str, int]] = []

    for path in files:
        records = load_records(path)
        if records is None:
            continue

        kept, dropped_sup, dropped_dup = [], 0, 0
        for rec in records:
            key = prompt_key(rec)
            ans = answer_text(rec)
            if key in reasoning_keys:
                source_variants[key].add(ans)
                dropped_sup += 1
                continue
            if not args.keep_exact_dupes and ans in seen_exact[key]:
                dropped_dup += 1
                continue
            seen_exact[key].add(ans)
            kept.append(rec)

        n_think = sum(1 for r in records if "<think>" in answer_text(r))
        if n_think:
            think_files.append((path.name, n_think))

        totals["in"] += len(records)
        totals["superseded"] += dropped_sup
        totals["exact"] += dropped_dup
        totals["out"] += len(kept)
        if dropped_sup or dropped_dup:
            planned.append((path, kept))
            print(f"  {path.name:52s} {len(records):6d} → {len(kept):6d}"
                  f"   (-{dropped_sup} superseded, -{dropped_dup} duplicate)")
        else:
            print(f"  {path.name:52s} {len(records):6d}     unchanged")

    print(f"\n  {'TOTAL':52s} {totals['in']:6d} → {totals['out']:6d}"
          f"   (-{totals['superseded']} superseded, -{totals['exact']} duplicate)")

    # --- things that need a human decision ---------------------------------
    lost = [k for k, v in source_variants.items() if len(v) > len(reasoning_variants[k])]
    if lost:
        print(f"\n  ! {len(lost)} prompt(s) had more answer variants in the source files than the")
        print(f"    reasoning corpus carries, so a valid variant is dropped with the superseded one:")
        for key in lost[:5]:
            print(f"      {len(reasoning_variants[key])} in reasoning vs {len(source_variants[key])} in source: "
                  f"{(key[0] if key else '')[:88]}")
        if len(lost) > 5:
            print(f"      … and {len(lost) - 5} more")

    if think_files:
        print(f"\n  ! <think> blocks found OUTSIDE the reasoning corpus — these files feed phase 1,")
        print(f"    where reasoning must not appear:")
        for name, n in think_files:
            print(f"      {name}: {n} record(s)")

    uncovered = reasoning_keys - set(source_variants)
    if uncovered:
        print(f"\n  · {len(uncovered)} reasoning prompt(s) matched nothing in the source files "
              f"(new prompts, or the user turn was edited).")

    # --- write --------------------------------------------------------------
    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to write these files.")
        return 0

    for path, kept in planned:
        backup = path.with_suffix(path.suffix + args.backup_suffix)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"\nwrote {len(planned)} file(s); originals backed up with '{args.backup_suffix}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
