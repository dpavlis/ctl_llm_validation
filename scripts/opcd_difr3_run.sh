#!/bin/bash -l
# difr3: sampler (rb1009_vp, GPU $SG :3013) + the drifted student adapter (difr2 r39) for the pair build, build_pairs, opcd prepare/train on GPU $TG.
#   setsid nohup scripts/opcd_difr3_run.sh > logs/evals/opcd_difr3_run.log 2>&1 &
cd ~/llama_train
TG=${TRAIN_GPU:-0}; SG=${SAMPLE_GPU:-1}; PY=~/venv/bin/python; L=logs/evals; CFG=configs/opcd_difr3.yaml
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
ts() { date '+%m-%d %H:%M'; }
STUDENT=${STUDENT:-difr2_r39}; SPATH=${SPATH:-$PWD/data/opcd/difr2/round_039/adapter_vllm}
curl -sf 127.0.0.1:3013/v1/models | grep -q rb1009_vp || GPU=$SG PORT=3013 setsid nohup scripts/validate_precision/vllm_sampler_3011.sh > $L/vllm_sampler_difr3.log 2>&1 < /dev/null &
until curl -sf 127.0.0.1:3013/v1/models | grep -q rb1009_vp; do sleep 10; done
echo "$(ts) difr3 sampler up (GPU $SG :3013)"
curl -s -X POST 127.0.0.1:3013/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"$STUDENT\", \"lora_path\": \"$SPATH\"}"; echo
CUDA_VISIBLE_DEVICES="" $PY -u scripts/difr3/build_pairs.py $CFG --url http://127.0.0.1:3013 --student $STUDENT --teacher rb1009_vp \
  --modes on --k-student 8 --k-teacher 4 \
  --out data/opcd/difr3_pairs.jsonl > $L/difr3_build_pairs.log 2>&1 || { echo "build_pairs failed"; tail -20 $L/difr3_build_pairs.log; exit 1; }
N=$(grep -c . data/opcd/difr3_pairs.jsonl); W=$(( (960 + N/2) / (N>0?N:1) )); [ $W -lt 1 ] && W=1; [ $W -gt 16 ] && W=16
sed -i "s#{file: data/opcd/difr3_pairs.jsonl, weight: [0-9]*}#{file: data/opcd/difr3_pairs.jsonl, weight: $W}#" $CFG
echo "$(ts) difr3 pairs: $N, weight $W ($(tail -1 $L/difr3_build_pairs.log | cut -c1-80))"
[ $N -lt 40 ] && { echo "too few pairs"; exit 1; }
$PY -u opcd.py prepare --config $CFG > $L/opcd_difr3_prepare.log 2>&1 || { echo "prepare failed"; tail -30 $L/opcd_difr3_prepare.log; exit 1; }
echo "$(ts) difr3 prepared: $(grep -c . data/opcd/difr3/prompts.jsonl) prompt rows; $(grep exec_fixed $L/opcd_difr3_prepare.log)"
CUDA_VISIBLE_DEVICES=$TG $PY -u opcd.py train --config $CFG > $L/opcd_difr3_train.log 2>&1 || { echo "train failed"; tail -30 $L/opcd_difr3_train.log; }
echo "$(ts) difr3 train done"
for p in $(ps -eo pid,user,args | awk -v u=$USER '$2==u && index($0,"--port 3013") && /vllm.entrypoints/ {print $1}'); do kill $p; done
