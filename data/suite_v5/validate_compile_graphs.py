"""Install isolated compiler-only fixtures and validate full graph resource context."""
import asyncio,json,hashlib,shutil
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
D=Path(__file__).parent
TARGET=Path('/home/pavlisd/cloverserver/CloverDXServer.7.4.2.Tomcat-10.1.54/sandboxes/DWHExample/data-tmp/suite_v5_compile')
async def main():
 TARGET.mkdir(exist_ok=True)
 for p in (D/'compile_graphs').glob('*.grf'):shutil.copy2(p,TARGET/p.name)
 rows=json.loads((D/'generate_rw.json').read_text());reports=[]
 async with streamablehttp_client('http://localhost:8083/clover/mcp/mcp',timeout=120) as (r,w,_):
  async with ClientSession(r,w) as s:
   await s.initialize()
   for p in sorted((D/'compile_graphs').glob('*.grf')):
    args=dict(sandboxCode='DWHExample',jobFile='data-tmp/suite_v5_compile/'+p.name)
    result=await s.call_tool('job_validate',args)
    payload=result.structuredContent
    if payload is None:
     raw=next(b.text for b in result.content if b.type=='text')
     try:payload=json.loads(raw)
     except json.JSONDecodeError:payload={'overall':'FAIL','tool_error':raw}
    reports.append(dict(test_id=p.stem,request=args,response=result.model_dump(mode='json',exclude_none=True),payload=payload,graph_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    print(p.stem,payload,flush=True)
 (D/'graph_compile_results.json').write_text(json.dumps(reports,indent=2)+'\n')
asyncio.run(main())
