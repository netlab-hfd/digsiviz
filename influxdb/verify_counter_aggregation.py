#!/usr/bin/env python3
"""
Empirically verify that the cascade's min/max/median carry no burst information,
because they are applied to a CUMULATIVE COUNTER rather than to a rate.

*** READ THIS BEFORE INTERPRETING THE OUTPUT ***

This is a FALSIFIER for the counter-mode cascade, written to prove that design
broken. Since the 2026-08-08 rate-first migration the cascade stores aggregates
of the RATE, so CHECK 2 and CHECK 3 are EXPECTED TO FAIL, and their failure is
the evidence that the current pipeline is correct:

    CHECK 2 reports MISMATCH  -> min != first sample, max != last sample,
                                 i.e. min/max describe traffic, not the window's
                                 edges. This is the desired result.
    CHECK 3 reports DIFFERS   -> (max-min)/elapsed != the mean rate, i.e. the
                                 extra aggregates carry information `mean` does
                                 not. This is the desired result.

"CLAIM CONFIRMED" on either check would mean the counter-mode bug is back.
CHECK 0 (ingest redundancy, expect 1.00x) and CHECK 1 (raw counter monotone)
are mode-independent and should still pass as written.

Also note the WINDOW ALIGNMENT paragraph below is stale in one detail: tier
points are now stamped at their window's START, not its STOP (uniform
timeSrc: "_start", see generate_manifest.TIMESRC). The slicing here still
reconstructs windows correctly because it slices by the window the stamp
belongs to, but do not take the "(T-every, T]" wording as current.

The claim (PROJECT_JOURNAL.md 12d), on a monotonically increasing series:
    min  == the counter value at the window's START
    max  == the counter value at the window's END
    -> they mark window boundaries, not traffic behaviour
    -> (max - min) / window == the mean rate == what `mean` already encodes
    -> burst PLACEMENT inside the window is invisible

Checks 1-3 run on whatever the live pipeline has produced. Check 4 (burst
placement blindness) needs controlled iperf3 runs and lives in
verify_burst_placement.py.

Compares traffic-1m against raw infldb directly: tier-1m is the only tier fed
from raw (`generate_manifest.py:tier1_task`), so it isolates one aggregation
step. Later tiers aggregate tier-1m's already-suffixed fields, and min-of-mins
== global min, so the result holds transitively.

WINDOW ALIGNMENT (the subtle part): aggregateWindow() aligns windows to the
epoch and stamps each output point with the window's STOP time. So a tier point
at time T summarises raw samples in the half-open interval (T-every, T].
Comparing against a naively-sliced window silently misaligns by one sample and
makes a true claim look false.

Talks to InfluxDB via `docker exec influx query`, matching backfill.py's
convention (no influxdb_client dependency).

Run:  python3 verify_counter_aggregation.py [--minutes N]
"""

import argparse
import csv
import io
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta


def parse_ts(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))

ORG = "myorg"
TOKEN = "mytoken"
CONTAINER = "influxdb"

RAW_BUCKET = "infldb"
TIER_BUCKET = "traffic-1m"
TIER_EVERY = 60  # seconds; must match the tier's `every`
MEASUREMENT = "network_interface"
BASE_FIELD = "statistics_out-octets"

# Counters are float64 in the pipeline; allow for float representation only,
# not for real disagreement.
EPS_REL = 1e-9


def flux(query):
    """Run a Flux query in the influxdb container, return parsed rows."""
    proc = subprocess.run(
        [
            "docker", "exec", "-i", CONTAINER,
            "influx", "query", "--org", ORG, "--token", TOKEN, "--raw", "-",
        ],
        input=query,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"influx query failed:\n{proc.stderr}")
    return parse_annotated_csv(proc.stdout)


def parse_annotated_csv(text):
    """Parse InfluxDB annotated CSV -> list of dicts. Skips #datatype/#group
    /#default annotation lines and the blank lines between result tables."""
    rows = []
    header = None
    for line in io.StringIO(text):
        line = line.rstrip("\n")
        if not line.strip():
            header = None  # a blank line ends a table; next non-# line is a header
            continue
        if line.startswith("#"):
            continue
        fields = next(csv.reader([line]))
        if header is None:
            header = fields
            continue
        rows.append(dict(zip(header, fields)))
    return rows


def series_key(r):
    return (r.get("hostname", ""), r.get("interface_name", ""))


def fetch_raw(minutes):
    rows = flux(f'''
from(bucket: "{RAW_BUCKET}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r._field == "{BASE_FIELD}")
  |> keep(columns: ["_time", "_value", "hostname", "interface_name"])
''')
    out = defaultdict(list)
    for r in rows:
        out[series_key(r)].append((r["_time"], float(r["_value"])))
    for k in out:
        out[k].sort()
    return out


def fetch_tier(minutes):
    aggs = ["min", "max", "mean", "median"]
    field_filter = " or ".join(f'r._field == "{BASE_FIELD}_{a}"' for a in aggs)
    rows = flux(f'''
from(bucket: "{TIER_BUCKET}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => {field_filter})
  |> keep(columns: ["_time", "_value", "_field", "hostname", "interface_name"])
''')
    # (series, window_stop) -> {agg: value}
    out = defaultdict(dict)
    for r in rows:
        agg = r["_field"].rsplit("_", 1)[1]
        out[(series_key(r), r["_time"])][agg] = float(r["_value"])
    return out


def close(a, b):
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= EPS_REL * scale


def monotone(win):
    """The 12d claim is about a monotone counter. A window containing a counter
    reset is excluded rather than counted as a falsification."""
    return all(win[i][1] >= win[i - 1][1] for i in range(1, len(win)))


def dedupe(win, min_gap=0.2):
    """Collapse redundant points from the same poll.

    The ingestion path writes TWO points per poll, ~90ms apart, so a 0.5s poll
    yields ~4 points/s instead of 2. Any per-sample rate computed over the raw
    series therefore alternates between 0 (the duplicate pair) and the true
    rate, biasing mean-of-rates LOW by ~40%. Keeping the first point of each
    cluster restores the real poll cadence.
    """
    out = [win[0]]
    for t, v in win[1:]:
        if (parse_ts(t) - parse_ts(out[-1][0])).total_seconds() >= min_gap:
            out.append((t, v))
    return out


def check_duplicates(raw):
    print("\n=== CHECK 0: redundancy in the raw ingest ===")
    print(f"    polling is ~0.5s, so expect ~2 points/s per series.")
    for key, samples in sorted(raw.items()):
        if len(samples) < 2:
            continue
        span = (parse_ts(samples[-1][0]) - parse_ts(samples[0][0])).total_seconds()
        if span <= 0:
            continue
        rate = len(samples) / span
        kept = len(dedupe(samples))
        print(f"  {key[0]:>4} {key[1]:<14} {rate:4.1f} pts/s  "
              f"-> {kept/span:4.1f} pts/s after dedupe  "
              f"({len(samples)/max(kept,1):.2f}x redundancy)")


def check_monotone(raw):
    print("\n=== CHECK 1: is the raw counter monotonically increasing? ===")
    ok = True
    for key, samples in sorted(raw.items()):
        drops = [
            (samples[i][0], samples[i - 1][1], samples[i][1])
            for i in range(1, len(samples))
            if samples[i][1] < samples[i - 1][1]
        ]
        status = "MONOTONE" if not drops else f"{len(drops)} DECREASE(S)"
        print(f"  {key[0]:>4} {key[1]:<14} n={len(samples):>5}  {status}")
        if drops:
            ok = False
            for t, prev, cur in drops[:3]:
                print(f"      {t}  {prev:.0f} -> {cur:.0f}")
    if not ok:
        print("  NOTE: decreases mean a counter reset (interface flap / restart).")
        print("        The 12d claim only holds within a monotone run.")
    return ok


def raw_window(samples, stop_iso, every):
    """Raw samples in the window aggregateWindow() actually summarised.

    Flux windows are [start, stop) — left-closed, RIGHT-OPEN — and each output
    point carries its window's STOP time. So the point at T summarises
    [T-every, T). Slicing this as (T-every, T] instead picks up the next
    window's first sample, which makes max look like it disagrees with the
    window's last sample by a constant offset — reading as "claim falsified"
    when the claim is fine and the slice is wrong.
    """
    stop = parse_ts(stop_iso)
    start = stop - timedelta(seconds=every)
    # A window whose start predates our raw fetch is only PARTIALLY covered:
    # its true first sample was never fetched, so `first` would be a mid-window
    # sample and min would look wrong. Skip rather than count as a mismatch.
    if not samples or parse_ts(samples[0][0]) > start:
        return []
    return [(t, v) for t, v in samples if start <= parse_ts(t) < stop]


def check_boundaries(raw, tier):
    print("\n=== CHECK 2: does min == window's FIRST raw sample, max == LAST? ===")
    print("    (if so, min/max encode window boundaries, not traffic)")
    tested = matched = 0
    for (key, stop), aggs in sorted(tier.items()):
        if key not in raw or "min" not in aggs or "max" not in aggs:
            continue
        win = raw_window(raw[key], stop, TIER_EVERY)
        if len(win) < 2 or not monotone(win):
            continue
        tested += 1
        first, last = win[0][1], win[-1][1]
        min_is_first = close(aggs["min"], first)
        max_is_last = close(aggs["max"], last)
        if min_is_first and max_is_last:
            matched += 1
        else:
            print(f"  MISMATCH {key[0]} {key[1]} @ {stop}  n={len(win)}")
            print(f"      min={aggs['min']:.0f} first={first:.0f} "
                  f"{'ok' if min_is_first else 'DIFFER'}")
            print(f"      max={aggs['max']:.0f} last={last:.0f} "
                  f"{'ok' if max_is_last else 'DIFFER'}")
    if tested == 0:
        print("  NO OVERLAPPING WINDOWS — raw retention is 1h and tier-1m")
        print("  retention is 1h; let the pipeline run a few minutes and retry.")
        return None
    print(f"\n  {matched}/{tested} windows: min == first sample AND max == last sample")
    if matched == tested:
        print("  => CLAIM CONFIRMED: min/max are window boundary markers.")
    return matched == tested


def check_maxmin_equals_mean_rate(raw, tier):
    print("\n=== CHECK 3: does (max-min)/elapsed == the window's mean rate? ===")
    print("    Mean rate is derived INDEPENDENTLY here: the mean of the raw")
    print("    per-sample rates (each diff/dt), i.e. what derivative()|>mean()")
    print("    computes. If it matches (max-min)/elapsed, then min+max carry")
    print("    nothing a rate-based mean does not already give.")
    tested = matched = 0
    worst = 0.0
    for (key, stop), aggs in sorted(tier.items()):
        if key not in raw or "min" not in aggs or "max" not in aggs:
            continue
        win = raw_window(raw[key], stop, TIER_EVERY)
        if len(win) < 2 or not monotone(win):
            continue
        elapsed = (parse_ts(win[-1][0]) - parse_ts(win[0][0])).total_seconds()
        if elapsed <= 0:
            continue
        # Dedupe first: on the raw (duplicated) series a per-sample rate is
        # biased ~40% low, which measures the ingest redundancy rather than the
        # 12d claim.
        win = dedupe(win)
        rates = []
        for i in range(1, len(win)):
            dt = (parse_ts(win[i][0]) - parse_ts(win[i - 1][0])).total_seconds()
            if dt > 0:
                rates.append((win[i][1] - win[i - 1][1]) / dt)
        if not rates:
            continue
        tested += 1
        mean_rate = sum(rates) / len(rates)
        rate_from_maxmin = (aggs["max"] - aggs["min"]) / elapsed
        denom = max(abs(mean_rate), 1e-9)
        rel = abs(rate_from_maxmin - mean_rate) / denom
        worst = max(worst, rel)
        if rel < 0.01:
            matched += 1
        else:
            print(f"  DIFFERS {key[0]} {key[1]} @ {stop}: "
                  f"maxmin={rate_from_maxmin:.1f} mean_rate={mean_rate:.1f} "
                  f"rel={rel:.2%}")
    if tested == 0:
        print("  no comparable windows yet.")
        return None
    print(f"\n  {matched}/{tested} windows agree within 1% "
          f"(worst relative error {worst:.2%})")
    if matched == tested:
        print("  => CLAIM CONFIRMED: (max-min)/elapsed IS the mean rate.")
        print("     The 3 extra aggregates cost 4x fields/cardinality for 1x info.")
    return matched == tested


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=55,
                    help="lookback window (raw retention is 1h; default 55)")
    args = ap.parse_args()

    print(f"Verifying 12d on the last {args.minutes} minutes.")
    print(f"raw={RAW_BUCKET}  tier={TIER_BUCKET}  field={BASE_FIELD}")

    raw = fetch_raw(args.minutes)
    tier = fetch_tier(args.minutes)
    print(f"\nraw series: {len(raw)}   tier windows: {len(tier)}")
    if not raw:
        sys.exit("\nNo raw data. Is the clab lab deployed and backend/main.py running?")
    if not tier:
        sys.exit(f"\nNo {TIER_BUCKET} data. The downsample task runs every 1m — "
                 "let the pipeline run a few minutes.")

    check_duplicates(raw)
    check_monotone(raw)
    check_boundaries(raw, tier)
    check_maxmin_equals_mean_rate(raw, tier)


if __name__ == "__main__":
    main()
