#!/usr/bin/env python3
"""E3 — deterministic replay driver.

Reads a recorded event's rate trace from InfluxDB, downsamples it to a target
granularity tier (derive->aggregate order, per JOURNAL 12d/14), then re-creates
it in the twin as piecewise-constant `iperf3 -u -b <rate>` segments
(zero-order hold per tier point). NO randomness here — randomness lives in REC.

The replayed traffic is recorded by the same gNMI->Kafka->Telegraf->InfluxDB
pipeline; analyze_e3.py later compares that recording against the original.

Usage:
  replay_tier.py --meta ../rec/events/<event>.meta --tier 60
  --tier 0  = raw control row: replays the lattice rate itself (E_real alone).
              Segment floor SEG_MIN applies — iperf3 process startup makes
              sub-5s segments dishonest, so the "raw" control is a 5 s hold.
"""
import argparse
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/allan/uni/research_project/projects/digsiviz/influxdb")
from e_repr import flux, dedupe, to_rate, parse_ts, MEASUREMENT, FIELD  # noqa: E402

H1 = "clab-ma-fp-stumpf-h1"
DST = "10.0.2.102"
PORT = 5201
RAW_BUCKET = "infldb"
HOSTNAME = "r1"                # r1 -> r2 is the observed link (out-octets)
IFACE = "ethernet-1/1"
GRID = 2                       # s; honest rate lattice (JOURNAL 14)
SEG_MIN = 5                    # s; smallest iperf3 segment worth running
CAPACITY_BPS = 10_000_000


def read_meta(path: Path):
    kv = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k] = v
    return int(kv["start_epoch"]), int(kv["end_epoch"]), kv.get("type", "?")


def fetch_window(start_epoch, end_epoch):
    rows = flux(f'''
from(bucket: "{RAW_BUCKET}")
  |> range(start: {start_epoch}, stop: {end_epoch})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r._field == "{FIELD}")
  |> filter(fn: (r) => r.hostname == "{HOSTNAME}" and r.interface_name == "{IFACE}")
  |> keep(columns: ["_time", "_value"])
''')
    samples = sorted((parse_ts(r["_time"]), float(r["_value"])) for r in rows)
    if not samples:
        sys.exit(f"no raw data for {HOSTNAME}/{IFACE} in window — "
                 "did the event record through the pipeline, and is it still inside "
                 "infldb's 1h retention?")
    return dedupe(samples)


def tier_segments(rate, t0, every):
    """derive->aggregate: mean of the lattice rate per tier window.
    Returns [(offset_s, length_s, bps)]."""
    wins = defaultdict(list)
    for t, bps in rate:
        wins[int((t - t0).total_seconds() // every)].append(bps)
    return [(w * every, every, sum(v) / len(v)) for w, v in sorted(wins.items())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--tier", type=int, required=True,
                    help="tier window seconds; 0 = raw control (SEG_MIN hold)")
    args = ap.parse_args()

    meta = Path(args.meta)
    start, end, etype = read_meta(meta)
    counter = fetch_window(start, end)
    t0 = counter[0][0]
    rate = to_rate(counter, GRID, t0)
    if not rate:
        sys.exit("empty rate series")

    every = args.tier if args.tier > 0 else SEG_MIN
    segs = tier_segments(rate, t0, every)
    total = sum(l for _, l, _ in segs)
    print(f"replaying {etype} event: {len(segs)} segments x {every}s "
          f"(~{total}s), tier={'raw' if args.tier == 0 else args.tier}")

    replay_t0 = time.time()
    for off, length, bps in segs:
        # honest zero-order hold: stay on schedule even if a segment overran
        ahead = (replay_t0 + off) - time.time()
        if ahead > 0:
            time.sleep(ahead)
        if bps < 1000:            # effectively idle window: send nothing
            continue
        bps_i = min(int(bps), CAPACITY_BPS)
        subprocess.run(
            ["docker", "exec", H1, "iperf3", "-u", "-c", DST, "-p", str(PORT),
             "-b", str(bps_i), "-t", str(int(length))],
            capture_output=True, text=True,
        )
    replay_t1 = time.time()

    out = meta.with_suffix(f".replay_tier{args.tier}")
    out.write_text(
        f"source_meta={meta}\ntier={args.tier}\nsegment={every}\n"
        f"replay_start_epoch={int(replay_t0)}\nreplay_end_epoch={int(replay_t1)}\n"
        f"hostname={HOSTNAME}\ninterface={IFACE}\n")
    print(f"replay done -> {out}")
    print("NOTE: analyze within infldb's 1h retention window.")


if __name__ == "__main__":
    main()
