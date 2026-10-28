#!/bin/bash -l
# Review prompts for the validate-precision OPCD run (spec/validate_precision_brief.md, Data 1-2): every exec-RFT pool
# reference whose hash is not a pool-1 (B1) reference, unchanged (clean) and with every server-confirmed planted defect.
# Seed 13 (B1: 11, B1-tweak: 12). The exec-RFT holdout is not read.
#   setsid nohup scripts/validate_precision/make_review_set.sh > logs/validate_precision/make_review_set.log 2>&1 &
cd ~/llama_train
~/venv/bin/python -u scripts/harness_measurement/make_mutants.py --exec-rft --pool data/exec_rft/pool.jsonl \
  --exclude data/agent_harness/pool1.jsonl --out data/validate_precision/review_mutants.jsonl --seed 13 \
  --per-kind 0 --controls -1 --workers 4
echo "$(date) DONE"
