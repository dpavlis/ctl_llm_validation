"""Step 2 of the exec-RFT pilot: sample k answers per pool prompt from a served adapter and execution-score each one.

Prompts are tokenized by opcd.Roles (the suite's per-task system prompt, chat template and thinking flag, exactly as
OPCD and test.py build them); sampling uses the suite's per-task settings (T 0.4, top_p 0.95, top_k 20, no penalties)
and no fixed max_tokens: each request may fill the server's context (16384) minus its prompt. Every answer's last CTL
block is run in its prompt's graph (exec_score.score_one); identical code for the same prompt is run once.

    ~/venv/bin/python scripts/exec_rft/sample_score.py --mode off --adapter c13c --urls http://127.0.0.1:3011,http://127.0.0.1:3012 \
        --prompts data/exec_rft/pool.jsonl data/exec_rft/holdout.jsonl --out results/exec_rft/samples_off.jsonl

Output (one line per sample): prompt id, sample index, mode, thinking, answer, status, detail, completion_ids,
new_tokens, hit_cap. A rerun resumes: prompts already complete in --out are skipped.
"""
import argparse, asyncio, hashlib, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

sys.path.insert(0, str(C.ROOT))
import opcd  # noqa: E402

MAX_LEN = 16384


def sample_prompt(roles, p, url, adapter, k, seed):
    import requests
    s = roles.sampling(p)
    ids = roles.ids("student", p)
    t0 = time.monotonic()
    r = requests.post(f"{url}/v1/completions", timeout=7200, json={
        "model": adapter, "prompt": ids, "max_tokens": MAX_LEN - len(ids), "n": k, "seed": seed,
        "temperature": s["temperature"], "top_p": s["top_p"], "top_k": s["top_k"],
        "repetition_penalty": s["repetition_penalty"], "stop_token_ids": opcd.stop_ids(roles.tok),
        "return_token_ids": True, "skip_special_tokens": False})
    r.raise_for_status()
    el = time.monotonic() - t0
    ch = sorted(r.json()["choices"], key=lambda c: c["index"])
    return [opcd.make_sample(roles, p, i, list(c["token_ids"]), c["finish_reason"] == "length", el) for i, c in enumerate(ch)]


async def main(a):
    cfg = opcd.load_cfg(a.config)
    roles = opcd.Roles(cfg)
    prompts = [r for f in a.prompts for r in C.read_jsonl(f)]
    for p in prompts:
        p.update(prompt_id=p["id"], task_type=p["task"], user=p["prompt"], mode=a.mode, set="exec")
    print("sampling:", {t: {k: v for k, v in opcd.sd.sampling_for(roles.mut["student", a.mode], t).items() if k != "system_prompt"}
                        for t in ("generate", "fix")}, flush=True)
    out = Path(a.out)
    done = {}
    if out.exists():
        for r in C.read_jsonl(out):
            done.setdefault(r["prompt_id"], []).append(r)
    todo = [p for p in prompts if len(done.get(p["id"], [])) < a.k]
    print(f"{len(prompts)} prompts, {len(todo)} to sample, mode {a.mode}, k {a.k}", flush=True)
    urls = a.urls.split(",")
    loop = asyncio.get_running_loop()
    ex = ThreadPoolExecutor(a.concurrency)
    fh = open(out, "a")
    async with C.Server(a.sessions) as srv:
        async def one(j, p):
            seed = a.seed + int(hashlib.sha256(p["id"].encode()).hexdigest()[:8], 16) % 1_000_000
            smps = await loop.run_in_executor(ex, sample_prompt, roles, p, urls[j % len(urls)], a.adapter, a.k, seed)
            cache = {}
            for s in smps:
                code = C.extract_code(s["answer"]) if s["think_closed"] else None
                sha = hashlib.sha256(code.encode()).hexdigest()[:10] if code else None
                if sha not in cache:
                    key = f"rft_{a.tag}_{a.mode}_{p['id'][4:]}_{sha}"
                    cache[sha] = await srv.score(p["manifest"], code, key) if code else ("no_code", "unclosed thinking" if not s["think_closed"] else "")
                s["status"], s["detail"] = cache[sha]
                s["code_sha"] = sha
                fh.write(json.dumps({k: v for k, v in s.items() if k not in ("raw", "teacher", "set")}, ensure_ascii=False) + "\n")
            fh.flush()
            print(p["id"], a.mode, [s["status"][:4] for s in smps], [s["new_tokens"] for s in smps], flush=True)

        sem = asyncio.Semaphore(a.concurrency)

        async def guarded(j, p):
            async with sem:
                try:
                    await one(j, p)
                except Exception as exc:  # noqa: BLE001 — a failed request is retried by a rerun
                    print("ERROR", p["id"], repr(exc)[:300], flush=True)
        await asyncio.gather(*(guarded(j, p) for j, p in enumerate(todo)))
    fh.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("on", "off"), required=True)
    ap.add_argument("--adapter", required=True, help="served model or LoRA name, e.g. c13c")
    ap.add_argument("--tag", default="c13c", help="key prefix of the scored graphs")
    ap.add_argument("--urls", default="http://127.0.0.1:3011,http://127.0.0.1:3012")
    ap.add_argument("--prompts", nargs="+", default=["data/exec_rft/pool.jsonl", "data/exec_rft/holdout.jsonl"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default="configs/opcd_c13c.yaml", help="opcd config: student prompts/tokenizer")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=24, help="prompts in flight (each asks for k samples)")
    ap.add_argument("--sessions", type=int, default=6, help="parallel MCP sessions for scoring")
    asyncio.run(main(ap.parse_args()))
