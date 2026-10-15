#!/bin/bash -l
# Earlier-checkpoint check for an OPCD run: selected suite v5 tests at n10, both modes, per round adapter.
#   setsid nohup scripts/opcd_ckpt_check.sh RUN TESTS ROUND... > logs/evals/ckpt_RUN.log 2>&1 &
#   e.g. scripts/opcd_ckpt_check.sh c11 T53,T60,T61 007 011 015   (servers :3011 off, :3012 on must be up)
cd /home/pavlisd/llama_train
RUN=$1; TESTS=$2; shift 2; PY=~/venv/bin/python; L=logs/evals
SUITE5=$PWD/results/eval_snapshot_20261013/ctl2_test_suite_v5.json
mk() {  # mk NAME ADAPTER MODE PORT SUITE
  sed -e "s/vllm_model: rb1006/vllm_model: $2/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$4#; s/run_label: qwen38_rb1006_vllm_$3/run_label: qwen38_$1/" \
      -e "s#suite_file: .*#suite_file: $5#" -e "1s/.*/# $1 ($2 on vLLM :$4), thinking ${3^^} -- written by scripts\/opcd_ckpt_check.sh./" \
      configs/eval_rb1006_vllm_$3.yaml > configs/eval_$1.yaml; }
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for r in "$@"; do a=${RUN}_r$r
  for p in 3011 3012; do curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$a\", \"lora_path\": \"$PWD/data/opcd/$RUN/round_$r/adapter_vllm\"}" >/dev/null || echo "load $a on :$p: already loaded or failed"; done
  mk ckpt_${a}_off $a off 3011 $SUITE5; mk ckpt_${a}_on $a on 3012 $SUITE5
done
( for r in "$@"; do t ckpt_${RUN}_r${r}_off configs/eval_ckpt_${RUN}_r${r}_off.yaml --tests $TESTS --runs 10; done ) &
( for r in "$@"; do t ckpt_${RUN}_r${r}_on configs/eval_ckpt_${RUN}_r${r}_on.yaml --tests $TESTS --runs 10; done ) &
wait; echo "$(date '+%m-%d %H:%M') checkpoint check done"
