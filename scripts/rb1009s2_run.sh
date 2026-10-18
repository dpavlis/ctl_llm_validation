#!/bin/bash -l
# rb1009 seed rerun (configs/qwen38_rb1009s2.yaml): SFT + DPO + export on GPU 1, then the base gates (scripts/base_eval.sh).
#   setsid nohup scripts/rb1009s2_run.sh > logs/rb1009s2_run.log 2>&1 &
cd ~/LlamaFactory
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
K=/home/pavlisd/llama_train/logs/evals/locks; mkdir -p $K
echo "$(date '+%m-%d %H:%M') rb1009s2 train (GPU 1)"
flock $K/gpu1.lock env CUDA_VISIBLE_DEVICES=1 ~/venv/bin/python ~/llama_train/train.py ~/llama_train/configs/qwen38_rb1009s2.yaml --skip-post-sft \
  > ~/llama_train/logs/rb1009s2_train.log 2>&1 || { echo "$(date '+%m-%d %H:%M') rb1009s2 TRAIN FAILED"; exit 1; }
echo "$(date '+%m-%d %H:%M') rb1009s2 trained"
cd ~/llama_train
scripts/base_eval.sh /home/pavlisd/exports/qwen38_rb1009s2_sftdpo rb1009s2 > logs/evals/rb1009s2_eval.log 2>&1
tail -n 1 logs/evals/rb1009s2_eval.log
echo "$(date '+%m-%d %H:%M') rb1009s2 done"
