"""Strict integrity, coverage, duplicate and real-execution gates for suite v5 round2.

A standalone resource-scope diagnostic is accepted only when the exact same
reference compiles and completes in its real graph. Actual diagnostics are kept.
"""
import argparse,collections,hashlib,json,re,sys,xml.etree.ElementTree as ET
from pathlib import Path
D=Path(__file__).resolve().parent;ROOT=D.parents[1]
sys.path.insert(0,str(D/'round2'))
from graph_harness import TYPE_MAP,normal,normalized_rows,parse_actual
from finalize_suite import scope_diagnostics
from dedup_suite_rw import grams
REQUIRED_KEYS={'test_id','type','group','component','archetype','temperature','system_prompt','user_message','rubric','reference','reference_compiles','compile_result','reference_runs','graph_file','run_ids','retired_scenario'}
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
def check(path=D/'generate_rw.json'):
 rows=json.loads(Path(path).read_text());errors=[];stats=[]
 def need(ok,msg):
  if not ok:errors.append(msg)
 need(isinstance(rows,list) and len(rows)==30,'Expected exactly30 tests')
 need([t.get('test_id') for t in rows]==[f'T{i}' for i in range(44,74)],'IDs must be T44–T73 in order')
 counts=collections.Counter(t.get('archetype') for t in rows);need(set(counts)==set(range(1,13)) and all(2<=v<=3 for v in counts.values()),'Every archetype requires2–3 tests')
 originals=json.loads((ROOT/'resources/ctl2_test_suite_v4.json').read_text())['tests'];system=next(t['system_prompt'] for t in originals if t['test_id']=='T33')
 specs=json.loads((D/'round2/final_graph_specs.json').read_text());compile_data={r['test_id']:r for r in json.loads((D/'compile_results.json').read_text())};runs={r['test_id']:r for r in json.loads((D/'graph_run_results.json').read_text())};extra=json.loads((D/'round2/extra_run_results.json').read_text())
 components=set();stateful=[];hard=[]
 for t in rows:
  tid=t['test_id'];need(REQUIRED_KEYS<=t.keys(),tid+': missing object fields');need(t['type']=='generate' and t['group']=='rw' and t['temperature']==.4,tid+': category/temperature')
  need(t['system_prompt']==system,tid+': system prompt differs from T33');spec=specs[tid]
  components.add(TYPE_MAP[t['component'].split(' (')[0]])
  words=len(t['user_message'].split());need(300<=words<=900,tid+': prompt word count')
  clauses=re.findall(r'^([0-9]+)\. (.*?)(?=\n[0-9]+\. |\n\n|\Z)',t['user_message'],re.M|re.S);nums=[int(n) for n,_ in clauses]
  need(8<=len(nums)<=10 and nums==list(range(1,len(nums)+1)),tid+': numbered clauses')
  required=t['rubric']['required'];forbidden=t['rubric']['forbidden'];need(8<=len(required)<=12 and 2<=len(forbidden)<=5,tid+': rubric resolution')
  need(t['rubric']['scoring']=={'method':'required_fraction','forbidden_penalty':.2},tid+': scoring')
  covered=set()
  for item in required:
   need({'id','check','rationale','clauses'}<=item.keys() and item['check'] and item['rationale'],tid+': malformed required item');covered.update(item.get('clauses',[]))
  need(covered==set(nums),tid+': clause/rubric coverage')
  itemids=[r['id'] for r in required+forbidden];need(len(itemids)==len(set(itemids)),tid+': duplicate rubric IDs')
  for item in forbidden:need({'id','check','rationale'}<=item.keys(),tid+': malformed forbidden item')
  blocks=re.findall(r'<Record\b.*?</Record>',t['user_message'],re.S);names=set();fieldcounts=[]
  for block in blocks:
   try:record=ET.fromstring(block)
   except ET.ParseError as e:errors.append(tid+': XML '+str(e));continue
   fs=record.findall('Field');fn=[f.get('name') for f in fs];names.update(fn);fieldcounts.append(len(fs))
   need(12<=len(fs)<=40,tid+': metadata field count in '+str(record.get('name')));need(len(fn)==len(set(fn)),tid+': duplicate metadata fields')
   need(record.get('name') and record.get('type')=='delimited',tid+': metadata attributes');need(any(f.get('type')=='date' for f in fs),tid+': metadata date')
   need(any(f.get('type')=='decimal' for f in fs),tid+': metadata decimal');need({f.get('nullable') for f in fs}=={'true','false'},tid+': explicit mixed nullability')
   for f in fs:
    if f.get('type')=='decimal':need(f.get('length') and f.get('scale'),tid+': decimal precision/scale')
  need(any('unused' in n for n in names),tid+': unrelated metadata field')
  prose=re.sub(r'<Record\b.*?</Record>','',t['user_message'],flags=re.S)+' '+ ' '.join(r['check']+' '+r['rationale'] for r in required+forbidden)
  prose=re.sub(r'\b[\w.-]+\.(?:csv|grf|fmt|ctl)\b','',prose)
  named=set(re.findall(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b',prose))
  properties=set(re.findall(r'\["([a-z][a-z0-9]*(?:_[a-z0-9]+)+)"\]',t['reference']))
  resources=set(spec.get('resources',{}).get('parameters',{}))
  need(named<=names|properties|resources,tid+': undeclared business fields '+str(sorted(named-names-properties-resources)))
  # Every real port field reference is checked against that CTL slot, not union metadata.
  compiler=compile_data[tid];request=compiler['request']
  for direction,p,name in re.findall(r'\$(in|out)\.(\d+)\.([A-Za-z_]\w*)',t['reference']):
   ports=request.get('inputMetadata' if direction=='in' else 'outputMetadata',[]);p=int(p)
   need(p<len(ports),tid+': CTL port not connected')
   if p<len(ports):need(name in {f.get('name') for f in ET.fromstring(ports[p]).findall('Field')},tid+': wrong port field '+name)
  need(t['reference'].startswith('//#CTL2\n'),tid+': header');need(request['code']==t['reference'] and compiler['reference_sha256']==sha(t['reference']),tid+': stale compiler code')
  result=json.loads(t['compile_result']);need(result==compiler['payload'],tid+': compile payload mismatch')
  standalone=result.get('overall')=='PASS' and result.get('problems')==[]
  need(t['standalone_reference_compiles'] is standalone,tid+': incorrect standalone flag');need(standalone or scope_diagnostics(result,spec),tid+': unapproved standalone compiler diagnostics')
  need(t['reference_compiles'] is True,tid+': unverified compilation')
  run=runs[tid];manifest=json.loads((D/'run_graphs'/tid/'manifest.json').read_text());localgraph=D/'run_graphs'/tid/'graph'/(tid+'.grf')
  need(t['reference_runs'] is True and run['reference_runs'] is True,tid+': reference did not run successfully')
  need(run['reference_sha256']==sha(t['reference']) and run['graph_sha256']==hashlib.sha256(localgraph.read_bytes()).hexdigest(),tid+': stale graph/reference evidence')
  need(run['completion']['status']=='FINISHED_OK' and run['validation']['overall']=='PASS' and run['validation']['problems']==[],tid+': graph validation/execution')
  need(t['graph_file']==run['graph_file'] and t['run_ids'] and run['run_ids'][0] in t['run_ids'],tid+': run identity')
  graphroot=ET.fromstring(localgraph.read_text());embedded=graphroot.find(".//Node[@id='Test']/attr[@name='"+{'REFORMAT':'transform','DATA_INTERSECTION':'transform','EXT_MERGE_JOIN':'transform','ROLLUP':'transform','DENORMALIZER':'denormalize','NORMALIZER':'normalize','PARTITION':'partitionSource','DATA_GENERATOR':'generate'}[TYPE_MAP[t['component'].split(' (')[0]]]+"']")
  need(embedded is not None and embedded.text==t['reference'],tid+': graph does not run literal reference')
  need(manifest['fixture']==spec['fixture'],tid+': stale hand-derived fixture')
  for port,output in run['outputs'].items():
   x=manifest['output_metadata'][int(port)];raw=(D/output['actual_file']).read_text();actual=parse_actual(raw,x);expected=normalized_rows(spec['fixture']['expected'].get(port,[]),x)
   need(actual==expected==output['actual']==output['expected'],tid+': actual/expected full-record mismatch port '+port)
  need(all(r['passed'] for r in run['row_checks']),tid+': per-record check')
  for e in [e for e in extra if e['test_id']==tid]:need(e['reference_runs'] and e['reference_sha256']==sha(t['reference']),tid+': extra boundary/negative fixture failed or stale')
  total=sum(len(a) for a in spec['fixture']['inputs'])
  need(8<=total<=20 if total else 8<=spec['fixture']['rows_count']<=20,tid+': main fixture population outside8–20')
  for i,port in enumerate(spec['fixture']['inputs']):
   fs={f.get('name') for f in ET.fromstring(spec['inputMetadata'][i]).findall('Field')}
   need(all(set(r)==fs for r in port),tid+': fixture input schema')
  traps=t.get('difficulty_traps',[])
  if any(re.search(r'first|previous|per.group|state|reset|predecessor|history|sentinel|list',q,re.I) for q in traps):stateful.append(tid)
  if len(traps)>=2:hard.append(tid)
  if t['component'].startswith('Denormalizer') or t['component'].startswith('Rollup'):stateful.append(tid)
  stats.append(dict(test_id=tid,words=words,record_field_counts=fieldcounts,required_count=len(required),clause_count=len(nums),fixture_input_count=total,output_count=sum(len(o['actual']) for o in run['outputs'].values()),standalone_compiles=standalone))
 need(len(components)>=8,'Need at least8 actual component types');need(len(set(stateful))>=6,'Need at least6 state/sentinel tests');need(len(hard)>=12,'Need at least12 multi-trap candidates')
 # Full prompt normalisation follows the external dedup script exactly.
 ng=[grams(t['user_message']) for t in rows];pairs=[]
 for i in range(len(rows)):
  for j in range(i+1,len(rows)):
   similarity=len(ng[i]&ng[j])/len(ng[i]|ng[j]);pairs.append(dict(a=rows[i]['test_id'],b=rows[j]['test_id'],jaccard=similarity));need(similarity<.30,'Cross-prompt5gram Jaccard>=.30 '+rows[i]['test_id']+'/'+rows[j]['test_id'])
 dedup=json.loads((D/'dedup_report.json').read_text());need(not dedup['exact_matches'] and dedup['max_external_jaccard']<=.5,'External duplication threshold');need(dedup['suite_sha256']==hashlib.sha256(Path(path).read_bytes()).hexdigest(),'Stale dedup report')
 need(len({r['reference'] for r in rows})==30 and len({r['user_message'] for r in rows})==30,'Duplicate new reference/prompt')
 for lo,hi in [(44,53),(54,63),(64,73)]:
  review=json.loads((D/'round2'/f'review_t{lo}_t{hi}.json').read_text());entries=review.get('final_addendum',{}).get('tests',review['tests']);byid={e['test_id']:e for e in entries}
  for t in rows:
   if lo<=int(t['test_id'][1:])<=hi:
    e=byid.get(t['test_id'],{});need(e.get('final_reference_sha256',e.get('reference_sha256'))==sha(t['reference']),t['test_id']+': stale independent reference review');need(e.get('final_prompt_sha256',e.get('prompt_sha256'))==sha(t['user_message']),t['test_id']+': stale independent prompt review')
 return dict(passed=not errors,errors=errors,tests=stats,archetypes=dict(counts),actual_components=sorted(components),stateful_test_ids=sorted(set(stateful)),multi_trap_candidate_ids=hard,pairwise_max=max(p['jaccard'] for p in pairs),nearest_internal_pairs=sorted(pairs,key=lambda p:p['jaccard'],reverse=True)[:10],dedup_missing_inputs=dedup['missing_inputs'],scope_compile_exception_ids=[r['test_id'] for r in rows if not r['standalone_reference_compiles']],run_verified_tests=30)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('path',nargs='?',type=Path,default=D/'generate_rw.json');p.add_argument('--report',type=Path);args=p.parse_args();result=check(args.path)
 if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k!='tests'},indent=2));sys.exit(0 if result['passed'] else 1)
