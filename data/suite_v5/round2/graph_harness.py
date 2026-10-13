"""Build self-contained file→reference→file graphs and compare complete typed rows.

Expected rows come from separately authored acceptance-contract fixtures. The
harness never executes a reference to generate its expected results.
"""
import csv,hashlib,io,json,re,xml.etree.ElementTree as E
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
D=Path(__file__).resolve().parents[1];R=D/'run_graphs';R.mkdir(exist_ok=True)
TYPE_MAP={'Reformat':'REFORMAT','DataIntersection':'DATA_INTERSECTION','ExtMergeJoin':'EXT_MERGE_JOIN','Rollup':'ROLLUP','Denormalizer':'DENORMALIZER','Normalizer':'NORMALIZER','Partition':'PARTITION','DataGenerator':'DATA_GENERATOR','Standalone / pure function':'REFORMAT'}
ANCHOR={'REFORMAT':'transform','DATA_INTERSECTION':'transform','EXT_MERGE_JOIN':'transform','ROLLUP':'transform','DENORMALIZER':'denormalize','NORMALIZER':'normalize','PARTITION':'partitionSource','DATA_GENERATOR':'generate'}
NULL='__NULL__'; DELIM='|'
def fields(xml):return E.fromstring(xml).findall('Field')
def canonical_date(value):
 if value is None:return None
 value=str(value).replace('T',' ').removesuffix('Z')
 if len(value)==10:value+=' 00:00:00'
 if len(value)==19:value+='.000'
 return value

def normal(value,f):
 if value is None:return None
 if f.get('containerType') or f.get('type')=='variant':
  if isinstance(value,str):return json.loads(value)
  return value
 t=f.get('type')
 if t in ['integer','long']:return int(value)
 if t=='boolean':return value if isinstance(value,bool) else value.lower()=='true'
 if t=='decimal':d=Decimal(str(value)).quantize(Decimal(1).scaleb(-int(f.get('scale','2'))));return str(abs(d) if d==0 else d)
 if t=='number':return float(value)
 if t=='date':return canonical_date(value)
 return str(value)
def raw_metadata(xml,name):
 root=E.fromstring(xml);root.set('name',name);root.set('locale','en.US');root.set('nullValue',NULL)
 for f in root.findall('Field'):
  f.set('type','string');f.attrib.pop('containerType',None);f.attrib.pop('format',None);f.attrib.pop('length',None);f.attrib.pop('scale',None)
 return E.tostring(root,encoding='unicode')
def csv_text(rows,xml,typed=False):
 fs=fields(xml);out=io.StringIO();w=csv.writer(out,delimiter=DELIM,quotechar='"',lineterminator='\n')
 for row in rows:
  assert set(row)=={f.get('name') for f in fs},('Incomplete fixture row',set(row),{f.get('name') for f in fs})
  values=[]
  for f in fs:
   v=row[f.get('name')]
   if v is None:v=NULL
   elif f.get('containerType') or f.get('type')=='variant':v=json.dumps(v,ensure_ascii=False,separators=(',',':')) if not isinstance(v,str) else v
   elif f.get('type')=='date':
    v=canonical_date(v)
    if typed:
     pattern=f.get('format','yyyy-MM-dd HH:mm:ss.SSS')
     v=v[:10] if pattern=='yyyy-MM-dd' else v[:19] if pattern=='yyyy-MM-dd HH:mm:ss' else v
   elif isinstance(v,bool):v='true' if v else 'false'
   values.append(v)
  w.writerow(values)
 return out.getvalue()
def parse_actual(text,xml):
 fs=fields(xml);result=[]
 for raw in csv.reader(io.StringIO(text),delimiter=DELIM,quotechar='"'):
  if not raw:continue
  assert len(raw)==len(fs),(len(raw),len(fs),raw)
  result.append({f.get('name'):normal(None if value==NULL else value,f) for f,value in zip(fs,raw)})
 return result
def normalized_rows(rows,xml):return [{f.get('name'):normal(row[f.get('name')],f) for f in fields(xml)} for row in rows]
def node(phase,id,typ,attrs=None,code=None,anchor=None,x=50,y=150):
 n=E.SubElement(phase,'Node',id=id,type=typ,enabled='enabled',guiName=id,guiX=str(x),guiY=str(y))
 for k,v in (attrs or {}).items():E.SubElement(n,'attr',name=k).text=str(v).lower() if isinstance(v,bool) else str(v)
 if code:E.SubElement(n,'attr',name=anchor or ANCHOR[typ]).text=code
 return n
def edge(phase,id,source,dest,meta):E.SubElement(phase,'Edge',id=id,fromNode=source,toNode=dest,metadata=meta,guiRouter='Manhattan',inPort='Port 0 (in)',outPort='Port 0 (out)')
def build(test,spec,variant=None):
 tid=test['test_id'];label=tid+(('_'+variant['name']) if variant else '')
 fixture=deepcopy(spec['fixture']);settings=deepcopy(spec.get('settings',{}));resources=deepcopy(spec.get('resources',{}));reference=test['reference']
 if variant:
  fixture.update({k:v for k,v in variant.items() if k in ['inputs','expected','params','rows_count','expected_failure']})
  settings.update(variant.get('settings',{}));resources['parameters'].update(variant.get('params',{})) if resources.get('parameters') else resources.update(parameters=variant.get('params',{}))
  reference=variant.get('reference',reference)
  if 'dictionary' in variant:resources['dictionary']=variant['dictionary']
  if 'resources' in variant:resources.update(variant['resources'])
 root=E.Element('Graph',author='Codex',name=label,id=str(6101300000+int(re.sub(r'\D','',tid) or '0')),nature='etlGraph',revision='1.0',guiVersion='7.5.0')
 glob=E.SubElement(root,'Global');params=E.SubElement(glob,'GraphParameters')
 E.SubElement(params,'GraphParameterFile',fileURL='workspace.prm')
 E.SubElement(params,'GraphParameter',name='PROJECT',value='.')
 for k,v in resources.get('parameters',{}).items():E.SubElement(params,'GraphParameter',name=k,value=str(v))
 note=E.SubElement(glob,'RichTextNote',id='Note',x='50',y='25',width='1200',height='100',backgroundColor='FAF6D6',textColor='444444',fontSize='medium',folded='false')
 E.SubElement(note,'attr',name='text').text=test['rubric']['description']+'\nAcceptance fixture exercises the business rules and preserves every source field for comparison.'
 paths=[]; local=R/label
 for sub in ['graph','data-in','data-out','expected']: (local/sub).mkdir(parents=True,exist_ok=True)
 def metadata(mid,x):E.SubElement(glob,'Metadata',id=mid).append(E.fromstring(x))
 ins=spec.get('inputMetadata',[]);outs=spec.get('outputMetadata',[])
 if not outs and spec['component'].startswith('Partition'):
  outs=[ins[0] for _ in range(max(int(p) for p in fixture['expected'])+1)]
 for i,x in enumerate(ins):metadata('In'+str(i),x);metadata('RawIn'+str(i),raw_metadata(x,'RawInput'+str(i)))
 for i,x in enumerate(outs):metadata('Out'+str(i),x);metadata('RawOut'+str(i),raw_metadata(x,'RawOutput'+str(i)))
 if spec.get('accumulatorMetadata'):metadata('Accumulator',spec['accumulatorMetadata']);settings['groupAccumulatorMetadataId']='Accumulator'
 for i,l in enumerate(resources.get('lookups',[])):
  metadata('Lookup'+str(i),l['metadata'])
  p=local/'data-in'/('lookup_'+str(i)+'.csv');p.write_text(csv_text(l['rows'],l['metadata'],typed=True))
  path='suite_v5/data-in/'+label+'_lookup_'+str(i)+'.csv';paths.append((p,path))
  lookup=E.SubElement(glob,'LookupTable',id=l.get('id',l['name']),name=l['name'],type='simpleLookup',charset='UTF-8',metadata='Lookup'+str(i),key=';'.join(l['key']),initialSize='64',keyDuplicates=str(l.get('keyDuplicates',True)).lower(),allowKeyDuplicates=str(l.get('keyDuplicates',True)).lower())
  E.SubElement(lookup,'attr',name='fileURL').text=path
 for s in resources.get('sequences',[]):E.SubElement(glob,'Sequence',id=s.get('id',s['name']),name=s['name'],start=str(s.get('start',1)),step=str(s.get('step',1)),type='PRIMITIVE_SEQUENCE')
 if resources.get('dictionary'):
  dictionary=E.SubElement(glob,'Dictionary')
  for entry in resources['dictionary']:
   value=entry['value'];value=str(value).lower() if isinstance(value,bool) else str(value)
   E.SubElement(dictionary,'Entry',name=entry['name'],type=entry['type'],input='true',**{'dictval.value':value})
 phase=E.SubElement(root,'Phase',number='0')
 for i,x in enumerate(ins):
  p=local/'data-in'/('input_'+str(i)+'.csv');p.write_text(csv_text(fixture['inputs'][i],x));path='suite_v5/data-in/'+label+'_input_'+str(i)+'.csv';paths.append((p,path))
  node(phase,'Reader'+str(i),'DATA_READER',{'fileURL':path,'charset':'UTF-8','dataPolicy':'strict','quotedStrings':True,'quoteCharacter':'"','parser':'org.jetel.data.parser.DataParser'},x=50,y=200+i*175)
  code='//#CTL2\nfunction integer transform(){\n'
  for f in fields(x):
   n=f.get('name');t=f.get('type');value='$in.0.'+n
   if f.get('containerType'):
    ct=f.get('containerType');value='cast(parseJson('+value+'),'+('list,'+t if ct=='list' else 'map,string,'+t)+')'
   elif t=='variant':value='parseJson('+value+')'
   elif t=='date':value='str2date('+value+',"yyyy-MM-dd HH:mm:ss.SSS","en.US","UTC",true)'
   elif t in ['integer','long','decimal','number','boolean']:value={'integer':'str2integer','long':'str2long','decimal':'str2decimal','number':'str2double','boolean':'str2bool'}[t]+'('+value+')'
   if t!='string' or f.get('containerType'):value='$in.0.'+n+' == null ? null : '+value
   code+='$out.0.'+n+'='+value+';\n'
  code+='return OK;}'
  node(phase,'Decode'+str(i),'REFORMAT',code=code,x=275,y=200+i*175)
  edge(phase,'Read'+str(i),'Reader'+str(i)+':0','Decode'+str(i)+':0','RawIn'+str(i));edge(phase,'Decoded'+str(i),'Decode'+str(i)+':0','Test:'+str(i),'In'+str(i))
 typ=TYPE_MAP.get(spec['component'].split(' (')[0],spec['component'])
 if typ=='DATA_GENERATOR':settings.setdefault('recordsNumber',fixture.get('rows_count',10))
 settings.setdefault('charset','UTF-8') if typ in ['REFORMAT','DENORMALIZER','NORMALIZER','PARTITION','DATA_INTERSECTION','EXT_MERGE_JOIN'] else None
 node(phase,'Test',typ,settings,code=reference,x=500,y=200)
 for i,x in enumerate(outs):
  code='//#CTL2\nfunction integer transform(){\n'
  for f in fields(x):
   n=f.get('name');t=f.get('type');value='$in.0.'+n
   if f.get('containerType') or t=='variant':value='writeJson('+value+')'
   elif t=='date':value='date2str('+value+',"yyyy-MM-dd HH:mm:ss.SSS","en.US","UTC")'
   elif t=='decimal':value='num2str('+value+',"0'+('.'+'0'*int(f.get('scale','2')) if int(f.get('scale','2')) else '')+'","en.US")'
   elif t in ['integer','long','number']:value='num2str('+value+')'
   elif t=='boolean':value='('+value+' ? "true" : "false")'
   if t!='string' or f.get('containerType'):value='$in.0.'+n+' == null ? null : '+value
   code+='$out.0.'+n+'='+value+';\n'
  code+='return OK;}'
  node(phase,'Encode'+str(i),'REFORMAT',code=code,x=725,y=200+i*175)
  outputpath='suite_v5/data-out/'+label+'_out_'+str(i)+'.csv'
  node(phase,'Writer'+str(i),'DATA_WRITER',{'fileURL':outputpath,'charset':'UTF-8','makeDirs':True,'quotedStrings':True,'quoteCharacter':'"','createEmptyFiles':True,'append':False},x=950,y=200+i*175)
  edge(phase,'Result'+str(i),'Test:'+str(i),'Encode'+str(i)+':0','Out'+str(i));edge(phase,'Written'+str(i),'Encode'+str(i)+':0','Writer'+str(i)+':0','RawOut'+str(i))
  expected=fixture.get('expected',{}).get(str(i),[]);(local/'expected'/('output_'+str(i)+'.json')).write_text(json.dumps(expected,indent=2,ensure_ascii=False)+'\n')
 graph=local/'graph'/(label+'.grf');E.indent(root);E.ElementTree(root).write(graph,encoding='utf-8',xml_declaration=True)
 graphpath='suite_v5/graph/'+label+'.grf';paths.append((graph,graphpath))
 manifest=dict(test_id=tid,label=label,graph_file=graphpath,reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),graph_sha256=hashlib.sha256(graph.read_bytes()).hexdigest(),files=[dict(local=str(p.relative_to(D)),remote=rp,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p,rp in paths],output_paths={str(i):'suite_v5/data-out/'+label+'_out_'+str(i)+'.csv' for i in range(len(outs))},output_metadata=outs,fixture=fixture,parameters=fixture.get('params',{}),expected_failure=fixture.get('expected_failure',False))
 (local/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n');return manifest
