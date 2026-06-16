"""Stage 2: Local model candidate generation via transformers.

Loads the exported checkpoint and samples N completions per prompt using a
temperature spread for diversity. Each completion is CTL-normalized (fences
stripped, //#CTL2 header ensured) before leaving this stage.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

# Plain ChatML template with thinking disabled — same as test.py
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

_CTL_FENCE_RE = re.compile(r"```(?:ctl2?|CTL2?)?\s*\n([\s\S]*?)\n?```", re.IGNORECASE)
_CTL_HEADER = "//#CTL2"


def normalize_ctl(text: str) -> str:
    """Strip markdown fences and ensure //#CTL2 header (§3.3)."""
    m = _CTL_FENCE_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    if not text.startswith(_CTL_HEADER):
        text = _CTL_HEADER + "\n" + text
    return text


@dataclass
class Candidate:
    source_id: str
    index: int       # 0-based within this prompt's batch
    text: str        # CTL-normalized (fences stripped, //#CTL2 present)
    gen_meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class LocalGenerator:
    """Loads an exported safetensors checkpoint and generates candidates."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._model = None
        self._tok = None

    def _load(self):
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        ckpt = self._cfg["checkpoint_dir"]
        dtype_map = {
            "float16":  torch.float16,
            "bfloat16": torch.bfloat16,
            "float32":  torch.float32,
        }
        dtype = dtype_map.get(self._cfg.get("dtype", "bfloat16"), torch.bfloat16)
        attn_impl = self._cfg.get("attn_impl", "flash_attention_2")

        print(f"[generator] Loading model from {ckpt} …")
        self._tok = AutoTokenizer.from_pretrained(ckpt, trust_remote_code=True)
        self._tok = _patch_nothink(self._tok)

        for impl in (attn_impl, "sdpa"):
            try:
                self._model = AutoModelForCausalLM.from_pretrained(
                    ckpt,
                    torch_dtype=dtype,
                    device_map="auto",
                    attn_implementation=impl,
                    trust_remote_code=True,
                )
                print(f"[generator] Loaded with attn_implementation={impl!r}")
                break
            except (ImportError, ValueError):
                if impl == "sdpa":
                    raise
                print(f"[generator] {impl!r} unavailable, falling back to sdpa")

        self._model.eval()

    def warm_up(self):
        self._load()

    def generate_candidates(
        self,
        source_id: str,
        system: Optional[str],
        prompt: str,
        temperatures: list[float],
        top_p: float = 0.95,
        max_new_tokens: int = 1024,
        seed: Optional[int] = None,
        dedup: bool = True,
    ) -> list[Candidate]:
        """
        Generate one completion per temperature value.

        Returns deduplicated, CTL-normalized Candidate objects.
        A temperature of 0.0 gives a greedy (deterministic) decode.
        """
        import torch

        self._load()

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        tokenized = self._tok.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
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

        seen_texts: set[str] = set()
        candidates: list[Candidate] = []

        for i, temp in enumerate(temperatures):
            if seed is not None:
                torch.manual_seed(seed + i)
            do_sample = temp > 0.0
            t0 = time.monotonic()
            with torch.inference_mode():
                output = self._model.generate(
                    input_ids,
                    attention_mask=torch.ones_like(input_ids),
                    max_new_tokens=max_new_tokens,
                    temperature=temp if do_sample else 1.0,
                    top_p=top_p if do_sample else 1.0,
                    do_sample=do_sample,
                    eos_token_id=stop_ids if stop_ids else None,
                    pad_token_id=self._tok.eos_token_id,
                )
            elapsed = round(time.monotonic() - t0, 2)
            raw = self._tok.decode(output[0][input_ids.shape[1]:], skip_special_tokens=True)
            normalized = normalize_ctl(raw)

            if dedup and normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            candidates.append(Candidate(
                source_id=source_id,
                index=i,
                text=normalized,
                gen_meta={
                    "temperature": temp,
                    "top_p": top_p,
                    "max_new_tokens": max_new_tokens,
                    "elapsed_s": elapsed,
                    "raw_len": len(raw),
                },
            ))

        return candidates


def _patch_nothink(tok):
    """Disable <think> scaffolding — same logic as test.py."""
    try:
        tok.apply_chat_template(
            [{"role": "user", "content": "hi"}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        _orig = tok.apply_chat_template

        def _nothink(*args, **kwargs):
            kwargs.setdefault("enable_thinking", False)
            return _orig(*args, **kwargs)

        tok.apply_chat_template = _nothink
        print("  [generator] Chat template: nothink via enable_thinking=False")
    except TypeError:
        tok.chat_template = _CHATML_NOTHINK_TEMPLATE
        print("  [generator] Chat template: nothink via ChatML override")
    return tok
