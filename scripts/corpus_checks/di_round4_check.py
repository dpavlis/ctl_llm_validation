#!/usr/bin/env python3
"""Acceptance checks of spec/dataintersection_single_output_brief.md (DataIntersection corpus, round 4).

Implements the brief's "Acceptance checks" section with its regexes as written. Run from anywhere:

    python scripts/corpus_checks/di_round4_check.py [--base REV]

Scope decisions (the brief names "the four files", but §4 says only DataIntersection rows change and the
Reformat / Normalizer rows downstream of the DataIntersection stay as they are):

* CTL_LoRA_dataintersection_sft.json and CTL_LoRA_DPO_dataintersection.jsonl: every row is checked.
* CTL_LoRA_scd2_sft.json and CTL_LoRA_DPO_scd2.jsonl: the DataIntersection rows are checked. They are listed
  below, split into rows whose CTL is the DataIntersection transform (or a review of one), prose rows about
  the DataIntersection, and rows whose CTL is a Reformat / Normalizer downstream of it. The downstream rows are
  exempt from checks 1 and 4a (their CTL is not a DataIntersection transform; a two-output Reformat may and
  must return ALL), and check 4b verifies that their code is unchanged against git HEAD (--base). Hits in
  non-DataIntersection SCD2 rows are reported as information only.
* "Explanation" = the answer text with fenced code blocks removed. For check 1 the review scaffolding line
  "VERDICT: PASS|FAIL" is also removed, so that "PASS" cannot satisfy the `pass` alternative.
* Sentence repetition: sentences are split on [.!?] followed by whitespace, after removing fenced code, the
  review scaffolding (ISSUES:/SUGGESTIONS:/VERDICT: lines, "[INFO] No issues found.", severity tags, bullet
  markers); sentences of fewer than 4 words ("No.", "Yes.") are not counted.
"""
import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / 'ctl_lora_training'
DATA = 'sft_training_data'
F_DI_SFT = f'{DATA}/CTL_LoRA_dataintersection_sft.json'
F_DI_DPO = f'{DATA}/CTL_LoRA_DPO_dataintersection.jsonl'
F_SC_SFT = f'{DATA}/CTL_LoRA_scd2_sft.json'
F_SC_DPO = f'{DATA}/CTL_LoRA_DPO_scd2.jsonl'
F_DI_LOG = f'{DATA}/logs/CTL_LoRA_dataintersection_validation.json'
F_SC_LOG = f'{DATA}/logs/CTL_LoRA_scd2_validation.json'
EXPECTED_COUNTS = {F_DI_SFT: 60, F_DI_DPO: 40, F_SC_SFT: 60, F_SC_DPO: 40}
REVIEWED = '2026-11-02'

# --- regexes as written in the brief -------------------------------------------------------------------------
PORT_PROMPT = re.compile(r'output [012]|port [012]|physical output|A-only|B-only|all outputs are connected', re.I)
SINGLE = re.compile(r'single|one output record|only (record|output)|the only record', re.I)
FORWARD = re.compile(r'forward|route|deliver|pass|take care', re.I)
EXPL_BANNED = ['output 0', 'output 1', 'output 2', 'port 0', 'port 1', 'port 2', 'A-only port', 'B-only port',
               'both port', 'all three', 'three ports']
REJ_BANNED = ['all three', 'three output ports', 'every connected', 'broadcast', 'both port', 'A-only port',
              'B-only port']

# --- SCD2 DataIntersection rows (ids for SFT, 1-based line numbers for DPO) ------------------------------------
SC_SFT_DI_TRANSFORM = {f'scd2_sft_{n:03d}' for n in
                       (1, 2, 3, 6, 7, 8, 11, 14, 15, 17, 21, 22, 27, 28, 47, 54, 55, 59)}
SC_SFT_DI_PROSE = {f'scd2_sft_{n:03d}' for n in (9, 37, 41, 58)}
SC_SFT_DOWNSTREAM = {f'scd2_sft_{n:03d}' for n in (4, 10, 12, 13, 16, 19, 20, 39, 45, 50, 52)}
SC_DPO_DI_TRANSFORM = {1, 5, 7, 8, 11, 15, 16, 17, 28, 31}
SC_DPO_DI_PROSE = {30, 32}
SC_DPO_DOWNSTREAM = {2, 3, 4, 6, 9, 10, 14, 29}

CODE = re.compile(r'```.*?```', re.S)


def explanation(text):
    return CODE.sub('', text)


def expl_for_check1(text):
    return re.sub(r'^VERDICT:.*$', '', explanation(text), flags=re.M)


def sentences(text):
    t = explanation(text)
    t = re.sub(r'^\s*(ISSUES:|SUGGESTIONS:|VERDICT:.*)\s*$', '', t, flags=re.M)
    t = t.replace('[INFO] No issues found.', ' ')
    t = re.sub(r'\[(ERROR|WARNING|INFO)\]', ' ', t)
    t = re.sub(r'^\s*[-*]\s+', ' ', t, flags=re.M)
    out = []
    for s in re.split(r'(?<=[.!?])\s+', t):
        s = ' '.join(s.split())
        if len(s.split()) >= 4:
            out.append(s)
    return out


def load(rev, rel):
    if rev is None:
        raw = (REPO / rel).read_text(encoding='utf-8')
    else:
        raw = subprocess.run(['git', '-C', str(REPO), 'show', f'{rev}:{rel}'], check=True,
                             capture_output=True, text=True).stdout
    if rel.endswith('.jsonl'):
        return [json.loads(l) for l in raw.splitlines() if l.strip()]
    return json.loads(raw)


def records(rel, rows):
    """Yield dicts: key, prompt, answer (SFT answer or DPO chosen), rejected (DPO), scope."""
    out = []
    for i, r in enumerate(rows):
        if rel.endswith('.jsonl'):
            line = i + 1
            key = f'{Path(rel).name}:{line}'
            if rel == F_SC_DPO:
                scope = ('di_transform' if line in SC_DPO_DI_TRANSFORM else 'di_prose' if line in SC_DPO_DI_PROSE
                         else 'downstream' if line in SC_DPO_DOWNSTREAM else 'non_di')
            else:
                scope = 'di_file'
            out.append(dict(key=key, prompt=r['prompt'], answer=r['chosen'], rejected=r['rejected'],
                            scope=scope, raw=r))
        else:
            key = r['id']
            if rel == F_SC_SFT:
                scope = ('di_transform' if key in SC_SFT_DI_TRANSFORM else 'di_prose' if key in SC_SFT_DI_PROSE
                         else 'downstream' if key in SC_SFT_DOWNSTREAM else 'non_di')
            else:
                scope = 'di_file'
            user = next(m['content'] for m in r['messages'] if m['role'] == 'user')
            ans = [m['content'] for m in r['messages'] if m['role'] == 'assistant'][-1]
            out.append(dict(key=key, prompt=user, answer=ans, rejected=None, scope=scope, raw=r))
    return out


def report(name, bad, n, info=None):
    status = 'PASS' if not bad else 'FAIL'
    print(f'[{status}] {name}: {n - len(bad) if n is not None else ""}{"/" + str(n) if n is not None else ""} ok'
          + (f'; offending ({len(bad)}): {", ".join(bad)}' if bad else ''))
    if info:
        print(f'       info: {info}')
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='HEAD', help='git revision of ctl_lora_training to diff against')
    args = ap.parse_args()

    cur = {f: load(None, f) for f in EXPECTED_COUNTS}
    old = {f: load(args.base, f) for f in EXPECTED_COUNTS}
    recs = {f: records(f, cur[f]) for f in cur}
    old_recs = {f: records(f, old[f]) for f in old}
    all_recs = [r for f in recs for r in recs[f]]
    checked = [r for r in all_recs if r['scope'] in ('di_file', 'di_transform', 'di_prose', 'downstream')]
    ok = True

    # 1. port-describing prompts: $out.0 + single-output wording + forwarding wording
    pool = [r for r in checked if r['scope'] != 'downstream' and PORT_PROMPT.search(r['prompt'])]
    bad = []
    for r in pool:
        e = expl_for_check1(r['answer'])
        miss = [k for k, ok_ in (('$out.0', '$out.0' in e), ('single', SINGLE.search(e)),
                                 ('forward', FORWARD.search(e))) if not ok_]
        if miss:
            bad.append(f'{r["key"]}(no {"/".join(miss)})')
    exempt = sorted(r['key'] for r in checked if r['scope'] == 'downstream' and PORT_PROMPT.search(r['prompt']))
    ok &= report('1a port-describing prompts: answer states the single output record', bad, len(pool),
                 f'downstream Reformat/Normalizer rows exempt per brief §4: {", ".join(exempt)}')

    # 1b. sentence repetition across the four files (all SFT answers and DPO chosen answers)
    cnt = collections.Counter()
    for r in all_recs:
        for s in set(sentences(r['answer'])):
            cnt[s] += 1
    rep = [f'"{s[:70]}…" x{c}' for s, c in cnt.most_common() if c > 5]
    ok &= report('1b no explanation sentence used more than 5 times (four files)', rep, None,
                 f'max repetition {cnt.most_common(1)[0][1] if cnt else 0}')

    # 2. banned port wording in SFT answers / DPO chosen explanations
    bad, info = [], []
    for r in all_recs:
        e = explanation(r['answer'])
        hits = [b for b in EXPL_BANNED if b.lower() in e.lower()]
        if not hits:
            continue
        if r['scope'] == 'non_di':
            info.append(f'{r["key"]}({"|".join(hits)})')
        elif r['key'] == 'scd2_sft_016':
            info.append(f'{r["key"]}({"|".join(hits)}; the two-output Reformat\'s own outputs, exempt §4)')
        else:
            bad.append(f'{r["key"]}({"|".join(hits)})')
    n2 = sum(1 for r in all_recs if r['scope'] != 'non_di')
    ok &= report('2  no port numbering in SFT / chosen explanations', bad, n2,
                 ('outside the checked scope: ' + ', '.join(info)) if info else None)

    # 3. DPO rejected answers: banned wording and `$out.1` in prose (both DPO files, all lines)
    bad = []
    rej = [r for r in all_recs if r['rejected'] is not None]
    for r in rej:
        p = explanation(r['rejected'])
        hits = [b for b in REJ_BANNED if b.lower() in p.lower()]
        if '$out.1' in p:
            hits.append('$out.1 in prose')
        if hits:
            bad.append(f'{r["key"]}({"|".join(hits)})')
    ok &= report('3  DPO rejected answers: no ALL / port statements, no $out.1 in prose', bad, len(rej))

    # 4a. return ALL in no SFT / chosen answer; emitting DataIntersection answers return OK
    bad, info = [], []
    for r in all_recs:
        has_all = re.search(r'return\s+ALL\b', r['answer'])
        if r['scope'] in ('di_file', 'di_transform', 'di_prose'):
            if has_all:
                bad.append(f'{r["key"]}(return ALL)')
            code = ''.join(CODE.findall(r['answer']))
            if code and re.search(r'\$out\.0\s*[.=]', code) and not re.search(r'return\s+OK\b', code):
                bad.append(f'{r["key"]}(emits without return OK)')
        elif has_all:
            info.append(r['key'])
    n4 = sum(1 for r in all_recs if r['scope'] in ('di_file', 'di_transform', 'di_prose'))
    ok &= report('4a return ALL in no DataIntersection SFT / chosen answer; emitting answers return OK', bad, n4,
                 f'return ALL kept in Reformat/Normalizer/joiner answers outside the DataIntersection CTL '
                 f'({len(info)}): {", ".join(info)}')

    # 4b. downstream Reformat / Normalizer answers unchanged (code blocks identical to base)
    bad = []
    for f in (F_SC_SFT, F_SC_DPO):
        for a, b in zip(recs[f], old_recs[f]):
            if a['scope'] != 'downstream':
                continue
            if CODE.findall(a['answer']) != CODE.findall(b['answer']):
                bad.append(f'{a["key"]}(chosen/answer code)')
            if a['rejected'] is not None and a['rejected'] != b['rejected']:
                bad.append(f'{a["key"]}(rejected)')
    prose_changed = [a['key'] for f in (F_SC_SFT, F_SC_DPO) for a, b in zip(recs[f], old_recs[f])
                     if a['scope'] == 'downstream' and a['answer'] != b['answer']]
    ndown = len(SC_SFT_DOWNSTREAM) + len(SC_DPO_DOWNSTREAM)
    ok &= report('4b downstream Reformat / Normalizer code unchanged (diff vs base)', bad, ndown,
                 f'prose-only edits in downstream rows: {", ".join(prose_changed) or "none"}')
    nondi_changed = [a['key'] for f in (F_SC_SFT, F_SC_DPO) for a, b in zip(recs[f], old_recs[f])
                     if a['scope'] == 'non_di' and a['raw'] != b['raw']]
    ok &= report('4c non-DataIntersection SCD2 rows unchanged', nondi_changed, None)

    # 5. counts, ids, order, prompts, reviewed_date, DPO file names
    bad = []
    for f, n in EXPECTED_COUNTS.items():
        if len(cur[f]) != n:
            bad.append(f'{f}: count {len(cur[f])} != {n}')
        for a, b in zip(recs[f], old_recs[f]):
            if a['key'] != b['key']:
                bad.append(f'{a["key"]}: id/order differs from base {b["key"]}')
            if a['prompt'] != b['prompt']:
                bad.append(f'{a["key"]}: prompt changed')
            if f.endswith('.jsonl') and a['raw']['system'] != b['raw']['system']:
                bad.append(f'{a["key"]}: system changed')
            if a['raw'] != b['raw'] and a['raw'].get('reviewed_date') != REVIEWED:
                bad.append(f'{a["key"]}: changed but reviewed_date {a["raw"].get("reviewed_date")}')
            if a['scope'] != 'non_di' and a['raw'].get('reviewed_date') != REVIEWED:
                bad.append(f'{a["key"]}: DataIntersection row reviewed_date {a["raw"].get("reviewed_date")}')
    for f in (F_DI_DPO, F_SC_DPO):
        if not re.fullmatch(r'CTL_LoRA_DPO_.*\.jsonl', Path(f).name):
            bad.append(f'{f}: name')
    changed = {f: sum(1 for a, b in zip(recs[f], old_recs[f]) if a['raw'] != b['raw']) for f in recs}
    ok &= report('5  counts 60/40/60/40, ids/order, prompts unchanged, reviewed_date, DPO names', bad, None,
                 'rows changed vs base: ' + ', '.join(f'{Path(f).name} {c}' for f, c in changed.items()))

    # 6. validation logs record rounds 3 and 4 and the compile results
    bad = []
    for f in (F_DI_LOG, F_SC_LOG):
        log = load(None, f)
        if log.get('reviewed_date') != REVIEWED:
            bad.append(f'{Path(f).name}: reviewed_date')
        rv = log.get('revisions', {})
        need = ('round3', 'round4') if f == F_DI_LOG else ('round4',)
        for k in need:
            if k not in rv:
                bad.append(f'{Path(f).name}: revisions.{k} missing')
        r4 = rv.get('round4', {})
        cr = r4.get('compile_results')
        if not cr or not isinstance(cr, dict) or 'results' not in cr:
            bad.append(f'{Path(f).name}: round4.compile_results missing')
        else:
            for x in cr['results']:
                if x.get('expected') != x.get('actual'):
                    bad.append(f'{Path(f).name}: {x.get("id")} expected {x.get("expected")} got {x.get("actual")}')
        for k in ('changed_sft_indices', 'changed_dpo_lines'):
            if k not in r4:
                bad.append(f'{Path(f).name}: round4.{k} missing')
    ok &= report('6  validation logs: rounds 3 and 4, changed rows, compile results', bad, None)

    print('ALL CHECKS PASS' if ok else 'SOME CHECKS FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
