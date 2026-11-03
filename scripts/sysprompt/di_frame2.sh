#!/bin/bash -l
# v2 of the DataIntersection framing text (ALL/0/1 accepted as OK): harness DI + validate DI only.
# DataIntersection framing test (spec/sysprompt_rules_findings.md, owner idea 2026-11-01): the join-like paragraph
# data/sysprompt/di_frame_v2.txt in the system prompt of valprec2, on the DI subsets only:
#  (1) suite T53/T54 thinking on 3x n10 (baseline results/validate_precision/gaps_valprec2.json, n30),
#  (2) harness pool_tweak DI tasks (51), thinking on, 2 runs, 2 rounds, paired with valprec2_pool_tweak.jsonl (76/102),
#  (3) B1-tweak DI records (40: 12 controls), both modes, 2 runs, format prompt, paired with validate_gt_tweak_valprec2_fmt.
#   GPU=0 setsid nohup scripts/sysprompt/di_frame.sh > logs/sysprompt/di_frame.log 2>&1 &
cd ~/llama_train
GPU=${GPU:-0}; PORT=${PORT:-3012}; L=logs/sysprompt; FR=data/sysprompt/di_frame_v2.txt; PY=~/venv/bin/python
ts() { date '+%m-%d %H:%M'; }
sed -e "s/CUDA_VISIBLE_DEVICES=0/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" $L/vllm_3012.sh > $L/vllm_diframe2.sh
setsid nohup bash $L/vllm_diframe2.sh > $L/vllm_diframe2_$PORT.log 2>&1 < /dev/null &
SERVER=$!; PIDS=""
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "$(ts) no server"; tail -20 $L/vllm_diframe2_$PORT.log; exit 1; }; done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"valprec2\", \"lora_path\": \"$PWD/data/opcd/valprec2/round_155/adapter\"}"; echo
echo "$(ts) DI framing v2 test start (GPU $GPU :$PORT)"
PIDS=""
( $PY -u agent_harness.py run data/agent_harness/pool_tweak_di.jsonl --model valprec2 --url http://127.0.0.1:$PORT \
    --modes on --runs 2 --rounds 2 --concurrency 4 --system-extra $FR \
    --out results/agent_harness/valprec2_diframe2_pool_tweak_di.jsonl > $L/harness_di_frame2.log 2>&1
  echo "$(ts) harness DI done ($(grep -c . results/agent_harness/valprec2_diframe2_pool_tweak_di.jsonl) records)" ) &
PIDS="$PIDS $!"
PIDS="$PIDS $!"
( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak_di.jsonl --model valprec2 \
    --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 8 --system-extra $FR \
    --out results/agent_harness/validate_gt_tweak_valprec2diframe2_fmt.jsonl > $L/gen_tweak_diframe2.log 2>&1
  $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_valprec2diframe2_fmt \
    --records data/agent_harness/validate_mutants_tweak_di.jsonl --diff tweak_valprec2diframe2_fmt:tweak_valprec2_fmt \
    --out results/sysprompt/gt_tweak_di_valprec2_frame2.md > /dev/null
  echo "$(ts) validate DI done ($(grep -c . results/agent_harness/validate_gt_tweak_valprec2diframe2_fmt.jsonl) lines)" ) &
PIDS="$PIDS $!"
PIDS="$PIDS $!"
wait $PIDS
# stop only the server this script started (a port-wide kill took down another lane's server on 2026-11-03)
pkill -P $SERVER; kill $SERVER 2>/dev/null
echo "$(ts) DI framing v2 test done"
