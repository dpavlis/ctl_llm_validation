"""Scoped local MCP client. Writes/runs only SuiteV5 or MiscExamples/suite_v5."""
import asyncio,json,sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
D=Path(__file__).parent
def payload(result):
 if result.structuredContent is not None:return result.structuredContent
 texts='\n'.join(c.text for c in result.content if c.type=='text')
 try:return json.loads(texts)
 except json.JSONDecodeError:return {'text':texts,'isError':result.isError}
def guard(name,args):
 allowed={'task_workflow_get','sandbox_list','knowledge_list_resources','knowledge_read_resource','knowledge_base_search','knowledge_base_read','sandbox_get_workspace_parameters','component_get_info','component_get_guide','ctl_validate','sandbox_write_file','sandbox_read_file','job_validate','job_run','job_await','job_get_tracking','job_get_log'}
 assert name in allowed,'Tool outside suite harness scope'
 if name in {'sandbox_write_file','sandbox_read_file','job_validate','job_run'}:
  assert args['sandboxCode'] in ['MiscExamples','SuiteV5']
  if name in ['job_run','job_validate']:
   assert args['jobFile'].startswith('suite_v5/') and '..' not in Path(args['jobFile']).parts
  else:
   assert args.get('sandboxPath','').startswith('suite_v5/')
   assert '..' not in args.get('sandboxPath','') and '/' not in args.get('filename','')
async def run(requests):
 outputs=[]
 async with streamablehttp_client('http://localhost:8083/clover/mcp/mcp',timeout=120) as (r,w,_):
  async with ClientSession(r,w) as s:
   await s.initialize()
   workflow=await s.call_tool('task_workflow_get',{'task':'validate_and_run'})
   for request in requests:
    name=request['tool'];args=request.get('arguments',{});guard(name,args)
    result=await s.call_tool(name,args);p=payload(result)
    outputs.append(dict(tool=name,arguments=args,payload=p,response=result.model_dump(mode='json',exclude_none=True)))
    if request.get('save'): (D/request['save']).write_text(json.dumps(p,indent=2,ensure_ascii=False)+'\n')
    print(name,request.get('label',''),json.dumps(p)[:600] if request.get('print',False) else ('ERROR' if result.isError else 'OK'),flush=True)
 return outputs
if __name__=='__main__':
 requests=json.loads(Path(sys.argv[1]).read_text());result=asyncio.run(run(requests))
 out=Path(sys.argv[2]) if len(sys.argv)>2 else D/'last_mcp_batch.json';out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
