#!/usr/bin/env python3
"""E1 analysis: per-config achieved vs offered, loss, CPU. mean +/- std over reps.

Usage: python3 analyze_e1.py results/<timestamp>/
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

TOTAL_OFFERED_MBIT = 10.0


def flow_stats(path: Path):
    """Return (recv_mbps, lost_pct) from one iperf3 --json output, or None."""
    try:
        data = json.loads(path.read_text())
        end = data["end"]["sum"]
        return end["bits_per_second"] / 1e6, end.get("lost_percent", 0.0)
    except (json.JSONDecodeError, KeyError):
        return None


def cpu_series(path: Path, col: int):
    vals = []
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) > col:
                try:
                    vals.append(float(parts[col].rstrip("%")))
                except ValueError:
                    pass
    return vals


def container_cpu(path: Path):
    """Mean CPU%% per container name."""
    per = defaultdict(list)
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3:
                try:
                    per[parts[1]].append(float(parts[2].rstrip("%")))
                except ValueError:
                    pass
    return {name: statistics.mean(v) for name, v in per.items() if v}


def main(outdir: Path):
    # group files: n{n}_rep{r}_flow{i}.json
    runs = defaultdict(list)  # n -> list of per-rep dicts
    tags = sorted({p.name.split("_flow")[0] for p in outdir.glob("n*_rep*_flow*.json")})
    for tag in tags:
        n = int(tag.split("_")[0][1:])
        flows = [flow_stats(p) for p in sorted(outdir.glob(f"{tag}_flow*.json"))]
        ok = [f for f in flows if f]
        if not ok:
            print(f"WARN {tag}: no parseable flows", file=sys.stderr)
            continue
        total_recv = sum(f[0] for f in ok)
        mean_loss = statistics.mean(f[1] for f in ok)
        host = cpu_series(outdir / f"{tag}_hostcpu.log", 1)
        cont = container_cpu(outdir / f"{tag}_containercpu.log")
        runs[n].append({
            "tag": tag,
            "flows_ok": len(ok),
            "flows_expected": n,
            "total_recv_mbps": total_recv,
            "achieved_pct": 100.0 * total_recv / TOTAL_OFFERED_MBIT,
            "mean_loss_pct": mean_loss,
            "host_cpu_mean": statistics.mean(host) if host else float("nan"),
            "host_cpu_max": max(host) if host else float("nan"),
            "cont_cpu": cont,
        })

    def ms(vals):
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) > 1 else 0.0
        return f"{m:6.2f} ± {s:5.2f}"

    print(f"{'n':>3} {'reps':>4} {'achieved Mbit/s':>17} {'achieved %':>12} "
          f"{'loss %':>12} {'host CPU %':>13} {'r1+r2 CPU %':>12}")
    for n in sorted(runs):
        reps = runs[n]
        fwd = []
        for r in reps:
            fwd.append(sum(v for k, v in r["cont_cpu"].items() if k.endswith(("r1", "r2"))))
        print(f"{n:>3} {len(reps):>4} "
              f"{ms([r['total_recv_mbps'] for r in reps]):>17} "
              f"{ms([r['achieved_pct'] for r in reps]):>12} "
              f"{ms([r['mean_loss_pct'] for r in reps]):>12} "
              f"{ms([r['host_cpu_mean'] for r in reps]):>13} "
              f"{ms(fwd) if fwd else 'n/a':>12}")
        incomplete = [r["tag"] for r in reps if r["flows_ok"] != r["flows_expected"]]
        if incomplete:
            print(f"    WARN incomplete flow sets: {incomplete}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
