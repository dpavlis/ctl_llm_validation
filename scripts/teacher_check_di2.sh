#!/bin/bash -l
# DataIntersection round-2b teacher check (data/opcd/build_di2_tcheck.py): the c11 DI teacher vs students c10 r019 and
# c11 r023 on the 60 revised, unhinted DI prompts, n3, thinking ON (:3012, GPU 1) and OFF (:3011, GPU 3).
# Starts both vLLM servers at --max-model-len 32768 (the teacher prompt is ~3k tokens longer).
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals
sed 's/--max-model-len 16384/--max-model-len 32768/' logs/evals/opcd_vllm_serve.sh > $L/vllm_3011_32k.sh
sed 's/--max-model-len 16384/--max-model-len 32768/' scripts/vllm_eval_serve.sh > $L/vllm_3012_32k.sh
for p in 3011 3012; do curl -sf 127.0.0.1:$p/v1/models >/dev/null || { setsid nohup bash $L/vllm_${p}_32k.sh > $L/vllm_${p}_32k.log 2>&1 < /dev/null & disown; }; done
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models >/dev/null; do sleep 10; done
  for a in c10_r019 c11_r023; do r=${a%%_*}; curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$a\", \"lora_path\": \"$PWD/data/opcd/$r/round_${a#*_r}/adapter_vllm\"}" >/dev/null || echo "load $a on :$p failed"; done; done
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for m in on off; do ( for n in teacher c10 c11; do t tcheck_di2_${n}_$m configs/eval_tcheck_di2_${n}_$m.yaml --runs 3; done ) & done
wait; echo "$(date '+%m-%d %H:%M') di2 teacher check done"
