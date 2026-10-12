#!/bin/bash -l
# One OPCD run end to end: train (GPU $2, vLLM sampler on GPU 3 / :3011), then evaluate the final adapter on the
# evaluation vLLM server (GPU 1 / :3012, test.py mut.mode vllm, 32 workers; no export): hard-case sets 1-3,
# T40/T42 fix n20, full ON n5, full OFF n5, validate OFF x9 (rb1006 on vLLM: WRONG 7.5% +- 1.3% over 9 reps).
#   scripts/opcd_run.sh RUN TRAIN_GPU LAST_ROUND   (needs scripts/vllm_eval_serve.sh on :3012 and the training sampler on :3011)
RUN=$1; G=$2; LAST=$(printf "%03d" $3); AD=${RUN}_r$LAST
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals; K=logs/evals/locks; SUITE=/home/pavlisd/llama_train/results/eval_snapshot_20261003/ctl2_test_suite_v4.json
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
pl() { for g in 0 1 2 3; do sudo -n nvidia-smi -i $g -pl 450 >/dev/null; l=$(nvidia-smi -i $g --query-gpu=power.limit --format=csv,noheader,nounits | cut -d. -f1); [ "$l" -le 450 ] || { echo "GPU $g limit is $l W -- stopping"; exit 1; }; done; }
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 --suite-file $SUITE > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $RUN $log done ($(( ($(date +%s)-s)/60 )) min)"; }
pl
echo "$(date '+%m-%d %H:%M') $RUN train (GPU $G)"
flock $K/gpu$G.lock env CUDA_VISIBLE_DEVICES=$G $PY -u opcd.py train --config configs/opcd_$RUN.yaml > $L/opcd_${RUN}_train.log 2>&1 || { echo "$RUN train failed"; exit 1; }
echo "$(date '+%m-%d %H:%M') $RUN train done"
( for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
    CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${RUN}_set$s --file $f $RUN=$AD:student --k 4 --config configs/opcd_$RUN.yaml > $L/hard_eval_${RUN}_set$s.log 2>&1; done
  echo "$(date '+%m-%d %H:%M') $RUN hard-case evals done" ) &
# final adapter onto the evaluation server (VllmSampler.publish already wrote the renamed-key copy)
curl -sf -X POST 127.0.0.1:3012/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"$AD\", \"lora_path\": \"$PWD/data/opcd/$RUN/round_$LAST/adapter_vllm\"}" >/dev/null \
  || { echo "$RUN: loading $AD on :3012 failed"; exit 1; }
for m in on off; do
  sed -e "s/vllm_model: rb1006/vllm_model: $AD/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:3012#; s/run_label: qwen38_rb1006_vllm_$m/run_label: qwen38_rb1006_vllm_opcd${RUN}_$m/" \
      -e "1s/.*/# OPCD $RUN (adapter $AD on the evaluation vLLM server), thinking ${m^^} -- written by logs\/evals\/opcd_run.sh./" \
      configs/eval_rb1006_vllm_$m.yaml > configs/eval_vllm_opcd${RUN}_$m.yaml
done
t vllm_opcd${RUN}_t40t42_n20 configs/eval_vllm_opcd${RUN}_on.yaml --tests T40,T42 --runs 20
t vllm_opcd${RUN}_on_full_n5 configs/eval_vllm_opcd${RUN}_on.yaml --runs 5
t vllm_opcd${RUN}_off_full_n5 configs/eval_vllm_opcd${RUN}_off.yaml --runs 5
for r in 2 3 4 5 6 7 8 9; do t vllm_opcd${RUN}_off_validate_rep$r configs/eval_vllm_opcd${RUN}_off.yaml --validate-only --runs 5; done
wait; echo "$(date '+%m-%d %H:%M') $RUN all done"
