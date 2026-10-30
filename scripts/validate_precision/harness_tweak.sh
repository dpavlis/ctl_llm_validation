#!/bin/bash -l
# valprec2 generate check (spec/validate_precision2_findings.md, Indication 5): the agentic harness on the fresh-domain
# pool_tweak exactly as c13c was run in §3.36 (scripts/harness_measurement/run_c13c.sh, errors-only pass): both thinking
# modes, 2 feedback rounds, --runs 2. Serves rb1009 on GPU $GPU :$PORT as "rb1009_vph" with the adapter hot-loaded as $RUN.
#   RUN=valprec2 LAST=155 GPU=2 setsid nohup scripts/validate_precision/harness_tweak.sh > logs/validate_precision/harness_tweak_valprec2.log 2>&1 &
cd ~/llama_train
RUN=${RUN:-valprec2}; LAST=${LAST:-155}; GPU=${GPU:-2}; PORT=${PORT:-3014}; L=logs/validate_precision
sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" -e "s/--served-model-name rb1009 /--served-model-name rb1009_vph /" scripts/vllm_eval_serve_rb1009.sh \
  > $L/vllm_serve_harness.sh
setsid nohup bash $L/vllm_serve_harness.sh > $L/vllm_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do
  sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "no server"; tail -20 $L/vllm_$PORT.log; exit 1; }
done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"$RUN\", \"lora_path\": \"$PWD/data/opcd/$RUN/$(printf 'round_%03d' $LAST)/adapter\"}"; echo
echo "$(date '+%m-%d %H:%M') harness pool_tweak $RUN (GPU $GPU :$PORT)"
~/venv/bin/python agent_harness.py run data/agent_harness/pool_tweak.jsonl --model $RUN --url http://127.0.0.1:$PORT \
  --modes off on --runs 2 --rounds 2 --concurrency 4 --out results/agent_harness/${RUN}_pool_tweak.jsonl
~/venv/bin/python agent_harness.py summary results/agent_harness/${RUN}_pool_tweak.jsonl --by component > results/agent_harness/${RUN}_pool_tweak.summary.md
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
echo "$(date '+%m-%d %H:%M') all done"
