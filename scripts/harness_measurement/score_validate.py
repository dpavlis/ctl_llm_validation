#!/home/pavlisd/venv/bin/python
"""Judge-free scoring of validate answers against the ground-truth records (spec/harness_measurement_brief.md Part B).

Parser only, no LLM. From each answer: the last `VERDICT: PASS|FAIL`, and the ISSUES lines `[ERROR]` / `[WARNING]`
(`[INFO]` lines are not findings). Measures, per model and thinking mode:
  verdict accuracy     VERDICT against the truth (a missing VERDICT counts as wrong)
  defect recall        planted mutant: some finding names the anchor (case-insensitive, backticks optional);
                       corpus FAIL record: share of the reference's issue lines whose anchor set some finding names
  severity accuracy    planted mutant: the first finding naming the anchor has the expected severity (§7); the
                       inverted-condition kind accepts either and is reported apart
  false alarm          control / corpus PASS record: any [ERROR] finding (and, separately, VERDICT FAIL)
  findings per answer  and, on one-defect mutants, findings that name no anchor (precision proxy)
CIs: Wilson for a proportion over answers; for model differences a paired bootstrap over records (2000 resamples),
which keeps the runs of one record together.

    ~/venv/bin/python scripts/harness_measurement/score_validate.py c13c rb1011 rb1011s2 rb1012 \
        [--out results/agent_harness/validate_gt_table.md]
"""
import argparse, collections, json, math, random, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORDS = [ROOT / "data/agent_harness/validate_mutants.jsonl", ROOT / "data/agent_harness/validate_corpus.jsonl"]
ISSUE_RE = re.compile(r"^\s*(?:[-*\d.)]+\s*)?\**\[(ERROR|WARNING|INFO)\]\**\s*(.*)$", re.M)


def parse(answer, strict=False):
    """(verdict, findings). Thinking-on answers often drop the VERDICT line; unless strict, the verdict then falls back
    to a bare PASS/FAIL line, else FAIL when there is an [ERROR]/[WARNING] finding and PASS otherwise."""
    text = answer or ""
    v = re.findall(r"VERDICT\**\s*:?\s*\**\s*(PASS|FAIL)", text, re.I)
    sect = re.split(r"^\s*\**SUGGESTIONS\**\s*:?\s*\**\s*$", text, flags=re.M)[0]
    finds = [(s.upper(), t) for s, t in ISSUE_RE.findall(sect) if s.upper() != "INFO"]
    if v:
        return v[-1].upper(), finds
    if strict:
        return None, finds
    bare = re.findall(r"(?m)^\W*(PASS|FAIL)\W*$", text)
    return (bare[-1] if bare else ("FAIL" if finds else "PASS")), finds


def names(line, res):
    plain = line.replace("`", "")
    # a dotted prefix is allowed (`$in.0.height` names `height`); records built before that fix had (?<![\w.])
    return any(re.search(r.replace(r"(?<![\w.])", r"(?<!\w)"), plain, re.I) for r in res)


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def score_one(rec, ans):
    """Per-answer measures (None where a measure does not apply)."""
    v, finds = parse(ans)
    m = dict(verdict_ok=v == rec["truth"], no_verdict=parse(ans, strict=True)[0] is None, n_find=len(finds),
             n_error=sum(s == "ERROR" for s, _ in finds))
    if rec["truth"] == "PASS":
        m.update(false_alarm=m["n_error"] > 0, fail_verdict=v == "FAIL")
    elif "anchor_res" in rec:          # planted mutant
        hit = [(s, t) for s, t in finds if names(t, rec["anchor_res"])]
        m["recall"] = bool(hit)
        # lenient: the anchor named anywhere in the prose (code blocks removed), tagged finding or not
        m["mention"] = names(re.sub(r"```.*?(```|$)", " ", ans or "", flags=re.S), rec["anchor_res"])
        m["extra"] = len(finds) - len(hit)
        if hit:
            exp = rec["severity"]
            m["sev_ok"] = hit[0][0] in exp.split("|")
            m["sev_got"] = hit[0][0]
    else:                               # corpus FAIL: issue-level recall
        got = [any(names(t, [r for a in iss["anchors"] for r in a["anchor_res"]]) for _, t in finds) for iss in rec["issues"]]
        m["recall"] = sum(got) / len(got)
        m["recall_all"] = all(got)
    return m


def load(model):
    p = ROOT / f"results/agent_harness/validate_gt_{model}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def agg(rows, key, pred=lambda m: True):
    xs = [m[key] for m in rows if key in m and m[key] is not None and pred(m)]
    if not xs:
        return None
    if isinstance(xs[0], bool):
        k = sum(xs); lo, hi = wilson(k, len(xs))
        return dict(p=k / len(xs), n=len(xs), lo=lo, hi=hi)
    return dict(p=sum(xs) / len(xs), n=len(xs))


def fmt(a, pct=True):
    if not a:
        return "–"
    if "lo" in a:
        return f"{a['p']:.2f} [{a['lo']:.2f}, {a['hi']:.2f}] ({a['n']})"
    return f"{a['p']:.2f} ({a['n']})"


def boot_diff(S, m1, m0, mode, key, sel, B=2000, seed=0):
    """Paired bootstrap over records of mean(key | m1) - mean(key | m0): per-record means of the runs."""
    def per_rec(model):
        d = collections.defaultdict(list)
        for (mod, md, rid), m in S.items():
            if mod == model and md == mode and key in m and m[key] is not None and sel(rid):
                d[rid].append(float(m[key]))
        return {k: sum(v) / len(v) for k, v in d.items()}
    a, b = per_rec(m1), per_rec(m0)
    ids = sorted(set(a) & set(b))
    if not ids:
        return None
    rng = random.Random(seed)
    diffs = []
    for _ in range(B):
        s = [rng.choice(ids) for _ in ids]
        diffs.append(sum(a[i] - b[i] for i in s) / len(s))
    diffs.sort()
    return sum(a[i] - b[i] for i in ids) / len(ids), diffs[int(0.025 * B)], diffs[int(0.975 * B)], len(ids)


def main(a):
    recs = {r["id"]: r for f in RECORDS if f.exists() for r in map(json.loads, f.read_text().splitlines())}
    S = {}             # (model, mode, rid) -> list of per-answer measures; flattened below
    rows = collections.defaultdict(list)
    for model in a.models:
        for x in load(model):
            if x.get("answer") is None or x["id"] not in recs:
                continue
            m = score_one(recs[x["id"]], x["answer"])
            m.update(id=x["id"], kind=recs[x["id"]]["kind"], source=recs[x["id"]]["source"],
                     component=recs[x["id"]].get("component"), truth=recs[x["id"]]["truth"], finish=x.get("finish"))
            rows[(model, x["mode"])].append(m)
    # per-record mean measures for the bootstrap
    for (model, mode), ms in rows.items():
        by = collections.defaultdict(list)
        for m in ms:
            by[m["id"]].append(m)
        for rid, L in by.items():
            S[(model, mode, rid)] = {k: (sum(float(x[k]) for x in L if x.get(k) is not None) / max(1, sum(x.get(k) is not None for x in L))
                                         if any(x.get(k) is not None for x in L) else None)
                                     for k in ("verdict_ok", "recall", "mention", "false_alarm", "fail_verdict", "sev_ok", "n_find", "extra")}
    mut = lambda m: m["kind"] not in ("control", "corpus_fail", "corpus_pass")  # noqa: E731
    ctl = lambda m: m["kind"] == "control"  # noqa: E731
    out = []
    keys = [k for k in [(md, mo) for md in a.models for mo in ("off", "on")] if k in rows]
    out.append("### B1 planted defects (mutants) and controls\n")
    out.append("| model | mode | mutants: verdict FAIL | defect recall | severity ok (excl. condition) | findings / answer | "
               "anchor named in prose (lenient) | unanchored findings / mutant | controls: verdict PASS | controls: any [ERROR] | controls: findings / answer | no VERDICT line |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    table = {}
    for model, mode in keys:
        ms = rows[(model, mode)]
        c = dict(v_mut=agg(ms, "verdict_ok", mut), recall=agg(ms, "recall", mut),
                 sev=agg(ms, "sev_ok", lambda m: mut(m) and m["kind"] != "inverted_condition"),
                 nf=agg(ms, "n_find", mut), mention=agg(ms, "mention", mut), extra=agg(ms, "extra", mut), v_ctl=agg(ms, "verdict_ok", ctl),
                 fa=agg(ms, "false_alarm", ctl), nf_ctl=agg(ms, "n_find", ctl),
                 no_verdict=agg(ms, "no_verdict"), length_cut=agg([dict(x=m["finish"] == "length") for m in ms], "x"))
        table[f"{model}/{mode}"] = c
        out.append(f"| {model} | {mode} | {fmt(c['v_mut'])} | {fmt(c['recall'])} | {fmt(c['sev'])} | {fmt(c['nf'])} | "
                   f"{fmt(c['mention'])} | {fmt(c['extra'])} | {fmt(c['v_ctl'])} | {fmt(c['fa'])} | {fmt(c['nf_ctl'])} | {fmt(c['no_verdict'])} |")
    kinds = sorted({m["kind"] for ms in rows.values() for m in ms if mut(m)})
    out.append("\n### B1 defect recall by mutation kind\n")
    out.append("| model | mode | " + " | ".join(kinds) + " |")
    out.append("|---|---|" + "---|" * len(kinds))
    for model, mode in keys:
        out.append(f"| {model} | {mode} | " + " | ".join(fmt(agg(rows[(model, mode)], "recall", lambda m, k=k: m["kind"] == k)) for k in kinds) + " |")
    out.append("\n### B1 severity of the finding that names the defect (ERROR / WARNING counts)\n")
    out.append("| model | mode | " + " | ".join(kinds) + " |")
    out.append("|---|---|" + "---|" * len(kinds))
    for model, mode in keys:
        cells = []
        for k in kinds:
            c = collections.Counter(m.get("sev_got") for m in rows[(model, mode)] if m["kind"] == k and m.get("sev_got"))
            cells.append(f"{c['ERROR']} / {c['WARNING']}")
        out.append(f"| {model} | {mode} | " + " | ".join(cells) + " |")
    comps = sorted({m["component"] for ms in rows.values() for m in ms if mut(m) or ctl(m)})
    out.append("\n### B1 by component: defect recall / control false alarm\n")
    out.append("| model | mode | " + " | ".join(comps) + " |")
    out.append("|---|---|" + "---|" * len(comps))
    for model, mode in keys:
        cells = []
        for cp in comps:
            r = agg(rows[(model, mode)], "recall", lambda m, cp=cp: mut(m) and m["component"] == cp)
            f = agg(rows[(model, mode)], "false_alarm", lambda m, cp=cp: ctl(m) and m["component"] == cp)
            cells.append(f"{r['p']:.2f}" if r else "–")
            cells[-1] += f" / {f['p']:.2f}" if f else " / –"
        out.append(f"| {model} | {mode} | " + " | ".join(cells) + " |")
    out.append("\n### B2 corpus validate records (training data of these models)\n")
    out.append("| model | mode | FAIL records: verdict FAIL | issue recall | all issues found | PASS records: verdict PASS | PASS records: any [ERROR] |")
    out.append("|---|---|---|---|---|---|---|")
    for model, mode in keys:
        ms = rows[(model, mode)]
        cf, cp = (lambda m: m["kind"] == "corpus_fail"), (lambda m: m["kind"] == "corpus_pass")
        rec_all = agg([dict(x=m["recall_all"]) for m in ms if "recall_all" in m], "x")
        out.append(f"| {model} | {mode} | {fmt(agg(ms, 'verdict_ok', cf))} | {fmt(agg(ms, 'recall', cf))} | {fmt(rec_all)} | "
                   f"{fmt(agg(ms, 'verdict_ok', cp))} | {fmt(agg(ms, 'false_alarm', cp))} |")
    # differences
    pairs = [tuple(p.split(":")) for p in a.diff]
    if pairs:
        out.append("\n### Differences (paired bootstrap over records, 95% CI)\n")
        out.append("| comparison | mode | defect recall (B1) | mutant verdict FAIL | control false alarm | control verdict FAIL | corpus FAIL verdict |")
        out.append("|---|---|---|---|---|---|---|")
        is_mut = lambda rid: recs[rid]["kind"] not in ("control", "corpus_fail", "corpus_pass")  # noqa: E731
        is_ctl = lambda rid: recs[rid]["kind"] == "control"  # noqa: E731
        is_cf = lambda rid: recs[rid]["kind"] == "corpus_fail"  # noqa: E731
        for m1, m0 in pairs:
            for mode in ("off", "on"):
                cells = []
                for key, sel in (("recall", is_mut), ("verdict_ok", is_mut), ("false_alarm", is_ctl), ("fail_verdict", is_ctl),
                                 ("verdict_ok", is_cf)):
                    d = boot_diff(S, m1, m0, mode, key, sel)
                    cells.append(f"{d[0]:+.3f} [{d[1]:+.3f}, {d[2]:+.3f}]" if d else "–")
                out.append(f"| {m1} − {m0} | {mode} | " + " | ".join(cells) + " |")
    text = "\n".join(out)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n")
        Path(a.out).with_suffix(".json").write_text(json.dumps(table, indent=1) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--diff", nargs="*", default=["rb1011s2:rb1011", "rb1012:rb1011", "c13c:rb1011"],
                    help="model pairs A:B for A − B")
    ap.add_argument("--out", default=str(ROOT / "results/agent_harness/validate_gt_table.md"))
    main(ap.parse_args())
