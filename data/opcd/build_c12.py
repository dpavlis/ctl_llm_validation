"""OPCD run c12 inputs: the revised DataIntersection set (ctl_lora_training d80aaa5, round 2b: no mechanism hints, 10
whole-component prompts in the suite T53 framing) on top of c10. SCD is left out (c9 and c11 both cost thinking-on SCD).

Teacher check (data/opcd/build_di2_tcheck.py, 60 prompts x 3): the c11 DataIntersection guide teacher scores 0.88 off /
0.90 on, whole-component prompts 0.95; c10 scores 0.23 / 0.16, whole-component 0.00. The teacher is
configs/opcd_c11_teachers/guide_DATA_INTERSECTION_{on,off}.yaml (guide + ctl2-basics §8.9 + §13.3), no worked example.

Writes
  data/opcd/c12_di.jsonl                          50 trained prompts (teacher guide11_DATA_INTERSECTION)
  data/opcd/hard_holdout_c12.json                 c9's 26 gap holdouts + the 10 DI holdouts, never trained
  data/opcd/teacher_check/suite_c12_holdout.json  the 10 DI holdouts, judged against the verified answer

    python data/opcd/build_c12.py
"""
import json
from pathlib import Path

R = Path(__file__).resolve().parents[2]
C = R / "ctl_lora_training/sft_training_data"
log = json.load(open(C / "logs/CTL_LoRA_dataintersection_validation.json"))
whole = {f"di_sft_{i:03d}" for i in log["whole_component_revision"]["sft_indices"]}
task = {m["id"]: {"generation": "generate", "explanation": "generate", "validation": "validate", "repair": "fix"}[m["task"]]
        for m in json.load(open(C / "logs/dataintersection_runtime/round2/manifest.json")) if m["kind"] == "sft"}
rows = [r for r in json.load(open(C / "CTL_LoRA_dataintersection_sft.json"))]
ids = [r["id"] for r in rows]

# 10 holdouts, stratified: 3 whole-component prompts, then every 6th of the rest
held = sorted(whole)[1::3][:3]
rest = [i for i in ids if i not in whole]
held += rest[4::6][:10 - len(held)]
held = set(held)

with open(R / "data/opcd/c12_di.jsonl", "w") as fh:
    for r in rows:
        if r["id"] in held:
            continue
        user = next(m["content"] for m in r["messages"] if m["role"] == "user")
        fh.write(json.dumps({"id": r["id"], "group": "DI2", "task_type": task[r["id"]], "component": "DATA_INTERSECTION",
                             "teacher": "guide11_DATA_INTERSECTION", "user": user}, ensure_ascii=False) + "\n")

c11 = json.load(open(R / "data/opcd/hard_holdout_c11.json"))
c9_held = [i for i in c11["holdout"] if not i.startswith(("di_sft_", "scd2_sft_"))]
(R / "data/opcd/hard_holdout_c12.json").write_text(json.dumps(
    {"holdout": c9_held + sorted(held), "note": "c9's gap holdouts + 10 DataIntersection round-2b holdouts (build_c12.py)"},
    indent=1) + "\n")

plain = json.loads((R / "data/opcd/teacher_check/suite_di2_plain.json").read_text())
(R / "data/opcd/teacher_check/suite_c12_holdout.json").write_text(json.dumps(
    dict(plain, version="c12-holdout", tests=[t for t in plain["tests"] if t["test_id"] in held]), indent=1, ensure_ascii=False))
print(len(rows) - len(held), "trained,", len(held), "held out:", sorted(held), "| whole-component held:", sorted(held & whole))
print("c9 holdouts kept:", len(c9_held))
