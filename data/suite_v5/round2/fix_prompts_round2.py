"""Round-2b prompt fixes (2026-10-13): remove clauses that give the trap away, drop expected-value hints
and comment requirements, and close the spec gaps the reviewers found. The rubric items that depended on
a gap are tightened to the now-stated behaviour (which the reference and its recorded run already follow).
Rewrites generate_rw.json in place; rebuild resources/ctl2_test_suite_v5.json after.
"""
import json
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "generate_rw.json"

PROMPT = [  # (test, old, new); old must occur exactly once
    # trap giveaways
    ("T65", " Resetting after all observations or before the next envelope are both valid; do not infer first-envelope "
            "detection from an uninitialized string/date being null.", ""),
    ("T67", " Use an explicit seen-valid flag because zero degrees and sample number zero are valid baseline values, "
            "not missing sentinels.", " Zero degrees and sample number zero are valid readings."),
    ("T73", " Use explicit accepted-history state, not null testing a default string/date.", ""),
    # T70: STOP / comment / expected-value hints
    ("T70", " Reset it before every line_no 1, even when the previous customer was incomplete in an earlier run. "
            "The first subtotal is 13.50, rather than null or an old accumulator value.", " It restarts with each customer."),
    ("T70", "A fresh component starts its row counter and subtotal state from zero. Do not reset the row counter at "
            "customer boundaries. Every successful generation returns an emitting result, including the last call; the "
            "component’s configured count also handles zero without manufacturing an initial row. Explain that "
            "ownership of row count in a code comment.",
            "The row numbering runs across customers; it does not restart at customer boundaries."),
    ("T70", " Generate exactly that configured population, with no CTL-driven abort or skipped generated row.",
            " Generate exactly that configured population."),
    # T71: STOP / comment / expected-value hints
    ("T71", " Successful final generation must not abort the graph.", ""),
    ("T71", " The first step is PARTIAL with level 9.00, and the fourth step overflows by 2.00.", ""),
    ("T71", ", and a code comment must state that configured recordsNumber owns termination", ""),
    # spec gaps
    ("T45", "Null, blank, time-bearing strings and shortened date digits fail;",
            "The text is not trimmed: surrounding whitespace, null, blank, time-bearing strings and shortened date digits fail;"),
    ("T46", "Null and empty fail DISPATCH, as do impossible dates or a timestamp suffix.",
            "The text is not trimmed. Null, empty and surrounding whitespace fail DISPATCH, as do impossible dates or a timestamp suffix."),
    ("T50", " Set reference_key to the normalized input carrier",
            " For every shipment, eligible or not, set reference_key to the normalized input carrier"),
    ("T52", "rounded half-up to two places", "rounded to two places with halves away from zero (2.505 to 2.51, -2.505 to -2.51)"),
    ("T68", "round half-up exactly once at the final result to two places",
            "round exactly once at the final result to two places, halves away from zero"),
    ("T68", "Otherwise return amount/budget*100 half-up rounded to two places",
            "Otherwise return amount/budget*100 rounded to two places with halves away from zero"),
    ("T55", "On repair rows settled_amount and remaining_amount are null even if some other quantity was usable.",
            "On repair rows settled_amount and remaining_amount are null even if some other quantity was usable; "
            "expected_amount is the invoice's value as read, or zero when there is no invoice."),
    ("T60", "A missing previous version gives null version fields on CANCELLED;",
            "is_current is false on CANCELLED and true on UNCHANGED. A missing previous version gives null version fields, "
            "including is_current, on CANCELLED;"),
    ("T66", "at most six integer digits", "one to six integer digits"),
]

RUBRIC = [  # (item id, old, new) in required/forbidden check text
    ("T45.8", " Trimming visit_day_txt first or not is both acceptable.", " visit_day_txt is not trimmed: \" 2026-04-01\" fails VISIT."),
    ("T46.9", " Trimming first or not is both acceptable.", " dispatch_txt is not trimmed: \" 20260101\" fails DISPATCH."),
    ("T50.11", "On a miss, reference_key is", "For every shipment (hit or miss), reference_key is"),
    ("T50.11", " Setting reference_key the same way on hits is also acceptable.", ""),
    ("T55.9", "(expected_amount is not graded on repair rows: invoice value, null or 0 are all accepted)",
              "and expected_amount the invoice's value as read (null for EXPECTED_NULL) or 0 when there is no invoice"),
    ("T60.8", " (is_current on UNCHANGED is not graded.)", " UNCHANGED has is_current true."),
]

tests = json.loads(P.read_text(encoding="utf-8"))
by_id = {t["test_id"]: t for t in tests}
for tid, old, new in PROMPT:
    m = by_id[tid]["user_message"]
    assert m.count(old) == 1, (tid, old)
    by_id[tid]["user_message"] = m.replace(old, new)
for iid, old, new in RUBRIC:
    t = by_id[iid.split(".")[0]]
    it = next(i for i in t["rubric"]["required"] + t["rubric"]["forbidden"] if i["id"] == iid)
    assert it["check"].count(old) == 1, (iid, old)
    it["check"] = it["check"].replace(old, new)
P.write_text(json.dumps(tests, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("applied", len(PROMPT), "prompt and", len(RUBRIC), "rubric fixes")
