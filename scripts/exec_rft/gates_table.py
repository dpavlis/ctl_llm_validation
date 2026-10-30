"""Exec-RFT pilot gate table (spec/exec_rft_pilot_brief.md Step 4): exec_rft1 against c13c, same vLLM path and judge.

  execution pass rate, 11 gap tests, by status   results/exec/exec_scores.json (c13c 10-17) + results/exec_rft/gaps_*.json
  judge score on the same gap answers            the same records (judge_score)
  held-out pool, 40 prompts x 8                  c13c: results/exec_rft/samples_*.jsonl; exec_rft1: holdout_exec_rft1_*.jsonl
  T40 / T42 below full (on), T54 $out.1/$out.2 (off), validate off x9 excluding T18/T22 (mean, WRONG share),
  full v4 thinking on n5 (validate / fix / generate), hard sets 1-3 (data/opcd/hard_eval/<run>_set<n>/report.json)
Differences carry a 95% CI: Newcombe (Wilson) for proportions, Welch for means, per-prompt paired for the held-out pool.
Gap-test samples are treated as independent (10 per test), so those CIs are optimistic.

    ~/venv/bin/python scripts/exec_rft/gates_table.py > results/exec_rft/gates.md
"""
import ast, collections, glob, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import common as C  # noqa: E402
import report as R  # noqa: E402
from dpoiso_table import newcombe, welch, jr  # noqa: E402

ROOT = C.ROOT
RES = ROOT / "results"
FILES = {   # stored test.py results per run and gate
    "c13c": dict(off_x9=sorted(glob.glob(str(RES / "results_qwen38_vllm_opcdc13c_off_2*.json"))),
                 on_full=[str(RES / "results_qwen38_vllm_opcdc13c_on_20261017T200918Z.json")],
                 t40t42=[str(RES / "results_qwen38_vllm_opcdc13c_on_20261017T200316Z.json")],
                 t54=[str(RES / "results_qwen38_t54n20_c13c_off_20261021T163007Z.json")]),
    "valprec2": dict(off_x9=sorted(glob.glob(str(RES / "results_qwen38_vp_v4_valprec2_off_2*.json"))),   # candidate since 10-30
                     on_full=sorted(glob.glob(str(RES / "results_qwen38_vp_v4_valprec2_on_2*.json"))),
                     t40t42=sorted(glob.glob(str(RES / "results_qwen38_vp_t40t42_valprec2_on_2*.json"))),
                     t54=sorted(glob.glob(str(RES / "results_qwen38_vp_t54_valprec2_off_2*.json")))),
    "exec_rft1": dict(off_x9=sorted(glob.glob(str(RES / "results_qwen38_rft_v4_exec_rft1_off_2*.json"))),
                      on_full=sorted(glob.glob(str(RES / "results_qwen38_rft_v4_exec_rft1_on_2*.json"))),
                      t40t42=sorted(glob.glob(str(RES / "results_qwen38_rft_t40t42_exec_rft1_on_2*.json"))),
                      t54=sorted(glob.glob(str(RES / "results_qwen38_rft_t54_exec_rft1_off_2*.json")))),
}
STATUSES = ["pass", "wrong_rows", "init_error", "runtime_error", "invalid", "no_code"]


def tests(files):
    return [t for f in files for t in json.load(open(f))["tests"]]


def gap_records(run):
    """{mode: [records]} of the 11 gap tests: c13c = the 10-17 run plus today's two; exec_rft1 = its two runs."""
    p = RES / (f"validate_precision/gaps_{run}.json" if run.startswith("valprec") else f"exec_rft/gaps_{run}.json")
    recs = json.load(open(p))
    if run == "c13c":
        recs += [r for r in json.load(open(RES / "exec/exec_scores.json")) if "v5gaps_c13c_" in r["results_file"]]
    return {m: [r for r in recs if f"_{m}_" in r["results_file"] and "v5gaps" in r["results_file"]] for m in ("off", "on")}


def fmt_p(k, n):
    return f"{k}/{n} ({k / n:.3f})" if n else "–"


def fmt_d(d):
    return f"{d[0]:+.3f} ({d[1]:+.3f}, {d[2]:+.3f})"


def main():
    rows = []
    G = {run: gap_records(run) for run in FILES}
    for m in ("off", "on"):
        a, b = G["c13c"][m], G["exec_rft1"][m]
        ka, kb = sum(r["status"] == "pass" for r in a), sum(r["status"] == "pass" for r in b)
        per_run = {run: [round(sum(r["status"] == "pass" for r in G[run][m] if r["results_file"] == f) /
                               sum(r["results_file"] == f for r in G[run][m]), 3)
                         for f in sorted({r["results_file"] for r in G[run][m]})] for run in FILES}
        rows.append((f"gap tests {m}: execution pass rate (runs: {per_run['c13c']} / {per_run['exec_rft1']})",
                     fmt_p(ka, len(a)), fmt_p(kb, len(b)), fmt_d(newcombe(kb, len(b), ka, len(a)))))
        for st in STATUSES[1:]:
            sa, sb = sum(r["status"] == st for r in a), sum(r["status"] == st for r in b)
            if sa or sb:
                rows.append((f"  {m}: {st}", fmt_p(sa, len(a)), fmt_p(sb, len(b)), fmt_d(newcombe(sb, len(b), sa, len(a)))))
        ja, jb = [r["judge_score"] or 0 for r in a], [r["judge_score"] or 0 for r in b]
        rows.append((f"gap tests {m}: judge score (n)", f"{sum(ja) / len(ja):.3f} ({len(ja)})", f"{sum(jb) / len(jb):.3f} ({len(jb)})",
                     fmt_d(welch(jb, ja))))
    held = {r["id"] for r in C.read_jsonl(C.DATA / "holdout.jsonl")}
    for m in ("off", "on"):
        pa = R.per_prompt(C.read_jsonl(RES / f"exec_rft/samples_{m}.jsonl"), held)
        pb = R.per_prompt(C.read_jsonl(RES / f"exec_rft/holdout_exec_rft1_{m}.jsonl"))
        ka, na = sum(map(sum, pa.values())), sum(map(len, pa.values()))
        kb, nb = sum(map(sum, pb.values())), sum(map(len, pb.values()))
        d, ci, n = R.clustered_diff(pa, pb)
        rows.append((f"held-out pool {m}: pass rate (40 prompts x 8, paired by prompt)", fmt_p(ka, na), fmt_p(kb, nb),
                     f"{d:+.3f} ({ci[0]:+.3f}, {ci[1]:+.3f})"))
    M = {}
    for run, f in FILES.items():
        x = {}
        t4 = tests(f["t40t42"])
        for tid in ("T40", "T42"):
            s = [float(t["numeric_score"]) < 1 for t in t4 if t["test_id"] == tid]
            x[tid] = (sum(s), len(s))
        t54 = tests(f["t54"])
        x["T54"] = (sum(bool(re.search(r"\$out\.[12]\b", (t["mut_response"] or "").split("</think>")[-1])) for t in t54), len(t54))
        x["T54_mean"] = [float(t["numeric_score"]) for t in t54]
        vals, w = [], collections.Counter()
        for t in tests(f["off_x9"]):
            if t["test_type"] == "validate" and t["test_id"] not in ("T18", "T22"):
                vals.append(float(t["numeric_score"]))
                for fi in jr(t).get("findings") or []:
                    w[fi.get("status")] += 1
        x["val"], x["val_wrong"], x["val_files"] = vals, (w["WRONG"], sum(w.values())), len(f["off_x9"])
        on = tests(f["on_full"])
        for ty in ("validate", "fix", "generate"):
            x[f"on_{ty}"] = [float(t["numeric_score"]) for t in on if t["test_type"] == ty]
        for s in (1, 2, 3):
            rep = json.load(open(ROOT / f"data/opcd/hard_eval/{run}_set{s}/report.json"))
            v = next(v for v in [rep] + [y for y in rep.values() if isinstance(y, dict)] if "samples" in v)
            x[f"hard{s}"] = (round(v["trap_belief_answer"] * v["samples"]), v["samples"])
            if s == 3:
                x["hard3_kind"] = {k: tuple(map(int, s_.split("/"))) for k, s_ in v["fail_by_kind"].items()}
        M[run] = x
    A, B = M["c13c"], M["exec_rft1"]
    for tid in ("T40", "T42"):
        rows.append((f"{tid} thinking on: below full score", fmt_p(*A[tid]), fmt_p(*B[tid]), fmt_d(newcombe(*B[tid], *A[tid]))))
    rows.append(("T54 thinking off: answers writing $out.1/$out.2", fmt_p(*A["T54"]), fmt_p(*B["T54"]), fmt_d(newcombe(*B["T54"], *A["T54"]))))
    rows.append(("T54 thinking off: judge mean (n)", f"{sum(A['T54_mean']) / len(A['T54_mean']):.3f} ({len(A['T54_mean'])})",
                 f"{sum(B['T54_mean']) / len(B['T54_mean']):.3f} ({len(B['T54_mean'])})", fmt_d(welch(B["T54_mean"], A["T54_mean"]))))
    for s in (1, 2, 3):
        rows.append((f"hard set {s}: answers with a belief claim (k4)", fmt_p(*A[f"hard{s}"]), fmt_p(*B[f"hard{s}"]), ""))
    for k, name in (("acc_nullable_uninit", "nullable field wrong"), ("acc_nonnullable_uninit", "non-nullable wrong"),
                    ("acc_metadata_default", "metadata default wrong"), ("gen_first_record_sentinel", "first-record sentinel wrong")):
        if k in A["hard3_kind"]:
            rows.append((f"hard set 3: {name}", fmt_p(*A["hard3_kind"][k]), fmt_p(*B["hard3_kind"][k]),
                         fmt_d(newcombe(*B["hard3_kind"][k], *A["hard3_kind"][k]))))
    rows.append((f"validate off x{A['val_files']}/x{B['val_files']} excl. T18/T22: mean (n)", f"{sum(A['val']) / len(A['val']):.3f} ({len(A['val'])})",
                 f"{sum(B['val']) / len(B['val']):.3f} ({len(B['val'])})", fmt_d(welch(B["val"], A["val"]))))
    rows.append(("validate off: WRONG share of findings (CI optimistic: findings cluster by answer)", fmt_p(*A["val_wrong"]),
                 fmt_p(*B["val_wrong"]), fmt_d(newcombe(*B["val_wrong"], *A["val_wrong"]))))
    for ty in ("validate", "fix", "generate"):
        a, b = A[f"on_{ty}"], B[f"on_{ty}"]
        rows.append((f"thinking on, full v4 n5: {ty} mean (n)", f"{sum(a) / len(a):.3f} ({len(a)})", f"{sum(b) / len(b):.3f} ({len(b)})",
                     fmt_d(welch(b, a))))
    print("| gate | c13c | exec_rft1 (round 056) | difference, 95% CI |")
    print("|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")
    json.dump({k: {kk: vv for kk, vv in v.items()} for k, v in M.items()}, open(RES / "exec_rft/gates.json", "w"), indent=1)


if __name__ == "__main__":
    main()
