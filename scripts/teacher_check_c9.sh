#!/bin/bash -l
# Teacher check for the c9 OPCD teacher (rb1006 + rulev3 + guide + §13.3) on the 36 teacher-check prompts, 4 runs, both modes.
cd /home/pavlisd/llama_train
for m in on off; do ( s=$(date +%s); CUDA_VISIBLE_DEVICES="" ~/venv/bin/python -u test.py configs/eval_tcheck_rb1006_ruleguide_$m.yaml --runs 4 --workers 32 > logs/evals/tcheck_rb1006_ruleguide_$m.log 2>&1
  echo "$(date '+%m-%d %H:%M') tcheck ruleguide $m done ($(( ($(date +%s)-s)/60 )) min)" ) & done; wait
