#!/bin/bash -l
# Merge the valprec2 OPCD adapter (round 155) into the rb1009 SFT+DPO export: the deployable model, no LoRA needed.
cd /home/pavlisd/llama_train
export CUDA_VISIBLE_DEVICES=${GPU:-0}
OUT=${OUT:-/home/pavlisd/exports/qwen38_ctl2_deploy_valprec2}
echo "$(date '+%m-%d %H:%M') export start -> $OUT (GPU $CUDA_VISIBLE_DEVICES)"
~/venv/bin/python opcd.py export --config configs/opcd_valprec2.yaml --round 155 --out "$OUT" || { echo "export FAILED"; exit 1; }
cp /home/pavlisd/exports/qwen38_rb1009_sftdpo/processor_config.json "$OUT/" 2>/dev/null
echo "$(date '+%m-%d %H:%M') export done"; du -sh "$OUT"

# vLLM rejects the text-only Qwen3_5TextConfig that AutoModelForCausalLM writes: restore the base config and the
# untouched vision tensors so the export is a drop-in replacement for the rb1009 folder.
~/venv/bin/python - "$OUT" <<'PY'
import json,shutil,sys
from safetensors import safe_open
from safetensors.torch import save_file
B='/home/pavlisd/exports/qwen38_rb1009_sftdpo'; M=sys.argv[1]
ib=json.load(open(f'{B}/model.safetensors.index.json')); im=json.load(open(f'{M}/model.safetensors.index.json'))
miss=[n for n in ib['weight_map'] if n not in im['weight_map']]
if miss:
    assert all(n.startswith('model.visual.') for n in miss), miss[:3]
    opened={}; tens={}
    for n in miss:
        f=ib['weight_map'][n]; opened.setdefault(f,safe_open(f'{B}/{f}','pt')); tens[n]=opened[f].get_tensor(n).contiguous()
    save_file(tens,f'{M}/model-visual.safetensors',metadata={'format':'pt'})
    for n in miss: im['weight_map'][n]='model-visual.safetensors'
    im['metadata']['total_size']=im['metadata'].get('total_size',0)+sum(t.numel()*t.element_size() for t in tens.values())
    json.dump(im,open(f'{M}/model.safetensors.index.json','w'),indent=2)
shutil.copy2(f'{B}/config.json',f'{M}/config.json')
print('restored',len(miss),'vision tensors and the base config')
PY
