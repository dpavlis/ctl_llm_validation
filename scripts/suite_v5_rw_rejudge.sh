#!/bin/bash -l
# Re-judge the six suite v5 rw runs against resources/ctl2_test_suite_v5.json (rubric fixes of 2026-10-13, ctl2-basics §8.9).
cd /home/pavlisd/llama_train
for f in $(ls results/results_qwen38_v5rw_*Z.json); do
  ~/venv/bin/python -u data/rejudge_results.py $f resources/ctl2_test_suite_v5.json configs/eval_v5rw_rb1006_on.yaml --workers 16
done
