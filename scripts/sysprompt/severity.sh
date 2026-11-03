#!/bin/bash -l
# Severity rule lane: deploy_v2 = deploy_v1 + data/sysprompt/severity_v1.txt (ERROR / WARNING / INFO ruling, findings §7) on valprec2.
#  (1) suite v4 validate tests (13), judge path, n5, both modes, deploy_v1 vs deploy_v2 (configs/eval_sp_v4val_valprec2_deploy{1,2}_{on,off}.yaml);
#  (2) validate ground truth B1-tweak, both modes, 2 runs, format prompt, deploy_v2, scored against deploy_v1 (tweak_valprec2deploy_fmt) and plain;
#  (3) harness pool_tweak, 165 tasks, thinking on, 2 runs, 2 rounds, deploy_v2, paired with valprec2_deploy_pool_tweak.jsonl (generate guard).
#   GPU=0 setsid nohup scripts/sysprompt/severity.sh > logs/sysprompt/severity.log 2>&1 &
cd /home/pavlisd/llama_train
GPU=${GPU:-0}; PORT=3012; L=logs/sysprompt; SP=data/sysprompt/deploy_v2.txt; PY=~/venv/bin/python; ts() { date '+%m-%d %H:%M'; }
export PATH=/home/pavlisd/venv/bin:$PATH
sed -e "s/CUDA_VISIBLE_DEVICES=0/CUDA_VISIBLE_DEVICES=$GPU/" $L/vllm_3012.sh > $L/vllm_severity.sh
setsid nohup bash $L/vllm_severity.sh > $L/vllm_severity_$PORT.log 2>&1 < /dev/null &
SERVER=$!; PIDS=""
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do sleep 10; kill -0 $SERVER 2>/dev/null || { echo "$(ts) no server"; tail -20 $L/vllm_severity_$PORT.log; exit 1; }; done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"valprec2\", \"lora_path\": \"$PWD/data/opcd/valprec2/round_155/adapter_vllm\"}"; echo
echo "$(ts) severity lane start (GPU $GPU :$PORT)"
( for v in 1 2; do for m in on off; do
    CUDA_VISIBLE_DEVICES="" $PY -u test.py configs/eval_sp_v4val_valprec2_deploy${v}_$m.yaml --validate-only --runs 5 --workers 16 > $L/v4val_deploy${v}_$m.log 2>&1
    echo "$(ts) v4 validate deploy$v $m done: $(grep -c 'Verdict:' $L/v4val_deploy${v}_$m.log) verdicts"; done; done ) &
PIDS="$PIDS $!"
( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak.jsonl --model valprec2 \
    --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 8 --system-extra $SP \
    --out results/agent_harness/validate_gt_tweak_valprec2deploy2_fmt.jsonl > $L/gen_tweak_deploy2.log 2>&1
  $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_valprec2deploy_fmt tweak_valprec2deploy2_fmt \
    --records data/agent_harness/validate_mutants_tweak.jsonl --diff tweak_valprec2deploy2_fmt:tweak_valprec2deploy_fmt tweak_valprec2deploy2_fmt:tweak_valprec2_fmt \
    --out results/sysprompt/gt_tweak_valprec2_deploy2.md > /dev/null
  echo "$(ts) validate done ($(grep -c . results/agent_harness/validate_gt_tweak_valprec2deploy2_fmt.jsonl) lines)" ) &
PIDS="$PIDS $!"
( $PY -u agent_harness.py run data/agent_harness/pool_tweak.jsonl --model valprec2 --url http://127.0.0.1:$PORT \
    --modes on --runs 2 --rounds 2 --concurrency 6 --system-extra $SP \
    --out results/agent_harness/valprec2_deploy2_pool_tweak.jsonl > $L/harness_deploy2.log 2>&1
  echo "$(ts) harness done ($(grep -c . results/agent_harness/valprec2_deploy2_pool_tweak.jsonl) records)" ) &
PIDS="$PIDS $!"
wait $PIDS
# stop only the server this script started
pkill -P $SERVER; kill $SERVER 2>/dev/null
echo "$(ts) severity lane done"
