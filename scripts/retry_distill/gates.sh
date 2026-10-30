#!/bin/bash -l
# retry1 gates (spec/retry_distill_brief.md, Gates) for one adapter, on the vLLM path c13c was measured on: thinking ON on
# the eval server (:3012, here GPU 0), thinking OFF on the sampler (:3011, GPU 1), both serving rb1009 with the adapter hot-loaded.
#   - suite v5 gap tests (11) n10 x 3, both modes, execution-scored (exec_score.py);
#   - agentic harness pool 1 and pool_tweak, --runs 2 --rounds 2, both modes: first attempt (attempts[0]) is the gate, the
#     final status gives the retry gain after training; the summary's cause table gives the §3.29 habits;
#   - T40/T42 n20 x 2 (on); T54 n20 (off); hard sets 1-3 (eval_hard_cases.py, k 4);
#   - validate ground truth (no judge): B1 and B1-tweak, --format, both modes, 2 runs (CLAUDE.md validate gate);
#   - full v4 n5 both modes and thinking-off validate x9 (judge regression check).
#   setsid nohup scripts/retry_distill/gates.sh retry1 066 > logs/retry_distill/gates_retry1.log 2>&1 &
#   GATES selects (default gt,gaps,harness,belief,suite). Waits up to 20 min for the two servers.
cd /home/pavlisd/llama_train
RUN=${1:-retry1}; R=${2:-066}; TAG=${3:-$RUN}; AD=${RUN}_r$R
GATES=${GATES:-gt,gaps,harness,belief,suite}
PY=~/venv/bin/python; L=logs/retry_distill; RA=results/agent_harness; RR=results/retry_distill; mkdir -p $RR
SP=${SPORT:-3011}; EP=${EPORT:-3012}
SUITE4=$PWD/results/eval_snapshot_20261003/ctl2_test_suite_v4.json; SUITE5=$PWD/results/eval_snapshot_20261013/ctl2_test_suite_v5.json
GAPS=T44,T46,T53,T54,T57,T60,T61,T62,T63,T67,T73
export PATH=/home/pavlisd/venv/bin:$PATH
ts() { date '+%m-%d %H:%M'; }
for p in $SP $EP; do n=0; until curl -sf 127.0.0.1:$p/v1/models >/dev/null; do sleep 20; n=$((n+1)); [ $n -gt 60 ] && { echo "$(ts) no server on :$p"; exit 1; }; done
  curl -sf -X POST 127.0.0.1:$p/v1/load_lora_adapter -H 'Content-Type: application/json' \
    -d "{\"lora_name\": \"$AD\", \"lora_path\": \"$PWD/data/opcd/$RUN/round_$R/adapter_vllm\"}" >/dev/null || echo "load $AD on :$p: already loaded or failed"
  curl -sf 127.0.0.1:$p/v1/models | grep -q "\"$AD\"" || { echo "$(ts) $AD not served on :$p"; exit 1; }; done
echo "$(ts) $TAG gates start ($AD; on :$EP, off :$SP; GATES=$GATES)"
mk() {  # mk NAME MODE PORT SUITE
  sed -e "s/vllm_model: rb1006/vllm_model: $AD/; s#vllm_url: http://127.0.0.1:3011#vllm_url: http://127.0.0.1:$3#; s/run_label: qwen38_rb1006_vllm_$2/run_label: qwen38_$1/" \
      -e "s#suite_file: .*#suite_file: $4#" -e "1s/.*/# $1 ($AD on vLLM :$3), thinking ${2^^} -- written by scripts\/retry_distill\/gates.sh./" \
      configs/eval_rb1006_vllm_$2.yaml > configs/eval_$1.yaml; }
t() { log=$1; shift; s=$(date +%s); CUDA_VISIBLE_DEVICES="" $PY -u test.py "$@" --workers 32 > $L/$log.log 2>&1; echo "$(ts) $log done ($(( ($(date +%s)-s)/60 )) min)"; }
for m in on off; do port=$EP; [ $m = off ] && port=$SP
  mk rd_v5gaps_${TAG}_$m $m $port $SUITE5; mk rd_v4_${TAG}_$m $m $port $SUITE4; done
mk rd_t40t42_${TAG}_on on $EP $SUITE4; mk rd_t54_${TAG}_off off $SP $SUITE5
ON=(); OFF=()
if [[ $GATES == *gaps* ]]; then
  for x in a b c; do
    ON+=("t rd_v5gaps_${TAG}_on_$x configs/eval_rd_v5gaps_${TAG}_on.yaml --tests $GAPS --runs 10")
    OFF+=("t rd_v5gaps_${TAG}_off_$x configs/eval_rd_v5gaps_${TAG}_off.yaml --tests $GAPS --runs 10"); done; fi
if [[ $GATES == *belief* ]]; then
  ON+=("t rd_t40t42_${TAG}_a configs/eval_rd_t40t42_${TAG}_on.yaml --tests T40,T42 --runs 20"
       "t rd_t40t42_${TAG}_b configs/eval_rd_t40t42_${TAG}_on.yaml --tests T40,T42 --runs 20")
  OFF+=("t rd_t54_${TAG}_off configs/eval_rd_t54_${TAG}_off.yaml --tests T54 --runs 20"); fi
if [[ $GATES == *suite* ]]; then
  ON+=("t rd_v4_${TAG}_on_full_n5 configs/eval_rd_v4_${TAG}_on.yaml --runs 5")
  OFF+=("t rd_v4_${TAG}_off_full_n5 configs/eval_rd_v4_${TAG}_off.yaml --runs 5")
  for r in 2 3 4 5 6 7 8 9; do OFF+=("t rd_v4_${TAG}_off_validate_rep$r configs/eval_rd_v4_${TAG}_off.yaml --validate-only --runs 5"); done; fi
( for c in "${ON[@]}"; do eval "$c"; done ) &
( for c in "${OFF[@]}"; do eval "$c"; done ) &
if [[ $GATES == *gt* ]]; then   # one gen_answers per set and mode, each mode on its own server; per-mode files, merged after
  ( for m in off on; do port=$SP; [ $m = on ] && port=$EP
      $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants_tweak.jsonl --model $AD --url http://127.0.0.1:$port \
        --modes $m --runs 2 --format --concurrency 16 --out $RA/validate_gt_tweak_${TAG}_fmt_$m.jsonl > $L/gen_tweak_${TAG}_fmt_$m.log 2>&1 &
      $PY -u scripts/harness_measurement/gen_answers.py data/agent_harness/validate_mutants.jsonl --model $AD --url http://127.0.0.1:$port \
        --modes $m --runs 2 --format --concurrency 16 --out $RA/validate_gt_${TAG}_fmt_$m.jsonl > $L/gen_b1_${TAG}_fmt_$m.log 2>&1 &
    done; wait
    cat $RA/validate_gt_tweak_${TAG}_fmt_off.jsonl $RA/validate_gt_tweak_${TAG}_fmt_on.jsonl > $RA/validate_gt_tweak_${TAG}_fmt.jsonl
    cat $RA/validate_gt_${TAG}_fmt_off.jsonl $RA/validate_gt_${TAG}_fmt_on.jsonl > $RA/validate_gt_${TAG}_fmt.jsonl
    echo "$(ts) validate ground-truth answers done" ) &
fi
if [[ $GATES == *harness* ]]; then   # one chain per mode (pool 1, then pool_tweak), 4 graph runs each on the CloverDX server
  for m in on off; do port=$EP; [ $m = off ] && port=$SP
    ( for pool in pool1 pool_tweak; do
        $PY -u agent_harness.py run data/agent_harness/$pool.jsonl --model $AD --url http://127.0.0.1:$port --modes $m --runs 2 --rounds 2 \
          --concurrency 4 --out $RA/${TAG}_${pool}_$m.jsonl > $L/harness_${TAG}_${pool}_$m.log 2>&1
        echo "$(ts) harness $pool $m done ($(grep -c . $RA/${TAG}_${pool}_$m.jsonl) records)"; done ) &
  done
fi
if [[ $GATES == *belief* ]]; then
  ( for s in 1 2 3; do f=hard_cases.jsonl; [ $s -gt 1 ] && f=hard_cases$s.jsonl
      CUDA_VISIBLE_DEVICES="" $PY -u data/opcd/eval_hard_cases.py ${TAG}_set$s --file $f $TAG=$AD:student --k 4 --config configs/opcd_$RUN.yaml > $L/hard_eval_${TAG}_set$s.log 2>&1; done
    echo "$(ts) hard-case evals done" ) &
fi
wait
if [[ $GATES == *gaps* ]]; then
  $PY data/suite_v5/exec_score.py $(ls results/results_qwen38_rd_v5gaps_${TAG}_o*_*.json) --out $RR/gaps_${TAG}.json > $L/exec_gaps_${TAG}.log 2>&1
  [[ $GATES == *belief* ]] && $PY data/suite_v5/exec_score.py $(ls results/results_qwen38_rd_t54_${TAG}_off*.json 2>/dev/null) --out $RR/t54_${TAG}.json >> $L/exec_gaps_${TAG}.log 2>&1
  echo "$(ts) execution scoring done"
fi
if [[ $GATES == *harness* ]]; then
  for pool in pool1 pool_tweak; do cat $RA/${TAG}_${pool}_on.jsonl $RA/${TAG}_${pool}_off.jsonl > $RA/${TAG}_${pool}.jsonl
    $PY agent_harness.py summary $RA/${TAG}_${pool}.jsonl > $RA/${TAG}_${pool}.summary.md 2> $L/summary_${TAG}_${pool}.log; done
fi
if [[ $GATES == *gt* ]]; then
  $PY scripts/harness_measurement/score_validate.py tweak_c13c_fmt tweak_${TAG}_fmt --records data/agent_harness/validate_mutants_tweak.jsonl --diff tweak_${TAG}_fmt:tweak_c13c_fmt \
      --out $RR/gt_tweak_${TAG}_fmt.md > /dev/null
  $PY scripts/harness_measurement/score_validate.py c13c_fmt ${TAG}_fmt --records data/agent_harness/validate_mutants.jsonl --diff ${TAG}_fmt:c13c_fmt \
      --out $RR/gt_b1_${TAG}_fmt.md > /dev/null
  echo "$(ts) validate ground truth scored"
fi
$PY scripts/retry_distill/gates_table.py $RUN $R > $RR/gates_${TAG}.md 2> $L/gates_table_${TAG}.log && echo "$(ts) gate table written" || echo "$(ts) gate table failed (see $L/gates_table_${TAG}.log)"
echo "$(ts) $TAG gates done"
