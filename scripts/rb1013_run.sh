#!/bin/bash -l
# rb1013: build the data set (rb1011 recipe on the current corpus, DI rounds 3+4), register it, SFT + DPO + export on one GPU.
#   GPU=1 setsid nohup scripts/rb1013_run.sh > logs/rb1013_run.log 2>&1 &
cd /home/pavlisd/llama_train
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
GPU=${GPU:-1}; TAG=rb1013; D=data/sft_rebuild_20261102_$TAG; PY=~/venv/bin/python; ts() { date '+%m-%d %H:%M'; }
used=$(nvidia-smi -i $GPU --query-gpu=memory.used --format=csv,noheader,nounits); [ "$used" -lt 1000 ] || { echo "GPU $GPU in use ($used MiB)"; exit 1; }
EXCL="CTL_LoRA_fix_defaults_explained.json CTL_LoRA_declaration_defaults_contrast.json CTL_LoRA_rollup_lifecycle_validate_sft.json CTL_LoRA_DPO_rollup_lifecycle_validate.jsonl CTL_LoRA_syntax_pitfalls_sft.json CTL_LoRA_DPO_syntax_pitfalls.jsonl CTL_LoRA_zerodate_sft.json CTL_LoRA_DPO_zerodate.jsonl"
echo "$(ts) $TAG build"
PYTHONPATH=~/LlamaFactory/src $PY data/build_sft_rebuild.py $TAG $D $EXCL --sd=c13c_belief:1 > logs/${TAG}_build.log 2>&1 || { echo "$(ts) build failed"; tail -5 logs/${TAG}_build.log; exit 1; }
tail -1 logs/${TAG}_build.log
cp $D/CTL_LoRA_training_data_$TAG.json $D/CTL_LoRA_eval_data_$TAG.json $D/CTL_LoRA_DPO_data_$TAG.jsonl $D/CTL_LoRA_DPO_eval_$TAG.jsonl ~/LlamaFactory/data/
$PY - <<'PY'
import json
p='/home/pavlisd/LlamaFactory/data/dataset_info.json'; d=json.load(open(p))
for k in ['clover_ctl_training','clover_ctl_eval','clover_dpo','clover_dpo_eval']:
    e=json.loads(json.dumps(d[k+'_rb1012'])); e['file_name']=e['file_name'].replace('rb1012','rb1013'); d[k+'_rb1013']=e
json.dump(d,open(p,'w'),indent=2,ensure_ascii=False); print('registered rb1013 datasets')
PY
cd ~/LlamaFactory && echo "$(ts) $TAG train (GPU $GPU)" && \
flock /home/pavlisd/llama_train/logs/evals/locks/gpu$GPU.lock env CUDA_VISIBLE_DEVICES=$GPU $PY ~/llama_train/train.py \
  ~/llama_train/configs/qwen38_$TAG.yaml --skip-post-sft > ~/llama_train/logs/${TAG}_train.log 2>&1 \
  && echo "$(ts) $TAG trained" || { echo "$(ts) $TAG TRAIN FAILED"; exit 1; }
[ -f /home/pavlisd/exports/qwen38_${TAG}_sftdpo/config.json ] && echo "$(ts) export ok" || echo "$(ts) NO EXPORT"
