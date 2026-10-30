#!/bin/bash -l
# Retry-distill data step 1c: the thinking-on triple prompts of pool_retry + pool_retry_tweak re-sampled thinking on with the
# thinking text stored (agent_harness.py now keeps `think` per attempt), since the thinking-on targets need the corrected
# attempt's thinking (spec/retry_distill_brief.md, Data 2). Same settings as before: k = 4, 2 rounds, --rows-feedback.
#   GPU=0 setsid nohup scripts/retry_distill_sample_on.sh > logs/evals/retry_distill_sample_on.log 2>&1 &
cd ~/llama_train
GPU=${GPU:-0}; PORT=${PORT:-3016}
sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" -e "s/--served-model-name rb1009 /--served-model-name rb1009_rd /" scripts/vllm_eval_serve_rb1009.sh \
  > logs/evals/vllm_serve_retry_on.sh
setsid nohup bash logs/evals/vllm_serve_retry_on.sh > logs/evals/vllm_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do
  sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "vLLM server died"; tail -20 logs/evals/vllm_$PORT.log; exit 1; }
done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"c13c\", \"lora_path\": \"$PWD/data/opcd/c13c/round_015/adapter\"}"; echo
echo "$(date) sampling on GPU $GPU :$PORT"
~/venv/bin/python agent_harness.py run data/agent_harness/pool_retry_on.jsonl --model c13c --url http://127.0.0.1:$PORT \
  --modes on --runs 4 --rounds 2 --rows-feedback --concurrency 6 --out results/agent_harness/c13c_pool_retry_on_think.jsonl \
  > logs/evals/agent_harness_c13c_retry_on.log 2>&1
echo "$(date) sampling done: $(grep -c . results/agent_harness/c13c_pool_retry_on_think.jsonl) records"
kill $SERVER; sleep 5
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
echo "$(date) DONE"
