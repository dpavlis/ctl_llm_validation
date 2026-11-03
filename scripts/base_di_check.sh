#!/bin/bash -l
# DataIntersection subsets for a base served as $TAG on :$PORT (no adapter, no system-extra): harness pool_tweak DI
# tasks (51 tasks, thinking on, 2 runs, 2 feedback rounds) and B1-tweak DI validate records (40, both modes, 2 runs,
# format prompt), scored against valprec2 (tweak_valprec2_fmt). Does not start or stop the server.
#   TAG=rb1013 PORT=3012 setsid nohup scripts/base_di_check.sh > logs/evals/di_check_rb1013.log 2>&1 &
cd ~/llama_train
TAG=${TAG:?}; PORT=${PORT:-3012}; L=logs/evals; PY=~/venv/bin/python; mkdir -p results/di_check
ts() { date '+%m-%d %H:%M'; }
curl -sf 127.0.0.1:$PORT/v1/models | grep -q "\"$TAG\"" || { echo "$(ts) no server $TAG on :$PORT"; exit 1; }
( $PY -u agent_harness.py run data/agent_harness/pool_tweak_di.jsonl --model $TAG --url http://127.0.0.1:$PORT \
    --modes on --runs 2 --rounds 2 --concurrency 4 --out results/agent_harness/${TAG}_pool_tweak_di.jsonl > $L/harness_di_$TAG.log 2>&1
  echo "$(ts) harness DI $TAG done ($(grep -c . results/agent_harness/${TAG}_pool_tweak_di.jsonl) records)" ) &
( $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak_di.jsonl --model $TAG \
    --url http://127.0.0.1:$PORT --modes off on --runs 2 --format --concurrency 8 \
    --out results/agent_harness/validate_gt_tweak_${TAG}_fmt.jsonl > $L/gen_tweak_di_$TAG.log 2>&1
  $PY scripts/harness_measurement/score_validate.py tweak_valprec2_fmt tweak_${TAG}_fmt \
    --records data/agent_harness/validate_mutants_tweak_di.jsonl --diff tweak_${TAG}_fmt:tweak_valprec2_fmt \
    --out results/di_check/gt_tweak_di_$TAG.md > /dev/null
  echo "$(ts) validate DI $TAG done" ) &
echo "$(ts) DI check $TAG start (:$PORT)"
wait
echo "$(ts) DI check $TAG done"
