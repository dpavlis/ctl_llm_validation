"""Acceptance pass on the targeted DPO repairs (spec/dpo_targeted_repairs_spec.md, Internal tracking):
format, library, compile (MCP, both sides for fix), belief scan, then one gpt-6-sol reference judgement and
claims audit on the chosen side. Writes data/self_distill/dporep/acceptance.jsonl."""
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

sys.path.insert(0, "/home/pavlisd/llama_train")
import self_distill as sd  # noqa: E402

D = sd.REPO_ROOT / "ctl_lora_training" / "sft_training_data"
OUT = sd.RUNS_DIR / "dporep"
OUT.mkdir(exist_ok=True)
cand = {json.loads(l)["id"]: json.loads(l) for l in open(D / "CTL_LoRAT_DPO_repair_candidates.jsonl")}
import os
pairs = [json.loads(l) for l in open(D / os.environ.get("PAIRS", "CTL_LoRAT_DPO_targeted_repairs.jsonl"))]
if os.environ.get("IDS"):
    keep = set(open(os.environ["IDS"]).read().split())
    pairs = [p for p in pairs if p["id"] in keep]
print(len(pairs), "pairs")

prompts, synths = {}, {}
mcp_cfg = sd.mcp_config(SimpleNamespace(mcp_url=None, no_compile=False))
sd.probe_mcp(mcp_cfg)
_, raw = sd.load_eval_config(sd.DEFAULT_EVAL_CONFIG)
judge = sd.Judge(sd.judge_config(raw))
for p in pairs:
    run = cand[p["candidate_id"]]["run"]
    if run not in synths:
        synths[run] = sd.MetadataSynth(sd.RUNS_DIR / run, judge, mcp_cfg)
        for q in sd.load_prompts(sd.RUNS_DIR / run):
            prompts.setdefault((run, q["prompt_id"]), q)


def check(p):
    c = cand[p["candidate_id"]]
    q = prompts[(c["run"], p["prompt_id"])]
    ans = p["chosen_answer"]
    row = {"id": p["id"], "group": p["group"], "prompt_id": p["prompt_id"]}
    row["format"] = sd.format_check(q, ans) or "ok"
    lib, unknown = sd.library_check(q, ans)
    row["library"] = lib or "ok"
    row["unknown"] = unknown
    row["beliefs"] = sd.belief_hits(ans)
    if q["task_type"] != "validate":
        row["compile_chosen"] = sd.compile_check(q, ans, mcp_cfg, synths[c["run"]])
        row["compile_rejected"] = c.get("compile")
    g = judge.grade(q, ans)
    row["judge"] = g
    row["claims"] = judge.check_claims(q, p["chosen_reasoning_content"], ans) if g.get("ok") else None
    return row


with ThreadPoolExecutor(8) as pool:
    rows = list(pool.map(check, pairs))
(OUT / os.environ.get("OUTNAME", "acceptance.jsonl")).write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows))
s = Counter()
for r in rows:
    s["format " + r["format"]] += 1
    s["library " + r["library"]] += 1
    if r["beliefs"]:
        s["belief hit"] += 1
    if "compile_chosen" in r:
        s["compile " + r["compile_chosen"]["status"]] += 1
    s["judge accept" if r["judge"].get("accept") else ("judge error" if not r["judge"].get("ok") else "judge reject")] += 1
    if r["claims"] is not None:
        s["claims clean" if r["claims"].get("clean") else "claims flagged"] += 1
print(json.dumps(dict(sorted(s.items())), indent=1), "judge tokens", judge.total_tokens())
