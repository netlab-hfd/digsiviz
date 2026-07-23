#!/usr/bin/env python3
"""E2 analysis: does the generator degrade over time?

Per run: sum receiver-side per-interval rates across flows -> aggregate rate
time series. Drift = linear-regression slope of that series (Mbit/s per hour)
+ first-quarter vs last-quarter mean comparison. CPU trend likewise.

Usage: python3 analyze_e2.py results/<timestamp>/
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def interval_series(path: Path):
    """[(t_second, mbps)] receiver-side per interval for one flow."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    out = []
    for iv in data.get("intervals", []):
        s = iv["sum"]
        out.append((s["start"], s["bits_per_second"] / 1e6))
    return out


def slope_per_hour(pairs):
    """Least-squares slope in Mbit/s per hour."""
    n = len(pairs)
    if n < 2:
        return float("nan")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in pairs) / denom * 3600


def quarter_means(pairs):
    q = max(1, len(pairs) // 4)
    first = statistics.mean(v for _, v in pairs[:q])
    last = statistics.mean(v for _, v in pairs[-q:])
    return first, last


def main(outdir: Path):
    tags = sorted({p.name.split("_flow")[0] for p in outdir.glob("d*_rep*_flow*.json")},
                  key=lambda t: (int(t.split("_")[0][1:]), t))
    by_dur = defaultdict(list)
    for tag in tags:
        dur = int(tag.split("_")[0][1:])
        # merge flows: per interval-start-second, sum across flows
        acc = defaultdict(float)
        for p in sorted(outdir.glob(f"{tag}_flow*.json")):
            for t, mbps in interval_series(p):
                acc[round(t)] += mbps
        series = sorted(acc.items())
        if not series:
            print(f"WARN {tag}: empty", file=sys.stderr)
            continue
        first, last = quarter_means(series)
        # host CPU trend
        cpu = []
        f = outdir / f"{tag}_hostcpu.log"
        if f.exists():
            for line in f.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2:
                    cpu.append((int(parts[0]), float(parts[1])))
        cpu_rel = [(t - cpu[0][0], v) for t, v in cpu] if cpu else []
        by_dur[dur].append({
            "tag": tag,
            "mean_mbps": statistics.mean(v for _, v in series),
            "slope_mbps_per_h": slope_per_hour(series),
            "q1_mbps": first,
            "q4_mbps": last,
            "cpu_mean": statistics.mean(v for _, v in cpu_rel) if cpu_rel else float("nan"),
            "cpu_slope_per_h": slope_per_hour(cpu_rel) if cpu_rel else float("nan"),
        })

    print(f"{'dur s':>6} {'rep':>4} {'mean Mbit/s':>12} {'drift Mb/s/h':>13} "
          f"{'Q1 mean':>9} {'Q4 mean':>9} {'CPU %':>7} {'CPU %/h':>8}")
    for dur in sorted(by_dur):
        for r in by_dur[dur]:
            print(f"{dur:>6} {r['tag'].split('rep')[1]:>4} {r['mean_mbps']:>12.2f} "
                  f"{r['slope_mbps_per_h']:>13.3f} {r['q1_mbps']:>9.2f} {r['q4_mbps']:>9.2f} "
                  f"{r['cpu_mean']:>7.1f} {r['cpu_slope_per_h']:>8.2f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
