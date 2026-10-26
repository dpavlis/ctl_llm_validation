"""Shared pieces of the exec-RFT pilot (spec/exec_rft_pilot_brief.md): the graph harness pointed at data/exec_rft/,
MCP sessions to the CloverDX server, and a reference runner that also returns the output rows.

Graphs are built by data/suite_v5/round2/graph_harness.build and scored by data/suite_v5/exec_score.score_one, both
unchanged; only their local folders are redirected here (remote paths stay under suite_v5/ in MiscExamples, which
exec_score.guard enforces).
"""
import asyncio, json, re, sys
from contextlib import AsyncExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "data/suite_v5"), str(ROOT / "data/suite_v5/round2")]
import graph_harness as H  # noqa: E402
import exec_score as X  # noqa: E402

DATA = ROOT / "data/exec_rft"
H.D = DATA                      # manifests record local files relative to this
H.R = X.R = DATA / "graphs"     # one folder per label: graph, data-in, expected, manifest.json
H.R.mkdir(parents=True, exist_ok=True)
H.ANCHOR.setdefault("EXT_HASH_JOIN", "transform")   # SCD-2 corpus fixtures use it; the suite harness had no such test
MCP_URL = "http://localhost:8083/clover/mcp/mcp"
extract_code = X.extract_code
STATUS_ORDER = ["harness_error", "no_code", "invalid", "init_error", "runtime_error", "wrong_rows", "pass"]


def read_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def write_jsonl(p, rows):
    Path(p).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


class Server:
    """n parallel MCP sessions; `await srv.call(name, args)` uses a free one (guarded as in exec_score)."""

    def __init__(self, n=6):
        self.n = n

    async def __aenter__(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        self.stack = AsyncExitStack()
        self.free = asyncio.Queue()
        for _ in range(self.n):
            rd, wr, _ = await self.stack.enter_async_context(streamablehttp_client(MCP_URL, timeout=180))
            s = await self.stack.enter_async_context(ClientSession(rd, wr))
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})
            self.free.put_nowait(s)
        self.uploaded = set()
        return self

    async def __aexit__(self, *exc):
        await self.stack.aclose()

    async def call(self, name, args):
        X.guard(name, args)
        s = await self.free.get()
        try:
            return X.payload(await s.call_tool(name, args))
        finally:
            self.free.put_nowait(s)

    async def upload_inputs(self, m):
        for x in m["files"]:
            if "/data-in/" in x["local"] and x["remote"] not in self.uploaded:
                await self.call("sandbox_write_file", dict(sandboxCode=X.SANDBOX, sandboxPath=x["remote"],
                                                           content=(H.D / x["local"]).read_text()))
                self.uploaded.add(x["remote"])

    async def score(self, m, code, key):
        """exec_score.score_one, with harness exceptions kept apart from model errors."""
        if code is None:
            return "no_code", ""
        await self.upload_inputs(m)
        try:
            return await X.score_one(self.call, m, code, key)
        except Exception as exc:  # noqa: BLE001
            return "harness_error", str(exc)[:400]

    async def run_rows(self, m, code, key):
        """Run code in m's graph and return (status, detail, {port: normalized rows}) — the reference runner that
        records a fixture's expected output (Step 1, source 2). Mirrors exec_score.score_one."""
        await self.upload_inputs(m)
        xml, outs = X.candidate_graph(m, code, key)
        gpath = f"suite_v5/exec/graph/{key}.grf"
        await self.call("sandbox_write_file", dict(sandboxCode=X.SANDBOX, sandboxPath=gpath,
                                                   content='<?xml version="1.0" encoding="UTF-8"?>\n' + xml))
        valid = await self.call("job_validate", dict(sandboxCode=X.SANDBOX, sandboxPath=gpath, timeoutSeconds=60))
        if valid.get("overall") != "PASS":
            return "invalid", json.dumps(valid)[:600], None
        run = await self.call("job_run", dict(sandboxCode=X.SANDBOX, sandboxPath=gpath, params=m.get("parameters", {})))
        done = await self.call("job_await", dict(runId=run["runId"], timeoutSeconds=90))
        if done.get("status") != "FINISHED_OK":
            err = done.get("error") or {}
            return "runtime_error", f"run {run['runId']}: {done.get('status')} {str(err.get('message'))[:300]}", None
        rows = {}
        for port, path in m["output_paths"].items():
            content = await self.call("sandbox_read_file", dict(sandboxCode=X.SANDBOX, sandboxPath=outs.get(path, path)))
            text = content if isinstance(content, str) else content.get("content", content.get("text", ""))
            rows[port] = H.parse_actual(text, m["output_metadata"][int(port)])
        return "ok", f"run {run['runId']}", rows


def worst(statuses):
    return min(statuses, key=STATUS_ORDER.index)


# ----------------------------------------------------------------------------- prompt overlap (5-gram Jaccard)

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\sA-Za-z0-9_]")
_FIELD = re.compile(r'"name"\s*:\s*"(\w+)"|name="(\w+)"|\$(?:in|out)\.\w+\.(\w+)|\b(\w+)\s*(?::|\()\s*(?:string|integer|long|decimal|number|boolean|date)\b')


def field_names(text):
    return {g for m in _FIELD.finditer(text) for g in m.groups() if g}


def grams(text, n=5):
    """Lower-cased token 5-grams with field names (metadata names, $in/$out fields, `name:type` pairs) and every
    identifier containing '_' masked to F."""
    fields = {f.lower() for f in field_names(text)}
    toks = [("F" if (t.lower() in fields or "_" in t) else t.lower()) for t in _WORD.findall(text)]
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0
