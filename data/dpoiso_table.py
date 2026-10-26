"""Results table for the rb1012 DPO isolation arms (spec/rb1012_dpo_isolation_brief.md), against rb1011, rb1012, rb1012s2.

Reads the stored test.py results (vLLM path, judge gpt-6.1-sol) and the hard-set-3 reports:
  T22 thinking off (all vllm_off files; n45 = validate x9 at n5): B1 WRONG, B4 / B5 CAUGHT
  T41 thinking on (T41 answers in vllm_on files, T40/T42-only files excluded): mean, B2 WRONG
  hard set 3 (data/opcd/hard_eval/<run>_set3/report.json, k4): wrong by kind
  validate thinking off excluding T18/T22: mean score, WRONG share of findings
  T40 / T42 thinking on below full score (files holding only T40/T42)
Differences against arm A carry a 95% CI: Newcombe (Wilson) for proportions, Welch normal for means. The WRONG share is
a share of findings, which cluster by answer, so its CI is optimistic.

    ~/venv/bin/python data/dpoiso_table.py [--hand B]     # --hand: print the T22 B1 WRONG answers of that arm
"""
import argparse, ast, collections, glob, json, math, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ["rb1011", "rb1012", "rb1012s2"] + [f"rb1011_dpoiso_{a}" for a in "ABCD"]
REF = "rb1011_dpoiso_A"


def tests(run, mode):
    out = []
    for f in sorted(glob.glob(str(ROOT / f"results/results_qwen38_{run}_vllm_{mode}_2*.json"))):
        out.append(json.load(open(f))["tests"])
    return out


def jr(t):
    j = t["judge_result"]
    return (ast.literal_eval(j) if isinstance(j, str) else j) or {}


def status(t, fid):
    return next((x.get("status") for x in jr(t).get("findings") or [] if x.get("id") == fid), None)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def newcombe(k1, n1, k0, n0):
    """95% CI of k1/n1 - k0/n0."""
    p1, p0 = k1 / n1, k0 / n0; l1, u1 = wilson(k1, n1); l0, u0 = wilson(k0, n0)
    return p1 - p0, p1 - p0 - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2), p1 - p0 + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)


def welch(x1, x0):
    m = lambda x: sum(x) / len(x)
    v = lambda x: sum((a - m(x)) ** 2 for a in x) / (len(x) - 1)
    d = m(x1) - m(x0); h = 1.96 * math.sqrt(v(x1) / len(x1) + v(x0) / len(x0))
    return d, d - h, d + h


def measure(run):
    off, on = tests(run, "off"), tests(run, "on")
    if not off and not on:
        return None
    r = {}
    t22 = [t for T in off for t in T if t["test_id"] == "T22"]
    r["T22_n"] = len(t22)
    for fid, st in (("T22.B1", "WRONG"), ("T22.B4", "CAUGHT"), ("T22.B5", "CAUGHT")):
        r[f"{fid}_{st}"] = sum(status(t, fid) == st for t in t22)
    vals, w = [], collections.Counter()
    for T in off:
        for t in T:
            if t["test_type"] == "validate" and t["test_id"] not in ("T18", "T22"):
                vals.append(float(t["numeric_score"]))
                for x in jr(t).get("findings") or []:
                    w[x.get("status")] += 1
    r["val"] = vals; r["val_wrong"] = (w["WRONG"], sum(w.values()))
    t41, t4 = [], []
    for T in on:
        ids = {t["test_id"] for t in T}
        if ids <= {"T40", "T42"}:
            t4 += T
        else:
            t41 += [t for t in T if t["test_id"] == "T41"]
    r["T41"] = [float(t["numeric_score"]) for t in t41]
    r["T41.B2_WRONG"] = sum(status(t, "T41.B2") == "WRONG" for t in t41)
    for tid in ("T40", "T42"):
        x = [t for t in t4 if t["test_id"] == tid]
        r[f"{tid}_below"] = (sum(float(t["numeric_score"]) < 1 for t in x), len(x))
    return r


def hard3(rep):
    d = json.load(open(rep))
    for v in ([d] + [x for x in d.values() if isinstance(x, dict)]):
        if "fail_by_kind" in v:
            return {k: tuple(map(int, s.split("/"))) for k, s in v["fail_by_kind"].items()}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--hand"); ap.add_argument("--out", default=str(ROOT / "results/dpoiso/table.json"))
    a = ap.parse_args()
    if a.hand:
        run = f"rb1011_dpoiso_{a.hand}" if len(a.hand) == 1 else a.hand
        for T in tests(run, "off"):
            for t in T:
                if t["test_id"] == "T22" and status(t, "T22.B1") == "WRONG":
                    note = next(x["note"] for x in jr(t)["findings"] if x["id"] == "T22.B1")
                    print(f"=== run {t['run']}  judge: {note}\n{t['mut_response']}\n")
        return
    M = {}
    for run in RUNS:
        m = measure(run)
        if m is None:
            continue
        rep = ROOT / f"data/opcd/hard_eval/{run}_set3/report.json"
        m["hard3"] = hard3(rep) if rep.exists() else None
        M[run] = m
    A = M.get(REF)
    rows = [
        ("T22 off: B1 WRONG (n)", lambda m: (m["T22.B1_WRONG"], m["T22_n"]), "p"),
        ("T22 off: B4 caught", lambda m: (m["T22.B4_CAUGHT"], m["T22_n"]), "p"),
        ("T22 off: B5 caught", lambda m: (m["T22.B5_CAUGHT"], m["T22_n"]), "p"),
        ("T41 on: mean (n)", lambda m: m["T41"], "m"),
        ("T41 on: B2 WRONG", lambda m: (m["T41.B2_WRONG"], len(m["T41"])), "p"),
        ("hard 3: nullable field wrong", lambda m: m["hard3"] and m["hard3"].get("acc_nullable_uninit"), "p"),
        ("hard 3: non-nullable wrong", lambda m: m["hard3"] and m["hard3"].get("acc_nonnullable_uninit"), "p"),
        ("hard 3: metadata default wrong", lambda m: m["hard3"] and m["hard3"].get("acc_metadata_default"), "p"),
        ("validate off x9 excl. T18/T22: mean (n)", lambda m: m["val"], "m"),
        ("validate off: WRONG findings", lambda m: m["val_wrong"], "p"),
        ("T40 on below full", lambda m: m["T40_below"], "p"),
        ("T42 on below full", lambda m: m["T42_below"], "p"),
    ]
    runs = list(M)
    print("| measure | " + " | ".join(runs) + " |"); print("|---" * (len(runs) + 1) + "|")
    table = {}
    for name, get, kind in rows:
        cells = []
        for run in runs:
            v = get(M[run])
            if not v or (kind == "p" and v[1] == 0) or (kind == "m" and not v):
                cells.append("–"); continue
            c = f"{v[0]}/{v[1]}" if kind == "p" else f"{sum(v) / len(v):.3f} ({len(v)})"
            if A and run != REF and get(A) and (kind == "m" or get(A)[1]):
                d = newcombe(v[0], v[1], *get(A)) if kind == "p" else welch(v, get(A))
                c += f"<br>{d[0]:+.2f} [{d[1]:+.2f}, {d[2]:+.2f}]"
                table.setdefault(name, {})[run] = dict(value=v if kind == "p" else sum(v) / len(v), n=v[1] if kind == "p" else len(v),
                                                       diff_vs_A=d)
            else:
                table.setdefault(name, {})[run] = dict(value=v if kind == "p" else sum(v) / len(v), n=v[1] if kind == "p" else len(v))
            cells.append(c)
        print(f"| {name} | " + " | ".join(cells) + " |")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(table, indent=1) + "\n")


if __name__ == "__main__":
    main()
