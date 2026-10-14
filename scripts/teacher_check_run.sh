#!/bin/bash -l
# OPCD generate-gap teacher check: c4 with the plain vs the guide system prompt, 36 prompts x 4 runs, thinking ON (:3012)
# and OFF (:3011). Needs both vLLM servers up with --max-model-len 32768 (the guide prompt is up to ~4k tokens longer).
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models >/dev/null; do sleep 10; done
  curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"c4_r015\", \"lora_path\": \"$PWD/data/opcd/c4/round_015/adapter_vllm\"}" >/dev/null || echo "load c4 on :$p failed"; done
t() { s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py configs/eval_tcheck_c4_$1.yaml --runs 4 --workers 32 > $L/tcheck_c4_$1.log 2>&1
      echo "$(date '+%m-%d %H:%M') tcheck $1 done ($(( ($(date +%s)-s)/60 )) min)"; }
( t plain_on; t guide_on ) &
( t plain_off; t guide_off ) &
wait
