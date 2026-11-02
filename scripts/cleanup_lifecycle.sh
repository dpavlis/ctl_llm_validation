#!/bin/bash
# Lifecycle cleanup (2026-11-02): weights and states of finished or superseded lanes. Supersedes disk_cleanup.sh and
# cleanup_tier1.sh. Dry run by default (lists every path with its size and the totals per group); --apply deletes.
#
#   scripts/cleanup_lifecycle.sh            # review
#   scripts/cleanup_lifecycle.sh --apply    # delete
#
# Kept everywhere: results/, logs/, spec/, configs/, scripts/, WORKLOG, the training data (data/*, LlamaFactory/data,
# ctl_lora_training), and in every OPCD round and LlamaFactory phase its small files (samples.jsonl, metrics.json, probes,
# trainer_log.jsonl, training_config.yaml, *_results.json, loss plots). Only weights, optimizer states and debris go.
#
# Models kept:
#   exports      qwen38_rb1009_sftdpo (valprec2 / c13c base), qwen38_rb1006_sftdpo (tokenizer / system-prompt path of
#                every eval_rb1006_* config, c4 / c10 base), qwen38_base, and the symlinks onto them
#   OPCD         valprec2/round_155 (ship candidate), c13c/round_015 (generate reference), difr1/round_019 (difr2's
#                comparison), the whole of any run that is training now (difr2)
#   LlamaFactory final adapters of rb1009 and rb1006 (what the two kept exports were merged from)
set -euo pipefail
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
H=/home/pavlisd; LT=$H/llama_train; LF=$H/LlamaFactory/saves; EX=$H/exports
KEEP_EXPORTS="qwen38_base qwen38_rb1009_sftdpo qwen38_rb1006_sftdpo"
KEEP_ROUNDS="valprec2/round_155 c13c/round_015 difr1/round_019"
KEEP_LF="qwen38-27B-rb1009 qwen38-27B-rb1006"

# runs training now are left alone entirely
ACTIVE=$(ps -u pavlisd -o args= | grep -o 'opcd.py train --config configs/opcd_[^ ]*\.yaml' | sed 's#.*opcd_##; s#\.yaml##' | sort -u || true)
[ -n "$ACTIVE" ] && echo "note: training now, excluded: $ACTIVE"

LIST=$(mktemp)
add() { printf '%s\t%s\n' "$1" "$2" >> "$LIST"; }   # $1 group, $2 path

# A1. OPCD optimizer.pt (resume state of finished runs)
# A2. OPCD round adapters outside KEEP_ROUNDS, smoke adapters, the vLLM loader test
for run in "$LT"/data/opcd/*/; do
  name=$(basename "$run"); [[ " $ACTIVE " == *" $name "* ]] && continue
  for r in "$run"round_*/; do
    [ -d "$r" ] || continue
    rel="$name/$(basename "$r")"
    [ -f "$r/optimizer.pt" ] && add "A1 OPCD optimizer.pt" "${r}optimizer.pt"
    [[ " $KEEP_ROUNDS " == *" $rel "* ]] && continue
    for sub in adapter adapter_vllm; do [ -d "$r$sub" ] && add "A2 OPCD round adapters" "$r$sub"; done
  done
  [ -d "${run}smoke/adapter" ] && add "A2 OPCD round adapters" "${run}smoke/adapter"
done
[ -d "$LT/data/opcd/vllm_check" ] && add "A2 OPCD round adapters" "$LT/data/opcd/vllm_check"

# A3. LlamaFactory intermediate checkpoints (optimizer states; each phase keeps its final adapter)
for c in "$LF"/*/*/checkpoint-*/; do [ -d "$c" ] && add "A3 LlamaFactory checkpoints" "${c%/}"; done

# B1. merged exports of superseded rebuilds, and symlinks whose target is gone or going
for d in "$EX"/*; do
  b=$(basename "$d")
  if [ -L "$d" ]; then
    t=$(basename "$(readlink "$d")")
    [ -e "$d" ] && [[ " $KEEP_EXPORTS " == *" $t "* || "$b" == qwen38_base ]] && continue
    add "B1 exports + dead symlinks" "$d"; continue
  fi
  [[ " $KEEP_EXPORTS " == *" $b "* ]] && continue
  add "B1 exports + dead symlinks" "$d"
done

# B2. LlamaFactory weights of superseded rebuilds and DPO / self-distill experiments (logs and configs stay)
for p in "$LF"/*/; do
  run=$(basename "$p"); [[ " $KEEP_LF " == *" $run "* ]] && continue
  find "$p" -path '*/checkpoint-*' -prune -o \( -name '*.safetensors' -o -name 'training_args.bin' \) -type f -print \
    | while read -r f; do add "B2 LlamaFactory final adapters" "$f"; done
done
for d in "$H/LlamaFactory/~"; do [ -d "$d" ] && add "B3 old Qwen3.5-9B LlamaFactory copy (May)" "$d"; done

# C. debris in the project
for p in "$LT/.venv" "$LT/__pycache__" "$LT/tmp" "$LT/saves" \
         "$LT/data/opcd/._generate_gaps.jsonl" "$LT/data/opcd/generate_gaps_pre_rebuild_20261013_a6pcdrk_.tar.gz" \
         "$LT/data/opcd/hard_holdout_c13e_draft.json" "$LT/logs/Qwen3.8-27B.yaml.bak_20261025_torn"; do
  [ -e "$p" ] && add "C project debris" "$p"
done
find "$LT/data" -name '*.pre_rulings1004' -type f | while read -r f; do add "C project debris" "$f"; done

# report
awk -F'\t' '{print $1"\t"$2}' "$LIST" | while IFS=$'\t' read -r g p; do
  printf '%s\t%s\t%s\n' "$g" "$(du -sb "$p" 2>/dev/null | cut -f1)" "$p"; done > "$LIST.sz"
awk -F'\t' '{s[$1]+=$2; n[$1]++; t+=$2} END {for (k in s) printf "  %-44s %5d paths %7.1f GB\n", k, n[k], s[k]/2^30;
  printf "  %-44s %5d paths %7.1f GB\n", "TOTAL", NR, t/2^30}' "$LIST.sz" | sort
echo "== full list (group, bytes, path): $LIST.sz"

if [ $APPLY = 1 ]; then
  cut -f3 "$LIST.sz" | while read -r p; do rm -rf -- "$p"; done
  echo "deleted. df:"; df -h /home | tail -1
else
  echo "(dry run; re-run with --apply to delete)"
fi
