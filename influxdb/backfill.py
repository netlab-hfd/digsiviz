#!/usr/bin/env python3
"""
Backfill synthetic traffic into every downsample tier bucket so the time
machine visibly shows years of history (dense recent, coarse old).

WHY direct-write and not the cascade: downsample tasks only process recent
data going forward, and raw `infldb` retains only 1h. They will never build
year-old tiers. So we write backdated points DIRECTLY into each tier bucket.

CONSTRAINT: each point must fall inside its bucket's retention window, or
InfluxDB drops it as already-expired. So each tier is backfilled across its
OWN retention span at its OWN resolution. The multi-year scroll comes from the
coarse buckets (52w/260w/520w), which have multi-year retention.

Schema matches the live pipeline + the Grafana dashboard (Task B):
  measurement = network_interface
  fields      = statistics_out-octets, statistics_in-octets  (cumulative
                counters; Grafana applies derivative() -> bps)
  tags        = hostname, interface_name, host, ip
NOTE: base field names (not the _mean/_min/_max/_median suffixes the real
cascade will use) so the existing Grafana panel renders this unchanged. This
script is a mechanics test of buckets + time machine, not the research path.

Idempotent: rewriting the same (bucket, tags, field, timestamp) overwrites.
"""

import math
import random
import subprocess
import time

ORG = "myorg"
TOKEN = "mytoken"
CONTAINER = "influxdb"

NOW = int(time.time())

# (bucket, step_seconds, span_seconds) — span kept <= bucket retention.
# retention values come from influxdb/manifest.yml.
TIERS = [
    ("traffic-1m",   60,           3600),          # 1m res,  last 1h   (ret 1h)
    ("traffic-5m",   300,          7200),          # 5m res,  last 2h   (ret 2h)
    ("traffic-1h",   3600,         57600),         # 1h res,  last 16h  (ret 16h)
    ("traffic-8h",   28800,        172800),        # 8h res,  last 2d   (ret 2d)
    ("traffic-1d",   86400,        1209600),       # 1d res,  last 2w   (ret 2w)
    ("traffic-1w",   604800,       4838400),       # 1w res,  last 8w   (ret 8w)
    ("traffic-4w",   2419200,      14515200),      # 4w res,  last 24w  (ret 24w)
    ("traffic-12w",  7257600,      29030400),      # 12w res, last 48w  (ret 48w)
    ("traffic-24w",  14515200,     62899200),      # 24w res, last ~2y  (ret ~2y)
    ("traffic-52w",  31449600,     314496000),     # 52w res, last ~10y (ret ~10y)
    ("traffic-260w", 157248000,    628992000),     # 5y res,  last ~20y (ret ~20y)
    ("traffic-520w", 314496000,    314496000),     # 10y res, last ~10y (ret ~10y)
]

# a couple of interfaces so the twin view looks populated
SERIES = [
    ("r1", "ethernet-1/1", "172.20.20.7"),
    ("r2", "ethernet-1/1", "172.20.20.8"),
]


def rate_bytes_per_s(i, n, phase):
    """Synthetic bitrate shape: diurnal sine + noise + one saturation spike."""
    base = 6e6                                   # ~6 MB/s baseline
    diurnal = 3e6 * math.sin(2 * math.pi * (i / max(n, 1)) * 3 + phase)
    noise = random.uniform(-5e5, 5e5)
    spike = 20e6 if (n > 4 and i == n // 2) else 0.0   # a saturation event mid-window
    return max(1e5, base + diurnal + noise + spike)


def build_lines(step, span):
    lines = []
    n = max(1, span // step)
    for si, (host, intf, ip) in enumerate(SERIES):
        out_ctr = random.uniform(1e9, 5e9)
        in_ctr = random.uniform(1e9, 5e9)
        for i in range(n):
            # +step so the oldest point sits strictly INSIDE the retention
            # window; a point exactly on the lower bound is rejected.
            ts = NOW - span + (i + 1) * step
            out_ctr += rate_bytes_per_s(i, n, phase=si) * step
            in_ctr += rate_bytes_per_s(i, n, phase=si + 1.5) * step
            lines.append(
                f"network_interface,hostname={host},interface_name={intf},"
                f"host=synthetic,ip={ip} "
                f"statistics_out-octets={out_ctr:.0f},"
                f"statistics_in-octets={in_ctr:.0f} {ts}"
            )
    return lines


def write_bucket(bucket, lines):
    lp = "\n".join(lines)
    res = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "influx", "write",
         "--bucket", bucket, "--org", ORG, "--token", TOKEN, "--precision", "s"],
        input=lp, text=True, capture_output=True,
    )
    ok = res.returncode == 0
    print(f"  {bucket:<14} {len(lines):>4} pts  {'OK' if ok else 'FAIL'}"
          + ("" if ok else f"\n    {res.stderr.strip()}"))
    return ok


def main():
    print(f"Backfilling {len(TIERS)} tiers x {len(SERIES)} series ...")
    allok = True
    for bucket, step, span in TIERS:
        allok &= write_bucket(bucket, build_lines(step, span))
    print("Done." if allok else "Done WITH ERRORS (see above).")


if __name__ == "__main__":
    main()
