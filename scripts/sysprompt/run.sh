#!/bin/bash -l
# Deployment-rules test on valprec2 (spec/valprec2_weaknesses.md): the rules in data/sysprompt/rules_v1.txt appended to the
# system prompt. Gap tests T57/T63/T67/T73 thinking on 3 x n10 and off 1 x n10 (baseline: results/validate_precision/gaps_valprec2.json),
# execution-scored; harness pool1_weak (syntax pitfalls + Rollup accumulator, 52 tasks) first attempts, 2 runs, both modes
# (baseline: results/agent_harness/valprec2_pool1_first_{off,on}.jsonl). Needs the rb1009 eval server on :3012 (logs/sysprompt/vllm_3012.sh).
# All streams run in parallel (vLLM batches them); test.py alone is one request at a time, ~10 min per thinking-on answer.
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/sysprompt; T=${TESTS:-T57,T63,T67,T73}
until curl -sf 127.0.0.1:3012/v1/models >/dev/null; do sleep 10; done
curl -sf -X POST 127.0.0.1:3012/v1/load_lora_adapter -H 'Content-Type: application/json' \
  -d "{\"lora_name\": \"valprec2\", \"lora_path\": \"$PWD/data/opcd/valprec2/round_155/adapter_vllm\"}" || echo "adapter load: already loaded or failed"
echo "$(date '+%m-%d %H:%M') start (parallel)"
for i in a b c; do
  ( $PY test.py configs/eval_sp_v5gaps_valprec2_rules_on.yaml --tests $T --runs 10 > $L/gaps_rules_on_$i.log 2>&1
    echo "$(date '+%m-%d %H:%M') on $i done: $(grep -c 'Verdict:' $L/gaps_rules_on_$i.log) verdicts" ) &
done
( $PY test.py configs/eval_sp_v5gaps_valprec2_rules_off.yaml --tests $T --runs 10 > $L/gaps_rules_off.log 2>&1
  echo "$(date '+%m-%d %H:%M') off done: $(grep -c 'Verdict:' $L/gaps_rules_off.log) verdicts" ) &
for m in off on; do
  ( $PY agent_harness.py run data/agent_harness/pool1_weak.jsonl --model valprec2 --url http://127.0.0.1:3012 --modes $m --runs 2 --rounds 0 \
      --concurrency 4 --system-extra data/sysprompt/rules_v1.txt --out results/agent_harness/valprec2_rules_pool1_weak_$m.jsonl > $L/harness_weak_$m.log 2>&1
    echo "$(date '+%m-%d %H:%M') harness $m done: $(wc -l < results/agent_harness/valprec2_rules_pool1_weak_$m.jsonl) records" ) &
done
wait
$PY data/suite_v5/exec_score.py $(ls results/results_qwen38_sp_v5gaps_valprec2_rules_o*_*.json) --out results/sysprompt/gaps_valprec2_rules.json > $L/exec_gaps_rules.log 2>&1
echo "$(date '+%m-%d %H:%M') exec scored"
echo "$(date '+%m-%d %H:%M') sysprompt test done"
