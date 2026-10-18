#!/bin/bash -l
# spec/belief_durability_plan.md Part B, end to end on GPUs 1 and 3 (0 and 2 are another user's):
#   1. prompt pools: c13c_belief (arm a) and c13c_gaps (the extra run of arm b)
#   2. c13c samples on two rb1009 vLLM servers in parallel (:3011 GPU 3, :3012 GPU 1); servers stopped afterwards
#   3. self_distill filter (compile via ctl_validate MCP, reference judge, claims audit, beliefs) + assemble, both runs
#   4. rebuilds rb1010a (+ belief traces) and rb1010b (+ belief + gap/DI traces) in parallel, GPU 1 and GPU 3
#   5. gates for each arm (scripts/base_eval.sh), one after the other
#   setsid nohup scripts/partb_run.sh > logs/partb_run.log 2>&1 &
set -uo pipefail
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals; K=$L/locks; mkdir -p $K
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
ts() { date '+%m-%d %H:%M'; }
ADAPTER=data/opcd/c13c/round_015/adapter_vllm
EXCL="CTL_LoRA_fix_defaults_explained.json CTL_LoRA_declaration_defaults_contrast.json"

echo "$(ts) 1. prompt pools"
$PY data/build_belief_traces.py select --run c13c_belief > $L/partb_select_belief.log 2>&1 || { echo "select belief failed"; exit 1; }
$PY data/build_belief_traces.py select --run c13c_gaps --gaps-only > $L/partb_select_gaps.log 2>&1 || { echo "select gaps failed"; exit 1; }

echo "$(ts) 2. sampling c13c"
setsid nohup bash $L/vllm_3011_rb1009.sh > $L/vllm_3011_rb1009.log 2>&1 < /dev/null & disown
setsid nohup bash scripts/vllm_eval_serve_rb1009.sh > $L/vllm_3012_rb1009.log 2>&1 < /dev/null & disown
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models | grep -q '"rb1009"'; do sleep 10; done; done
( $PY data/build_belief_traces.py sample --run c13c_belief --adapter $ADAPTER --url http://127.0.0.1:3011 > $L/partb_sample_belief.log 2>&1 ) &
( $PY data/build_belief_traces.py sample --run c13c_gaps --adapter $ADAPTER --url http://127.0.0.1:3012 > $L/partb_sample_gaps.log 2>&1 ) &
wait
P=$(ps -u pavlisd -o pid=,args= | awk '$2 ~ /python3$/ && /vllm.entrypoints.openai.api_server/ && /served-model-name rb1009/ {print $1}'); [ -n "$P" ] && kill $P
tail -n 1 $L/partb_sample_belief.log $L/partb_sample_gaps.log

echo "$(ts) 3. filter + assemble"
for run in c13c_belief c13c_gaps; do
  $PY self_distill.py filter --run $run --eval-config configs/eval_rb1006_vllm_on.yaml --judge-workers 12 > $L/partb_filter_$run.log 2>&1 \
    || { echo "filter $run failed (see $L/partb_filter_$run.log; rerun resumes)"; exit 1; }
  $PY self_distill.py assemble --run $run --cutoff 4096 > $L/partb_assemble_$run.log 2>&1 || { echo "assemble $run failed"; exit 1; }
  tail -n 3 $L/partb_filter_$run.log | head -1; grep -iE "kept|accepted" $L/partb_assemble_$run.log | tail -2
done

echo "$(ts) 4. rebuilds"
until [ "$(nvidia-smi -i 1 --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 1000 ] && \
      [ "$(nvidia-smi -i 3 --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 1000 ]; do sleep 10; done
declare -A SDARGS=([rb1010a]="--sd=c13c_belief:1" [rb1010b]="--sd=c13c_belief:1 --sd=c13c_gaps:1")
declare -A GPU=([rb1010a]=1 [rb1010b]=3)
for tag in rb1010a rb1010b; do
  D=data/sft_rebuild_20261018_$tag
  PYTHONPATH=~/LlamaFactory/src $PY data/build_sft_rebuild.py $tag $D $EXCL ${SDARGS[$tag]} > $L/partb_build_$tag.log 2>&1 || { echo "build $tag failed"; exit 1; }
  tail -n 1 $L/partb_build_$tag.log
  $PY - "$tag" <<'PYEOF'
import json, sys
tag = sys.argv[1]; p = '/home/pavlisd/LlamaFactory/data/dataset_info.json'; d = json.load(open(p))
for k in [k for k in list(d) if k.endswith('rb1009')]:
    d[k.replace('rb1009', tag)] = json.loads(json.dumps(d[k]).replace('rb1009', tag))
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
PYEOF
  cp $D/*$tag* ~/LlamaFactory/data/
  { echo "# $tag: rb1009 recipe (corpus d80aaa5, same exclusions) + ${SDARGS[$tag]} -- spec/belief_durability_plan.md Part B; written by scripts/partb_run.sh"
    sed -n '/^# LlamaFactory SFT/,$p' configs/qwen38_rb1009.yaml | sed "s/rb1009/$tag/g"; } > configs/qwen38_$tag.yaml
done
for tag in rb1010a rb1010b; do
  ( cd ~/LlamaFactory && flock $K/gpu${GPU[$tag]}.lock env CUDA_VISIBLE_DEVICES=${GPU[$tag]} $PY ~/llama_train/train.py \
      ~/llama_train/configs/qwen38_$tag.yaml --skip-post-sft > ~/llama_train/logs/${tag}_train.log 2>&1 \
      && echo "$(ts) $tag trained" || echo "$(ts) $tag TRAIN FAILED" ) &
done
wait

echo "$(ts) 5. gates"
for tag in rb1010a rb1010b; do
  [ -f /home/pavlisd/exports/qwen38_${tag}_sftdpo/config.json ] || { echo "no export for $tag, skipping its gates"; continue; }
  scripts/base_eval.sh /home/pavlisd/exports/qwen38_${tag}_sftdpo $tag > $L/${tag}_eval.log 2>&1
  tail -n 1 $L/${tag}_eval.log
done
echo "$(ts) Part B done"
