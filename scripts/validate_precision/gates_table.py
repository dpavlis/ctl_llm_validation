#!/home/pavlisd/venv/bin/python
"""valprec1 gate table (spec/validate_precision_brief.md, Gates): the generate, belief and judge gates against c13c, same
vLLM path and judge. The validate ground-truth gates are score_validate.py's (results/validate_precision/gt_*.md).

  gap tests, execution pass rate by status   c13c: exec_rft's 3 x n10 (gates_table.gap_records); valprec1: gaps_valprec1.json
  harness pool 1, first attempt              c13c: results/agent_harness/c13c_pool1.jsonl attempts[0]; valprec1: *_pool1_first_*.jsonl
  T40 / T42 below full (on), T54 $out.1/$out.2 and execution (off), hard sets 1-3, validate off x9 excl. T18/T22
  (mean, WRONG share), full v4 thinking on n5 (validate / fix / generate)
Differences carry a 95% CI (Newcombe for proportions, Welch for means); samples are treated as independent.

    ~/venv/bin/python scripts/validate_precision/gates_table.py [RUN] > results/validate_precision/gates_valprec1.md
"""
import collections, glob, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/exec_rft"))
sys.path.insert(0, str(ROOT / "data"))
import gates_table as E  # noqa: E402
from dpoiso_table import newcombe, welch, jr  # noqa: E402

RES = ROOT / "results"
RUN = sys.argv[1] if len(sys.argv) > 1 else "valprec1"
FILES = {"c13c": E.FILES["c13c"],
         RUN: dict(off_x9=sorted(glob.glob(str(RES / f"results_qwen38_vp_v4_{RUN}_off_2*.json"))),
                   on_full=sorted(glob.glob(str(RES / f"results_qwen38_vp_v4_{RUN}_on_2*.json"))),
                   t40t42=sorted(glob.glob(str(RES / f"results_qwen38_vp_t40t42_{RUN}_on_2*.json"))),
                   t54=sorted(glob.glob(str(RES / f"results_qwen38_vp_t54_{RUN}_off_2*.json"))))}


def gaps(run):
    if run == "c13c":
        return E.gap_records("c13c")
    recs = json.load(open(RES / f"validate_precision/gaps_{run}.json"))
    return {m: [r for r in recs if f"_{m}_" in r["results_file"]] for m in ("off", "on")}


def harness_first(run):
    f = RES / ("agent_harness/c13c_pool1.jsonl" if run == "c13c" else f"agent_harness/{run}_pool1_first_on.jsonl")
    fs = [f] if run == "c13c" else [f, RES / f"agent_harness/{run}_pool1_first_off.jsonl"]
    out = collections.defaultdict(list)
    for p in fs:
        for l in open(p):
            r = json.loads(l)
            out[r["mode"]].append(r["attempts"][0]["status"])
    return out


def main():
    rows = []
    G = {run: gaps(run) for run in FILES}
    for m in ("off", "on"):
        a, b = G["c13c"][m], G[RUN][m]
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
    H = {run: harness_first(run) for run in FILES}
    for m in ("off", "on"):
        a, b = H["c13c"][m], H[RUN][m]
        ka, kb = a.count("pass"), b.count("pass")
        rows.append((f"harness pool 1 {m}: first-attempt pass rate", E.fmt_p(ka, len(a)), E.fmt_p(kb, len(b)),
                     E.fmt_d(newcombe(kb, len(b), ka, len(a)))))
        for st in ("compile_error", "wrong_rows"):
            sa, sb = a.count(st), b.count(st)
            rows.append((f"  {m}: first attempt {st}", E.fmt_p(sa, len(a)), E.fmt_p(sb, len(b)), E.fmt_d(newcombe(sb, len(b), sa, len(a)))))
    M = {}
    for run, f in FILES.items():
        x = {}
        t4 = E.tests(f["t40t42"])
        for tid in ("T40", "T42"):
            s = [float(t["numeric_score"]) < 1 for t in t4 if t["test_id"] == tid]
            x[tid] = (sum(s), len(s))
        t54 = E.tests(f["t54"])
        x["T54"] = (sum(bool(re.search(r"\$out\.[12]\b", (t["mut_response"] or "").split("</think>")[-1])) for t in t54), len(t54))
        vals, w = [], collections.Counter()
        for t in E.tests(f["off_x9"]):
            if t["test_type"] == "validate" and t["test_id"] not in ("T18", "T22"):
                vals.append(float(t["numeric_score"]))
                for fi in jr(t).get("findings") or []:
                    w[fi.get("status")] += 1
        x["val"], x["val_wrong"], x["val_files"] = vals, (w["WRONG"], sum(w.values())), len(f["off_x9"])
        on = E.tests(f["on_full"])
        for ty in ("validate", "fix", "generate"):
            x[f"on_{ty}"] = [float(t["numeric_score"]) for t in on if t["test_type"] == ty]
        for s in (1, 2, 3):
            rep = json.load(open(ROOT / f"data/opcd/hard_eval/{run}_set{s}/report.json"))
            v = next(v for v in [rep] + [y for y in rep.values() if isinstance(y, dict)] if "samples" in v)
            x[f"hard{s}"] = (round(v["trap_belief_answer"] * v["samples"]), v["samples"])
            if s == 3:
                x["hard3_kind"] = {k: tuple(map(int, s_.split("/"))) for k, s_ in v.get("fail_by_kind", {}).items()}
        M[run] = x
    A, B = M["c13c"], M[RUN]
    for tid in ("T40", "T42"):
        rows.append((f"{tid} thinking on: below full score", E.fmt_p(*A[tid]), E.fmt_p(*B[tid]), E.fmt_d(newcombe(*B[tid], *A[tid]))))
    rows.append(("T54 thinking off: answers writing $out.1/$out.2", E.fmt_p(*A["T54"]), E.fmt_p(*B["T54"]), E.fmt_d(newcombe(*B["T54"], *A["T54"]))))
    for s in (1, 2, 3):
        rows.append((f"hard set {s}: answers with a belief claim (k4)", E.fmt_p(*A[f"hard{s}"]), E.fmt_p(*B[f"hard{s}"]), ""))
    for k, name in (("acc_nullable_uninit", "nullable field wrong"), ("acc_nonnullable_uninit", "non-nullable wrong"),
                    ("acc_metadata_default", "metadata default wrong"), ("gen_first_record_sentinel", "first-record sentinel wrong")):
        if k in A["hard3_kind"] and k in B["hard3_kind"]:
            rows.append((f"hard set 3: {name}", E.fmt_p(*A["hard3_kind"][k]), E.fmt_p(*B["hard3_kind"][k]),
                         E.fmt_d(newcombe(*B["hard3_kind"][k], *A["hard3_kind"][k]))))
    rows.append((f"validate off x{A['val_files']}/x{B['val_files']} excl. T18/T22: mean (n)", f"{sum(A['val']) / len(A['val']):.3f} ({len(A['val'])})",
                 f"{sum(B['val']) / len(B['val']):.3f} ({len(B['val'])})", E.fmt_d(welch(B["val"], A["val"]))))
    rows.append(("validate off: WRONG share of findings (CI optimistic: findings cluster by answer)", E.fmt_p(*A["val_wrong"]),
                 E.fmt_p(*B["val_wrong"]), E.fmt_d(newcombe(*B["val_wrong"], *A["val_wrong"]))))
    for ty in ("validate", "fix", "generate"):
        a, b = A[f"on_{ty}"], B[f"on_{ty}"]
        rows.append((f"thinking on, full v4 n5: {ty} mean (n)", f"{sum(a) / len(a):.3f} ({len(a)})", f"{sum(b) / len(b):.3f} ({len(b)})",
                     E.fmt_d(welch(b, a))))
    print(f"| gate | c13c | {RUN} (round 122) | difference, 95% CI |")
    print("|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")
    json.dump({k: {kk: vv for kk, vv in v.items()} for k, v in M.items()}, open(RES / f"validate_precision/gates_{RUN}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
