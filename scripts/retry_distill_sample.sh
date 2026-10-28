#!/bin/bash -l
# Retry-distill sampling phase (spec/retry_distill_brief.md, Data step 1): c13c on data/agent_harness/pool_retry.jsonl
# (the exec-RFT pool minus pool 1's 97 tasks and the 40-prompt holdout: 160 corpus generate/fix prompts with
# server-verified fixtures), both thinking modes, k = 4 runs, 2 feedback rounds with --rows-feedback. The triples
# (attempt 0 failed, a later attempt passed) are read from the attempts of results/agent_harness/c13c_pool_retry_rows.jsonl.
# Serves rb1009 + the c13c adapter on GPU $GPU, port $PORT, name rb1009_rd (not "rb1009": Part B's cleanup kills that name).
#   GPU=3 setsid nohup scripts/retry_distill_sample.sh > logs/evals/retry_distill_sample.log 2>&1 &
cd ~/llama_train
GPU=${GPU:-3}; PORT=${PORT:-3015}
sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" -e "s/--served-model-name rb1009 /--served-model-name rb1009_rd /" scripts/vllm_eval_serve_rb1009.sh \
  > logs/evals/vllm_serve_retry.sh
setsid nohup bash logs/evals/vllm_serve_retry.sh > logs/evals/vllm_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do
  sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "vLLM server died"; tail -20 logs/evals/vllm_$PORT.log; exit 1; }
done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"c13c\", \"lora_path\": \"$PWD/data/opcd/c13c/round_015/adapter\"}"; echo
echo "$(date) sampling on GPU $GPU :$PORT"
~/venv/bin/python agent_harness.py run data/agent_harness/pool_retry.jsonl --model c13c --url http://127.0.0.1:$PORT \
  --modes off on --runs 4 --rounds 2 --rows-feedback --concurrency 6 --out results/agent_harness/c13c_pool_retry_rows.jsonl \
  > logs/evals/agent_harness_c13c_retry.log 2>&1
echo "$(date) sampling done: $(grep -c . results/agent_harness/c13c_pool_retry_rows.jsonl) records"
kill $SERVER; sleep 5
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
~/venv/bin/python agent_harness.py summary results/agent_harness/c13c_pool_retry_rows.jsonl > results/agent_harness/c13c_pool_retry_rows.summary.md 2>&1
echo "$(date) DONE"
