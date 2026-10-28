#!/home/pavlisd/venv/bin/python
"""Per-round statistics of an OPCD run with review tags (valprec1): samples, trained, guard rejections (context quote,
rule citation) and KL per token by tag and mode, summed over rounds; skipped samples; the belief probe.

    ~/venv/bin/python scripts/validate_precision/round_stats.py valprec1 [--out results/validate_precision/round_stats_valprec1.md]
"""
import argparse, collections, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(a):
    d = ROOT / "data/opcd" / a.run
    ms = [json.loads(p.read_text()) for p in sorted(d.glob("round_*/metrics.json"))]
    tot = collections.defaultdict(lambda: collections.Counter())
    kl = collections.defaultdict(list)
    for m in ms:
        for k, v in m.get("by_tag", {}).items():
            for f in ("samples", "trained", "context_quote", "cite_guarded"):
                tot[k][f] += v[f]
            if v["trained"]:
                kl[k].append((m["round"], v["kl_per_token"]))
    lines = [f"# {a.run}: {len(ms)} rounds", "",
             f"skipped: context quote {sum(m.get('skipped_context_quote', 0) for m in ms)}, cutoff "
             f"{sum(m['skipped_cutoff'] for m in ms)}, truncated {sum(m['skipped_truncated'] for m in ms)}; "
             f"minutes per round {sum(m['sample_min'] + m['train_min'] for m in ms) / max(1, len(ms)):.1f}", "",
             "| tag | samples | trained | context quote | rule cite guarded | KL/token first 10 rounds | last 10 rounds |", "|---|---|---|---|---|---|---|"]
    for k in sorted(tot):
        first = [x for r, x in kl[k] if r < 10]; last = [x for r, x in kl[k] if r >= len(ms) - 10]
        f = lambda xs: f"{sum(xs) / len(xs):.3f}" if xs else "-"
        t = tot[k]
        lines.append(f"| {k} | {t['samples']} | {t['trained']} | {t['context_quote']} | {t['cite_guarded']} | {f(first)} | {f(last)} |")
    lines += ["", "| set | KL/token first 10 | last 10 | belief rate first 10 | last 10 |", "|---|---|---|---|---|"]
    for s in ("target", "hard", "contrast", "replay", "replay_validate_off"):
        xs = [(m["round"], m["summary"][s]) for m in ms if s in m["summary"]]
        g = lambda f, lo, hi: (lambda v: f"{sum(v) / len(v):.3f}" if v else "-")([x[f] for r, x in xs if lo <= r < hi])
        lines.append(f"| {s} | {g('kl_per_token', 0, 10)} | {g('kl_per_token', len(ms) - 10, len(ms))} | "
                     f"{g('belief_rate', 0, 10)} | {g('belief_rate', len(ms) - 10, len(ms))} |")
    probes = sorted(d.glob("probe_*.json"))
    lines += ["", "probe (belief rate by round): " + ", ".join(
        f"{p.stem[6:]}: {json.loads(p.read_text())['belief_rate']}" for p in probes)]
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out")
    main(ap.parse_args())
