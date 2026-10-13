"""Assemble final reviewed author shards with real compiler and run evidence."""
import hashlib,json,re,xml.etree.ElementTree as E
from pathlib import Path
from graph_harness import D,TYPE_MAP
P=D/'round2'
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
def scope_diagnostics(payload,spec):
 records={E.fromstring(x).get('name') for x in spec.get('inputMetadata',[])+spec.get('outputMetadata',[])}
 records.update(E.fromstring(l['metadata']).get('name') for l in spec.get('resources',{}).get('lookups',[]))
 def known(p):
  msg=p['message']
  if re.fullmatch("Unknown variable type or metadata name '[^']+'",msg):return msg.split("'")[1] in records
  if re.search(r'Unable to resolve (?:lookup table|sequence) ',msg):return True
  if re.fullmatch("Dictionary entry '[^']+' does not exist",msg):return True
  return False
 return bool(payload.get('problems')) and all(known(p) for p in payload['problems'])
def rubric_runtime_corrections(test):
 if test['component'].split(' (')[0]=='DataIntersection':
  test['rubric']['required'][0]['check']='Uses the matched-pair transform with internal CTL $out.0, routed by DataIntersection to physical output 1; accepts any successful nonnegative return such as OK/0, 1 or ALL. Uses SKIP only for matches the business contract suppresses. One-sided input records pass through automatically; do not rely on one-sided callbacks. Unused helper declarations alone are not a defect.'
  test['rubric']['required'][0]['rationale']='Live runs 17918/17919/17920 verify OK/1/ALL and internal output 0; 17922 verifies SKIP, 17993 verifies STOP errors. The worker differs from the previously recorded port-1 CTL owner ruling.'
  for r in test['rubric']['forbidden']:
   r['check']=r['check'].replace('Must not invent transformLeftOnly or transformRightOnly hooks, fabricate INSERT/DELETE rows, or write matched results to unavailable internal CTL outputs 1/2.', 'Must not rely on transformLeftOnly/transformRightOnly callbacks for required output, fabricate INSERT/DELETE rows, or write to unavailable internal CTL outputs 1/2. Harmless unused helper declarations alone are not a violation.')
   r['check']=r['check'].replace('Must not invent left-only or right-only callbacks to build pass-through rows.','Must not rely on left-only or right-only callbacks to perform required mapping or alter pass-through rows; harmless unused helpers alone are not a violation.')
  test['rubric']['forbidden'].append(dict(id=test['test_id']+'.F'+str(len(test['rubric']['forbidden'])+1),check='Must not use STOP or another failing negative result instead of a successful emit or the specified SKIP.',rationale='Live run 17993 fails with transform code -2; non-SKIP does not mean every negative return is valid.'))
def finalize():
 objs=[]
 for p in sorted(P.glob('shard_t*.json')):objs+=json.loads(p.read_text())
 objs.sort(key=lambda o:int(o['test']['test_id'][1:]));assert len(objs)==30
 raw=json.loads((P/'compile_responses.json').read_text());assert len(raw)==30
 runs={r['test_id']:r for r in json.loads((D/'graph_run_results.json').read_text())}
 extras=json.loads((P/'extra_run_results.json').read_text());manifests={m['test_id']:m for m in json.loads((P/'main_manifests.json').read_text())}
 tests=[];contexts={};evidence=[];changes=[]
 for obj,c in zip(objs,raw):
  t,s=obj['test'],obj['graph_spec'];tid=t['test_id'];run=runs[tid];m=manifests[tid]
  assert c['arguments']['code']==t['reference'],tid+' stale standalone compile'
  assert run['reference_sha256']==sha(t['reference']) and run['graph_sha256']==m['graph_sha256'],tid+' stale graph run'
  assert run['reference_runs'] and run['completion']['status']=='FINISHED_OK',tid+' failed main run'
  assert run['validation']['overall']=='PASS' and not run['validation']['problems'],tid+' graph validation diagnostics'
  diagnostic=c['payload'];standalone=diagnostic['overall']=='PASS' and not diagnostic['problems']
  assert standalone or scope_diagnostics(diagnostic,s),tid+' non-scope standalone compile error'
  t['compile_result']=json.dumps(diagnostic,ensure_ascii=False);t['reference_compiles']=True;t['standalone_reference_compiles']=standalone
  t['compile_verification_method']='ctl_validate' if standalone else 'job_validate plus FINISHED_OK graph execution (standalone context limitation)'
  t['graph_compile_result']=run['validation'];t['reference_runs']=True;t['graph_file']=run['graph_file'];t['run_ids']=run['run_ids']
  associated=[e for e in extras if e['test_id']==tid];assert all(e['reference_runs'] for e in associated),tid+' failed extra probe'
  t['run_ids']+= [rid for e in associated for rid in e['run_ids']];rubric_runtime_corrections(t)
  tests.append(t);contexts[tid]=dict(**{k:v for k,v in c['arguments'].items() if k!='code'},graph_resources=s.get('resources',{}),physical_output_metadata=s.get('outputMetadata',[]))
  evidence.append(dict(test_id=tid,request=c['arguments'],response=c['response'],payload=diagnostic,reference_sha256=sha(t['reference']),header_mode='//#CTL2',standalone_reference_compiles=standalone,graph_compile_verified=run['reference_runs'],graph_validation=run['validation'],run_ids=t['run_ids']))
  changes.append(obj['change'])
 (D/'generate_rw.json').write_text(json.dumps(tests,indent=2,ensure_ascii=False)+'\n')
 (D/'compile_contexts.json').write_text(json.dumps(contexts,indent=2,ensure_ascii=False)+'\n')
 (D/'compile_results.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
 (D/'change_log.json').write_text(json.dumps(changes,indent=2,ensure_ascii=False)+'\n')
 (P/'final_graph_specs.json').write_text(json.dumps({o['test']['test_id']:o['graph_spec'] for o in objs},indent=2,ensure_ascii=False)+'\n')
 print('Assembled30 tests;',sum(t['standalone_reference_compiles'] for t in tests),'standalone compiler passes; all30 actual graph compile/run passes')
if __name__=='__main__':finalize()
