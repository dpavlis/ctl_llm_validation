#!/bin/bash -l
# rb1009 gates (findings §3.23 follow-up): rb1009 served as a plain base on both GPUs, :3011 (GPU 3, thinking OFF) and
# :3012 (GPU 1, thinking ON). Compared with the rb1006 vLLM baselines (§4.7, §3.20):
#   - suite v4 full n5 both modes; thinking-off validate x9; T40/T42 n20 thinking on;
#   - suite v5 gap tests incl. DataIntersection T53/T54 and SCD T60/T61, n10 both modes;
#   - hard-case sets 1-3 (declaration belief), k4.
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals
export PATH=/home/pavlisd/venv/bin:$PATH
for p in 3011 3012; do
  src=logs/evals/opcd_vllm_serve.sh; [ $p = 3012 ] && src=scripts/vllm_eval_serve.sh
  sed -e 's#--model /home/pavlisd/exports/qwen38_rb1006_sftdpo --served-model-name rb1006#--model /home/pavlisd/exports/qwen38_rb1009_sftdpo --served-model-name rb1009#' \
      -e 's/ --lora-modules smoke=[^ ]*//' $src > $L/vllm_${p}_rb1009.sh
  grep -q "served-model-name rb1009" $L/vllm_${p}_rb1009.sh || { echo "serve script for $p not rewritten"; exit 1; }
  setsid nohup bash $L/vllm_${p}_rb1009.sh > $L/vllm_${p}_rb1009.log 2>&1 < /dev/null & disown
done
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models | grep -q rb1009; do sleep 10; done; done
echo "$(date '+%m-%d %H:%M') servers up"
GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
( t rb1009_v5gaps_on configs/eval_rb1009_v5gaps_on.yaml --tests $GAPS --runs 10
  t rb1009_t40t42_n20 configs/eval_rb1009_vllm_on.yaml --tests T40,T42 --runs 20
  t rb1009_on_full_n5 configs/eval_rb1009_vllm_on.yaml --runs 5 ) &
( t rb1009_v5gaps_off configs/eval_rb1009_v5gaps_off.yaml --tests $GAPS --runs 10
  t rb1009_off_full_n5 configs/eval_rb1009_vllm_off.yaml --runs 5
  for r in 2 3 4 5 6 7 8 9; do t rb1009_off_validate_rep$r configs/eval_rb1009_vllm_off.yaml --validate-only --runs 5; done
  for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
    CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py rb1009_set$s --file $f rb1009=rb1009:student --k 4 --config configs/opcd_c12.yaml > $L/hard_eval_rb1009_set$s.log 2>&1; done
  echo "$(date '+%m-%d %H:%M') hard-case evals done" ) &
wait; echo "$(date '+%m-%d %H:%M') rb1009 evals done"
