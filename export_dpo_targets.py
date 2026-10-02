"""Export rejected self-distillation samples of the weak groups as DPO-repair candidates.

The repair itself (a minimal correction of each sample, which becomes the chosen side of a
DPO pair) is done by another agent on another machine, from the ctl_lora_training repository
alone (brief: llama_train spec/dpo_targeted_repairs_spec.md). Everything that agent needs is therefore written
into one self-contained JSONL in that repository: the exact system and user prompt the model
saw, its thinking and answer, the corpus reference answer, and what the judge and the claims
audit reported.

Groups: fix_tier2 (CTL_LoRA_fix_this_code), validate_2 and validate_multi3 (reviews with 2 and
3+ findings). Samples rejected at the judge or claims stage only; format failures teach
formatting, and compile/library failures are caught without a judge.

    python export_dpo_targets.py [--out ctl_lora_training/sft_training_data/CTL_LoRAT_DPO_repair_candidates.jsonl]
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import self_distill as sd

GROUPS = ("fix_tier2", "validate_2", "validate_multi3")
RUNS = {  # run -> judge model that graded it
    "pilot1": "gpt-5.6-terra",
    "pilot2": "gpt-5.6-terra",
    "full1": "gpt-5.6-terra",
    "gen2pilot_fix6": "gpt-6-sol",
    "gen2pilot_sd1ep2": "gpt-6-sol",
    "gen2full": "gpt-6-sol",
}
REJECT_STAGES = ("judge", "claims")
JUDGE_LISTS = ("false_claims", "missing", "wrong_fixes", "severity_mismatches", "broken_requirements",
               "extra_findings", "compile_problems")
TEACHERS = {  # export path -> the name the spec uses
    "qwen38_fix6_sftdpo": "base",
    "qwen38_2x2_sd1ep2_on": "sd1ep2",
}
DEFAULT_OUT = sd.REPO_ROOT / "ctl_lora_training" / "sft_training_data" / "CTL_LoRAT_DPO_repair_candidates.jsonl"


def teacher_name(path: str) -> str:
    return TEACHERS.get(Path(path or "").name, Path(path or "").name)


def problems(judged: dict) -> dict:
    j = judged.get("judge") or {}
    out = {k: j[k] for k in JUDGE_LISTS if j.get(k)}
    c = judged.get("claims") or {}
    if c.get("answer_false_claims"):
        out["answer_false_claims"] = c["answer_false_claims"]
    if c.get("uncorrected_trace_false_claims"):
        out["trace_false_claims"] = c["uncorrected_trace_false_claims"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows, seen, skipped = [], set(), Counter()
    for run, judge_model in RUNS.items():
        out = sd.RUNS_DIR / run
        if not (out / "prompts.jsonl").exists():
            continue
        prompts = {p["prompt_id"]: p for p in sd.load_prompts(out)}
        samples = sd.load_samples(out)
        for key, j in sorted(sd.load_judged(out).items()):
            p = prompts[key[0]]
            group = p.get("selection_group") or sd.pilot_group(p)
            if group not in GROUPS:
                continue
            if j["accepted"] or j["rejected_at"] not in REJECT_STAGES:
                continue
            if p["record_id"] in sd.KNOWN_WRONG_REFERENCES:
                skipped["known wrong reference"] += 1
                continue
            s = samples[key]
            digest = hashlib.sha256((s["thinking"] + "\x00" + s["answer"]).encode()).hexdigest()[:16]
            if digest in seen:  # a reused sample judged again in a later run
                skipped["duplicate sample"] += 1
                continue
            seen.add(digest)
            rows.append({
                "id": f"dpocand_{p['prompt_id']}_{digest[:8]}",
                "prompt_id": p["prompt_id"],
                "group": group,
                "task_type": p["task_type"],
                "component": p["component"],
                "source_file": p["source_file"],
                "source_record_id": p["record_id"],
                "system": s["system_prompt"],
                "prompt": p["user"],
                "reference_answer": p["reference"],
                "model": teacher_name(s.get("teacher_model")),
                "reasoning_content": s["thinking"],
                "answer": s["answer"],
                "compile": j.get("compile"),
                "rejected_at": j["rejected_at"],
                "judge_model": judge_model,
                "judge_reason": (j.get("judge") or {}).get("reason"),
                "claims_reason": (j.get("claims") or {}).get("reason"),
                "problems": problems(j),
                "run": run,
            })

    rows.sort(key=lambda r: (GROUPS.index(r["group"]), r["prompt_id"], r["id"]))
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(json.dumps({
        "out": str(args.out),
        "candidates": len(rows),
        "prompts": len({r["prompt_id"] for r in rows}),
        "by_group": Counter(r["group"] for r in rows),
        "prompts_by_group": Counter(g for g, _ in {(r["group"], r["prompt_id"]) for r in rows}),
        "by_model": Counter(r["model"] for r in rows),
        "by_judge": Counter(r["judge_model"] for r in rows),
        "rejected_at": Counter(r["rejected_at"] for r in rows),
        "skipped": skipped,
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
