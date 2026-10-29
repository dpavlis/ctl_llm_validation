#!/bin/bash -l
# Sampler for the valprec OPCD runs (spec/validate_precision_brief.md): rb1009 base + hot-loaded adapters, GPU ${GPU:-3}, port ${PORT:-3011}.
# Served as rb1009_vp: scripts/harness_measurement/run_models.sh cleanup kills any server named rb1009.
export CUDA_HOME=/home/pavlisd/cuda-home PATH=/home/pavlisd/cuda-home/bin:$PATH
CU13=/home/pavlisd/vllm-venv/lib/python3.12/site-packages/nvidia/cu13
export LD_LIBRARY_PATH=$CU13/lib:$LD_LIBRARY_PATH LIBRARY_PATH=$CU13/lib/stubs:$LIBRARY_PATH
export CUDA_VISIBLE_DEVICES=${GPU:-3} OMP_NUM_THREADS=8 VLLM_ALLOW_RUNTIME_LORA_UPDATING=True
exec /home/pavlisd/vllm-venv/bin/python3 -m vllm.entrypoints.openai.api_server --host 127.0.0.1 --port ${PORT:-3011} \
  --model /home/pavlisd/exports/qwen38_rb1009_sftdpo --served-model-name rb1009_vp --dtype bfloat16 \
  --max-model-len 16384 --gpu-memory-utilization 0.90 --max-num-seqs 64 --enable-prefix-caching \
  --enable-lora --max-lora-rank 32 --max-loras 4
