"""Exact and exhaustive 5-word-gram Jaccard comparison against specified corpora.

The inverted index visits every prior prompt sharing any gram, so nearest scores
are exact, not MinHash estimates. Compare full prompts and business prose with
metadata/code fences removed; the larger score is the external acceptance gate.
"""
import collections,hashlib,json,re
from pathlib import Path
D=Path(__file__).resolve().parent;ROOT=D.parents[1]
def norm(s):return ' '.join(re.findall(r'\w+',s.lower()))
def prose(s):return re.sub(r'<Metadata\b.*?</Metadata>|<Record\b.*?</Record>|```.*?```',' ',s,flags=re.S)
def grams(s):
 a=norm(s).split();return set(tuple(a[i:i+5]) for i in range(max(0,len(a)-4)))
def user(r):
 if 'messages' in r:return '\n'.join(m.get('content','') for m in r['messages'] if m.get('role')=='user')
 for k in ['user_message','user','prompt','instruction']:
  if isinstance(r.get(k),str):return r[k]
 return ''
def main():
 suite=D/'generate_rw.json';rows=json.loads(suite.read_text());missing=[];sources=[];prior=[]
 paths=[ROOT/'resources/ctl2_test_suite_v4.json']+sorted(set((ROOT/'ctl_lora_training/sft_training_data').glob('CTL_LoRAT_*.json')) | set((ROOT/'ctl_lora_training/sft_training_data').glob('CTL_LoRA_*.json')))+sorted((ROOT/'data/opcd').glob('hard_cases*.jsonl'))+[ROOT/'data/genbench/tasks.jsonl']
 for p in paths:
  if not p.exists():missing.append(str(p.relative_to(ROOT)));continue
  data=[json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.suffix=='.jsonl' else json.loads(p.read_text())
  if isinstance(data,dict):data=data['tests']
  sources.append(dict(path=str(p.relative_to(ROOT)),records=len(data),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
  for i,r in enumerate(data):
   text=user(r)
   if text:prior.append((str(p.relative_to(ROOT)),r.get('test_id',r.get('id',str(i))),text))
 exact=collections.defaultdict(list)
 for i,(_,_,s) in enumerate(prior):exact[norm(s)].append(i)
 results={r['test_id']:dict(test_id=r['test_id'],nearest={},exact_matches=[]) for r in rows}
 for r in rows:
  for i in exact.get(norm(r['user_message']),[]):results[r['test_id']]['exact_matches'].append(dict(source=prior[i][0],id=prior[i][1]))
 for view,func in [('full_prompt',lambda s:s),('business_prose',prose)]:
  old=[grams(func(t)) for _,_,t in prior];index=collections.defaultdict(list)
  for i,gset in enumerate(old):
   for gram in gset:index[gram].append(i)
  for r in rows:
   new=grams(func(r['user_message']));shared=collections.Counter(i for g in new for i in index.get(g,[]));best=(0,None)
   for i,intersection in shared.items():
    score=intersection/(len(new)+len(old[i])-intersection)
    if score>best[0]:best=(score,i)
   score,i=best;match=dict(jaccard=score)
   if i is not None:match.update(source=prior[i][0],id=prior[i][1])
   results[r['test_id']]['nearest'][view]=match
  del index,old
 maximum=max(m['jaccard'] for r in results.values() for m in r['nearest'].values())
 report=dict(method='normalised word 5-gram exact Jaccard; full prompt and business prose',threshold=0.5,prior_records=len(prior),sources=sources,missing_inputs=missing,suite_sha256=hashlib.sha256(suite.read_bytes()).hexdigest(),exact_matches=[r for r in results.values() if r['exact_matches']],max_external_jaccard=maximum,tests=list(results.values()),coverage_complete=not missing)
 (D/'dedup_report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(dict(prior_records=len(prior),sources=len(sources),missing_inputs=missing,max_external_jaccard=maximum,exact_matches=len(report['exact_matches'])),indent=2))
if __name__=='__main__':main()
