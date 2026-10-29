#!/bin/bash -l
# Keeps an OPCD run folder small while it trains (/home filled up on 2026-10-28 and killed valprec2 in round 10): every
# 5 minutes, deletes adapter / adapter_vllm / optimizer.pt of every finished round except the newest KEEP (default 2),
# keeping each round's metrics.json and samples.jsonl. Resume needs only the newest finished round; the gates use the last.
#   setsid nohup scripts/validate_precision/prune_rounds.sh valprec2 > logs/validate_precision/prune_valprec2.log 2>&1 &
# Stops when the run's last round (LAST, default 155) has finished.
cd /home/pavlisd/llama_train/data/opcd/${1:?run name}
KEEP=${KEEP:-2}; LAST=${LAST:-155}
while :; do
  done_rounds=$(for d in round_*; do [ -f "$d/metrics.json" ] && echo "$d"; done | sort)
  for d in $(echo "$done_rounds" | head -n -"$KEEP"); do
    [ -e "$d/optimizer.pt" ] || [ -e "$d/adapter" ] || continue
    rm -rf "$d/adapter" "$d/adapter_vllm" "$d/optimizer.pt" && echo "$(date '+%m-%d %H:%M') pruned $d"
  done
  [ -f "$(printf 'round_%03d' "$LAST")/metrics.json" ] && { echo "last round finished"; exit 0; }
  sleep 300
done
