#!/bin/bash -l
# Part A step 3 (spec/harness_measurement_brief.md): c13c on pool_tweak exactly as pool 1 was run — both thinking modes,
# 2 feedback rounds, errors-only and --rows-feedback, --runs 2. Waits for a free GPU (another lane may hold them), serves
# rb1009 there on :3014 with the c13c adapter hot-loaded as "c13c", runs both harness passes in parallel, then stops
# its own server. The base is served as "rb1009_hm" so that Part B's run_models.sh cleanup (which kills any server named
# rb1009) cannot stop it; that killed the first attempt on 10-26 at 23:24. The harness resumes: records with a final
# status are skipped, so drop model_error records before a rerun.
#   setsid nohup scripts/harness_measurement/run_c13c.sh > logs/harness_measurement/run_c13c.log 2>&1 &
cd ~/llama_train
PORT=${PORT:-3014}
until GPU=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F', ' '$2 < 1000 {print $1; exit}'); [ -n "$GPU" ]; do
  sleep 120
done
echo "$(date) using GPU $GPU"
sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" -e "s/--served-model-name rb1009 /--served-model-name rb1009_hm /" scripts/vllm_eval_serve_rb1009.sh \
  > logs/harness_measurement/vllm_serve.sh
setsid nohup bash logs/harness_measurement/vllm_serve.sh > logs/harness_measurement/vllm_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do
  sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "vLLM server died"; tail -20 logs/harness_measurement/vllm_$PORT.log; exit 1; }
done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"c13c\", \"lora_path\": \"$PWD/data/opcd/c13c/round_015/adapter\"}"; echo
export POOL=pool_tweak RUNS=2 URL=http://127.0.0.1:$PORT
scripts/agent_harness_run.sh > logs/harness_measurement/c13c_pool_tweak.log 2>&1 &
A=$!
scripts/agent_harness_rows_run.sh > logs/harness_measurement/c13c_pool_tweak_rows.log 2>&1 &
B=$!
wait $A $B
echo "$(date) harness passes done"
kill $SERVER; sleep 5; pkill -u $USER -f "vllm_serve.sh" ; true
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
~/venv/bin/python scripts/harness_measurement/tweak_table.py > results/agent_harness/pool_tweak_vs_pool1.md
echo DONE
