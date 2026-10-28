#!/home/pavlisd/venv/bin/python
"""Teacher contexts for the validate-precision OPCD run (spec/validate_precision_brief.md, Data 2-3).

Input: the review set from make_mutants.py --exec-rft (clean references and server-confirmed planted defects, each
with its server result). Output: an opcd.py hard file, one row per (review prompt, thinking mode):
  user             the review prompt exactly as B1's (make_mutants.build_prompt), no hint about the defect;
  system_extra     the suite's validate output format (gen_answers.FORMAT) on half the rows, empty on the other half;
                   each prompt gets the format in one mode and not in the other, alternating within each kind;
  teacher_context  the server's verdict on this code + the fact sheet (teacher only; opcd.Roles.ids);
  tag              review_clean / review_planted : fmt / plain (per-round stats).

Every fact in FACTS is in findings §7 or was run on the server; the source is noted next to each line here, not in the
prompt. Exclusions are re-checked: no task of pool 1 / pool_tweak, no exec-RFT holdout task, no code of B1 / B1-tweak.

    ~/venv/bin/python scripts/validate_precision/build_context.py
"""
import argparse, collections, hashlib, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/harness_measurement"))
sys.path.insert(0, str(ROOT))
from gen_answers import FORMAT  # noqa: E402
import self_distill as sd  # noqa: E402

FACTS = "\n".join([
    "Verified CTL2 facts (CloverDX server runs and owner rulings):",
    # §7 "Rollup lifecycle" (runs 21965-21968)
    "- A Rollup transform must define all five functions initGroup, updateGroup, finishGroup, updateTransform and "
    "transform; if any is missing the component fails at initialization (\"Required function(s) ... are missing!\").",
    # §3.35 probes rollup_acc 007/018 (results/agent_harness/control_probes.json): batch_group 1, 2, 3
    "- initGroup runs once per group, when the group's first record arrives, before updateGroup sees that record. A "
    "global counter that starts at 0 and is incremented in initGroup numbers the first group 1, the second 2.",
    # §7 "Rollup accumulator" (corrected 2026-10-22); §3.35 probes: counts, peaks and positions reset per group
    "- The accumulator record is reset from its metadata before each group: a nullable field without assignment is "
    "null, a non-nullable field is zero (or its metadata default). Arithmetic or ++ on a non-nullable accumulator field "
    "needs no initialization, and accumulator values do not carry into the next group. Global variables keep their "
    "value until the code assigns them; a global reset in initGroup starts each group fresh.",
    # §7 DataIntersection (2026-10-13, live runs; ctl2-basics §8.9)
    "- DataIntersection: input 0 is A, input 1 is B. The CTL transform writes $out.0, which the component sends out on "
    "port 1 (matched records); ports 0 (A only) and 2 (B only) are pass-through. Writing $out.1 or $out.2 in the "
    "transform fails at initialization.",
    # ctl2-basics §13.3 (run 18244); probe ms_diff_dst: 48 h across the 2026-03-29 change
    "- Millisecond date arithmetic (date2long differences, dateAdd(d, n, millisec)) is exact UTC time and has no "
    "daylight-saving shift. dateAdd(d, n, day) and date functions without a time-zone argument use the server's zone.",
    # probes int_gt_null, dec_gt_null, date_lt_null, if_null_gt, null_vs_null_gt, int_plus_null, dec_plus_null,
    # null_local_plus_one, not_null_bool, if_null_bool (NullPointerException); int_eq_null, int_ne_null, str_eq_null
    # (false / true / false); assign_null_*_local, assign_null_out (assigned); str_concat_null ("anullb")
    "- Null values: <, >, <=, >=, arithmetic, ! and an if on a null value throw at runtime; == and != with null do not "
    "throw (null == 5 is false); assigning null to a local variable or a nullable field is allowed; string + null "
    "appends \"null\".",
    # probes dec_div_int 3.75, dec_gt_int_literal true, dec_times_int 52.50, int_div_dec 3.5, int_div_int 3,
    # long_div_int 3, num_div_int 3.75
    "- Numbers: a decimal divided by an integer is a decimal (7.50 / 2 = 3.75); a decimal compared with an integer "
    "literal compiles and compares numerically; integer / integer and long / integer truncate (7 / 2 = 3).",
    # §7 severity ruling (memory ctl2-severity-error-vs-warning)
    "- Severity: ERROR is a compile error, a failure that happens on the stated inputs, or a violation of a stated "
    "requirement. A risk that depends on data the task does not describe (for example a null in a nullable field the "
    "requirements do not mention) is a WARNING, never an ERROR.",
])

CLEAN = ("This code was compiled and run on the CloverDX server against the task's fixture ({n} input rows) and produced "
         "exactly the required output rows. Report an [ERROR] only for a violation of a stated requirement or a compiler "
         "rule that you can point to in the code; a run that met the requirements cannot have one. Do not invent inputs "
         "the task does not describe. If nothing qualifies, answer ISSUES: none, VERDICT: PASS.")
PLANTED = ("This code was run on the CloverDX server: {status}: {detail}. Find the statement responsible and report it "
           "as the finding; do not report anything else as an ERROR unless you can point to it.")
STATUS = {"invalid": "graph validation failed", "init_error": "the component failed at initialization",
          "runtime_error": "the run failed", "wrong_rows": "the run finished with wrong output rows"}


def detail(r):
    d = r["server_detail"].strip()
    d = d.replace("Graph validation failed: ", "")
    return " ".join(d.split())[:500]


def sha(code):
    return hashlib.sha256(code.strip().encode()).hexdigest()


def main(a):
    recs = [json.loads(l) for l in Path(a.review).read_text().splitlines() if l.strip()]
    # exclusions (Do not: pool 1, pool_tweak, B1, B1-tweak, the exec-RFT holdout)
    bad_tasks = {json.loads(l)["id"] for f in ("data/agent_harness/pool1.jsonl", "data/agent_harness/pool_tweak.jsonl",
                                                "data/exec_rft/holdout.jsonl") for l in (ROOT / f).read_text().splitlines() if l.strip()}
    gt = [json.loads(l) for f in ("data/agent_harness/validate_mutants.jsonl", "data/agent_harness/validate_mutants_tweak.jsonl")
          for l in (ROOT / f).read_text().splitlines() if l.strip()]
    bad_code = {sha(r["code"]) for r in gt}
    bad_prompt = {sd.make_prompt_id(r["prompt"]) for r in gt}
    assert not {r["task_id"] for r in recs} & bad_tasks, "review set contains an excluded task"
    assert not {sha(r["code"]) for r in recs} & bad_code, "review set contains B1 / B1-tweak code"
    assert not {sd.make_prompt_id(r["prompt"]) for r in recs} & bad_prompt, "review prompt equals a B1 / B1-tweak prompt"

    rng = random.Random(a.seed)
    by_kind = collections.defaultdict(list)
    for r in sorted(recs, key=lambda r: r["id"]):
        by_kind[r["kind"]].append(r)
    rows = []
    for kind, rs in sorted(by_kind.items()):
        rng.shuffle(rs)
        for i, r in enumerate(rs):
            clean = kind == "control"
            verdict = CLEAN.format(n=r["input_rows"]) if clean else \
                PLANTED.format(status=STATUS[r["server_status"]], detail=detail(r))
            fmt_mode = "on" if i % 2 == 0 else "off"   # the mode in which this prompt carries the output format
            for mode in ("on", "off"):
                fmt = mode == fmt_mode
                rows.append(dict(id=f"vp_{r['id']}:{mode}", task_type="validate", component=r["component"],
                                 source_file=f"exec_rft:{r['source']}", record_id=r["task_id"], user=r["prompt"],
                                 prompt_id=f"{sd.make_prompt_id(r['prompt'] + ('|fmt' if fmt else ''))}:{mode}", mode=mode,
                                 system_extra=FORMAT if fmt else "", teacher_context=verdict + "\n\n" + FACTS,
                                 tag=f"review_{'clean' if clean else 'planted'}:{'fmt' if fmt else 'plain'}",
                                 kind=kind, server_status=r["server_status"], anchor=r["anchor"]))
    out = Path(a.out)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    rep = dict(prompts=len(recs), rows=len(rows),
               by_kind=collections.Counter(r["kind"] for r in recs),
               by_kind_component={k: collections.Counter(r["component"] for r in v) for k, v in sorted(by_kind.items())},
               by_tag_mode=collections.Counter(f"{x['tag']}:{x['mode']}" for x in rows),
               by_server_status=collections.Counter(f"{r['kind']}:{r['server_status']}" for r in recs),
               context_chars=dict(min=min(len(x["teacher_context"]) for x in rows), max=max(len(x["teacher_context"]) for x in rows)),
               facts_chars=len(FACTS))
    out.with_suffix(".report.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default=str(ROOT / "data/validate_precision/review_mutants.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data/validate_precision/review_prompts.jsonl"))
    ap.add_argument("--seed", type=int, default=0)
    main(ap.parse_args())
