"""OPCD run c11 inputs: DataIntersection and SCD-2 prompt groups on top of c10 (findings §3.21, spec/scd2_training_set_brief.md).

Prompts are the user turns of the corpus sets ctl_lora_training/sft_training_data/CTL_LoRA_dataintersection_sft.json
and CTL_LoRA_scd2_sft.json (run-verified, owner's server). Their answers are never trained on directly: they are the
optional worked example in the teacher's prompt (field "worked_example"; opcd.py "teacher_context"), as in SDFT.

Writes
  configs/opcd_c11_teachers/guide_<COMP>_{on,off}.yaml   rulev3 + component guide (+ §8.9 for DataIntersection) + §13.3
  data/opcd/c11_di_scd.jsonl                             120 prompts with component, task_type, teacher, worked_example
  data/opcd/c11_holdout.json                             10 per group, never trained
  data/opcd/teacher_check/suite_c11_teacher.json         T53, T54, T60, T61 with the teacher's system prompt
  data/opcd/teacher_check/suite_c11_holdout.json         the 20 holdouts, judged against the verified answer

    python data/opcd/build_c11.py
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


def guide(name: str) -> str:
    text = json.loads((GUIDES / f"{name}_guide.json").read_text())["text"]
    parts = re.split(r"(?m)^(?=## )", text)
    return "\n\n".join([parts[0].strip()] + [p.strip() for p in parts[1:] if p[3:].startswith(KEEP)])


basics = (R / "resources/ctl2-basics.md").read_text()
facts = basics[basics.index("### 13.3"):basics.index("## 14.")].strip()
di_ref = basics[basics.index("### 8.9 DataIntersection"):basics.index("## 9. Graph Parameters")].strip()


def block(comp: str) -> str:
    extra = f"\n\n{di_ref}" if comp == "DATA_INTERSECTION" else ""
    return f"\n{MARKER}\n\n{guide(comp)}{extra}\n\n# Reference: verified runtime behaviour\n\n{facts}\n"


def component(text: str) -> str:
    """The component the prompt asks to write or judge: 'this <Component>' first, else the most specific mention."""
    names = {"normalizer": "NORMALIZER", "reformat": "REFORMAT", "rollup": "ROLLUP", "extmergejoin": "EXT_MERGE_JOIN",
             "exthashjoin": "EXT_HASH_JOIN", "dataintersection": "DATA_INTERSECTION"}
    m = re.search(r"(?i)\bthis (normalizer|reformat|rollup|extmergejoin|exthashjoin|dataintersection)\b", text)
    if m:
        return names[m.group(1).lower()]
    for k in ("normalizer", "reformat", "rollup", "extmergejoin", "exthashjoin", "dataintersection"):
        if re.search(rf"(?i)\b{k}\b", text):
            return names[k]
    return "DATA_INTERSECTION"   # conceptual SCD-2 flow questions: DataIntersection is the anchor


def task_of(user: str, kind: str | None) -> str:
    if kind:
        return {"explanation": "generate"}.get(kind, kind)
    u = re.sub(r"```.*?```", "", user, flags=re.S)
    if re.search(r"(?i)\b(fix|repair|correct) (this|the)\b", u):
        return "fix"
    if re.search(r"(?i)\b(validate|review) (this|the)\b", u):
        return "validate"
    return "generate"


scd_kind = {m["id"]: m["task_kind"] for m in json.load(open(C / "logs/scd2_runtime/manifest.json")) if m["kind"] == "sft"}
rows = []
for group, f in (("DI", "CTL_LoRA_dataintersection_sft.json"), ("SCD", "CTL_LoRA_scd2_sft.json")):
    for n, r in enumerate(json.load(open(C / f))):
        user = next(m["content"] for m in r["messages"] if m["role"] == "user")
        gold = next(m["content"] for m in r["messages"] if m["role"] == "assistant")
        comp = component(user)
        rows.append({"id": r["id"], "group": group, "task_type": task_of(user, scd_kind.get(r["id"])), "component": comp,
                     "teacher": f"guide11_{comp}", "user": user,
                     "worked_example": "# Worked example: a verified answer to this exact request\n\n" + gold,
                     "holdout": n % 6 == 5})

tdir = R / "configs/opcd_c11_teachers"
tdir.mkdir(exist_ok=True)
for comp in sorted({r["component"] for r in rows}):
    for mode in ("on", "off"):
        c = yaml.safe_load(open(R / f"configs/eval_rb1006_rulev3_{mode}.yaml"))
        for task in ("generate", "validate", "fix"):
            c["mut"][task]["system_prompt"] += block(comp)
        with open(tdir / f"guide_{comp}_{mode}.yaml", "w") as fh:
            fh.write(f"# OPCD c11 teacher guide_{comp}, thinking {mode.upper()}: rulev3 + CloverDX {comp} guide"
                     f"{' + ctl2-basics §8.9' if comp == 'DATA_INTERSECTION' else ''} + §13.3 -- data/opcd/build_c11.py\n")
            yaml.safe_dump(c, fh, sort_keys=False, allow_unicode=True)

with open(R / "data/opcd/c11_di_scd.jsonl", "w") as fh:
    for r in rows:
        fh.write(json.dumps({k: v for k, v in r.items() if k != "holdout"}, ensure_ascii=False) + "\n")
held = [r["id"] for r in rows if r["holdout"]]
(R / "data/opcd/c11_holdout.json").write_text(json.dumps({"holdout": held}, indent=1) + "\n")

# teacher check on the suite tests that measure these gaps (judge rubrics from the frozen v5 suite)
v5 = json.loads((R / "results/eval_snapshot_20261013/ctl2_test_suite_v5.json").read_text())
comp_of = {"T53": "DATA_INTERSECTION", "T54": "DATA_INTERSECTION", "T60": "NORMALIZER", "T61": "REFORMAT"}
rule = yaml.safe_load(open(R / "configs/eval_rb1006_rulev3_on.yaml"))["mut"]["generate"]["system_prompt"]
tests = [dict(t, system_prompt=rule + block(comp_of[t["test_id"]])) for t in v5["tests"] if t["test_id"] in comp_of]
(R / "data/opcd/teacher_check/suite_c11_teacher.json").write_text(json.dumps(
    dict(v5, version="c11-teacher-check", tests=tests), indent=1, ensure_ascii=False))

# holdout suite: the judge compares with the verified answer
ho = []
for r in rows:
    if not r["holdout"]:
        continue
    gold = r["worked_example"].split("\n\n", 1)[1]
    ho.append({"test_id": r["id"], "type": r["task_type"] if r["task_type"] != "fix" else "fix", "component": r["component"],
               "temperature": 0.4, "system_prompt": SYSTEM, "user_message": r["user"],
               "rubric": {"description": f"c11 holdout ({r['group']}): judged against a run-verified reference answer",
                          "required": [
                              {"id": f"{r['id']}.1", "check": "Reaches the same decisions and produces the same records or "
                               "findings as this verified reference answer (equivalent CTL2 forms accepted):\n" + gold,
                               "rationale": "The reference was compiled and run on the CloverDX server."},
                              {"id": f"{r['id']}.2", "check": "Makes no claim about the component contract, ports, return "
                               "values or CTL2 behaviour that contradicts the reference answer or ctl2-basics.md.",
                               "rationale": "A correct result reached with a false explanation still teaches the wrong contract."}],
                          "forbidden": [], "scoring": {"method": "required_fraction", "forbidden_penalty": 0.2}}})
(R / "data/opcd/teacher_check/suite_c11_holdout.json").write_text(json.dumps(
    dict(v5, version="c11-holdout", tests=ho), indent=1, ensure_ascii=False))
from collections import Counter
print(len(rows), "prompts,", len(held), "held out;", dict(Counter((r["group"], r["component"]) for r in rows)))
print("tasks", dict(Counter((r["group"], r["task_type"]) for r in rows)))

# split by group: the teacher check (T53/T54 +0.4..+0.5 with the guide teacher; T60/T61 -0.01..-0.18) puts the
# DataIntersection group on the guide-only teacher and the SCD-2 group on guide + worked example
for g, name in (("DI", "c11_di"), ("SCD", "c11_scd")):
    with open(R / f"data/opcd/{name}.jsonl", "w") as fh:
        for r in rows:
            if r["group"] == g:
                fh.write(json.dumps({k: v for k, v in r.items() if k != "holdout"}, ensure_ascii=False) + "\n")
