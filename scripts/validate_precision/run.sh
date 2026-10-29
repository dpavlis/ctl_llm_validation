#!/bin/bash -l
# valprec1 / valprec2 end to end (spec/validate_precision_brief.md, _precision2_brief.md; RUN=valprec2 LAST=155): train on GPU 1 (sampler :3011 on GPU 3 serving rb1009_vp,
# scripts/validate_precision/vllm_sampler_3011.sh), then the eval server on GPU 1 (:3012, served rb1009_vpe) and the gates.
#   setsid nohup scripts/validate_precision/run.sh > logs/validate_precision/run.log 2>&1 &
#   RUN=valprec2 LAST=155 setsid nohup scripts/validate_precision/run.sh > logs/validate_precision/run_valprec2.log 2>&1 &
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/validate_precision; RUN=${RUN:-valprec1}; LAST=${LAST:-122}
TGPU=${TGPU:-1}; SPORT=${SPORT:-3011}   # training / eval-server GPU and sampler port (valprec2: TGPU=2 SPORT=3013)
export PATH=/home/pavlisd/venv/bin:$PATH TMPDIR=/home/pavlisd/venv-ds-tmp
curl -sf 127.0.0.1:$SPORT/v1/models >/dev/null || { echo "no sampler on :$SPORT"; exit 1; }
echo "$(date '+%m-%d %H:%M') $RUN train (GPU $TGPU)"
CUDA_VISIBLE_DEVICES=$TGPU $PY -u opcd.py train --config configs/opcd_$RUN.yaml > $L/train_$RUN.log 2>&1 || { echo "train failed"; exit 1; }
echo "$(date '+%m-%d %H:%M') train done"
sed -e 's/--served-model-name rb1009 /--served-model-name rb1009_vpe /' -e "s/CUDA_VISIBLE_DEVICES=1 /CUDA_VISIBLE_DEVICES=$TGPU /" scripts/vllm_eval_serve_rb1009.sh > $L/vllm_3012.sh
setsid nohup bash $L/vllm_3012.sh > $L/vllm_3012.log 2>&1 < /dev/null & disown
until curl -sf 127.0.0.1:3012/v1/models >/dev/null; do sleep 10; done
SPORT=$SPORT scripts/validate_precision/gates.sh $RUN $LAST
echo "$(date '+%m-%d %H:%M') all done"
