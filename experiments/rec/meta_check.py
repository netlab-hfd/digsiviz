#!/usr/bin/env python3
"""Heterogeneous-generator validation: intended schedule vs recorded trace.

The REC meta logs every dynamic-flow arrival (start offset, duration). The
intended aggregate at any instant is therefore reconstructable exactly:
    base_rate + flow_rate * (number of active dynamic flows)
Lay that against the pipeline-recorded rate (cached counter -> lattice rate)
and report how faithfully the twin carried the *mixed-rate* offered load.
This is the heterogeneous complement of E1's homogeneous calibration.

Usage: meta_check.py <event.meta>
"""
import math
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e3"))
from replay_tier import read_meta, load_counter_cache  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "influxdb"))
from e_repr import to_rate  # noqa: E402

GRID = 2
CAPACITY_MBPS = 10.0
MAX_LAG_S = 30


def intended_series(meta: Path, n_samples: int):
    """Intended aggregate Mbit/s on the GRID lattice, from the arrival log."""
    base = flow = dur = None
    arrivals = []  # (start_off, end_off)
    for line in meta.read_text().splitlines():
        if line.startswith("base_rate="):
            base = float(line.split("=")[1])
        elif line.startswith("flow_rate="):
            flow = float(line.split("=")[1])
        elif line.startswith("duration="):
            dur = int(line.split("=")[1])
        else:
            m = re.match(r"arrival slot=\d+ len=(\d+)s t=\+(\d+)s", line)
            if m:
                ln, off = int(m.group(1)), int(m.group(2))
                arrivals.append((off, off + ln))
            m = re.match(r"burst_start=\+(\d+)s flows=(\d+) len=(\d+)s", line)
            if m:
                off, k, ln = map(int, m.groups())
                arrivals += [(off, off + ln)] * k
    out = []
    for i in range(n_samples):
        t = i * GRID
        active = sum(1 for s, e in arrivals if s <= t < e)
        rate = (base + flow * active) / 1e6 if t < dur else 0.0
        out.append(rate)
    return out, len(arrivals)


def main():
    meta = Path(sys.argv[1])
    counter = load_counter_cache(meta)
    t0 = counter[0][0]
    rec_pts = to_rate(counter, GRID, t0)
    idx = {int((t - t0).total_seconds() // GRID): bps / 1e6 for t, bps in rec_pts}
    n = max(idx) + 1
    recorded = [idx.get(i, 0.0) for i in range(n)]
    intended, n_flows = intended_series(meta, n)

    # small alignment: pipeline poll/flush delay
    best, lag = -math.inf, 0
    for L in range(-MAX_LAG_S // GRID, MAX_LAG_S // GRID + 1):
        pairs = [(intended[i], recorded[i + L]) for i in range(n) if 0 <= i + L < n]
        s = sum(a * b for a, b in pairs) / len(pairs)
        if s > best:
            best, lag = s, L
    pairs = [(intended[i], recorded[i + lag]) for i in range(n) if 0 <= i + lag < n]
    it, rc = [p[0] for p in pairs], [p[1] for p in pairs]

    rmse = math.sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs))
    mae = sum(abs(a - b) for a, b in pairs) / len(pairs)
    mi, mr = statistics.mean(it), statistics.mean(rc)
    cov = sum((a - mi) * (b - mr) for a, b in pairs)
    corr = cov / math.sqrt(sum((a - mi) ** 2 for a in it) * sum((b - mr) ** 2 for b in rc))

    print(f"{meta.name}: {n_flows} dynamic flows, {len(pairs)} pts @{GRID}s, lag {lag * GRID:+d}s")
    print(f"  intended mean {mi:5.2f} | recorded mean {mr:5.2f} Mbit/s "
          f"(delivery {100 * mr / mi:6.2f} %)")
    print(f"  corr {corr:6.4f} | NRMSE {100 * rmse / CAPACITY_MBPS:5.2f} % cap | "
          f"MAE {100 * mae / CAPACITY_MBPS:5.2f} % cap")


if __name__ == "__main__":
    main()
