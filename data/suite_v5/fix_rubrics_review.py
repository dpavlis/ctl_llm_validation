"""Rubric-only fixes from the 2026-10-13 review of generate_rw.json (prompts unchanged, so earlier
model answers can be re-judged). Rewrites generate_rw.json in place; rebuild resources/ctl2_test_suite_v5.json after.
"""
import json
from pathlib import Path

P = Path(__file__).with_name("generate_rw.json")

# (test ids, item suffix, old text, new text)
FIXES = [
    # nvl on the non-nullable ref is penalised by F3 already; do not also fail .2 for it
    (("T44", "T45", "T46"), ".2", " without a redundant null guard on that non-nullable field", ""),
    (("T50", "T51", "T52"), ".4", "with a null-safe record guard before dereference.",
     "with a null-safe guard before dereference (isnull(rec), rec == null, or count(...) > 0 before get)."),
    # owner run 4584 (2026-10-13): any non-SKIP return (OK/0, 1, ALL) emits the matched record on port 1; SKIP drops it
    (("T53", "T54", "T55"), ".1", "writes output 1 and returns 1 for emitted matched pairs.",
     "writes output 1 and returns any non-SKIP value (OK, 1 or ALL) for emitted matched pairs."),
    (("T56", "T57", "T58"), ".1", "Uses Denormalizer append/transform/clean with persistent winner state",
     "Uses Denormalizer append/transform with persistent winner state reset per group (in clean() or at the end of transform())"),
    (("T56", "T57", "T58"), ".F2", "Must not use epoch/null sentinels that skip the first candidate.",
     "Must not detect the first candidate by a sentinel value of the saved winner (e.g. its date being null or the epoch) instead of a flag or counter."),
    (("T56", "T57", "T58"), ".F3", "armed incorrectly after clean().", "armed incorrectly for the next group."),
    (("T59", "T60", "T61"), ".5", "no reset, current-before-next or lifecycle access.", "no reset or current-before-next."),
    (("T62", "T63"), ".F3", " or rely on nullable accumulator defaults", ""),
    (("T68", "T69"), ".F2", "for either public function.", "in canonicalCode or businessToken."),
    (("T70", "T71"), ".2", "Counter starts at zero and increments before use;",
     "The first row uses n=1 (counter from zero incremented before use, or any equivalent scheme);"),
    (("T72", "T73"), ".1", "strictly UTC-parsed RUN_TS", "RUN_TS parsed in UTC (strict flag optional)"),
]

tests = json.loads(P.read_text(encoding="utf-8"))
by_id = {t["test_id"]: t for t in tests}
for tids, suf, old, new in FIXES:
    for tid in tids:
        items = by_id[tid]["rubric"]["required"] + by_id[tid]["rubric"]["forbidden"]
        it = next(i for i in items if i["id"] == tid + suf)
        assert old in it["check"], (tid + suf, it["check"])
        it["check"] = it["check"].replace(old, new)
P.write_text(json.dumps(tests, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("applied", sum(len(f[0]) for f in FIXES), "item fixes")
