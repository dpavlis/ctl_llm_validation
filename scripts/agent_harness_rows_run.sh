#!/bin/bash -l
# Agentic harness on c13c with --rows-feedback: the agent also sees the failing test output (ceiling for wrong-rows fixes).
#   URL=http://127.0.0.1:3011 setsid nohup scripts/agent_harness_rows_run.sh > logs/evals/agent_harness_c13c_rows.log 2>&1 &
cd ~/llama_train
~/venv/bin/python agent_harness.py run data/agent_harness/pool1.jsonl --model c13c --url ${URL:-http://127.0.0.1:3012} \
  --modes off on --runs 1 --rounds 2 --rows-feedback --concurrency ${CONC:-4} --out results/agent_harness/c13c_pool1_rows.jsonl
