#!/bin/bash -l
# valprec1 gates (spec/validate_precision_brief.md, Gates) for one adapter, on the vLLM path c13c was measured on: thinking ON on
# the eval server (:3012, GPU 1), thinking OFF on the sampler (:3011, GPU 3), both serving rb1009 with the adapter hot-loaded.
#   - validate ground truth (no judge): B1 and B1-tweak, --format, both modes, 2 runs; B1 plain (no format), 2 runs, thinking off
#     (and thinking on for valprec2+: PLAIN_MODES="off on"); scored against c13c and, with CMP=valprec1, against valprec1 too;
#   - suite v5 gap tests (11) n10 x 3, both modes, execution-scored (exec_score.py);
#   - agentic harness pool 1, first attempt only (--rounds 0), --runs 2, both modes;
#   - T40/T42 n20 x 2 (on); T54 n20 (off); hard sets 1-3 (eval_hard_cases.py, k 4);
#   - full v4 n5 both modes and thinking-off validate x9 (judge regression check).
#   setsid nohup scripts/validate_precision/gates.sh valprec1 ROUND > logs/validate_precision/gates_valprec1.log 2>&1 &
#   GATES selects (default gt,gaps,harness,belief,suite).
cd /home/pavlisd/llama_train
RUN=$1; R=$2; TAG=${3:-$1}; AD=${RUN}_r$R
GATES=${GATES:-gt,gaps,harness,belief,suite}
PY=~/venv/bin/python; L=logs/validate_precision; RA=results/agent_harness
SP=${SPORT:-3011}; PLAIN_MODES=${PLAIN_MODES:-off}; CMP=${CMP:-}   # valprec2: PLAIN_MODES="off on" CMP=valprec1
SUITE4=$PWD/results/eval_snapshot_20261003/ctl2_test_suite_v4.json; SUITE5=$PWD/results/eval_snapshot_20261013/ctl2_test_suite_v5.json
GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
export PATH=/home/pavlisd/venv/bin:$PATH
for p in $SP 3012; do curl -sf 127.0.0.1:$p/v1/models >/dev/null || { echo "no server on :$p"; exit 1; }
  curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$AD\", \"lora_path\": \"$PWD/data/opcd/$RUN/round_$R/adapter_vllm\"}" >/dev/null || echo "load $AD on :$p: already loaded or failed"; done
mk() {  # mk NAME MODE PORT SUITE
  sed -e "s/vllm_model: rb1006/vllm_model: $AD/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$3#; s/run_label: qwen38_rb1006_vllm_$2/run_label: qwen38_$1/" \
      -e "s#suite_file: .*#suite_file: $4#" -e "1s/.*/# $1 ($AD on vLLM :$3), thinking ${2^^} -- written by scripts\/validate_precision\/gates.sh./" \
      configs/eval_rb1006_vllm_$2.yaml > configs/eval_$1.yaml; }
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(date '+%m-%d %H:%M') $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for m in on off; do port=3012; [ $m = off ] && port=$SP
  mk vp_v5gaps_${TAG}_$m $m $port $SUITE5; mk vp_v4_${TAG}_$m $m $port $SUITE4; done
mk vp_t40t42_${TAG}_on on 3012 $SUITE4; mk vp_t54_${TAG}_off off $SP $SUITE5
ON=(); OFF=()
if [[ $GATES == *gaps* ]]; then
  for x in a b c; do
    ON+=("t vp_v5gaps_${TAG}_on_$x configs/eval_vp_v5gaps_${TAG}_on.yaml --tests $GAPS --runs 10")
    OFF+=("t vp_v5gaps_${TAG}_off_$x configs/eval_vp_v5gaps_${TAG}_off.yaml --tests $GAPS --runs 10"); done; fi
if [[ $GATES == *belief* ]]; then
  ON+=("t vp_t40t42_${TAG}_a configs/eval_vp_t40t42_${TAG}_on.yaml --tests T40,T42 --runs 20"
       "t vp_t40t42_${TAG}_b configs/eval_vp_t40t42_${TAG}_on.yaml --tests T40,T42 --runs 20")
  OFF+=("t vp_t54_${TAG}_off configs/eval_vp_t54_${TAG}_off.yaml --tests T54 --runs 20"); fi
if [[ $GATES == *suite* ]]; then
  ON+=("t vp_v4_${TAG}_on_full_n5 configs/eval_vp_v4_${TAG}_on.yaml --runs 5")
  OFF+=("t vp_v4_${TAG}_off_full_n5 configs/eval_vp_v4_${TAG}_off.yaml --runs 5")
  for r in 2 3 4 5 6 7 8 9; do OFF+=("t vp_v4_${TAG}_off_validate_rep$r configs/eval_vp_v4_${TAG}_off.yaml --validate-only --runs 5"); done; fi
( for c in "${ON[@]}"; do eval "$c"; done ) &
( for c in "${OFF[@]}"; do eval "$c"; done ) &
if [[ $GATES == *gt* ]]; then   # one gen_answers per mode, each on its own server
  ( for m in off on; do port=$SP; [ $m = on ] && port=3012
      $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak.jsonl --model $AD --url http://127.0.0.1:$port \
        --modes $m --runs 2 --format --out $RA/validate_gt_tweak_${TAG}_fmt.jsonl > $L/gen_tweak_${TAG}_fmt_$m.log 2>&1 &
      $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants.jsonl --model $AD --url http://127.0.0.1:$port \
        --modes $m --runs 2 --format --out $RA/validate_gt_${TAG}_fmt_$m.jsonl > $L/gen_b1_${TAG}_fmt_$m.log 2>&1 &
    done
    for m in $PLAIN_MODES; do port=$SP; [ $m = on ] && port=3012
      $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants.jsonl --model $AD --url http://127.0.0.1:$port \
        --modes $m --runs 2 --out $RA/validate_gt_${TAG}_plain_$m.jsonl > $L/gen_b1_${TAG}_plain_$m.log 2>&1 &
    done
    wait
    cat $RA/validate_gt_${TAG}_fmt_off.jsonl $RA/validate_gt_${TAG}_fmt_on.jsonl > $RA/validate_gt_${TAG}_fmt.jsonl
    cat $(for m in $PLAIN_MODES; do echo $RA/validate_gt_${TAG}_plain_$m.jsonl; done) > $RA/validate_gt_${TAG}.jsonl
    echo "$(date '+%m-%d %H:%M') validate ground-truth answers done" ) &
fi
if [[ $GATES == *harness* ]]; then
  ( $PY -u agent_harness.py run data/agent_harness/pool1.jsonl --model $AD --url http://127.0.0.1:3012 --modes on --runs 2 --rounds 0 \
      --concurrency 4 --out $RA/${TAG}_pool1_first_on.jsonl > $L/harness_${TAG}_on.log 2>&1 &
    $PY -u agent_harness.py run data/agent_harness/pool1.jsonl --model $AD --url http://127.0.0.1:$SP --modes off --runs 2 --rounds 0 \
      --concurrency 4 --out $RA/${TAG}_pool1_first_off.jsonl > $L/harness_${TAG}_off.log 2>&1 &
    wait; echo "$(date '+%m-%d %H:%M') harness done" ) &
fi
if [[ $GATES == *belief* ]]; then
  ( for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
      CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${TAG}_set$s --file $f $TAG=$AD:student --k 4 --config configs/opcd_$RUN.yaml > $L/hard_eval_${TAG}_set$s.log 2>&1; done
    echo "$(date '+%m-%d %H:%M') hard-case evals done" ) &
fi
wait
if [[ $GATES == *gaps* ]]; then
  $PY data/suite_v5/exec_score.py $(ls results/results_qwen38_vp_v5gaps_${TAG}_o*_*.json) --out results/validate_precision/gaps_${TAG}.json > $L/exec_gaps_${TAG}.log 2>&1
  [[ $GATES == *belief* ]] && $PY data/suite_v5/exec_score.py $(ls results/results_qwen38_vp_t54_${TAG}_off*.json 2>/dev/null) --out results/validate_precision/t54_${TAG}.json >> $L/exec_gaps_${TAG}.log 2>&1
fi
if [[ $GATES == *gt* ]]; then
  $PY scripts/harness_measurement/score_validate.py tweak_c13c_fmt tweak_${TAG}_fmt --records data/agent_harness/validate_mutants_tweak.jsonl --diff tweak_${TAG}_fmt:tweak_c13c_fmt \
      --out results/validate_precision/gt_tweak_${TAG}_fmt.md > /dev/null
  $PY scripts/harness_measurement/score_validate.py c13c_fmt ${TAG}_fmt --records data/agent_harness/validate_mutants.jsonl --diff ${TAG}_fmt:c13c_fmt \
      --out results/validate_precision/gt_b1_${TAG}_fmt.md > /dev/null
  $PY scripts/harness_measurement/score_validate.py c13c ${TAG} --records data/agent_harness/validate_mutants.jsonl --diff ${TAG}:c13c \
      --out results/validate_precision/gt_b1_${TAG}_plain.md > /dev/null
  if [ -n "$CMP" ]; then   # the same three tables with the previous round as a third model
    $PY scripts/harness_measurement/score_validate.py tweak_c13c_fmt tweak_${CMP}_fmt tweak_${TAG}_fmt --records data/agent_harness/validate_mutants_tweak.jsonl \
        --diff tweak_${TAG}_fmt:tweak_c13c_fmt tweak_${TAG}_fmt:tweak_${CMP}_fmt --out results/validate_precision/gt_tweak_${TAG}_vs_${CMP}_fmt.md > /dev/null
    $PY scripts/harness_measurement/score_validate.py c13c_fmt ${CMP}_fmt ${TAG}_fmt --records data/agent_harness/validate_mutants.jsonl \
        --diff ${TAG}_fmt:c13c_fmt ${TAG}_fmt:${CMP}_fmt --out results/validate_precision/gt_b1_${TAG}_vs_${CMP}_fmt.md > /dev/null
    $PY scripts/harness_measurement/score_validate.py c13c ${CMP} ${TAG} --records data/agent_harness/validate_mutants.jsonl \
        --diff ${TAG}:c13c ${TAG}:${CMP} --out results/validate_precision/gt_b1_${TAG}_vs_${CMP}_plain.md > /dev/null
  fi
  echo "$(date '+%m-%d %H:%M') validate ground truth scored"
fi
echo "$(date '+%m-%d %H:%M') $TAG gates done"
