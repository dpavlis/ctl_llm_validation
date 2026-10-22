"""Execution-based scoring of suite-v5 generate answers (review plan, 2026-10-21).

Each stored answer's CTL replaces the reference code in the test's acceptance graph
(data/suite_v5/run_graphs/<label>, built by round2/graph_harness.py), runs on the CloverDX server
(sandbox MiscExamples, under suite_v5/exec/), and its output rows are compared with the fixture's
expected rows. A test with variants (T64_*, T70_*, T71_*, T73_*) passes only if every variant passes;
expected-failure variants pass when the Test component fails at runtime.

Status per answer: pass | wrong_rows | runtime_error | init_error (CTL fails to compile at component init, e.g. $out.1
on an unconnected port) | invalid (graph validation fails) | no_code.

    python data/suite_v5/exec_score.py results/results_qwen38_v5gaps_c13c_off_*.json [--out results/exec/NAME.json]

Results go to results/exec/ (one record per answer, with run ids and the first error line); answers already scored
there are skipped, so a rerun resumes.
"""
import argparse, asyncio, hashlib, json, re, sys, xml.etree.ElementTree as E
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "round2"))
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp_batch import payload
from graph_harness import D, R, parse_actual, normalized_rows

SANDBOX = "MiscExamples"
DETAIL_LEN = 300   # characters of a server error kept in the detail (exec_retry.py raises it to feed the full message back)
TOOLS = {"task_workflow_get", "sandbox_write_file", "sandbox_read_file", "job_validate", "job_run", "job_await"}


def guard(name, args):
    """Scope (current server API: sandboxPath includes the file name): only suite_v5/ in MiscExamples."""
    assert name in TOOLS, name
    if "sandboxCode" in args:
        path = args["sandboxPath"]
        assert args["sandboxCode"] == SANDBOX and path.startswith("suite_v5/") and ".." not in Path(path).parts, args
MANIFESTS = {}
for p in sorted(R.glob("*/manifest.json")):
    m = json.loads(p.read_text())
    if m["test_id"].startswith("T"):
        MANIFESTS.setdefault(m["test_id"], []).append(m)


def extract_code(answer):
    """The last fenced block that defines a CTL function; the header is added when missing."""
    answer = (answer or "").split("</think>")[-1]
    blocks = [b for b in re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", answer, re.S) if re.search(r"\bfunction\s+\w+", b)]
    if not blocks:
        return None
    code = blocks[-1].strip()
    return code if code.startswith("//#CTL2") else "//#CTL2\n" + code


def candidate_graph(m, code, key):
    """The label's acceptance graph with the Test node's CTL replaced and outputs redirected under suite_v5/exec/."""
    root = E.parse(R / m["label"] / "graph" / Path(m["graph_file"]).name).getroot()
    test = root.find(".//Node[@id='Test']")
    attrs = [a for a in test.findall("attr") if (a.text or "").lstrip().startswith("//#CTL2")]
    assert len(attrs) == 1, (m["label"], [a.get("name") for a in test.findall("attr")])
    attrs[0].text = code
    outs = {}
    for a in root.iter("attr"):
        if a.get("name") == "fileURL" and (a.text or "").startswith("suite_v5/data-out/"):
            new = f"suite_v5/exec/out/{key}_{Path(a.text).name}"
            outs[a.text] = new
            a.text = new
    return E.tostring(root, encoding="unicode"), outs


async def score_one(call, m, code, key):
    """Run one variant; returns (status, detail)."""
    xml, outs = candidate_graph(m, code, key)
    gpath = f"suite_v5/exec/graph/{key}.grf"
    await call("sandbox_write_file", dict(sandboxCode=SANDBOX, sandboxPath=gpath,
                                          content='<?xml version="1.0" encoding="UTF-8"?>\n' + xml))
    valid = await call("job_validate", dict(sandboxCode=SANDBOX, sandboxPath=gpath, timeoutSeconds=60))
    if valid.get("overall") != "PASS":
        return "invalid", json.dumps(valid)[:2 * DETAIL_LEN]
    run = await call("job_run", dict(sandboxCode=SANDBOX, sandboxPath=gpath, params=m.get("parameters", {})))
    rid = run["runId"]
    done = await call("job_await", dict(runId=rid, timeoutSeconds=90))
    err = done.get("error") or {}
    if m["expected_failure"]:
        ok = done.get("status") == "ERROR" and err.get("componentId") == "Test" and "initialization failed" not in err.get("message", "").lower()
        return ("pass" if ok else "wrong_rows"), f"run {rid}: expected failure, got {done.get('status')} {str(err.get('message'))[:200]}"
    if done.get("status") != "FINISHED_OK":
        if "initialization failed" in str(err.get("message", "")).lower():   # CTL compiled in the component at init: e.g. $out.1 on an unconnected port
            return "init_error", f"run {rid}: {err.get('componentId')} {str(err.get('message'))[:DETAIL_LEN]}"
        return "runtime_error", f"run {rid}: {done.get('status')} {err.get('componentId')} {str(err.get('message'))[:DETAIL_LEN]}"
    bad = []
    for port, path in m["output_paths"].items():
        content = await call("sandbox_read_file", dict(sandboxCode=SANDBOX, sandboxPath=outs.get(path, path)))
        text = content if isinstance(content, str) else content.get("content", content.get("text", ""))
        meta = m["output_metadata"][int(port)]
        try:
            actual = parse_actual(text, meta)
        except Exception as exc:  # noqa: BLE001 — unparsable output counts as wrong rows
            bad.append(f"port {port}: unparsable output ({exc})"); continue
        expected = normalized_rows(m["fixture"]["expected"].get(port, []), meta)
        if actual != expected:
            first = next((i for i in range(max(len(actual), len(expected)))
                          if i >= len(actual) or i >= len(expected) or actual[i] != expected[i]), None)
            bad.append(f"port {port}: {len(actual)} rows vs {len(expected)} expected; first diff at row {first}")
    return ("wrong_rows" if bad else "pass"), f"run {rid}: " + ("; ".join(bad) or "rows match")


async def main(files, out):
    done = {}
    if out.exists():
        done = {(r["results_file"], r["test_id"], r["run"]): r for r in json.loads(out.read_text())}
    async with streamablehttp_client("http://localhost:8083/clover/mcp/mcp", timeout=180) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})

            async def call(name, args):
                guard(name, args)
                return payload(await s.call_tool(name, args))

            uploaded = set()
            for f in files:
                for t in json.loads(Path(f).read_text())["tests"]:
                    tid = t["test_id"]
                    if tid not in MANIFESTS or (Path(f).name, tid, t["run"]) in done:
                        continue
                    rec = dict(results_file=Path(f).name, test_id=tid, run=t["run"], judge_score=t.get("numeric_score"), variants={})
                    code = extract_code(t.get("mut_response"))
                    if code is None:
                        rec["status"] = "no_code"
                    else:
                        rec["code_sha"] = hashlib.sha256(code.encode()).hexdigest()[:12]
                        for m in MANIFESTS[tid]:
                            for x in m["files"]:
                                if "/data-in/" in x["local"] and x["remote"] not in uploaded:
                                    pth = Path(x["remote"])
                                    await call("sandbox_write_file", dict(sandboxCode=SANDBOX, sandboxPath=str(pth),
                                                                          content=(D / x["local"]).read_text()))
                                    uploaded.add(x["remote"])
                            key = f"{m['label']}_{rec['code_sha']}"
                            try:
                                st, det = await score_one(call, m, code, key)
                            except Exception as exc:  # noqa: BLE001 — harness error, kept apart from model errors
                                st, det = "harness_error", str(exc)[:400]
                            rec["variants"][m["label"]] = dict(status=st, detail=det)
                        order = ["harness_error", "invalid", "init_error", "runtime_error", "wrong_rows", "pass"]
                        rec["status"] = min((v["status"] for v in rec["variants"].values()), key=order.index)
                    done[(rec["results_file"], tid, t["run"])] = rec
                    out.write_text(json.dumps(list(done.values()), indent=1, ensure_ascii=False) + "\n")
                    print(rec["results_file"][:60], tid, t["run"], rec["status"], f"judge {rec['judge_score']}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+")
    ap.add_argument("--out", type=Path, default=Path("results/exec/exec_scores.json"))
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(a.results, a.out))
