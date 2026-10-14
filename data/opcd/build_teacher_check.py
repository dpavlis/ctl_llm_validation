"""Teacher check for the OPCD generate gaps (spec/opcd_generate_gaps_brief.md, internal tracking).

Builds two test.py suites over the same prompts (6 per gap from generate_gaps.jsonl):
  teacher_check/suite_plain.json  - the standard generate system prompt (what the student sees)
  teacher_check/suite_guide.json  - the same + the CloverDX component guide (contract, examples, common mistakes;
                                    G1 also the dictionary guide) + ctl2-basics.md §13.3 (the teacher's prompt)
The judge prompts come from suite v5; the judge reference is resources/ctl2-basics.md (no copy next to the suites).

    python data/opcd/build_teacher_check.py
"""
import json, re
from pathlib import Path

R = Path(__file__).resolve().parents[2]
OUT = R / "data/opcd/teacher_check"
GUIDES = R / "data/suite_v5/round2"
PICK = ("01", "04", "07", "10", "13", "16")
KEEP = ("Description", "Purpose", "CTL2 contract", "Examples", "Common mistakes")   # guide sections, by heading prefix
SYSTEM = ("You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean "
          "the same language.\nHelp users write, debug, and explain CTL2 code and related concepts. Provide working code, "
          "explanation, or both as needed.\nPrefer correct, practical, minimal solutions.\n")


def guide(name: str) -> str:
    text = json.loads((GUIDES / f"{name}_guide.json").read_text())["text"]
    parts = re.split(r"(?m)^(?=## )", text)
    head, keep = parts[0].strip(), [p.strip() for p in parts[1:] if p[3:].startswith(KEEP)]
    return "\n\n".join([head] + keep)


basics = (R / "resources/ctl2-basics.md").read_text()
facts = basics[basics.index("### 13.3"):basics.index("## 14.")].strip()
v5 = json.loads((R / "resources/ctl2_test_suite_v5.json").read_text())
rows = [json.loads(l) for l in open(R / "data/opcd/generate_gaps.jsonl")]
rows = [r for r in rows if r["id"].rsplit("_", 1)[1] in PICK]

plain, teach = [], []
for r in rows:
    t = {"test_id": r["id"].replace("opcd_gen_", ""), "type": "generate", "component": r["component"], "gap": r["gap"],
         "temperature": 0.4, "system_prompt": SYSTEM, "user_message": r["user"],
         "rubric": {"description": f"OPCD generate gap {r['gap']}", "required": r["rubric"]["required"],
                    "forbidden": r["rubric"]["forbidden"],
                    "scoring": {"method": "required_fraction", "forbidden_penalty": 0.2}}}
    g = guide(r["component"]) + ("\n\n" + guide("dictionary") if r["gap"] == "G1" else "")
    plain.append(t)
    teach.append(dict(t, system_prompt=SYSTEM + "\n# Reference: the component you are writing for\n\n" + g
                      + "\n\n# Reference: verified runtime behaviour\n\n" + facts + "\n"))

OUT.mkdir(exist_ok=True)
for name, tests in (("plain", plain), ("guide", teach)):
    suite = {"version": f"teacher-check-{name}", "description": "OPCD generate-gap teacher check",
             "judge_system_prompt": v5["judge_system_prompt"], "judge_instructions": v5["judge_instructions"],
             "tests": tests}
    (OUT / f"suite_{name}.json").write_text(json.dumps(suite, indent=1, ensure_ascii=False))
print(len(plain), "prompts;", "guide system prompt chars:", min(len(t["system_prompt"]) for t in teach),
      "-", max(len(t["system_prompt"]) for t in teach))
