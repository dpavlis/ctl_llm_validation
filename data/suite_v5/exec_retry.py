"""Compile-and-retry experiment (2026-10-22): how much of a model's failing generate code would an agent that runs its graph
and reads the server error recover?

For each stored suite-v5 answer that exec_score.py marked init_error / runtime_error / invalid (failures the agent can see;
wrong_rows needs the expected output and is left out), the server's full error message is sent back to the same model
(same thinking mode and system prompt, the original answer as the assistant turn), and the corrected code is
execution-scored again. Up to ROUNDS rounds; a round that compiles and runs but gives wrong rows ends the loop.

    python data/suite_v5/exec_retry.py --model c13c_r015 --url http://127.0.0.1:3012 \
        --scores results/exec/exec_scores.json --files results/results_qwen38_v5gaps_c13c_*.json \
        --out results/exec/retry_c13c.json

Needs the model on vLLM and the CloverDX server on :8083.
"""
import argparse, asyncio, json, re, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent))
import exec_score as X

X.DETAIL_LEN = 3000
VISIBLE = {"init_error", "runtime_error", "invalid"}
FEEDBACK = ("I ran this in a CloverDX graph and it failed:\n\n{error}\n\n"
            "Fix the code and give the complete corrected version.")


def error_text(detail):
    return re.sub(r"^run \d+: ", "", detail).strip()


async def run_variants(call, tid, code, tag):
    """Score code on every variant of the test; returns (overall status, first visible error or None)."""
    order = ["harness_error", "invalid", "init_error", "runtime_error", "wrong_rows", "pass"]
    worst, err = "pass", None
    for m in X.MANIFESTS[tid]:
        try:
            st, det = await X.score_one(call, m, code, f"{m['label']}_{tag}")
        except Exception as exc:  # noqa: BLE001
            st, det = "harness_error", str(exc)[:400]
        if order.index(st) < order.index(worst):
            worst = st
        if st in VISIBLE and err is None:
            err = error_text(det)
    return worst, err


async def ask(client, url, model, messages, think, sampling):
    body = dict(model=model, messages=messages,   # no max_tokens: vLLM uses the rest of the context (16k)
                temperature=sampling.get("temperature", 0.4), top_p=sampling.get("top_p", 0.95),
                top_k=sampling.get("top_k", 20),
                chat_template_kwargs={"enable_thinking": think, "reasoning_effort": "medium"})
    r = await client.post(f"{url}/v1/chat/completions", json=body, timeout=900)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    return msg.get("content") or ""


async def main(a):
    scores = {(r["results_file"], r["test_id"], r["run"]): r for r in json.loads(Path(a.scores).read_text())}
    done = {}
    out = Path(a.out)
    if out.exists():
        done = {(r["results_file"], r["test_id"], r["run"]): r for r in json.loads(out.read_text())
                if not any(x["status"] == "model_error" for x in r["rounds"])}   # retry requests that failed
    todo = []
    for f in a.files:
        think = "_on_" in Path(f).name
        for t in json.loads(Path(f).read_text())["tests"]:
            k = (Path(f).name, t["test_id"], t["run"])
            if k in scores and scores[k]["status"] in VISIBLE and k not in done:
                todo.append((k, t, think))
    print(len(todo), "failing answers with a visible error", flush=True)
    sem = asyncio.Semaphore(a.concurrency)
    async with X.streamablehttp_client("http://localhost:8083/clover/mcp/mcp", timeout=180) as (rd, wr, _), \
            httpx.AsyncClient() as client:
        async with X.ClientSession(rd, wr) as s:
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})
            lock = asyncio.Lock()   # one MCP session: serialize server calls, overlap the model calls

            async def call(name, args):
                X.guard(name, args)
                async with lock:
                    return X.payload(await s.call_tool(name, args))

            uploaded = set()   # input fixtures for every test
            for tid, ms in X.MANIFESTS.items():
                for m in ms:
                    for x in m["files"]:
                        if "/data-in/" in x["local"] and x["remote"] not in uploaded:
                            await call("sandbox_write_file", dict(sandboxCode=X.SANDBOX, sandboxPath=x["remote"],
                                                                  content=(X.D / x["local"]).read_text()))
                            uploaded.add(x["remote"])

            async def one(k, t, think):
                async with sem:
                    tid = t["test_id"]
                    code = X.extract_code(t["mut_response"])
                    st, err = await run_variants(call, tid, code, f"r0_{abs(hash(code)) % 10**10}")
                    rec = dict(results_file=k[0], test_id=tid, run=k[2], thinking=think, original=st, rounds=[])
                    msgs = [{"role": "system", "content": t["mut_system_prompt"]},
                            {"role": "user", "content": t["mut_user_message"]},
                            {"role": "assistant", "content": t["mut_response"]}]
                    for rnd in range(1, a.rounds + 1):
                        if err is None:
                            break
                        msgs.append({"role": "user", "content": FEEDBACK.format(error=err)})
                        try:
                            reply = await ask(client, a.url, a.model, msgs, think, t.get("mut_sampling") or {})
                        except Exception as exc:  # noqa: BLE001
                            rec["rounds"].append(dict(status="model_error", error=str(exc)[:300])); break
                        msgs.append({"role": "assistant", "content": reply.split("</think>")[-1]})
                        new = X.extract_code(reply)
                        if new is None:
                            rec["rounds"].append(dict(status="no_code")); break
                        st, err = await run_variants(call, tid, new, f"r{rnd}_{abs(hash(new)) % 10**10}")
                        rec["rounds"].append(dict(status=st, error=(err or "")[:400]))
                    rec["final"] = rec["rounds"][-1]["status"] if rec["rounds"] else st
                    done[k] = rec
                    out.write_text(json.dumps(list(done.values()), indent=1, ensure_ascii=False) + "\n")
                    print(k[0][:40], tid, k[2], rec["original"], "->", [r["status"] for r in rec["rounds"]], flush=True)

            await asyncio.gather(*(one(k, t, th) for k, t, th in todo))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:3012")
    ap.add_argument("--scores", default="results/exec/exec_scores.json")
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=8)
    asyncio.run(main(ap.parse_args()))
