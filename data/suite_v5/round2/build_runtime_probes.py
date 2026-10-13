"""Live semantic probes; observations are preserved independently of suite expectations."""
import json
from pathlib import Path
from graph_harness import build,D
from rw2_common import field,record
F=field
probes=[]
def add(id,component,code,inputs,outputs,fixture,settings=None,resources=None):
 test=dict(test_id=id,reference=code,rubric={'description':id+' runtime contract probe'})
 spec=dict(test_id=id,component=component,inputMetadata=[record(n,f) for n,f in inputs],outputMetadata=[record(n,f) for n,f in outputs],fixture=fixture,settings=settings or {},resources=resources or {})
 manifest=build(test,spec);probes.append(manifest)
# Probe conversions independently; do not assume shape validation in isDate.
fs=[F('case_id','integer',False),F('raw_date'),F('decimal_threw','boolean',False),F('decimal_null','boolean',False),F('is_date','boolean',False),F('parse_threw','boolean',False),F('parsed_date'),F('unicode_length','integer',False)]
code='''//#CTL2
integer i=0;
function integer generate(){
 i++;$out.0.case_id=i;
 string text=i%2==1 ? "2025-02-30" : "2025-1-1";
 $out.0.raw_date=text;$out.0.decimal_threw=false;$out.0.decimal_null=false;
 try {decimal d=str2decimal("");$out.0.decimal_null=isnull(d);} catch(CTLException e){$out.0.decimal_threw=true;}
 $out.0.is_date=isDate(text,"yyyy-MM-dd","en.US","UTC",true);
 $out.0.parse_threw=false;$out.0.parsed_date=null;
 try {date dt=str2date(text,"yyyy-MM-dd","en.US","UTC",true);$out.0.parsed_date=date2str(dt,"yyyy-MM-dd HH:mm:ss","en.US","UTC");}catch(CTLException e){$out.0.parse_threw=true;}
 $out.0.unicode_length=length("A😀");
 return OK;
}'''
# Expected provisional observations will be corrected only after inspecting actual evidence.
expected=[dict(case_id=i,raw_date='2025-02-30' if i%2 else '2025-1-1',decimal_threw=True,decimal_null=False,is_date=False,parse_threw=True,parsed_date=None,unicode_length=3) for i in range(1,9)]
add('P901','DataGenerator',code,[],[('ConversionProbe',fs)],dict(inputs=[],expected={'0':expected},rows_count=8))
add('P902','DataGenerator','//#CTL2\nfunction integer generate(){raiseError("ZERO_GENERATOR_CALLED");}',[],[('ZeroProbe',[F('called','boolean')])],dict(inputs=[],expected={'0':[]},rows_count=0))
# Reset-at-transform vs clean() using three groups (3,1,4 rows).
infs=[F('group_key',nullable=False),F('amount','integer',False)];outfs=[F('group_key',nullable=False),F('rows_seen','integer',False),F('total','integer',False)]
inputs=[dict(group_key=k,amount=a) for k,a in [('A',2),('A',3),('A',1),('B',4),('C',0),('C',5),('C',-1),('C',2)]]
expected=[dict(group_key='A',rows_seen=3,total=6),dict(group_key='B',rows_seen=1,total=4),dict(group_key='C',rows_seen=4,total=6)]
code='''//#CTL2
integer n=0;integer sum=0;
function integer append(){n++;sum+=$in.0.amount;return OK;}
function integer transform(){$out.0.group_key=$in.0.group_key;$out.0.rows_seen=n;$out.0.total=sum;n=0;sum=0;return OK;}
function void clean(){}'''
add('P903','Denormalizer',code,[('GroupProbe',infs)],[('GroupResult',outfs)],dict(inputs=[inputs],expected={'0':expected}),{'key':'group_key'})
# Four return values plus hooks that throw if one-sided records ever invoke them.
side=[F('key_id','integer'),F('value_cd')];match=[F('key_id','integer'),F('pair_txt')]
a=[dict(key_id=k,value_cd=v) for k,v in [(None,'NA'),(1,'A1'),(2,'A2'),(2,'A3'),(4,'A4')]]
b=[dict(key_id=k,value_cd=v) for k,v in [(None,'NB'),(2,'B2'),(2,'B3'),(3,'B3'),(5,'B5')]]
for j,value in enumerate(['OK','1','ALL','SKIP'],start=4):
 code='''//#CTL2
function integer transform(){$out.0.key_id=$in.1.key_id;$out.0.pair_txt=$in.0.value_cd+":"+$in.1.value_cd;return '''+value+''';}
function integer transformLeftOnly(){raiseError("LEFT_HOOK_CALLED");}
function integer transformRightOnly(){raiseError("RIGHT_HOOK_CALLED");}
'''
 matches=[] if value=='SKIP' else [dict(key_id=None,pair_txt='NA:NB')]+[dict(key_id=2,pair_txt=x+':'+y) for x in ['A2','A3'] for y in ['B2','B3']]
 add('P90'+str(j),'DataIntersection',code,[('Side',side),('Side',side)],[('Side',side),('Both',match),('Side',side)],dict(inputs=[a,b],expected={'0':[a[1],a[4]],'1':matches,'2':[b[3],b[4]]}),{'joinKey':'$key_id=$key_id','equalNULL':True,'keyDuplicates':True})
# Dictionary typed default values, mutable counter and Unicode digest source.
fs=[F('flag','boolean',False),F('label',nullable=False),F('counter','integer',False)]
code='''//#CTL2
function integer generate(){$out.0.flag=dictionary.Enabled;$out.0.label=dictionary.RunLabel;dictionary.Count=dictionary.Count+1;$out.0.counter=dictionary.Count;return OK;}'''
add('P908','DataGenerator',code,[],[('DictResult',fs)],dict(inputs=[],expected={'0':[dict(flag=True,label='RW2',counter=i) for i in range(1,9)]},rows_count=8),resources={'dictionary':[{'name':'Enabled','type':'boolean','value':True},{'name':'RunLabel','type':'string','value':'RW2'},{'name':'Count','type':'integer','value':0}]})
(D/'round2/probe_manifests.json').write_text(json.dumps(probes,indent=2)+'\n');print('Built',len(probes),'probes')
