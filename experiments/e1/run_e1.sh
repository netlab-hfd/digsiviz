#!/usr/bin/env bash
# E1 — Calibration: flow-count sweep (EXPERIMENT_MATRIX.md)
# Vary: n parallel iperf3 UDP flows in {1,2,5,10,20}; total offered always 10 Mbit/s.
# Hold: 60 s per run, path h1 -> r1 -> r2 -> h2, baseline pipeline running.
# Measure: per-flow receiver bitrate + loss (iperf3 JSON), host CPU, per-container CPU.
# Repetitions: 3 per config.
set -u

H1=clab-ma-fp-stumpf-h1
H2=clab-ma-fp-stumpf-h2
DST=10.0.2.102
DUR=60
TOTAL_MBIT=10
FLOW_COUNTS=(1 2 5 10 20)
REPS=3
BASE_PORT=5201
OUTDIR="$(cd "$(dirname "$0")" && pwd)/results/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"

echo "E1 run -> $OUTDIR"

# --- Start iperf3 servers on h2, one port per potential flow (idempotent) ---
MAX_FLOWS=20
for i in $(seq 0 $((MAX_FLOWS - 1))); do
  port=$((BASE_PORT + i))
  docker exec "$H2" pgrep -f "iperf3 -s -p $port" >/dev/null 2>&1 ||
    docker exec -d "$H2" iperf3 -s -p "$port"
done
sleep 2

# --- Host CPU sampler: overall busy% from /proc/stat at 1 s ---
host_cpu_sampler() { # $1=outfile ; runs until killed
  local prev_idle prev_total
  read -r _ user nice system idle iowait irq softirq steal _ < /proc/stat
  prev_idle=$((idle + iowait)); prev_total=$((user + nice + system + idle + iowait + irq + softirq + steal))
  while sleep 1; do
    read -r _ user nice system idle iowait irq softirq steal _ < /proc/stat
    local idle_now=$((idle + iowait))
    local total_now=$((user + nice + system + idle + iowait + irq + softirq + steal))
    local didle=$((idle_now - prev_idle)) dtotal=$((total_now - prev_total))
    [ "$dtotal" -gt 0 ] && echo "$(date +%s) $(awk -v i="$didle" -v t="$dtotal" 'BEGIN{printf "%.1f", 100*(1-i/t)}')" >> "$1"
    prev_idle=$idle_now; prev_total=$total_now
  done
}

# --- Container CPU sampler via docker stats (~1 s cadence) ---
container_cpu_sampler() { # $1=outfile ; runs until killed
  while :; do
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' \
      clab-ma-fp-stumpf-h1 clab-ma-fp-stumpf-h2 \
      clab-ma-fp-stumpf-r1 clab-ma-fp-stumpf-r2 clab-ma-fp-stumpf-r3 \
      2>/dev/null | sed "s/^/$(date +%s) /" >> "$1"
  done
}

for n in "${FLOW_COUNTS[@]}"; do
  # Per-flow rate in bits/s (integer): total split evenly
  rate_bps=$(( TOTAL_MBIT * 1000000 / n ))
  for rep in $(seq 1 "$REPS"); do
    tag="n${n}_rep${rep}"
    echo "=== $tag : ${n} flows x ${rate_bps} bps, ${DUR}s ==="
    host_cpu_sampler "$OUTDIR/${tag}_hostcpu.log" & HOST_SAMPLER=$!
    container_cpu_sampler "$OUTDIR/${tag}_containercpu.log" & CONT_SAMPLER=$!

    pids=()
    for i in $(seq 0 $((n - 1))); do
      port=$((BASE_PORT + i))
      docker exec "$H1" iperf3 -u -c "$DST" -p "$port" -b "$rate_bps" -t "$DUR" --json \
        > "$OUTDIR/${tag}_flow${i}.json" 2> "$OUTDIR/${tag}_flow${i}.err" &
      pids+=($!)
    done
    fails=0
    for p in "${pids[@]}"; do wait "$p" || fails=$((fails + 1)); done

    kill "$HOST_SAMPLER" "$CONT_SAMPLER" 2>/dev/null
    wait "$HOST_SAMPLER" "$CONT_SAMPLER" 2>/dev/null
    echo "$tag done (client failures: $fails)"
    sleep 5   # settle between runs
  done
done

echo "E1 complete -> $OUTDIR"
