#!/bin/bash -l
# Suite v5 real-world generate tests (T44-T73), n5: rb1006, OPCD c4 (c4_r015) and c7 (c7_r039), thinking ON and OFF.
# Queues: :3012 (GPU 1) rb1006 on, c4 on; :3011 (GPU 3) the three OFF runs, then c7 on.
# Needs scripts/vllm_eval_serve.sh (:3012) and logs/evals/opcd_vllm_serve.sh (:3011) up.
#   [TESTS=T44,T46 RUNS=10] setsid nohup scripts/suite_v5_rw_run.sh [ROUND] > logs/evals/suite_v5_rw_run.log 2>&1 &
#   (ROUND tag, default v5rw; TESTS default T44-T73, RUNS default 5)
cd /home/pavlisd/llama_train
R=${1:-v5rw}; PY=~/venv/bin/python; L=logs/evals; SUITE=$PWD/resources/ctl2_test_suite_v5.json
TESTS=${TESTS:-$(seq -s, -f "T%g" 44 73)}; RUNS=${RUNS:-5}
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models >/dev/null; do sleep 10; done
  for a in c4_r015 c7_r039; do r=${a%%_*}; curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$a\", \"lora_path\": \"$PWD/data/opcd/$r/round_${a#*_r}/adapter_vllm\"}" >/dev/null || echo "load $a on :$p failed"; done; done
cfg() {  # cfg MODEL_ADAPTER MODE PORT -> configs/eval_${R}_<n>_<mode>.yaml
  local ad=$1 m=$2 port=$3 n=${1%%_*}
  sed -e "s/vllm_model: rb1006/vllm_model: $ad/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$port#" \
      -e "s/run_label: qwen38_rb1006_vllm_$m/run_label: qwen38_${R}_${n}_$m/" \
      -e "s#suite_file: .*#suite_file: $SUITE#" \
      -e "1s/.*/# Suite v5 rw tests ($R): $n ($ad on vLLM :$port), thinking ${m^^} -- written by scripts\/suite_v5_rw_run.sh./" \
      configs/eval_rb1006_vllm_$m.yaml > configs/eval_${R}_${n}_$m.yaml; }
t() {  # t MODEL_ADAPTER MODE PORT
  local n=${1%%_*} s=$(date +%s); cfg "$@"
  CUDA_VISIBLE_DEVICES="" $PY -u test.py configs/eval_${R}_${n}_$2.yaml --tests $TESTS --runs $RUNS --workers 32 > $L/${R}_${n}_$2.log 2>&1
  echo "$(date '+%m-%d %H:%M') $R $n $2 done ($(( ($(date +%s)-s)/60 )) min): $(grep -h 'Generate (rw)' $L/${R}_${n}_$2.log | tail -1 | sed 's/.*Generate (rw): //')"; }
( t rb1006 on 3012; t c4_r015 on 3012 ) &
( t rb1006 off 3011; t c4_r015 off 3011; t c7_r039 off 3011; t c7_r039 on 3011 ) &
wait
