"""Capture unfiltered, actual ctl_validate diagnostics (never use skip heuristics)."""
import asyncio,json
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
D=Path(__file__).parent
async def main():
 rows=json.loads((D/'generate_rw.json').read_text());ctx=json.loads((D/'compile_contexts.json').read_text());results=[]
 async with streamablehttp_client('http://localhost:8083/clover/mcp/mcp',timeout=120) as (r,w,_):
  async with ClientSession(r,w) as s:
   await s.initialize()
   for t in rows:
    c=dict(ctx[t['test_id']]);c.pop('graph_resources');c['code']=t['reference']
    response=await s.call_tool('ctl_validate',c)
    raw=response.model_dump(mode='json',exclude_none=True)
    payload=response.structuredContent
    if payload is None:
     payload=json.loads(next(b.text for b in response.content if b.type=='text'))
    t['compile_result']=json.dumps(payload,ensure_ascii=False)
    t['reference_compiles']=not response.isError and payload.get('overall')=='PASS' and not payload.get('problems')
    results.append({'test_id':t['test_id'],'request':c,'response':raw,'payload':payload,'header_mode':'//#CTL2','reference_sha256':__import__('hashlib').sha256(t['reference'].encode()).hexdigest()})
    print(t['test_id'],payload,flush=True)
 (D/'generate_rw.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n')
 (D/'compile_results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
asyncio.run(main())
