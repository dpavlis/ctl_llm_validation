"""Re-judge the stored answers of a test.py results file against another suite snapshot
(suite JSON + the ctl2-basics.md beside it), with the judge from an eval config. Only the judge
changes: the MUT answers are reused, so the delta is the judge/reference effect alone.

    python data/rejudge_results.py <results.json> <suite.json> <eval_config.yaml> [--workers 8]

Writes <results>_rejudged_<snapshot-dir-name>.json next to the input, with test.py's aggregates.
"""
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test as T
import yaml

ap = argparse.ArgumentParser()
ap.add_argument("results"); ap.add_argument("suite"); ap.add_argument("eval_config")
ap.add_argument("--workers", type=int, default=8)
ap.add_argument("--only-failed", action="store_true", help="re-judge only runs whose judge output failed to parse")
a = ap.parse_args()
suite = json.load(open(a.suite))
ref = (Path(a.suite).parent / "ctl2-basics.md").read_text()
system = T.build_judge_system_prompt(suite["judge_system_prompt"], suite["judge_instructions"], ref)
tests = {t["test_id"]: t for t in suite["tests"]}
jcfg = yaml.safe_load(open(a.eval_config))["judge"]
jcfg = {k: v for k, v in jcfg.items() if k != "api_key"}
client = T.OpenAIJudgeClient(jcfg)
res = json.load(open(a.results))

def parse_failed(r):
    return "parse failure" in (str(r.get("critical_failure")) + str((r.get("judge_result") or {}).get("notes"))).lower()


def rejudge(r):
    r = dict(r)
    if not r.get("mut_response"):           # MUT failure: nothing to judge, keep as is
        return r
    if a.only_failed and not parse_failed(r):
        return r
    t = tests[r["test_id"]]
    try:
        raw = T._call_judge_with_retry(client, system, T.build_judge_user_message(t, r["mut_response"]))
    except Exception as exc:  # noqa: BLE001
        raw = None; print("judge error", r["test_id"], exc, flush=True)
    if raw is None:
        r.update(judge_result={"verdict": "ERROR", "findings": []}, numeric_score=0.0,
                 critical_failure="Judge JSON parse failure (rejudge)", judge_fp_count=0)
        return r
    try:
        jr = T.JudgeResponse(**raw).model_dump() if T._HAVE_PYDANTIC else raw
    except Exception:  # noqa: BLE001 — same fallback as test.py
        jr = raw
    r.update(judge_result=jr, numeric_score=T.compute_numeric_score(jr, t),
             critical_failure=T.detect_critical_failure(jr, t),
             judge_fp_count=sum(1 for i in (jr.get("false_positives_triggered") or []) if i.get("triggered")))
    return r

runs = list(ThreadPoolExecutor(a.workers).map(rejudge, res["tests"]))
rw = {k for k, t in tests.items() if t.get("group") == "rw"}   # suite v5 real-world tests, scored apart as in test.py
def mean(ty):
    s = [r["numeric_score"] for r in runs if r["test_id"] not in rw and
         ((ty is None and r.get("test_type") in ("generate", "validate")) or r.get("test_type") == ty)]
    return round(sum(s) / len(s), 4) if s else None
s_rw = [r["numeric_score"] for r in runs if r["test_id"] in rw]
out = dict(res, tests=runs, suite_score=mean(None), generate_score=mean("generate"),
           validate_score=mean("validate"), fix_score=mean("fix"),
           generate_rw_score=round(sum(s_rw) / len(s_rw), 4) if s_rw else None,
           rejudged={"from": a.results, "suite": a.suite, "judge": jcfg.get("model")})
p = Path(a.results).with_name(Path(a.results).stem + f"_rejudged_{Path(a.suite).parent.name}.json")
json.dump(out, open(p, "w"), indent=2)
errs = sum(1 for r in runs if "rejudge" in str(r.get("critical_failure")))
print(f"{p.name}: suite {out['suite_score']} gen {out['generate_score']} val {out['validate_score']} fix {out['fix_score']} rw {out['generate_rw_score']} "
      f"(was {res.get('suite_score')}/{res.get('generate_score')}/{res.get('validate_score')}/{res.get('fix_score')}), judge errors {errs}")
