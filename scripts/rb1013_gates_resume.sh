#!/bin/bash -l
# Resume of scripts/base_eval.sh for rb1013 after the 03:28–03:32 mishap (another lane's cleanup killed the :3012 server,
# my own kill hit the thinking-off branch). Reruns: thinking on everything (+ DI subsets), thinking off validate reps 5-9
# and the hard-case sets. Thinking-off :3011 on GPU 0, thinking-on :3012 on GPU 1. Stops only the servers it started.
cd ~/llama_train; L=logs/evals; PY=~/venv/bin/python; TAG=rb1013; export PATH=/home/pavlisd/venv/bin:$PATH
ts() { date '+%m-%d %H:%M'; }
setsid nohup bash $L/vllm_3011_rb1013.sh > $L/vllm_3011_rb1013.log 2>&1 < /dev/null & S1=$!
setsid nohup bash $L/vllm_3012_rb1013.sh > $L/vllm_3012_rb1013.log 2>&1 < /dev/null & S2=$!
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models | grep -q "\"$TAG\""; do sleep 10; done; done
echo "$(ts) $TAG servers up"
GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(ts) $log done ($(( ($(date +%s)-s)/60 )) min, $(grep -c 'Verdict:' $L/$log.log) verdicts)"; }
( t ${TAG}_v5gaps_on configs/eval_${TAG}_v5gaps_on.yaml --tests $GAPS --runs 10
  TAG=$TAG PORT=3012 scripts/base_di_check.sh > $L/di_check_$TAG.log 2>&1 &
  t ${TAG}_t40t42_n20 configs/eval_${TAG}_vllm_on.yaml --tests T40,T42 --runs 20
  t ${TAG}_t41_n20 configs/eval_${TAG}_vllm_on.yaml --tests T41 --runs 20
  t ${TAG}_on_full_n5 configs/eval_${TAG}_vllm_on.yaml --runs 5
  wait; cat $L/di_check_$TAG.log ) & P1=$!
( for r in 5 6 7 8 9; do t ${TAG}_off_validate_rep$r configs/eval_${TAG}_vllm_off.yaml --validate-only --runs 5; done
  for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
    CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${TAG}_set$s --file $f $TAG=$TAG:student --k 4 --config configs/opcd_hardeval_$TAG.yaml > $L/hard_eval_${TAG}_set$s.log 2>&1; done
  echo "$(ts) hard-case evals done" ) & P2=$!
wait $P1 $P2
pkill -P $S1; pkill -P $S2
echo "$(ts) $TAG evals done (resume)"
