#!/bin/bash -l
# Deployment prompt v1 = rules_v1 + DataIntersection join paragraph (data/sysprompt/deploy_v1.txt) on valprec2, thinking on:
#  (1) gap tests T57/T63/T67/T73 3 x n10 execution-scored (baselines results/validate_precision/gaps_valprec2.json, results/sysprompt/gaps_valprec2_rules.json),
#  (2) harness pool_tweak, all 165 tasks, on, 2 runs, 2 rounds, paired with results/agent_harness/valprec2_pool_tweak.jsonl,
#  (3) validate ground truth B1-tweak (196 records), both modes, 2 runs, format prompt, paired with tweak_valprec2_fmt.
#   GPU=0 setsid nohup scripts/sysprompt/deploy.sh > logs/sysprompt/deploy.log 2>&1 &
cd /home/pavlisd/llama_train
GPU=${GPU:-0}; PORT=3012; L=logs/sysprompt; SP=data/sysprompt/deploy_v1.txt; PY=~/venv/bin/python; ts() { date '+%m-%d %H:%M'; }
sed -e "s/CUDA_VISIBLE_DEVICES=0/CUDA_VISIBLE_DEVICES=$GPU/" $L/vllm_3012.sh > $L/vllm_deploy.sh
setsid nohup bash $L/vllm_deploy.sh > $L/vllm_deploy_$PORT.log 2>&1 < /dev/null &
SERVER=$!; PIDS=""
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do sleep 10; kill -0 $SERVER 2>/dev/null || { echo "$(ts) no server"; tail -20 $L/vllm_deploy_$PORT.log; exit 1; }; done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"valprec2\", \"lora_path\": \"$PWD/data/opcd/valprec2/round_155/adapter_vllm\"}"; echo
echo "$(ts) deploy prompt test start (GPU $GPU :$PORT)"
for i in a b c; do
  ( $PY test.py configs/eval_sp_v5gaps_valprec2_deploy_on.yaml --tests T57,T63,T67,T73 --runs 10 > $L/gaps_deploy_on_$i.log 2>&1
    echo "$(ts) gaps on $i done: $(grep -c 'Verdict:' $L/gaps_deploy_on_$i.log) verdicts" ) &
PIDS="$PIDS $!"
done
( $PY -u agent_harness.py run data/agent_harness/pool_tweak.jsonl --model valprec2 --url http://127.0.0.1:$PORT \
    --modes on --runs 2 --rounds 2 --concurrency 6 --system-extra $SP \
    --out results/agent_harness/valprec2_deploy_pool_tweak.jsonl > $L/harness_deploy.log 2>&1
  echo "$(ts) harness done ($(grep -c . results/agent_harness/valprec2_deploy_pool_tweak.jsonl) records)" ) &
PIDS="$PIDS $!"
( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak.jsonl --model valprec2 \
    --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 8 --system-extra $SP \
    --out results/agent_harness/validate_gt_tweak_valprec2deploy_fmt.jsonl > $L/gen_tweak_deploy.log 2>&1
  $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_valprec2deploy_fmt \
    --records data/agent_harness/validate_mutants_tweak.jsonl --diff tweak_valprec2deploy_fmt:tweak_valprec2_fmt \
    --out results/sysprompt/gt_tweak_valprec2_deploy.md > /dev/null
  echo "$(ts) validate done ($(grep -c . results/agent_harness/validate_gt_tweak_valprec2deploy_fmt.jsonl) lines)" ) &
PIDS="$PIDS $!"
wait $PIDS
$PY data/suite_v5/exec_score.py $(ls results/results_qwen38_sp_v5gaps_valprec2_deploy_on_*.json) --out results/sysprompt/gaps_valprec2_deploy.json > $L/exec_gaps_deploy.log 2>&1
echo "$(ts) exec scored"
# stop only the server this script started (a port-wide kill took down another lane's server on 2026-11-03)
pkill -P $SERVER; kill $SERVER 2>/dev/null
echo "$(ts) deploy prompt test done"
