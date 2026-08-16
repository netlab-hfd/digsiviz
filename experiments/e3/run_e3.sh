#!/usr/bin/env bash
# E3 — replay-per-tier sequence: for each recorded event, replay from
# tier {raw(0), 60, 300} and analyze immediately after each replay
# (replay trace must be read from infldb well inside its 1h retention;
# originals come from the on-disk counter cache).
set -u
cd "$(dirname "$0")"

METAS=("$@")
[ ${#METAS[@]} -eq 0 ] && { echo "usage: run_e3.sh <event.meta> [...]"; exit 1; }
TIERS=(0 60 300)
OUT="results_$(date +%Y%m%d-%H%M%S).csv"
echo "event,tier,lag_s,nrmse_pct,mae_pct,mean_ratio,max_ratio,std_ratio" > "$OUT"

for meta in "${METAS[@]}"; do
  for tier in "${TIERS[@]}"; do
    echo "=== replay $(basename "$meta") tier=$tier ==="
    python3 replay_tier.py --meta "$meta" --tier "$tier" || { echo "REPLAY FAILED"; continue; }
    sleep 20   # let the last poll/flush land in influx before analyzing
    python3 analyze_e3.py --replay-meta "${meta%.meta}.replay_tier${tier}" \
      | tee /dev/stderr | grep '^CSV,' | cut -d, -f2- >> "$OUT"
  done
done
echo "E3 complete -> $OUT"
