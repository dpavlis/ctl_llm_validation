#!/bin/bash -l
# rb1011s2 extra gates (brief addendum): suite-v5 gap tests n10 both modes + exec_score, thinking-on full suite n5.
# Needs the rb1011s2 server on :3026 (logs/evals/vllm_rb1011s2.sh).
cd /home/pavlisd/llama_train; export PATH=/home/pavlisd/venv/bin:$PATH
PY=~/venv/bin/python; L=logs/evals; GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
ts() { date '+%m-%d %H:%M'; }
n=0; until curl -sf 127.0.0.1:3026/v1/models | grep -q rb1011s2; do sleep 10; n=$((n+1)); [ $n -gt 90 ] && { echo "server not up"; exit 1; }; done
t() { log=$1; shift; CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(ts) $log done"; }
( t v5gaps_rb1011s2_on configs/eval_v5gaps_rb1011s2_on.yaml --tests $GAPS --runs 10
  t rb1011s2_full_on_n5 configs/eval_rb1011s2_vllm_on.yaml --runs 5 ) & a=$!
( t v5gaps_rb1011s2_off configs/eval_v5gaps_rb1011s2_off.yaml --tests $GAPS --runs 10 ) & b=$!
wait $a $b
$PY data/suite_v5/exec_score.py $(ls results/results_qwen38_v5gaps_rb1011s2_o*_*.json) --out results/exec/gaps_rb1011s2.json > $L/exec_gaps_rb1011s2.log 2>&1
echo "$(ts) exec scoring done"
S=$(ps -u pavlisd -o pid=,args= | awk '$2 ~ /python3$/ && /vllm.entrypoints.openai.api_server/ && /served-model-name rb1011s2/ {print $1}'); [ -n "$S" ] && kill $S
echo "$(ts) all done"
