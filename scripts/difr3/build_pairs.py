"""difr3 (WORKLOG 2026-11-02, option 1): fixed DPO pairs for the review false alarm on clean DataIntersection code.

For every DI control review row of review_prompts_v3 that returns ALL (22 records x {fmt, plain} x {on, off}):
  rejected = a student sample whose answer raises an [ERROR] on the clean code. valprec2 itself flags only 12 of 88
             thinking-on samples here (2026-11-02 first build: 19 pairs), so the student is the drifted difr2 round 39
             (--student difr2_r39), whose false alarms are the ones to push away from; thinking on only (--modes on):
             the thinking-off teacher flags these controls itself (28-35 of 44) and thinking-off review does not ship;
  chosen   = a review-teacher sample (rb1009 base, rulev6 validate prompt + format + teacher_context) with no error
             finding, closed thinking, not at the cap, and no quote of its context (train.context_guard).
Rows come out in the exec-row shape (prompts.exec_fixed): completion_ids (chosen) / rejected_ids under the STUDENT prompt.
  python scripts/difr3/build_pairs.py configs/opcd_difr3.yaml --url http://127.0.0.1:3013 --student valprec2 --teacher rb1009_vp \
      --out data/opcd/difr3_pairs.jsonl
"""
import argparse, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests, yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import opcd  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("config"); ap.add_argument("--url", default="http://127.0.0.1:3013"); ap.add_argument("--student", default="valprec2")
ap.add_argument("--teacher", default="rb1009_vp"); ap.add_argument("--reviews", default="data/validate_precision/review_prompts_v3.jsonl")
ap.add_argument("--k-student", type=int, default=4); ap.add_argument("--k-teacher", type=int, default=2)
ap.add_argument("--max-pairs-per-row", type=int, default=4); ap.add_argument("--out", required=True); ap.add_argument("--workers", type=int, default=16)
ap.add_argument("--limit", type=int, default=0); ap.add_argument("--modes", default="on,off")
a = ap.parse_args()
cfg = yaml.safe_load(open(a.config))
roles = opcd.Roles(cfg)
guard = re.compile(cfg["train"]["context_guard"], re.I)
rows = [r for r in opcd.sd.read_jsonl(Path(a.reviews))
        if r["kind"] == "control" and "ntersection" in r["component"].lower() and "return ALL" in r["user"]
        and r["mode"] in a.modes.split(",")]
if a.limit:
    rows = rows[:a.limit]
print(f"{len(rows)} DI control rows with return ALL", flush=True)
stops = opcd.stop_ids(roles.tok)

def draw(model, ids, p, k, seed):
    s = roles.sampling(p)
    r = requests.post(f"{a.url}/v1/completions", timeout=7200, json={
        "model": model, "prompt": ids, "max_tokens": cfg["train"]["max_new_tokens"], "n": k, "seed": seed,
        "temperature": s["temperature"], "top_p": s["top_p"], "top_k": s["top_k"], "repetition_penalty": s["repetition_penalty"],
        "stop_token_ids": stops, "return_token_ids": True, "skip_special_tokens": False})
    r.raise_for_status()
    out = []
    for i, c in enumerate(sorted(r.json()["choices"], key=lambda c: c["index"])):
        comp = list(c["token_ids"]); raw = roles.tok.decode(comp, skip_special_tokens=True)
        th, ans = opcd.split_thinking(raw, thinking_enabled=(p["mode"] == "on"))
        out.append({"ids": comp, "raw": raw, "answer": ans, "closed": p["mode"] == "off" or "</think>" in raw,
                    "cap": c["finish_reason"] == "length"})
    return out

def one(r):
    p = dict(r, task_type="validate")
    seed = int(r["prompt_id"][:8], 16) % 1_000_000 if r.get("prompt_id") else 7
    st = draw(a.student, roles.ids("student", p), p, a.k_student, seed)
    te = draw(a.teacher, roles.ids("teacher", p), p, a.k_teacher, seed + 1)
    bad = [s for s in st if "[ERROR]" in s["answer"] and s["closed"] and not s["cap"]]
    plain = r["tag"].endswith(":plain")
    good = [s for s in te if "[ERROR]" not in s["answer"] and s["closed"] and not s["cap"] and not guard.search(s["raw"])
            and (plain or "VERDICT: PASS" in s["answer"]) and not (plain and re.search(r"\bERROR\b", s["answer"]))]
    pairs = []
    for i, b in enumerate(bad[:a.max_pairs_per_row]):
        if not good:
            break
        c = good[i % len(good)]
        pairs.append({"prompt_id": f"{r['id']}:d{i}", "task_type": "validate", "component": r["component"],
                      "source_file": r.get("source_file"), "record_id": r.get("record_id"), "user": r["user"], "mode": r["mode"],
                      "system_extra": r.get("system_extra"), "tag": r["tag"] + ":pair", "exec_kind": "dpo",
                      "completion_ids": c["ids"], "rejected_ids": b["ids"], "exec_status": "clean_false_alarm",
                      "chosen_answer": c["answer"][:400], "rejected_error": next(l for l in b["answer"].splitlines() if "[ERROR]" in l)[:300]})
    return {"id": r["id"], "mode": r["mode"], "tag": r["tag"], "student": len(st), "student_flag": len(bad),
            "teacher": len(te), "teacher_clean": len(good), "teacher_quote": sum(bool(guard.search(s["raw"])) for s in te),
            "teacher_error": sum("[ERROR]" in s["answer"] for s in te), "pairs": pairs}

t0 = time.monotonic(); res = []
with ThreadPoolExecutor(a.workers) as ex:
    for i, x in enumerate(ex.map(one, rows), 1):
        res.append(x)
        if i % 10 == 0:
            print(f"{i}/{len(rows)} rows, {sum(len(x['pairs']) for x in res)} pairs, {int(time.monotonic() - t0)}s", flush=True)
pairs = [p for x in res for p in x["pairs"]]
Path(a.out).write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs))
stat = {}
for x in res:
    d = stat.setdefault(f"{x['mode']}:{x['tag']}", {"rows": 0, "student": 0, "student_flag": 0, "teacher": 0, "teacher_clean": 0, "teacher_quote": 0, "teacher_error": 0, "pairs": 0})
    d["rows"] += 1
    for k in ("student", "student_flag", "teacher", "teacher_clean", "teacher_quote", "teacher_error"):
        d[k] += x[k]
    d["pairs"] += len(x["pairs"])
rep = {"rows": len(rows), "pairs": len(pairs), "by": stat}
Path(a.out).with_suffix(".report.json").write_text(json.dumps(rep, indent=1))
print(json.dumps(rep, indent=1))
