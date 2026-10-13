"""Prompt-wording fixes from the 2026-10-13 review of generate_rw.json (after the n5 baselines of rb1006/c4/c7,
which were run on the earlier wording). Rewrites generate_rw.json in place; rebuild resources/ctl2_test_suite_v5.json after.
"""
import json
from pathlib import Path

P = Path(__file__).with_name("generate_rw.json")

# (test ids, old text, new text) -- each old text must occur exactly once in the prompt
FIXES = [
    # the 12-digit cap read as an assurance, but the reference (and T.3) enforce it as a rule
    (("T44", "T45", "T46"), "Zero is accepted. Every accepted amount has at most 12 integer digits.",
     "Zero is accepted. Reject an amount with more than 12 integer digits; at least one digit must precede "
     "the decimal point, so \".5\" fails."),
    # meaningless for three scalar comparisons
    (("T53", "T54", "T55"), " One changed field appears once even when its value changed in several business interpretations.", ""),
    # "Required ... if supplied" contradicted itself
    (("T64", "T65"), "Required unexpected-error hooks, if supplied, must log",
     "Optional error hooks (countOnError, transformOnError), if supplied, must log"),
]
# T64/T65: name the JSON properties as literal keys
KEYS = {"T64": ("lines", "sku"), "T65": ("findings", "code")}
for tid, (arr, code) in KEYS.items():
    FIXES += [
        ((tid,), f"The root property {arr} may be", f"The root property \"{arr}\" may be"),
        ((tid,), f"is an object with {code} as a nonblank string", f"is an object with \"{code}\" as a nonblank string"),
        ((tid,), "may have a details object, missing or null. Inside details, note may be",
         "may have a \"details\" object, missing or null. Inside \"details\", \"note\" may be"),
        ((tid,), "Each child amount property is", "Each child's \"amount\" property is"),
    ]

tests = json.loads(P.read_text(encoding="utf-8"))
by_id = {t["test_id"]: t for t in tests}
for tids, old, new in FIXES:
    for tid in tids:
        m = by_id[tid]["user_message"]
        assert m.count(old) == 1, (tid, old)
        by_id[tid]["user_message"] = m.replace(old, new)
P.write_text(json.dumps(tests, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("applied", sum(len(f[0]) for f in FIXES), "prompt fixes")
