"""Shared schema helpers; each author module owns independent business scenarios."""
import hashlib,json
from pathlib import Path
from xml.sax.saxutils import escape
D=Path(__file__).resolve().parents[1]
OLD={t['test_id']:t for t in json.loads((D/'round1/generate_rw.json').read_text())}
SYSTEM=OLD['T44']['system_prompt']
def field(name,typ='string',nullable=True,**attrs):
 if typ=='date':attrs.setdefault('timeZone','UTC')
 return dict(name=name,type=typ,nullable=str(nullable).lower(),**attrs)
def decimal(name,nullable=True,precision=18,scale=2):return field(name,'decimal',nullable,length=str(precision),scale=str(scale))
def record(name,fields):return '<Record name="'+name+'" type="delimited" fieldDelimiter="|" recordDelimiter="\\n" nullValue="__NULL__">\n'+''.join('  <Field '+' '.join(k+'="'+escape(str(v),{'"':'&quot;'})+'"' for k,v in x.items())+'/>\n' for x in fields)+'</Record>'
def make(tid,archetype,component,title,intro,clauses,inputs,outputs,code,checks,forbidden,fixture,settings=None,resources=None,acc=None,change=None,traps=None):
 assert 8<=len(clauses)<=10,(tid,len(clauses))
 assert 8<=len(checks)<=12,(tid,len(checks))
 ins=[record(*x) for x in inputs];outs=[record(*x) for x in outputs]
 msg=title+'\n\n'+intro+'\n\nWrite the complete CTL2 for this component only, including its required entry functions.\n\n'+'\n'.join(f'{i+1}. {s}' for i,s in enumerate(clauses))+'\n\n'
 for i,x in enumerate(ins):msg+=f'Input metadata port {i}:\n```xml\n{x}\n```\n\n'
 for i,x in enumerate(outs):msg+=f'Output metadata port {i}:\n```xml\n{x}\n```\n\n'
 if acc:msg+='Accumulator metadata:\n```xml\n'+record(*acc)+'\n```\n\n'
 for lookup in (resources or {}).get('lookups',[]):msg+='Reference metadata '+lookup['name']+':\n```xml\n'+lookup['metadata']+'\n```\n\n'
 required=[dict(id=tid+'.'+str(i+1),check=c,rationale=r,clauses=cl) for i,(c,r,cl) in enumerate(checks)]
 assert set(c for r in required for c in r['clauses'])==set(range(1,len(clauses)+1)),tid
 old=OLD[tid]
 test=dict(test_id=tid,type='generate',group='rw',component=component,archetype=archetype,temperature=.4,system_prompt=SYSTEM,user_message=msg,rubric=dict(description=title,required=required,forbidden=[dict(id=tid+'.F'+str(i+1),check=c,rationale=r) for i,(c,r) in enumerate(forbidden)],scoring=dict(method='required_fraction',forbidden_penalty=.2)),reference=code if code.startswith('//#CTL2') else '//#CTL2\n'+code,reference_compiles=False,compile_result='Pending round-2 compiler check',reference_runs=False,graph_file=None,run_ids=[],retired_scenario=None if (change or {}).get('action')=='kept' else dict(component=old['component'],prompt_sha256=hashlib.sha256(old['user_message'].encode()).hexdigest(),reference_sha256=hashlib.sha256(old['reference'].encode()).hexdigest(),archived_file='round1/generate_rw.json'),difficulty_traps=traps or [])
 spec=dict(test_id=tid,component=component,inputMetadata=ins,outputMetadata=outs,settings=settings or {},resources=resources or {},fixture=fixture)
 if acc:spec['accumulatorMetadata']=record(*acc)
 return dict(test=test,graph_spec=spec,change=dict(test_id=tid,**(change or {'action':'replaced','reason':'Distinct business mechanism and edge cases.'})))
def write_shard(name,objects):
 p=D/'round2'/name;p.write_text(json.dumps(objects,indent=2,ensure_ascii=False)+'\n');print('Wrote',p)
