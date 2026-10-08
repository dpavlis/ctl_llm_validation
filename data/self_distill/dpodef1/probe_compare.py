"""Belief rate on the 50 held-out probe prompts: base rb1006 samples (dpodef1 run) vs the DPO model
(dpodef1_probe run). Same labelling as build_pairs.py; also counts 'realnull_safe' (overshoot)."""
import json, re, sys
from collections import Counter
sys.path.insert(0, "/home/pavlisd/llama_train")
import self_distill as sd  # noqa: E402
BELIEF = sd.KNOWN_FALSE_BELIEFS["declared variables start null"]
DEF = re.compile(r"(epoch|empty (list|map)|uninitiali[sz]ed|declared|defaults? to|starts? (at|as|empty)|bare declaration)", re.I)
REALNULL = re.compile(r"(variant|byte|cbyte|nullable|accumulator|map key|missing key|slave|unmatched)", re.I)
SAFE = re.compile(r"(not null|never null|cannot be null|can't be null|is safe|no null|non-null)", re.I)


def run_labels(run, probe_ids):
    d = sd.RUNS_DIR / run
    S = sd.load_samples(d); J = sd.load_judged(d)
    c = Counter(); per = {}
    for k, s in S.items():
        if k[0] not in probe_ids or k not in J: continue
        j = J[k]; jd = j.get("judge") or {}
        jt = (jd.get("false_claims") or []) + (jd.get("wrong_fixes") or [])
        text = (s.get("thinking") or "") + "\n" + (s.get("answer") or "")
        b = bool(BELIEF.search(text)) or any(DEF.search(t) and re.search("null", t, re.I) for t in jt)
        o = any(REALNULL.search(t) and SAFE.search(t) for t in jt)
        c["n"] += 1; c["belief"] += b; c["overshoot"] += o; c["accepted"] += bool(j.get("accepted"))
        c["open_think"] += not s.get("think_closed")
        per.setdefault(k[0], []).append(b)
    return c, per


P = [json.loads(l) for l in open(sd.RUNS_DIR / "dpodef1" / "prompts.jsonl")]
probe = {p["prompt_id"]: p for p in P if p["split"] == "probe"}
for run in ("dpodef1", "dpodef1_probe"):
    c, per = run_labels(run, probe)
    if not c["n"]: print(run, "no samples"); continue
    g = Counter()
    for pid, v in per.items():
        grp = probe[pid]["selection_group"].split(":")[1]; g[grp, "n"] += len(v); g[grp, "b"] += sum(v)
    print(f"{run:15s} n={c['n']} belief={c['belief']/c['n']:.1%} accepted={c['accepted']/c['n']:.1%} "
          f"overshoot={c['overshoot']} open_think={c['open_think']} | " +
          " ".join(f"{k}:{g[k,'b']}/{g[k,'n']}" for k in ("fixdef", "fixexpl", "other_fix", "other_validate")))
