#!/usr/bin/env python3
"""E3 — fidelity metrics: original event vs its replay (the locked package,
JOURNAL 15):

  1. timing  — cross-correlation lag (s)
  2. shape   — capacity-normalized NRMSE (% of 10 Mbit/s) after alignment; MAE too
  3. chars   — preserved-ratios replay/original for mean, max, std

Both traces come from the SAME instrument (raw infldb counter, GRID lattice),
so instrument bias cancels. Compare at raw resolution per JOURNAL 12b.

Usage: analyze_e3.py --replay-meta ../rec/events/<event>.replay_tier60
"""
import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_tier import fetch_window, read_meta, get_counter  # noqa: E402
sys.path.insert(0, "/home/allan/uni/research_project/projects/digsiviz/influxdb")
from e_repr import to_rate  # noqa: E402

GRID = 2
CAPACITY_MBPS = 10.0
MAX_LAG_S = 60


def series(start, end, meta=None):
    """meta given -> cache-first read (original event, may have expired from
    infldb); meta None -> live fetch (replay trace, always < 1h old)."""
    counter = get_counter(meta, start, end) if meta else fetch_window(start, end)
    t0 = counter[0][0]
    rate = to_rate(counter, GRID, t0)
    # dense lattice array (fill gaps with 0 = idle)
    idx = {int((t - t0).total_seconds() // GRID): bps / 1e6 for t, bps in rate}
    n = max(idx) + 1
    return [idx.get(i, 0.0) for i in range(n)]


def xcorr_lag(a, b, max_lag):
    """lag (in samples) shifting b to best match a, by max normalized dot."""
    best, best_lag = -math.inf, 0
    for lag in range(-max_lag, max_lag + 1):
        s = n = 0
        for i in range(len(a)):
            j = i + lag
            if 0 <= j < len(b):
                s += a[i] * b[j]
                n += 1
        if n > 10 and s / n > best:
            best, best_lag = s / n, lag
    return best_lag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-meta", required=True)
    args = ap.parse_args()

    rmeta = {}
    for line in Path(args.replay_meta).read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rmeta[k] = v

    src = Path(rmeta["source_meta"])
    o_start, o_end, etype = read_meta(src)
    orig = series(o_start, o_end, meta=src)
    repl = series(int(rmeta["replay_start_epoch"]), int(rmeta["replay_end_epoch"]))

    lag = xcorr_lag(orig, repl, MAX_LAG_S // GRID)
    aligned = [(orig[i], repl[i + lag]) for i in range(len(orig))
               if 0 <= i + lag < len(repl)]
    if len(aligned) < 10:
        sys.exit("traces barely overlap after alignment — check windows")
    o = [p[0] for p in aligned]
    r = [p[1] for p in aligned]

    rmse = math.sqrt(sum((a - b) ** 2 for a, b in aligned) / len(aligned))
    mae = sum(abs(a - b) for a, b in aligned) / len(aligned)

    def ratio(f):
        den = f(o)
        return f(r) / den if den else float("nan")

    tier = rmeta["tier"]
    print(f"event={etype} tier={'raw' if tier == '0' else tier + 's'} "
          f"n={len(aligned)} pts @{GRID}s")
    print(f"  timing lag        : {lag * GRID:+d} s")
    print(f"  shape NRMSE       : {100 * rmse / CAPACITY_MBPS:6.2f} % of capacity")
    print(f"  shape MAE         : {100 * mae / CAPACITY_MBPS:6.2f} % of capacity")
    print(f"  mean preserved    : {ratio(statistics.mean):6.3f}")
    print(f"  max  preserved    : {ratio(max):6.3f}")
    print(f"  std  preserved    : {ratio(statistics.stdev):6.3f}")
    # machine-readable line for aggregation across (event, tier, rep)
    print(f"CSV,{etype},{tier},{lag * GRID},{100 * rmse / CAPACITY_MBPS:.3f},"
          f"{100 * mae / CAPACITY_MBPS:.3f},{ratio(statistics.mean):.4f},"
          f"{ratio(max):.4f},{ratio(statistics.stdev):.4f}")


if __name__ == "__main__":
    main()
