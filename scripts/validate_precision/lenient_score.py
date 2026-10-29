#!/usr/bin/env python3
# Format-independent B1 re-score (spec/validate_precision2_findings.md): for plain answers that drop the ISSUES:/VERDICT: layout.
#   python3 scripts/validate_precision/lenient_score.py results/agent_harness/validate_gt_<tag>.jsonl ...
# Format-independent re-score of plain answers: a control is a false alarm if the answer marks anything ERROR
# ([ERROR], **ERROR**, "ERROR:" / "ERROR —") or says the verdict is FAIL; a mutant counts as caught if the answer
# both marks an ERROR/FAIL and names the anchor (anchor_res) anywhere.
import json,re,sys,random,collections
M={r['id']:r for r in map(json.loads,open('data/agent_harness/validate_mutants.jsonl'))}
ERR=re.compile(r'(?m)\[ERROR\]|\*\*ERROR\b|^\s*[-*]?\s*ERROR\b|\bERROR\s*[:—–-]|VERDICT\W*FAIL|verdict[^.\n]{0,20}\bFAIL\b')
FMT=re.compile(r'ISSUES:')
def ci(xs,B=2000):
    random.seed(0); n=len(xs); m=sum(xs)/n
    bs=sorted(sum(random.choice(xs) for _ in range(n))/n for _ in range(B)); return m,bs[int(.025*B)],bs[int(.975*B)],n
for f in sys.argv[1:]:
    rows=[json.loads(l) for l in open(f)]
    for mode in ('off','on'):
        rs=[r for r in rows if r['mode']==mode and r['id'] in M]
        if not rs: continue
        ctl=[1 if ERR.search(r['answer'] or '') else 0 for r in rs if M[r['id']]['truth']=='PASS']
        mut=[]
        for r in rs:
            m=M[r['id']]
            if m['truth']!='FAIL': continue
            a=r['answer'] or ''
            mut.append(1 if ERR.search(a) and any(re.search(p,a) for p in m['anchor_res']) else 0)
        fmt=sum(1 for r in rs if FMT.search(r['answer'] or ''))/len(rs)
        cap=sum(1 for r in rs if r.get('finish')=='length')/len(rs)
        print(f"{f.split('/')[-1]:45s} {mode}  ISSUES-format {fmt:.2f}  cap {cap:.2f}  "
              "recall %.2f [%.2f,%.2f] (%d)  ctl FA %.2f [%.2f,%.2f] (%d)"%(ci(mut)+ci(ctl)))
