#!/bin/bash -l
# c11 teacher check: the c11 teacher on suite v5 T53/T54/T60/T61 (n10) vs plain c10 on T53/T54 (c10's T60/T61 n10 exist).
# Needs both vLLM servers at --max-model-len 32768 with c10_r019 loaded.
cd /home/pavlisd/llama_train
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models >/dev/null; do sleep 10; done
  curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"c10_r019\", \"lora_path\": \"$PWD/data/opcd/c10/round_019/adapter_vllm\"}" >/dev/null || echo "load c10 on :$p failed"; done
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" ~/venv/bin/python -u test.py "$@" --workers 32 > logs/evals/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for m in on off; do ( t tcheck_c11teacher_$m configs/eval_tcheck_c11teacher_$m.yaml --runs 10
                      t tcheck_c10_t5354_$m configs/eval_v5gaps_c10_$m.yaml --tests T53,T54 --runs 10 ) & done
wait; echo "$(date '+%m-%d %H:%M') c11 teacher check done"
