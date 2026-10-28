#!/bin/bash -l
# Retry-distill data step 1b (spec/retry_distill_brief.md): a second --tweak batch with seeds different from Part A
# (101-105) as the rest of the training pool, then c13c sampled on it exactly as on pool_retry (k = 4, both modes,
# 2 rounds, --rows-feedback). Seeds 201-202 on the six corpus sets, 203-205 on Rollup accumulator only (Part A's Rollup
# acceptance was low). Per-seed pools in data/agent_harness/tweak_retry/, merged into data/agent_harness/pool_retry_tweak.jsonl
# with pool_tweak's ids excluded. Serves rb1009 + c13c on GPU $GPU, port $PORT, name rb1009_rd.
#   GPU=2 setsid nohup scripts/retry_distill_tweak.sh > logs/evals/retry_distill_tweak.log 2>&1 &
cd ~/llama_train
GPU=${GPU:-2}; PORT=${PORT:-3015}
S=ctl_lora_training/sft_training_data
T=data/agent_harness/tweak_retry
for seed in 201 202; do
  [ -f $T/s$seed.report.json ] || ~/venv/bin/python agent_harness.py pool --seed $seed --tweak-concurrency 8 --out $T/s$seed.jsonl --tweak \
    $S/CTL_LoRA_scd2_sft.json $S/CTL_LoRA_syntax_pitfalls_sft.json $S/CTL_LoRA_rollup_accumulator_sft.json \
    $S/CTL_LoRA_normalizer_multirow_sft.json $S/CTL_LoRA_dataintersection_sft.json $S/CTL_LoRA_zerodate_sft.json
  echo "$(date) seed $seed done"
done
for seed in 203 204 205; do
  [ -f $T/s${seed}r.report.json ] || ~/venv/bin/python agent_harness.py pool --seed $seed --tweak-concurrency 8 \
    --out $T/s${seed}r.jsonl --tweak $S/CTL_LoRA_rollup_accumulator_sft.json
  echo "$(date) seed ${seed}r done"
done
~/venv/bin/python scripts/harness_measurement/merge_pools.py --dir $T --exclude data/agent_harness/pool_tweak.jsonl \
  --out data/agent_harness/pool_retry_tweak.jsonl
echo "$(date) pool built: $(grep -c . data/agent_harness/pool_retry_tweak.jsonl) tasks"

sed -e "s/CUDA_VISIBLE_DEVICES=1/CUDA_VISIBLE_DEVICES=$GPU/" -e "s/--port 3012/--port $PORT/" -e "s/--served-model-name rb1009 /--served-model-name rb1009_rd /" scripts/vllm_eval_serve_rb1009.sh \
  > logs/evals/vllm_serve_retry_tweak.sh
setsid nohup bash logs/evals/vllm_serve_retry_tweak.sh > logs/evals/vllm_$PORT.log 2>&1 < /dev/null &
SERVER=$!
until curl -sf 127.0.0.1:$PORT/v1/models >/dev/null; do
  sleep 10
  kill -0 $SERVER 2>/dev/null || { echo "vLLM server died"; tail -20 logs/evals/vllm_$PORT.log; exit 1; }
done
curl -s -X POST 127.0.0.1:$PORT/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"c13c\", \"lora_path\": \"$PWD/data/opcd/c13c/round_015/adapter\"}"; echo
echo "$(date) sampling on GPU $GPU :$PORT"
~/venv/bin/python agent_harness.py run data/agent_harness/pool_retry_tweak.jsonl --model c13c --url http://127.0.0.1:$PORT \
  --modes off on --runs 4 --rounds 2 --rows-feedback --concurrency 6 --out results/agent_harness/c13c_pool_retry_tweak_rows.jsonl \
  > logs/evals/agent_harness_c13c_retry_tweak.log 2>&1
echo "$(date) sampling done: $(grep -c . results/agent_harness/c13c_pool_retry_tweak_rows.jsonl) records"
kill $SERVER; sleep 5
for p in $(ps -eo pid,user,args | awk -v u=$USER -v port="--port $PORT" '$2==u && index($0, port) && /vllm.entrypoints/ {print $1}'); do kill $p; done
~/venv/bin/python agent_harness.py summary results/agent_harness/c13c_pool_retry_tweak_rows.jsonl > results/agent_harness/c13c_pool_retry_tweak_rows.summary.md 2>&1
echo "$(date) DONE"
