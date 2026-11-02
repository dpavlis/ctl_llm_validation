#!/bin/bash -l
# difr2: sampler (rb1009_vp, GPU $SG :3013) + opcd prepare/train on GPU $TG. Gates run separately once a round is chosen.
#   setsid nohup scripts/opcd_difr2_run.sh > logs/evals/opcd_difr2_run.log 2>&1 &
cd ~/llama_train
TG=${TRAIN_GPU:-0}; SG=${SAMPLE_GPU:-1}; PY=~/venv/bin/python; L=logs/evals
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
GPU=$SG PORT=3013 setsid nohup scripts/validate_precision/vllm_sampler_3011.sh > $L/vllm_sampler_difr2.log 2>&1 < /dev/null &
until curl -sf 127.0.0.1:3013/v1/models | grep -q rb1009_vp; do sleep 10; done
echo "$(date '+%m-%d %H:%M') difr2 sampler up (GPU $SG :3013)"
$PY -u opcd.py prepare --config configs/opcd_difr2.yaml > $L/opcd_difr2_prepare.log 2>&1 || { echo "prepare failed"; tail -30 $L/opcd_difr2_prepare.log; exit 1; }
echo "$(date '+%m-%d %H:%M') difr2 prepared: $(grep -c . data/opcd/difr2/prompts.jsonl) prompt rows"
CUDA_VISIBLE_DEVICES=$TG $PY -u opcd.py train --config configs/opcd_difr2.yaml > $L/opcd_difr2_train.log 2>&1 || { echo "train failed"; tail -30 $L/opcd_difr2_train.log; }
echo "$(date '+%m-%d %H:%M') difr2 train done"
for p in $(ps -eo pid,user,args | awk -v u=$USER '$2==u && /--port 3013/ && /vllm.entrypoints/ {print $1}'); do kill $p; done
