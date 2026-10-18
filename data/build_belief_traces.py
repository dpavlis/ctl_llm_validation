"""Part B of spec/belief_durability_plan.md: sample the OPCD-corrected model's own answers on belief-relevant prompts, so the
next base rebuild (rb1010a/b) can carry the declaration-default fix in its SFT corpus.

The run directory is a regular self-distill run (data/self_distill/<run>/), so the strict self-distill filter and assembly
are reused unchanged:

  # 1. prompts (no GPU): belief prompt pool with reference answers -> prompts.jsonl, select_report.json
  python data/build_belief_traces.py select --run c13c_belief            # arm rb1010a
  python data/build_belief_traces.py select --run c13c_gaps --gaps-only  # arm rb1010b adds this run (no duplicate sampling)

  # 2. samples: the adapter on a vLLM server holding its base (e.g. rb1009 on :3011) -> samples.shard0.jsonl
  python data/build_belief_traces.py sample --run c13c_belief --config configs/opcd_c13c.yaml \
      --adapter data/opcd/c13c/round_015/adapter_vllm [--k 4] [--k-off 2]

  # 3. filter + assemble with self_distill.py (format, function library, compile via ctl_validate MCP, reference judge,
  #    thinking-claims audit, belief patterns; one accepted sample per prompt; <think>-tagged train file)
  python self_distill.py filter   --run c13c_belief --eval-config configs/eval_rb1006_vllm_on.yaml --judge-workers 8
  python self_distill.py assemble --run c13c_belief --cutoff 4096
  #    -> data/self_distill/c13c_belief/selfdistill_c13c_belief_train.json
  #       rb1010a: data/build_sft_rebuild.py ... --sd=c13c_belief:1
  #       rb1010b: data/build_sft_rebuild.py ... --sd=c13c_belief:1 --sd=c13c_gaps:1

Prompt pool (plan B1). Every prompt carries the corpus reference answer the judge compares against:
  - dpodef1 train split (206 belief-prone fix / validate prompts) and dpodef3b_plain (53 declaration-contrast prompts);
  - the corpus prompts of CTL_LoRA_fix_defaults_explained.json (80; its answers stay out of the rebuild),
    CTL_LoRA_declaration_defaults_contrast.json (55) and CTL_LoRA_fix_to_spec_explained.json (120);
  - the OPCD contrast prompts (data/opcd/contrast_prompts.jsonl: something really IS null), reference looked up by record id;
  - with --gaps (arm rb1010b): the c9 gap prompts and the revised DataIntersection prompts, with their verified references.
Excluded: eval data and suites v2-v5 (self_distill exclusion set) plus the frozen v5 snapshot, the 50 probe prompts, every
hard-case set (hard sets stay OPCD prompts and measures; set 2 and T42 must stay clean), duplicates.

Sampling (plan B2): plain student system prompt (no rule), eval sampling from the OPCD config's student configs; thinking ON
k per prompt; validate prompts also thinking OFF (k-off; their own prompt entry "<id>:off", so assembly keeps one of each).
Samples whose thinking or answer hits the OPCD belief scan are dropped here and logged (scan_rejects.jsonl); the
self_distill filter then applies its own belief patterns and the claims audit on top.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import self_distill as sd  # noqa: E402

C = sd.TRAIN_DIR
SNAPSHOT_SUITE = ROOT / "results/eval_snapshot_20261013/ctl2_test_suite_v5.json"
CORPUS_FILES = ("CTL_LoRA_fix_defaults_explained.json", "CTL_LoRA_declaration_defaults_contrast.json",
                "CTL_LoRA_fix_to_spec_explained.json")
HARD_FILES = ("data/opcd/hard_cases.jsonl", "data/opcd/hard_cases2.jsonl", "data/opcd/hard_cases3.jsonl")


def entry_from_record(rec: dict, fname: str, idx: int) -> dict | None:
    """A self-distill prompt entry (as self_distill.build_pool makes it) from one corpus record, or None."""
    split = sd._split_record(rec)
    if split is None:
        return None
    user, ref = split
    task = sd.classify_task(user, ref, rec.get("tags") or [])
    if task == "other":
        return None
    component, src = sd.resolve_component(rec, user)
    if not component:
        return None
    sent, added = sd.with_validate_format(user) if task == "validate" else (user, False)
    e = {"prompt_id": sd.make_prompt_id(user), "task_type": task, "component": component, "component_source": src,
         "compile_bucket": sd.compile_bucket_for(component, sd.main_ctl_block(ref) or sd.main_ctl_block(user)),
         "source_file": fname, "source_origin": "belief_pool", "source_index": idx, "record_id": rec.get("id"),
         "source_id": rec.get("source_id") or rec.get("id"), "tags": rec.get("tags") or [], "user": sent,
         "user_original": user, "format_instruction_added": added, "reference": ref}
    if task == "validate":
        parsed = sd.parse_validate_answer(ref)
        e["ref_findings"], e["ref_verdict"] = parsed["findings"], parsed["verdict"]
    elif task == "fix":
        e["fix_to_spec"], e["fix_score"] = "fix_code" in e["tags"], sd.fix_score(ref)
    return e


def cmd_select(args) -> int:
    out = sd.RUNS_DIR / args.run
    out.mkdir(parents=True, exist_ok=True)
    excluded, _ = sd.load_exclusion_set()
    for t in json.loads(SNAPSHOT_SUITE.read_text())["tests"]:
        excluded.add(sd.norm_ws(t["user_message"]))
    for f in HARD_FILES:
        for h in sd.read_jsonl(ROOT / f):
            excluded.add(sd.norm_ws(h["user"]))
    probe = [p for p in sd.read_jsonl(sd.RUNS_DIR / "dpodef1/prompts.jsonl") if p.get("split") == "probe"]
    excluded |= {sd.norm_ws(p.get("user_original") or p["user"]) for p in probe}

    rows, report = [], Counter()

    def add(e: dict | None, source: str) -> None:
        if e is None:
            report[f"{source}:unusable"] += 1
            return
        if not e.get("reference"):
            report[f"{source}:no_reference"] += 1
            return
        if sd.norm_ws(e.get("user_original") or e["user"]) in excluded:
            report[f"{source}:excluded"] += 1
            return
        rows.append(dict(e, belief_source=source))
        report[f"{source}:kept"] += 1

    belief = not args.gaps_only
    for p in sd.read_jsonl(sd.RUNS_DIR / "dpodef1/prompts.jsonl") if belief else []:
        if p.get("split") == "train":
            add(p, "dpodef1")
    for p in sd.read_jsonl(sd.RUNS_DIR / "dpodef3b_plain/prompts.jsonl") if belief else []:
        add(p, "dpodef3b")
    by_id = {}
    for f in sorted(C.glob("CTL_LoRA*.json")):
        for i, rec in enumerate(sd.read_records(f)):
            if rec.get("id"):
                by_id[(f.name, rec["id"])] = (rec, i)
    for fname in CORPUS_FILES if belief else ():
        for i, rec in enumerate(sd.read_records(C / fname)):
            add(entry_from_record(rec, fname, i), fname.replace("CTL_LoRA_", "").replace(".json", ""))
    for p in sd.read_jsonl(ROOT / "data/opcd/contrast_prompts.jsonl") if belief else []:
        hit = by_id.get((p.get("source_file"), p.get("record_id")))
        add(entry_from_record(hit[0], p["source_file"], hit[1]) if hit else None, "contrast")
    if args.gaps or args.gaps_only:
        # references: the run-verified gap references (generate_gaps.jsonl) and the DI corpus answers; the c9 gap holdouts
        # and the c12 DI holdouts are never drawn (gap holdouts stay a measure; c12_di.jsonl already omits its holdouts)
        gap_ref = {g["id"]: g.get("reference") for g in sd.read_jsonl(ROOT / "data/opcd/generate_gaps.jsonl")}
        gap_held = set(json.load(open(ROOT / "data/opcd/generate_gaps_c9_holdout.json"))["holdout"])
        di_ref = {r["id"]: sd._split_record(r)[1] for r in sd.read_records(C / "CTL_LoRA_dataintersection_sft.json")
                  if sd._split_record(r)}
        for f, src, refs in (("data/opcd/generate_gaps_c9.jsonl", "gaps", gap_ref), ("data/opcd/c12_di.jsonl", "di", di_ref)):
            for p in sd.read_jsonl(ROOT / f):
                if p["id"] in gap_held:
                    report[f"{src}:holdout"] += 1
                    continue
                sent, added = sd.with_validate_format(p["user"]) if p["task_type"] == "validate" else (p["user"], False)
                add({"prompt_id": sd.make_prompt_id(p["user"]), "task_type": p["task_type"], "component": p["component"],
                     "compile_bucket": sd.compile_bucket_for(p["component"], sd.main_ctl_block(refs.get(p["id"]) or "")),
                     "source_file": f, "record_id": p["id"], "source_id": p["id"], "tags": [], "user": sent, "user_original": p["user"],
                     "format_instruction_added": added, "reference": refs.get(p["id"])}, src)

    seen, dedup = set(), []
    for r in rows:
        if r["prompt_id"] in seen:
            report["duplicate"] += 1
            continue
        seen.add(r["prompt_id"]); dedup.append(r)
    # validate prompts get a second entry sampled thinking OFF (plan B2: thinking-off validate is what rb1008 damaged)
    offs = [dict(r, prompt_id=r["prompt_id"] + ":off", mode="off") for r in dedup if r["task_type"] == "validate"] \
        if args.k_off else []
    final = dedup + offs
    (out / "prompts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in final))
    rep = {"counts": dict(sorted(report.items())), "prompts": len(dedup), "off_entries": len(offs),
           "by_task": dict(Counter(r["task_type"] for r in dedup)), "by_source": dict(Counter(r["belief_source"] for r in dedup))}
    sd.write_json(out / "select_report.json", rep)
    print(json.dumps(rep, indent=1))
    print(f"-> {sd.rel(out / 'prompts.jsonl')}")
    return 0


def cmd_sample(args) -> int:
    import requests
    import opcd
    out = sd.RUNS_DIR / args.run
    prompts = sd.read_jsonl(out / "prompts.jsonl")
    cfg = opcd.load_cfg(args.config)
    roles = opcd.Roles(cfg)
    sampler = opcd.VllmSampler(cfg, roles)
    name = args.adapter_name or Path(args.adapter).parent.parent.name + "_" + Path(args.adapter).parent.name.replace("round_", "r")
    r = requests.post(f"{sampler.url}/v1/load_lora_adapter", json={"lora_name": name, "lora_path": str(Path(args.adapter).resolve())},
                      timeout=600)
    if r.status_code != 200 and "already" not in r.text:
        raise SystemExit(f"load_lora_adapter {name}: {r.status_code} {r.text[:200]}")
    sampler.current = name
    shard, rejects = out / "samples.shard0.jsonl", out / "scan_rejects.jsonl"
    done = {row["prompt_id"] for row in sd.read_jsonl(shard)} if shard.exists() else set()
    todo = [p for p in prompts if p["prompt_id"] not in done]
    print(f"{len(prompts)} prompts, {len(done)} sampled, {len(todo)} to go; adapter {name} on {sampler.url}")
    stats = Counter()
    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        jobs = [(dict(p, set="belief"), args.seed + int(sd.make_prompt_id(p["prompt_id"])[:8], 16) % 1_000_000) for p in batch]
        t0 = time.monotonic()
        res = []
        for (p, seed), k in zip(jobs, [args.k_off if p.get("mode") == "off" else args.k for p, _ in jobs]):
            res.append((p, seed, k))
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(sampler.workers) as ex:
            got = list(ex.map(lambda j: sampler._one(j[0], j[1], j[2], args.max_new), res))
        keep, drop = [], []
        for (p, seed, k), smps in zip(res, got):
            for s in smps:
                belief = opcd.scan_belief((s["thinking"] or "") + "\n" + (s["answer"] or ""))
                row = {"prompt_id": p["prompt_id"], "sample_idx": s["sample_idx"], "task_type": p["task_type"],
                       "mode": s["mode"], "thinking": s["thinking"] or "", "answer": s["answer"] or "",
                       "think_closed": s["think_closed"], "hit_cap": s["hit_cap"], "new_tokens": s["new_tokens"],
                       "seed": seed, "system_prompt": roles.system("student", s["mode"], p["task_type"]),
                       "sampling": {"k": k, **{kk: roles.sampling(p)[kk] for kk in ("temperature", "top_p", "top_k")}},
                       "teacher_model": f"{cfg['base_model']} + {name}", "sampled_at": sd.now_iso()}
                if belief:
                    drop.append(dict(row, scan_hits=[m.group(0) for m in belief][:3])); stats["scan_reject"] += 1
                else:
                    keep.append(row); stats["kept"] += 1
        sd.append_jsonl(shard, keep)
        if drop:
            sd.append_jsonl(rejects, drop)
        print(f"  [{i + len(batch)}/{len(todo)}] {time.monotonic() - t0:.0f}s  {dict(stats)}", flush=True)
    print(f"done: {dict(stats)} -> {sd.rel(shard)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("select")
    p.add_argument("--run", required=True)
    p.add_argument("--gaps", action="store_true", help="also the c9 gap and DI prompts")
    p.add_argument("--gaps-only", action="store_true", help="only the gap and DI prompts (arm rb1010b's second run)")
    p.add_argument("--k-off", type=int, default=2, help="0: no thinking-off validate entries")
    p = sub.add_parser("sample")
    p.add_argument("--run", required=True)
    p.add_argument("--config", default="configs/opcd_c13c.yaml", help="OPCD config: student prompts, sampling, sampler URL")
    p.add_argument("--adapter", required=True, help="the adapter_vllm directory to sample")
    p.add_argument("--adapter-name", default=None)
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--k-off", type=int, default=2)
    p.add_argument("--max-new", type=int, default=6144)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    return {"select": cmd_select, "sample": cmd_sample}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
