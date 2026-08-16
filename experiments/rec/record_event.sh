#!/usr/bin/env bash
# REC — record a reference event into infldb via the live pipeline.
# Prof's recipe: baseline 4 Mbit/s + randomly arriving 1.512 Mbit/s flows.
# The randomness lives HERE (recording); E3 replay is deterministic.
#
# Usage: record_event.sh <fluct|burst> [total_duration_s]
#   fluct — baseline + Poisson-ish arrivals of 1.512M flows, random durations.
#   burst — baseline + k simultaneous 1.512M flows for a fixed window
#           (the RQ2 headline saturation-style event).
#
# Writes a meta file (start/end epoch + type) — E3 needs the window.
set -u

TYPE=${1:?usage: record_event.sh <fluct|burst> [duration_s]}
DUR=${2:-900}                      # default 15 min; must stay < infldb 1h retention
H1=clab-ma-fp-stumpf-h1
H2=clab-ma-fp-stumpf-h2
DST=10.0.2.102
BASE_PORT=5201                     # baseline flow
DYN_PORT0=5202                     # dynamic flows: 5202..5202+MAX_DYN-1
MAX_DYN=${REC_MAX_DYN:-8}          # cap concurrent dynamic flows; keep <= n_max-1 from E1
BASE_RATE=4000000                  # 4 Mbit/s baseline
FLOW_RATE=1512000                  # 1.512 Mbit/s per dynamic flow
MEAN_GAP=15                        # fluct: mean seconds between arrivals
FLOW_MIN=10; FLOW_MAX=45           # fluct: dynamic flow duration range (s)
BURST_AT=${REC_BURST_AT:-$((DUR / 3))}   # burst: start offset (env-overridable)
BURST_FLOWS=4                      # 4 x 1.512 + 4 = ~10 Mbit/s total
BURST_LEN=60
OUTDIR="$(cd "$(dirname "$0")" && pwd)/events"
mkdir -p "$OUTDIR"
STAMP=$(date +%Y%m%d-%H%M%S)
META="$OUTDIR/${TYPE}_${STAMP}.meta"

# servers (idempotent)
for i in $(seq 0 "$MAX_DYN"); do
  port=$((BASE_PORT + i))
  docker exec "$H2" pgrep -f "iperf3 -s -p $port" >/dev/null 2>&1 ||
    docker exec -d "$H2" iperf3 -s -p "$port"
done
sleep 2

T0=$(date +%s)
{
  echo "type=$TYPE"
  echo "start_epoch=$T0"
  echo "duration=$DUR"
  echo "base_rate=$BASE_RATE"
  echo "flow_rate=$FLOW_RATE"
} > "$META"
echo "REC $TYPE for ${DUR}s -> $META"

# baseline flow, full duration
docker exec "$H1" iperf3 -u -c "$DST" -p "$BASE_PORT" -b "$BASE_RATE" -t "$DUR" \
  > /dev/null 2>&1 &
BASE_PID=$!

slot_busy=()   # slot -> pid
for i in $(seq 0 $((MAX_DYN - 1))); do slot_busy[i]=0; done

free_slot() {
  for i in $(seq 0 $((MAX_DYN - 1))); do
    p=${slot_busy[i]}
    if [ "$p" = 0 ] || ! kill -0 "$p" 2>/dev/null; then echo "$i"; return; fi
  done
  echo -1
}

if [ "$TYPE" = fluct ]; then
  END=$((T0 + DUR - FLOW_MIN))
  while [ "$(date +%s)" -lt "$END" ]; do
    # exponential-ish inter-arrival: -MEAN_GAP * ln(U)
    gap=$(awk -v m="$MEAN_GAP" 'BEGIN{srand(); printf "%d", -m*log(rand()+1e-9)}')
    [ "$gap" -lt 1 ] && gap=1
    sleep "$gap"
    slot=$(free_slot)
    [ "$slot" = -1 ] && continue   # at cap, skip this arrival
    flen=$(( FLOW_MIN + RANDOM % (FLOW_MAX - FLOW_MIN + 1) ))
    remain=$(( T0 + DUR - $(date +%s) )); [ "$flen" -gt "$remain" ] && flen=$remain
    [ "$flen" -lt 2 ] && break
    port=$((DYN_PORT0 + slot))
    docker exec "$H1" iperf3 -u -c "$DST" -p "$port" -b "$FLOW_RATE" -t "$flen" \
      > /dev/null 2>&1 &
    slot_busy[slot]=$!
    echo "arrival slot=$slot len=${flen}s t=+$(( $(date +%s) - T0 ))s" | tee -a "$META"
  done
elif [ "$TYPE" = burst ]; then
  sleep "$BURST_AT"
  echo "burst_start=+${BURST_AT}s flows=$BURST_FLOWS len=${BURST_LEN}s" | tee -a "$META"
  for i in $(seq 0 $((BURST_FLOWS - 1))); do
    docker exec "$H1" iperf3 -u -c "$DST" -p "$((DYN_PORT0 + i))" -b "$FLOW_RATE" -t "$BURST_LEN" \
      > /dev/null 2>&1 &
  done
else
  echo "unknown type $TYPE"; exit 1
fi

wait "$BASE_PID"
echo "end_epoch=$(date +%s)" >> "$META"
echo "REC done -> $META"
