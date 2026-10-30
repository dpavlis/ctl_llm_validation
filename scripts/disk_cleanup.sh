#!/bin/bash
# Disk cleanup proposal (2026-10-26). DRY RUN by default: prints every path it would delete with its size, and the total.
#   scripts/disk_cleanup.sh            # list only
#   DO_IT=1 scripts/disk_cleanup.sh    # delete
# Three groups, each can be switched off: EXPORTS=0 SAVES=0 OPCD=0.
# Everything deleted here is reproducible: a merged export from its adapter (minutes), an intermediate checkpoint or
# OPCD round from its config and data. Nothing in results/, logs/, data/ (other than data/opcd round adapters) or the
# HF cache is touched. Check the KEEP lists before running with DO_IT=1.
set -u
export LC_ALL=C   # printf decimal point
DO_IT=${DO_IT:-0}; EXPORTS=${EXPORTS:-1}; SAVES=${SAVES:-1}; OPCD=${OPCD:-1}
H=/home/pavlisd; LT=$H/llama_train
total=0; n=0
rm_path() {   # $1 path, $2 reason. Never follows a symlink: a link is unlinked, its target untouched.
  local p=${1%/}; [ -e "$p" ] || [ -L "$p" ] || return
  if [ -L "$p" ]; then printf '%8s     %s   (symlink -> %s; link removed only)\n' "-" "$p" "$(readlink "$p")"; n=$((n + 1)); [ "$DO_IT" = 1 ] && rm "$p"; return; fi
  local kb; kb=$(du -sk "$p" | cut -f1); total=$((total + kb)); n=$((n + 1))
  printf '%8.1f GB  %s   (%s)\n' "$(awk -v k="$kb" 'BEGIN{printf "%.1f", k/1048576}')" "$p" "$2"
  [ "$DO_IT" = 1 ] && rm -rf "$p"
}

# ------------------------------------------------------------------ 1. merged exports (51 GB each)
# KEEP: served or referenced by current measurements (§3.26, §3.28, §3.34; the c13c base; eval/mut_validate defaults).
KEEP_EXPORTS="qwen38_base qwen38_rb1009_sftdpo qwen38_rb1006_sftdpo qwen38_rb1011_sftdpo qwen38_rb1011s2_sftdpo qwen38_rb1009s2_sftdpo qwen38_rb1012_sftdpo qwen38_rb1012s2_sftdpo qwen38_fix6_sftdpo qwen38_rb1010a_sftdpo"
if [ "$EXPORTS" = 1 ]; then
  echo "== 1. ~/exports: merged models not in the keep list"
  for d in "$H"/exports/*; do
    b=$(basename "$d"); [ -d "$d" ] || continue
    case " $KEEP_EXPORTS " in *" $b "*) continue;; esac
    if [ -L "$d" ]; then   # eval-config aliases (qwen38_<run>_on/_off) pointing at an export: unlink only if the target goes too
      t=$(basename "$(readlink -f "$d")"); case " $KEEP_EXPORTS " in *" $t "*) continue;; esac
      rm_path "$d" "alias"; continue
    fi
    [ "$(du -sk "$d" | cut -f1)" -gt 10485760 ] || continue     # only full merged models (> 10 GB)
    rm_path "$d" "merged export; rebuild from its adapter in ~/LlamaFactory/saves or data/opcd"
  done
fi

# ------------------------------------------------------------------ 2. LlamaFactory intermediate checkpoints (3.6 GB each)
# Each phase dir keeps its top-level adapter_model.safetensors (what the export used) and its last checkpoint.
# Extra keeps: the SFT checkpoints the isolation arms start from (§3.32).
KEEP_CKPT="qwen38-27B-rb1011/2026-10-18-21-50-38_sft/checkpoint-2240 qwen38-27B-rb1012/2026-10-22-19-53-15_sft/checkpoint-2262"
if [ "$SAVES" = 1 ]; then
  echo "== 2. ~/LlamaFactory/saves: intermediate checkpoints (keeping the top-level adapter and the last checkpoint per phase)"
  for p in "$H"/LlamaFactory/saves/*/*/; do
    [ -f "$p/adapter_model.safetensors" ] || continue      # a phase without a final adapter is left alone
    last=$(ls "$p" | grep '^checkpoint-' | sort -t- -k2 -n | tail -1)
    for c in "$p"checkpoint-*/; do
      [ -d "$c" ] || continue
      cb=$(basename "$c"); rel=$(echo "$c" | sed "s#$H/LlamaFactory/saves/##; s#/\$##")
      [ "$cb" = "$last" ] && continue
      case " $KEEP_CKPT " in *" $rel "*) continue;; esac
      rm_path "$c" "intermediate checkpoint; final adapter kept in $(basename "$p")"
    done
  done
  # the two aborted r128/8b runs have no final adapter and no export: all three checkpoints each
  for r in qwen38-27B-rb1008b qwen38-27B-rb1008r128 chunked_logps_memtest; do
    rm_path "$H/LlamaFactory/saves/$r" "aborted or test run, never exported"
  done
fi

# ------------------------------------------------------------------ 3. OPCD run folders: per-round adapters (1.2–2.4 GB each)
# KEEP whole final round for referenced runs; prompts/samples/metrics/probes stay everywhere; delete other round_* dirs.
# Runs with nothing referenced any more lose all rounds (their metrics.json / samples.jsonl / probes stay).
declare -A KEEP_ROUND=( [c13c]=round_015 [c4]=round_015 [c10]=round_019 [c13d]=round_009 [c14]=round_015 [s3b-rb1011]=round_015 [exec_rft1]=round_056 [retry1]=round_066 [valprec1]=round_122 [valprec2]=round_155 )
if [ "$OPCD" = 1 ]; then
  echo "== 3. data/opcd: round adapters (keeping the final round of c13c c4 c10 c13d c14 s3b-rb1011 exec_rft1 retry1)"
  for d in "$LT"/data/opcd/*/; do
    run=$(basename "$d"); [ -d "$d/round_000" ] || continue
    keep=${KEEP_ROUND[$run]:-}
    for r in "$d"round_*/; do
      rb=$(basename "$r")
      [ "$rb" = "$keep" ] && continue
      # keep each round's small files; delete only the adapter weights
      for sub in adapter adapter_vllm; do rm_path "$r$sub" "round adapter of $run (final kept: ${keep:-none})"; done
    done
  done
fi

echo; printf 'TOTAL %d paths, %.1f GB %s\n' "$n" "$(awk -v k="$total" 'BEGIN{printf "%.1f", k/1048576}')" "$([ "$DO_IT" = 1 ] && echo DELETED || echo '(dry run; DO_IT=1 to delete)')"
