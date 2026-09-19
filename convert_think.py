#!/usr/bin/env python3
"""Merge assistant reasoning_content into content wrapped in <think> tags.

Input files must be JSON arrays in SFT/ShareGPT-like structure. Records from all
input files are concatenated into one output array.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# Must match LlamaFactory's Template.thought_words for the qwen3_* templates
# (src/llamafactory/data/template.py, register_template default:
#     thought_words or ("<think>\n", "\n</think>\n\n")
# ).  Getting these delimiters exactly right matters twice over:
#   * enable_thinking=true  -> the block is kept verbatim and loss is computed on it,
#     so it must match the `<think>\n` the model's own chat template already has
#     open in the generation prompt at inference time;
#   * enable_thinking=false -> Template.remove_thought() strips the block with the
#     regex `<think>\n(.*?)\n</think>\n\n`, which silently fails to match any other
#     spelling and would leave literal tags in the training target.
THINK_OPEN = "<think>\n"
THINK_CLOSE = "\n</think>\n\n"

# Matches an already-wrapped assistant content in any spelling, so the script is
# idempotent and can be re-run over its own output.
THINK_BLOCK = re.compile(r"^\s*<think>(.*?)</think>\n*(.*)$", re.DOTALL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read one or more SFT JSON files, move assistant reasoning_content into "
            "assistant content as a <think>...</think> prefix in LlamaFactory's "
            "canonical thought_words spelling, drop reasoning_content, and write one "
            "merged JSON output file."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Input SFT JSON file paths or glob patterns (e.g. sft_training_data/*.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Path to output JSON file.",
    )
    parser.add_argument(
        "--only-reasoning",
        action="store_true",
        help=(
            "Keep only records where at least one assistant turn carries a non-empty "
            "reasoning_content (or an already-populated <think> block). Use this to "
            "build the dataset for a thinking SFT stage."
        ),
    )
    return parser.parse_args()


def expand_inputs(patterns: List[str]) -> List[Path]:
    paths: List[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            paths.extend(Path(match) for match in matches)
        else:
            paths.append(Path(pattern))

    unique_paths: List[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(path)
    return unique_paths


def load_array(path: Path) -> List[Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(f"Expected top-level JSON array in {path}")
    return data


def merge_assistant_think(record: Dict[str, Any]) -> bool:
    """Rewrite assistant turns in place.  Returns True if any carried real reasoning."""
    messages = record.get("messages")
    if not isinstance(messages, list):
        return False

    has_reasoning = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue

        content = message.get("content")
        if not isinstance(content, str):
            content = ""

        reasoning = message.pop("reasoning_content", None)
        reasoning_text = reasoning.strip() if isinstance(reasoning, str) else ""

        # Already wrapped (re-run over previous output, or hand-authored tags):
        # unwrap first so the delimiters get normalised rather than nested.
        wrapped = THINK_BLOCK.match(content)
        if wrapped:
            existing, content = wrapped.group(1).strip(), wrapped.group(2)
            if existing and not reasoning_text:
                reasoning_text = existing

        message["content"] = THINK_OPEN + reasoning_text + THINK_CLOSE + content
        has_reasoning = has_reasoning or bool(reasoning_text)

    return has_reasoning


def transform_records(records: List[Any], only_reasoning: bool = False) -> tuple[List[Any], int]:
    transformed: List[Any] = []
    reasoning_count = 0
    for record in records:
        has_reasoning = merge_assistant_think(record) if isinstance(record, dict) else False
        if has_reasoning:
            reasoning_count += 1
        if only_reasoning and not has_reasoning:
            continue
        transformed.append(record)
    return transformed, reasoning_count


def main() -> None:
    args = parse_args()
    input_paths = expand_inputs(args.inputs)

    if not input_paths:
        print("No input files provided.", file=sys.stderr)
        sys.exit(1)

    merged: List[Any] = []
    file_count = 0
    record_count = 0
    reasoning_total = 0

    try:
        for input_path in input_paths:
            data = load_array(input_path)
            kept, reasoning_count = transform_records(data, only_reasoning=args.only_reasoning)
            merged.extend(kept)
            file_count += 1
            record_count += len(data)
            reasoning_total += reasoning_count

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as out:
            json.dump(merged, out, ensure_ascii=True, indent=2)
            out.write("\n")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    empty = record_count - reasoning_total
    print(f"Processed {file_count} file(s), {record_count} record(s).")
    print(f"  with reasoning : {reasoning_total}")
    print(f"  empty <think>  : {empty}" + (" (dropped)" if args.only_reasoning else ""))
    print(f"Wrote {len(merged)} record(s) to {args.output}")


if __name__ == "__main__":
    main()
