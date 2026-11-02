"""dpodef2: context-distillation DPO pairs against the "declared variables start null" belief.

chosen   = rb1006 sample drawn WITH the declaration rule (+ Java/C# contrast) in the system prompt
           (run dpodef2, configs/eval_rb1006_rulectx_on.yaml) that passed the full filter
           (format, library, compile, judge, claims), holds no belief, and does not refer to the
           rule / instructions it was given;
rejected = rb1006 sample of the same prompt drawn WITHOUT the rule (runs dpodef1 + dpodef1x) that
           holds the belief (belief scan or judge false-claim / wrong-fix about a declaration default).
Both are trained under the PLAIN system prompt (the rejected sample's), so the model learns to reason
this way without being told. At most 2 pairs per prompt, length ratio 0.6-1.6 (was 0.7-1.4), about 5k tokens max.
A belief-scan hit whose context names Java / C# / JavaScript / .NET is a correct contrast, not the belief.

  python build_ctx_pairs.py      -> pairs.jsonl, dpodef2_train.jsonl, report.json
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/home/pavlisd/llama_train")
import self_distill as sd  # noqa: E402

RUN = Path(__file__).resolve().parent
BASE = sd.RUNS_DIR / "dpodef1"
EXTRA = sd.RUNS_DIR / "dpodef1x"
P = {json.loads(l)["prompt_id"]: json.loads(l) for l in open(BASE / "prompts.jsonl")}

BELIEF = sd.KNOWN_FALSE_BELIEFS["declared variables start null"]
DEF = re.compile(r"(epoch|empty (list|map)|uninitiali[sz]ed|declared|defaults? to|starts? (at|as|empty)|bare declaration)", re.I)
LANG = re.compile(r"\b(Java|C#|C Sharp|JavaScript|JS|TypeScript|\.NET|Kotlin)\b")
REFERS = re.compile(
    r"(system prompt|system message|the instructions?\b|as instructed|I(?:'ve| have) been told|"
    r"(?:per|according to|by) the (?:rules?|guidance|instructions?|prompt|note)|the rules? (?:says?|states?|given|above)|"
    r"the (?:given|stated|provided) rule|as (?:stated|noted|mentioned) (?:above|in the prompt)|the prompt (?:says|states)|"
    r"global or local, starts at its type)", re.I)


def scan_belief(text):
    """Belief-scan hits that are not a correct Java/C#/JS contrast."""
    return [m for m in BELIEF.finditer(text) if not LANG.search(text[max(0, m.start() - 160):m.end() + 60])]


def judge_belief(j):
    jd = (j or {}).get("judge") or {}
    return any(DEF.search(t) and re.search("null", t, re.I)
               for t in (jd.get("false_claims") or []) + (jd.get("wrong_fixes") or []))


def load(run, offset=0):
    S = {(pid, i + offset): {**v, "sample_idx": i + offset} for (pid, i), v in sd.load_samples(run).items()}
    J = {(pid, i + offset): v for (pid, i), v in sd.load_judged(run).items()}
    return S, J


def full(s):
    return "<think>\n" + s["thinking"].strip() + "\n</think>\n\n" + s["answer"].strip()


def main():
    CS, CJ = load(sd.RUNS_DIR / "dpodef2")
    RS, RJ = load(BASE)
    xs, xj = load(EXTRA, offset=4)
    RS.update(xs); RJ.update(xj)

    chosen, stats = defaultdict(list), Counter()
    for k, s in CS.items():
        j = CJ.get(k)
        if k[0] not in P or P[k[0]]["split"] != "train" or j is None:
            continue
        stats["rule_samples"] += 1
        text = s["thinking"] + "\n" + s["answer"]
        bel = bool(scan_belief(text)) or judge_belief(j)
        stats["rule_belief"] += bel
        if not j.get("accepted") or not s.get("think_closed"):
            continue
        stats["rule_accepted"] += 1
        if bel:
            continue
        if REFERS.search(text):
            stats["rule_dropped_refers_to_rule"] += 1
            continue
        chosen[k[0]].append(k)

    rejected = defaultdict(list)
    for k, s in RS.items():
        if k[0] not in P or P[k[0]]["split"] != "train" or k not in RJ or not s.get("think_closed"):
            continue
        text = s["thinking"] + "\n" + s["answer"]
        if scan_belief(text) or judge_belief(RJ[k]):
            rejected[k[0]].append(k)

    pairs, skipped = [], Counter()
    for pid in sorted(set(chosen) & set(rejected)):
        p, n = P[pid], 0
        for kc, kr in zip(chosen[pid], rejected[pid]):
            if n >= 2:
                break
            c, r = full(CS[kc]), full(RS[kr])
            ratio = len(c) / max(len(r), 1)
            if not 0.6 <= ratio <= 1.6:  # widened from 0.7-1.4 on 2026-10-09 (35 -> 48 pairs)
                skipped["length_ratio"] += 1
                continue
            if len(p["user"]) + max(len(c), len(r)) > 18000:
                skipped["too_long"] += 1
                continue
            n += 1
            pairs.append({"id": f"dpodef2_{pid}_{kc[1]}_{kr[1]}", "prompt_id": pid, "record_id": p.get("record_id"),
                          "task_type": p["task_type"], "system": RS[kr]["system_prompt"], "prompt": p["user"],
                          "chosen": c, "rejected": r, "len_ratio": round(ratio, 3)})
    assert not any("Declaration defaults in CTL2" in x["system"] for x in pairs), "rule leaked into a training system prompt"
    (RUN / "pairs.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in pairs))
    keys = ("id", "system", "prompt", "chosen", "rejected", "task_type")
    (RUN / "dpodef2_train.jsonl").write_text("".join(json.dumps({k: x[k] for k in keys}, ensure_ascii=False) + "\n" for x in pairs))
    rs = sorted(x["len_ratio"] for x in pairs)
    rep = {**stats, "rule_belief_rate": round(stats["rule_belief"] / max(stats["rule_samples"], 1), 3),
           "prompts_with_chosen": len(chosen), "prompts_with_rejected": len(rejected),
           "prompts_with_both": len(set(chosen) & set(rejected)), "pairs": len(pairs),
           "pair_prompts": len({x["prompt_id"] for x in pairs}), "by_task": Counter(x["task_type"] for x in pairs),
           "by_source": Counter(P[x["prompt_id"]]["source_file"] for x in pairs), "skipped": skipped,
           "len_ratio_median": rs[len(rs) // 2] if rs else None,
           "plain_system_prompts": len({x["system"] for x in pairs})}
    sd.write_json(RUN / "report.json", rep)
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
