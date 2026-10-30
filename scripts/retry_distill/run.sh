#!/bin/bash -l
# Retry-distill round 1 end to end (spec/retry_distill_brief.md): wait for the thinking-on re-sample (scripts/retry_distill_sample_on.sh,
# GPU 0), build the rows, prepare, set the round count so every exec row is drawn once, smoke (gradient norms per loss kind),
# then train retry1 on GPU $TRAIN_GPU with the sampler on :3011 (logs/retry_distill/vllm_3011.sh, GPU 1).
#   setsid nohup scripts/retry_distill/run.sh > logs/retry_distill/run.log 2>&1 &
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/retry_distill; TRAIN_GPU=${TRAIN_GPU:-0}
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
until grep -qE 'DONE|vLLM server died' logs/evals/retry_distill_sample_on.log 2>/dev/null; do sleep 120; done
grep -q DONE logs/evals/retry_distill_sample_on.log || { echo "thinking-on re-sample failed"; exit 1; }
echo "$(date '+%m-%d %H:%M') re-sample done: $(grep -c . results/agent_harness/c13c_pool_retry_on_think.jsonl) records"
$PY scripts/retry_distill/build_samples.py --pools data/agent_harness/pool_retry.jsonl data/agent_harness/pool_retry_tweak.jsonl \
  --off results/agent_harness/c13c_pool_retry_rows.jsonl results/agent_harness/c13c_pool_retry_tweak_rows.jsonl \
  --on results/agent_harness/c13c_pool_retry_on_think.jsonl --out data/retry_distill > $L/build_samples.log 2>&1 || { echo "build failed"; exit 1; }
grep -A3 '"stats"' $L/build_samples.log
[ -d data/opcd/retry1 ] && { echo "data/opcd/retry1 exists: refusing to resume"; exit 1; }
$PY opcd.py prepare --config configs/opcd_retry1.yaml > $L/prepare.log 2>&1 || { echo "prepare failed"; tail -5 $L/prepare.log; exit 1; }
tail -4 $L/prepare.log
# rounds: non-replay draws per round = prompts_per_round * (1 - replay_share); the exec share of them is exec weight / all
ROUNDS=$($PY - <<'PYEOF'
import json
rows=[json.loads(l) for l in open("data/opcd/retry1/prompts.jsonl")]
ex=sum(r.get("weight") or 1 for r in rows if r["set"]=="exec"); other=sum(r.get("weight") or 1 for r in rows if r["set"] not in ("exec","replay","probe"))
draws=32*(1-0.4)*ex/(ex+other)  # weights may be null
import math; print(math.ceil(ex/draws)); print(f"exec rows {ex}, other non-replay weight {other}, exec draws/round {draws:.1f}", file=__import__("sys").stderr)
PYEOF
)
sed -i "s/^  rounds: .*/  rounds: $ROUNDS                  # every exec row drawn once (run.sh)/" configs/opcd_retry1.yaml
echo "$(date '+%m-%d %H:%M') rounds = $ROUNDS"
curl -sf 127.0.0.1:3011/v1/models >/dev/null || { echo "no sampler on :3011"; exit 1; }
CUDA_VISIBLE_DEVICES=$TRAIN_GPU $PY -u opcd.py smoke --exec --config configs/opcd_retry1.yaml > $L/smoke.log 2>&1 || { echo "smoke failed"; tail -20 $L/smoke.log; exit 1; }
grep -iE "grad|norm|exec (nll|dpo|sft)" $L/smoke.log | tail -12
echo "$(date '+%m-%d %H:%M') retry1 train (GPU $TRAIN_GPU)"
CUDA_VISIBLE_DEVICES=$TRAIN_GPU $PY -u opcd.py train --config configs/opcd_retry1.yaml > $L/train_retry1.log 2>&1 || { echo "train failed"; tail -5 $L/train_retry1.log; exit 1; }
echo "$(date '+%m-%d %H:%M') train done"
