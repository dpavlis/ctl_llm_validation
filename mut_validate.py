#!/home/pavlisd/venv/bin/python
"""
mut-validate — MUT self-correction / judge-fix SFT generator

Reads SFT examples (same formats as dpo_forge.py), keeps only those whose
user prompt states input/output metadata plus a clear code-generation
instruction, sends the prompt to the locally trained model under test (MUT),
and has a stronger judge LLM review the resulting CTL2 code against a fixed
ISSUES / SUGGESTIONS / VERDICT text format (no CloverDX execution involved).

  - If the MUT is right first try (PASS, no WARNING) -> counted, no output.
  - If not, the review is fed back to the MUT for another attempt, up to
    --attempts total (default: 2, i.e. one retry — the original behavior).
      - If a later attempt then reviews as PASS -> a "MUT self-corrected"
        SFT conversation (the full multi-turn attempt/feedback history) is
        appended to output.self_corrected_file.
      - If every attempt is exhausted without a PASS -> the judge rewrites
        the LAST attempt's code itself, and a 4-turn "judge corrected it"
        SFT conversation is appended to output.judge_corrected_file.

  --tweak: before any of the above, the judge LLM rewrites the prompt into a
  different-but-structurally-similar task (new domain, new field names/types,
  a genuinely different business rule, same component type) — so the MUT is
  tested on something it wasn't trained on verbatim. The business domain,
  process, and region are picked from curated lists (review_judge.py) rather
  than left for the model to invent — it otherwise reliably converges on the
  same few domains. Deterministic per example by default (reproducible
  re-runs); pass --tweak-random too for a fresh random domain every run.

Usage:
  /home/pavlisd/venv/bin/python mut_validate.py <input_file>
      [--config configs/mut_validate.yaml] [--index N] [--limit N]
      [--attempts N] [--verbose] [--dry-run] [--overwrite] [--tweak] [--tweak-random]

Runs on GPU 1 by default (CUDA_VISIBLE_DEVICES=1) so it doesn't collide with
the judge server, typically running on GPU 0. Override by exporting
CUDA_VISIBLE_DEVICES yourself before invoking.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

# Default to GPU 1 for the MUT checkpoint — GPU 0 is normally occupied by the
# local judge server (e.g. the Qwen3-Coder-Next vLLM instance at :3000).
# Must be set before torch initializes CUDA; setdefault so an explicit
# CUDA_VISIBLE_DEVICES in the environment still wins.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")

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

DEFAULT_CONFIG: dict = {
    "model": {
        "checkpoint_dir": None,
        "adapter_dir": None,
        "dtype": "bfloat16",
        "attn_impl": "flash_attention_2",
        "system_prompt": None,
        "generation": {
            "temperature": 0.3,
            "top_p": 1.0,
            "top_k": 50,
            "repetition_penalty": 1.0,
            "max_new_tokens": 2048,
            "seed": 42,
        },
    },
    "judge": {
        "provider": "anthropic",
        "model": "claude-opus-4-20250514",
        "api_key": None,
        "base_url": None,
        "max_retries": 2,
        # Confirmed via real runs: reasoning-tier models can spend the ENTIRE
        # budget on hidden reasoning tokens on a hard fix() task and return
        # empty content (finish_reason="length") — see ReviewJudgeClient
        # ._call_openai's exhaustion check. 8192 gives more headroom than
        # the 4096 that was observed to run out; still bounded, and a
        # genuine exhaustion now raises instead of silently corrupting output.
        "max_completion_tokens": 8192,  # cap on the judge's response length per call (OpenAI provider only; ignored by anthropic)
        "reasoning_effort": "medium",   # OpenAI provider only: none | minimal | low | medium | high | xhigh
        # OpenAI provider only — see ReviewJudgeClient's class docstring in
        # review_judge.py. The review/fix system prompts are large (~25K
        # tokens) and near-fully stable, but calls are spaced out by local
        # MUT generation time in between, which was expiring the default
        # short-lived cache before the next call arrived.
        # Versioned ("v7") so bumping it deliberately busts the cache
        # namespace whenever review_judge.py's shared system-prompt content
        # (rules/reference/notes) changes materially — bump this alongside
        # such edits. Each call suffixes its own purpose (review/fix).
        "prompt_cache_key": "ctl-reviewer:v7",
        # SDK only accepts exactly "in_memory" (short default) or "24h"
        # (extended) — there is no shorter non-default option to pick.
        "prompt_cache_retention": "24h",      # "24h" | "in_memory" | null to omit the field entirely
        "request_timeout_s": 180,       # hard cap on a single judge HTTP call
    },
    # Used only with --tweak. A separate, usually cheaper/local, LLM that rewrites
    # each prompt (new domain/fields/logic) before it's shown to the MUT. Kept
    # distinct from "judge" — defaults to the local Qwen server, since OpenAI's
    # moderation classifier has intermittently flagged the tweak prompt (a
    # completely benign "rewrite this into a new practice task" request) on
    # some reasoning-tier OpenAI models.
    "tweak_llm": {
        "provider": "openai",
        "model": "Qwen3-Coder-Next",
        "api_key": "not-needed",
        "base_url": "http://virt-ai:3000/v1",
        "max_retries": 2,
        "max_completion_tokens": 8192,  # see the judge section's comment on this — same exhaustion risk when tweak_llm is swapped to a reasoning-tier OpenAI model
        "reasoning_effort": "medium",
        # Local vLLM servers typically don't recognize these OpenAI-specific
        # fields; ReviewJudgeClient auto-detects the rejection and stops
        # sending them after the first failed attempt, so leaving them set
        # here is harmless even against a local server. Own version counter
        # since this covers a different prompt family (tweak/numeric-check)
        # — bump independently of "ctl-reviewer" above.
        "prompt_cache_key": "ctl-tweak:v1",
        "prompt_cache_retention": "24h",
        "request_timeout_s": 180,
    },
    # Optional: a real CTL2 compiler/metadata check via an MCP server's
    # `ctl_validate` tool (Streamable HTTP transport), used as a fast,
    # deterministic pre-filter in front of the LLM judge — see
    # dpo_forge/ctl_validate_mcp.py for the full rationale. Disabled by
    # default since it depends on an external server actually running.
    "ctl_validate_mcp": {
        "enabled": False,
        "url": "http://localhost:8083/clover/mcp/mcp",
        "timeout_s": 30,
    },
    "output": {
        "self_corrected_file": "data/mut_validate/self_corrected.jsonl",
        "judge_corrected_file": "data/mut_validate/judge_corrected.jsonl",
    },
}

# ---------------------------------------------------------------------------
# Config loading (mirrors dpo_forge.py)
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
# Filter: "contains metadata and a clear instruction to generate code"
# ---------------------------------------------------------------------------

_METADATA_RE = re.compile(
    r"<Metadata\b"              # XML block, e.g. <Metadata id="...">
    r"|\binput\s+metadata\b"    # prose header, e.g. "Input metadata (port 0):"
    r"|\boutput\s+metadata\b",  # prose header, e.g. "Output metadata (port 0):"
    re.IGNORECASE,
)
_INSTRUCTION_RE = re.compile(
    r"\b(write|create|generate|implement|produce|build|provide|fix|correct|refactor|show|give)\b"
    r"[^.\n]{0,100}\b(ctl2?|transform|component|reformat|rollup|filter|normalizer|"
    r"denormalizer|partition|join|lookup|sequence|data\s*generator|code|solution|"
    r"implementation|expression|records?)\b"
    r"|\bhow\s+(do|can|would|should)\s+(i|you)\b[^?\n]{0,150}\bctl2?\b",
    re.IGNORECASE,
)


def _is_codegen_with_metadata(example) -> bool:
    """True if the user prompt has both a metadata block — an XML
    <Metadata> block, or a prose "Input/Output metadata" header (some SFT
    sources describe ports as a plain field list instead of XML, e.g.
    "Input metadata (port 0):\\n- field: type") — and a recognizable
    code-generation instruction. A simple regex heuristic (mirrors loader.py's
    substring-based failure_mode_filter) — false negatives just mean fewer
    examples processed, not incorrect ones."""
    return bool(_METADATA_RE.search(example.prompt)) and bool(_INSTRUCTION_RE.search(example.prompt))


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _source_identity(example) -> str:
    """Every identifier that could help someone find this exact example again
    later — its ordinal position in the input file we loaded, that file's own
    name, and (if present) the record's own reference to an even earlier
    original source file/id, from before it was merged into this input file."""
    parts = [f"source_index={example.source_index}", f"input_file={example.source_file!r}"]
    orig_file = example.meta.get("source_file")
    if orig_file:
        parts.append(f"original_source_file={orig_file!r}")
    orig_id = example.meta.get("id")
    if orig_id:
        parts.append(f"original_id={orig_id!r}")
    parts.append(f"example_id={example.id}")
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Logging helpers — console output stays exactly as before (short, and gated
# behind --verbose for large bodies); the run log file additionally gets
# EVERYTHING, always at full length, regardless of --verbose.
# ---------------------------------------------------------------------------

def _log(msg: str, log_fh=None) -> None:
    """Print to console and mirror the same line(s) into the run log file."""
    print(msg)
    if log_fh:
        log_fh.write(msg + "\n")
        log_fh.flush()


def _log_full_body(label: str, text: str, log_fh, console: bool, max_lines: int = 30) -> None:
    """Always write the full, untruncated text to the run log file. Only
    echoes a (possibly truncated) preview to the console when console=True."""
    if log_fh:
        log_fh.write(f"\n--- {label} (full) ---\n{text}\n")
        log_fh.flush()
    if console:
        lines = text.splitlines()
        print(f"    --- {label} ({len(lines)} lines) ---")
        for line in lines[:max_lines]:
            print(f"    | {line}")
        if len(lines) > max_lines:
            print(f"    | ... ({len(lines) - max_lines} more lines)")
        print()


def _log_review(label: str, review, log_fh=None) -> None:
    n_err = sum(1 for i in review.issues if i.severity == "ERROR")
    n_warn = sum(1 for i in review.issues if i.severity == "WARNING")
    n_info = sum(1 for i in review.issues if i.severity == "INFO")
    _log(f"    [{label}] verdict={review.verdict}  "
         f"issues: {n_err} ERROR / {n_warn} WARNING / {n_info} INFO", log_fh)
    for issue in review.issues:
        _log(f"      [{issue.severity}] {issue.description}", log_fh)
    if log_fh:
        log_fh.write(f"\n--- {label} (full render) ---\n{review.render()}\n")
        log_fh.flush()


def _usage_snapshot(judge) -> tuple[int, int, int]:
    u = judge.usage
    return (u.input_tokens, u.cached_tokens, u.output_tokens)


def _log_usage_delta(label: str, judge, before: tuple[int, int, int], log_fh=None) -> None:
    """Print this call's token usage (input / cached / generated) — cached is
    the portion of input served from the provider's prompt cache, a subset of
    input, not additional to it."""
    u = judge.usage
    d_in = u.input_tokens - before[0]
    d_cached = u.cached_tokens - before[1]
    d_out = u.output_tokens - before[2]
    pct = f"{100*d_cached/d_in:.0f}%" if d_in else "—"
    _log(f"    [{label}] tokens: in={d_in} cached={d_cached} ({pct}) generated={d_out}", log_fh)


def _log_usage_breakdown(label: str, client, log_fh=None) -> None:
    """Print token usage split by purpose (review/fix/tweak/numeric-check),
    not just the aggregate — a single client instance handles more than one
    prompt "family" with very different caching behavior (e.g. the judge
    client's review() calls share a large, cacheable system prompt; its
    fix() calls use a different, unrelated one), so a combined-only number
    dilutes the real per-purpose cache hit rate. See
    ReviewJudgeClient.usage_by_purpose."""
    if not client.usage.calls:
        return
    _log(f"  {label} (by purpose):", log_fh)
    for purpose, u in sorted(client.usage_by_purpose.items()):
        pct = f"{100*u.cache_hit_rate:.1f}%" if u.input_tokens else "—"
        _log(f"    {purpose:<16} {u.calls:>3} calls  in={u.input_tokens:>9}  "
             f"(cached: {u.cached_tokens:>8}, {pct:>6})  out={u.output_tokens:>7}", log_fh)
    u = client.usage
    pct = f"{100*u.cache_hit_rate:.1f}%" if u.input_tokens else "—"
    _log(f"    {'TOTAL':<16} {u.calls:>3} calls  in={u.input_tokens:>9}  "
         f"(cached: {u.cached_tokens:>8}, {pct:>6})  out={u.output_tokens:>7}  total={u.total_tokens}", log_fh)


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> None:
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        sys.exit(f"ERROR: config not found: {config_path}")
    cfg = _deep_merge(DEFAULT_CONFIG, load_config(config_path))

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"ERROR: input file not found: {input_path}")

    if args.dry_run:
        _dry_run(cfg, input_path)
        return

    # ── Per-run log file — always full detail, regardless of --verbose ─────
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"mut_validate_{input_path.stem}_{run_stamp}.log"
    log_fh = open(log_path, "w", encoding="utf-8")
    log_fh.write(
        f"mut-validate run log\n"
        f"started: {run_stamp}\n"
        f"input: {input_path}\n"
        f"config: {config_path}\n"
        f"index: {args.index}  limit: {args.limit}  attempts: {args.attempts}  "
        f"tweak: {args.tweak}  tweak_random: {args.tweak_random}\n"
        f"judge: {cfg['judge'].get('provider')} / {cfg['judge'].get('model')}\n"
        + (f"tweak_llm: {cfg['tweak_llm'].get('provider')} / {cfg['tweak_llm'].get('model')}\n" if args.tweak else "")
        + f"MUT checkpoint: {cfg['model'].get('checkpoint_dir')}\n\n"
    )
    log_fh.flush()
    print(f"[mut-validate] Full run log: {log_path}")

    try:
        _cmd_run_inner(args, cfg, input_path, log_fh)
    finally:
        log_fh.close()


def _cmd_run_inner(args: argparse.Namespace, cfg: dict, input_path: Path, log_fh) -> None:
    from dpo_forge.loader import load_examples
    from dpo_forge.generator import LocalGenerator, normalize_ctl
    from dpo_forge.review_judge import (
        ReviewJudgeClient, describe_component_resolution, infer_component_type_from_prompt,
        pick_business_domain,
    )
    from dpo_forge.ctl_validate_mcp import validate_ctl
    from dpo_forge.output import write_conversation_jsonl

    # ── Load + filter examples ──────────────────────────────────────────
    examples = load_examples(sft_files=[str(input_path)], shuffle=False)
    if not examples:
        sys.exit("No examples found in the input file.")

    filtered = [e for e in examples if _is_codegen_with_metadata(e)]
    _log(f"[mut-validate] Loaded {len(examples)} example(s); "
         f"{len(filtered)} match the metadata+codegen filter "
         f"({len(examples) - len(filtered)} skipped)", log_fh)
    if not filtered:
        sys.exit("No examples matched the metadata+codegen filter.")

    start_index = args.index or 0
    if start_index:
        if start_index >= len(filtered):
            sys.exit(f"ERROR: --index {start_index} is out of range "
                      f"(only {len(filtered)} filtered examples)")
        filtered = filtered[start_index:]
        _log(f"[mut-validate] Skipping first {start_index} filtered example(s) (--index {start_index})", log_fh)

    if args.limit is not None:
        filtered = filtered[:args.limit]
    _log(f"[mut-validate] Processing {len(filtered)} example(s)"
         + (f" (from index {start_index})" if start_index else "")
         + (f", limit {args.limit}" if args.limit is not None else ""), log_fh)
    # Business-domain-hint randomness source for --tweak, per the module
    # comment above review_judge.pick_business_domain():
    #   --tweak alone        -> deterministic per example (seeded from the
    #                            example's own id) -> reproducible re-runs,
    #                            still varied across examples in one run.
    #   --tweak --tweak-random -> one shared, unseeded (OS-entropy-seeded)
    #                            rng -> different domains on every run.
    shared_domain_rng = random.Random() if args.tweak_random else None

    def _domain_rng_for(example) -> random.Random:
        return shared_domain_rng if shared_domain_rng is not None else random.Random(example.id)

    if args.tweak:
        tweak_cfg = cfg["tweak_llm"]
        _log(f"[mut-validate] --tweak enabled: each prompt is rewritten by "
             f"{tweak_cfg.get('provider')}/{tweak_cfg.get('model')} "
             f"(new domain/fields/logic, same component type) before use "
             f"— business domain is {'freshly randomized each run (--tweak-random)' if args.tweak_random else 'deterministic per example (stable across re-runs)'}",
             log_fh)

    # ── Init clients ─────────────────────────────────────────────────────
    model_cfg = cfg["model"]
    if not model_cfg.get("checkpoint_dir"):
        sys.exit("ERROR: model.checkpoint_dir must be set.")

    generator = LocalGenerator(model_cfg)
    generator.warm_up()

    judge = ReviewJudgeClient(cfg["judge"], log_file=log_fh)
    # Reused for two purposes: (1) --tweak prompt rewriting, and (2) fact-
    # checking any judge ISSUE that mentions a numeric type, always on
    # regardless of --tweak — see review_judge.check_numeric_claim().
    tweak_llm_client = ReviewJudgeClient(cfg["tweak_llm"], log_file=log_fh)
    tweak_client = tweak_llm_client if args.tweak else None
    numeric_verifier = tweak_llm_client

    ctl_validate_cfg = cfg.get("ctl_validate_mcp") or {}
    if ctl_validate_cfg.get("enabled"):
        _log(f"[mut-validate] ctl_validate MCP pre-filter enabled: {ctl_validate_cfg.get('url')} "
             f"(ERROR-severity results skip the LLM judge for that attempt)", log_fh)

    gen_cfg = model_cfg.get("generation") or {}
    temperature = gen_cfg.get("temperature", 0.3)
    top_p = gen_cfg.get("top_p", 1.0)
    top_k = gen_cfg.get("top_k", 50)
    repetition_penalty = gen_cfg.get("repetition_penalty", 1.0)
    max_new_tokens = gen_cfg.get("max_new_tokens", 2048)
    seed = gen_cfg.get("seed")
    mut_system_prompt: Optional[str] = model_cfg.get("system_prompt")
    if mut_system_prompt:
        mut_system_prompt = mut_system_prompt.strip()

    self_corrected_path = Path(cfg["output"]["self_corrected_file"])
    judge_corrected_path = Path(cfg["output"]["judge_corrected_file"])

    if args.overwrite:
        for path in (self_corrected_path, judge_corrected_path):
            if path.exists():
                path.unlink()
                _log(f"[mut-validate] --overwrite: removed existing {path}", log_fh)

    n_first_pass = 0
    n_self_corrected = 0
    n_self_corrected_by_attempt: dict[int, int] = {}
    n_judge_fixed = 0
    n_judge_fix_failed = 0
    n_ctl_validate_fail = 0
    n_unparseable = 0
    n_missing_component = 0
    t_start = time.monotonic()

    # ── Main loop ─────────────────────────────────────────────────────────
    for i, example in enumerate(filtered):
        n = len(filtered)
        _log(f"\n[{i+1}/{n}] example {example.id}  ({example.source_file}#{example.source_index})", log_fh)

        system = mut_system_prompt if mut_system_prompt is not None else example.system

        # The dataset's own "inferred_component" label is not trusted — it's
        # been found flatly wrong (e.g. Denormalizer tasks mislabeled as
        # Normalizer). Classify from what the prompt itself actually asks for.
        component_type = infer_component_type_from_prompt(example.prompt)
        if not component_type:
            n_missing_component += 1
            _log(f"  [component] WARNING: prompt doesn't clearly name a component type — "
                 f"flagging for manual labeling. {_source_identity(example)}", log_fh)

        prompt = example.prompt
        if args.tweak:
            business_domain = pick_business_domain(_domain_rng_for(example))
            _log(f"  [tweak] business domain: {business_domain.replace(chr(10), ' / ')}", log_fh)
            print("  [tweak] rewriting prompt (new domain/fields/logic, same component) …")
            try:
                tweaked_prompt = tweak_client.tweak(example.prompt, component_type, business_domain=business_domain)
            except Exception as e:
                # A silent fallback to the untweaked prompt would defeat the
                # purpose of --tweak (testing on genuinely novel prompts) and
                # produce examples mislabeled as "tweaked" that are actually
                # verbatim originals, without any indication in the output.
                # Stop the whole run instead of masking the failure.
                _log(f"  [tweak] FATAL: tweak LLM call failed for {_source_identity(example)}: {e}", log_fh)
                raise SystemExit(
                    f"[mut-validate] FATAL: --tweak LLM call failed ({e}) -- stopping run "
                    f"rather than silently falling back to the untweaked prompt. See run log for details."
                )
            _log_full_body("original prompt (pre-tweak)", example.prompt, log_fh, console=args.verbose)
            _log_full_body("tweaked prompt", tweaked_prompt, log_fh, console=args.verbose)
            tweaked_component_type = infer_component_type_from_prompt(tweaked_prompt)
            if component_type and tweaked_component_type and tweaked_component_type != component_type:
                _log(f"  [tweak] WARNING: component type drifted after tweak "
                     f"({component_type!r} -> {tweaked_component_type!r}). {_source_identity(example)}", log_fh)
            component_type = tweaked_component_type or component_type
            prompt = tweaked_prompt

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        _log_full_body("prompt", prompt, log_fh, console=args.verbose)

        # ── Attempt loop: MUT generates, judge reviews, feedback appended on
        # failure, up to args.attempts tries. Attempt 1 requires PASS with no
        # WARNING to count as "correct first try"; later attempts only
        # require PASS (self-correction via feedback need not be pristine).
        # `messages` accumulates the full conversation across attempts, so a
        # self-corrected write on attempt k naturally includes every prior
        # failed attempt + feedback round — a direct generalization of the
        # old fixed 2-attempt shape (which is exactly what this produces
        # when args.attempts == 2, the previous hardcoded behavior).
        prior_review = None
        last_mut_text = last_code = last_review = None
        outcome = None  # "first_pass" | "self_corrected" | "exhausted" | "skip"

        for attempt in range(1, args.attempts + 1):
            print(f"  [MUT] generating (attempt {attempt}/{args.attempts}) …")
            mut_text = generator.generate_reply(
                messages, temperature=temperature, top_p=top_p, top_k=top_k,
                repetition_penalty=repetition_penalty, max_new_tokens=max_new_tokens, seed=seed,
            )
            code = normalize_ctl(mut_text)
            _log_full_body(f"MUT response (attempt {attempt})", mut_text, log_fh, console=args.verbose)

            if attempt == 1:
                # Log which component-type bucket this example actually
                # resolves to — the dataset's own label and the code-inferred
                # one can disagree.
                resolution = describe_component_resolution(component_type, code)
                _log(f"  component: {resolution}", log_fh)

            print(f"  [judge] reviewing attempt {attempt} …")

            # Fast, deterministic compile/metadata pre-filter (optional —
            # see ctl_validate_mcp.py). A real compile error found here
            # becomes the review directly; the LLM judge is skipped for
            # this attempt entirely, since a compile error needs no
            # semantic opinion. Falls through to the LLM judge on PASS,
            # or whenever this step can't run (disabled, no metadata XML
            # in the prompt, MCP call failed, etc.).
            _log(
                f"  [ctl-validate] calling ctl_validate on attempt {attempt} "
                f"with component_type={component_type!r}",
                log_fh,
            )
            mcp_review = validate_ctl(ctl_validate_cfg, component_type, prompt, code,
                                       log_fn=lambda msg: _log(msg, log_fh))
            if mcp_review is not None:
                _log_review(f"ctl-validate-{attempt}", mcp_review, log_fh)

            if mcp_review is not None and mcp_review.verdict == "FAIL":
                n_ctl_validate_fail += 1
                _log(f"  [{example.id}] -> ctl_validate FAIL on attempt {attempt} "
                     f"(compile/metadata error) — skipping LLM judge for this attempt", log_fh)
                review = mcp_review
            else:
                usage_before = _usage_snapshot(judge)
                try:
                    review = judge.review(
                        prompt, code, component_type,
                        prior_issues=(prior_review.issues if prior_review else None),
                        numeric_verifier=numeric_verifier,
                    )
                except Exception as e:
                    _log(f"  [{example.id}] -> SKIPPED (judge review attempt {attempt} raised: {e})", log_fh)
                    n_unparseable += 1
                    outcome = "skip"
                    break
                _log_usage_delta(f"review-{attempt}", judge, usage_before, log_fh)
                if review is None:
                    _log(f"  [{example.id}] -> SKIPPED (judge review unparseable on attempt {attempt})", log_fh)
                    n_unparseable += 1
                    outcome = "skip"
                    break
                _log_review(f"review-{attempt}", review, log_fh)

            messages.append({"role": "assistant", "content": mut_text})
            last_mut_text, last_code, last_review = mut_text, code, review

            is_pass = review.verdict == "PASS" and (attempt > 1 or not review.has_warning)
            if is_pass:
                if attempt == 1:
                    _log(f"  [{example.id}] -> CORRECT on 1st MUT pass", log_fh)
                    n_first_pass += 1
                    outcome = "first_pass"
                else:
                    _log(f"  [{example.id}] -> CORRECT on {_ordinal(attempt)} attempt (MUT self-corrected)", log_fh)
                    n_self_corrected += 1
                    n_self_corrected_by_attempt[attempt] = n_self_corrected_by_attempt.get(attempt, 0) + 1
                    outcome = "self_corrected"
                break

            _log(f"  [{example.id}] -> attempt {attempt} {review.verdict} "
                 f"({'warnings present' if review.has_warning else 'errors present'})"
                 + (" -> retrying MUT" if attempt < args.attempts else ""), log_fh)
            if attempt < args.attempts:
                feedback = review.render() + "\n\nPlease fix the issues above and provide the corrected code."
                messages.append({"role": "user", "content": feedback})
            prior_review = review
        else:
            # for/else: fires only when the loop ran to completion without
            # ever hitting a `break` — i.e. every attempt failed review,
            # including the last one (which has no feedback round after it).
            outcome = "exhausted"

        if outcome == "skip" or outcome == "first_pass":
            continue

        extra = {
            "example_id": example.id,
            "source_file": example.source_file,
            "source_index": example.source_index,
            "component_type": component_type,
        }
        if args.tweak:
            extra["tweaked"] = True
            extra["original_prompt"] = example.prompt
            extra["business_domain"] = business_domain

        if outcome == "self_corrected":
            extra["attempts_used"] = attempt
            conversation = [m for m in messages if m is not None]
            write_conversation_jsonl(conversation, self_corrected_path, extra)
        else:
            _log(f"  [{example.id}] -> MUT FAILED to self-correct after {args.attempts} attempt(s) "
                 f"(review-{args.attempts} FAIL) -> judge fixes the code", log_fh)
            usage_before = _usage_snapshot(judge)
            try:
                fixed_code = judge.fix(prompt, last_code, last_review, component_type)
            except Exception as e:
                _log(f"  [{example.id}] -> SKIPPED (judge fix raised: {e})", log_fh)
                n_unparseable += 1
                continue
            _log_usage_delta("fix", judge, usage_before, log_fh)

            # The judge's own fix can still be uncompilable CTL2 — verify it
            # with the same ctl_validate pre-filter used on MUT attempts. On
            # a real compile/metadata FAIL, feed that error straight back to
            # the judge via fix() again (it already accepts any ReviewResult,
            # so a ctl_validate result works exactly like an LLM review) and
            # ask for a correction. Up to MAX_JUDGE_FIX_ROUNDS such
            # correction rounds; if it still fails after that, give up on
            # this example rather than write uncompilable CTL2 to the SFT
            # output.
            MAX_JUDGE_FIX_ROUNDS = 2
            judge_fix_failed = False
            for fix_round in range(1, MAX_JUDGE_FIX_ROUNDS + 2):
                fix_code = normalize_ctl(fixed_code)
                _log(
                    f"  [ctl-validate] calling ctl_validate for judge-fix round {fix_round} "
                    f"with component_type={component_type!r}",
                    log_fh,
                )
                fix_review = validate_ctl(ctl_validate_cfg, component_type, prompt, fix_code,
                                           log_fn=lambda msg: _log(msg, log_fh))
                if fix_review is not None:
                    _log_review(f"ctl-validate-fix-{fix_round}", fix_review, log_fh)
                if fix_review is None or fix_review.verdict != "FAIL":
                    break
                n_ctl_validate_fail += 1
                if fix_round > MAX_JUDGE_FIX_ROUNDS:
                    _log(f"  [{example.id}] -> SKIPPED (judge fix still fails ctl_validate "
                         f"after {MAX_JUDGE_FIX_ROUNDS} correction round(s))", log_fh)
                    judge_fix_failed = True
                    break
                _log(f"  [{example.id}] -> judge fix failed ctl_validate (round {fix_round}) "
                     f"-- sending error back to judge for correction", log_fh)
                usage_before = _usage_snapshot(judge)
                try:
                    fixed_code = judge.fix(prompt, fix_code, fix_review, component_type)
                except Exception as e:
                    _log(f"  [{example.id}] -> SKIPPED (judge fix correction round {fix_round} raised: {e})", log_fh)
                    judge_fix_failed = True
                    break
                _log_usage_delta(f"fix-retry-{fix_round}", judge, usage_before, log_fh)

            if judge_fix_failed:
                n_judge_fix_failed += 1
                continue

            n_judge_fixed += 1
            extra["attempts_used"] = args.attempts
            conversation = [
                {"role": "system", "content": system} if system else None,
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": last_mut_text},
                {"role": "user", "content": last_review.render() + "\n\nPlease fix the issues above and provide the corrected code."},
                {"role": "assistant", "content": fixed_code},
            ]
            conversation = [m for m in conversation if m is not None]
            write_conversation_jsonl(conversation, judge_corrected_path, extra)

    # ── Summary ──────────────────────────────────────────────────────────
    total = len(filtered)
    wall_clock = time.monotonic() - t_start
    _log("\n" + "=" * 60, log_fh)
    _log("mut-validate — Run Report", log_fh)
    _log("=" * 60, log_fh)
    _log(f"  Examples processed:        {total}", log_fh)
    if total:
        _log(f"  Correct on 1st MUT pass:   {n_first_pass}  ({100*n_first_pass/total:.1f}%)", log_fh)
        self_corrected_label = "Self-corrected (no retry: --attempts=1)" if args.attempts < 2 \
            else f"Self-corrected (attempts 2-{args.attempts})"
        _log(f"  {self_corrected_label}: {n_self_corrected}  "
             f"({100*n_self_corrected/total:.1f}%)  -> {self_corrected_path}", log_fh)
        if args.attempts > 2 and n_self_corrected_by_attempt:
            breakdown = ", ".join(
                f"attempt {k}: {v}" for k, v in sorted(n_self_corrected_by_attempt.items())
            )
            _log(f"    ({breakdown})", log_fh)
        _log(f"  MUT failed (judge fixed):  {n_judge_fixed}  ({100*n_judge_fixed/total:.1f}%)  -> {judge_corrected_path}", log_fh)
        if ctl_validate_cfg.get("enabled"):
            _log(f"  ctl_validate FAILs (syntax/metadata errors): {n_ctl_validate_fail}  "
                 f"(across all MUT attempts + judge-fix rounds)", log_fh)
        if n_judge_fix_failed:
            _log(f"  Skipped (judge fix still failed ctl_validate): {n_judge_fix_failed}", log_fh)
        if n_unparseable:
            _log(f"  Skipped (unparseable):     {n_unparseable}", log_fh)
        if n_missing_component:
            _log(f"  Missing component type:    {n_missing_component}  (see [component] WARNING lines above/in log for source identification)", log_fh)
    # Split by purpose rather than one mixed aggregate — review() and fix()
    # (or tweak() and check_numeric_claim()) share a client instance but use
    # unrelated system prompts with very different caching behavior; a single
    # combined cache-hit % hides which prompt family actually caches. See
    # _log_usage_breakdown / ReviewJudgeClient.usage_by_purpose.
    _log_usage_breakdown("Judge", judge, log_fh)
    _log_usage_breakdown("Tweak/numeric-check LLM", tweak_llm_client, log_fh)
    _log(f"  Wall clock:                {wall_clock:.1f}s", log_fh)
    _log("=" * 60, log_fh)


def _dry_run(cfg: dict, input_path: Path) -> None:
    print("[dry-run] Effective config:")
    print(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
    print(f"[dry-run] Input file: {input_path}")
    ckpt = cfg["model"].get("checkpoint_dir")
    print(f"[dry-run] Checkpoint: {ckpt}")
    print(f"[dry-run] Judge: {cfg['judge']['provider']} / {cfg['judge']['model']}")
    print(f"[dry-run] Self-corrected output: {cfg['output']['self_corrected_file']}")
    print(f"[dry-run] Judge-corrected output: {cfg['output']['judge_corrected_file']}")

    from dpo_forge.loader import load_examples
    examples = load_examples(sft_files=[str(input_path)], shuffle=False)
    filtered = [e for e in examples if _is_codegen_with_metadata(e)]
    print(f"[dry-run] {len(examples)} example(s) loaded, "
          f"{len(filtered)} match the metadata+codegen filter")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mut_validate",
        description="MUT self-correction / judge-fix SFT generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  ./mut_validate.py data/sft_input/ctl2_sft_component_generation_with_metadata_100.json
  ./mut_validate.py data/sft_input/foo.json --config configs/mut_validate.yaml --limit 20
  ./mut_validate.py data/sft_input/foo.json --index 20 --limit 20 --verbose
  ./mut_validate.py data/sft_input/foo.json --tweak --limit 20
  ./mut_validate.py data/sft_input/foo.json --tweak --tweak-random --limit 20
  ./mut_validate.py data/sft_input/foo.json --attempts 4 --limit 20

(runs on GPU 1 by default; uses /home/pavlisd/venv via the shebang)
""",
    )
    parser.add_argument("input", help="Path to the SFT input file (JSON or JSONL)")
    parser.add_argument("--config", "-c", default="configs/mut_validate.yaml", metavar="YAML",
                        help="Path to mut_validate.yaml config file (default: configs/mut_validate.yaml)")
    parser.add_argument("--index", type=int, default=0, metavar="N",
                        help="Skip the first N filtered examples (0-based start index)")
    parser.add_argument("--limit", "-n", type=int, default=None, metavar="N",
                        help="Process at most N filtered examples (default: all)")
    parser.add_argument("--attempts", type=int, default=2, metavar="N",
                        help="Max MUT generate+review attempts per example before the judge fixes the code "
                             "directly (default: 2, the original fixed pass-1/pass-2 behavior). Attempt 1 must "
                             "PASS with no WARNING to count as correct-first-try; later attempts only need PASS. "
                             "--attempts 1 disables the feedback retry entirely.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show MUT prompts/responses for each example")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print effective config and filter counts, then exit")
    parser.add_argument("--overwrite", action="store_true",
                        help="Delete existing output files before running, instead of appending to them")
    parser.add_argument("--tweak", action="store_true",
                        help="Have the judge LLM rewrite each prompt (new domain, field names/types, "
                             "and a genuinely different business rule, same component type) before "
                             "sending it to the MUT — avoids testing on prompts the MUT was trained on verbatim. "
                             "The business domain/process/region is picked deterministically per example "
                             "(stable across re-runs of the same input file) unless --tweak-random is also given.")
    parser.add_argument("--tweak-random", action="store_true",
                        help="Modifier for --tweak (implies it): pick each example's business domain/process/"
                             "region from a freshly-seeded random source instead of a per-example-deterministic "
                             "one, so repeated runs land on different domains instead of the same ones every time")

    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be >= 1")
    if args.tweak_random:
        args.tweak = True  # --tweak-random is a modifier of --tweak, not a separate feature
    cmd_run(args)


if __name__ == "__main__":
    main()
