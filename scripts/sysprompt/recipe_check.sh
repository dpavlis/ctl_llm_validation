#!/bin/bash -l
# Deployment recipe check (spec/sysprompt_rules_findings.md, next step): valprec2 + data/sysprompt/rules_v1.txt in the
# system prompt, measured (1) on the fresh-domain pool_tweak harness, thinking on, 2 runs, 2 feedback rounds (paired with
# results/agent_harness/valprec2_pool_tweak.jsonl) and (2) on the B1-tweak validate ground truth, both modes, 2 runs,
# format prompt (paired with validate_gt_tweak_valprec2_fmt.jsonl). Serves rb1009 on GPU $GPU :$PORT, adapter valprec2.
#   GPU=0 setsid nohup scripts/sysprompt/recipe_check.sh > logs/sysprompt/recipe_check.log 2>&1 &
cd ~/llama_train
GPU=${GPU:-0}; PORT=${PORT:-3012}; L=logs/sysprompt; RULES=data/sysprompt/rules_v1.txt; PY=~/venv/bin/python
ts() { date '+%m-%d %H:%M'; }
sed -e "s/CUDA_VISIBLE_DEVICES=0/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" $L/vllm_3012.sh > $L/vllm_recipe.sh
setsid nohup bash $L/vllm_recipe.sh > $L/vllm_recipe_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "$(ts) no server"; tail -20 $L/vllm_recipe_$PORT.log; exit 1; }; done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"valprec2\", \"lora_path\": \"$PWD/data/opcd/valprec2/round_155/adapter\"}"; echo
echo "$(ts) recipe check start (GPU $GPU :$PORT)"
( $PY -u agent_harness.py run data/agent_harness/pool_tweak.jsonl --model valprec2 --url http://127.0.0.1:$PORT \
    --modes on --runs 2 --rounds 2 --concurrency 4 --system-extra $RULES \
    --out results/agent_harness/valprec2_rules_pool_tweak.jsonl > $L/harness_tweak_rules.log 2>&1
  $PY agent_harness.py summary results/agent_harness/valprec2_rules_pool_tweak.jsonl --by component \
    > results/agent_harness/valprec2_rules_pool_tweak.summary.md
  echo "$(ts) harness pool_tweak done ($(grep -c . results/agent_harness/valprec2_rules_pool_tweak.jsonl) records)" ) &
H=$!
( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak.jsonl --model valprec2 \
    --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 12 --system-extra $RULES \
    --out results/agent_harness/validate_gt_tweak_valprec2rules_fmt.jsonl > $L/gen_tweak_rules.log 2>&1
  $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_valprec2rules_fmt \
    --records data/agent_harness/validate_mutants_tweak.jsonl --diff tweak_valprec2rules_fmt:tweak_valprec2_fmt \
    --out results/sysprompt/gt_tweak_valprec2_rules.md > /dev/null
  echo "$(ts) validate gt tweak done ($(grep -c . results/agent_harness/validate_gt_tweak_valprec2rules_fmt.jsonl) lines)" ) &
V=$!
wait $H $V   # not a bare wait: the server subshell is a child too and never exits on its own
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
echo "$(ts) recipe check done"
