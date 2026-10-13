"""Check the round-2b rubric rewrites (rubric_rewrite_T*.json) and merge them into generate_rw.json.

    python data/suite_v5/round2/merge_rubric_rewrite.py [--write]

Without --write it only checks. Rules: rubric_rewrite_rules.md.
"""
import collections, json, re, sys
from pathlib import Path

D = Path(__file__).resolve().parent
SUITE = D.parent / "generate_rw.json"
BOILER = re.compile(r"numbered business contract|corresponding business obligation", re.I)

tests = json.loads(SUITE.read_text(encoding="utf-8"))
new = {}
for p in sorted(D.glob("rubric_rewrite_T*.json")):
    new.update(json.loads(p.read_text(encoding="utf-8")))

errors, notes = [], {}
for t in tests:
    tid = t["test_id"]
    r = new.get(tid)
    if r is None:
        errors.append(f"{tid}: no rewrite"); continue
    req, fb = r["required"], r["forbidden"]
    if not 8 <= len(req) <= 12: errors.append(f"{tid}: {len(req)} required items")
    if not 2 <= len(fb) <= 4: errors.append(f"{tid}: {len(fb)} forbidden items")
    want = [f"{tid}.{i}" for i in range(1, len(req) + 1)] + [f"{tid}.F{i}" for i in range(1, len(fb) + 1)]
    if [i["id"] for i in req + fb] != want: errors.append(f"{tid}: ids {[i['id'] for i in req + fb]}")
    clauses = re.findall(r"(?m)^(\d+)\. (.+)$", t["user_message"])
    covered = {c for i in req for c in i.get("clauses", [])}
    missing = [int(n) for n, _ in clauses if int(n) not in covered]
    if missing: errors.append(f"{tid}: clauses not covered {missing}")
    for i in req + fb:
        if not i.get("check") or not i.get("rationale"): errors.append(f"{i['id']}: empty check/rationale")
        if BOILER.search(i.get("rationale", "")): errors.append(f"{i['id']}: boilerplate rationale")
        if any(i["check"].strip()[:60] in text for _, text in clauses): errors.append(f"{i['id']}: copies a clause")
    if r.get("notes"): notes[tid] = r["notes"]

print(json.dumps({"errors": errors, "counts": {k: [len(v["required"]), len(v["forbidden"])] for k, v in new.items()}}, indent=1))
if errors or "--write" not in sys.argv:
    sys.exit(1 if errors else 0)
for t in tests:
    r = new[t["test_id"]]
    t["rubric"]["required"], t["rubric"]["forbidden"] = r["required"], r["forbidden"]
    if r.get("notes"): t["rubric_notes"] = r["notes"]
SUITE.write_text(json.dumps(tests, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("merged", len(tests))
