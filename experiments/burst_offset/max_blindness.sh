#!/usr/bin/env bash
# 12d burst-placement figure driver: fire an identical 5s @40M UDP burst at
# different offsets inside separate 1-minute aggregation windows, then show
# the tier-1m min/max are invariant to placement while the raw trace's peak
# position tracks the offset. (JOURNAL 12d: on a cumulative counter, min/max
# encode window boundaries, not traffic.)
#
# PRECONDITIONS: full pipeline live (poller writing infldb), lab OTHERWISE
# QUIET — do not run while a REC/E3 rep is in flight, it would contaminate
# both experiments. iperf3 server on h2:5201 (record_event.sh leaves one).
#
# Timing model: tier-1m task = every 1m, offset 30s; aggregateWindow windows
# are [start, stop) stamped at STOP (JOURNAL 13 gotchas). So window [T, T+60)
# is stamped T+60 and safely queryable from ~T+60+45s.
set -u
cd "$(dirname "$0")"

H1=clab-ma-fp-stumpf-h1
DST=10.0.2.102
PORT=5201
read -r -a OFFSETS <<< "${BLIND_OFFSETS:-3 28 50}"   # burst start offsets (s) within the 1m window
BURST_LEN=${BLIND_BURST_LEN:-5}
# 40M was the original 12d spec (counter-mode: any rate works, min/max are
# endpoints regardless). Use 10M to match the paper's modelled link capacity
# when checking the RATE-FIRST cascade, where the stored max is compared against
# the true peak and the value therefore matters.
RATE=${BLIND_RATE:-40M}
# Pass --rate once the cascade stores rates (2026-08-08 migration).
ANALYZE_FLAGS=${BLIND_ANALYZE_FLAGS:-}
OUT="blindness_$(date +%Y%m%d-%H%M%S).csv"
WINDOWS=()

docker exec clab-ma-fp-stumpf-h2 pgrep -f "iperf3 -s -p $PORT" >/dev/null 2>&1 ||
  docker exec -d clab-ma-fp-stumpf-h2 iperf3 -s -p "$PORT"

for off in "${OFFSETS[@]}"; do
  now=$(date +%s)
  T=$(( (now / 60 + 1) * 60 ))                 # next minute boundary
  [ $((T - now)) -lt 5 ] && T=$((T + 60))      # need lead time to sleep+exec
  echo "window T=$T ($(date -d @"$T" +%H:%M:%S)) burst at +${off}s"
  sleep $((T - $(date +%s) + off))
  docker exec "$H1" iperf3 -u -c "$DST" -p "$PORT" -b "$RATE" -t "$BURST_LEN" \
    > /dev/null 2>&1
  WINDOWS+=("$T:$off")
done

LAST_T=${WINDOWS[-1]%%:*}
WAIT_UNTIL=$((LAST_T + 60 + 45))               # window stop + task offset 30s + lag
now=$(date +%s)
[ "$now" -lt "$WAIT_UNTIL" ] && { echo "waiting $((WAIT_UNTIL - now))s for tier-1m task"; sleep $((WAIT_UNTIL - now)); }

python3 analyze_blindness.py $ANALYZE_FLAGS "$OUT" "${WINDOWS[@]}"
echo "12d figure data -> $OUT"
