#!/bin/bash -l
# B1-tweak answers (findings §4.8): serve each model on $GPU, sample both thinking modes on
# data/agent_harness/validate_mutants_tweak.jsonl with the suite's output-format prompt (gen_answers.py --format),
# stop the server, score. Waits for the mutant file if make_mutants_tweak.sh is still running.
#   GPU=1 MODELS="c13c" setsid nohup scripts/harness_measurement/run_tweak_gt.sh > logs/harness_measurement/run_tweak_gt_g1.log 2>&1 &
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/harness_measurement; RUNS=${RUNS:-2}; MODELS=${MODELS:-c13c}
REC=data/agent_harness/validate_mutants_tweak.jsonl
ts() { date '+%m-%d %H:%M'; }
until [ -s $REC ] && ! pgrep -u $USER -f 'make_mutants.py --pool data/agent_harness/pool_tweak' >/dev/null; do sleep 30; done
echo "$(ts) records: $(grep -c . $REC)"
for M in $MODELS; do
  case $M in
    c13c) EXP=qwen38_rb1009_sftdpo; NAME=rb1009_tw; P=3041; AD="--load-adapter data/opcd/c13c/round_015/adapter_vllm" ;;
    rb1011) EXP=qwen38_rb1011_sftdpo; NAME=$M; P=3042; AD="" ;;
    rb1011s2) EXP=qwen38_rb1011s2_sftdpo; NAME=$M; P=3043; AD="" ;;
    rb1012) EXP=qwen38_rb1012_sftdpo; NAME=$M; P=3044; AD="" ;;
    *) echo "unknown model $M"; continue ;;
  esac
  sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $P/" \
      -e "s#--model /home/pavlisd/exports/qwen38_rb1006_sftdpo --served-model-name rb1006#--model /home/pavlisd/exports/$EXP --served-model-name $NAME#" \
      scripts/vllm_eval_serve.sh > $L/vllm_tw_$M.sh
  grep -q "served-model-name $NAME" $L/vllm_tw_$M.sh || { echo "$(ts) $M: serve script not rewritten"; continue; }
  n=0; until [ "$(nvidia-smi -i $GPU --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 1000 ]; do sleep 10; n=$((n+1))
    [ $n -gt 60 ] && { echo "$(ts) $M: GPU $GPU still busy"; break; }; done
  echo "$(ts) $M: serving $EXP on GPU $GPU :$P"
  setsid nohup bash $L/vllm_tw_$M.sh > $L/vllm_tw_$M.log 2>&1 < /dev/null &
  n=0; until curl -sf 127.0.0.1:$P/v1/models | grep -q "\"$NAME\""; do sleep 10; n=$((n+1))
    [ $n -gt 90 ] && { echo "$(ts) $M: server did not come up"; break; }; done
  $PY -u scripts/harness_measurement/gen_answers.py $REC --model $M --url http://127.0.0.1:$P $AD --modes off on --runs $RUNS --format \
      --out results/agent_harness/validate_gt_tweak_${M}_fmt.jsonl > $L/gen_tweak_${M}_fmt.log 2>&1
  echo "$(ts) $M: answers done ($(grep -c . results/agent_harness/validate_gt_tweak_${M}_fmt.jsonl) lines)"
  S=$(ps -u $USER -o pid=,args= | awk -v t="served-model-name $NAME" '/vllm.entrypoints.openai.api_server/ && index($0,t) {print $1}')
  [ -n "$S" ] && kill $S
  sleep 30
done
$PY scripts/harness_measurement/score_validate.py $(for M in $MODELS; do echo -n "tweak_${M}_fmt "; done) --records $REC --diff \
    --out results/agent_harness/validate_gt_tweak_table_fmt.md > /dev/null && echo "$(ts) scored"
echo "$(ts) GPU $GPU done"
