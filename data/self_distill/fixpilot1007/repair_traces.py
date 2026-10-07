"""Minimal repairs of rb1006's own fix traces on the 27 fix-defaults prompts where every sample
held the "declared variables start null" belief (fixpilot1007). gpt-6-sol edits only the false
sentences (and what follows from them); each repaired trace then goes through the same checks as
the self-distill filter: format, library, compile, belief scan, judge, claims audit.
Writes repairs.jsonl (all attempts) in this run directory."""
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/home/pavlisd/llama_train")
import self_distill as sd  # noqa: E402

RUN = Path(__file__).resolve().parent
PER_PROMPT = 2
RETRY = "--retry" in sys.argv
P = {json.loads(l)["prompt_id"]: json.loads(l) for l in open(RUN / "prompts.jsonl")}
S = {}
for f in sorted(RUN.glob("samples.shard*.jsonl")):
    for l in open(f):
        r = json.loads(l)
        S[(r["prompt_id"], r["sample_idx"])] = r
J = [json.loads(l) for l in open(RUN / "judged.jsonl")]

DEF = re.compile(r"(epoch|empty (list|map)|uninitiali[sz]ed|declared|defaults? to|starts? (at|as|empty)|bare declaration)", re.I)


def is_default_issue(t):
    return bool(DEF.search(t) and re.search("null", t, re.I))


def issues(j):
    jd = j.get("judge") or {}
    out = []
    for k in ("missing", "false_claims", "wrong_fixes", "broken_requirements", "compile_problems"):
        out += [f"{k}: {x}" for x in jd.get(k) or []]
    if j.get("compile", {}).get("status") == "fail":
        out += [f"compile: {x}" for x in j["compile"].get("problems", [])]
    return out


# Prompts where all 4 samples hold the belief (belief scan or judge).
by_pid = defaultdict(list)
for j in J:
    if "defaults" not in P[j["prompt_id"]]["source_file"]:
        continue
    s = S[(j["prompt_id"], j["sample_idx"])]
    jd = j.get("judge") or {}
    bel = bool(sd.belief_hits(s["thinking"] + "\n" + s["answer"])) or any(
        is_default_issue(x) for x in (jd.get("false_claims") or []) + (jd.get("wrong_fixes") or []))
    by_pid[j["prompt_id"]].append((bel, j))
targets = [p for p, v in by_pid.items() if all(b for b, _ in v)]
# Per prompt, the samples with the fewest flagged issues (compile pass first).
cands = []
for p in targets:
    js = sorted((j for _, j in by_pid[p]),
                key=lambda j: (j.get("compile", {}).get("status") != "pass", len(issues(j))))
    cands += js[:PER_PROMPT]

RULE = """CTL2 rule (owner ruling, binding): a variable declared without an initializer, global or local,
starts at its type's default, never null: integer/long/decimal 0, number 0.0, boolean false,
string "", date the epoch (1970-01-01 00:00:00), lists and maps empty. Only variant, byte and
cbyte start null. Nullable input fields, unmatched slave fields, missing map keys, nullable
Rollup accumulator fields without a metadata default, and null function results ARE null."""

SYSTEM = """You copy-edit a draft (working notes plus final answer) for a CTL2 code-fix task with MINIMAL edits.
Keep the author's voice, structure, wording and length. Change only:
1. sentences that state or rely on a false claim (in particular that a declared, uninitialised
   variable starts null), and the conclusions, problem-list items, guards or initialisers that
   follow from them;
2. the other issues listed by the reviewer, if any, fixed in the same minimal way.
In the notes, replace a false claim with the correct reasoning at that point (e.g. "date prevX;
starts at the epoch, so on the first record the comparison is safe and gives ..."), in the same
style; do not add commentary about the correction. In the answer, a declaration that is not a
defect stays unchanged in the corrected code and is mentioned once after the numbered problem list
as "Left unchanged: ..." with its actual first-use value, as the reference answer does. The
corrected code must compile and satisfy the specification; use the reference answer as ground
truth for which defects are real. Everything else stays verbatim.
Return JSON only: {"thinking": "<edited notes>", "answer": "<edited answer>"}."""


def repair(j):
    p = P[j["prompt_id"]]
    s = S[(j["prompt_id"], j["sample_idx"])]
    user = (f"{RULE}\n\n=== TASK (user prompt) ===\n{p['user']}\n\n=== REFERENCE ANSWER ===\n{p['reference']}\n\n"
            f"=== REVIEWER FINDINGS ON THE DRAFT ===\n" + ("\n".join(issues(j)) or "(belief only)") +
            f"\n\n=== DRAFT NOTES ===\n{s['thinking']}\n\n=== DRAFT ANSWER ===\n{s['answer']}")
    row = {"prompt_id": j["prompt_id"], "sample_idx": j["sample_idx"], "record_id": p["record_id"],
           "original_issues": issues(j)}
    try:
        txt = judge._client()._call(SYSTEM, user, purpose="repair")
        m = re.search(r"\{.*\}", txt, re.S)
        out = json.loads(m.group(0))
        th, ans = out["thinking"].strip(), out["answer"].strip()
    except Exception as e:  # noqa: BLE001
        return {**row, "accepted": False, "stage": "repair_call", "error": repr(e)[:300]}
    row.update(thinking=th, answer=ans,
               sim_thinking=round(difflib.SequenceMatcher(None, s["thinking"], th, autojunk=False).ratio(), 3),
               sim_answer=round(difflib.SequenceMatcher(None, s["answer"], ans, autojunk=False).ratio(), 3))
    fmt = sd.format_check(p, ans)
    if fmt:
        return {**row, "accepted": False, "stage": "format", "reason": fmt}
    lib, unknown = sd.library_check(p, ans)
    if lib:
        return {**row, "accepted": False, "stage": "library", "reason": lib, "unknown": unknown}
    bh = sd.belief_hits(th + "\n" + ans)
    if bh:
        return {**row, "accepted": False, "stage": "belief", "reason": bh}
    comp = sd.compile_check(p, ans, mcp_cfg, synth)
    row["compile"] = comp
    if comp["status"] == "fail":
        return {**row, "accepted": False, "stage": "compile"}
    g = judge.grade(p, ans)
    row["judge"] = g.get("verdict")
    if not g.get("ok") or not g.get("accept"):
        return {**row, "accepted": False, "stage": "judge"}
    c = judge.check_claims(p, th, ans)
    row["claims"] = c.get("verdict")
    if not c.get("ok") or not c.get("clean"):
        return {**row, "accepted": False, "stage": "claims"}
    if row["sim_thinking"] < 0.6:
        return {**row, "accepted": False, "stage": "too_rewritten"}
    return {**row, "accepted": True}


mcp_cfg = sd.mcp_config(SimpleNamespace(mcp_url=None, no_compile=False))
sd.probe_mcp(mcp_cfg)
_, raw = sd.load_eval_config(sd.DEFAULT_EVAL_CONFIG)
judge = sd.Judge(sd.judge_config(raw))
synth = sd.MetadataSynth(RUN, judge, mcp_cfg)

if __name__ == "__main__":
    if RETRY:
        prev = [json.loads(l) for l in open(RUN / "repairs.jsonl")]
        done = {r["prompt_id"] for r in prev if r["accepted"]}
        tried = {(r["prompt_id"], r["sample_idx"]) for r in prev if r.get("stage") != "repair_call"}
        cands = [j for j in cands if j["prompt_id"] not in done and (j["prompt_id"], j["sample_idx"]) not in tried]
        print(f"retry: {len(cands)} candidates on prompts without an accepted repair", flush=True)
        with ThreadPoolExecutor(6) as pool:
            rows = list(pool.map(repair, cands))
        keep = [r for r in prev if not (r.get("stage") == "repair_call" and (r["prompt_id"], r["sample_idx"]) in {(x["prompt_id"], x["sample_idx"]) for x in rows})]
        (RUN / "repairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in keep + rows))
        print("retry results:", dict(Counter("accepted" if r["accepted"] else r["stage"] for r in rows)))
        allr = keep + rows
        print("prompts with an accepted repair:", len({r["prompt_id"] for r in allr if r["accepted"]}), "of", len(targets))
        sys.exit(0)
    print(f"targets {len(targets)} prompts, {len(cands)} candidate samples", flush=True)
    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(repair, cands))
    (RUN / "repairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows))
    st = Counter("accepted" if r["accepted"] else r["stage"] for r in rows)
    print("results:", dict(st))
    print("prompts with an accepted repair:", len({r["prompt_id"] for r in rows if r["accepted"]}), "of", len(targets))
    acc = [r for r in rows if r["accepted"]]
    if acc:
        print("similarity to original (thinking) median:", sorted(r["sim_thinking"] for r in acc)[len(acc) // 2])
