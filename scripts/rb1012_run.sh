#!/bin/bash -l
# rb1012 (seed 42) and rb1012s2 (seed 7): rb1011 recipe + Rollup lifecycle validate set + CTL2 syntax pitfalls set
# (configs/qwen38_rb1012{,s2}.yaml). SFT + DPO + export of both in parallel on two free GPUs (default 1 and 3; GPUS="a b"
# to override), then for each: the base gates (scripts/base_eval.sh) and execution scoring of its suite-v5 gap answers.
#   setsid nohup scripts/rb1012_run.sh > logs/rb1012_run.log 2>&1 &
cd /home/pavlisd/llama_train
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
K=logs/evals/locks; mkdir -p $K; ts() { date '+%m-%d %H:%M'; }
read -r G1 G2 <<< "${GPUS:-1 3}"
for g in $G1 $G2; do
  used=$(nvidia-smi -i $g --query-gpu=memory.used --format=csv,noheader,nounits)
  [ "$used" -lt 1000 ] || { echo "GPU $g is in use ($used MiB)"; exit 1; }
done
declare -A GPU=([rb1012]=$G1 [rb1012s2]=$G2)
for tag in rb1012 rb1012s2; do
  ( cd ~/LlamaFactory && echo "$(ts) $tag train (GPU ${GPU[$tag]})" && \
    flock /home/pavlisd/llama_train/$K/gpu${GPU[$tag]}.lock env CUDA_VISIBLE_DEVICES=${GPU[$tag]} ~/venv/bin/python ~/llama_train/train.py \
      ~/llama_train/configs/qwen38_$tag.yaml --skip-post-sft > ~/llama_train/logs/${tag}_train.log 2>&1 \
    && echo "$(ts) $tag trained" || echo "$(ts) $tag TRAIN FAILED" ) &
done
wait
for tag in rb1012 rb1012s2; do
  E=/home/pavlisd/exports/qwen38_${tag}_sftdpo
  [ -f $E/config.json ] || { echo "$(ts) no export for $tag, skipping its gates"; continue; }
  scripts/base_eval.sh $E $tag > logs/evals/${tag}_eval.log 2>&1
  tail -n 1 logs/evals/${tag}_eval.log
  ~/venv/bin/python data/suite_v5/exec_score.py $(ls results/results_qwen38_${tag}_v5gaps_o*_2*.json) \
    --out results/exec/exec_scores.json > logs/evals/${tag}_exec.log 2>&1
  echo "$(ts) $tag gates + exec scoring done"
done
echo "$(ts) rb1012 done"
