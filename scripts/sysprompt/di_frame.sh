#!/bin/bash -l
# DataIntersection framing test (spec/sysprompt_rules_findings.md, owner idea 2026-11-01): the join-like paragraph
# data/sysprompt/di_frame_v1.txt in the system prompt of valprec2, on the DI subsets only:
#  (1) suite T53/T54 thinking on 3x n10 (baseline results/validate_precision/gaps_valprec2.json, n30),
#  (2) harness pool_tweak DI tasks (51), thinking on, 2 runs, 2 rounds, paired with valprec2_pool_tweak.jsonl (76/102),
#  (3) B1-tweak DI records (40: 12 controls), both modes, 2 runs, format prompt, paired with validate_gt_tweak_valprec2_fmt.
#   GPU=0 setsid nohup scripts/sysprompt/di_frame.sh > logs/sysprompt/di_frame.log 2>&1 &
cd ~/llama_train
GPU=${GPU:-0}; PORT=${PORT:-3012}; L=logs/sysprompt; FR=data/sysprompt/di_frame_v1.txt; PY=~/venv/bin/python
ts() { date '+%m-%d %H:%M'; }
sed -e "s/CUDA_VISIBLE_DEVICES=0/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" $L/vllm_3012.sh > $L/vllm_diframe.sh
setsid nohup bash $L/vllm_diframe.sh > $L/vllm_diframe_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "$(ts) no server"; tail -20 $L/vllm_diframe_$PORT.log; exit 1; }; done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"valprec2\", \"lora_path\": \"$PWD/data/opcd/valprec2/round_155/adapter\"}"; echo
echo "$(ts) DI framing test start (GPU $GPU :$PORT)"
PIDS=""
for x in a b c; do
  ( $PY test.py configs/eval_sp_di_valprec2_frame_on.yaml --tests T53,T54 --runs 10 > $L/di_frame_on_$x.log 2>&1
    echo "$(ts) suite on $x done: $(grep -c 'Verdict:' $L/di_frame_on_$x.log) verdicts" ) &
  PIDS="$PIDS $!"
done
( $PY -u agent_harness.py run data/agent_harness/pool_tweak_di.jsonl --model valprec2 --url http://127.0.0.1:$PORT \
    --modes on --runs 2 --rounds 2 --concurrency 4 --system-extra $FR \
    --out results/agent_harness/valprec2_diframe_pool_tweak_di.jsonl > $L/harness_di_frame.log 2>&1
  echo "$(ts) harness DI done ($(grep -c . results/agent_harness/valprec2_diframe_pool_tweak_di.jsonl) records)" ) &
PIDS="$PIDS $!"
( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak_di.jsonl --model valprec2 \
    --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 8 --system-extra $FR \
    --out results/agent_harness/validate_gt_tweak_valprec2diframe_fmt.jsonl > $L/gen_tweak_diframe.log 2>&1
  $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_valprec2diframe_fmt \
    --records data/agent_harness/validate_mutants_tweak_di.jsonl --diff tweak_valprec2diframe_fmt:tweak_valprec2_fmt \
    --out results/sysprompt/gt_tweak_di_valprec2_frame.md > /dev/null
  echo "$(ts) validate DI done ($(grep -c . results/agent_harness/validate_gt_tweak_valprec2diframe_fmt.jsonl) lines)" ) &
PIDS="$PIDS $!"
wait $PIDS
$PY data/suite_v5/exec_score.py $(ls results/results_qwen38_sp_di_valprec2_frame_on_*.json) --out results/sysprompt/gaps_di_valprec2_frame.json > $L/exec_di_frame.log 2>&1 && echo "$(ts) exec scored"
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
echo "$(ts) DI framing test done"
