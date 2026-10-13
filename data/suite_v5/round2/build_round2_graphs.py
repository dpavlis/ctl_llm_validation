"""Build all author shards and their main/boundary/expected-failure fixtures."""
import argparse,json
from pathlib import Path
from graph_harness import D,build
P=D/'round2'
def build_shards(shards):
 objects=[]
 for p in shards:objects+=json.loads(p.read_text())
 manifests=[];extra=[]
 for obj in objects:
  test,spec=obj['test'],obj['graph_spec'];manifests.append(build(test,spec))
  for key in ['failure_probes','dictionary_probes','boundary_probes']:
   for i,probe in enumerate(spec['fixture'].get(key,[])):
    variant=dict(probe);variant.setdefault('name',key+'_'+str(i));extra.append(build(test,spec,variant))
 (P/'main_manifests.json').write_text(json.dumps(manifests,indent=2)+'\n');(P/'extra_manifests.json').write_text(json.dumps(extra,indent=2)+'\n')
 print('Built',len(manifests),'main and',len(extra),'extra graphs')
 return objects,manifests
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('shards',nargs='*',type=Path);args=parser.parse_args();build_shards(args.shards or sorted(P.glob('shard_t*.json')))
