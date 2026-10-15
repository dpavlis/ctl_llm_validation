"""Teacher check for the revised DataIntersection set (round 2b, ctl_lora_training d80aaa5): are the unhinted prompts a
usable OPCD signal? Same 60 prompts, judged against the run-verified answer, for
  - the c11 DataIntersection teacher (rb1006 adapter off + rulev3 + DataIntersection guide + ctl2-basics §8.9 + §13.3), and
  - the students c10 r019 (the next run's start) and c11 r023 (trained on the round-1, hinted prompts).

Writes data/opcd/teacher_check/suite_di2_teacher.json (teacher system prompt) and suite_di2_plain.json (plain prompt),
and the eval configs configs/eval_tcheck_di2_{teacher,c10,c11}_{on,off}.yaml.

    python data/opcd/build_di2_tcheck.py
"""
import json, re
from pathlib import Path
import yaml

R = Path(__file__).resolve().parents[2]
C = R / "ctl_lora_training/sft_training_data"
GUIDES = R / "data/suite_v5/round2"
KEEP = ("Description", "Purpose", "CTL2 contract", "Examples", "Common mistakes")
MARKER = "# Reference: the component you are writing for"
SYSTEM = ("You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean "
          "the same language.\nHelp users write, debug, and explain CTL2 code and related concepts. Provide working code, "
          "explanation, or both as needed.\nPrefer correct, practical, minimal solutions.\n")

# the c11 teacher block for DATA_INTERSECTION, as data/opcd/build_c11.py builds it
text = json.loads((GUIDES / "DATA_INTERSECTION_guide.json").read_text())["text"]
parts = re.split(r"(?m)^(?=## )", text)
guide = "\n\n".join([parts[0].strip()] + [p.strip() for p in parts[1:] if p[3:].startswith(KEEP)])
basics = (R / "resources/ctl2-basics.md").read_text()
facts = basics[basics.index("### 13.3"):basics.index("## 14.")].strip()
di_ref = basics[basics.index("### 8.9 DataIntersection"):basics.index("## 9. Graph Parameters")].strip()
block = f"\n{MARKER}\n\n{guide}\n\n{di_ref}\n\n# Reference: verified runtime behaviour\n\n{facts}\n"
rule = yaml.safe_load(open(R / "configs/eval_rb1006_rulev3_on.yaml"))["mut"]["generate"]["system_prompt"]

task = {m["id"]: {"generation": "generate", "explanation": "generate", "validation": "validate", "repair": "fix"}[m["task"]]
        for m in json.load(open(C / "logs/dataintersection_runtime/round2/manifest.json")) if m["kind"] == "sft"}
tests = []
for r in json.load(open(C / "CTL_LoRA_dataintersection_sft.json")):
    user = next(m["content"] for m in r["messages"] if m["role"] == "user")
    gold = next(m["content"] for m in r["messages"] if m["role"] == "assistant")
    tests.append({"test_id": r["id"], "type": task[r["id"]], "component": "DATA_INTERSECTION", "temperature": 0.4,
                  "system_prompt": SYSTEM, "user_message": user,
                  "rubric": {"description": "DataIntersection round 2b: judged against a run-verified reference answer",
                             "required": [
                                 {"id": f"{r['id']}.1", "check": "Reaches the same decisions and produces the same records or "
                                  "findings as this verified reference answer (equivalent CTL2 forms accepted):\n" + gold,
                                  "rationale": "The reference was compiled and run on the CloverDX server."},
                                 {"id": f"{r['id']}.2", "check": "Makes no claim about the component contract, ports, return "
                                  "values or CTL2 behaviour that contradicts the reference answer or ctl2-basics.md.",
                                  "rationale": "A correct result reached with a false explanation still teaches the wrong contract."}],
                             "forbidden": [], "scoring": {"method": "required_fraction", "forbidden_penalty": 0.2}}})

v5 = json.loads((R / "results/eval_snapshot_20261013/ctl2_test_suite_v5.json").read_text())
out = R / "data/opcd/teacher_check"
(out / "suite_di2_plain.json").write_text(json.dumps(dict(v5, version="di2-plain", tests=tests), indent=1, ensure_ascii=False))
(out / "suite_di2_teacher.json").write_text(json.dumps(dict(v5, version="di2-teacher", tests=[
    dict(t, system_prompt=rule + block) for t in tests]), indent=1, ensure_ascii=False))

for mode, port in (("on", 3012), ("off", 3011)):
    base = yaml.safe_load(open(R / f"configs/eval_tcheck_c11teacher_{mode}.yaml"))
    base["mut"].pop("validate", None)   # a config system_prompt would override the test's own (the teacher's)
    for name, model, suite in (("teacher", "rb1006", "teacher"), ("c10", "c10_r019", "plain"), ("c11", "c11_r023", "plain")):
        c = json.loads(json.dumps(base))
        c["mut"].update(vllm_model=model, vllm_url=f"http://127.0.0.1:{port}", run_label=f"qwen38_tcheck_di2_{name}_{mode}")
        c["suite_file"] = str(out / f"suite_di2_{suite}.json")
        with open(R / f"configs/eval_tcheck_di2_{name}_{mode}.yaml", "w") as fh:
            fh.write(f"# DataIntersection round-2b teacher check: {name} ({model}), thinking {mode.upper()} "
                     f"-- data/opcd/build_di2_tcheck.py\n")
            yaml.safe_dump(c, fh, sort_keys=False, allow_unicode=True)
from collections import Counter
print(len(tests), "tests", dict(Counter(t["type"] for t in tests)))
