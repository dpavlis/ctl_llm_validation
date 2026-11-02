#!/bin/bash -l
# $RUN (default difr1) round pick: DataIntersection subsets only, no system-extra, for rounds $ROUNDS (default 19 39) hot-loaded on rb1009 (:3012, GPU $GPU).
#  (1) harness pool_tweak DI tasks (51), thinking on, 2 runs, 2 rounds, paired with valprec2_pool_tweak.jsonl (76/102 first, 89/102 final);
#  (2) B1-tweak DI records (40: 12 controls), both modes, 2 runs, format prompt, paired with validate_gt_tweak_valprec2_fmt (FA on 0.08).
#   GPU=0 setsid nohup scripts/difr1_di_check.sh > logs/difr1/di_check.log 2>&1 &
cd ~/llama_train
RUN=${RUN:-difr1}; GPU=${GPU:-0}; PORT=${PORT:-3012}; ROUNDS=${ROUNDS:-19 39}; L=logs/$RUN; PY=~/venv/bin/python; mkdir -p $L results/$RUN
ts() { date '+%m-%d %H:%M'; }
sed -e "s/CUDA_VISIBLE_DEVICES=0/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" logs/sysprompt/vllm_3012.sh > $L/vllm_$PORT.sh
setsid nohup bash $L/vllm_$PORT.sh > $L/vllm_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "$(ts) no server"; tail -20 $L/vllm_$PORT.log; exit 1; }; done
PIDS=""
for R in $ROUNDS; do AD=${RUN}_r$R
  curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$AD\", \"lora_path\": \"$PWD/data/opcd/$RUN/round_0$R/adapter_vllm\"}"; echo
  ( $PY -u agent_harness.py run data/agent_harness/pool_tweak_di.jsonl --model $AD --url http://127.0.0.1:$PORT \
      --modes on --runs 2 --rounds 2 --concurrency 4 --out results/agent_harness/${AD}_pool_tweak_di.jsonl > $L/harness_di_$AD.log 2>&1
    echo "$(ts) harness DI $AD done ($(grep -c . results/agent_harness/${AD}_pool_tweak_di.jsonl) records)" ) &
  PIDS="$PIDS $!"
  ( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak_di.jsonl --model $AD \
      --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 8 \
      --out results/agent_harness/validate_gt_tweak_${AD}_fmt.jsonl > $L/gen_tweak_$AD.log 2>&1
    $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_${AD}_fmt \
      --records data/agent_harness/validate_mutants_tweak_di.jsonl --diff tweak_${AD}_fmt:tweak_valprec2_fmt \
      --out results/$RUN/gt_tweak_di_$AD.md > /dev/null
    echo "$(ts) validate DI $AD done" ) &
  PIDS="$PIDS $!"
done
echo "$(ts) $RUN DI check start (GPU $GPU :$PORT, rounds $ROUNDS)"
wait $PIDS
echo "$(ts) $RUN DI check done (server :$PORT left running)"
