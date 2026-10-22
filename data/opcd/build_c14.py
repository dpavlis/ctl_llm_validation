"""OPCD run c14 inputs: the revised Rollup accumulator set (ctl_lora_training round 2) as OPCD prompts, both thinking modes,
scored by the rulev7 teacher, named per prompt ("teacher": "acc") so it applies in both modes (component_teacher
swaps thinking-on samples only). Target: the belief fix's overgeneralization to Rollup accumulators
("a nullable accumulator field starts at zero"; findings §3.27 review correction). rb1009 never trained on this set.

Writes
  data/opcd/c14_acc.jsonl          70 trained prompts: 40 SFT user turns + the 30 DPO prompts (thinking on, rulev7)
  data/opcd/c14_acc_off.jsonl      the same 70 for thinking off, scored by plain rb1009 (teacher "student")
  data/opcd/hard_holdout_c14.json  c13d's holdouts + 10 SFT holdouts, never trained

    python data/opcd/build_c14.py
"""
import json
from pathlib import Path

R = Path(__file__).resolve().parents[2]
C = R / "ctl_lora_training/sft_training_data"
sft = json.load(open(C / "CTL_LoRA_rollup_accumulator_sft.json"))
dpo = [json.loads(l) for l in open(C / "CTL_LoRA_DPO_rollup_accumulator.jsonl")]


def task(user, answer):
    if "VERDICT" in answer:
        return "validate"
    return "fix" if "function " in user else "generate"   # fix and explanation prompts both carry the code


rows = []
for r in sft:
    user = next(m["content"] for m in r["messages"] if m["role"] == "user")
    answer = next(m["content"] for m in r["messages"] if m["role"] == "assistant")
    rows.append({"id": r["id"], "task_type": task(user, answer), "user": user})
# 10 holdouts, stratified by task: every 5th of each task's list
held = set()
for t, k in (("fix", 5), ("validate", 3), ("generate", 2)):
    ids = [r["id"] for r in rows if r["task_type"] == t]
    held |= set(ids[2::5][:k])
with open(R / "data/opcd/c14_acc.jsonl", "w") as fh:
    for r in rows:
        if r["id"] not in held:
            fh.write(json.dumps({"id": r["id"], "group": "ACC2", "task_type": r["task_type"], "component": "ROLLUP",
                                 "teacher": "acc", "user": r["user"]}, ensure_ascii=False) + "\n")
    for i, p in enumerate(dpo):
        fh.write(json.dumps({"id": f"rollup_acc_dpo_{i + 1:03d}", "group": "ACC2", "task_type": task(p["prompt"], p["chosen"]),
                             "component": "ROLLUP", "teacher": "acc", "user": p["prompt"]}, ensure_ascii=False) + "\n")
# thinking-off copy scored by plain rb1009 (adapter off, plain prompt: role "student"). Teacher check (n20, thinking off):
# rulev7 catches T22.B1 (uninitialised acc.count) 1/20 vs plain 11/20, while both avoid c13c's T41.B2 error (2 and 1 vs 15/20).
with open(R / "data/opcd/c14_acc.jsonl") as src, open(R / "data/opcd/c14_acc_off.jsonl", "w") as fh:
    for line in src:
        r = json.loads(line)
        r.update(id=r["id"] + "_off", teacher="student")
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
c13d = json.load(open(R / "data/opcd/hard_holdout_c13d.json"))
(R / "data/opcd/hard_holdout_c14.json").write_text(json.dumps(
    {"holdout": c13d["holdout"] + sorted(held), "note": "c13d's holdouts + 10 Rollup accumulator SFT holdouts (build_c14.py)"},
    indent=1) + "\n")
print(len(rows) - len(held) + len(dpo), "trained,", len(held), "held out:", sorted(held))
