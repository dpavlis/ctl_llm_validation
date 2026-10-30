#!/bin/bash -l
# Agentic harness on the candidate (MODEL, default valprec2 = served adapter name): both thinking modes, pool1, 2 feedback rounds.
# Uses the shared eval server on :3012 (rb1009 base, adapter hot-loaded).
#   setsid nohup scripts/agent_harness_run.sh > logs/evals/agent_harness_valprec2.log 2>&1 &
#   MODEL=c13c reproduces the c13c runs.
#   POOL=pool_tweak RUNS=2 runs the fresh-domain pool (spec/harness_measurement_brief.md Part A).
cd ~/llama_train
M=${MODEL:-valprec2}
~/venv/bin/python agent_harness.py run data/agent_harness/${POOL:-pool1}.jsonl --model $M --url ${URL:-http://127.0.0.1:3012} \
  --modes off on --runs ${RUNS:-1} --rounds 2 --concurrency ${CONC:-4} --out results/agent_harness/${M}_${POOL:-pool1}.jsonl
