#!/usr/bin/env python3
"""
test.py — CTL2 fine-tuned model evaluation script

Runs ctl2_test_suite.json against a model under test (MUT), judges each
response with a separate LLM (Anthropic or OpenAI-compatible), writes
structured results + a human-readable summary, and appends an eval entry
to the shared run log (logs/<BaseModel>.yaml) used by train.py.

Architecture:
  resources/ctl2_test_suite.json
      ↓ (system_prompt + user_message + temperature)
  [MUT] — local (transformers, safetensors from export dir) OR api (OpenAI-compatible)
      ↓ (raw response)
  [Judge] — Anthropic OR OpenAI
      ↓ (structured JSON verdict)
  compute_numeric_score + detect_critical_failure
      ↓
  results/<model>_<ts>.json  +  summary/<model>_<ts>.md
  logs/<BaseModel>.yaml        ← shared with train.py

Shared config with train.py:
  Set  training_config: configs/example.yaml  in eval_config.yaml.
  test.py reads output_base / run_name from that file and:
    • Auto-discovers the most recent completed export directory
    • Appends eval scores to the same log file train.py writes

Usage:
  python llama_train/test.py llama_train/configs/eval_config.yaml
  python llama_train/test.py configs/eval_config.yaml --tests T4,T5,T7
  python llama_train/test.py configs/eval_config.yaml --runs 3
  python llama_train/test.py configs/eval_config.yaml --dry-run
  python llama_train/test.py --compare results/a.json results/b.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Optional rich display
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table

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


# ---------------------------------------------------------------------------
# Optional pydantic for judge response validation
# ---------------------------------------------------------------------------
try:
    from pydantic import BaseModel

    class _FindingItem(BaseModel):
        id: str
        status: str  # PRESENT | MISSING | WRONG | CAUGHT | MISSED
        note: str = ""

    class _FPItem(BaseModel):
        id: str
        triggered: bool
        note: str = ""

    class _ForbiddenItem(BaseModel):
        id: str
        present: bool
        note: str = ""

    class JudgeResponse(BaseModel):
        test_id: str
        verdict: str  # PASS | PARTIAL | FAIL | ERROR
        score: str    # "N/M"
        findings: list[_FindingItem] = []
        false_positives_triggered: list[_FPItem] = []
        forbidden_present: list[_ForbiddenItem] = []
        notes: str = ""

    _HAVE_PYDANTIC = True

except ImportError:
    _HAVE_PYDANTIC = False
    JudgeResponse = dict  # type: ignore


# ---------------------------------------------------------------------------
# Constants — resource filenames and directory paths
# ---------------------------------------------------------------------------

_SCRIPT_DIR    = Path(__file__).parent
_RESOURCES_DIR = _SCRIPT_DIR / "resources"
_LOGS_DIR      = _SCRIPT_DIR / "logs"

_SUITE_FILENAME      = "ctl2_test_suite.json"
_CTL2_REF_FILENAME   = "ctl2-basics.md"
_DEFAULT_JUDGE_MODEL = "claude-opus-4-20250514"


# ---------------------------------------------------------------------------
# Config defaults and loading
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    # Path to the training config YAML.  When set, test.py inherits
    # output_base / run_name / model_name_or_path from it and:
    #   • auto-discovers the most recent export directory (if mut.model_path is null)
    #   • appends eval scores to the shared logs/<BaseModel>.yaml run log
    "training_config": None,

    "mut": {
        # "local"  — load safetensors from disk via transformers (GPU required)
        # "api"    — call an OpenAI-compatible endpoint (Ollama, OpenAI, vLLM, etc.)
        "mode": "local",

        # --- local mode ---
        # Absolute or relative path to the exported model directory.
        # Leave null to auto-discover from training_config output paths.
        "model_path": None,
        "torch_dtype": "float16",  # float16 | bfloat16 | float32
        "device_map": "auto",
        "max_new_tokens": 2048,
        # Optional: LlamaFactory template registry name (e.g. qwen3_6).
        # If null, test.py can read training_config.template automatically.
        "chat_template_name": None,
        # Template source strategy:
        # auto        -> if chat_template_name is set, try applying that template;
        #                otherwise use tokenizer built-in template.
        # tokenizer   -> always use tokenizer built-in template.
        # llamafactory -> force applying mut.chat_template_name from
        #                LlamaFactory registry.
        "template_source": "auto",
        # Optional: explicit Jinja template string override.
        # If set, this takes precedence over chat_template_name.
        "chat_template": None,
        # Set false for models trained with a nothink template.
        "enable_thinking": False,

        # --- api mode ---
        "base_url": "http://localhost:11434/v1",
        "model": None,
        "api_key": "ollama",
    },
    "judge": {
        "provider": "anthropic",  # "anthropic" | "openai"
        "model": _DEFAULT_JUDGE_MODEL,
        "api_key": None,
        "base_url": None,
    },
    "runs_per_test": 1,
    "timeout_seconds": 240,
    "output_dir": "./results",
    "test_ids": None,
    "suite_file": None,
}

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
# Export auto-discovery  (mirrors train.py's find_latest_sft_checkpoint logic)
# ---------------------------------------------------------------------------

def find_latest_export(output_base: str, run_name: str) -> Optional[str]:
    """Return path of the most recent completed export directory, or None.

    'Completed' means the directory exists and contains at least one
    .safetensors shard — same check as train.py's is_export_complete().
    Directories are named YYYY-MM-DD-HH-MM-SS_export, which sorts
    lexicographically in chronological order.
    """
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


def resolve_mut_model_path(cfg: dict, config_dir: Path) -> tuple[str, str, str]:
    """Resolve the MUT model path, run_name, and base_model_name.

    Priority for model_path:
      1. mut.model_path explicitly set in eval_config.yaml (non-null)
      2. Auto-discover from training_config paths

    Returns (model_path, run_name, base_model_name).
    run_name and base_model_name are used for log writing.
    """
    mut_cfg = cfg.get("mut", {})
    training_config_ref = cfg.get("training_config")

    # Load training config if referenced
    tc: dict = {}
    if training_config_ref:
        tc_path = Path(training_config_ref)
        if not tc_path.is_absolute():
            # Try: cwd → script directory → config file's directory
            for base in [Path.cwd(), Path(__file__).parent, config_dir]:
                candidate = (base / tc_path).resolve()
                if candidate.exists():
                    tc_path = candidate
                    break
        if tc_path.exists():
            tc = load_config(tc_path)
        else:
            _print(f"[yellow]Warning: training_config not found: {tc_path}[/yellow]")

    run_name = tc.get("run_name", "run")
    base_model = tc.get("model_name_or_path", "unknown")

    model_path = mut_cfg.get("model_path")

    if not model_path and tc:
        # If the training config overrides export_dir with an absolute path,
        # check that directory directly for safetensors before falling back to
        # the standard output_base/run_name/*_export discovery.
        override_export_dir = tc.get("export", {}).get("export_dir")
        if override_export_dir:
            override_path = Path(override_export_dir).expanduser().resolve()
            if override_path.is_dir() and any(override_path.glob("*.safetensors")):
                model_path = str(override_path)
                _print(f"  [cyan]Auto-discovered export (export_dir override):[/cyan] {model_path}")

        if not model_path:
            output_base = tc.get("output_base", "saves")
            # output_base in training config is relative to LLAMAFACTORY_DIR, but
            # train.py resolves it from LLAMAFACTORY_DIR as cwd.  We honour the
            # LLAMAFACTORY_DIR env var the same way.
            llamafactory_dir = Path(
                os.environ.get("LLAMAFACTORY_DIR", "~/LlamaFactory")
            ).expanduser().resolve()
            abs_output_base = (llamafactory_dir / output_base).resolve()

            discovered = find_latest_export(str(abs_output_base), run_name)
            if discovered:
                model_path = discovered
                _print(f"  [cyan]Auto-discovered export:[/cyan] {model_path}")
            else:
                _print(
                    f"[red]ERROR:[/red] no completed export found under "
                    f"{abs_output_base}/{run_name}"
                    + (f" or {override_export_dir}" if override_export_dir else "")
                    + f"\n  Run train.py first, or set mut.model_path explicitly."
                )
                sys.exit(1)

    if not model_path:
        _print(
            "[red]ERROR:[/red] mut.model_path is not set and training_config is not "
            "specified.  Set one of them in your eval config."
        )
        sys.exit(1)

    # Try to read base model from export_config.yaml inside the export dir
    # (written by train.py at export time) — overrides what's in training_config
    export_cfg_path = Path(model_path) / "export_config.yaml"
    if export_cfg_path.exists():
        try:
            with open(export_cfg_path) as f:
                ec = yaml.safe_load(f) or {}
            base_model = ec.get("model_name_or_path", base_model)
        except Exception:
            pass

    return model_path, run_name, base_model


def resolve_training_enable_thinking(cfg: dict, config_dir: Path) -> Optional[bool]:
    """Read enable_thinking from linked training config when available."""
    tc_ref = cfg.get("training_config")
    if not tc_ref:
        return None

    tc_path = Path(tc_ref)
    if not tc_path.is_absolute():
        for base in [Path.cwd(), Path(__file__).parent, config_dir]:
            candidate = (base / tc_path).resolve()
            if candidate.exists():
                tc_path = candidate
                break

    if not tc_path.exists():
        return None

    try:
        tc = load_config(tc_path)
    except Exception:
        return None

    value = tc.get("enable_thinking")
    if value is None:
        return None
    return bool(value)


def resolve_template_name(cfg: dict, config_dir: Path) -> Optional[str]:
    """Resolve chat template name from MUT config or linked training config."""
    mut_cfg = cfg.get("mut", {})
    template_name = mut_cfg.get("chat_template_name")
    if template_name:
        return str(template_name)

    tc_ref = cfg.get("training_config")
    if not tc_ref:
        return None

    tc_path = Path(tc_ref)
    if not tc_path.is_absolute():
        for base in [Path.cwd(), Path(__file__).parent, config_dir]:
            candidate = (base / tc_path).resolve()
            if candidate.exists():
                tc_path = candidate
                break

    if not tc_path.exists():
        return None

    try:
        tc = load_config(tc_path)
    except Exception:
        return None

    name = tc.get("template")
    return str(name) if name else None


# ---------------------------------------------------------------------------
# MUT clients
# ---------------------------------------------------------------------------

# Plain ChatML template — no thinking tokens, mirrors the Ollama nothink template.
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
    """Return the tokenizer with thinking disabled.

    Tries the tokenizer's native enable_thinking=False kwarg first (Qwen3 ≥ some
    release supports this).  Falls back to replacing chat_template with a plain
    ChatML template that contains no <think> scaffolding.
    """
    try:
        # Probe whether the tokenizer accepts enable_thinking
        tok.apply_chat_template(
            [{"role": "user", "content": "hi"}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        # It worked — monkey-patch apply_chat_template to always pass the flag
        _orig = tok.apply_chat_template

        def _nothink_apply(*args, **kwargs):
            kwargs.setdefault("enable_thinking", False)
            return _orig(*args, **kwargs)

        tok.apply_chat_template = _nothink_apply
        _print("  [dim]Chat template: nothink via enable_thinking=False[/dim]")
    except TypeError:
        # Tokenizer does not support enable_thinking — replace the template directly
        tok.chat_template = _CHATML_NOTHINK_TEMPLATE
        _print("  [dim]Chat template: nothink via ChatML template override[/dim]")
    return tok


def _try_apply_llamafactory_template(tok, template_name: str, enable_thinking: bool) -> bool:
    """Apply a LlamaFactory template by name to tokenizer.chat_template."""
    llamafactory_dir = Path(os.environ.get("LLAMAFACTORY_DIR", "~/LlamaFactory")).expanduser().resolve()
    src_dir = llamafactory_dir / "src"

    if not src_dir.is_dir():
        _print(f"  [yellow]Warning:[/yellow] LLAMAFACTORY src not found: {src_dir}")
        return False

    src_dir_str = str(src_dir)
    if src_dir_str not in sys.path:
        sys.path.insert(0, src_dir_str)

    try:
        from llamafactory.data.template import get_template_and_fix_tokenizer

        data_args = SimpleNamespace(
            template=template_name,
            train_on_prompt=False,
            tool_format=None,
            default_system=None,
            enable_thinking=enable_thinking,
            preserve_thinking=False,
        )
        get_template_and_fix_tokenizer(tok, data_args)
        return True
    except Exception as exc:
        _print(
            f"  [yellow]Warning:[/yellow] could not apply template name "
            f"'{template_name}' from LlamaFactory: {exc}"
        )
        return False


class LocalMUTClient:
    """Loads an exported model (safetensors) from disk and runs local inference."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._model = None
        self._tok = None
        self._enable_thinking = bool(cfg.get("enable_thinking", False))

    def _load(self):
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        model_path = self._cfg.get("model_path")
        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        # Support both legacy key name (torch_dtype) and current key (dtype)
        dtype_key = self._cfg.get("dtype") or self._cfg.get("torch_dtype", "float16")
        dtype = dtype_map.get(dtype_key, torch.float16)

        _print(f"  Loading model from [cyan]{model_path}[/cyan] …")
        self._tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        # Apply chat template from config/name, otherwise keep tokenizer default.
        template_name = self._cfg.get("chat_template_name")
        template_source = str(self._cfg.get("template_source", "auto")).lower()
        custom_template = self._cfg.get("chat_template")
        applied = False
        if custom_template:
            self._tok.chat_template = custom_template
            _print("  [dim]Chat template: custom template from config[/dim]")
            applied = True
        elif template_source == "llamafactory":
            if template_name and _try_apply_llamafactory_template(
                self._tok, str(template_name), enable_thinking=self._enable_thinking
            ):
                _print(f"  [dim]Chat template: LlamaFactory template '{template_name}'[/dim]")
                applied = True
            elif template_name:
                _print(
                    f"  [yellow]Warning:[/yellow] could not apply LlamaFactory template "
                    f"'{template_name}', using tokenizer built-in template"
                )
        elif template_source == "auto":
            # If a template name is configured, prefer applying it explicitly.
            if template_name and _try_apply_llamafactory_template(
                self._tok, str(template_name), enable_thinking=self._enable_thinking
            ):
                _print(f"  [dim]Chat template: LlamaFactory template '{template_name}'[/dim]")
                applied = True
            elif self._tok.chat_template:
                _print("  [dim]Chat template: tokenizer built-in template[/dim]")
                applied = True
        elif template_source == "tokenizer":
            _print("  [dim]Chat template: tokenizer built-in template[/dim]")
            applied = True
        else:
            _print(
                f"  [yellow]Warning:[/yellow] unknown template_source={template_source!r}; "
                "falling back to tokenizer built-in template"
            )
            applied = True

        if not applied:
            if not self._enable_thinking:
                self._tok = _patch_tokenizer_nothink(self._tok)
            else:
                _print("  [dim]Chat template: tokenizer built-in template[/dim]")

        self._model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=dtype,
            device_map=self._cfg.get("device_map", "auto"),
            trust_remote_code=True,
        )
        self._model.eval()
        _print(
            f"  Model loaded.  [dim](thinking={'enabled' if self._enable_thinking else 'disabled'})[/dim]"
        )

    def _tokenize_messages(self, messages: list[dict]):
        kwargs = dict(
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        try:
            return self._tok.apply_chat_template(
                messages,
                enable_thinking=self._enable_thinking,
                **kwargs,
            )
        except TypeError:
            # Older tokenizer implementations may not accept enable_thinking.
            return self._tok.apply_chat_template(messages, **kwargs)

    def warm_up(self):
        """Eagerly load the model so it is ready before the first test."""
        self._load()

    def generate(self, system_prompt: str, user_message: str, temperature: float, top_p: float = 1.0, top_k: int = 50, repetition_penalty: float = 1.0) -> str:
        import torch

        self._load()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        tokenized = self._tokenize_messages(messages)
        # apply_chat_template may return a BatchEncoding or a plain tensor depending
        # on the transformers version — normalise to a plain input_ids tensor.
        if hasattr(tokenized, "input_ids"):
            input_ids = tokenized.input_ids.to(self._model.device)
        else:
            input_ids = tokenized.to(self._model.device)

        # Build stop-token list: tokenizer EOS + <|im_end|> (ChatML assistant
        # turn terminator).  Without <|im_end|> in eos_token_id the model keeps
        # generating past the end of its answer until max_new_tokens is exhausted.
        stop_ids: list[int] = []
        if self._tok.eos_token_id is not None:
            stop_ids.append(self._tok.eos_token_id)
        im_end_id = self._tok.convert_tokens_to_ids("<|im_end|>")
        if (
            im_end_id is not None
            and im_end_id != self._tok.unk_token_id
            and im_end_id not in stop_ids
        ):
            stop_ids.append(im_end_id)

        do_sample = temperature > 0.0
        with torch.inference_mode():
            output = self._model.generate(
                input_ids,
                attention_mask=torch.ones_like(input_ids),
                max_new_tokens=self._cfg.get("max_new_tokens", 2048),
                temperature=temperature if do_sample else 1.0,
                top_p=top_p if do_sample else 1.0,
                top_k=top_k if do_sample else 50,
                repetition_penalty=repetition_penalty,
                do_sample=do_sample,
                eos_token_id=stop_ids if stop_ids else None,
                pad_token_id=self._tok.eos_token_id,
            )
        return self._tok.decode(output[0][input_ids.shape[1]:], skip_special_tokens=True)

    def generate_stream(self, system_prompt: str, user_message: str, temperature: float, top_p: float = 1.0, top_k: int = 50, repetition_penalty: float = 1.0):
        import torch
        from transformers import TextIteratorStreamer

        self._load()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        tokenized = self._tokenize_messages(messages)
        if hasattr(tokenized, "input_ids"):
            input_ids = tokenized.input_ids.to(self._model.device)
        else:
            input_ids = tokenized.to(self._model.device)

        stop_ids: list[int] = []
        if self._tok.eos_token_id is not None:
            stop_ids.append(self._tok.eos_token_id)
        im_end_id = self._tok.convert_tokens_to_ids("<|im_end|>")
        if (
            im_end_id is not None
            and im_end_id != self._tok.unk_token_id
            and im_end_id not in stop_ids
        ):
            stop_ids.append(im_end_id)

        do_sample = temperature > 0.0
        streamer = TextIteratorStreamer(self._tok, skip_prompt=True, skip_special_tokens=True)
        exc: list[Exception] = []

        def _worker():
            try:
                with torch.inference_mode():
                    self._model.generate(
                        input_ids,
                        attention_mask=torch.ones_like(input_ids),
                        max_new_tokens=self._cfg.get("max_new_tokens", 2048),
                        temperature=temperature if do_sample else 1.0,
                        top_p=top_p if do_sample else 1.0,
                        top_k=top_k if do_sample else 50,
                        repetition_penalty=repetition_penalty,
                        do_sample=do_sample,
                        eos_token_id=stop_ids if stop_ids else None,
                        pad_token_id=self._tok.eos_token_id,
                        streamer=streamer,
                    )
            except Exception as err:
                exc.append(err)
                streamer.end()

        t = Thread(target=_worker, daemon=True)
        t.start()

        for text in streamer:
            yield text

        t.join()
        if exc:
            raise exc[0]


class APIMUTClient:
    """Calls an OpenAI-compatible endpoint (Ollama, OpenAI, vLLM, etc.)."""

    def __init__(self, cfg: dict, timeout: int = 240):
        from openai import OpenAI

        self._client = OpenAI(
            base_url=cfg.get("base_url", "http://localhost:11434/v1"),
            api_key=cfg.get("api_key", "ollama"),
        )
        self._model = cfg.get("model") or ""
        self._timeout = timeout

    def generate(self, system_prompt: str, user_message: str, temperature: float, top_p: float = 1.0, top_k: int = 50, repetition_penalty: float = 1.0) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            top_p=top_p,
            timeout=self._timeout,
        )
        return resp.choices[0].message.content or ""

    def generate_stream(self, system_prompt: str, user_message: str, temperature: float, top_p: float = 1.0, top_k: int = 50, repetition_penalty: float = 1.0):
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            top_p=top_p,
            timeout=self._timeout,
            stream=True,
        )
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta.content or ""
            if delta:
                yield delta


def make_mut_client(cfg: dict, timeout: int):
    mode = cfg.get("mode", "local")
    if mode == "local":
        return LocalMUTClient(cfg)
    if mode == "api":
        return APIMUTClient(cfg, timeout=timeout)
    raise ValueError(f"Unknown mut.mode: {mode!r}. Expected 'local' or 'api'.")


# ---------------------------------------------------------------------------
# Judge clients
# ---------------------------------------------------------------------------

class AnthropicJudgeClient:
    def __init__(self, cfg: dict):
        import anthropic

        api_key = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = cfg.get("model", _DEFAULT_JUDGE_MODEL)

    def evaluate(self, system_prompt: str, user_message: str) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text


class OpenAIJudgeClient:
    def __init__(self, cfg: dict):
        from openai import OpenAI

        api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key, base_url=cfg.get("base_url"))
        self._model = cfg.get("model", "gpt-4o")

    def evaluate(self, system_prompt: str, user_message: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
        )
        return resp.choices[0].message.content or ""


def make_judge_client(cfg: dict):
    provider = cfg.get("provider", "anthropic")
    if provider == "anthropic":
        return AnthropicJudgeClient(cfg)
    if provider == "openai":
        return OpenAIJudgeClient(cfg)
    raise ValueError(f"Unknown judge.provider: {provider!r}. Expected 'anthropic' or 'openai'.")


# ---------------------------------------------------------------------------
# Judge prompt construction
# ---------------------------------------------------------------------------

_JUDGE_SCHEMA = """\
{
  "test_id": "<string>",
  "verdict": "PASS" | "PARTIAL" | "FAIL" | "ERROR",
  "findings": [
    { "id": "<item_id>", "status": "PRESENT|MISSING|WRONG|CAUGHT|MISSED", "note": "<string>" }
  ],
  "false_positives_triggered": [
    { "id": "<fp_id>", "triggered": true|false, "note": "<string>" }
  ],
  "forbidden_present": [
    { "id": "<forbidden_id>", "present": true|false, "note": "<string>" }
  ],
  "notes": "<brief overall justification>"
}"""


def _normalise_bugs(bugs: list) -> list:
    """Return a copy of the bugs list with correct_fix normalised for the judge.

    If correct_fix is a list, it is converted to a human-readable string so the
    judge understands that *any* of the listed forms is an acceptable answer:
      ["isnull($in.0.score)", "nvl($in.0.score, 0) != 0"]
      → "Any of the following is acceptable: (1) isnull($in.0.score)  (2) nvl($in.0.score, 0) != 0"
    A plain string is left as-is.
    """
    result = []
    for bug in bugs:
        b = dict(bug)
        fix = b.get("correct_fix")
        if isinstance(fix, list):
            if len(fix) == 1:
                b["correct_fix"] = fix[0]
            else:
                numbered = "  ".join(f"({i+1}) {v}" for i, v in enumerate(fix))
                b["correct_fix"] = f"Any of the following is acceptable: {numbered}"
        result.append(b)
    return result


def build_judge_system_prompt(
    judge_system_prompt: str,
    judge_instructions: str,
    ctl2_reference: Optional[str] = None,
) -> str:
    """Combine all static judge content into one system prompt.

    Order (most-stable → least-stable, maximises cache prefix length):
      1. CTL2 language reference  — never changes, longest stable block
      2. Judge role description   — from suite JSON, static per project
      3. Evaluation instructions  — from suite JSON, static per project
      4. Required JSON schema     — defined in test.py, static per project

    Keeping all static content here (rather than appending it to every user
    message) maximises prompt-cache hits on both Anthropic and OpenAI providers:
    the system prompt prefix is identical across all test evaluations in a run.
    """
    parts = []
    if ctl2_reference:
        parts += [
            "# CTL2 Language Reference",
            "",
            ctl2_reference,
            "",
            "---",
        ]
    parts += [
        judge_system_prompt,
        "## Evaluation Instructions",
        judge_instructions,
        "## Required Output Format",
        "Respond with a single raw JSON object exactly matching this schema "
        "(no markdown fences, no prose before or after):",
        _JUDGE_SCHEMA,
    ]
    return "\n\n".join(parts)


def build_judge_user_message(test: dict, mut_response: str) -> str:
    """Build the per-test user message for the judge.

    Contains only the variable content that changes per test: the test definition
    (system prompt + user message sent to MUT, rubric) and the model's response.
    All static instructions and the output schema are in the system prompt so they
    are cached and not repeated in every call.
    """
    rubric = test.get("rubric", {})
    bugs = _normalise_bugs(test.get("bugs", []))
    component = test.get("component", "") or "—"

    display: dict = {}
    if bugs:
        display["bugs"] = bugs
    display.update(rubric)

    parts = [
        "## Test Definition",
        "",
        f"Test ID: {test['test_id']}",
        f"Type: {test['type']}",
        f"Component: {component}",
        "",
        "### System prompt sent to model:",
        test["system_prompt"],
        "",
        "### User message sent to model:",
        test["user_message"],
        "",
        "### Rubric:",
        json.dumps(display, indent=2),
        "",
        "---",
        "",
        "## Model Response to Evaluate:",
        "",
        mut_response or "(empty response)",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Numeric scoring + critical failure detection
# ---------------------------------------------------------------------------

def compute_score_str(judge_result: dict) -> str:
    """Return a human-readable 'N/M' fraction computed from judge findings.

    N = number of required findings the judge reported as CAUGHT or PRESENT.
    M = total required findings evaluated.

    Computed entirely in code from the judge's per-finding statuses — the judge
    is not asked to produce a score string itself, ensuring consistency.
    Falls back to '?/?' if no findings are present.
    """
    findings = judge_result.get("findings") or []
    if not findings:
        return "?/?"
    passed_statuses = {"PRESENT", "CAUGHT"}
    passed = sum(1 for f in findings if f.get("status") in passed_statuses)
    return f"{passed}/{len(findings)}"


def compute_numeric_score(judge_result: dict, test: dict) -> float:
    """Return a [0.0, 1.0] score derived from judge findings.

    All arithmetic is performed here in code — the judge supplies only
    per-finding statuses, FP triggers, and forbidden-item presence flags.

    Base score = passed_required / total_required
    Penalties (applied after base, clamped to [0.0, 1.0]):
      -0.20 per forbidden item reported PRESENT
      -0.25 per false-positive trap reported TRIGGERED
             (only on tests that define false_positive_traps in the rubric)
    """
    findings = judge_result.get("findings") or []
    forbidden_present = judge_result.get("forbidden_present") or []
    fp_triggered = judge_result.get("false_positives_triggered") or []

    passed_statuses = {"PRESENT", "CAUGHT"}
    total = len(findings)
    passed = sum(1 for f in findings if f.get("status") in passed_statuses)

    if total > 0:
        score = passed / total
    else:
        # No findings to count — fall back to verdict-based score
        score = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0, "ERROR": 0.0}.get(
            judge_result.get("verdict", ""), 0.0
        )

    for item in forbidden_present:
        if item.get("present"):
            score -= 0.20

    rubric_fp_traps = (test.get("rubric") or {}).get("false_positive_traps") or []
    if rubric_fp_traps:
        for item in fp_triggered:
            if item.get("triggered"):
                score -= 0.25

    return max(0.0, min(1.0, score))


def detect_critical_failure(judge_result: dict, test: dict) -> Optional[str]:
    """Return a description of a critical failure, or None.

    Driven entirely by the test's rubric — no test-ID-specific hardcoding.

    Three rubric-level signals trigger a critical failure:

    1. forbidden item with "critical": true  AND  judge reports it PRESENT
       → single item is enough

    2. rubric.critical_forbidden_all: [id, ...]  AND  judge reports ALL of
       them PRESENT  →  combination rule (e.g. both date boundary styles used)

    3. rubric.critical_wrong_verdict: true  AND  verdict_expected is set  AND
       judge verdict contradicts it  →  e.g. FAIL on code that should be PASS

    4. false_positive_trap with "critical": true  AND  judge reports it
       TRIGGERED  →  inverted semantics that would mislead the user
    """
    rubric = test.get("rubric") or {}
    verdict = judge_result.get("verdict", "")

    # Build lookup maps from judge result
    fp_present: dict[str, bool] = {
        item["id"]: bool(item.get("present"))
        for item in (judge_result.get("forbidden_present") or [])
        if isinstance(item, dict) and "id" in item
    }
    fp_triggered: dict[str, bool] = {
        item["id"]: bool(item.get("triggered"))
        for item in (judge_result.get("false_positives_triggered") or [])
        if isinstance(item, dict) and "id" in item
    }

    # 1. Individual critical forbidden items
    for item in (rubric.get("forbidden") or []):
        if isinstance(item, dict) and item.get("critical") and fp_present.get(item["id"]):
            return (
                f"{item['id']} violated: {item.get('check', item['id'])} "
                f"— {item.get('rationale', 'critical correctness failure')}"
            )

    # 2. Critical-if-ALL-present combination
    critical_all: list = rubric.get("critical_forbidden_all") or []
    if critical_all and all(fp_present.get(fid) for fid in critical_all):
        ids = ", ".join(critical_all)
        checks = [
            item.get("check", fid)
            for fid in critical_all
            for item in (rubric.get("forbidden") or [])
            if isinstance(item, dict) and item.get("id") == fid
        ]
        return f"All of [{ids}] violated: " + "; ".join(checks)

    # 3. Wrong verdict on code with a known expected verdict
    if rubric.get("critical_wrong_verdict"):
        expected = rubric.get("verdict_expected")
        if expected and verdict and verdict != expected:
            return (
                f"Wrong verdict: expected {expected} but judge returned {verdict} — "
                f"{'false positive failure on correct code' if expected == 'PASS' else 'missed critical bugs'}"
            )

    # 4. Critical false-positive traps triggered
    for trap in (rubric.get("false_positive_traps") or []):
        if isinstance(trap, dict) and trap.get("critical") and fp_triggered.get(trap["id"]):
            return (
                f"{trap['id']} triggered: {trap.get('trap', trap['id'])} "
                f"— {trap.get('reality', 'critical semantic error')}"
            )

    return None


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def _strip_thinking(text: str) -> str:
    return re.sub(
        r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", "", text, flags=re.IGNORECASE
    ).strip()


def parse_judge_json(raw: str) -> Optional[dict]:
    raw = _strip_thinking(raw)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[\s\S]+\}", raw)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Run log  (shared format with train.py — logs/<BaseModel>.yaml)
# ---------------------------------------------------------------------------

def _load_log(log_path: Path) -> list:
    if not log_path.exists():
        return []
    with open(log_path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def append_eval_log(
    log_dir: Path,
    base_model: str,
    run_name: str,
    results: dict,
) -> Path:
    """Append an eval entry to the shared run log (same file as train.py).

    Log file: logs/<slug>.yaml  where slug = Path(base_model).name
    Entry type: "eval"  (train.py writes type: "training")
    """
    slug = Path(base_model).name  # e.g. "Qwen3-8B" from "Qwen/Qwen3-8B"
    log_path = log_dir / f"{slug}.yaml"
    existing = _load_log(log_path)

    # Per-test summary — compact format for easy human scanning
    tests_summary: dict = {}
    for r in results.get("tests", []):
        tid = r["test_id"]
        run_i = r.get("run", 1)
        key = tid if run_i == 1 else f"{tid}_r{run_i}"
        jr = r.get("judge_result", {})
        cell: dict = {
            "verdict": jr.get("verdict", "?"),
            "score":   compute_score_str(jr),
            "numeric": round(r.get("numeric_score", 0.0), 4),
        }
        if r.get("critical_failure"):
            cell["critical"] = r["critical_failure"]
        tests_summary[key] = cell

    entry: dict = {
        "timestamp":      results["timestamp"],
        "type":           "eval",
        "run_name":       run_name,
        "model":          results["model"],
        "suite_score":    results["suite_score"],
        "generate_score": results["generate_score"],
        "validate_score": results["validate_score"],
        "tests":          tests_summary,
    }

    existing.insert(0, entry)  # newest first — same convention as train.py

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        f.write(f"# Run log for {base_model}\n")
        f.write(
            "# Written by train.py (type: training) "
            "and test.py (type: eval) — newest first\n"
        )
        f.write("# config_diff: hyperparameter changes vs. previous training run\n\n")
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return log_path


# ---------------------------------------------------------------------------
# Single-test runner
# ---------------------------------------------------------------------------

def _resolve_mut_overrides(mut_cfg: dict, test_type: str, test: dict) -> tuple[str, float, float, int, float]:
    """Return (system_prompt, temperature, top_p) applying any per-type MUT config overrides."""
    type_cfg = mut_cfg.get(test_type) or {}
    system_prompt = type_cfg.get("system_prompt") or test["system_prompt"]
    temperature = type_cfg["temperature"] if "temperature" in type_cfg else test.get("temperature", 0.1)
    top_p = type_cfg.get("top_p", 1.0)
    top_k = type_cfg.get("top_k", 50)
    repetition_penalty = type_cfg.get("repetition_penalty", 1.0)
    return system_prompt, temperature, top_p, top_k, repetition_penalty


def _build_mut_user_message(test: dict) -> str:
    """Return the user message to send to the MUT (unchanged for all test types).

    Emits a warning when a validate-type test's user message does not contain
    the word "validate" — the model keys off that framing and omitting it may
    produce a generate-style response instead of a bug report.
    """
    user_message = test["user_message"]
    if test.get("type") == "validate" and "validate" not in user_message.lower():
        test_id = test.get("test_id", "?")
        _print(
            f"[bold yellow]⚠  WARNING[/bold yellow] [{test_id}] validate test user message "
            "does not contain the word 'validate' — model may not produce a bug report."
        )
    return user_message


def _call_mut_with_retry(mut_client, test: dict, timeout: int, mut_cfg: dict, debug: bool = False) -> tuple[str, float]:
    test_type = test.get("type", "generate")
    system_prompt, temperature, top_p, top_k, repetition_penalty = _resolve_mut_overrides(mut_cfg, test_type, test)
    user_message = _build_mut_user_message(test)

    last_exc: Optional[Exception] = None
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            if debug and hasattr(mut_client, "generate_stream"):
                chunks: list[str] = []
                for chunk in mut_client.generate_stream(
                    system_prompt, user_message, temperature, top_p, top_k, repetition_penalty
                ):
                    chunks.append(chunk)
                    if _HAVE_RICH:
                        _console.print(chunk, end="", markup=False, highlight=False)
                    else:
                        print(chunk, end="", flush=True)
                if _HAVE_RICH:
                    _console.print()
                else:
                    print()
                response = "".join(chunks)
            else:
                response = mut_client.generate(system_prompt, user_message, temperature, top_p, top_k, repetition_penalty)
            return response or "", time.monotonic() - t0
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            last_exc = exc
            if attempt == 0 and (
                "timeout" in str(exc).lower() or elapsed >= timeout - 5
            ):
                _print("    [yellow]MUT timeout on attempt 1, retrying…[/yellow]")
                continue
            break

    raise last_exc  # type: ignore[misc]


def _call_judge_with_retry(
    judge_client, judge_system_prompt: str, user_message: str
) -> Optional[dict]:
    for attempt in range(2):
        prompt = user_message
        if attempt == 1:
            prompt = (
                user_message
                + "\n\n**IMPORTANT: Your entire response must be a single raw JSON object "
                "with no markdown fences, no explanatory text — just the JSON.**"
            )
        raw = judge_client.evaluate(judge_system_prompt, prompt)
        result = parse_judge_json(raw)
        if result:
            return result
        if attempt == 0:
            _print("    [yellow]Judge returned invalid JSON, retrying…[/yellow]")

    return None


def run_single_test(
    test: dict,
    mut_client,
    judge_client,
    judge_system_prompt: str,
    timeout: int,
    mut_cfg: dict,
    run_index: int = 1,
    debug: bool = False,
) -> dict:
    test_id = test["test_id"]
    t_global = time.monotonic()

    # Resolve prompts once so we can store the exact values sent to MUT
    test_type = test.get("type", "generate")
    mut_system_prompt, _temperature, _top_p , _top_k, _repetition_penalty= _resolve_mut_overrides(mut_cfg, test_type, test)
    mut_user_message = _build_mut_user_message(test)

    # Debug: print full messages to console
    if debug:
        _print(f"    [bold magenta]→ MUT SYSTEM MESSAGE:[/bold magenta]")
        _print(f"    [dim]{mut_system_prompt}[/dim]")
        _print(f"    [bold magenta]→ MUT USER MESSAGE:[/bold magenta]")
        _print(f"    [dim]{mut_user_message}[/dim]")

    # Step 1: MUT
    _print(f"    → MUT call (run {run_index}) …  [dim]temp={_temperature}, top-p={_top_p}, top-k={_top_k}, rep_penalty={_repetition_penalty}[/dim]")
    if debug:
        _print("    [bold magenta]→ MUT STREAM:[/bold magenta]")
    try:
        mut_response, mut_duration = _call_mut_with_retry(mut_client, test, timeout, mut_cfg, debug=debug)
    except Exception as exc:  # noqa: BLE001
        import traceback
        exc_repr = repr(exc) if not str(exc) else f"{type(exc).__name__}: {exc}"
        _print(f"    [red]MUT ERROR:[/red] {exc_repr}")
        _print(f"    [dim]{traceback.format_exc().strip()}[/dim]")
        return _error_result(test, run_index, f"MUT call failed: {exc_repr}", time.monotonic() - t_global)

    _print(f"      {len(mut_response)} chars in {mut_duration:.1f}s")

    # Step 2: Judge
    _print("    → Judge call …")
    judge_user_msg = build_judge_user_message(test, mut_response)
    try:
        judge_raw = _call_judge_with_retry(judge_client, judge_system_prompt, judge_user_msg)
    except Exception as exc:  # noqa: BLE001
        _print(f"    [red]Judge ERROR:[/red] {exc}")
        judge_raw = None

    if judge_raw is None:
        r = _error_result(test, run_index, "Judge JSON parse failure", time.monotonic() - t_global)
        r["mut_response"] = mut_response
        return r

    # Validate with pydantic if available
    if _HAVE_PYDANTIC:
        try:
            judge_result: dict = JudgeResponse(**judge_raw).model_dump()
        except Exception:
            judge_result = judge_raw
    else:
        judge_result = judge_raw

    # Step 3: Score
    numeric = compute_numeric_score(judge_result, test)
    critical = detect_critical_failure(judge_result, test)

    fp_triggered = [
        item for item in (judge_result.get("false_positives_triggered") or [])
        if item.get("triggered")
    ]
    fp_count = len(fp_triggered)

    verdict = judge_result.get("verdict", "?")
    score_str = compute_score_str(judge_result)
    crit_tag = "  [red][CRITICAL FAILURE][/red]" if critical else ""
    fp_tag = f"  [yellow]+FP({fp_count})[/yellow]" if fp_count else ""
    _print(f"      Verdict: [bold]{verdict}[/bold]  Score: {score_str}  Numeric: {numeric:.2f}{crit_tag}{fp_tag}")

    return {
        "test_id":          test_id,
        "test_type":        test.get("type"),
        "test_component":   test.get("component") or "",
        "run":              run_index,
        "mut_system_prompt": mut_system_prompt,
        "mut_user_message": mut_user_message,
        "mut_response":     mut_response,
        "judge_result":     judge_result,
        "numeric_score":    numeric,
        "critical_failure": critical,
        "judge_fp_count":   fp_count,
        "duration_seconds": time.monotonic() - t_global,
    }


def _error_result(test: dict, run_index: int, reason: str, duration: float) -> dict:
    return {
        "test_id":       test["test_id"],
        "test_type":     test.get("type"),
        "test_component": test.get("component") or "",
        "run":           run_index,
        "mut_response":  "",
        "judge_result":  {
            "test_id": test["test_id"],
            "verdict": "ERROR",
            "score": "0/0",
            "findings": [],
            "false_positives_triggered": [],
            "forbidden_present": [],
            "notes": reason,
        },
        "numeric_score":    0.0,
        "critical_failure": reason,
        "duration_seconds": duration,
    }


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------

def run_suite(cfg: dict, suite_file: Path, run_name: str, base_model: str, debug: bool = False) -> dict:
    """Run the full (or filtered) test suite. Returns the results dict."""
    with open(suite_file) as f:
        suite = json.load(f)

    # Load CTL2 reference — gives the judge ground-truth language knowledge so it
    # can evaluate fixes and explanations accurately, not just pattern-match rubric text.
    ctl2_reference: Optional[str] = None
    ref_path = _find_reference_file(suite_file)
    if ref_path:
        ctl2_reference = ref_path.read_text(encoding="utf-8")
        _print(f"  [dim]CTL2 reference loaded: {ref_path} ({len(ctl2_reference):,} chars)[/dim]")
    else:
        _print(f"  [yellow]Warning: {_CTL2_REF_FILENAME} not found — judge will have no language reference.[/yellow]")

    judge_system_prompt: str = build_judge_system_prompt(
        suite["judge_system_prompt"], suite["judge_instructions"], ctl2_reference
    )
    tests: list[dict] = suite["tests"]

    # Filter by test_ids
    test_ids_filter = cfg.get("test_ids")
    if isinstance(test_ids_filter, str):
        test_ids_filter = [t.strip() for t in test_ids_filter.split(",")]
    if test_ids_filter:
        tests = [t for t in tests if t["test_id"] in test_ids_filter]

    if not tests:
        _print("[red]No tests match the requested IDs.[/red]")
        sys.exit(1)

    timeout = int(cfg.get("timeout_seconds", 240))
    runs_per_test = int(cfg.get("runs_per_test", 1))
    mut_cfg = cfg.get("mut", {})
    judge_cfg = cfg.get("judge", {})

    _print("\n[bold cyan]Initialising MUT client…[/bold cyan]")
    mut_client = make_mut_client(mut_cfg, timeout)
    if hasattr(mut_client, "warm_up"):
        mut_client.warm_up()

    _print("[bold cyan]Initialising judge client…[/bold cyan]")
    judge_client = make_judge_client(judge_cfg)

    # Safe model name for output file names
    if mut_cfg.get("mode") == "local":
        raw_name = Path(mut_cfg.get("model_path", "unknown")).name
    else:
        raw_name = mut_cfg.get("model") or "unknown"
    model_name = re.sub(r"[^\w\-.]", "_", raw_name)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    _print(
        f"\n[bold]Suite:[/bold] {len(tests)} test(s) × {runs_per_test} run(s)  |  "
        f"Model: [cyan]{model_name}[/cyan]"
    )
    _print("─" * 60)

    all_results: list[dict] = []

    for test in tests:
        test_id = test["test_id"]
        comp = test.get("component", "") or ""
        comp_str = f" [{comp}]" if comp else ""
        _print(f"\n[bold yellow]▶ {test_id}[/bold yellow] {test.get('type', '?')}{comp_str}")

        for run_i in range(1, runs_per_test + 1):
            result = run_single_test(
                test, mut_client, judge_client,
                judge_system_prompt,
                timeout, mut_cfg, run_index=run_i, debug=debug,
            )
            all_results.append(result)

    # Suite-level averages — derived from each result's recorded type, not hardcoded ID sets
    generate_ids = {r["test_id"] for r in all_results if r.get("test_type") == "generate"}
    validate_ids = {r["test_id"] for r in all_results if r.get("test_type") == "validate"}

    def _mean(tid_set: set) -> float:
        scores = [r["numeric_score"] for r in all_results if r["test_id"] in tid_set]
        return sum(scores) / len(scores) if scores else 0.0

    all_tids = {r["test_id"] for r in all_results}

    return {
        "model":          model_name,
        "base_model":     base_model,
        "run_name":       run_name,
        "timestamp":      timestamp,
        "suite_score":    round(_mean(all_tids), 4),
        "generate_score": round(_mean(generate_ids), 4),
        "validate_score": round(_mean(validate_ids), 4),
        "tests":          all_results,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_results_json(results: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"results_{results['model']}_{results['timestamp']}.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    return path


_FAILURE_ANALYSIS_SYSTEM = """\
You are an expert on CTL2 (CloverDX transformation language) and LLM fine-tuning.
You will receive structured test results showing where a fine-tuned model failed or \
partially failed. Write a concise, actionable failure analysis in Markdown.

Rules:
- One ## section per distinct failure or error pattern you observe.
- Each ## heading MUST end with the test ID(s) it concerns in square brackets,
  e.g. "## Missed regex operator semantics [T5]" or
       "## Incorrect isNull explanation [T5, T13]".
  If the same pattern appears in multiple tests, group them into one section and
  list all affected IDs.
- State exactly what the model did wrong and what the correct behaviour is.
- Be specific enough that the section could be used directly to write a targeted
  SFT or DPO training example — quote the model's wrong output where helpful.
- Do NOT restate verdicts or scores — focus on the substance of what went wrong.
- If the model generated false positives (flagged correct code as wrong), call out
  the specific false claim and the correct explanation.
- End with a short ## Summary section listing the top-priority issues to fix."""


def generate_llm_failure_summary(judge_client, results: dict, suite_file: Path) -> str:
    """Ask the judge LLM to write a structured failure analysis of non-passing tests."""
    with open(suite_file) as f:
        suite = json.load(f)
    tests_by_id = {t["test_id"]: t for t in suite["tests"]}

    failing = [
        r for r in results["tests"]
        if r.get("judge_result", {}).get("verdict") in ("FAIL", "PARTIAL")
        or r.get("judge_fp_count", 0) > 0
    ]
    if not failing:
        return (
            "# Failure Analysis\n\n"
            f"**Model:** `{results['model']}`  "
            f"**Run:** {results['timestamp']}\n\n"
            "All tests passed with no issues or false positives detected.\n"
        )

    blocks: list[str] = []
    for r in failing:
        test_id = r["test_id"]
        suite_test = tests_by_id.get(test_id, {})
        jr = r.get("judge_result", {})

        lines = [
            f"### {test_id} ({r.get('test_type', '?')}"
            + (f" — {r.get('test_component')}" if r.get("test_component") else "")
            + ")",
            f"Verdict: {jr.get('verdict')}  Score: {compute_score_str(jr)}  "
            f"Numeric: {r.get('numeric_score', 0):.2f}",
            "",
            "**Input:**",
            "```",
            suite_test.get("user_message", "(not available)"),
            "```",
            "",
            "**Model response:**",
            "```",
            r.get("mut_response", ""),
            "```",
            "",
            "**Judge findings:**",
        ]
        for finding in jr.get("findings", []):
            lines.append(
                f"- [{finding.get('status', '?')}] {finding.get('id', '')}: "
                f"{finding.get('note', '')}"
            )
        fp_list = [fp for fp in (jr.get("false_positives_triggered") or []) if fp.get("triggered")]
        if fp_list:
            lines += ["", "**False positives flagged by judge:**"]
            for fp in fp_list:
                lines.append(f"- {fp.get('id', '')}: {fp.get('note', '')}")
        if jr.get("notes"):
            lines += ["", f"**Judge notes:** {jr['notes']}"]

        blocks.append("\n".join(lines))

    combined = "\n\n---\n\n".join(blocks)
    user_msg = (
        f"Model under test: `{results['model']}` (base: `{results.get('base_model', '?')}`)\n"
        f"Run: {results['timestamp']}\n"
        f"Suite score: {results['suite_score']:.4f}  "
        f"Generate: {results['generate_score']:.4f}  "
        f"Validate: {results['validate_score']:.4f}\n\n"
        f"---\n\n{combined}"
    )
    return judge_client.evaluate(_FAILURE_ANALYSIS_SYSTEM, user_msg)


def write_failure_analysis_md(content: str, results: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"analysis_{results['model']}_{results['timestamp']}.md"

    header = (
        f"# CTL2 Failure Analysis\n\n"
        f"**Model:** `{results['model']}`  "
        f"**Base:** `{results.get('base_model', '?')}`  "
        f"**Run:** {results['timestamp']}\n\n"
    )

    failing = [
        r for r in results["tests"]
        if r.get("judge_result", {}).get("verdict") in ("FAIL", "PARTIAL")
        or r.get("judge_fp_count", 0) > 0
    ]
    conversation_blocks: list[str] = []
    for r in failing:
        tid = r["test_id"]
        comp = f" — {r['test_component']}" if r.get("test_component") else ""
        verdict = r.get("judge_result", {}).get("verdict", "?")
        score = compute_score_str(r.get("judge_result", {}))
        lines = [
            f"### {tid}{comp}  ({verdict} {score})",
            "",
            "**SYSTEM**",
            "```",
            r.get("mut_system_prompt", ""),
            "```",
            "",
            "**USER**",
            "```",
            r.get("mut_user_message", ""),
            "```",
            "",
            "**ASSISTANT**",
            "```",
            r.get("mut_response", ""),
            "```",
        ]
        conversation_blocks.append("\n".join(lines))

    conversations_section = ""
    if conversation_blocks:
        conversations_section = (
            "\n\n---\n\n"
            "# Raw MUT Conversations\n\n"
            + "\n\n---\n\n".join(conversation_blocks)
        )

    with open(path, "w") as f:
        f.write(header + content + conversations_section + "\n")
    return path


def write_summary_md(results: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"summary_{results['model']}_{results['timestamp']}.md"

    lines: list[str] = [
        "# CTL2 Evaluation Summary",
        "",
        f"**Model:** `{results['model']}`",
        f"**Base model:** `{results.get('base_model', '?')}`",
        f"**Run:** {results['timestamp']}",
        "",
        "| Test | Run | Type | Component | Verdict | Score | Numeric | Critical |",
        "|------|-----|------|-----------|---------|-------|---------|----------|",
    ]

    for r in results["tests"]:
        jr = r.get("judge_result", {})
        verdict = jr.get("verdict", "?")
        score = compute_score_str(jr)
        numeric = r.get("numeric_score", 0.0)
        critical = "⚠ YES" if r.get("critical_failure") else ""
        lines.append(
            f"| {r['test_id']} | {r['run']} "
            f"| {r.get('test_type') or '?'} "
            f"| {r.get('test_component') or '—'} "
            f"| {verdict} | {score} | {numeric:.2f} | {critical} |"
        )

    lines += [
        "",
        f"**Suite score:**    {results['suite_score']:.4f}",
        f"**Generate score:** {results['generate_score']:.4f}",
        f"**Validate score:** {results['validate_score']:.4f}",
    ]

    criticals = [
        (r["test_id"], r["run"], r["critical_failure"])
        for r in results["tests"]
        if r.get("critical_failure")
    ]
    if criticals:
        lines += ["", "## Critical Failures", ""]
        for tid, run, desc in criticals:
            lines.append(f"- **{tid} (run {run}):** {desc}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return path


def load_prev_eval_entry(log_dir: Path, base_model: str, run_name: str) -> Optional[dict]:
    """Return the most recent eval log entry for this run_name, or None."""
    slug = Path(base_model).name
    log_path = log_dir / f"{slug}.yaml"
    entries = _load_log(log_path)
    for entry in entries:            # newest-first
        if entry.get("type") == "eval" and entry.get("run_name") == run_name:
            return entry
    return None


def _delta_cell(current: float, prev: Optional[float], *, rich: bool) -> tuple[str, str]:
    """Return (prev_str, indicator_str) for the two new columns."""
    if prev is None:
        return "—", "—"
    prev_str = f"{prev:.2f}"
    diff = current - prev
    if abs(diff) < 5e-4:
        ind = "=" if not rich else "[dim]=[/dim]"
    elif diff > 0:
        ind = "+" if not rich else "[green]+[/green]"
    else:
        ind = "-" if not rich else "[red]-[/red]"
    return prev_str, ind


def print_summary_table(results: dict, prev_entry: Optional[dict] = None):
    prev_tests: dict = (prev_entry or {}).get("tests", {})

    if _HAVE_RICH:
        table = Table(title=f"Results: {results['model']}", show_header=True, header_style="bold")
        for col, justify in [
            ("Test", "left"), ("Run", "right"), ("Type", "left"),
            ("Component", "left"), ("Verdict", "left"),
            ("Score", "left"), ("Numeric", "right"), ("Prev", "right"), ("±", "center"),
            ("Critical?", "left"),
        ]:
            table.add_column(col, justify=justify)

        for r in results["tests"]:
            jr = r.get("judge_result", {})
            verdict = jr.get("verdict", "?")
            color = {"PASS": "green", "PARTIAL": "yellow", "FAIL": "red", "ERROR": "red"}.get(verdict, "white")
            critical = r.get("critical_failure") or ""
            fp_count = r.get("judge_fp_count", 0)
            fp_cell = f"[yellow]+FP({fp_count})[/yellow]" if fp_count else ""
            flags = " ".join(filter(None, [f"[red]{critical}[/red]" if critical else "", fp_cell]))
            numeric = r.get("numeric_score", 0.0)
            prev_numeric = (prev_tests.get(r["test_id"]) or {}).get("numeric")
            prev_str, ind_str = _delta_cell(numeric, prev_numeric, rich=True)
            table.add_row(
                r["test_id"], str(r["run"]),
                r.get("test_type") or "?",
                r.get("test_component") or "—",
                f"[{color}]{verdict}[/{color}]",
                compute_score_str(jr),
                f"{numeric:.2f}",
                prev_str,
                ind_str,
                flags,
            )

        _console.print(table)

        # Suite-level scores with prev comparison
        def _suite_delta(key: str) -> str:
            cur = results.get(key, 0.0)
            prv = (prev_entry or {}).get(key)
            _, ind = _delta_cell(cur, prv, rich=True)
            prv_str = f" (prev {prv:.4f} {ind})" if prv is not None else ""
            return f"[bold]{cur:.4f}[/bold]{prv_str}"

        _console.print(
            f"\nSuite: {_suite_delta('suite_score')}  "
            f"Generate: {_suite_delta('generate_score')}  "
            f"Validate: {_suite_delta('validate_score')}"
        )
    else:
        print("\n" + "=" * 84)
        print(f"Model: {results['model']}   {results['timestamp']}")
        print("-" * 84)
        print(f"{'Test':<8} {'Run':<4} {'Type':<10} {'Component':<16} {'Verdict':<8} {'Score':<8} {'Num':<6} {'Prev':<6} {'±':<2} Critical")
        print("-" * 84)
        for r in results["tests"]:
            jr = r.get("judge_result", {})
            numeric = r.get("numeric_score", 0.0)
            prev_numeric = (prev_tests.get(r["test_id"]) or {}).get("numeric")
            prev_str, ind_str = _delta_cell(numeric, prev_numeric, rich=False)
            print(
                f"{r['test_id']:<8} {r['run']:<4} "
                f"{(r.get('test_type') or '?'):<10} "
                f"{(r.get('test_component') or '—'):<16} "
                f"{jr.get('verdict', '?'):<8} "
                f"{compute_score_str(jr):<8} "
                f"{numeric:<6.2f} "
                f"{prev_str:<6} "
                f"{ind_str:<2} "
                f"{'YES' if r.get('critical_failure') else ''}"
            )
        print("-" * 84)

        def _suite_delta_plain(key: str) -> str:
            cur = results.get(key, 0.0)
            prv = (prev_entry or {}).get(key)
            _, ind = _delta_cell(cur, prv, rich=False)
            prv_str = f" (prev {prv:.4f} {ind})" if prv is not None else ""
            return f"{cur:.4f}{prv_str}"

        print(
            f"Suite: {_suite_delta_plain('suite_score')}  "
            f"Generate: {_suite_delta_plain('generate_score')}  "
            f"Validate: {_suite_delta_plain('validate_score')}"
        )


# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------

def compare_results(files: list[Path]):
    all_data: dict[str, dict] = {}
    for p in files:
        with open(p) as f:
            data = json.load(f)
        all_data[data["model"]] = data

    test_ids: list[str] = []
    for data in all_data.values():
        for t in data["tests"]:
            if t["test_id"] not in test_ids:
                test_ids.append(t["test_id"])
        break

    model_names = list(all_data.keys())

    if _HAVE_RICH:
        table = Table(title="Model Comparison", show_header=True, header_style="bold")
        table.add_column("Test", style="bold")
        for m in model_names:
            table.add_column(m[:22])
        if len(model_names) == 2:
            table.add_column("Δ", justify="right")

        for tid in test_ids:
            row: list[str] = [tid]
            nums: list[float] = []
            for m in model_names:
                match = next((r for r in all_data[m]["tests"] if r["test_id"] == tid), None)
                if match:
                    v = (match.get("judge_result") or {}).get("verdict", "?")
                    n = match.get("numeric_score", 0.0)
                    nums.append(n)
                    color = {"PASS": "green", "PARTIAL": "yellow", "FAIL": "red"}.get(v, "white")
                    row.append(f"[{color}]{v}[/{color}] ({n:.2f})")
                else:
                    row.append("—")
                    nums.append(0.0)
            if len(model_names) == 2 and len(nums) == 2:
                d = nums[1] - nums[0]
                row.append(
                    f"[green]+{d:.2f}[/green]" if d > 0.01
                    else (f"[red]{d:.2f}[/red]" if d < -0.01 else f"{d:.2f}")
                )
            table.add_row(*row)

        suite_row: list[str] = ["[bold]Suite[/bold]"]
        suite_scores: list[float] = []
        for m in model_names:
            s = all_data[m].get("suite_score", 0.0)
            suite_scores.append(s)
            suite_row.append(f"[bold]{s:.4f}[/bold]")
        if len(model_names) == 2:
            d = suite_scores[1] - suite_scores[0]
            suite_row.append(f"[bold]{d:+.4f}[/bold]")
        table.add_row(*suite_row)

        _console.print(table)
    else:
        w = 18
        print(f"\n{'Test':<8}" + "".join(f"{m[:w]:<{w+2}}" for m in model_names))
        print("-" * (8 + (w + 2) * len(model_names)))
        for tid in test_ids:
            row_str = f"{tid:<8}"
            for m in model_names:
                match = next(
                    (r for r in all_data[m]["tests"] if r["test_id"] == tid), None
                )
                if match:
                    v = (match.get("judge_result") or {}).get("verdict", "?")
                    n = match.get("numeric_score", 0.0)
                    row_str += f"{v}({n:.2f}){'':>{w-6}}"
                else:
                    row_str += f"{'—':<{w+2}}"
            print(row_str)
        print("-" * (8 + (w + 2) * len(model_names)))
        suite_str = f"{'Suite':<8}"
        for m in model_names:
            s = all_data[m].get("suite_score", 0.0)
            suite_str += f"{s:.4f}{'':>{w-2}}"
        print(suite_str)


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def _find_suite_file(cfg: dict, config_dir: Path) -> Path:
    """Locate the test suite JSON in priority order."""
    # 1. Explicit in config
    if cfg.get("suite_file"):
        p = Path(cfg["suite_file"])
        return p if p.is_absolute() else config_dir / p

    # 2. resources/ next to test.py, then legacy locations
    candidates = [
        _RESOURCES_DIR / _SUITE_FILENAME,
        _SCRIPT_DIR / _SUITE_FILENAME,              # legacy location
        Path("resources") / _SUITE_FILENAME,
        Path(_SUITE_FILENAME),
    ]
    for p in candidates:
        if p.exists():
            return p

    return candidates[0]  # will fail existence check in caller


def _find_reference_file(suite_file: Path) -> Optional[Path]:
    """Locate the CTL2 language reference file alongside the suite file, or None."""
    candidates = [
        suite_file.parent / _CTL2_REF_FILENAME,
        _RESOURCES_DIR / _CTL2_REF_FILENAME,
        Path("resources") / _CTL2_REF_FILENAME,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def main():
    parser = argparse.ArgumentParser(
        description="CTL2 model evaluation — runs the test suite and judges responses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Run all tests (auto-discover latest export from training_config)
  python test.py configs/eval_config.yaml

  # Run only validate tests
  python test.py configs/eval_config.yaml --tests T4,T5,T7

  # 3 runs per test for statistical scoring
  python test.py configs/eval_config.yaml --runs 3

  # Dry-run: print effective config and exit
  python test.py configs/eval_config.yaml --dry-run

  # Compare two result files side by side
  python test.py --compare results/results_a.json results/results_b.json

eval_config.yaml schema:
  # Link to training config — enables auto-discovery and shared log
  training_config: configs/example.yaml

  mut:
    mode: local               # local (safetensors) | api (OpenAI-compatible)
    model_path: null          # null = auto-discover from training_config
    torch_dtype: float16      # float16 | bfloat16 | float32
    device_map: auto
    max_new_tokens: 2048
    chat_template_name: null  # optional LlamaFactory template name
    template_source: auto     # auto | tokenizer | llamafactory
    chat_template: null       # optional explicit Jinja template override
    enable_thinking: false
    base_url: http://localhost:11434/v1  # for mode=api
    model: my-model                     # for mode=api
    api_key: ollama                     # for mode=api

  judge:
    provider: anthropic       # anthropic | openai
    model: claude-opus-4-20250514
    api_key: ${ANTHROPIC_API_KEY}

  runs_per_test: 1
  timeout_seconds: 240
  output_dir: ./results
  test_ids: null              # null = all; or [T1, T4, T7]
""",
    )

    parser.add_argument("config", nargs="?", help="Path to YAML eval config file.")
    parser.add_argument("--tests", "-t", metavar="T1,T2,…",
                        help="Comma-separated test IDs to run (default: all).")
    parser.add_argument("--runs", "-n", type=int, metavar="N",
                        help="Runs per test — overrides config runs_per_test.")
    parser.add_argument("--output-dir", "-o", metavar="DIR",
                        help="Output directory — overrides config output_dir.")
    parser.add_argument("--suite-file", "-s", metavar="FILE",
                        help="Path to ctl2_test_suite.json (auto-discovered if omitted).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print effective config and exit without running tests.")
    parser.add_argument("--compare", nargs="+", metavar="FILE",
                        help="Compare two or more results JSON files side by side.")
    parser.add_argument("--no-llm-summary", action="store_true",
                        help="Skip the LLM-generated failure analysis after the run.")
    parser.add_argument("--no-log", action="store_true",
                        help="Skip writing eval results to the shared run log.")
    parser.add_argument("--debug", action="store_true",
                        help="Print full MUT messages (system + user) for each test to console.")

    args = parser.parse_args()

    # ── Compare mode ──────────────────────────────────────────────────────
    if args.compare:
        files = [Path(p) for p in args.compare]
        missing = [str(p) for p in files if not p.exists()]
        if missing:
            print("ERROR: file(s) not found: " + ", ".join(missing), file=sys.stderr)
            sys.exit(1)
        compare_results(files)
        return

    # ── Normal run ────────────────────────────────────────────────────────
    if not args.config:
        parser.error("config file is required (unless --compare is used)")

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    config_dir = config_path.parent

    cfg = _deep_merge(DEFAULT_CONFIG, load_config(config_path))

    # CLI overrides
    if args.tests:
        cfg["test_ids"] = [t.strip() for t in args.tests.split(",")]
    if args.runs:
        cfg["runs_per_test"] = args.runs
    if args.output_dir:
        cfg["output_dir"] = args.output_dir
    if args.suite_file:
        cfg["suite_file"] = args.suite_file

    # ── Resolve model path + run identity ─────────────────────────────────
    model_path, run_name, base_model = resolve_mut_model_path(cfg, config_dir)
    mut_cfg = cfg.setdefault("mut", {})
    mut_cfg["model_path"] = model_path  # ensure it's set for client

    # Keep template resolution behavior aligned with chat.py.
    template_name = resolve_template_name(cfg, config_dir)
    if template_name and not mut_cfg.get("chat_template_name"):
        mut_cfg["chat_template_name"] = template_name
        _print(f"  [dim]Template name from training config:[/dim] {template_name}")

    _print(
        "  [dim]Template selection:[/dim] "
        f"source={mut_cfg.get('template_source', 'auto')} "
        f"name={mut_cfg.get('chat_template_name')!r}"
    )

    train_enable_thinking = resolve_training_enable_thinking(cfg, config_dir)
    mut_enable_thinking = bool(mut_cfg.get("enable_thinking", False))
    if (
        train_enable_thinking is not None
        and train_enable_thinking != mut_enable_thinking
    ):
        _print(
            "  [yellow]Warning:[/yellow] enable_thinking mismatch between training_config "
            f"({train_enable_thinking}) and eval config ({mut_enable_thinking}). "
            "This can degrade output quality."
        )

    # ── Locate suite file ─────────────────────────────────────────────────
    suite_file = _find_suite_file(cfg, config_dir)
    if not suite_file.exists():
        print(
            f"ERROR: Test suite not found: {suite_file}\n"
            f"  Expected at: {_RESOURCES_DIR / _SUITE_FILENAME}\n"
            f"  Use --suite-file to specify its location.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Dry-run ──────────────────────────────────────────────────────────
    if args.dry_run:
        _print("[bold]Dry-run — effective config:[/bold]")
        display_cfg = dict(cfg)
        _print(yaml.dump(display_cfg, default_flow_style=False))
        _print(f"Suite file   : {suite_file}")
        _print(f"Model path   : {model_path}")
        _print(f"Run name     : {run_name}")
        _print(f"Base model   : {base_model}")
        return

    # ── Run suite ─────────────────────────────────────────────────────────
    results = run_suite(cfg, suite_file, run_name=run_name, base_model=base_model, debug=args.debug)

    # ── Write outputs ─────────────────────────────────────────────────────
    output_dir = Path(cfg["output_dir"])
    results_path = write_results_json(results, output_dir)
    summary_path = write_summary_md(results, output_dir)

    # Load previous eval entry BEFORE appending current run so the table can compare
    log_dir = _LOGS_DIR
    prev_entry = load_prev_eval_entry(log_dir, base_model, run_name)

    print_summary_table(results, prev_entry=prev_entry)

    _print(f"\n[green]Results written:[/green]")
    _print(f"  {results_path}")
    _print(f"  {summary_path}")

    # ── LLM failure analysis ──────────────────────────────────────────────
    if not args.no_llm_summary:
        judge_cfg = cfg.get("judge", {})
        try:
            judge_client = make_judge_client(judge_cfg)
            _print("\n[bold cyan]Generating failure analysis…[/bold cyan]")
            analysis_content = generate_llm_failure_summary(judge_client, results, suite_file)
            analysis_path = write_failure_analysis_md(analysis_content, results, output_dir)
            _print(f"  {analysis_path}")
        except Exception as exc:  # noqa: BLE001
            _print(f"[yellow]Warning: failure analysis skipped: {exc}[/yellow]")

    # ── Append to shared run log ──────────────────────────────────────────
    if not args.no_log:
        try:
            log_path = append_eval_log(log_dir, base_model, run_name, results)
            _print(f"  {log_path}  [dim](run log)[/dim]")
        except Exception as exc:  # noqa: BLE001
            _print(f"[yellow]Warning: could not write run log: {exc}[/yellow]")


if __name__ == "__main__":
    main()
