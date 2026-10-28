#!/bin/bash -l
# valprec1 smoke (GPU 1): c13c's adapter, target fix/validate + replay generate + one clean and one planted review prompt;
# repeated steps on one batch, the KL must fall. Prints what the student and the teacher see.
#   setsid nohup scripts/validate_precision/smoke.sh > logs/validate_precision/smoke.log 2>&1 &
cd /home/pavlisd/llama_train
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
CUDA_VISIBLE_DEVICES=${GPU:-1} ~/venv/bin/python -u opcd.py smoke --config configs/opcd_valprec1.yaml --review --steps 4 --max-new 3072
echo "$(date) DONE"
