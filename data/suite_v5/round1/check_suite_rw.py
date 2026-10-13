"""Check the fixed regression suite; strict default includes external validation gates.

python data/suite_v5/check_suite_rw.py --allow-incomplete checks artifact integrity
while still reporting (not concealing) unresolved compiler or corpus coverage gates.
"""
import argparse,collections,hashlib,json,re,sys,xml.etree.ElementTree as ET
from pathlib import Path
D=Path(__file__).resolve().parent
ROOT=D.parents[1]
REQUIRED_KEYS={'test_id','type','group','component','archetype','temperature','system_prompt','user_message','rubric','reference','reference_compiles','compile_result'}
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def check(path=D/'generate_rw.json'):
 rows=json.loads(Path(path).read_text());errors=[];gates=[];stats=[]
 def need(ok,message):
  if not ok:errors.append(message)
 need(isinstance(rows,list) and len(rows)==30,'Expected an array of exactly 30 tests')
 need([t.get('test_id') for t in rows]==[f'T{i}' for i in range(44,74)],'IDs must be T44–T73 in order')
 counts=collections.Counter(t.get('archetype') for t in rows)
 need(set(counts)==set(range(1,13)) and all(2<=v<=3 for v in counts.values()),'Every archetype needs 2–3 tests')
 original=json.loads((ROOT/'resources/ctl2_test_suite_v4.json').read_text())
 system=next(t['system_prompt'] for t in original['tests'] if t['test_id']=='T33')
 evidence={e['test_id']:e for e in json.loads((D/'compile_results.json').read_text())}
 contexts=json.loads((D/'compile_contexts.json').read_text())
 for t in rows:
  tid=t['test_id'];need(REQUIRED_KEYS<=t.keys(),tid+': missing object keys')
  need(t['type']=='generate' and t['group']=='rw' and t['temperature']==0.4,tid+': wrong category or temperature')
  need(t['system_prompt']==system,tid+': system prompt must be verbatim T33')
  msg=t['user_message'];words=len(msg.split());need(300<=words<=900,tid+': prompt word count '+str(words))
  clauses=re.findall(r'^([0-9]+)\. (.*?)(?=\n[0-9]+\. |\n\n|\Z)',msg,re.M|re.S)
  nums=[int(n) for n,_ in clauses];need(5<=len(nums)<=10 and nums==list(range(1,len(nums)+1)),tid+': malformed numbered clauses')
  rub=t['rubric'];required=rub['required'];forbidden=rub['forbidden']
  need(6<=len(required)<=12 and 2<=len(forbidden)<=5,tid+': rubric size')
  need(rub['scoring']=={'method':'required_fraction','forbidden_penalty':0.2},tid+': scoring')
  covered=set()
  for r in required:
   need({'id','check','rationale','clauses'}<=r.keys(),tid+': malformed required item')
   covered.update(r.get('clauses',[]));need(bool(r['check']) and bool(r['rationale']),r['id']+': empty check/rationale')
  need(covered==set(nums),tid+': every spec clause must be linked to a rubric item')
  itemids=[r['id'] for r in required+forbidden];need(len(itemids)==len(set(itemids)),tid+': duplicate rubric IDs')
  for r in forbidden:need({'id','check','rationale'}<=r.keys(),tid+': malformed forbidden item')
  blocks=re.findall(r'<Record\b.*?</Record>',msg,re.S);names=set();fieldcounts=[];has_decimal=False
  for block in blocks:
   try:record=ET.fromstring(block)
   except ET.ParseError as e:errors.append(tid+': bad metadata XML '+str(e));continue
   fields=record.findall('Field');fieldcounts.append(len(fields));fn=[f.get('name') for f in fields];names.update(fn)
   need(12<=len(fields)<=40,tid+': field count outside 12–40 in '+record.get('name',''))
   need(len(fn)==len(set(fn)) and None not in fn,tid+': duplicate/unnamed field')
   need(record.get('name') and record.get('type')=='delimited',tid+': incomplete record attributes')
   need(any(f.get('type')=='date' for f in fields),tid+': record missing a date')
   need({f.get('nullable') for f in fields}=={'true','false'},tid+': record must specify mixed nullability')
   for f in fields:
    if f.get('type')=='decimal':
     has_decimal=True;need(f.get('length') and f.get('scale'),tid+': decimal lacks length/scale')
  need(has_decimal,tid+': no decimal metadata')
  need('unused_archive_label' in names,tid+': no unrelated context field')
  prose=re.sub(r'<Record\b.*?</Record>','',msg,flags=re.S)+' '+ ' '.join(r['check']+' '+r['rationale'] for r in required+forbidden)
  # Production field identifiers use lowercase underscore names. Graph parameters
  # and constants are uppercase; these are separately declared graph context.
  prose=re.sub(r'\b[\w.-]+\.(?:csv|grf|fmt|ctl)\b','',prose)
  named=set(re.findall(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b',prose))
  need(named<=names,tid+': spec/rubric fields absent from metadata: '+str(sorted(named-names)))
  for direction,port,name in re.findall(r'\$(in|out)\.(\d+)\.([A-Za-z_]\w*)',t['reference']):
   ports=contexts[tid].get('inputMetadata' if direction=='in' else 'outputMetadata',[])
   index=int(port)
   need(index<len(ports),tid+': reference port not declared '+direction+'.'+port)
   if index<len(ports):
    port_fields={f.get('name') for f in ET.fromstring(ports[index]).findall('Field')}
    need(name in port_fields,tid+': reference field not on specified port '+direction+'.'+port+'.'+name)
  need(t['reference'].startswith('//#CTL2\n'),tid+': header mode mismatch')
  e=evidence.get(tid);need(bool(e),tid+': missing compiler evidence')
  if e:
   need(e['reference_sha256']==digest(t['reference']) and e['request']['code']==t['reference'],tid+': stale compiler code evidence')
   payload=json.loads(t['compile_result']);need(payload==e['payload'],tid+': stored compiler payload mismatch')
   clean=payload.get('overall')=='PASS' and payload.get('problems')==[]
   need(t['reference_compiles'] is clean,tid+': compilation flag misrepresents actual diagnostics')
   if not clean:gates.append(tid+': reference has standalone compiler diagnostics')
   for k in ['componentType','inputMetadata','outputMetadata','accumulatorMetadata']:
    need(e['request'].get(k)==contexts[tid].get(k),tid+': stale compiler metadata/context '+k)
  stats.append(dict(test_id=tid,words=words,record_field_counts=fieldcounts,clause_count=len(nums),required_count=len(required),forbidden_count=len(forbidden)))
 need(len({r['user_message'] for r in rows})==30,'Duplicate new prompts')
 need(len({r['reference'] for r in rows})==30,'Duplicate new references')
 if (D/'dedup_report.json').exists():
  dedup=json.loads((D/'dedup_report.json').read_text())
  need(dedup['max_external_jaccard']<=0.5 and not dedup['exact_matches'],'External duplication threshold exceeded')
  need(dedup['suite_sha256']==hashlib.sha256(Path(path).read_bytes()).hexdigest(),'Dedup report is stale')
  gates.extend('Dedup input unavailable: '+p for p in dedup['missing_inputs'])
 else:gates.append('Dedup report missing')
 for span in ['t44_t53','t54_t63','t64_t73']:
  p=D/('review_'+span+'.json')
  need(p.exists(),'Missing required independent review '+span)
  if p.exists():
   review=json.loads(p.read_text());addendum=review.get('final_addendum',{})
   records=addendum.get('tests',addendum.get('reviewed_final_references',review.get('final_review',[])))
   if isinstance(records,dict):records=records.get('tests',[])
   if not records:records=review.get('tests',[])
   hashes={r['test_id']:r.get('final_reference_sha256',r.get('reference_sha256')) for r in records}
   lo,hi=map(int,re.findall(r'\d+',span))
   for n in range(lo,hi+1):
    tid='T'+str(n);row=next(t for t in rows if t['test_id']==tid)
    need(hashes.get(tid)==digest(row['reference']),tid+': independent review hash missing or stale')
 return dict(structural_pass=not errors,ready_for_snapshot=not errors and not gates,errors=errors,incomplete_gates=gates,archetype_coverage=dict(counts),tests=stats)
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('path',nargs='?',type=Path,default=D/'generate_rw.json');parser.add_argument('--allow-incomplete',action='store_true');parser.add_argument('--report',type=Path)
 args=parser.parse_args();report=check(args.path)
 if args.report:args.report.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2));sys.exit(0 if report['structural_pass'] and (args.allow_incomplete or report['ready_for_snapshot']) else 1)
