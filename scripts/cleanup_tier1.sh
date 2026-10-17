#!/bin/bash
# Tier-1 disk cleanup: training artefacts whose removal loses no result, model or ability to re-export.
# Dry run by default (prints what would go and the total); pass --apply to delete.
#
#   scripts/cleanup_tier1.sh            # review
#   scripts/cleanup_tier1.sh --apply    # delete
#
# 1. LlamaFactory intermediate checkpoints (saves/<run>/<stamp>/checkpoint-*): optimizer states for resuming a finished run.
#    Only where the run directory holds its final adapter_model.safetensors; runs without one (the crashed rb1008b/r128 SFTs)
#    are skipped and listed. trainer_state.json, logs and the final adapter stay.
# 2. OPCD optimizer.pt in every round (data/opcd/<run>/round_*/optimizer.pt): only used to resume a run mid-way.
#    Kept: any run in KEEP_RUNS (the one training now) and the final round of the run it started from.
# 3. OPCD adapter_vllm of non-final rounds: the vLLM conversion, which opcd.py regenerates from adapter/ when needed.
#    Kept: final rounds and every round named as init_adapter in configs/opcd_*.yaml. The adapter/ itself always stays.
# 4. Two exports with no remaining use (+ their symlinks): qwen38_rb1006_opcdsmoke (smoke test),
#    qwen38_fix6_sftdpo_dpo1full (abandoned DPO variant). Their eval/LF configs stay in git for the record.
set -euo pipefail
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
H=/home/pavlisd; LT=$H/llama_train; LF=$H/LlamaFactory/saves; EX=$H/exports
KEEP_RUNS=""                           # OPCD runs left untouched (in training / being evaluated), e.g. "c13c"
KEEP_ROUNDS=""                         # rounds whose optimizer.pt stays (resume source of a kept run), e.g. "c13b/round_015"

for r in $KEEP_RUNS; do
  pgrep -u pavlisd -f "opcd.py train --config configs/opcd_$r.yaml" >/dev/null && echo "note: $r is training; it is excluded"
done

LIST=$(mktemp); SKIP=$(mktemp)
# 1
for d in "$LF"/*/*/; do
  ls -d "$d"checkpoint-* >/dev/null 2>&1 || continue
  if [ -f "$d/adapter_model.safetensors" ]; then ls -d "$d"checkpoint-* >> "$LIST"; else echo "${d%/}" >> "$SKIP"; fi
done
# 2 and 3
INIT=$(grep -ho '^init_adapter: data/opcd/[^ ]*' "$LT"/configs/opcd_*.yaml | sed 's#init_adapter: data/opcd/##; s#/adapter$##' | sort -u)
for run in "$LT"/data/opcd/c*/; do
  name=$(basename "$run"); [[ " $KEEP_RUNS " == *" $name "* ]] && continue
  rounds=$(ls -d "$run"round_* 2>/dev/null | sort) || continue
  [ -z "$rounds" ] && continue
  last=$(echo "$rounds" | tail -1)
  for r in $rounds; do
    rel="$name/$(basename "$r")"
    [ -f "$r/optimizer.pt" ] && [[ " $KEEP_ROUNDS " != *" $rel "* ]] && echo "$r/optimizer.pt" >> "$LIST"
    if [ "$r" != "$last" ] && [ -d "$r/adapter_vllm" ] && ! grep -qx "$rel" <<< "$INIT"; then echo "$r/adapter_vllm" >> "$LIST"; fi
  done
done
# 4
for e in qwen38_rb1006_opcdsmoke qwen38_fix6_sftdpo_dpo1full; do
  [ -d "$EX/$e" ] && echo "$EX/$e" >> "$LIST"
  find "$EX" -maxdepth 1 -type l -lname "$EX/$e" >> "$LIST"
done

echo "== to delete: $(wc -l < "$LIST") paths"
awk -F/ '{ if ($0 ~ /checkpoint-/) k="1 LlamaFactory checkpoints"; else if ($0 ~ /optimizer.pt$/) k="2 OPCD optimizer.pt"; else if ($0 ~ /adapter_vllm$/) k="3 OPCD non-final adapter_vllm"; else k="4 exports + symlinks"; print k "\t" $0 }' "$LIST" \
  | while IFS=$'\t' read -r k p; do printf '%s\t%s\n' "$k" "$(du -sb "$p" 2>/dev/null | cut -f1)"; done \
  | awk -F'\t' '{s[$1]+=$2; t+=$2} END {for (k in s) printf "  %-32s %6.0f GB\n", k, s[k]/2^30; printf "  %-32s %6.0f GB\n", "TOTAL", t/2^30}' | sort
if [ -s "$SKIP" ]; then echo "== skipped (no final adapter; checkpoints are the only artefact):"; sed 's/^/  /' "$SKIP"; fi
echo "== full list: $LIST"

if [ $APPLY = 1 ]; then
  while read -r p; do rm -rf -- "$p"; done < "$LIST"
  echo "deleted. df:"; df -h /home | tail -1
else
  echo "(dry run; re-run with --apply to delete)"
fi
