#!/usr/bin/env python3
"""
chat.py — Interactive chat with a CTL2 fine-tuned model

Loads an exported safetensors model and starts a multi-turn conversation
in the terminal.  Conversation history is kept for the full session so
the model has context across turns.

Usage:
  python chat.py configs/chat_config.yaml
  python chat.py configs/chat_config.yaml --model /home/pavlisd/exports/qwen35-9B-CTLv11
  python chat.py configs/chat_config.yaml --temperature 0.7 --top-p 0.95
  python chat.py configs/chat_config.yaml --logfile session.log

Commands during chat:
  /reset    — clear conversation history (start fresh)
  /history  — show the conversation so far
  /quit     — exit  (also: /exit, Ctrl-D, Ctrl-C)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Optional rich display
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule

    _HAVE_RICH = True
    _console = Console()
except ImportError:
    _HAVE_RICH = False
    _console = None  # type: ignore


def _print(msg: str = "", **kwargs):
    if _HAVE_RICH:
        _console.print(msg, **kwargs)
    else:
        plain = re.sub(r"\[/?[^\]]+\]", "", msg)
        print(plain, **kwargs)


def _rule(title: str = ""):
    if _HAVE_RICH:
        _console.print(Rule(title))
    else:
        w = 72
        if title:
            pad = (w - len(title) - 2) // 2
            print("─" * pad + f" {title} " + "─" * pad)
        else:
            print("─" * w)


# ---------------------------------------------------------------------------
# Config loading (reuses env-var expansion from test.py pattern)
# ---------------------------------------------------------------------------

_ENV_RE = re.compile(r"\$\{([^}]+)\}")

DEFAULT_CONFIG: dict = {
    # Link to training config for export auto-discovery (same as eval_config.yaml)
    "training_config": "configs/qwen35-9B.yaml",

    "model": {
        # "local"  — load safetensors from disk via transformers (GPU required)
        # "api"    — call an OpenAI-compatible endpoint
        "mode": "local",

        # Path to the exported model directory.
        # Leave null to auto-discover latest from training_config.
        "model_path": None,

        # Data type: float16 | bfloat16 | float32
        "dtype": "bfloat16",

        # HuggingFace device map
        "device_map": "auto",

        # Maximum tokens per response
        "max_new_tokens": 2048,

        # Set false for models trained with a nothink template (recommended)
        "enable_thinking": False,

        # --- api mode ---
        "base_url": "http://localhost:11434/v1",
        "api_model": None,
        "api_key": "ollama",
    },

    # Generation settings
    "temperature": 0.7,
    "top_p": 0.95,

    # System message shown to the model at the start of every conversation
    "system_prompt": (
        "You are a CloverDX ETL expert specializing in transformation graphs, "
        "components, and CTL2. CTL and CTL2 mean the same language.\n"
        "Help users write, debug, and explain CTL2 code and related concepts. "
        "Provide working code, explanation, or both as needed.\n"
        "Prefer correct, practical, minimal solutions."
    ),

    # Optional: override the chat template (Jinja2 string).
    # Leave null to use the tokenizer's built-in template.
    "chat_template": None,

    # If set, log the full session to this file.
    "logfile": None,
}


def _expand_env(v: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), v)


def _expand_recursive(obj):
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
    merged = _deep_merge(DEFAULT_CONFIG, raw)
    return _expand_recursive(merged)


# ---------------------------------------------------------------------------
# Export auto-discovery  (same logic as test.py)
# ---------------------------------------------------------------------------

def _find_latest_export(output_base: str, run_name: str) -> Optional[str]:
    run_dir = Path(output_base) / run_name
    if not run_dir.is_dir():
        return None
    candidates = sorted(
        [d for d in run_dir.iterdir() if d.is_dir() and d.name.endswith("_export")],
        key=lambda d: d.name,
    )
    for d in reversed(candidates):
        if any(d.glob("*.safetensors")):
            return str(d)
    return None


def resolve_model_path(cfg: dict, config_dir: Path) -> str:
    """Resolve the model path: explicit cfg > training_config export_dir > latest export."""
    model_cfg = cfg.get("model", {})
    model_path = model_cfg.get("model_path")

    if model_path:
        return model_path

    # Try to auto-discover from linked training config
    tc_ref = cfg.get("training_config")
    tc: dict = {}
    if tc_ref:
        tc_path = Path(tc_ref)
        if not tc_path.is_absolute():
            for base in [Path.cwd(), Path(__file__).parent, config_dir]:
                candidate = (base / tc_path).resolve()
                if candidate.exists():
                    tc_path = candidate
                    break
        if tc_path.exists():
            with open(tc_path) as f:
                tc = _expand_recursive(yaml.safe_load(f) or {})
        else:
            _print(f"[yellow]Warning: training_config not found: {tc_path}[/yellow]")

    if tc:
        # Check explicit export_dir override first
        override = tc.get("export", {}).get("export_dir")
        if override:
            p = Path(override).expanduser().resolve()
            if p.is_dir() and any(p.glob("*.safetensors")):
                _print(f"  [cyan]Auto-discovered export:[/cyan] {p}")
                return str(p)

        # Fall back to scanning output_base/run_name/*_export dirs
        llamafactory_dir = Path(
            os.environ.get("LLAMAFACTORY_DIR", "~/LlamaFactory")
        ).expanduser().resolve()
        output_base = tc.get("output_base", "saves")
        abs_output_base = (llamafactory_dir / output_base).resolve()
        run_name = tc.get("run_name", "run")
        discovered = _find_latest_export(str(abs_output_base), run_name)
        if discovered:
            _print(f"  [cyan]Auto-discovered export:[/cyan] {discovered}")
            return discovered

    _print(
        "[red]ERROR:[/red] Could not locate a model export.\n"
        "  Set model.model_path in chat_config.yaml, or use --model on the command line."
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Model wrapper
# ---------------------------------------------------------------------------

# Plain ChatML template — no thinking tokens (same as test.py)
_CHATML_NOTHINK_TEMPLATE = (
    "{% for message in messages %}"
    "{% if message['role'] == 'system' %}"
    "<|im_start|>system\n{{ message['content'] }}<|im_end|>\n"
    "{% elif message['role'] == 'user' %}"
    "<|im_start|>user\n{{ message['content'] }}<|im_end|>\n"
    "<|im_start|>assistant\n"
    "{% elif message['role'] == 'assistant' %}"
    "{{ message['content'] }}<|im_end|>\n"
    "{% endif %}"
    "{% endfor %}"
)


def _patch_tokenizer_nothink(tok):
    try:
        tok.apply_chat_template(
            [{"role": "user", "content": "hi"}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        _orig = tok.apply_chat_template

        def _nothink_apply(*args, **kwargs):
            kwargs.setdefault("enable_thinking", False)
            return _orig(*args, **kwargs)

        tok.apply_chat_template = _nothink_apply
        _print("  [dim]Chat template: nothink via enable_thinking=False[/dim]")
    except TypeError:
        tok.chat_template = _CHATML_NOTHINK_TEMPLATE
        _print("  [dim]Chat template: nothink via ChatML template override[/dim]")
    return tok


class LocalModel:
    def __init__(self, model_path: str, cfg: dict):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype_map = {
            "float16":  torch.float16,
            "bfloat16": torch.bfloat16,
            "float32":  torch.float32,
        }
        dtype_key = cfg.get("dtype") or cfg.get("torch_dtype", "bfloat16")
        dtype = dtype_map.get(dtype_key, torch.bfloat16)

        _print(f"\n  Loading model from [cyan]{model_path}[/cyan] …")
        tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        # Apply custom chat template if provided in config
        custom_template = cfg.get("chat_template")
        if custom_template:
            tok.chat_template = custom_template
            _print("  [dim]Chat template: custom template from config[/dim]")
        elif not cfg.get("enable_thinking", False):
            tok = _patch_tokenizer_nothink(tok)

        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=dtype,
            device_map=cfg.get("device_map", "auto"),
            trust_remote_code=True,
        )
        model.eval()

        self._tok = tok
        self._model = model
        self._max_new_tokens = cfg.get("max_new_tokens", 2048)
        _print(f"  Model loaded.  [dim](thinking={'enabled' if cfg.get('enable_thinking') else 'disabled'})[/dim]\n")

    def generate(self, messages: list[dict], temperature: float, top_p: float) -> str:
        import torch

        tokenized = self._tok.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt",
        )
        if hasattr(tokenized, "input_ids"):
            input_ids = tokenized.input_ids.to(self._model.device)
        else:
            input_ids = tokenized.to(self._model.device)

        do_sample = temperature > 0.0
        with torch.inference_mode():
            output = self._model.generate(
                input_ids,
                max_new_tokens=self._max_new_tokens,
                temperature=temperature if do_sample else 1.0,
                top_p=top_p if do_sample else 1.0,
                do_sample=do_sample,
                pad_token_id=self._tok.eos_token_id,
            )
        return self._tok.decode(output[0][input_ids.shape[1]:], skip_special_tokens=True)


class APIModel:
    def __init__(self, cfg: dict):
        from openai import OpenAI

        self._client = OpenAI(
            base_url=cfg.get("base_url", "http://localhost:11434/v1"),
            api_key=cfg.get("api_key", "ollama"),
        )
        self._model_name = cfg.get("api_model") or ""
        _print(f"  API model: [cyan]{self._model_name}[/cyan] at {cfg.get('base_url')}\n")

    def generate(self, messages: list[dict], temperature: float, top_p: float) -> str:
        resp = self._client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Session logger
# ---------------------------------------------------------------------------

class SessionLogger:
    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self._path, "w", encoding="utf-8")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._f.write(f"# Chat session — {ts}\n\n")
        self._f.flush()

    def log(self, role: str, content: str):
        label = {"user": "USER", "assistant": "ASSISTANT", "system": "SYSTEM"}.get(role, role.upper())
        self._f.write(f"## {label}\n\n{content}\n\n")
        self._f.write("---\n\n")
        self._f.flush()

    def note(self, text: str):
        self._f.write(f"_{text}_\n\n")
        self._f.flush()

    def close(self):
        self._f.close()


# ---------------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------------

def run_chat(model, system_prompt: str, temperature: float, top_p: float,
             logger: Optional[SessionLogger]):

    history: list[dict] = []

    if logger:
        logger.log("system", system_prompt)

    _rule("CTL2 Chat")
    _print(
        f"  [dim]Model temp={temperature}  top_p={top_p}  "
        f"system={repr(system_prompt[:60])}{'…' if len(system_prompt) > 60 else ''}[/dim]"
    )
    _print("  [dim]Commands: /reset  /history  /quit[/dim]")
    _rule()
    _print()

    def _messages_with_system():
        return [{"role": "system", "content": system_prompt}] + history

    while True:
        # Read user input (multi-line: blank line or Ctrl-D ends input)
        try:
            if _HAVE_RICH:
                _console.print("[bold green]You>[/bold green] ", end="")
            else:
                print("You> ", end="", flush=True)
            lines = []
            first = True
            while True:
                try:
                    line = input("" if first else "... ")
                    first = False
                    lines.append(line)
                    # Single-line input: submit immediately unless it ends with \
                    if not line.endswith("\\") and len(lines) == 1:
                        break
                    # Multi-line: blank line terminates
                    if not line.strip() and len(lines) > 1:
                        break
                except EOFError:
                    # Ctrl-D while typing → submit what we have
                    break
        except (EOFError, KeyboardInterrupt):
            _print("\n\n[dim]Exiting.[/dim]")
            break

        user_text = "\n".join(lines).rstrip("\\").strip()

        if not user_text:
            continue

        # --- built-in commands ---
        if user_text.lower() in ("/quit", "/exit"):
            _print("[dim]Goodbye.[/dim]")
            break

        if user_text.lower() == "/reset":
            history.clear()
            if logger:
                logger.note("*** conversation reset ***")
            _print("[yellow]Conversation history cleared.[/yellow]\n")
            continue

        if user_text.lower() == "/history":
            if not history:
                _print("[dim]No history yet.[/dim]\n")
            else:
                for turn in history:
                    role_label = "[bold green]You[/bold green]" if turn["role"] == "user" else "[bold blue]Model[/bold blue]"
                    _print(f"{role_label}: {turn['content']}\n")
            continue

        # --- generate response ---
        history.append({"role": "user", "content": user_text})
        if logger:
            logger.log("user", user_text)

        _print("\n[bold blue]Model>[/bold blue]")
        try:
            response = model.generate(_messages_with_system(), temperature, top_p)
        except KeyboardInterrupt:
            _print("\n[yellow](interrupted)[/yellow]")
            history.pop()  # discard the unanswered user turn
            continue
        except Exception as exc:
            _print(f"\n[red]ERROR during generation:[/red] {exc}")
            history.pop()
            continue

        history.append({"role": "assistant", "content": response})
        if logger:
            logger.log("assistant", response)

        if _HAVE_RICH:
            # Render markdown inside a subtle panel
            try:
                _console.print(Panel(Markdown(response), border_style="dim blue", padding=(0, 1)))
            except Exception:
                _console.print(response)
        else:
            # Plain terminal: indent the response
            for line in response.splitlines():
                print("  " + line)

        _print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Interactive chat with a CTL2 fine-tuned model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            During chat:
              /reset    — clear conversation history
              /history  — print conversation so far
              /quit     — exit
        """),
    )
    parser.add_argument("config", nargs="?", default="configs/chat_config.yaml",
                        help="Path to chat_config.yaml (default: configs/chat_config.yaml)")
    parser.add_argument("--model", metavar="PATH",
                        help="Path to exported model directory (overrides config)")
    parser.add_argument("--temperature", type=float, metavar="T",
                        help="Sampling temperature (overrides config)")
    parser.add_argument("--top-p", type=float, dest="top_p", metavar="P",
                        help="Top-p nucleus sampling (overrides config)")
    parser.add_argument("--logfile", metavar="FILE",
                        help="Log the session to this file (overrides config)")
    parser.add_argument("--system", metavar="TEXT",
                        help="Override the system prompt (overrides config)")
    args = parser.parse_args()

    config_path = Path(args.config)
    config_dir  = config_path.parent.resolve()

    if not config_path.exists():
        # Gracefully fall back to defaults if no config file provided
        cfg = _expand_recursive(DEFAULT_CONFIG)
        _print(f"[yellow]No config file found at {config_path} — using defaults.[/yellow]")
    else:
        cfg = load_config(config_path)

    # Command-line overrides
    if args.model:
        cfg["model"]["model_path"] = args.model
    if args.temperature is not None:
        cfg["temperature"] = args.temperature
    if args.top_p is not None:
        cfg["top_p"] = args.top_p
    if args.logfile:
        cfg["logfile"] = args.logfile
    if args.system:
        cfg["system_prompt"] = args.system

    temperature  = float(cfg.get("temperature", 0.7))
    top_p        = float(cfg.get("top_p", 0.95))
    system_prompt = cfg.get("system_prompt", "You are a helpful assistant.")

    # Resolve model path
    model_cfg = cfg.get("model", {})
    model_path = resolve_model_path(cfg, config_dir)
    model_cfg["model_path"] = model_path

    # Load model
    mode = model_cfg.get("mode", "local")
    if mode == "local":
        model = LocalModel(model_path, model_cfg)
    elif mode == "api":
        model = APIModel(model_cfg)
    else:
        _print(f"[red]Unknown model mode:[/red] {mode!r}  (expected 'local' or 'api')")
        sys.exit(1)

    # Set up optional logger
    logger = None
    logfile = cfg.get("logfile")
    if logfile:
        logger = SessionLogger(logfile)
        _print(f"  [dim]Logging session to: {logfile}[/dim]")

    try:
        run_chat(model, system_prompt, temperature, top_p, logger)
    finally:
        if logger:
            logger.close()
            _print(f"[dim]Session saved to {logfile}[/dim]")


if __name__ == "__main__":
    main()
