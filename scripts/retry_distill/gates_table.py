#!/home/pavlisd/venv/bin/python
"""retry1 gate table (spec/retry_distill_brief.md, Gates): retry1 against c13c, same vLLM path and judge. The validate
ground-truth gates are score_validate.py's (results/retry_distill/gt_*.md).

  gap tests, execution pass rate by status   c13c: exec_rft's 3 x n10 (exec_rft/gates_table.gap_records); retry1: gaps_retry1.json
  harness pool 1 / pool_tweak                c13c: results/agent_harness/c13c_<pool>.jsonl; retry1: <run>_<pool>.jsonl
                                             first attempt = attempts[0] (the gate), final = after 2 feedback rounds (retry gain),
                                             first-attempt compile/init causes (§3.29 habits)
  T40 / T42 below full (on), T54 $out.1/$out.2 and judge (off), hard sets 1-3, validate off x9 excl. T18/T22
  (mean, WRONG share), full v4 thinking on n5 (validate / fix / generate)
Differences carry a 95% CI (Newcombe for proportions, Welch for means); samples are treated as independent.

    ~/venv/bin/python scripts/retry_distill/gates_table.py [RUN [LAST]] > results/retry_distill/gates_retry1.md
"""
import collections, glob, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/exec_rft"))
sys.path.insert(0, str(ROOT / "data"))
import gates_table as E  # noqa: E402
from dpoiso_table import newcombe, welch, jr  # noqa: E402

RES = ROOT / "results"
RUN = sys.argv[1] if len(sys.argv) > 1 else "retry1"
BASE = os.environ.get("BASELINE", "c13c")   # the comparison model: c13c (retry1's table) or valprec2 (the candidate since 10-30)
LAST = sys.argv[2] if len(sys.argv) > 2 else "066"
FILES = {BASE: E.FILES[BASE],
         RUN: dict(off_x9=sorted(glob.glob(str(RES / f"results_qwen38_rd_v4_{RUN}_off_2*.json"))),
                   on_full=sorted(glob.glob(str(RES / f"results_qwen38_rd_v4_{RUN}_on_2*.json"))),
                   t40t42=sorted(glob.glob(str(RES / f"results_qwen38_rd_t40t42_{RUN}_on_2*.json"))),
                   t54=sorted(glob.glob(str(RES / f"results_qwen38_rd_t54_{RUN}_off_2*.json"))))}
CAUSES = ("reserved_time_unit", "regex_negation", "ternary_constant", "wrong_arguments", "type_mismatch", "undeclared_variable",
          "unknown_field", "unknown_function", "other")


def gaps(run):
    if run in E.FILES and run != RUN:
        return E.gap_records(run)
    p = RES / f"retry_distill/gaps_{run}.json"
    recs = json.load(open(p)) if p.exists() else []
    return {m: [r for r in recs if f"_{m}_" in r["results_file"]] for m in ("off", "on")}


def harness(run, pool):
    """{mode: [records]} of one pool; c13c's stored runs or the run's merged file."""
    fs = [RES / f"agent_harness/{run}_{pool}.jsonl"]
    if run.startswith("valprec") and pool == "pool1":   # valprec2's pool 1 runs are stored per mode
        fs = [RES / f"agent_harness/{run}_pool1_first_{m}.jsonl" for m in ("off", "on")]
    out = collections.defaultdict(list)
    for f in fs:
        if f.exists():
            for l in open(f):
                r = json.loads(l)
                out[r["mode"]].append(r)
    return out


def out1(text):
    return bool(re.search(r"\$out\.[12]\b", (text or "").split("</think>")[-1]))


def main():
    rows, P = [], {}
    G = {run: gaps(run) for run in FILES}
    for m in ("off", "on"):
        a, b = G[BASE][m], G[RUN][m]
        if len(b) < 2:
            continue
        ka, kb = sum(r["status"] == "pass" for r in a), sum(r["status"] == "pass" for r in b)
        per_run = [round(sum(r["status"] == "pass" for r in b if r["results_file"] == f) / sum(r["results_file"] == f for r in b), 3)
                   for f in sorted({r["results_file"] for r in b})]
        rows.append((f"gap tests {m}: execution pass rate ({RUN} runs {per_run})", E.fmt_p(ka, len(a)), E.fmt_p(kb, len(b)),
                     E.fmt_d(newcombe(kb, len(b), ka, len(a)))))
        for st in E.STATUSES[1:]:
            sa, sb = sum(r["status"] == st for r in a), sum(r["status"] == st for r in b)
            if sa or sb:
                rows.append((f"  {m}: {st}", E.fmt_p(sa, len(a)), E.fmt_p(sb, len(b)), E.fmt_d(newcombe(sb, len(b), sa, len(a)))))
        ja, jb = [r["judge_score"] or 0 for r in a], [r["judge_score"] or 0 for r in b]
        rows.append((f"gap tests {m}: judge score (n)", f"{sum(ja) / len(ja):.3f} ({len(ja)})", f"{sum(jb) / len(jb):.3f} ({len(jb)})",
                     E.fmt_d(welch(jb, ja))))
    for pool in ("pool1", "pool_tweak"):
        H = {run: harness(run, pool) for run in FILES}
        for m in ("off", "on"):
            a, b = H[BASE][m], H[RUN][m]
            if not a or not b:
                continue
            fa, fb = [r["attempts"][0]["status"] for r in a], [r["attempts"][0]["status"] for r in b]
            rows.append((f"harness {pool} {m}: first-attempt pass rate", E.fmt_p(fa.count("pass"), len(fa)), E.fmt_p(fb.count("pass"), len(fb)),
                         E.fmt_d(newcombe(fb.count("pass"), len(fb), fa.count("pass"), len(fa)))))
            for st in ("compile_error", "wrong_rows"):
                rows.append((f"  {m}: first attempt {st}", E.fmt_p(fa.count(st), len(fa)), E.fmt_p(fb.count(st), len(fb)),
                             E.fmt_d(newcombe(fb.count(st), len(fb), fa.count(st), len(fa)))))
            la, lb = [r["final"] for r in a], [r["final"] for r in b]
            rows.append((f"harness {pool} {m}: final pass rate after 2 feedback rounds", E.fmt_p(la.count("pass"), len(la)), E.fmt_p(lb.count("pass"), len(lb)),
                         E.fmt_d(newcombe(lb.count("pass"), len(lb), la.count("pass"), len(la)))))
            ca = collections.Counter(r["attempts"][0].get("cause") for r in a if r["attempts"][0].get("cause"))
            cb = collections.Counter(r["attempts"][0].get("cause") for r in b if r["attempts"][0].get("cause"))
            for c in CAUSES:
                if ca[c] or cb[c]:
                    rows.append((f"  {m}: first-attempt cause {c}", E.fmt_p(ca[c], len(fa)), E.fmt_p(cb[c], len(fb)),
                                 E.fmt_d(newcombe(cb[c], len(fb), ca[c], len(fa)))))
            P[f"{pool}_{m}"] = dict(first=collections.Counter(fb), final=collections.Counter(lb), causes=dict(cb),
                                    c13c_first=collections.Counter(fa), c13c_final=collections.Counter(la), c13c_causes=dict(ca))
    M = {}
    for run, f in FILES.items():
        x = {}
        if f["t40t42"]:
            t4 = E.tests(f["t40t42"])
            for tid in ("T40", "T42"):
                s = [float(t["numeric_score"]) < 1 for t in t4 if t["test_id"] == tid]
                x[tid] = (sum(s), len(s))
        if f["t54"]:
            t54 = E.tests(f["t54"])
            x["T54"] = (sum(out1(t["mut_response"]) for t in t54), len(t54))
            x["T54_mean"] = [float(t["numeric_score"]) for t in t54]
        if f["off_x9"]:
            vals, w = [], collections.Counter()
            for t in E.tests(f["off_x9"]):
                if t["test_type"] == "validate" and t["test_id"] not in ("T18", "T22"):
                    vals.append(float(t["numeric_score"]))
                    for fi in jr(t).get("findings") or []:
                        w[fi.get("status")] += 1
            x["val"], x["val_wrong"], x["val_files"] = vals, (w["WRONG"], sum(w.values())), len(f["off_x9"])
        if f["on_full"]:
            on = E.tests(f["on_full"])
            for ty in ("validate", "fix", "generate"):
                x[f"on_{ty}"] = [float(t["numeric_score"]) for t in on if t["test_type"] == ty]
        for s in (1, 2, 3):
            p = ROOT / f"data/opcd/hard_eval/{run}_set{s}/report.json"
            if not p.exists():
                continue
            rep = json.load(open(p))
            v = next(v for v in [rep] + [y for y in rep.values() if isinstance(y, dict)] if "samples" in v)
            x[f"hard{s}"] = (round(v["trap_belief_answer"] * v["samples"]), v["samples"])
            if s == 3:
                x["hard3_kind"] = {k: tuple(map(int, s_.split("/"))) for k, s_ in v.get("fail_by_kind", {}).items()}
        M[run] = x
    A, B = M[BASE], M[RUN]
    for tid in ("T40", "T42"):
        if tid in B:
            rows.append((f"{tid} thinking on: below full score", E.fmt_p(*A[tid]), E.fmt_p(*B[tid]), E.fmt_d(newcombe(*B[tid], *A[tid]))))
    if "T54" in B:
        rows.append(("T54 thinking off n20: answers writing $out.1/$out.2", E.fmt_p(*A["T54"]), E.fmt_p(*B["T54"]), E.fmt_d(newcombe(*B["T54"], *A["T54"]))))
        rows.append(("T54 thinking off n20: judge mean (n)", f"{sum(A['T54_mean']) / len(A['T54_mean']):.3f} ({len(A['T54_mean'])})",
                     f"{sum(B['T54_mean']) / len(B['T54_mean']):.3f} ({len(B['T54_mean'])})", E.fmt_d(welch(B["T54_mean"], A["T54_mean"]))))
    for s in (1, 2, 3):
        if f"hard{s}" in B:
            rows.append((f"hard set {s}: answers with a belief claim (k4)", E.fmt_p(*A[f"hard{s}"]), E.fmt_p(*B[f"hard{s}"]), ""))
    for k, name in (("acc_nullable_uninit", "nullable field wrong"), ("acc_nonnullable_uninit", "non-nullable wrong"),
                    ("acc_metadata_default", "metadata default wrong"), ("gen_first_record_sentinel", "first-record sentinel wrong")):
        if k in A.get("hard3_kind", {}) and k in B.get("hard3_kind", {}):
            rows.append((f"hard set 3: {name}", E.fmt_p(*A["hard3_kind"][k]), E.fmt_p(*B["hard3_kind"][k]),
                         E.fmt_d(newcombe(*B["hard3_kind"][k], *A["hard3_kind"][k]))))
    if "val" in B:
        rows.append((f"validate off x{A['val_files']}/x{B['val_files']} excl. T18/T22: mean (n)", f"{sum(A['val']) / len(A['val']):.3f} ({len(A['val'])})",
                     f"{sum(B['val']) / len(B['val']):.3f} ({len(B['val'])})", E.fmt_d(welch(B["val"], A["val"]))))
        rows.append(("validate off: WRONG share of findings (CI optimistic: findings cluster by answer)", E.fmt_p(*A["val_wrong"]),
                     E.fmt_p(*B["val_wrong"]), E.fmt_d(newcombe(*B["val_wrong"], *A["val_wrong"]))))
    for ty in ("validate", "fix", "generate"):
        if f"on_{ty}" in B:
            a, b = A[f"on_{ty}"], B[f"on_{ty}"]
            rows.append((f"thinking on, full v4 n5: {ty} mean (n)", f"{sum(a) / len(a):.3f} ({len(a)})", f"{sum(b) / len(b):.3f} ({len(b)})",
                         E.fmt_d(welch(b, a))))
    print(f"| gate | {BASE} | {RUN} (round {int(LAST)}) | difference, 95% CI |")
    print("|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")
    json.dump({"models": M, "harness": P}, open(RES / f"retry_distill/gates_{RUN}.json", "w"), indent=1, default=lambda o: dict(o))


if __name__ == "__main__":
    main()
