"""On-policy context distillation (OPCD): spec/onpolicy_context_distillation_spec.md.

One set of weights, two roles:
  student  = base + a trainable LoRA, PLAIN system prompt (what the model sees at eval time);
  teacher  = the same base with the adapter disabled, RULE system prompt.
Per round: the student samples k completions per prompt; every sampled token y_t is scored by
both, s_t = log pi_student(y_t | plain, y_<t) and r_t = log pi_teacher(y_t | rule, y_<t), and the
student is trained with the per-token reverse-KL policy gradient
    A_t = r_t - s_t (detached),   L = -sum_t A_t * log pi_student(y_t) / n_tokens.
Prompts are tokenized by test.py's own LocalMUTClient code path, so they are byte-identical to
evaluation (system prompt, template, enable_thinking, reasoning_effort).

  python opcd.py prepare --config configs/opcd_c1.yaml      # prompt sets -> data/opcd/<run>/prompts.jsonl
  python opcd.py smoke   --config configs/opcd_c1.yaml      # 4 prompts, repeated steps on one batch: KL must fall
  python opcd.py train   --config configs/opcd_c1.yaml      # rounds; resumes after the last finished round
  python opcd.py export  --config configs/opcd_c1.yaml --round N --out /home/pavlisd/exports/<name>
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "self_distill" / "dpodef2"))
import self_distill as sd  # noqa: E402
import test as eval_harness  # noqa: E402
from build_ctx_pairs import REFERS, scan_belief  # noqa: E402
from dpo_forge.generator import split_thinking  # noqa: E402

OUT_BASE = ROOT / "data" / "opcd"


# ----------------------------------------------------------------------------- config / prompts

def load_cfg(path: str) -> dict:
    cfg = yaml.safe_load(open(path))
    cfg["_out"] = OUT_BASE / cfg["run"]
    return cfg


def read_prompts(spec: dict) -> list[dict]:
    path = Path(spec["file"]) if "file" in spec else sd.RUNS_DIR / spec["run"] / "prompts.jsonl"
    rows = sd.read_jsonl(path)
    if "split" in spec:
        rows = [p for p in rows if p.get("split") == spec["split"]]
    return rows


def cmd_prepare(cfg: dict) -> None:
    out = cfg["_out"]
    out.mkdir(parents=True, exist_ok=True)
    pc = cfg["prompts"]
    sets: dict[str, list[dict]] = {"target": [], "hard": [], "probe": [], "replay": []}
    for s in pc["target"]:
        sets["target"] += read_prompts(s)
    if pc.get("hard") and Path(pc["hard"]).exists():
        held = set(json.load(open(pc["hard_holdout"]))["holdout"]) if pc.get("hard_holdout") else set()
        for h in sd.read_jsonl(Path(pc["hard"])):  # agent-authored (spec/opcd_hard_cases_brief.md)
            if h["id"] in held:
                continue  # measured with data/opcd/eval_hard_cases.py --holdout, never trained
            h.setdefault("prompt_id", sd.make_prompt_id(h["user"]))
            if h["task_type"] == "validate":
                h["user"], _ = sd.with_validate_format(h["user"])
            h.setdefault("record_id", h.get("id"))
            sets["hard"].append(h)
    sets["probe"] = read_prompts(pc["probe"])
    used = {p["prompt_id"] for k in ("target", "hard", "probe") for p in sets[k]}
    assert not ({p["prompt_id"] for p in sets["probe"]} & {p["prompt_id"] for p in sets["target"] + sets["hard"]}), \
        "probe prompts overlap the training prompts"

    excluded, _ = sd.load_exclusion_set()
    pool, _ = sd.build_pool(excluded)
    pool = [p for p in pool if p["prompt_id"] not in used]
    n_train = len(sets["target"]) + len(sets["hard"])
    n_replay = math.ceil(n_train * pc["replay_share"] / (1 - pc["replay_share"]))
    rng = random.Random(cfg["train"]["seed"])
    for task, share in pc["replay_task_mix"].items():
        cand = [p for p in pool if p["task_type"] == task]
        sets["replay"] += rng.sample(cand, min(len(cand), round(n_replay * share)))

    keep = ("prompt_id", "task_type", "component", "source_file", "record_id", "user")
    rows = [{**{k: p.get(k) for k in keep}, "set": name} for name, ps in sets.items() for p in ps]
    seen, dedup = set(), []
    for r in rows:  # a prompt in two training sets is trained once
        if r["prompt_id"] in seen:
            continue
        seen.add(r["prompt_id"]); dedup.append(r)
    (out / "prompts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in dedup))
    rep = Counter(f"{r['set']}:{r['task_type']}" for r in dedup)
    print(json.dumps(dict(sorted(rep.items())), indent=1))
    print(f"-> {sd.rel(out / 'prompts.jsonl')} ({len(dedup)} prompts; pool after exclusions {len(pool)})")


# ----------------------------------------------------------------------------- model / tokenization

class _NoModel:
    def eval(self):
        return self


def prompt_tokenizer(eval_config: str):
    """A LocalMUTClient with its tokenizer and chat template loaded exactly as test.py loads them
    (the model load is stubbed out); returns (client, mut_cfg)."""
    cfg, _raw = sd.load_eval_config(Path(eval_config))
    mut_cfg = sd.resolve_mut_config(cfg, Path(eval_config))
    client = eval_harness.LocalMUTClient(mut_cfg)
    import transformers
    with mock.patch.object(transformers.AutoModelForCausalLM, "from_pretrained", lambda *a, **k: _NoModel()):
        client._load()
    client._model = None  # never generate through it
    return client, mut_cfg


class Roles:
    """Per (role, mode): tokenizer client + per-task system prompt and sampling."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.clients, self.mut = {}, {}
        for role in ("student", "teacher"):
            for mode in ("on", "off"):
                c, m = prompt_tokenizer(cfg[role][mode])
                if bool(m.get("enable_thinking")) != (mode == "on"):
                    raise SystemExit(f"{cfg[role][mode]}: enable_thinking does not match mode {mode}")
                self.clients[role, mode], self.mut[role, mode] = c, m
        marker = cfg["rule_marker"]
        for task in ("generate", "validate", "fix"):
            for mode in ("on", "off"):
                st, te = self.system("student", mode, task), self.system("teacher", mode, task)
                if marker in st:
                    raise SystemExit(f"rule found in the STUDENT {task}/{mode} system prompt")
                if marker not in te:
                    raise SystemExit(f"rule missing from the TEACHER {task}/{mode} system prompt")
        self.base_paths = {str(Path(m["model_path"]).resolve()) for m in self.mut.values()}

    def mode(self, p: dict) -> str:
        """Thinking mode for a prompt: `modes` by task, `replay_modes` overriding it for replay prompts."""
        if p.get("set") == "replay" and p["task_type"] in (self.cfg.get("replay_modes") or {}):
            return self.cfg["replay_modes"][p["task_type"]]
        return self.cfg["modes"][p["task_type"]]

    def teacher_role(self, p: dict) -> str:
        """Replay prompts with replay_teacher: plain are scored by rb1006 under the PLAIN prompt
        (adapter off): an on-policy reverse-KL anchor back to rb1006, not a rule signal."""
        return "student" if p.get("set") == "replay" and self.cfg.get("replay_teacher") == "plain" else "teacher"

    def system(self, role: str, mode: str, task: str) -> str:
        return sd.sampling_for(self.mut[role, mode], task)["system_prompt"]

    def sampling(self, p: dict) -> dict:
        return sd.sampling_for(self.mut["student", self.mode(p)], p["task_type"])

    def ids(self, role: str, p: dict) -> list[int]:
        mode, task = self.mode(p), p["task_type"]
        msgs = [{"role": "system", "content": self.system(role, mode, task)}, {"role": "user", "content": p["user"]}]
        t = self.clients[role, mode]._tokenize_messages(msgs)
        t = t.input_ids if hasattr(t, "input_ids") else t
        return [int(x) for x in (t[0] if hasattr(t, "dim") and t.dim() == 2 else t)]

    @property
    def tok(self):
        return self.clients["student", "on"]._tok


def load_model(cfg: dict, adapter: Path | None = None, trainable: bool = True):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM

    base = AutoModelForCausalLM.from_pretrained(cfg["base_model"], dtype=torch.bfloat16, device_map={"": 0})
    base.config.use_cache = True
    base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    lc = cfg["lora"]
    if adapter is not None:
        model = PeftModel.from_pretrained(base, str(adapter), is_trainable=trainable)
    else:
        model = get_peft_model(base, LoraConfig(r=lc["r"], lora_alpha=lc["alpha"], lora_dropout=lc["dropout"],
                                                target_modules=lc["target"], bias="none", task_type="CAUSAL_LM"))
    n_tr = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"model loaded; trainable params {n_tr / 1e6:.1f}M", flush=True)
    return model


def stop_ids(tok) -> list[int]:
    ids = [tok.eos_token_id] if tok.eos_token_id is not None else []
    im_end = tok.convert_tokens_to_ids("<|im_end|>")
    if im_end is not None and im_end != tok.unk_token_id and im_end not in ids:
        ids.append(im_end)
    return ids


def make_sample(roles: Roles, p: dict, i: int, comp: list[int], hit_cap: bool, gen_s: float) -> dict:
    task = p["task_type"]
    mode = roles.mode(p)
    raw = roles.tok.decode(comp, skip_special_tokens=True)
    thinking, answer = split_thinking(raw, thinking_enabled=(mode == "on"))
    return {"prompt_id": p["prompt_id"], "set": p["set"], "task_type": task, "mode": mode, "sample_idx": i,
            "teacher": roles.teacher_role(p),
            "completion_ids": comp, "raw": raw, "thinking": thinking, "answer": answer,
            "think_closed": mode == "off" or "</think>" in raw, "hit_cap": hit_cap,
            "new_tokens": len(comp), "gen_s": round(gen_s, 1)}


def sample(model, roles: Roles, p: dict, k: int, max_new: int, seed: int) -> list[dict]:
    """k student samples (adapter on, plain prompt) with HF generate, as
    self_distill.SamplingClient.sample_k draws them."""
    import torch

    s = roles.sampling(p)
    ids = roles.ids("student", p)
    inp = torch.tensor([ids], device=model.device)
    stops = stop_ids(roles.tok)
    torch.manual_seed(seed)
    model.eval()
    t0 = time.monotonic()
    with torch.inference_mode():
        out = model.generate(input_ids=inp, attention_mask=torch.ones_like(inp), max_new_tokens=max_new,
                             do_sample=True, temperature=s["temperature"], top_p=s["top_p"], top_k=s["top_k"],
                             repetition_penalty=s["repetition_penalty"], num_return_sequences=k,
                             eos_token_id=stops, pad_token_id=roles.tok.eos_token_id)
    el = time.monotonic() - t0
    res = []
    for i, row in enumerate(out):
        n, hit_cap = sd.generated_length(row[len(ids):].tolist(), set(stops))
        res.append(make_sample(roles, p, i, row[len(ids):len(ids) + n].tolist(), hit_cap, el))
    return res


class HfSampler:
    def __init__(self, model, roles: Roles):
        self.model, self.roles = model, roles

    def publish(self, adapter_dir: Path, name: str) -> None:
        pass  # the trainer's own weights are sampled

    def sample_many(self, jobs: list[tuple[dict, int]], k: int, max_new: int) -> list[list[dict]]:
        return [sample(self.model, self.roles, p, k, max_new, seed) for p, seed in jobs]


class VllmSampler:
    """Student sampling on a vLLM server holding the same base weights. Step 0 check (2026-10-09):
    vLLM 0.23 serves Qwen3_5ForConditionalGeneration with LoRA, and its per-token log-probs match
    HF to ~1e-3 nats/token. Each round's adapter is hot-loaded under a new name
    (VLLM_ALLOW_RUNTIME_LORA_UPDATING=True) after its keys are renamed to the
    ConditionalGeneration layout (model.layers.N -> model.language_model.layers.N)."""

    def __init__(self, cfg: dict, roles: Roles):
        sc = cfg["sampler"]
        self.url, self.base_name = sc["url"].rstrip("/"), sc["served_model"]
        self.workers, self.roles, self.current = sc.get("concurrency", 32), roles, sc["served_model"]

    def publish(self, adapter_dir: Path, name: str) -> None:
        import requests
        from safetensors.torch import load_file, save_file
        dst = adapter_dir.parent / "adapter_vllm"
        dst.mkdir(exist_ok=True)
        t = load_file(adapter_dir / "adapter_model.safetensors")
        save_file({k.replace("base_model.model.model.layers.", "base_model.model.model.language_model.layers."): v
                   for k, v in t.items()}, dst / "adapter_model.safetensors")
        shutil.copy2(adapter_dir / "adapter_config.json", dst / "adapter_config.json")
        requests.post(f"{self.url}/v1/unload_lora_adapter", json={"lora_name": name}, timeout=120)  # resume
        r = requests.post(f"{self.url}/v1/load_lora_adapter", json={"lora_name": name, "lora_path": str(dst.resolve())},
                          timeout=600)
        if r.status_code != 200:
            raise RuntimeError(f"vLLM load_lora_adapter {name}: {r.status_code} {r.text[:300]}")
        old, self.current = self.current, name
        if old not in (self.base_name, name):
            requests.post(f"{self.url}/v1/unload_lora_adapter", json={"lora_name": old}, timeout=120)
        print(f"vLLM now samples adapter {name}", flush=True)

    def _one(self, p: dict, seed: int, k: int, max_new: int) -> list[dict]:
        import requests
        s = self.roles.sampling(p)
        ids = self.roles.ids("student", p)
        t0 = time.monotonic()
        r = requests.post(f"{self.url}/v1/completions", timeout=7200, json={
            "model": self.current, "prompt": ids, "max_tokens": max_new, "n": k, "seed": seed,
            "temperature": s["temperature"], "top_p": s["top_p"], "top_k": s["top_k"],
            "repetition_penalty": s["repetition_penalty"], "stop_token_ids": stop_ids(self.roles.tok),
            "return_token_ids": True, "skip_special_tokens": False})
        r.raise_for_status()
        el = time.monotonic() - t0
        ch = sorted(r.json()["choices"], key=lambda c: c["index"])
        return [make_sample(self.roles, p, i, list(c["token_ids"]), c["finish_reason"] == "length", el)
                for i, c in enumerate(ch)]

    def sample_many(self, jobs: list[tuple[dict, int]], k: int, max_new: int) -> list[list[dict]]:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(self.workers) as ex:
            return list(ex.map(lambda j: self._one(j[0], j[1], k, max_new), jobs))


def _chunk_logp(h, tgt, w):
    import torch.nn.functional as F
    return F.linear(h, w).float().log_softmax(-1).gather(-1, tgt[:, None])[:, 0]


def completion_logps(model, prompt_ids: list[int], comp_ids: list[int], grad: bool, chunk: int):
    """log p(comp_ids[t] | prompt, comp_ids[:t]) for every completion token. The vocabulary
    (248k) is projected in chunks; with grad each chunk is recomputed in backward."""
    import torch
    from torch.utils.checkpoint import checkpoint

    base = model.get_base_model()
    ids = torch.tensor([prompt_ids + comp_ids], device=model.device)
    h = base.model(input_ids=ids, use_cache=False).last_hidden_state[0]
    P, T = len(prompt_ids), len(comp_ids)
    h = h[P - 1:P - 1 + T]
    tgt = ids[0, P:P + T]
    w = base.lm_head.weight
    parts = []
    for i in range(0, T, chunk):
        if grad:
            parts.append(checkpoint(_chunk_logp, h[i:i + chunk], tgt[i:i + chunk], w, use_reentrant=False))
        else:
            parts.append(_chunk_logp(h[i:i + chunk], tgt[i:i + chunk], w))
    return torch.cat(parts)


def teacher_logps(model, roles: Roles, smp: dict, chunk: int):
    import torch
    ids = roles.ids(roles.teacher_role(smp), smp)
    model.eval()
    with torch.no_grad(), model.disable_adapter():
        return completion_logps(model, ids, smp["completion_ids"], grad=False, chunk=chunk).cpu()


def flagged_tokens(roles: Roles, comp: list[int], adv, n: int = 8) -> list[dict]:
    """The n tokens the teacher disagrees with most (most negative A_t), with context."""
    import torch
    idx = torch.topk(-adv, min(n, len(adv))).indices.tolist()
    tok = roles.tok
    return [{"pos": i, "A": round(float(adv[i]), 2), "token": tok.decode(comp[i:i + 1]),
             "context": tok.decode(comp[max(0, i - 16):i + 1])[-120:]} for i in sorted(idx)]


# ----------------------------------------------------------------------------- training

class Trainer:
    def __init__(self, cfg: dict, roles: Roles, model):
        import torch
        self.cfg, self.roles, self.model = cfg, roles, model
        tc = cfg["train"]
        self.params = [p for p in model.parameters() if p.requires_grad]
        self.opt = torch.optim.AdamW(self.params, lr=tc["lr"], weight_decay=0.0, betas=(0.9, 0.999))
        self.step = 0

    def lr_at(self, step: int) -> float:
        tc = self.cfg["train"]
        return tc["lr"] * min(1.0, (step + 1) / max(1, tc["warmup_steps"]))

    def train_minibatch(self, smps: list[dict]) -> dict:
        """One optimizer step over smps (each with prompt_ids, completion_ids, r = teacher logps)."""
        import torch
        tc = self.cfg["train"]
        self.model.train()
        self.opt.zero_grad(set_to_none=True)
        n_tok = sum(len(s["completion_ids"]) for s in smps)
        stats = []
        for s in smps:
            lp = completion_logps(self.model, s["prompt_ids"], s["completion_ids"], grad=True, chunk=tc["logits_chunk"])
            r = s["r"].to(lp.device)
            adv = (r - lp.detach())
            if tc.get("adv_clip"):
                adv = adv.clamp(-tc["adv_clip"], tc["adv_clip"])
            loss = -(adv * lp).sum() / n_tok
            loss.backward()
            kl = (lp.detach() - r).cpu()  # per-token sample estimate of KL(student || teacher)
            s["kl_mean"] = round(float(kl.mean()), 4)
            s["kl_max"] = round(float(kl.max()), 2)
            s["flagged"] = flagged_tokens(self.roles, s["completion_ids"], -kl)
            stats.append(float(kl.sum()))
        gn = torch.nn.utils.clip_grad_norm_(self.params, tc["grad_clip"])
        for g in self.opt.param_groups:
            g["lr"] = self.lr_at(self.step)
        self.opt.step()
        self.step += 1
        return {"step": self.step, "tokens": n_tok, "kl_per_token": round(sum(stats) / n_tok, 4),
                "grad_norm": round(float(gn), 3), "lr": self.lr_at(self.step - 1)}

    def save(self, d: Path) -> None:
        import torch
        self.model.save_pretrained(str(d / "adapter"))
        torch.save({"opt": self.opt.state_dict(), "step": self.step}, d / "optimizer.pt")

    def load_state(self, d: Path) -> None:
        import torch
        st = torch.load(d / "optimizer.pt", map_location="cpu", weights_only=False)
        self.opt.load_state_dict(st["opt"])
        self.step = st["step"]


def scan(smp: dict) -> dict:
    text = (smp.get("thinking") or "") + "\n" + (smp.get("answer") or "")
    return {"belief": bool(scan_belief(text)), "quotes_rule": bool(REFERS.search(text))}


def summarize(smps: list[dict]) -> dict:
    out = {}
    for name, sel in (("all", smps), ("target", [s for s in smps if s["set"] in ("target", "hard")]),
                      ("replay", [s for s in smps if s["set"] == "replay"]),
                      ("replay_validate_off", [s for s in smps if s["set"] == "replay" and s["mode"] == "off"])):
        if not sel:
            continue
        tok = sum(len(s["completion_ids"]) for s in sel)
        out[name] = {
            "samples": len(sel),
            "kl_per_token": round(sum(s["kl_mean"] * len(s["completion_ids"]) for s in sel if "kl_mean" in s) / max(tok, 1), 4),
            "belief_rate": round(sum(s["belief"] for s in sel) / len(sel), 3),
            "quote_rate": round(sum(s["quotes_rule"] for s in sel) / len(sel), 3),
            "unclosed_think": sum(not s["think_closed"] for s in sel),
            "hit_cap": sum(s["hit_cap"] for s in sel),
            "median_tokens": sorted(len(s["completion_ids"]) for s in sel)[len(sel) // 2],
        }
    return out


def write_samples(path: Path, smps: list[dict]) -> None:
    drop = ("completion_ids", "prompt_ids", "r", "user")
    path.write_text("".join(json.dumps({k: v for k, v in s.items() if k not in drop}, ensure_ascii=False) + "\n"
                            for s in smps))


def score_and_train(trainer: Trainer, smps: list[dict], steps: int) -> list[dict]:
    cfg, roles, model = trainer.cfg, trainer.roles, trainer.model
    tc = cfg["train"]
    keep = []
    for s in smps:
        s["prompt_ids"] = roles.ids("student", s)
        if len(s["prompt_ids"]) + len(s["completion_ids"]) > tc["cutoff"]:
            s["skipped"] = "cutoff"
            continue
        s["r"] = teacher_logps(model, roles, s, tc["logits_chunk"])
        keep.append(s)
    random.Random(trainer.step).shuffle(keep)
    logs = []
    per = math.ceil(len(keep) / steps)
    for i in range(0, len(keep), per):
        logs.append(trainer.train_minibatch(keep[i:i + per]))
        print(f"  step {logs[-1]}", flush=True)
    return logs


def run_probe(sampler, probe: list[dict], k: int, max_new: int, seed: int) -> dict:
    smps = []
    for got in sampler.sample_many([(p, seed + int(p["prompt_id"][:8], 16) % 1_000_000) for p in probe], k, max_new):
        for s in got:
            s.update(scan(s)); smps.append(s)
    n = len(smps)
    return {"samples": n, "belief_rate": round(sum(s["belief"] for s in smps) / n, 3),
            "quote_rate": round(sum(s["quotes_rule"] for s in smps) / n, 3),
            "unclosed_think": sum(not s["think_closed"] for s in smps),
            "by_prompt": {p["prompt_id"]: sum(s["belief"] for s in smps if s["prompt_id"] == p["prompt_id"]) for p in probe}}


def round_prompts(cfg: dict, prompts: list[dict], rnd: int) -> list[dict]:
    """Round rnd's batch: target/hard and replay prompts, each drawn without replacement from a
    seeded shuffle (reshuffled on wrap-around), so every training prompt is used before any repeats."""
    tc = cfg["train"]
    n = tc["prompts_per_round"]
    n_rep = round(n * cfg["prompts"]["replay_share"])
    out = []
    hw = int(cfg["prompts"].get("hard_weight", 1))
    for off, names, cnt in ((0, ("target", "hard"), n - n_rep), (500, ("replay",), n_rep)):
        pool = [p for p in prompts if p["set"] in names for _ in range(hw if p["set"] == "hard" else 1)]
        start = rnd * cnt
        for j in range(start, start + cnt):
            ep, pos = divmod(j, len(pool))
            order = pool[:]
            random.Random(tc["seed"] * 1000 + off + ep).shuffle(order)
            out.append(order[pos])
    return out


def cmd_train(cfg: dict, args) -> None:
    out = cfg["_out"]
    prompts = sd.read_jsonl(out / "prompts.jsonl")
    tc, pcfg = cfg["train"], cfg.get("probe") or {}
    roles = Roles(cfg)
    done = sorted(int(d.name.split("_")[1]) for d in out.glob("round_*") if (d / "metrics.json").exists())
    last = done[-1] if done else None
    model = load_model(cfg, out / f"round_{last:03d}" / "adapter" if last is not None else None)
    trainer = Trainer(cfg, roles, model)
    sampler = VllmSampler(cfg, roles) if (cfg.get("sampler") or {}).get("url") else HfSampler(model, roles)
    if last is not None:
        trainer.load_state(out / f"round_{last:03d}")
        sampler.publish(out / f"round_{last:03d}" / "adapter", f"{cfg['run']}_r{last:03d}")
        print(f"resumed after round {last} (optimizer step {trainer.step})", flush=True)
    probe = sorted((p for p in prompts if p["set"] == "probe"), key=lambda p: p["prompt_id"])
    random.Random(tc["seed"]).shuffle(probe)
    probe = probe[:pcfg.get("n", 0)]
    if probe and last is None and not (out / "probe_000.json").exists():
        print("probe before training (round 0) ...", flush=True)
        sd.write_json(out / "probe_000.json", run_probe(sampler, probe, pcfg["k"], tc["max_new_tokens"], 7))
    first = 0 if last is None else last + 1
    rounds = args.rounds or tc["rounds"]
    for rnd in range(first, rounds):
        d = out / f"round_{rnd:03d}"
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        batch = round_prompts(cfg, prompts, rnd)
        smps = []
        jobs = [(p, tc["seed"] + rnd * 7919 + int(p["prompt_id"][:8], 16) % 1_000_000) for p in batch]
        for i, (p, got) in enumerate(zip(batch, sampler.sample_many(jobs, tc["k"], tc["max_new_tokens"])), 1):
            for s in got:
                s["user"] = p["user"]; s.update(scan(s))
            smps += got
            print(f"r{rnd} sample {i}/{len(batch)} {p['set']}/{p['task_type']}/{got[0]['mode']} "
                  f"{[s['new_tokens'] for s in got]} tok, {got[0]['gen_s']}s, belief {[int(s['belief']) for s in got]}", flush=True)
        t_s = time.monotonic() - t0
        logs = score_and_train(trainer, smps, tc["steps_per_round"])
        trainer.save(d)
        sampler.publish(d / "adapter", f"{cfg['run']}_r{rnd:03d}")
        write_samples(d / "samples.jsonl", smps)
        met = {"round": rnd, "steps": logs, "summary": summarize([s for s in smps if "kl_mean" in s]),
               "skipped_cutoff": sum(s.get("skipped") == "cutoff" for s in smps),
               "sample_min": round(t_s / 60, 1), "train_min": round((time.monotonic() - t0 - t_s) / 60, 1)}
        if probe and pcfg.get("every") and (rnd + 1) % pcfg["every"] == 0:
            met["probe"] = run_probe(sampler, probe, pcfg["k"], tc["max_new_tokens"], 7)
            sd.write_json(out / f"probe_{rnd + 1:03d}.json", met["probe"])
        sd.write_json(d / "metrics.json", met)
        print(f"== round {rnd} done: {json.dumps(met['summary'])}"
              + (f" probe belief {met['probe']['belief_rate']}" if "probe" in met else ""), flush=True)


def cmd_smoke(cfg: dict, args) -> None:
    """4 target prompts (fix/validate/generate), k=1; repeat `steps` optimizer steps on the same
    samples and require the per-token KL to fall. Writes data/opcd/<run>/smoke/."""
    out = cfg["_out"] / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    roles = Roles(cfg)
    prompts = sd.read_jsonl(cfg["_out"] / "prompts.jsonl")
    pick, want = [], [("target", "fix"), ("target", "fix"), ("target", "validate"), ("replay", "generate")]
    for st, tt in want:
        pick.append(next(p for p in prompts if p["set"] == st and p["task_type"] == tt and p not in pick))
    # what the student and the teacher see
    for p in pick[:1] + pick[2:3]:
        for role in ("student", "teacher"):
            ids = roles.ids(role, p)
            txt = roles.tok.decode(ids)
            print(f"--- {role} / {p['task_type']} ({roles.mode(p)}): {len(ids)} prompt tokens; "
                  f"rule present: {cfg['rule_marker'] in txt}; tail: {txt[-80:]!r}")
    model = load_model(cfg)
    tc = dict(cfg["train"]); tc["lr"] = args.lr or tc["lr"]
    cfg = {**cfg, "train": tc}
    trainer = Trainer(cfg, roles, model)
    smps = []
    for p in pick:
        for s in sample(model, roles, p, 1, args.max_new or tc["max_new_tokens"], 1234):
            s["user"] = p["user"]; s.update(scan(s)); smps.append(s)
            print(f"sampled {p['set']}/{p['task_type']}/{s['mode']}: {s['new_tokens']} tok in {s['gen_s']}s, "
                  f"think_closed {s['think_closed']}, belief {s['belief']}", flush=True)
    for s in smps:
        s["prompt_ids"] = roles.ids("student", s)
        s["r"] = teacher_logps(model, roles, s, tc["logits_chunk"])
    hist = []
    for i in range(args.steps):
        t0 = time.monotonic()
        lg = trainer.train_minibatch(smps)
        lg["sec"] = round(time.monotonic() - t0, 1)
        lg["per_sample_kl"] = [s["kl_mean"] for s in smps]
        hist.append(lg)
        print(f"step {i}: {lg}", flush=True)
    import torch
    write_samples(out / "samples.jsonl", smps)
    rep = {"steps": hist, "kl_fell": hist[-1]["kl_per_token"] < hist[0]["kl_per_token"],
           "finite": all(math.isfinite(h["kl_per_token"]) for h in hist),
           "peak_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 1),
           "flagged_first_sample": smps[0]["flagged"]}
    sd.write_json(out / "report.json", rep)
    trainer.save(out)
    print(json.dumps({k: v for k, v in rep.items() if k != "steps"}, indent=1, ensure_ascii=False))


def cmd_export(cfg: dict, args) -> None:
    """Merge a round's adapter into the base and save a full model test.py can load."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    adapter = Path(args.adapter) if args.adapter else cfg["_out"] / f"round_{args.round:03d}" / "adapter"
    base = AutoModelForCausalLM.from_pretrained(cfg["base_model"], dtype=torch.bfloat16, device_map={"": 0})
    model = PeftModel.from_pretrained(base, str(adapter)).merge_and_unload()
    outd = Path(args.out)
    model.save_pretrained(str(outd), max_shard_size="5GB")
    for f in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "generation_config.json"):
        if (Path(cfg["base_model"]) / f).exists():
            shutil.copy2(Path(cfg["base_model"]) / f, outd / f)
    (outd / "opcd_export.json").write_text(json.dumps({"base": cfg["base_model"], "adapter": str(adapter)}, indent=1))
    print(f"exported {adapter} -> {outd}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("prepare", "smoke", "train", "export"))
    ap.add_argument("--config", required=True)
    ap.add_argument("--rounds", type=int, help="train: stop after this many rounds (default: config)")
    ap.add_argument("--steps", type=int, default=4, help="smoke: optimizer steps on the same batch")
    ap.add_argument("--lr", type=float, help="smoke: override the learning rate")
    ap.add_argument("--max-new", type=int, help="smoke: max new tokens per sample")
    ap.add_argument("--round", type=int, help="export: round number")
    ap.add_argument("--adapter", help="export: adapter dir (instead of --round)")
    ap.add_argument("--out", help="export: output dir")
    args = ap.parse_args()
    cfg = load_cfg(args.config)
    {"prepare": lambda: cmd_prepare(cfg), "smoke": lambda: cmd_smoke(cfg, args),
     "train": lambda: cmd_train(cfg, args), "export": lambda: cmd_export(cfg, args)}[args.cmd]()


if __name__ == "__main__":
    main()
