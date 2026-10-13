"""Self-contained graph fixtures for resources unavailable to ctl_validate."""
import json,xml.etree.ElementTree as E
from pathlib import Path
D=Path(__file__).parent; G=D/'compile_graphs';G.mkdir(exist_ok=True)
rows=json.loads((D/'generate_rw.json').read_text());contexts=json.loads((D/'compile_contexts.json').read_text())
for row in rows:
 c=contexts[row['test_id']];resources=c['graph_resources']
 if not resources.get('lookup') and not resources.get('sequence'):continue
 graph=E.Element('Graph',{'name':row['test_id']+'_compile','id':row['test_id'],'nature':'etlGraph'})
 glob=E.SubElement(graph,'Global');params=E.SubElement(glob,'GraphParameters')
 E.SubElement(params,'GraphParameter',name='PROJECT',value='.')
 for name,value in resources.get('parameters',{}).items():E.SubElement(params,'GraphParameter',name=name,value=value)
 for i,x in enumerate(c.get('inputMetadata',[])): E.SubElement(glob,'Metadata',id='In'+str(i)).append(E.fromstring(x))
 for i,x in enumerate(c.get('outputMetadata',[])):E.SubElement(glob,'Metadata',id='Out'+str(i)).append(E.fromstring(x))
 if 'lookup' in resources:
  l=resources['lookup'];E.SubElement(glob,'Metadata',id='RuleMeta').append(E.fromstring(l['metadata']))
  E.SubElement(glob,'LookupTable',id=l['name'],name=l['name'],type='simpleLookup',metadata='RuleMeta',key=';'.join(l['key']),initialSize='16')
 if 'sequence' in resources:
  s=resources['sequence'];E.SubElement(glob,'Sequence',id=s['name'],name=s['name'],type='SIMPLE_SEQUENCE',start=str(s['start']),step=str(s['step']))
 phase=E.SubElement(graph,'Phase',number='0')
 for i,x in enumerate(c.get('inputMetadata',[])):
  node=E.SubElement(phase,'Node',id='Source'+str(i),type='DATA_GENERATOR',recordsNumber='0')
  E.SubElement(node,'attr',name='generate').text='//#CTL2\nfunction integer generate(){return OK;}'
 transform=E.SubElement(phase,'Node',id='UnderTest',type='REFORMAT')
 E.SubElement(transform,'attr',name='transform').text=row['reference']
 for i,x in enumerate(c.get('inputMetadata',[])):E.SubElement(phase,'Edge',id='Input'+str(i),fromNode='Source'+str(i)+':0',toNode='UnderTest:'+str(i),metadata='In'+str(i))
 for i,x in enumerate(c.get('outputMetadata',[])):
  E.SubElement(phase,'Node',id='Sink'+str(i),type='TRASH')
  E.SubElement(phase,'Edge',id='Output'+str(i),fromNode='UnderTest:'+str(i),toNode='Sink'+str(i)+':0',metadata='Out'+str(i))
 E.indent(graph);E.ElementTree(graph).write(G/(row['test_id']+'.grf'),encoding='utf-8',xml_declaration=True)
print('Created',len(list(G.glob('*.grf'))),'graph fixtures')
