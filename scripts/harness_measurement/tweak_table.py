"""Part A of spec/harness_measurement_brief.md: c13c on the fresh-domain pool (pool_tweak) against pool 1.

Three pass rates per thinking mode, each from the agent_harness results files:
  first attempt              attempts[0] of the errors-only run
  after error feedback       final status of the errors-only run (2 rounds)
  after rows feedback        final status of the --rows-feedback run (2 rounds)
Pool 1 is reported whole (137 = 30 suite v5 + 107 corpus) and as its 107 corpus tasks, which are the closer comparison:
pool_tweak is rewritten from the same corpus sets.

CIs (95%) treat the task as the unit: per-task pass rate (mean over its runs), then the difference of the two pool means
with a Welch standard error. Runs of one task are not independent samples, so pooling them as n would be optimistic.

    ~/venv/bin/python scripts/harness_measurement/tweak_table.py > results/agent_harness/pool_tweak_vs_pool1.md
"""
import collections, json, math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results/agent_harness"
FILES = dict(pool1=("c13c_pool1.jsonl", "c13c_pool1_rows.jsonl"),
             tweak=("c13c_pool_tweak.jsonl", "c13c_pool_tweak_rows.jsonl"))
COMP = [("DataIntersection", r"INTERSECTION"), ("joiner (merge/hash join)", r"JOIN"), ("Rollup", r"ROLLUP"),
        ("Denormalizer", r"DENORMALIZER"), ("Normalizer", r"NORMALIZER"), ("Partition", r"PARTITION"),
        ("Reformat", r"REFORMAT|STANDALONE")]


def read(name):
    p = RES / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def comp(c):
    c = c.upper().replace(" ", "_")
    return next((n for n, pat in COMP if re.search(pat, c)), "other")


def per_task(recs, measure):
    """{task_id: mean over runs of measure(rec)}."""
    by = collections.defaultdict(list)
    for r in recs:
        by[r["task_id"]].append(float(measure(r)))
    return {k: sum(v) / len(v) for k, v in by.items()}


def mean_se(x):
    x = list(x)
    n = len(x)
    if n == 0:
        return float("nan"), float("nan"), 0
    m = sum(x) / n
    var = sum((v - m) ** 2 for v in x) / (n - 1) if n > 1 else 0.0
    return m, math.sqrt(var / n), n


def diff(a, b):
    """b - a with a 95% CI (normal approximation on per-task means)."""
    ma, sa, _ = mean_se(a.values())
    mb, sb, _ = mean_se(b.values())
    d, se = mb - ma, math.sqrt(sa ** 2 + sb ** 2)
    return d, d - 1.96 * se, d + 1.96 * se


MEASURES = dict(first=lambda r: r["first"] == "pass", errors=lambda r: r["final"] == "pass", rows=lambda r: r["final"] == "pass")


def cell(recs, key):
    t = per_task(recs, MEASURES[key])
    m, se, n = mean_se(t.values())
    return t, f"{m:.3f} ± {1.96 * se:.3f} ({n} tasks, {len(recs)} runs)" if n else "–"


def main():
    D = {p: dict(errors=read(f[0]), rows=read(f[1])) for p, f in FILES.items()}
    corpus = lambda rs: [r for r in rs if r["source"] != "suite_v5"]  # noqa: E731
    out = ["| mode | measure | pool 1 (137) | pool 1 corpus (107) | pool_tweak | tweak − pool 1 corpus, 95% CI | tweak − pool 1 |",
           "|---|---|---|---|---|---|---|"]
    for mode in ("off", "on"):
        for key, label in (("first", "first attempt"), ("errors", "after error feedback"), ("rows", "after rows feedback")):
            src = "rows" if key == "rows" else "errors"
            p1 = [r for r in D["pool1"][src] if r["mode"] == mode]
            tw = [r for r in D["tweak"][src] if r["mode"] == mode]
            t1, c1 = cell(p1, key)
            tc, cc = cell(corpus(p1), key)
            tt, ct = cell(tw, key)
            dc = diff(tc, tt) if tt and tc else None
            d1 = diff(t1, tt) if tt and t1 else None
            f = lambda d: f"{d[0]:+.3f} ({d[1]:+.3f}, {d[2]:+.3f})" if d else "–"  # noqa: E731
            out.append(f"| {mode} | {label} | {c1} | {cc} | {ct} | {f(dc)} | {f(d1)} |")
    out += ["", "### By component (after error feedback; first attempt in brackets)", "",
            "| component | mode | pool 1 corpus | pool_tweak |", "|---|---|---|---|"]
    for name, _ in COMP + [("other", None)]:
        for mode in ("off", "on"):
            cells = []
            for rs in (corpus(D["pool1"]["errors"]), D["tweak"]["errors"]):
                ms = [r for r in rs if r["mode"] == mode and comp(r["component"]) == name]
                if not ms:
                    cells.append("–")
                    continue
                fin = mean_se(per_task(ms, MEASURES["errors"]).values())
                fst = mean_se(per_task(ms, MEASURES["first"]).values())
                cells.append(f"{fin[0]:.2f} [{fst[0]:.2f}] ({fin[2]} tasks)")
            if cells != ["–", "–"]:
                out.append(f"| {name} | {mode} | {cells[0]} | {cells[1]} |")
    out += ["", "### Final status mix (errors-only run)", "", "| pool | mode | mix |", "|---|---|---|"]
    for p in ("pool1", "tweak"):
        for mode in ("off", "on"):
            mix = collections.Counter(r["final"] for r in D[p]["errors"] if r["mode"] == mode)
            out.append(f"| {p} | {mode} | " + ", ".join(f"{k} {v}" for k, v in mix.most_common()) + " |")
    out += ["", "### Compile / init error causes, all attempts of the errors-only run (share of attempts with a cause)", "",
            "| cause | pool 1 off | pool 1 on | pool_tweak off | pool_tweak on |", "|---|---|---|---|---|"]
    C = {}
    for p in ("pool1", "tweak"):
        for mode in ("off", "on"):
            att = [x for r in D[p]["errors"] if r["mode"] == mode for x in r["attempts"]]
            C[p, mode] = (collections.Counter(x["cause"] for x in att if x.get("cause")), len(att))
    for c in sorted({c for v, _ in C.values() for c in v}):
        out.append(f"| {c} | " + " | ".join(f"{C[k][0][c]} / {C[k][1]}" for k in
                                            [("pool1", "off"), ("pool1", "on"), ("tweak", "off"), ("tweak", "on")]) + " |")
    print("\n".join(out))


if __name__ == "__main__":
    sys.exit(main())
