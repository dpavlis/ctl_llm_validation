#!/bin/bash -l
# Part A step 1 (spec/harness_measurement_brief.md): the fresh-domain pool. Every generate prompt of the six corpus sets
# with runtime harnesses is rewritten once per seed (agent_harness.py pool --tweak); seeds continue until the merged pool
# has >= TARGET tasks. Per-seed pools in data/agent_harness/tweak/, merged into data/agent_harness/pool_tweak.jsonl.
#   setsid nohup scripts/harness_measurement/tweak_pool.sh > logs/harness_measurement/tweak_pool.log 2>&1 &
cd ~/llama_train
S=ctl_lora_training/sft_training_data
TARGET=${TARGET:-130}
for seed in ${SEEDS:-101 102 103 104 105 106}; do
  out=data/agent_harness/tweak/s$seed.jsonl
  if [ ! -f ${out%.jsonl}.report.json ]; then
    ~/venv/bin/python agent_harness.py pool --seed $seed --tweak-concurrency ${CONC:-8} --out $out --tweak \
      $S/CTL_LoRA_scd2_sft.json $S/CTL_LoRA_syntax_pitfalls_sft.json $S/CTL_LoRA_rollup_accumulator_sft.json \
      $S/CTL_LoRA_normalizer_multirow_sft.json $S/CTL_LoRA_dataintersection_sft.json $S/CTL_LoRA_zerodate_sft.json
  fi
  n=$(~/venv/bin/python scripts/harness_measurement/merge_pools.py | ~/venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['tasks'])")
  echo "after seed $seed: $n tasks"
  [ "$n" -ge "$TARGET" ] && break
done
echo DONE
