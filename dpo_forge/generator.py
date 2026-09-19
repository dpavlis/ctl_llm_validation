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

_THINK_OPEN_RE = re.compile(r"<think\s*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", re.IGNORECASE)


def split_thinking(text: str, thinking_enabled: bool = True) -> tuple[str, str]:
    """Split a raw completion into (thinking, answer).

    Qwen3-style templates open `<think>` in the *generation prompt* itself, so
    the decoded completion usually starts mid-thought with no opening tag and
    closes with `</think>`. Splitting on the LAST `</think>` therefore handles
    both shapes (tag present or not).

    Only the answer half may ever reach the judge, the conversation history or
    the exported training data — chain-of-thought is scratch work, not output.

    With no `</think>` present:
      * thinking disabled -> there was no thinking; the whole text is answer.
      * thinking enabled  -> generation was cut off mid-thought (max_new_tokens
        exhausted). Returns an EMPTY answer so the caller can detect it rather
        than silently judging a fragment of reasoning as if it were code.
    """
    matches = list(_THINK_CLOSE_RE.finditer(text))
    if matches:
        last = matches[-1]
        thinking = _THINK_OPEN_RE.sub("", text[:last.start()], count=1).strip()
        return thinking, text[last.end():].strip()

    if thinking_enabled:
        return text.strip(), ""
    return "", text.strip()


def normalize_ctl(text: str) -> str:
    """Strip markdown fences and trim (§3.3).

    Does NOT inject the //#CTL2 header. Emitting the header is the model's
    responsibility — CloverDX treats header-less code as the removed CTL1
    language. A missing header is therefore a real defect we must preserve so
    the runner can flag the candidate invalid (it then becomes a DPO 'rejected'),
    not silently repair it.
    """
    m = _CTL_FENCE_RE.search(text)
    if m:
        text = m.group(1)
    return text.strip()


@dataclass
class Candidate:
    source_id: str
    index: int       # 0-based within this prompt's batch
    text: str        # CTL-normalized (fences stripped; //#CTL2 header NOT fabricated)
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
        self._enable_thinking = bool(cfg.get("enable_thinking", False))
        effort = cfg.get("reasoning_effort")
        self._reasoning_effort = str(effort) if effort else None
        # Older tokenizers reject unknown apply_chat_template kwargs with a
        # TypeError; probed once in _load().
        self._accepts_thinking_kwarg = True

    @property
    def enable_thinking(self) -> bool:
        return self._enable_thinking

    def _template_kwargs(self) -> dict:
        if not self._accepts_thinking_kwarg:
            return {}
        kwargs = {"enable_thinking": self._enable_thinking}
        if self._enable_thinking and self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        return kwargs

    def _check_reasoning_effort(self) -> None:
        """Validate reasoning_effort at load time.

        Jinja silently ignores variables a template never reads, so without
        this an unsupported template or a bad value would fail quietly.
        """
        if not self._reasoning_effort:
            return
        if not self._enable_thinking:
            print("  [generator] WARNING: reasoning_effort is set but enable_thinking "
                  "is false — the template applies it only while thinking is enabled.")
            return
        template = getattr(self._tok, "chat_template", None) or ""
        if "reasoning_effort" not in template:
            print(f"  [generator] WARNING: chat template does not reference reasoning_effort; "
                  f"{self._reasoning_effort!r} will be ignored.")
            return
        try:
            self._tok.apply_chat_template(
                [{"role": "user", "content": "hi"}],
                tokenize=False, add_generation_prompt=True, **self._template_kwargs(),
            )
        except Exception as exc:
            # The template itself validates the allowed values.
            raise SystemExit(
                f"[generator] FATAL: reasoning_effort={self._reasoning_effort!r} rejected "
                f"by the chat template: {exc}"
            )

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
        try:
            self._tok.apply_chat_template(
                [{"role": "user", "content": "hi"}],
                tokenize=False, add_generation_prompt=True,
                enable_thinking=self._enable_thinking,
            )
        except TypeError:
            self._accepts_thinking_kwarg = False
            if self._enable_thinking:
                raise SystemExit(
                    "[generator] FATAL: enable_thinking: true was requested, but this "
                    "tokenizer's apply_chat_template does not accept the flag."
                )
        if self._enable_thinking:
            print(f"  [generator] Chat template: thinking ENABLED"
                  + (f" (reasoning_effort={self._reasoning_effort})" if self._reasoning_effort else ""))
        else:
            self._tok = _patch_nothink(self._tok)
        self._check_reasoning_effort()

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
            **self._template_kwargs(),
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
            # Chain-of-thought never becomes a candidate.
            thinking, answer = split_thinking(raw, self._enable_thinking)
            if self._enable_thinking and not answer:
                print(f"  [generator] WARNING: completion {i} was cut off mid-thought "
                      f"(max_new_tokens={max_new_tokens}) — no answer after </think>, skipping")
                continue
            normalized = normalize_ctl(answer)

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
                    "thinking_len": len(thinking),
                },
            ))

        return candidates

    def generate_reply(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        top_p: float = 1.0,
        top_k: int = 50,
        repetition_penalty: float = 1.0,
        max_new_tokens: int = 2048,
        seed: Optional[int] = None,
    ) -> str:
        """
        Generate one completion for an already-built multi-turn message list
        (e.g. system/user/assistant/user/...). Unlike generate_candidates(),
        the caller supplies the full conversation history — used to show the
        MUT its own earlier answer plus follow-up feedback.

        Returns the raw decoded text (fences NOT stripped, thinking NOT removed
        — the caller normalizes, and splits with split_thinking() so it can log
        the reasoning separately from the answer).
        """
        import torch

        self._load()

        tokenized = self._tok.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            **self._template_kwargs(),
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

        if seed is not None:
            torch.manual_seed(seed)
        do_sample = temperature > 0.0
        with torch.inference_mode():
            output = self._model.generate(
                input_ids,
                attention_mask=torch.ones_like(input_ids),
                max_new_tokens=max_new_tokens,
                temperature=temperature if do_sample else 1.0,
                top_p=top_p if do_sample else 1.0,
                top_k=top_k if do_sample else 1,
                repetition_penalty=repetition_penalty if do_sample else 1.0,
                do_sample=do_sample,
                eos_token_id=stop_ids if stop_ids else None,
                pad_token_id=self._tok.eos_token_id,
            )
        return self._tok.decode(output[0][input_ids.shape[1]:], skip_special_tokens=True)


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
