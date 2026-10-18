#!/bin/bash -l
# Gates for a new base export without OPCD (as scripts/rb1009_eval.sh, parameterised): the base served as TAG on :3011
# (GPU 3, thinking OFF) and :3012 (GPU 1, thinking ON). Suite v4 full n5 both modes, thinking-off validate x9, T40/T42 n20,
# suite v5 gap tests incl. T53/T54 n10 both modes, hard-case sets 1-3 k4. Stops both servers at the end.
#   setsid nohup scripts/base_eval.sh /home/pavlisd/exports/qwen38_rb1010a_sftdpo rb1010a > logs/evals/rb1010a_eval.log 2>&1 &
set -uo pipefail
# one gate run at a time, on free GPUs (rebuilds may still be training on GPU 1 or 3)
exec 9>/home/pavlisd/llama_train/logs/evals/locks/base_eval.lock; flock 9
until [ "$(nvidia-smi -i 1 --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 1000 ] && \
      [ "$(nvidia-smi -i 3 --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 1000 ]; do sleep 60; done
cd /home/pavlisd/llama_train
BASE=$1; TAG=$2; PY=~/venv/bin/python; L=logs/evals
export PATH=/home/pavlisd/venv/bin:$PATH
for m in on off; do for s in vllm v5gaps; do
  sed -e "s/rb1009/$TAG/g" -e "s#model_path: /home/pavlisd/exports/qwen38_${TAG}_sftdpo#model_path: $BASE#" \
      configs/eval_rb1009_${s}_$m.yaml > configs/eval_${TAG}_${s}_$m.yaml; done; done
for p in 3011 3012; do
  src=logs/evals/opcd_vllm_serve.sh; [ $p = 3012 ] && src=scripts/vllm_eval_serve.sh
  sed -e "s#--model /home/pavlisd/exports/qwen38_rb1006_sftdpo --served-model-name rb1006#--model $BASE --served-model-name $TAG#" \
      -e 's/ --lora-modules smoke=[^ ]*//' $src > $L/vllm_${p}_$TAG.sh
  grep -q "served-model-name $TAG" $L/vllm_${p}_$TAG.sh || { echo "serve script for $p not rewritten"; exit 1; }
  setsid nohup bash $L/vllm_${p}_$TAG.sh > $L/vllm_${p}_$TAG.log 2>&1 < /dev/null & disown
done
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models | grep -q "\"$TAG\""; do sleep 10; done; done
echo "$(date '+%m-%d %H:%M') $TAG servers up"
GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
( t ${TAG}_v5gaps_on configs/eval_${TAG}_v5gaps_on.yaml --tests $GAPS --runs 10
  t ${TAG}_t40t42_n20 configs/eval_${TAG}_vllm_on.yaml --tests T40,T42 --runs 20
  t ${TAG}_t41_n20 configs/eval_${TAG}_vllm_on.yaml --tests T41 --runs 20
  t ${TAG}_on_full_n5 configs/eval_${TAG}_vllm_on.yaml --runs 5 ) &
( t ${TAG}_v5gaps_off configs/eval_${TAG}_v5gaps_off.yaml --tests $GAPS --runs 10
  t ${TAG}_off_full_n5 configs/eval_${TAG}_vllm_off.yaml --runs 5
  for r in 2 3 4 5 6 7 8 9; do t ${TAG}_off_validate_rep$r configs/eval_${TAG}_vllm_off.yaml --validate-only --runs 5; done
  sed "s/served_model: rb1009/served_model: $TAG/" configs/opcd_c13.yaml > configs/opcd_hardeval_$TAG.yaml
  for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
    CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${TAG}_set$s --file $f $TAG=$TAG:student --k 4 --config configs/opcd_hardeval_$TAG.yaml > $L/hard_eval_${TAG}_set$s.log 2>&1; done
  echo "$(date '+%m-%d %H:%M') hard-case evals done" ) &
wait
P=$(ps -u pavlisd -o pid=,args= | awk -v t="served-model-name $TAG" '$2 ~ /python3$/ && /vllm.entrypoints.openai.api_server/ && index($0,t) {print $1}')
[ -n "$P" ] && kill $P
echo "$(date '+%m-%d %H:%M') $TAG evals done"
