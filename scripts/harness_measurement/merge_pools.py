"""Merge the per-seed tweak pools (data/agent_harness/tweak/s<seed>.jsonl) into data/agent_harness/pool_tweak.jsonl.

Tasks are deduplicated by id (the hash of the rewritten prompt). Two kinds of drops (step 2 of Part A):
  prose_origin  the corpus answer to the original prompt has no CTL code (an explanation, design or validate question
                filed as generate), unless the rewrite explicitly asks for CTL: the hand check found 3 of 15 sampled
                tasks were such prose questions, which the model would answer without code (scored no_code)
  --drop        a JSON list of {id, why} removed by reading
The report sums the per-seed rejection counters and adds the acceptance rate.

    ~/venv/bin/python scripts/harness_measurement/merge_pools.py [--drop data/agent_harness/pool_tweak.dropped.json]
    # a second batch (retry-distill training pool): --dir data/agent_harness/tweak_retry --exclude data/agent_harness/pool_tweak.jsonl
"""
import argparse, collections, glob, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data/agent_harness"
CODE_RE = re.compile(r"//#CTL2|function\s+\w+\s+\w+\s*\(")
ASKS_CTL_RE = re.compile(r"\bWrite (complete )?CTL2?\b|\bReturn (the )?complete CTL", re.I)


def corpus_answers():
    out = {}
    for f in glob.glob(str(ROOT / "ctl_lora_training/sft_training_data/CTL_LoRA_*_sft.json")):
        for r in json.loads(Path(f).read_text()):
            out[r.get("id")] = next((m["content"] for m in r.get("messages", []) if m["role"] == "assistant"), "")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop")
    ap.add_argument("--out", default=str(D / "pool_tweak.jsonl"))
    ap.add_argument("--dir", default=str(D / "tweak"), help="folder of the per-seed pools (default data/agent_harness/tweak)")
    ap.add_argument("--exclude", nargs="*", default=[], help="pools whose task ids are dropped (e.g. pool_tweak.jsonl for a training batch)")
    a = ap.parse_args()
    exclude = {json.loads(l)["id"] for f in a.exclude for l in Path(f).read_text().splitlines()}
    drop = {d["id"]: d["why"] for d in json.loads(Path(a.drop).read_text())} if a.drop else {}
    tasks, rejected, seeds = {}, collections.Counter(), {}
    for p in sorted(Path(a.dir).glob("s*.jsonl")):
        if p.name.endswith(".rejected.jsonl"):
            continue
        rep = json.loads(p.with_suffix(".report.json").read_text())
        rejected.update(rep["rejected"])
        seeds[p.stem] = dict(kept=rep["rejected"].get("tweak_kept", 0),
                             tried=sum(v for k, v in rep["rejected"].items() if k.startswith("tweak_")))
        for l in p.read_text().splitlines():
            t = json.loads(l)
            if t["id"] not in exclude:
                tasks.setdefault(t["id"], t)
    answers = corpus_answers()
    for t in tasks.values():
        if not CODE_RE.search(answers.get(t["origin"]) or "") and not ASKS_CTL_RE.search(t["prompt"]):
            drop.setdefault(t["id"], "prose_origin")
    kept = [t for t in tasks.values() if t["id"] not in drop]
    with open(a.out, "w") as fh:
        for t in kept:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    tried = sum(s["tried"] for s in seeds.values())
    reasons = {k[6:]: v for k, v in rejected.most_common() if k.startswith("tweak_") and k != "tweak_kept"}
    report = dict(tasks=len(kept), accepted_by_server=len(tasks), dropped_after_review=len(tasks) - len(kept),
                  dropped_by_reason=collections.Counter(drop[t] for t in tasks if t in drop), dropped=drop, tried=tried, acceptance_rate=round(rejected["tweak_kept"] / tried, 3) if tried else None,
                  rejections=reasons, seeds=seeds,
                  by_set=collections.Counter(t["set"] for t in kept), by_component=collections.Counter(t["component"] for t in kept))
    Path(a.out).with_suffix(".report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "dropped"}, indent=1))


if __name__ == "__main__":
    main()
