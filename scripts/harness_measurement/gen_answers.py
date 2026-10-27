#!/home/pavlisd/venv/bin/python
"""Sample validate answers for the ground-truth records (make_mutants.py, corpus_validate.py) from a vLLM server.

Same request as the agentic harness and the suite's validate settings: the suite system prompt, temperature 0.4,
top_p 0.95, top_k 20, reasoning_effort medium in thinking mode. One line per (record, run, mode); a rerun resumes.

    ~/venv/bin/python scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants.jsonl \
        data/agent_harness/validate_corpus.jsonl --model c13c --url http://127.0.0.1:3031 --modes off on --runs 2 \
        --out results/agent_harness/validate_gt_c13c.jsonl [--load-adapter data/opcd/c13c/round_015]
"""
import argparse, asyncio, json, sys, time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ("You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean "
          "the same language.\nHelp users write, debug, and explain CTL2 code and related concepts. Provide working code, "
          "explanation, or both as needed.\nPrefer correct, practical, minimal solutions.")
SAMPLING = dict(temperature=0.4, top_p=0.95, top_k=20)
# --format: the suite-v5 validate tests' own system prompt (SYSTEM + the ISSUES / SUGGESTIONS / VERDICT format). test.py's
# eval configs override it with the plain SYSTEM, so the plain run matches the evaluation path and --format is the
# parser-readable condition (thinking-on answers are mostly untagged prose without it).
FORMAT = ("\n\nOutput format:\n\nISSUES:\n  [severity] Description   (severity is ERROR, WARNING, or INFO)\n  ...\n\n"
          "SUGGESTIONS:\n  - Optional improvement hints (omit section if none)\n\nVERDICT: PASS | FAIL\n"
          "  (FAIL if any ERROR-severity issue is found; PASS otherwise)\n\nIf no issues are found respond with just:\n"
          "  ISSUES: none\n  VERDICT: PASS")


async def main(a):
    recs = [json.loads(l) for f in a.records for l in Path(f).read_text().splitlines() if l.strip()]
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {(r["id"], r["run"], r["mode"]) for r in map(json.loads, out.read_text().splitlines()) if r.get("answer") is not None}
    todo = [(r, run, mode) for mode in a.modes for run in range(1, a.runs + 1) for r in recs if (r["id"], run, mode) not in done]
    print(len(todo), "to do,", len(done), "done", flush=True)
    sem, lock = asyncio.Semaphore(a.concurrency), asyncio.Lock()
    async with httpx.AsyncClient() as client:
        if a.load_adapter:
            r = await client.post(f"{a.url}/v1/load_lora_adapter", json=dict(lora_name=a.model, lora_path=str(Path(a.load_adapter).resolve())),
                                  timeout=300)
            print("load adapter:", r.status_code, r.text[:120], flush=True)
        n = 0

        async def one(rec, run, mode):
            nonlocal n
            async with sem:
                body = dict(model=a.model, max_tokens=a.max_tokens, **SAMPLING,
                            messages=[{"role": "system", "content": (rec.get("system") or SYSTEM) + (FORMAT if a.format else "")},
                                      {"role": "user", "content": rec["prompt"]}],
                            chat_template_kwargs={"enable_thinking": mode == "on", "reasoning_effort": "medium"})
                t0 = time.monotonic()
                row = dict(id=rec["id"], run=run, mode=mode, model=a.model)
                for attempt in range(3):
                    try:
                        r = await client.post(f"{a.url}/v1/chat/completions", json=body, timeout=1800)
                        r.raise_for_status()
                        j = r.json(); msg = j["choices"][0]["message"]
                        text = msg.get("content") or ""
                        think = msg.get("reasoning_content") or (text.split("</think>")[0] if "</think>" in text else "")
                        row.update(answer=text.split("</think>")[-1], think_chars=len(think or ""),
                                   completion_tokens=j.get("usage", {}).get("completion_tokens"),
                                   finish=j["choices"][0].get("finish_reason"))
                        break
                    except Exception as exc:  # noqa: BLE001
                        row["error"] = str(exc)[:300]
                        await asyncio.sleep(5)
                row["seconds"] = round(time.monotonic() - t0, 1)
                async with lock:
                    with open(out, "a") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n += 1
                    if n % 50 == 0:
                        print(f"{n}/{len(todo)}", flush=True)

        await asyncio.gather(*(one(*x) for x in todo))
    print("done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("records", nargs="+")
    ap.add_argument("--model", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--load-adapter")
    ap.add_argument("--modes", nargs="+", default=["off", "on"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--concurrency", type=int, default=48)
    ap.add_argument("--format", action="store_true", help="append the suite's validate output-format instruction")
    ap.add_argument("--out", required=True)
    asyncio.run(main(ap.parse_args()))
