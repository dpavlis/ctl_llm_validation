#!/bin/bash -l
# Suite v5 real-world generate tests (T44-T73), n5, thinking ON on :3012 (GPU 1) and OFF on :3011 (GPU 3):
# rb1006, OPCD c4 (c4_r015) and c7 (c7_r039). Needs scripts/vllm_eval_serve.sh and logs/evals/opcd_vllm_serve.sh up.
#   setsid nohup scripts/suite_v5_rw_run.sh > logs/evals/suite_v5_rw_run.log 2>&1 &
cd /home/pavlisd/llama_train
PY=~/venv/bin/python; L=logs/evals; SUITE=$PWD/resources/ctl2_test_suite_v5.json
TESTS=$(seq -s, -f "T%g" 44 73)
for p in 3011 3012; do until curl -sf 127.0.0.1:$p/v1/models >/dev/null; do sleep 10; done
  for a in c4_r015 c7_r039; do r=${a%%_*}; curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$a\", \"lora_path\": \"$PWD/data/opcd/$r/round_${a#*_r}/adapter_vllm\"}" >/dev/null || echo "load $a on :$p failed"; done; done
for m in on off; do port=3011; [ $m = on ] && port=3012
  for ad in rb1006 c4_r015 c7_r039; do n=${ad%%_*}
    sed -e "s/vllm_model: rb1006/vllm_model: $ad/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$port#" \
        -e "s/run_label: qwen38_rb1006_vllm_$m/run_label: qwen38_v5rw_${n}_$m/" \
        -e "s#suite_file: .*#suite_file: $SUITE#" \
        -e "1s/.*/# Suite v5 rw tests: $n ($ad on vLLM :$port), thinking ${m^^} -- written by scripts\/suite_v5_rw_run.sh./" \
        configs/eval_rb1006_vllm_$m.yaml > configs/eval_v5rw_${n}_$m.yaml
  done
  ( for n in rb1006 c4 c7; do s=$(date +%s)
      CUDA_VISIBLE_DEVICES="" $PY -u test.py configs/eval_v5rw_${n}_$m.yaml --tests $TESTS --runs 5 --workers 32 > $L/v5rw_${n}_$m.log 2>&1
      echo "$(date '+%m-%d %H:%M') v5rw $n $m done ($(( ($(date +%s)-s)/60 )) min)"; done ) &
done
wait
