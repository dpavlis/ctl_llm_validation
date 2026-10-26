#!/bin/bash -l
# rb1012 DPO isolation (spec/rb1012_dpo_isolation_brief.md): for each arm, the DPO phase alone on rb1011's SFT adapter
# (configs/qwen38_rb1011_dpoiso_<arm>.yaml, data from data/build_dpoiso.py), export, then serve it on the same GPU (port
# 302N, N = arm's position A=1 .. D=4) and measure:
#   thinking off: validate-only n5 x9 (T22 n45 inside), hard set 3 k4;  thinking on: T41 n25, T40/T42 n20.
# One worker per free GPU takes arms from a shared queue, so a GPU that frees later can join with a second start:
#   GPUS="0 2" ARMS="A B C" setsid nohup scripts/dpoiso_run.sh > logs/dpoiso_run.log 2>&1 &
#   GPUS="1" ARMS="" setsid nohup scripts/dpoiso_run.sh > logs/dpoiso_run_g1.log 2>&1 &    # joins the existing queue
cd /home/pavlisd/llama_train
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
PY=~/venv/bin/python; L=logs/evals; K=$L/locks; Q=logs/dpoiso_queue; mkdir -p $K
SFT=/home/pavlisd/LlamaFactory/saves/qwen38-27B-rb1011/2026-10-18-21-50-38_sft/checkpoint-2240
ts() { date '+%m-%d %H:%M'; }
[ -n "${ARMS-A B C}" ] && echo ${ARMS-A B C} | tr ' ' '\n' >> $Q
pop() { ( flock 9; a=$(head -n 1 $Q); [ -n "$a" ] && sed -i 1d $Q; echo $a ) 9>$Q.lock; }

arm() {   # $1 arm, $2 GPU
  local a=$1 g=$2 T=rb1011_dpoiso_$1 P=302$(( $(printf '%d' "'$1") - 64 ))
  local E=/home/pavlisd/exports/qwen38_${T}_sftdpo
  echo "$(ts) $a: train on GPU $g"
  ( cd ~/LlamaFactory && CUDA_VISIBLE_DEVICES=$g $PY ~/llama_train/train.py ~/llama_train/configs/qwen38_rb1011_dpoiso_$a.yaml \
      --sft-adapter $SFT --skip-post-sft ) > logs/dpoiso_${a}_train.log 2>&1
  [ -f $E/config.json ] || { echo "$(ts) $a: TRAIN/EXPORT FAILED (logs/dpoiso_${a}_train.log)"; return; }
  echo "$(ts) $a: exported, serving on GPU $g :$P"
  sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$g/" -e "s/--port 3012/--port $P/" \
      -e "s#--model /home/pavlisd/exports/qwen38_rb1006_sftdpo --served-model-name rb1006#--model $E --served-model-name $T#" \
      -e 's/ --enable-lora --max-lora-rank 32 --max-loras 4//' scripts/vllm_eval_serve.sh > $L/vllm_$T.sh
  grep -q "served-model-name $T" $L/vllm_$T.sh || { echo "$(ts) $a: serve script not rewritten"; return; }
  setsid nohup bash $L/vllm_$T.sh > $L/vllm_$T.log 2>&1 < /dev/null &
  local n=0; until curl -sf 127.0.0.1:$P/v1/models | grep -q "\"$T\""; do sleep 10; n=$((n+1))
    [ $n -gt 90 ] && { echo "$(ts) $a: server did not come up ($L/vllm_$T.log)"; return; }; done
  t() { log=$1; shift; CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(ts) $a: $log done"; }
  ( t ${T}_t41_n25 configs/eval_${T}_vllm_on.yaml --tests T41 --runs 25
    t ${T}_t40t42_n20 configs/eval_${T}_vllm_on.yaml --tests T40,T42 --runs 20 ) & local e1=$!
  ( for r in 1 2 3 4 5 6 7 8 9; do t ${T}_off_validate_rep$r configs/eval_${T}_vllm_off.yaml --validate-only --runs 5; done
    CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${T}_set3 --file hard_cases3.jsonl $T=$T:student --k 4 \
      --config configs/opcd_hardeval_$T.yaml > $L/hard_eval_${T}_set3.log 2>&1; echo "$(ts) $a: hard set 3 done" ) & local e2=$!
  wait $e1 $e2   # a bare wait would also wait for the vLLM server started above
  local S=$(ps -u pavlisd -o pid=,args= | awk -v t="served-model-name $T" '$2 ~ /python3$/ && /vllm.entrypoints.openai.api_server/ && index($0,t) {print $1}')
  [ -n "$S" ] && kill $S
  echo "$(ts) $a: evals done, server stopped"
}

worker() {   # $1 GPU
  exec 8>$K/gpu$1.lock; flock 8
  while a=$(pop); [ -n "$a" ]; do
    used=$(nvidia-smi -i $1 --query-gpu=memory.used --format=csv,noheader,nounits)
    [ "$used" -lt 1000 ] || { echo "$(ts) GPU $1 is in use ($used MiB); putting $a back"; ( flock 9; { echo $a; cat $Q; } > $Q.tmp && mv $Q.tmp $Q ) 9>$Q.lock; return; }
    arm $a $1
    sleep 30   # let the server's memory free before the next arm
  done
}
for g in ${GPUS:-0 2}; do worker $g & done
wait
echo "$(ts) dpoiso workers on GPUs ${GPUS:-0 2} done"
