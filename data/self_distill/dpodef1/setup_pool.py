"""dpodef1 (spec/thinking_dpo_defaults_plan.md): prompt pool of corpus prompts whose code declares a
non-null-default variable without an initializer and uses it; 50 stratified held-out probe prompts;
reuse rb1006's fixpilot1007 samples, judgements and metadata for the prompts that have them."""
import json, random, re, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "/home/pavlisd/llama_train")
import self_distill as sd  # noqa: E402

RUN = Path(__file__).resolve().parent
PILOT = sd.RUNS_DIR / "fixpilot1007"
sd.FIX_TOPUP_FILES = sd.FIX_TOPUP_FILES + ("CTL_LoRA_fix_defaults_explained.json", "CTL_LoRA_fix_to_spec_explained.json")
excluded, _ = sd.load_exclusion_set()
pool, _ = sd.build_pool(excluded)
DECL = re.compile(r"^\s*(date|integer|long|decimal|number|boolean|string|[a-z]+\[\]|map\[[^\]]+\])\s+(\w+)\s*;", re.M)


def tempting(p):
    blocks = re.findall(r"```ctl\n(.*?)```", p["user"], re.S)
    if not blocks:
        return []
    code = blocks[-1]
    out = []
    for t, n in DECL.findall(code):
        rest = code.split(f"{n};", 1)[1] if f"{n};" in code else ""
        if re.search(rf"(?<![\w.])({n})\b(?!\s*=[^=])", rest):
            out.append("date" if t == "date" else "list/map" if "[" in t else "scalar")
    return sorted(set(out))


sel = []
for p in pool:
    ty = tempting(p)
    if ty and p["task_type"] in ("fix", "validate"):
        p = dict(p, decl_types=ty)
        sel.append(p)
# Stratified hold-out: 15 fix-defaults, 15 fix-explained, 20 others (8 validate).
rng = random.Random(1008)
def grp(p):
    if p["source_file"] == "CTL_LoRA_fix_defaults_explained.json": return "fixdef"
    if p["source_file"] == "CTL_LoRA_fix_to_spec_explained.json": return "fixexpl"
    return "other_" + p["task_type"]
by = defaultdict(list)
for p in sel: by[grp(p)].append(p)
quota = {"fixdef": 15, "fixexpl": 15, "other_validate": 8, "other_fix": 12}
probe = set()
for g, n in quota.items():
    for p in rng.sample(sorted(by[g], key=lambda x: x["prompt_id"]), min(n, len(by[g]))):
        probe.add(p["prompt_id"])
for p in sel:
    p["split"] = "probe" if p["prompt_id"] in probe else "train"
    p["selection_group"] = "dpodef1:" + grp(p)
(RUN / "prompts.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in sel))
# Reuse pilot samples / judgements / metadata for prompts that have them.
ids = {p["prompt_id"] for p in sel}
rows = [l for f in sorted(PILOT.glob("samples.shard*.jsonl")) for l in open(f) if json.loads(l)["prompt_id"] in ids]
(RUN / "samples.shard_reused.jsonl").write_text("".join(rows))
jud = [l for l in open(PILOT / "judged.jsonl") if json.loads(l)["prompt_id"] in ids]
(RUN / "judged.jsonl").write_text("".join(jud))
shutil.copy(PILOT / "metadata_synth.jsonl", RUN / "metadata_synth.jsonl")
reused = {json.loads(l)["prompt_id"] for l in rows}
print("prompts", len(sel), Counter(grp(p) for p in sel), "| probe", len(probe), Counter(grp(p) for p in sel if p["split"] == "probe"))
print("reused samples", len(rows), "for", len(reused), "prompts; judged rows", len(jud), "| to sample:", len(ids - reused))
sd.write_json(RUN / "select_report.json", {"created": sd.now_iso(), "plan": "spec/thinking_dpo_defaults_plan.md", "prompts": len(sel), "probe": sorted(probe), "teacher": "rb1006 (configs/eval_rb1006_on.yaml)"})
