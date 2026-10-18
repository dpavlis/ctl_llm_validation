#!/bin/bash -l
# OPCD generate-gap run (c9, c10, …) end to end on GPUs 1 and 3 (GPUs 0 and 2 are another user's): train on GPU 1 with the sampler on GPU 3 (:3011),
# then the evaluation server on GPU 1 (:3012) and the evaluations:
#   - gap holdout (12 prompts, 3 per gap) and suite v5 gap tests at n10, both modes; G4 holdout thinking-on n10 more;
#   - the c4 gates: hard-case sets 1-3, T40/T42 n20, full v4 ON/OFF n5, thinking-off validate x9.
#   setsid nohup scripts/opcd_gaps_run.sh RUN [LAST_ROUND=019] > logs/evals/opcd_RUN_run.log 2>&1 &
#   (needs the sampler logs/evals/opcd_vllm_serve.sh on :3011 / GPU 3; GPU 1 free. c4's comparison runs exist already.)
cd /home/pavlisd/llama_train
RUN=$1; LAST=${2:-019}; HO2=${HO2:-}   # HO2: an extra holdout suite run for this run and for BASE (c11: DataIntersection / SCD-2)
# EVAL_SERVE: the eval server script for :3012 (default scripts/vllm_eval_serve.sh, base rb1006; c13: the rb1009 one)
# TRAIN_GPU / SAMPLE_GPU / SAMPLE_PORT / EVAL_PORT (defaults 1 / 3 / 3011 / 3012): another GPU pair, e.g. c13d on 0 / 2 / 3016 / 3015
# (EVAL_SERVE must then start its server on TRAIN_GPU and EVAL_PORT).
TG=${TRAIN_GPU:-1} SG=${SAMPLE_GPU:-3} SP=${SAMPLE_PORT:-3011} EP=${EVAL_PORT:-3012}
BASE=${BASE:-} AD=${RUN}_r$LAST; PY=~/venv/bin/python; L=logs/evals; K=logs/evals/locks
SUITE4=$PWD/results/eval_snapshot_20261003/ctl2_test_suite_v4.json; SUITE5=$PWD/results/eval_snapshot_20261013/ctl2_test_suite_v5.json
GAPS=${GAPS:-T44,T46,T57,T60,T61,T62,T63,T67,T73}
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
for g in $TG $SG; do sudo -n nvidia-smi -i $g -pl 450 >/dev/null; l=$(nvidia-smi -i $g --query-gpu=power.limit --format=csv,noheader,nounits | cut -d. -f1); [ "$l" -le 450 ] || { echo "GPU $g limit $l W"; exit 1; }; done
mkdir -p $K
until curl -sf 127.0.0.1:$SP/v1/models >/dev/null; do sleep 10; done   # the sampler must answer before training starts
echo "$(date '+%m-%d %H:%M') $RUN train (GPU $TG)"
flock $K/gpu$TG.lock env CUDA_VISIBLE_DEVICES=$TG $PY -u opcd.py train --config configs/opcd_$RUN.yaml > $L/opcd_${RUN}_train.log 2>&1 || { echo "$RUN train failed"; exit 1; }
echo "$(date '+%m-%d %H:%M') $RUN train done"
setsid nohup ${EVAL_SERVE:-scripts/vllm_eval_serve.sh} > $L/vllm_eval_serve.log 2>&1 < /dev/null & disown
until curl -sf 127.0.0.1:$EP/v1/models >/dev/null; do sleep 10; done
for p in $SP $EP; do for a in $AD ${BASE:+${BASE}_r019}; do r=${a%%_*}; curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"$a\", \"lora_path\": \"$PWD/data/opcd/$r/round_${a#*_r}/adapter_vllm\"}" >/dev/null || echo "load $a on :$p: already loaded or failed"; done; done
mk() {  # mk NAME ADAPTER MODE PORT SUITE [nosys]
  sed -e "s/vllm_model: rb1006/vllm_model: $2/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$4#; s/run_label: qwen38_rb1006_vllm_$3/run_label: qwen38_$1/" \
      -e "s#suite_file: .*#suite_file: $5#" -e "1s/.*/# $1 ($2 on vLLM :$4), thinking ${3^^} -- written by scripts\/opcd_c9_run.sh./" \
      configs/eval_rb1006_vllm_$3.yaml > configs/eval_$1.yaml; }
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for m in on off; do port=$EP; [ $m = off ] && port=$SP
  for a in $AD; do n=${a%%_*}
    mk gapho_${n}_$m $a $m $port $PWD/data/opcd/teacher_check/suite_c9holdout.json
    mk v5gaps_${n}_$m $a $m $port $SUITE5
  done
  mk vllm_opcd${RUN}_$m $AD $m $port $SUITE4
done
( for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
    CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${RUN}_set$s --file $f $RUN=$AD:student --k 4 --config configs/opcd_$RUN.yaml > $L/hard_eval_${RUN}_set$s.log 2>&1; done
  echo "$(date '+%m-%d %H:%M') $RUN hard-case evals done" ) &
( t gapho_${RUN}_on configs/eval_gapho_${RUN}_on.yaml --runs 4; t v5gaps_${RUN}_on configs/eval_v5gaps_${RUN}_on.yaml --tests $GAPS --runs 10
  sed "s/run_label: qwen38_gapho_${RUN}_on/run_label: qwen38_confirm_ho_${RUN}_on/" configs/eval_gapho_${RUN}_on.yaml > configs/eval_confirm_ho_${RUN}_on.yaml
  t confirm_ho_${RUN}_on configs/eval_confirm_ho_${RUN}_on.yaml --tests G4_03,G4_09,G4_15 --runs 10
  t vllm_opcd${RUN}_t40t42_n20 configs/eval_vllm_opcd${RUN}_on.yaml --tests T40,T42 --runs 20
  t vllm_opcd${RUN}_on_full_n5 configs/eval_vllm_opcd${RUN}_on.yaml --runs 5 ) &
( t gapho_${RUN}_off configs/eval_gapho_${RUN}_off.yaml --runs 4; t v5gaps_${RUN}_off configs/eval_v5gaps_${RUN}_off.yaml --tests $GAPS --runs 10
  t vllm_opcd${RUN}_off_full_n5 configs/eval_vllm_opcd${RUN}_off.yaml --runs 5
  for r in 2 3 4 5 6 7 8 9; do t vllm_opcd${RUN}_off_validate_rep$r configs/eval_vllm_opcd${RUN}_off.yaml --validate-only --runs 5; done ) &
if [ -n "$HO2" ]; then
  for m in on off; do port=$EP; [ $m = off ] && port=$SP
    for a in $AD ${BASE:+${BASE}_r019}; do mk ho2_${a%%_*}_$m $a $m $port $HO2; done; done
  ( for a in $AD ${BASE:+${BASE}_r019}; do t ho2_${a%%_*}_on configs/eval_ho2_${a%%_*}_on.yaml --runs 4; done ) &
  ( for a in $AD ${BASE:+${BASE}_r019}; do t ho2_${a%%_*}_off configs/eval_ho2_${a%%_*}_off.yaml --runs 4; done ) &
fi
wait; echo "$(date '+%m-%d %H:%M') $RUN all done"
