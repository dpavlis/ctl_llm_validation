#!/bin/bash -l
# Part B resume (steps 3-5 of scripts/partb_run.sh), after its assemble step stopped on 2026-10-18: one belief prompt had
# all 4 samples dropped by the pre-scan, so assemble now runs with --allow-incomplete (such prompts are dropped by design).
# Filter resumes from judged.jsonl. Original header:
# spec/belief_durability_plan.md Part B, end to end on GPUs 1 and 3 (0 and 2 are another user's):
#   1. prompt pools: c13c_belief (arm a) and c13c_gaps (the extra run of arm b)
#   2. c13c samples on two rb1009 vLLM servers in parallel (:3011 GPU 3, :3012 GPU 1); servers stopped afterwards
#   3. self_distill filter (compile via ctl_validate MCP, reference judge, claims audit, beliefs) + assemble, both runs
#   4. rebuilds rb1010a (+ belief traces) and rb1010b (+ belief + gap/DI traces) in parallel, GPU 1 and GPU 3
#   5. gates for each arm (scripts/base_eval.sh), one after the other
#   setsid nohup scripts/partb_resume.sh > logs/partb_resume.log 2>&1 &
set -uo pipefail
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals; K=/home/pavlisd/llama_train/logs/evals/locks; mkdir -p $K   # absolute: step 4 runs from ~/LlamaFactory
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
ts() { date '+%m-%d %H:%M'; }
ADAPTER=data/opcd/c13c/round_015/adapter_vllm
EXCL="CTL_LoRA_fix_defaults_explained.json CTL_LoRA_declaration_defaults_contrast.json CTL_LoRA_rollup_accumulator_sft.json CTL_LoRA_DPO_rollup_accumulator.jsonl CTL_LoRA_normalizer_multirow_sft.json CTL_LoRA_DPO_normalizer_multirow.jsonl"   # rb1009 corpus exactly: the Rollup/Normalizer sets (e12bc6c, under revision) stay out so the arms differ from rb1009 only by the traces

# step 3 (filter + assemble) completed 2026-10-18 12:36: c13c_belief 274 traces, c13c_gaps 44
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
