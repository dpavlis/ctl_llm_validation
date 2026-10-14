"""OPCD run c9 inputs: guide teachers for the generate gaps G1, G3, G4, G6 (spec/opcd_generate_gaps_brief.md).

The teacher-check (data/opcd/build_teacher_check.py) showed the CloverDX component guide + ctl2-basics §13.3 in the
prompt beats plain c4 by +0.12..+0.41 on G1 dictionary, G3 stateful routing, G4 SCD and G6 UTC calendars, and gives
nothing on G2 / G5, which are left out. The OPCD teacher is rb1006 with the adapter disabled, which still has the
declaration-default belief, so its prompt is rulev3 (the c4 teacher) + the guide + §13.3.

Writes
  configs/opcd_c9_teachers/<name>_{on,off}.yaml  one named teacher per component (guide_<COMP>; G1: guide_dict_<COMP>)
  data/opcd/generate_gaps_c9.jsonl               the G1/G3/G4/G6 prompts with their teacher name
  data/opcd/generate_gaps_c9_holdout.json        3 prompts per gap, never trained
  data/opcd/teacher_check/suite_ruleguide.json   the teacher-check suite for exactly this teacher prompt (36 prompts)

    python data/opcd/build_c9.py
"""
import json, re
from pathlib import Path
import yaml

R = Path(__file__).resolve().parents[2]
GUIDES = R / "data/suite_v5/round2"
KEEP = ("Description", "Purpose", "CTL2 contract", "Examples", "Common mistakes")
GAPS = ("G1", "G3", "G4", "G6")
HOLDOUT = ("03", "09", "15")          # per gap; disjoint from the teacher-check picks 01/04/07/10/13/16
MARKER = "# Reference: the component you are writing for"


def guide(name: str) -> str:
    text = json.loads((GUIDES / f"{name}_guide.json").read_text())["text"]
    parts = re.split(r"(?m)^(?=## )", text)
    return "\n\n".join([parts[0].strip()] + [p.strip() for p in parts[1:] if p[3:].startswith(KEEP)])


basics = (R / "resources/ctl2-basics.md").read_text()
facts = basics[basics.index("### 13.3"):basics.index("## 14.")].strip()


def block(comp: str, dictionary: bool) -> str:
    g = guide(comp) + ("\n\n" + guide("dictionary") if dictionary else "")
    return f"\n{MARKER}\n\n{g}\n\n# Reference: verified runtime behaviour\n\n{facts}\n"


rows = [json.loads(l) for l in open(R / "data/opcd/generate_gaps.jsonl")]
rows = [r for r in rows if r["gap"] in GAPS]
names = {}
for r in rows:
    names[r["id"]] = ("guide_dict_" if r["gap"] == "G1" else "guide_") + r["component"]

# named teacher configs: rulev3 teacher configs with the guide block appended to every task's system prompt
tdir = R / "configs/opcd_c9_teachers"
tdir.mkdir(exist_ok=True)
for name in sorted(set(names.values())):
    comp, dic = name.split("_", 2)[-1] if name.startswith("guide_dict_") else name[len("guide_"):], name.startswith("guide_dict_")
    for mode in ("on", "off"):
        c = yaml.safe_load(open(R / f"configs/eval_rb1006_rulev3_{mode}.yaml"))
        for task in ("generate", "validate", "fix"):
            c["mut"][task]["system_prompt"] = c["mut"][task]["system_prompt"] + block(comp, dic)
        with open(tdir / f"{name}_{mode}.yaml", "w") as f:
            f.write(f"# OPCD c9 teacher {name}, thinking {mode.upper()}: rulev3 + CloverDX {comp} guide"
                    f"{' + dictionary guide' if dic else ''} + ctl2-basics §13.3 -- data/opcd/build_c9.py\n")
            yaml.safe_dump(c, f, sort_keys=False, allow_unicode=True)

held = [r["id"] for r in rows if r["id"].rsplit("_", 1)[1] in HOLDOUT]
(R / "data/opcd/generate_gaps_c9_holdout.json").write_text(json.dumps({"holdout": held}, indent=1) + "\n")
with open(R / "data/opcd/generate_gaps_c9.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps({"id": r["id"], "gap": r["gap"], "task_type": "generate", "component": r["component"],
                            "teacher": names[r["id"]], "user": r["user"]}, ensure_ascii=False) + "\n")

# teacher check for exactly this teacher prompt (generate, rulev3 + guide), on the teacher-check prompts
rule = yaml.safe_load(open(R / "configs/eval_rb1006_rulev3_on.yaml"))["mut"]["generate"]["system_prompt"]
plain = json.loads((R / "data/opcd/teacher_check/suite_plain.json").read_text())
gap_of = {r["id"].replace("opcd_gen_", ""): r for r in json.loads("[" + ",".join(open(R / "data/opcd/generate_gaps.jsonl")) + "]")}
suite = dict(plain, version="teacher-check-ruleguide",
             tests=[dict(t, system_prompt=rule + block(t["component"], gap_of[t["test_id"]]["gap"] == "G1"))
                    for t in plain["tests"]])
(R / "data/opcd/teacher_check/suite_ruleguide.json").write_text(json.dumps(suite, indent=1, ensure_ascii=False))
print(f"{len(rows)} prompts ({len(held)} held out), teachers: {sorted(set(names.values()))}")
