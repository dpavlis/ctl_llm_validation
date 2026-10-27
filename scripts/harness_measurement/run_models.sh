#!/bin/bash -l
# Validate ground truth (spec/harness_measurement_brief.md Part B): serve each model on one GPU, sample answers for the
# planted-defect and corpus records in both thinking modes (gen_answers.py), stop the server. One call per GPU:
#   GPU=1 MODELS="c13c rb1011s2" setsid nohup scripts/harness_measurement/run_models.sh > logs/harness_measurement/run_g1.log 2>&1 &
#   GPU=3 MODELS="rb1011 rb1012" setsid nohup scripts/harness_measurement/run_models.sh > logs/harness_measurement/run_g3.log 2>&1 &
# c13c is the rb1009 export plus the OPCD adapter data/opcd/c13c/round_015, hot-loaded under the name c13c.
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/harness_measurement; RUNS=${RUNS:-2}
# FMT=1: the suite's validate output-format system prompt (gen_answers.py --format), results *_fmt.jsonl
FA=""; SUF=""; [ -n "$FMT" ] && { FA="--format"; SUF="_fmt"; }
REC="data/agent_harness/validate_mutants.jsonl data/agent_harness/validate_corpus.jsonl"
ts() { date '+%m-%d %H:%M'; }
for M in $MODELS; do
  case $M in
    c13c) EXP=qwen38_rb1009_sftdpo; NAME=rb1009; P=3031; AD="--load-adapter data/opcd/c13c/round_015/adapter_vllm" ;;
    rb1011) EXP=qwen38_rb1011_sftdpo; NAME=$M; P=3032; AD="" ;;
    rb1011s2) EXP=qwen38_rb1011s2_sftdpo; NAME=$M; P=3033; AD="" ;;
    rb1012) EXP=qwen38_rb1012_sftdpo; NAME=$M; P=3034; AD="" ;;
    *) echo "unknown model $M"; continue ;;
  esac
  sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $P/" \
      -e "s#--model /home/pavlisd/exports/qwen38_rb1006_sftdpo --served-model-name rb1006#--model /home/pavlisd/exports/$EXP --served-model-name $NAME#" \
      scripts/vllm_eval_serve.sh > $L/vllm_$M.sh
  grep -q "served-model-name $NAME" $L/vllm_$M.sh || { echo "$(ts) $M: serve script not rewritten"; continue; }
  n=0; until [ "$(nvidia-smi -i $GPU --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 1000 ]; do sleep 10; n=$((n+1))
    [ $n -gt 60 ] && { echo "$(ts) $M: GPU $GPU still busy"; break; }; done     # the previous server's memory
  echo "$(ts) $M: serving $EXP on GPU $GPU :$P"
  setsid nohup bash $L/vllm_$M.sh > $L/vllm_$M.log 2>&1 < /dev/null &
  n=0; until curl -sf 127.0.0.1:$P/v1/models | grep -q "\"$NAME\""; do sleep 10; n=$((n+1))
    [ $n -gt 90 ] && { echo "$(ts) $M: server did not come up"; break; }; done
  $PY -u scripts/harness_measurement/gen_answers.py $REC --model $M --url http://127.0.0.1:$P $AD --modes off on --runs $RUNS $FA \
      --out results/agent_harness/validate_gt_$M$SUF.jsonl > $L/gen_$M$SUF.log 2>&1
  echo "$(ts) $M$SUF: answers done ($(grep -c . results/agent_harness/validate_gt_$M$SUF.jsonl) lines)"
  S=$(ps -u pavlisd -o pid=,args= | awk -v t="served-model-name $NAME" '$2 ~ /python3$/ && /vllm.entrypoints.openai.api_server/ && index($0,t) {print $1}')
  [ -n "$S" ] && kill $S
  sleep 30
done
echo "$(ts) GPU $GPU done"
