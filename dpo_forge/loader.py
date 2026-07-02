"""Stage 1: SFT file ingestion, normalization, and dedup.

Supports:
  - OpenAI chat format  {"messages": [{"role": ..., "content": ...}, ...]}
    (what CTL_LoRA_training_data.json and CTL_LoRA_eval_data.json use)
  - Alpaca format       {"instruction": ..., "input": ..., "output": ...}

Only single-turn examples (one user → one assistant) are in scope for v0.1.
Multi-turn rows are skipped with a count warning.
"""

from __future__ import annotations

import glob as _glob
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SourceExample:
    id: str              # stable 16-char SHA-256 prefix of the normalized prompt
    system: Optional[str]
    prompt: str          # the user turn
    reference: str       # ground-truth assistant answer (the chosen candidate)
    source_file: str = ""   # filename (no path) of the SFT file this came from
    source_index: int = 0   # zero-based position of this record within source_file
    meta: dict = field(default_factory=dict)  # passthrough: comments, failure_mode, etc.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _make_id(prompt: str) -> str:
    return hashlib.sha256(_normalize(prompt).encode()).hexdigest()[:16]


def _load_raw(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    # JSON array or single object
    if stripped.startswith(("[", "{")):
        try:
            obj = json.loads(stripped)
            return obj if isinstance(obj, list) else [obj]
        except json.JSONDecodeError:
            pass
    # JSONL fallback
    records = []
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _parse_chat(record: dict) -> Optional[tuple[Optional[str], str, str, dict]]:
    """
    Parse OpenAI chat format: {"messages": [{"role": ..., "content": ...}]}.
    Returns (system, prompt, reference, extra_meta) or None.
    """
    msgs = record.get("messages") or []
    if not msgs:
        return None

    system = None
    user_turns: list[str] = []
    asst_turns: list[str] = []

    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            system = content
        elif role == "user":
            user_turns.append(content)
        elif role == "assistant":
            asst_turns.append(content)

    if len(user_turns) != 1 or len(asst_turns) != 1:
        return None  # multi-turn or missing turns

    meta = {k: v for k, v in record.items() if k != "messages"}
    return system, user_turns[0], asst_turns[0], meta


def _parse_alpaca(record: dict) -> Optional[tuple[Optional[str], str, str, dict]]:
    """Parse Alpaca format: {"instruction": ..., "input": ..., "output": ...}."""
    instruction = record.get("instruction", "").strip()
    inp = record.get("input", "").strip()
    output = (record.get("output") or record.get("response", "")).strip()
    if not instruction or not output:
        return None
    prompt = (instruction + "\n\n" + inp) if inp else instruction
    meta = {k: v for k, v in record.items() if k not in ("instruction", "input", "output", "response")}
    return None, prompt, output, meta


def _parse_record(record: dict) -> Optional[tuple[Optional[str], str, str, dict, bool]]:
    """
    Try chat format first, then Alpaca.
    Returns (system, prompt, reference, meta, is_multiturn_skip) or None.
    """
    if "messages" in record:
        msgs = record.get("messages") or []
        user_count = sum(1 for m in msgs if m.get("role") == "user")
        if user_count > 1:
            return None, None, None, {}, True  # multi-turn skip
        result = _parse_chat(record)
        if result:
            sys, prompt, ref, meta = result
            return sys, prompt, ref, meta, False
        return None, None, None, {}, False

    if "instruction" in record:
        result = _parse_alpaca(record)
        if result:
            sys, prompt, ref, meta = result
            return sys, prompt, ref, meta, False

    return None, None, None, {}, False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_examples(
    sft_files: list[str],
    failure_mode_filter: Optional[str] = None,
    limit: Optional[int] = None,
    shuffle: bool = False,
    seed: int = 42,
) -> list[SourceExample]:
    """
    Load, normalize, and dedup SFT examples from one or more files or glob patterns.

    Args:
        sft_files: list of file paths or glob patterns
        failure_mode_filter: if set, only keep examples whose meta.failure_mode
            contains this string (case-insensitive)
        limit: max examples to return (applied after shuffle)
        shuffle: shuffle before applying limit
        seed: RNG seed for shuffle
    """
    paths: list[Path] = []
    for pattern in sft_files:
        expanded = _glob.glob(pattern, recursive=True)
        if expanded:
            paths.extend(Path(p) for p in sorted(expanded))
        else:
            p = Path(pattern)
            if p.exists():
                paths.append(p)

    n_multiturn = 0
    n_no_ref = 0
    n_unparseable = 0
    seen_ids: set[str] = set()
    examples: list[SourceExample] = []

    for path in paths:
        fname = path.name
        for rec_idx, rec in enumerate(_load_raw(path)):
            sys, prompt, ref, meta, is_multiturn = _parse_record(rec)

            if is_multiturn:
                n_multiturn += 1
                continue
            if prompt is None:
                n_unparseable += 1
                continue
            if not ref:
                n_no_ref += 1
                continue

            ex_id = _make_id(prompt)
            if ex_id in seen_ids:
                continue
            seen_ids.add(ex_id)

            if failure_mode_filter:
                mode = meta.get("failure_mode") or meta.get("failure_modes") or ""
                if isinstance(mode, list):
                    mode = ",".join(mode)
                if failure_mode_filter.lower() not in mode.lower():
                    continue

            examples.append(SourceExample(
                id=ex_id,
                system=sys,
                prompt=prompt,
                reference=ref,
                source_file=fname,
                source_index=rec_idx,
                meta=meta,
            ))

    if n_multiturn:
        print(f"[loader] Skipped {n_multiturn} multi-turn example(s) (out of scope for v0.1)")
    if n_no_ref:
        print(f"[loader] Skipped {n_no_ref} example(s) missing a reference answer")
    if n_unparseable:
        print(f"[loader] Skipped {n_unparseable} unparseable record(s)")
    print(f"[loader] Loaded {len(examples)} unique examples from {len(paths)} file(s)")

    if shuffle:
        random.Random(seed).shuffle(examples)
    if limit is not None:
        examples = examples[:limit]

    return examples
