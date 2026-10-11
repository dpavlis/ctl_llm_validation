"""Contrast prompts for OPCD c3: corpus prompts where something really IS null, so the student does not
overshoot "declared variables are never null" onto record fields (c2: T22 says a nullable Rollup
accumulator field starts at 0; validate thinking-off WRONG 4.5% -> 7.8%).

  python data/opcd/select_contrast.py  -> data/opcd/contrast_prompts.jsonl
Categories (regex on the prompt): Rollup with a nullable accumulator / initGroup; nullable field in a
string concatenation; lookup / map read that can miss. Probe prompts are excluded.
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import self_distill as sd  # noqa: E402

NULLABLE = r'nullable(="true"|\s*\)|: true|,)|\(nullable\)'
CATS = {
    "rollup_nullable_acc": (30, lambda p: p["component"] == "ROLLUP" and re.search(r"accumulat|initGroup", p["user"])
                            and re.search(NULLABLE, p["user"], re.I)),
    "null_concat": (15, lambda p: re.search(NULLABLE, p["user"], re.I)
                    and re.search(r'\+\s*\$in\.\d\.\w+|\$in\.\d\.\w+\s*\+\s*"', p["user"])),
    "lookup_miss": (15, lambda p: re.search(r"lookup\(|\.get\(|\[\$in\.\d\.\w+\]", p["user"])),
}


def main():
    pool, _ = sd.build_pool(sd.load_exclusion_set()[0])
    probe = {json.loads(l)["prompt_id"] for l in open(sd.RUNS_DIR / "dpodef1" / "prompts.jsonl")
             if json.loads(l).get("split") == "probe"}
    rng, out, seen = random.Random(0), [], set(probe)
    for cat, (n, f) in CATS.items():
        cand = [p for p in pool if p["prompt_id"] not in seen and f(p)]
        for p in rng.sample(cand, min(n, len(cand))):
            seen.add(p["prompt_id"])
            out.append({k: p.get(k) for k in ("prompt_id", "task_type", "component", "source_file", "record_id", "user")}
                       | {"contrast_kind": cat})
    path = Path(__file__).resolve().parent / "contrast_prompts.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    from collections import Counter
    print(len(out), Counter((r["contrast_kind"], r["task_type"]) for r in out))


if __name__ == "__main__":
    main()
