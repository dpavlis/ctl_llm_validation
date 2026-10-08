"""dpodef1 pairs (spec/thinking_dpo_defaults_plan.md, steps 3-4).

Labels every judged sample (belief / clean-accepted / other), repairs belief samples of the TRAIN split
with minimal gpt-6-sol edits (re-checked like the self-distill filter), and builds thinking-on DPO pairs:
  A natural  chosen = clean-accepted sample, rejected = belief sample of the same prompt
  B repair   chosen = minimal repair of the rejected belief sample
  C contrast chosen = clean-accepted sample, rejected = sample that calls a REAL null safe
At most 2 pairs per prompt, both sides close </think>, chosen/rejected length ratio within 0.7-1.4.

  python build_pairs.py label      # stats only
  python build_pairs.py repair     # repairs (cached in repairs.jsonl; pilot repairs reused)
  python build_pairs.py pairs      # write pairs.jsonl, dpodef1_train.jsonl, report.json
"""
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
PILOT = sd.RUNS_DIR / "fixpilot1007"
P = {json.loads(l)["prompt_id"]: json.loads(l) for l in open(RUN / "prompts.jsonl")}
S = sd.load_samples(RUN)
J = {k: v for k, v in sd.load_judged(RUN).items() if k[0] in P}
EXTRA = sd.RUNS_DIR / "dpodef1x"  # 4 extra samples (seed 1) on the train prompts with belief samples
if (EXTRA / "judged.jsonl").exists():
    for (pid, i), v in sd.load_samples(EXTRA).items():
        S[(pid, i + 4)] = {**v, "sample_idx": i + 4}
    for (pid, i), v in sd.load_judged(EXTRA).items():
        if pid in P:
            J[(pid, i + 4)] = {**v, "sample_idx": i + 4}
VERSION = 2 if "--v2" in sys.argv else 1

BELIEF = sd.KNOWN_FALSE_BELIEFS["declared variables start null"]
DEF = re.compile(r"(epoch|empty (list|map)|uninitiali[sz]ed|declared|defaults? to|starts? (at|as|empty)|bare declaration)", re.I)
REALNULL = re.compile(r"(variant|byte|cbyte|nullable|accumulator|map key|missing key|slave|unmatched)", re.I)
SAFE = re.compile(r"(not null|never null|cannot be null|can't be null|is safe|no null|non-null)", re.I)


def judge_texts(j):
    jd = j.get("judge") or {}
    return (jd.get("false_claims") or []) + (jd.get("wrong_fixes") or [])


def label(key):
    s, j = S[key], J.get(key)
    text = (s.get("thinking") or "") + "\n" + (s.get("answer") or "")
    jt = judge_texts(j) if j else []
    belief = bool(BELIEF.search(text)) or any(DEF.search(t) and re.search("null", t, re.I) for t in jt)
    realnull_safe = any(REALNULL.search(t) and SAFE.search(t) for t in jt)
    ok = bool(j and j.get("accepted")) and s.get("think_closed")
    if belief:
        return "belief"
    if realnull_safe:
        return "realnull_safe"
    return "clean" if ok else "other"


LAB = {k: label(k) for k in S if k in J}


def stats():
    c = Counter()
    for (pid, _), l in LAB.items():
        c[P[pid]["split"], l] += 1
    per = defaultdict(Counter)
    for (pid, _), l in LAB.items():
        per[pid][l] += 1
    tr = [p for p in per if P[p]["split"] == "train"]
    print("labels:", dict(sorted(c.items())))
    print("train prompts:", len(tr), "| with belief:", sum(1 for p in tr if per[p]["belief"]),
          "| with clean+belief (natural pair):", sum(1 for p in tr if per[p]["belief"] and per[p]["clean"]),
          "| with realnull_safe:", sum(1 for p in tr if per[p]["realnull_safe"]))
    pr = [p for p in per if P[p]["split"] == "probe"]
    nb = sum(per[p]["belief"] for p in pr); nt = sum(sum(per[p].values()) for p in pr)
    print(f"probe base belief rate: {nb}/{nt} = {nb / max(nt, 1):.1%}")
    return per


# ---------------------------------------------------------------- repairs
RULE = """CTL2 rule (owner ruling, binding): a variable declared without an initializer, global or local,
starts at its type's default, never null: integer/long/decimal 0, number 0.0, boolean false,
string "", date the epoch (1970-01-01 00:00:00), lists and maps empty. Only variant, byte and
cbyte start null. Nullable input fields, unmatched slave fields, missing map keys, nullable
Rollup accumulator fields without a metadata default, and null function results ARE null."""

SYSTEM = """You copy-edit a draft (working notes plus final answer) for a CTL2 task with MINIMAL edits.
Keep the author's voice, structure, wording and length. Change only:
1. sentences that state or rely on a false claim (in particular that a declared, uninitialised
   variable starts null), and the conclusions, findings, guards or initialisers that follow from them;
2. the other issues listed by the reviewer, if any, fixed in the same minimal way.
In the notes, replace a false claim with the correct reasoning at that point (e.g. "date prevX;
starts at the epoch, so on the first record the comparison is safe and gives ..."), in the same
style; do not add commentary about the correction.
For a FIX task: a declaration that is not a defect stays unchanged in the corrected code and is
mentioned once after the numbered problem list as "Left unchanged: ..." with its actual first-use
value. The corrected code must compile and satisfy the specification.
For a VALIDATE/REVIEW task: remove a finding that only exists because of the false claim (or
correct it if a real issue remains), keep the answer's format, and adjust the verdict line if the
remaining findings require it.
Use the reference answer as ground truth for which issues are real. Everything else stays verbatim.
Return JSON only: {"thinking": "<edited notes>", "answer": "<edited answer>"}."""

LENGTH_RULE = """
KEEP THE LENGTH: the edited notes must be about as long as the draft notes (within 10-15%).
Do not just delete the false reasoning: replace it, at the same point and in the same voice,
with equally detailed CORRECT reasoning about the same declaration: state the value it actually
has on first use (e.g. "prevShip is 1970-01-01, so dateDiff(ship, prevShip, day) is about 20,000"),
trace what the code then does on the first record or group, check it against the specification's
required output, and conclude that it needs no change. Do the same in the answer: where a false
finding or fix is removed, the "Left unchanged" line (fix) or the remaining findings (review)
should carry the concrete first-use value."""



def issues(j):
    jd = j.get("judge") or {}
    out = []
    for k in ("missing", "false_claims", "wrong_fixes", "broken_requirements", "compile_problems"):
        out += [f"{k}: {x}" for x in jd.get(k) or []]
    if (j.get("compile") or {}).get("status") == "fail":
        out += [f"compile: {x}" for x in j["compile"].get("problems", [])]
    return out


def repair(key):
    pid, idx = key
    p, s, j = P[pid], S[key], J[key]
    user = (f"{RULE}\n\n=== TASK (user prompt) ===\n{p['user']}\n\n=== REFERENCE ANSWER ===\n{p['reference']}\n\n"
            "=== REVIEWER FINDINGS ON THE DRAFT ===\n" + ("\n".join(issues(j)) or "(belief only)") +
            f"\n\n=== DRAFT NOTES ===\n{s['thinking']}\n\n=== DRAFT ANSWER ===\n{s['answer']}")
    row = {"prompt_id": pid, "sample_idx": idx, "record_id": p.get("record_id"), "task_type": p["task_type"],
           "version": VERSION}
    try:
        txt = judge._client()._call(SYSTEM + (LENGTH_RULE if VERSION == 2 else ""), user, purpose="repair")
        out = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        th, ans = out["thinking"].strip(), out["answer"].strip()
    except Exception as e:  # noqa: BLE001
        return {**row, "accepted": False, "stage": "repair_call", "error": repr(e)[:300]}
    row.update(thinking=th, answer=ans,
               sim_thinking=round(difflib.SequenceMatcher(None, s["thinking"], th, autojunk=False).ratio(), 3),
               len_ratio=round(len(full(th, ans)) / max(len(full(s["thinking"], s["answer"])), 1), 3))
    fmt = sd.format_check(p, ans)
    if fmt:
        return {**row, "accepted": False, "stage": "format", "reason": fmt}
    lib, unknown = sd.library_check(p, ans)
    if lib:
        return {**row, "accepted": False, "stage": "library", "reason": lib, "unknown": unknown}
    if BELIEF.search(th + "\n" + ans):
        return {**row, "accepted": False, "stage": "belief"}
    if p["task_type"] != "validate":
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


def repairs_path(version):
    return RUN / ("repairs.jsonl" if version == 1 else f"repairs_v{version}.jsonl")


def load_repairs_version(version):
    path = repairs_path(version)
    if version == 1 and not path.exists():  # seed with the pilot's repairs (same teacher, same prompts)
        rows = [l for l in open(PILOT / "repairs.jsonl") if json.loads(l)["prompt_id"] in P]
        path.write_text("".join(rows))
    if not path.exists():
        return {}
    return {(r["prompt_id"], r["sample_idx"]): r for r in map(json.loads, open(path))}


def rep_ratio(k, r):
    return len(full(r["thinking"], r["answer"])) / max(len(full(S[k]["thinking"], S[k]["answer"])), 1)


def load_repairs():
    """Best accepted repair per sample: v1 if its length ratio is >= 0.7, else v2 if accepted."""
    v1, v2 = load_repairs_version(1), load_repairs_version(2)
    out = dict(v1)
    for k, r in v2.items():
        a = v1.get(k)
        if r.get("accepted") and not (a and a.get("accepted") and k in S and rep_ratio(k, a) >= 0.7):
            out[k] = r
        elif k not in out:
            out[k] = r
    return out


def cmd_repair():
    global judge, mcp_cfg, synth
    mcp_cfg = sd.mcp_config(SimpleNamespace(mcp_url=None, no_compile=False))
    sd.probe_mcp(mcp_cfg)
    _, raw = sd.load_eval_config(sd.DEFAULT_EVAL_CONFIG)
    judge = sd.Judge(sd.judge_config(raw))
    synth = sd.MetadataSynth(RUN, judge, mcp_cfg)
    done = load_repairs() if VERSION == 1 else load_repairs_version(2)
    best = load_repairs()

    def good(k):
        r = best.get(k)
        return bool(r and r.get("accepted") and rep_ratio(k, r) >= 0.7)
    per = defaultdict(list)
    for key, l in LAB.items():
        if l == "belief" and P[key[0]]["split"] == "train" and S[key].get("think_closed"):
            per[key[0]].append(key)
    todo = []
    for pid, keys in per.items():
        if VERSION == 2:
            ok = sum(1 for k in keys if good(k))
            rest = [k for k in keys if not good(k) and not (k in done and done[k].get("stage") != "repair_call")]
            rest.sort(key=lambda k: (k not in best, (J[k].get("compile") or {}).get("status") == "fail", len(issues(J[k]))))
            todo += rest[:max(0, 2 - ok)]
            continue
        ok = sum(1 for k in keys if done.get(k, {}).get("accepted"))
        tried = {k for k in keys if k in done and done[k].get("stage") != "repair_call"}
        rest = sorted((k for k in keys if k not in tried and not done.get(k, {}).get("accepted")),
                      key=lambda k: ((J[k].get("compile") or {}).get("status") == "fail", len(issues(J[k]))))
        todo += rest[:max(0, 2 - ok)]
    print(f"repairs: {len(done)} cached, {len(todo)} to run", flush=True)
    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(repair, todo))
    for r in rows:
        done[(r["prompt_id"], r["sample_idx"])] = r
    repairs_path(VERSION).write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in done.values()))
    print("this run:", dict(Counter("accepted" if r["accepted"] else r["stage"] for r in rows)))
    print("accepted repairs total:", sum(1 for r in done.values() if r["accepted"]),
          "on", len({r["prompt_id"] for r in done.values() if r["accepted"]}), "prompts")
    acc = sorted(r["len_ratio"] for r in rows if r.get("accepted") and "len_ratio" in r)
    if acc:
        print("length ratio of accepted repairs (this run): median", acc[len(acc) // 2], "min", acc[0])


# ---------------------------------------------------------------- pairs
def full(th, ans):
    return "<think>\n" + th.strip() + "\n</think>\n\n" + ans.strip()


def ratio_ok(a, b):
    r = len(a) / max(len(b), 1)
    return 0.7 <= r <= 1.4


def cmd_pairs():
    reps = load_repairs()
    by = defaultdict(lambda: defaultdict(list))
    for key, l in LAB.items():
        if P[key[0]]["split"] == "train":
            by[key[0]][l].append(key)
    pairs, skipped = [], Counter()
    for pid, labs in sorted(by.items()):
        p = P[pid]
        cand = []
        for k in labs["belief"]:  # B: repair pairs (most targeted) first
            r = reps.get(k)
            if r and r.get("accepted"):
                cand.append(("repair", full(r["thinking"], r["answer"]), k))
        for kc, kb in zip(labs["clean"], labs["belief"]):  # A: natural pairs
            cand.append(("natural", full(S[kc]["thinking"], S[kc]["answer"]), kb))
        for kc, kr in zip(labs["clean"], labs["realnull_safe"]):  # C: contrast
            cand.append(("contrast", full(S[kc]["thinking"], S[kc]["answer"]), kr))
        n = 0
        used = set()
        for kind, chosen, krej in cand:
            if n >= 2 or krej in used:
                continue
            rej = full(S[krej]["thinking"], S[krej]["answer"])
            if not ratio_ok(chosen, rej):
                skipped["length_ratio:" + kind] += 1
                continue
            if len(p["user"]) + max(len(chosen), len(rej)) > 18000:  # ~5k tokens; cutoff_len is 6144
                skipped["too_long:" + kind] += 1
                continue
            used.add(krej)
            n += 1
            pairs.append({"id": f"dpodef1_{pid}_{krej[1]}_{kind}", "kind": kind, "prompt_id": pid,
                          "record_id": p.get("record_id"), "task_type": p["task_type"],
                          "system": S[krej]["system_prompt"], "prompt": p["user"], "chosen": chosen, "rejected": rej})
    (RUN / "pairs.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in pairs))
    keys = ("id", "system", "prompt", "chosen", "rejected", "task_type")
    (RUN / "dpodef1_train.jsonl").write_text("".join(json.dumps({k: x[k] for k in keys}, ensure_ascii=False) + "\n" for x in pairs))
    rep = {"pairs": len(pairs), "by_kind": Counter(x["kind"] for x in pairs), "by_task": Counter(x["task_type"] for x in pairs),
           "prompts": len({x["prompt_id"] for x in pairs}), "skipped": skipped,
           "by_source": Counter(P[x["prompt_id"]]["source_file"] for x in pairs)}
    sd.write_json(RUN / "report.json", rep)
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "label"
    stats()
    if cmd == "repair":
        cmd_repair()
    elif cmd == "pairs":
        cmd_pairs()
