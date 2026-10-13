"""Author the current round2 suite and graphs (compiler/run evidence required afterward).

Network-free authoring only. Historical round1 builder is in round1/.
"""
import subprocess,sys
from pathlib import Path
D=Path(__file__).resolve().parent;P=D/'round2'
for name in ['author_t44_t53.py','author_t54_t63.py','author_t64_t73.py','build_round2_graphs.py']:
 subprocess.run([sys.executable,str(P/name)],check=True)
print('Authored30 scenarios and graph fixtures. Execute main/extra manifests, capture ctl_validate results, then round2/finalize_suite.py.')
