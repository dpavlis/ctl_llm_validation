"""Execute prepared suite-only graph fixtures; retain every MCP response and row comparison."""
import argparse,asyncio,hashlib,json,sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp_batch import payload,guard
from graph_harness import D,R,parse_actual,normalized_rows
async def execute(manifests,report_file):
 report=[]
 if report_file.exists():report=json.loads(report_file.read_text())
 labels={m['label'] for m in manifests};report=[r for r in report if r['label'] not in labels]
 async with streamablehttp_client('http://localhost:8083/clover/mcp/mcp',timeout=120) as (r,w,_):
  async with ClientSession(r,w) as s:
   await s.initialize();await s.call_tool('task_workflow_get',{'task':'validate_and_run'})
   async def call(name,args,evidence):
    guard(name,args);result=await s.call_tool(name,args);p=payload(result)
    evidence.append(dict(tool=name,arguments=args,payload=p,response=result.model_dump(mode='json',exclude_none=True)))
    return p
   for m in manifests:
    local=R/m['label'];evidence=[];result=dict(test_id=m['test_id'],label=m['label'],graph_file=m['graph_file'],graph_sha256=m['graph_sha256'],reference_sha256=m['reference_sha256'],input_files=[x['local'] for x in m['files'] if '/data-in/' in x['local']],expected_files=[str(p.relative_to(D)) for p in sorted((local/'expected').glob('*.json'))],reference_runs=False,run_ids=[],outputs={},row_checks=[],expected_failure=m['expected_failure'])
    try:
     for f in m['files']:
      path=Path(f['remote']);await call('sandbox_write_file',dict(sandboxCode='MiscExamples',sandboxPath=str(path.parent),filename=path.name,content=(D/f['local']).read_text()),evidence)
     valid=await call('job_validate',dict(sandboxCode='MiscExamples',jobFile=m['graph_file'],timeoutSeconds=60),evidence);result['validation']=valid
     if valid.get('overall')!='PASS':raise RuntimeError('Graph validation did not pass: '+json.dumps(valid))
     run=await call('job_run',dict(sandboxCode='MiscExamples',jobFile=m['graph_file'],params=m.get('parameters',{})),evidence)
     rid=run['runId'];result['run_ids']=[rid]
     done=await call('job_await',dict(runId=rid,timeoutSeconds=60),evidence);result['completion']=done
     result['tracking']=await call('job_get_tracking',dict(runId=rid,detailed=True),evidence)
     log=await call('job_get_log',dict(runId=rid),evidence);result['log']=log
     if m['expected_failure']:
      text=json.dumps(log)+json.dumps(done)
      error=done.get('error',{});message=error.get('message','').lower()
      result['reference_runs']=done.get('status')=='ERROR' and error.get('componentId')=='Test' and 'initialization failed' not in message and 'compilation finished' not in message and (not m['fixture'].get('error_contains') or m['fixture']['error_contains'] in text)
      result['negative_failure_verified']=result['reference_runs']
     else:
      if done.get('status')!='FINISHED_OK':raise RuntimeError('Graph run status '+str(done.get('status')))
      for port,path in m['output_paths'].items():
       content=await call('sandbox_read_file',dict(sandboxCode='MiscExamples',sandboxPath=path),evidence)
       # sandbox_read_file returns text content wrapped either directly or as content.
       if isinstance(content,str):text=content
       elif 'content' in content:text=content['content']
       elif 'text' in content:text=content['text']
       else:raise RuntimeError('Unrecognised file response '+json.dumps(content))
       (local/'data-out'/('output_'+port+'.csv')).write_text(text)
       actual=parse_actual(text,m['output_metadata'][int(port)]);expected=normalized_rows(m['fixture']['expected'].get(port,[]),m['output_metadata'][int(port)])
       result['outputs'][port]=dict(actual=actual,expected=expected,actual_file=str((local/'data-out'/('output_'+port+'.csv')).relative_to(D)),pass_count=len(actual) if actual==expected else 0)
       for index in range(max(len(actual),len(expected))):
        a=actual[index] if index<len(actual) else None;e=expected[index] if index<len(expected) else None
        result['row_checks'].append(dict(port=int(port),index=index,passed=a==e,actual=a,expected=e))
      result['reference_runs']=all(c['passed'] for c in result['row_checks'])
      result['record_counts_match']=all(len(v['actual'])==len(v['expected']) for v in result['outputs'].values())
      result['reference_runs'] &= result['record_counts_match']
    except Exception as exc:result['error']=str(exc)
    result['evidence_file']=str((local/'mcp_evidence.json').relative_to(D));(local/'mcp_evidence.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
    report.append(result);report_file.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(m['label'],'PASS' if result['reference_runs'] else 'FAIL',result.get('run_ids'),str(result.get('error',''))[:1000],flush=True)
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--report',type=Path,default=D/'graph_run_results.json');args=p.parse_args()
 manifests=json.loads(args.manifest.read_text());asyncio.run(execute(manifests,args.report))
