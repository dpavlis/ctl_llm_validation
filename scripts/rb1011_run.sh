#!/bin/bash -l
# rb1011 next-base candidate (configs/qwen38_rb1011.yaml): SFT + DPO + export on GPU 3, then the base gates (scripts/base_eval.sh).
#   setsid nohup scripts/rb1011_run.sh > logs/rb1011_run.log 2>&1 &
cd ~/LlamaFactory
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
K=/home/pavlisd/llama_train/logs/evals/locks; mkdir -p $K
echo "$(date '+%m-%d %H:%M') rb1011 train (GPU 3)"
flock $K/gpu3.lock env CUDA_VISIBLE_DEVICES=3 ~/venv/bin/python ~/llama_train/train.py ~/llama_train/configs/qwen38_rb1011.yaml --skip-post-sft \
  > ~/llama_train/logs/rb1011_train.log 2>&1 || { echo "$(date '+%m-%d %H:%M') rb1011 TRAIN FAILED"; exit 1; }
echo "$(date '+%m-%d %H:%M') rb1011 trained"
cd ~/llama_train
scripts/base_eval.sh /home/pavlisd/exports/qwen38_rb1011_sftdpo rb1011 > logs/evals/rb1011_eval.log 2>&1
tail -n 1 logs/evals/rb1011_eval.log
echo "$(date '+%m-%d %H:%M') rb1011 done"
