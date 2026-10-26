"""Exec-RFT pilot tables: Step-2 yield (per mode: status distribution, per-prompt pass-count histogram, no-signal prompts,
init-error causes) and the execution gates (gap tests by status, held-out pool), with 95% confidence intervals.

    ~/venv/bin/python scripts/exec_rft/report.py yield results/exec_rft/samples_{off,on}.jsonl
    ~/venv/bin/python scripts/exec_rft/report.py gaps results/exec/exec_scores.json:c13c_o results/exec_rft/gaps_c13c.json results/exec_rft/gaps_exec_rft1.json
    ~/venv/bin/python scripts/exec_rft/report.py holdout results/exec_rft/samples_{off,on}.jsonl results/exec_rft/holdout_exec_rft1_{off,on}.jsonl
"""
import collections, json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import causes  # noqa: E402
import common as C  # noqa: E402

STATUSES = ["pass", "wrong_rows", "init_error", "runtime_error", "invalid", "no_code", "harness_error"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def diff_ci(k1, n1, k2, n2, z=1.96):
    """Difference of two proportions (2 - 1) with a normal-approximation 95% CI (samples treated as independent)."""
    p1, p2 = k1 / n1, k2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return round(p2 - p1, 3), (round(p2 - p1 - z * se, 3), round(p2 - p1 + z * se, 3))


def clustered_diff(a, b, z=1.96):
    """Difference of pass rates over the same prompts (b - a), CI from the per-prompt paired differences, so samples of
    one prompt are not counted as independent. a, b: {prompt: [0/1, ...]}."""
    ids = sorted(set(a) & set(b))
    d = [sum(b[i]) / len(b[i]) - sum(a[i]) / len(a[i]) for i in ids]
    m = sum(d) / len(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1)) if len(d) > 1 else 0.0
    se = sd / math.sqrt(len(d))
    return round(m, 3), (round(m - z * se, 3), round(m + z * se, 3)), len(ids)


def yield_table(files):
    out = {}
    for f in files:
        rows = C.read_jsonl(f)
        mode = rows[0]["mode"]
        by = collections.defaultdict(list)
        for r in rows:
            by[r["prompt_id"]].append(r["status"] == "pass")
        st = collections.Counter(r["status"] for r in rows)
        hist = collections.Counter(sum(v) for v in by.values())
        init = [(C.extract_code(r["answer"]), r["detail"], r.get("component")) for r in rows if r["status"] == "init_error"]
        k = max(len(v) for v in by.values())
        out[mode] = dict(samples=len(rows), prompts=len(by), pass_rate=round(st["pass"] / len(rows), 3),
                         status={s: st.get(s, 0) for s in STATUSES if st.get(s)},
                         pass_count_histogram={i: hist.get(i, 0) for i in range(k + 1)},
                         no_signal=dict(all_fail=hist.get(0, 0), all_pass=hist.get(k, 0)),
                         with_signal=sum(1 for v in by.values() if 0 < sum(v) < len(v)),
                         init_error_causes=causes.tally(init),
                         median_tokens=sorted(r["new_tokens"] for r in rows)[len(rows) // 2],
                         hit_cap=sum(bool(r.get("hit_cap")) for r in rows))
    return out


def per_prompt(rows, ids=None):
    by = collections.defaultdict(list)
    for r in rows:
        if ids is None or r["prompt_id"] in ids:
            by[r["prompt_id"]].append(int(r["status"] == "pass"))
    return by


if __name__ == "__main__":
    cmd, files = sys.argv[1], sys.argv[2:]
    if cmd == "yield":
        print(json.dumps(yield_table(files), indent=1))
