#!/bin/bash -l
# B1-tweak: the planted-defect validate set re-derived from the pool_tweak references (spec/harness_measurement_findings.md
# caveat: B1 comes from pool-1 references, 27 of its 30 lifecycle mutants from the Rollup-accumulator set that rb1011/rb1012
# saw in SFT and c13c did not). Nobody trained on pool_tweak, so this set compares models without that confound.
#   setsid nohup scripts/harness_measurement/make_mutants_tweak.sh > logs/harness_measurement/make_mutants_tweak.log 2>&1 &
cd ~/llama_train
~/venv/bin/python -u scripts/harness_measurement/make_mutants.py --pool data/agent_harness/pool_tweak.jsonl \
  --out data/agent_harness/validate_mutants_tweak.jsonl --seed 12 --per-kind 30 --controls 50 --workers 4
echo "$(date) DONE"
