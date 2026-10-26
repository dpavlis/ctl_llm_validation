"""DPO data for the rb1012 DPO isolation arms (spec/rb1012_dpo_isolation_brief.md).

All arms are cut from rb1012's built DPO file, which is rb1011's 2083 pairs plus the 25 lifecycle and 40 syntax pairs,
inserted in place with the order of rb1011's pairs preserved (checked below):
  A  rb1011's pairs, unchanged (byte-identical to rb1011's file)
  B  A + the 25 Rollup lifecycle validate pairs
  C  A + the 25 lifecycle + 40 syntax pitfalls pairs (= rb1012's DPO data)
  D  A + the 5 lifecycle pairs whose rejected answer says a nullable accumulator field starts at zero
     (category nullable_accumulator_claimed_zero in the set's validation log; source_index 4, 5, 12, 13, 19)
The eval split is rb1011's (identical to rb1012's). Writes data/sft_rebuild_20261025_dpoiso/ and copies the files into
~/LlamaFactory/data/, registering clover_dpo_dpoiso_{A,B,C,D}.

    ~/venv/bin/python data/build_dpoiso.py
"""
import hashlib, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LF = Path.home() / "LlamaFactory/data"
OUT = ROOT / "data/sft_rebuild_20261025_dpoiso"
R11 = ROOT / "data/sft_rebuild_20261018_rb1011/CTL_LoRA_DPO_data_rb1011.jsonl"
R12 = ROOT / "data/sft_rebuild_20261022_rb1012/CTL_LoRA_DPO_data_rb1012.jsonl"
EVAL = ROOT / "data/sft_rebuild_20261018_rb1011/CTL_LoRA_DPO_eval_rb1011.jsonl"
LIFE, SYN = "CTL_LoRA_DPO_rollup_lifecycle_validate.jsonl", "CTL_LoRA_DPO_syntax_pitfalls.jsonl"
ZERO = {4, 5, 12, 13, 19}

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
lines12 = R12.read_text().splitlines(keepends=True)
recs12 = [json.loads(l) for l in lines12]
recs11 = [json.loads(l) for l in R11.read_text().splitlines()]
key = lambda r: (r["prompt"], r["chosen"], r["rejected"])
old = [(l, r) for l, r in zip(lines12, recs12) if r["source_file"] not in (LIFE, SYN)]
assert [key(r) for _, r in old] == [key(r) for r in recs11], "rb1012 minus the new sets is not rb1011's pairs in order"
assert sum(r["source_file"] == LIFE for r in recs12) == 25 and sum(r["source_file"] == SYN for r in recs12) == 40

keep = {
    "A": lambda r: r["source_file"] not in (LIFE, SYN),
    "B": lambda r: r["source_file"] != SYN,
    "C": lambda r: True,
    "D": lambda r: r["source_file"] != SYN and (r["source_file"] != LIFE or r["source_index"] in ZERO),
}
OUT.mkdir(parents=True, exist_ok=True)
info = json.loads((LF / "dataset_info.json").read_text())
report = dict(source_rb1011=str(R11), source_rb1011_sha256=sha(R11), source_rb1012=str(R12), source_rb1012_sha256=sha(R12),
              eval=dict(dataset="clover_dpo_eval_rb1011", file=str(EVAL), sha256=sha(EVAL)), arms={})
for arm, f in keep.items():
    name = f"CTL_LoRA_DPO_data_dpoiso_{arm}.jsonl"
    sel = [(l, r) for l, r in zip(lines12, recs12) if f(r)]
    # A is rb1011's file byte for byte (its pair ids are rb1011's); the others are cut from rb1012's file
    (OUT / name).write_bytes(R11.read_bytes() if arm == "A" else "".join(l for l, _ in sel).encode())
    shutil.copyfile(OUT / name, LF / name)
    info[f"clover_dpo_dpoiso_{arm}"] = dict(file_name=name, ranking=True, columns=dict(
        prompt="prompt", system="system", chosen="chosen", rejected="rejected"))
    n = lambda s: sum(r["source_file"] == s for _, r in sel)
    report["arms"][arm] = dict(dataset=f"clover_dpo_dpoiso_{arm}", file=name, pairs=len(sel), sha256=sha(OUT / name),
                               lifecycle_pairs=n(LIFE), syntax_pairs=n(SYN),
                               lifecycle_source_index=sorted(r["source_index"] for _, r in sel if r["source_file"] == LIFE))
assert report["arms"]["A"]["sha256"] == report["source_rb1011_sha256"]
(LF / "dataset_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n")
(OUT / "build_report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({a: (v["pairs"], v["lifecycle_pairs"], v["syntax_pairs"]) for a, v in report["arms"].items()}))
