#!/bin/bash -l
# Exec-RFT pilot round 1 end to end: train exec_rft1 on GPU 1 (sampler :3011 on GPU 3, already serving rb1009), then start the
# eval server on GPU 1 (:3012) and run the gates for the final round and c13c's second gap-test run.
#   setsid nohup scripts/exec_rft/run.sh > logs/exec_rft/run.log 2>&1 &
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/exec_rft; LAST=${LAST:-056}
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
curl -sf 127.0.0.1:3011/v1/models >/dev/null || { echo "no sampler on :3011"; exit 1; }
echo "$(date '+%m-%d %H:%M') exec_rft1 train (GPU 1)"
CUDA_VISIBLE_DEVICES=1 $PY -u opcd.py train --config configs/opcd_exec_rft1.yaml > $L/train_exec_rft1.log 2>&1 || { echo "train failed"; exit 1; }
echo "$(date '+%m-%d %H:%M') train done"
setsid nohup bash scripts/vllm_eval_serve_rb1009.sh > $L/vllm_3012.log 2>&1 < /dev/null & disown
until curl -sf 127.0.0.1:3012/v1/models >/dev/null; do sleep 10; done
scripts/exec_rft/gates.sh exec_rft1 $LAST
GATES=gaps scripts/exec_rft/gates.sh c13c 015
echo "$(date '+%m-%d %H:%M') all done"
