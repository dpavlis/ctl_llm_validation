#!/bin/bash -l
# T41 / T60 teacher checks on rb1009 (GPUs 0/2, :3015/:3016), alongside Part B.
#   T41/T22: rulev6 (c13c's teacher) vs rulev7 (= rulev6 + rulev4's Rollup accumulator note), thinking on; rulev7 full v4 n3
#   T60 off: the guide_NORMALIZER teacher that scores the G4 gap prompts in thinking-off mode
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 24 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
( t tcheck_rulev6_t41t22 configs/eval_tcheck_rulev6_rollup_rb1009_on.yaml --tests T41,T22 --runs 20
  t tcheck_rulev7_t41t22 configs/eval_tcheck_rulev7_rollup_rb1009_on.yaml --tests T41,T22 --runs 20
  t tcheck_rulev7_full configs/eval_tcheck_rulev7_rb1009_on.yaml --runs 3 ) &
( t tcheck_guideNORM_t60off configs/eval_tcheck_guideNORM_rb1009_off.yaml --tests T60 --runs 10 ) &
wait; echo "$(date '+%m-%d %H:%M') t41/t60 checks done"
