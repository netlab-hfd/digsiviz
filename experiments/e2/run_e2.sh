#!/usr/bin/env bash
# E2 — Endurance: duration sweep (EXPERIMENT_MATRIX.md)
# Vary: run duration in {60s, 5m, 30m, 2h}.
# Hold: n = n_max flows (arg 1, from E1), total offered 10 Mbit/s, baseline pipeline.
# Measure: achieved rate OVER TIME (iperf3 per-interval JSON), CPU over time, loss.
# Reps: 3 for durations <= 30m, 1 for the 2h run (see EXPERIMENT_MATRIX.md).
set -u

N_FLOWS=${1:?usage: run_e2.sh <n_max from E1>}
H1=clab-ma-fp-stumpf-h1
H2=clab-ma-fp-stumpf-h2
DST=10.0.2.102
TOTAL_MBIT=10
DURATIONS=(${E2_DURATIONS:-60 300 1800 7200})   # override: E2_DURATIONS="60 300 1800"
BASE_PORT=5201
OUTDIR="$(cd "$(dirname "$0")" && pwd)/results/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"
echo "E2 run (n=$N_FLOWS) -> $OUTDIR"

for i in $(seq 0 $((N_FLOWS - 1))); do
  port=$((BASE_PORT + i))
  docker exec "$H2" pgrep -f "iperf3 -s -p $port" >/dev/null 2>&1 ||
    docker exec -d "$H2" iperf3 -s -p "$port"
done
sleep 2

host_cpu_sampler() {
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
container_cpu_sampler() {
  while :; do
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' \
      clab-ma-fp-stumpf-h1 clab-ma-fp-stumpf-h2 \
      clab-ma-fp-stumpf-r1 clab-ma-fp-stumpf-r2 clab-ma-fp-stumpf-r3 \
      2>/dev/null | sed "s/^/$(date +%s) /" >> "$1"
  done
}

rate_bps=$(( TOTAL_MBIT * 1000000 / N_FLOWS ))
for dur in "${DURATIONS[@]}"; do
  reps=3; [ "$dur" -ge 7200 ] && reps=1
  for rep in $(seq 1 "$reps"); do
    tag="d${dur}_rep${rep}"
    echo "=== $tag : ${N_FLOWS} flows x ${rate_bps} bps, ${dur}s ==="
    host_cpu_sampler "$OUTDIR/${tag}_hostcpu.log" & HOST_SAMPLER=$!
    container_cpu_sampler "$OUTDIR/${tag}_containercpu.log" & CONT_SAMPLER=$!
    pids=()
    for i in $(seq 0 $((N_FLOWS - 1))); do
      port=$((BASE_PORT + i))
      docker exec "$H1" iperf3 -u -c "$DST" -p "$port" -b "$rate_bps" -t "$dur" --json \
        > "$OUTDIR/${tag}_flow${i}.json" 2> "$OUTDIR/${tag}_flow${i}.err" &
      pids+=($!)
    done
    fails=0
    for p in "${pids[@]}"; do wait "$p" || fails=$((fails + 1)); done
    kill "$HOST_SAMPLER" "$CONT_SAMPLER" 2>/dev/null
    wait "$HOST_SAMPLER" "$CONT_SAMPLER" 2>/dev/null
    echo "$tag done (client failures: $fails)"
    sleep 10
  done
done
echo "E2 complete -> $OUTDIR"
