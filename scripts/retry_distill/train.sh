#!/bin/bash -l
# retry1 training only (run.sh did prepare + smoke; its round count came out empty, fixed by hand to 67).
#   TRAIN_GPU=0 setsid nohup scripts/retry_distill/train.sh > logs/retry_distill/train.log 2>&1 &
cd /home/pavlisd/llama_train
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
curl -sf 127.0.0.1:3011/v1/models >/dev/null || { echo "no sampler on :3011"; exit 1; }
echo "$(date '+%m-%d %H:%M') retry1 train (GPU ${TRAIN_GPU:-0})"
CUDA_VISIBLE_DEVICES=${TRAIN_GPU:-0} ~/venv/bin/python -u opcd.py train --config configs/opcd_retry1.yaml > logs/retry_distill/train_retry1.log 2>&1 || { echo "train failed"; tail -5 logs/retry_distill/train_retry1.log; exit 1; }
echo "$(date '+%m-%d %H:%M') train done"
