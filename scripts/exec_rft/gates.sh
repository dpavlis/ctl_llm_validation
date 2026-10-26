#!/bin/bash -l
# Exec-RFT pilot gates (spec/exec_rft_pilot_brief.md Step 4) for one adapter, on the vLLM path c13c was measured on:
# thinking ON on the eval server (:3012), thinking OFF on the sampler (:3011), both serving rb1009 with the adapter hot-loaded.
#   - suite v5 gap tests (11) n10, both modes, twice, then execution-scored (exec_score.py) — judge score from the same runs;
#   - held-out pool: 40 prompts x 8 samples, both modes (sample_score.py);
#   - T40/T42 n20 twice (on); T54 n20 (off); hard sets 1-3 (eval_hard_cases.py, k 4);
#   - full v4 n5 both modes (thinking-on validate/fix/generate) and thinking-off validate x9 (full n5 + 8 validate-only reps).
#   setsid nohup scripts/exec_rft/gates.sh RUN ROUND [TAG] > logs/exec_rft/gates_RUN.log 2>&1 &
#   RUN=c13c ROUND=015 gives the baseline's second gap-test run only (GATES=gaps); TAG names results (default RUN).
# Needs both servers up (scripts/vllm_eval_serve_rb1009.sh on GPU 1 :3012, logs/exec_rft/vllm_3011_rb1009.sh on GPU 3 :3011).
cd /home/pavlisd/llama_train
RUN=$1; R=$2; TAG=${3:-$1}; AD=${RUN}_r$R; [ "$RUN" = c13c ] && AD=c13c
GATES=${GATES:-gaps,holdout,belief,suite}
PY=~/venv/bin/python; L=logs/exec_rft
SUITE4=$PWD/results/eval_snapshot_20261003/ctl2_test_suite_v4.json; SUITE5=$PWD/results/eval_snapshot_20261013/ctl2_test_suite_v5.json
GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
export PATH=/home/pavlisd/venv/bin:$PATH
for p in 3011 3012; do curl -sf 127.0.0.1:$p/v1/models >/dev/null || { echo "no server on :$p"; exit 1; }
  curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$AD\", \"lora_path\": \"$PWD/data/opcd/$RUN/round_$R/adapter_vllm\"}" >/dev/null || echo "load $AD on :$p: already loaded or failed"; done
mk() {  # mk NAME MODE PORT SUITE
  sed -e "s/vllm_model: rb1006/vllm_model: $AD/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$3#; s/run_label: qwen38_rb1006_vllm_$2/run_label: qwen38_$1/" \
      -e "s#suite_file: .*#suite_file: $4#" -e "1s/.*/# $1 ($AD on vLLM :$3), thinking ${2^^} -- written by scripts\/exec_rft\/gates.sh./" \
      configs/eval_rb1006_vllm_$2.yaml > configs/eval_$1.yaml; }
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for m in on off; do port=3012; [ $m = off ] && port=3011
  mk rft_v5gaps_${TAG}_$m $m $port $SUITE5; mk rft_v4_${TAG}_$m $m $port $SUITE4; done
mk rft_t40t42_${TAG}_on on 3012 $SUITE4; mk rft_t54_${TAG}_off off 3011 $SUITE5   # own labels: kept apart from the gap / full runs
ON=(); OFF=()
if [[ $GATES == *gaps* ]]; then
  ON+=("t rft_v5gaps_${TAG}_on_a configs/eval_rft_v5gaps_${TAG}_on.yaml --tests $GAPS --runs 10"
       "t rft_v5gaps_${TAG}_on_b configs/eval_rft_v5gaps_${TAG}_on.yaml --tests $GAPS --runs 10")
  OFF+=("t rft_v5gaps_${TAG}_off_a configs/eval_rft_v5gaps_${TAG}_off.yaml --tests $GAPS --runs 10"
        "t rft_v5gaps_${TAG}_off_b configs/eval_rft_v5gaps_${TAG}_off.yaml --tests $GAPS --runs 10"); fi
if [[ $GATES == *belief* ]]; then
  ON+=("t rft_t40t42_${TAG}_a configs/eval_rft_t40t42_${TAG}_on.yaml --tests T40,T42 --runs 20"
       "t rft_t40t42_${TAG}_b configs/eval_rft_t40t42_${TAG}_on.yaml --tests T40,T42 --runs 20")
  OFF+=("t rft_t54_${TAG}_off configs/eval_rft_t54_${TAG}_off.yaml --tests T54 --runs 20"); fi
if [[ $GATES == *suite* ]]; then
  ON+=("t rft_v4_${TAG}_on_full_n5 configs/eval_rft_v4_${TAG}_on.yaml --runs 5")
  OFF+=("t rft_v4_${TAG}_off_full_n5 configs/eval_rft_v4_${TAG}_off.yaml --runs 5")
  for r in 2 3 4 5 6 7 8 9; do OFF+=("t rft_v4_${TAG}_off_validate_rep$r configs/eval_rft_v4_${TAG}_off.yaml --validate-only --runs 5"); done; fi
( for c in "${ON[@]}"; do eval "$c"; done ) &
( for c in "${OFF[@]}"; do eval "$c"; done ) &
if [[ $GATES == *belief* ]]; then
  ( for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
      CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${TAG}_set$s --file $f $TAG=$AD:student --k 4 --config configs/opcd_exec_rft1.yaml > $L/hard_eval_${TAG}_set$s.log 2>&1; done
    echo "$(date '+%m-%d %H:%M') hard-case evals done" ) &
fi
if [[ $GATES == *holdout* ]]; then
  ( for m in off on; do CUDA_VISIBLE_DEVICES="" $PY -u scripts/exec_rft/sample_score.py --mode $m --adapter $AD --tag $TAG --concurrency 8 \
      --prompts data/exec_rft/holdout.jsonl --out results/exec_rft/holdout_${TAG}_$m.jsonl > $L/holdout_${TAG}_$m.log 2>&1; done
    echo "$(date '+%m-%d %H:%M') holdout sampling done" ) &
fi
wait
if [[ $GATES == *gaps* ]]; then
  $PY data/suite_v5/exec_score.py $(ls results/results_qwen38_rft_v5gaps_${TAG}_o*_*.json) --out results/exec_rft/gaps_${TAG}.json > $L/exec_gaps_${TAG}.log 2>&1
  [[ $GATES == *belief* ]] && $PY data/suite_v5/exec_score.py $(ls results/results_qwen38_rft_t54_${TAG}_off*.json 2>/dev/null) --out results/exec_rft/t54_${TAG}.json >> $L/exec_gaps_${TAG}.log 2>&1
fi
echo "$(date '+%m-%d %H:%M') $TAG gates done"
