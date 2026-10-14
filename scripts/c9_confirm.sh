#!/bin/bash -l
# c9 confirmation reruns, thinking ON, n10: suite v5 T57/T61 and the three G4 holdout prompts; c4 on :3011, c9 on :3012.
cd /home/pavlisd/llama_train
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" ~/venv/bin/python -u test.py "$@" --workers 32 > logs/evals/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for n in c4 c9; do ( t confirm_v5_${n}_on configs/eval_confirm_v5_${n}_on.yaml --tests T57,T61 --runs 10
                     t confirm_ho_${n}_on configs/eval_confirm_ho_${n}_on.yaml --tests G4_03,G4_09,G4_15 --runs 10 ) & done
wait; echo "$(date '+%m-%d %H:%M') confirm all done"
