#!/home/pavlisd/venv/bin/python
"""Server probes for the facts the validate-precision teacher may state (spec/validate_precision_brief.md, Data 3).

B1-tweak's thinking-off false alarms claim that a nullable field compared or assigned without a guard "can throw", and
that decimal / integer arithmetic "truncates" or "does not compile". Each probe is one CTL2 expression evaluated in a
REFORMAT on the CloverDX server (sandbox MiscExamples, suite_v5/agent/probe/) against one input row, nulls included; the
result string or the runtime error is recorded. Only what these runs show goes into the fact sheet.

    ~/venv/bin/python scripts/validate_precision/probe_facts.py --out results/validate_precision/fact_probes.json
"""
import argparse, asyncio, json, sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import agent_harness as AH  # noqa: E402

PRE = "suite_v5/agent/probe/vp_"
IN_FIELDS = [("i", "integer"), ("l", "long"), ("d", "decimal"), ("n", "number"), ("s", "string"), ("b", "boolean"),
             ("t", "date"), ("i2", "integer")]
NULL_ROW = "|".join(["__NULL__"] * len(IN_FIELDS))
VAL_ROW = "7|7|7.50|7.5|x|true|2026-03-29 00:00:00|2"

# (name, claim probed, CTL body statements computing string `r`, input row)
PROBES = [
    ("int_gt_null", "a null integer field compared with > throws", 'r = toString($in.0.i > 5);', NULL_ROW),
    ("int_lt_null", "a null integer field compared with < throws", 'r = toString($in.0.i < 5);', NULL_ROW),
    ("int_eq_null", "a null integer field compared with == throws", 'r = toString($in.0.i == 5);', NULL_ROW),
    ("int_ne_null", "a null integer field compared with != throws", 'r = toString($in.0.i != 5);', NULL_ROW),
    ("null_vs_null_gt", "two null fields compared with >", 'r = toString($in.0.i > $in.0.i2);', NULL_ROW),
    ("dec_gt_null", "a null decimal field compared with > throws", 'r = toString($in.0.d > 5D);', NULL_ROW),
    ("date_lt_null", "a null date compared with < throws", 'r = toString($in.0.t < today());', NULL_ROW),
    ("str_eq_null", "a null string compared with == throws", 'r = toString($in.0.s == "x");', NULL_ROW),
    ("if_null_gt", "a null field in an if condition throws",
     'if ($in.0.i > 5) { r = "then"; } else { r = "else"; }', NULL_ROW),
    ("int_plus_null", "null + 1 throws", 'integer x = $in.0.i + 1; r = toString(x);', NULL_ROW),
    ("dec_plus_null", "null decimal + 1D throws", 'decimal x = $in.0.d + 1D; r = toString(x);', NULL_ROW),
    ("str_concat_null", "string + null", 'r = "a" + $in.0.s + "b";', NULL_ROW),
    ("assign_null_long_local", "a null assigned to a long local throws", 'long x = $in.0.l; r = "assigned " + toString(x);', NULL_ROW),
    ("assign_null_int_local", "a null assigned to an integer local throws", 'integer x = $in.0.i; r = "assigned " + toString(x);', NULL_ROW),
    ("assign_null_dec_local", "a null assigned to a decimal local throws", 'decimal x = $in.0.d; r = "assigned " + toString(x);', NULL_ROW),
    ("null_local_plus_one", "a local holding null, then + 1", 'integer x = $in.0.i; x = x + 1; r = toString(x);', NULL_ROW),
    ("not_null_bool", "! on a null boolean field", 'r = toString(!$in.0.b);', NULL_ROW),
    ("if_null_bool", "a null boolean field as an if condition", 'if ($in.0.b) { r = "then"; } else { r = "else"; }', NULL_ROW),
    ("assign_null_out", "a null assigned to a nullable output field", '$out.0.v = $in.0.i; r = "ok " + toString($out.0.v);', NULL_ROW),
    ("dec_div_int", "decimal divided by an integer literal truncates", 'r = toString($in.0.d / 2);', VAL_ROW),
    ("dec_div_int_typed", "decimal / integer literal stored in a decimal", 'decimal x = $in.0.d / 2; r = toString(x);', VAL_ROW),
    ("dec_gt_int_literal", "a decimal compared with an integer literal does not compile", 'r = toString($in.0.d > 7);', VAL_ROW),
    ("dec_eq_int_literal", "a decimal == an integer literal", 'r = toString($in.0.d == 7);', VAL_ROW),
    ("dec_times_int", "decimal * integer field", 'r = toString($in.0.d * $in.0.i);', VAL_ROW),
    ("int_div_int", "integer / integer", 'r = toString($in.0.i / $in.0.i2);', VAL_ROW),
    ("long_div_int", "long / integer", 'r = toString($in.0.l / 2);', VAL_ROW),
    ("num_div_int", "number / integer", 'r = toString($in.0.n / 2);', VAL_ROW),
    ("int_div_dec", "integer / decimal literal", 'r = toString($in.0.i / 2D);', VAL_ROW),
    ("ms_diff_dst", "UTC millisecond arithmetic across a DST change",
     'long a = date2long(str2date("2026-03-28 12:00:00", "yyyy-MM-dd HH:mm:ss", "en.US", "UTC")); '
     'long c = date2long(str2date("2026-03-30 12:00:00", "yyyy-MM-dd HH:mm:ss", "en.US", "UTC")); r = toString((c - a) / 3600000L);',
     VAL_ROW),
]


def graph(name, body):
    fields = "\n".join(f'        <Field name="{n}" type="{t}" nullable="true"'
                       + (' format="yyyy-MM-dd HH:mm:ss" timeZone="UTC"' if t == "date" else "")
                       + (' length="18" scale="2"' if t == "decimal" else "") + " />" for n, t in IN_FIELDS)
    ctl = ("//#CTL2\nfunction integer transform() {\n    string r = \"\";\n    " + body
           + "\n    $out.0.result = r;\n    return ALL;\n}\n")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Graph name="vp_{name}" id="vp_{name}" nature="etlGraph" revision="1.0" guiVersion="7.5.0">
  <Global>
    <Metadata id="In0">
      <Record name="ProbeIn" type="delimited" fieldDelimiter="|" recordDelimiter="\\n" nullValue="__NULL__" locale="en.US">
{fields}
      </Record>
    </Metadata>
    <Metadata id="Out0">
      <Record name="ProbeOut" type="delimited" fieldDelimiter="|" recordDelimiter="\\n" nullValue="__NULL__">
        <Field name="i" type="integer" nullable="true" />
        <Field name="v" type="integer" nullable="true" />
        <Field name="result" type="string" nullable="true" />
      </Record>
    </Metadata>
  </Global>
  <Phase number="0">
    <Node id="Reader0" type="DATA_READER" guiName="Reader0" guiX="50" guiY="200">
      <attr name="fileURL">{PRE}{name}_in.csv</attr>
      <attr name="charset">UTF-8</attr>
      <attr name="dataPolicy">strict</attr>
    </Node>
    <Node id="Test" type="REFORMAT" guiName="Test" guiX="300" guiY="200">
      <attr name="transform">{escape(ctl)}</attr>
    </Node>
    <Node id="Writer0" type="DATA_WRITER" guiName="Writer0" guiX="550" guiY="200">
      <attr name="fileURL">{PRE}{name}_out.csv</attr>
      <attr name="charset">UTF-8</attr>
      <attr name="makeDirs">true</attr>
      <attr name="createEmptyFiles">true</attr>
      <attr name="append">false</attr>
    </Node>
    <Edge id="E0" fromNode="Reader0:0" toNode="Test:0" metadata="In0" />
    <Edge id="E1" fromNode="Test:0" toNode="Writer0:0" metadata="Out0" />
  </Phase>
</Graph>
"""


async def main(a):
    out = []
    async with AH.X.streamablehttp_client(AH.MCP_URL, timeout=180) as (rd, wr, _):
        async with AH.X.ClientSession(rd, wr) as s:
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})

            async def call(n, args):
                AH.guard(n, args)
                return AH.X.payload(await s.call_tool(n, args))
            for name, claim, body, row in PROBES:
                if a.only and name not in a.only:
                    continue
                await call("sandbox_write_file", dict(sandboxCode=AH.SANDBOX, sandboxPath=f"{PRE}{name}_in.csv", content=row + "\n"))
                gp = f"{PRE}{name}.grf"
                await call("sandbox_write_file", dict(sandboxCode=AH.SANDBOX, sandboxPath=gp, content=graph(name, body)))
                rec = dict(name=name, claim=claim, ctl=body, input=row)
                valid = await call("job_validate", dict(sandboxCode=AH.SANDBOX, sandboxPath=gp, timeoutSeconds=60))
                if valid.get("overall") != "PASS":
                    rec.update(status="invalid", detail=json.dumps(valid)[:1500])
                else:
                    run = await call("job_run", dict(sandboxCode=AH.SANDBOX, sandboxPath=gp, params={}))
                    done = await call("job_await", dict(runId=run["runId"], timeoutSeconds=90))
                    rec["run_id"] = run["runId"]
                    if done.get("status") != "FINISHED_OK":
                        err = done.get("error") or {}
                        rec.update(status="runtime_error", detail=str(err.get("message"))[:1500])
                    else:
                        c = await call("sandbox_read_file", dict(sandboxCode=AH.SANDBOX, sandboxPath=f"{PRE}{name}_out.csv"))
                        text = c if isinstance(c, str) else c.get("content", c.get("text", ""))
                        rec.update(status="ok", output=text.strip())
                print(f"{name:24s} {rec['status']:14s} {rec.get('output', rec.get('detail', ''))[:200]}", flush=True)
                out.append(rec)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "results/validate_precision/fact_probes.json"))
    ap.add_argument("--only", nargs="*")
    asyncio.run(main(ap.parse_args()))
