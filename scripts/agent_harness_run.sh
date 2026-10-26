#!/bin/bash -l
# Agentic harness on c13c: both thinking modes, pool1, 2 feedback rounds. Uses the shared eval server on :3012.
#   setsid nohup scripts/agent_harness_run.sh > logs/evals/agent_harness_c13c.log 2>&1 &
cd ~/llama_train
~/venv/bin/python agent_harness.py run data/agent_harness/pool1.jsonl --model c13c --url ${URL:-http://127.0.0.1:3012} \
  --modes off on --runs ${RUNS:-1} --rounds 2 --concurrency ${CONC:-4} --out results/agent_harness/c13c_pool1.jsonl
