#!/bin/bash -l
# Part A step 1, after the fixture-prompt fix: seeds 101-102 kept no Rollup task (every Rollup reference failed to
# compile), so the Rollup accumulator prompts get three more seeds with the fixed FIXTURE_SYSTEM. Waits for tweak_pool.sh.
#   setsid nohup scripts/harness_measurement/tweak_rollup.sh > logs/harness_measurement/tweak_rollup.log 2>&1 &
cd ~/llama_train
while pgrep -u $USER -f "harness_measurement/tweak_pool.sh" >/dev/null; do sleep 30; done
S=ctl_lora_training/sft_training_data
for seed in 103 104 105; do
  [ -f data/agent_harness/tweak/s${seed}r.report.json ] || ~/venv/bin/python agent_harness.py pool --seed $seed \
    --tweak-concurrency 8 --out data/agent_harness/tweak/s${seed}r.jsonl --tweak $S/CTL_LoRA_rollup_accumulator_sft.json
done
~/venv/bin/python scripts/harness_measurement/merge_pools.py
echo DONE
