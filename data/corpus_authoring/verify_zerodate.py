"""Verify the zeroDate() records on the CloverDX server and write the corpus files.

  1. Every code block is compiled with ctl_validate and must give its expected result (PASS, or FAIL with the expected
     message).
  2. Every block with a fixture is run in a graph built by data/suite_v5/round2/graph_harness.build. The output rows must
     match the fixture, except blocks marked "<check>!": those are DPO rejected answers that compile and must produce
     WRONG rows (a fake 1970 date, today() as the cutoff).
  3. Only if everything matches are these written:
       ctl_lora_training/sft_training_data/CTL_LoRA_zerodate_sft.json
       ctl_lora_training/sft_training_data/CTL_LoRA_DPO_zerodate.jsonl
       ctl_lora_training/sft_training_data/logs/CTL_LoRA_zerodate_validation.json (+ graphs under logs/zerodate_runtime/)

    cd ~/llama_train && ~/venv/bin/python data/corpus_authoring/verify_zerodate.py
"""
import asyncio, hashlib, json, shutil, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "data/suite_v5"), str(ROOT / "data/suite_v5/round2"), str(Path(__file__).parent)]
import graph_harness as H
import exec_score as X
import zerodate_records as Z

WORK = H.D / "zerodate_check"            # scratch graphs (under data/suite_v5 so the harness's relative paths work)
H.R = WORK; X.R = WORK
OUT = ROOT / "ctl_lora_training/sft_training_data"
TODAY = date.today().isoformat()


def args_for(check, code):
    c = Z.CHECKS[check] if check else None
    if c is None:      # compile-only block: infer from the record's metadata via the matching check
        return None
    a = dict(componentType=c["component"].lower(), code=code, inputMetadata=c["ins"], outputMetadata=c["outs"])
    if c.get("acc"):
        a["accumulatorMetadata"] = c["acc"]
    return a


COMPILE_ONLY_META = {   # metadata for blocks with no fixture
    Z.C_POL_BAD: "pol", Z.C_BADGE_BAD: "badge", Z.C_MAIL_BAD: "mail", Z.C_READ_BAD: "read", Z.C_CUTOFF_BAD: "mail",
    Z.C_READ.replace("zeroDate()", "zeroDate"): "read",
}


def manifest(check, code, label):
    c = Z.CHECKS[check.rstrip("!")]
    test = dict(test_id=label, reference=code, rubric=dict(description=f"zeroDate corpus check {label}"))
    spec = dict(component=c["component"], inputMetadata=c["ins"], outputMetadata=c["outs"], settings=c.get("settings", {}),
                resources={}, fixture=dict(inputs=c["inputs"], expected=c["expected"]))
    if c.get("acc"):
        spec["accumulatorMetadata"] = c["acc"]
    return H.build(test, spec)


async def main():
    shutil.rmtree(WORK, ignore_errors=True); WORK.mkdir(parents=True)
    blocks = [(r["id"], i, code, exp, chk) for r in Z.RECORDS for i, (code, exp, chk) in enumerate(r["blocks"])]
    blocks += [(d["id"], i, code, exp, chk) for d in Z.DPO for i, (code, exp, chk) in enumerate(d["blocks"])]
    results, ok = [], True
    async with X.streamablehttp_client("http://localhost:8083/clover/mcp/mcp", timeout=180) as (rd, wr, _):
        async with X.ClientSession(rd, wr) as s:
            await s.initialize()
            await s.call_tool("task_workflow_get", {"task": "validate_and_run"})

            async def call(n, a):
                X.guard(n, a)
                return X.payload(await s.call_tool(n, a))

            for rid, i, code, exp, chk in blocks:
                meta_check = (chk or COMPILE_ONLY_META[code]).rstrip("!")
                a = args_for(meta_check, code)
                d = (await s.call_tool("ctl_validate", a)).structuredContent or {}
                errs = [p["message"] for p in d.get("problems", []) if p.get("severity") == "ERROR"]
                want_pass = exp == "PASS"
                comp_ok = (d.get("overall") == "PASS") if want_pass else (d.get("overall") == "FAIL" and any(exp[5:] in e for e in errs))
                rec = dict(id=rid, block=i, expected=exp, compile=d.get("overall"), errors=errs, compile_ok=comp_ok)
                if chk and comp_ok:
                    label = f"zerodate_{rid.split('_')[-2]}_{rid.split('_')[-1]}_{i}"
                    m = manifest(chk, code, label)
                    for x in m["files"]:
                        if "/data-in/" in x["local"]:
                            await call("sandbox_write_file", dict(sandboxCode="MiscExamples", sandboxPath=x["remote"],
                                                                  content=(H.D / x["local"]).read_text()))
                    st, det = await X.score_one(call, m, code, label)
                    want_rows = not chk.endswith("!")
                    rec.update(runtime=st, detail=det, runtime_ok=(st == "pass") if want_rows else (st == "wrong_rows"))
                ok &= rec["compile_ok"] and rec.get("runtime_ok", True)
                results.append(rec)
                print(rid, i, exp, chk, "compile", d.get("overall"), errs[:1], rec.get("runtime"), "OK" if rec["compile_ok"] and rec.get("runtime_ok", True) else "MISMATCH", flush=True)
    print("ALL OK" if ok else "MISMATCHES", len(results), "blocks")
    if not ok:
        return
    sft = [dict(id=r["id"], messages=[dict(role="user", content=r["user"]), dict(role="assistant", content=r["assistant"])],
                reviewed_date=TODAY) for r in Z.RECORDS]
    (OUT / "CTL_LoRA_zerodate_sft.json").write_text(json.dumps(sft, indent=2, ensure_ascii=False) + "\n")
    with open(OUT / "CTL_LoRA_DPO_zerodate.jsonl", "w") as fh:
        for d in Z.DPO:
            fh.write(json.dumps(dict(prompt=d["prompt"], chosen=d["chosen"], rejected=d["rejected"], system=Z.SYSTEM,
                                     reviewed_date=TODAY), ensure_ascii=False) + "\n")
    rt = OUT / "logs/zerodate_runtime"; shutil.rmtree(rt, ignore_errors=True); shutil.copytree(WORK, rt)
    files = [dict(path=f"sft_training_data/{n}", sha256=hashlib.sha256((OUT / n).read_bytes()).hexdigest())
             for n in ("CTL_LoRA_zerodate_sft.json", "CTL_LoRA_DPO_zerodate.jsonl")]
    log = dict(reviewed_date=TODAY, status="PASS", author="llama_train session (findings §3.30 follow-up)",
               purpose="Explain zeroDate() as a function (bare name: \"Variable 'zeroDate' is not declared\"), that a declared "
                       "date already holds the epoch, and null instead of a fake 1970 date for missing values. rb1012s2 wrote "
                       "the bare name 48 times; the corpus used zeroDate() correctly but never explained it.",
               sft_count=len(sft), dpo_count=len(Z.DPO),
               sft_task_mix=dict(generate=3, fix=3, validate=3, explanation=1),
               source="llama_train/data/corpus_authoring/zerodate_records.py (records), verify_zerodate.py (this check)",
               compiler_and_runtime=results, runtime_graphs="logs/zerodate_runtime/", files=files)
    (OUT / "logs/CTL_LoRA_zerodate_validation.json").write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n")
    shutil.rmtree(WORK, ignore_errors=True)
    print("written:", [f["path"] for f in files])


asyncio.run(main())
