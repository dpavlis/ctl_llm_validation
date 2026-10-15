#!/bin/bash -l
# rb1009 base rebuild (configs/qwen38_rb1009.yaml): SFT + DPO + export on GPU 1 (GPUs 0 and 2 are another user's).
#   setsid nohup scripts/rb1009_run.sh > logs/rb1009_train.log 2>&1 &
cd ~/LlamaFactory
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
echo "$(date '+%m-%d %H:%M') rb1009 start (GPU 1)"
flock /home/pavlisd/llama_train/logs/evals/locks/gpu1.lock env CUDA_VISIBLE_DEVICES=1 ~/venv/bin/python ~/llama_train/train.py \
  ~/llama_train/configs/qwen38_rb1009.yaml --skip-post-sft || { echo "$(date '+%m-%d %H:%M') rb1009 FAILED"; exit 1; }
echo "$(date '+%m-%d %H:%M') rb1009 done"
