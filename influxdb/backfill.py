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

traffic-520w has NO cascade task at all (generate_manifest.cascade_capable): a
520-week window cannot fit inside a ten-year retention, so any task would
summarise the window from a fraction of itself. This script is its ONLY writer.

TIMESTAMPS match the cascade exactly -- same epoch-aligned grid, stamped at each
window's START (generate_manifest.TIMESRC). Backfilled and cascade-written points
therefore land on the same boundaries instead of interleaving half a window
apart. See build_lines() for the span snap that keeps that true where a tier's
retention is not a whole multiple of its step.

Schema matches what the cascade now writes:
  measurement = network_interface
  fields      = statistics_{out,in}-octets_{mean,min,max,median}
                RATES IN OCTETS PER SECOND (multiply by 8 for bits/s).
                Do NOT apply derivative() to these.
  tags        = hostname, interface_name, host, ip

CHANGED 2026-08-08 with the rate-first cascade migration. This script used to
write cumulative COUNTERS under the base field names, which meant the tier
buckets held two different naming conventions and two different units at once
(backfill: base names, counters; cascade: suffixed names, counters). Now both
write suffixed rate fields, so a tier bucket has exactly one schema and one
unit. This also closes the "two field-naming conventions" wart.

Each output point carries a real intra-window spread: the synthetic rate is
sampled SUBSAMPLES times inside the window and reduced to mean/min/max/median,
so min/max differ from the mean the way they do for real traffic. Under the old
counter-based cascade they could not -- min/max of a monotone counter are just
the window's endpoints.

Rate shape is scaled to the 10 Mbit/s model capacity used throughout the
experiments (4 Mbit/s baseline, one spike to ~10 Mbit/s), so the time machine
and the measured results speak in the same units.

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
# Retentions come from influxdb/manifest.yml and are DERIVED there by
# generate_manifest.retention(); run `python3 generate_manifest.py` to print the
# current table and re-sync the spans below if the tier ladder ever changes.
#
# Spans == retention, so every tier is backfilled across exactly as much history
# as it is allowed to keep. Under the old scheduler-derived retentions most tiers
# could only hold enough history to feed the next task (the 1h tier: 16h), which
# made the scroll jump straight from hours to years; the coverage term now gives
# each tier ~24 points of its own, so the time machine degrades smoothly.
TIERS = [
    ("traffic-1m",   60,           3600),          # 1m res,  last 1h    (ret 1h)
    ("traffic-5m",   300,          7200),          # 5m res,  last 2h    (ret 2h)
    ("traffic-1h",   3600,         86400),         # 1h res,  last 1d    (ret 1d)
    ("traffic-8h",   28800,        691200),        # 8h res,  last 8d    (ret 8d)
    ("traffic-1d",   86400,        2073600),       # 1d res,  last 24d   (ret 24d)
    ("traffic-1w",   604800,       14515200),      # 1w res,  last 24w   (ret 24w)
    ("traffic-4w",   2419200,      58060800),      # 4w res,  last ~1.8y (ret ~1.8y)
    ("traffic-12w",  7257600,      174182400),     # 12w res, last ~5.5y (ret ~5.5y)
    ("traffic-24w",  14515200,     314496000),     # 24w res, last ~10y  (ret ~10y)
    ("traffic-52w",  31449600,     314496000),     # 52w res, last ~10y  (ret ~10y)
    ("traffic-260w", 157248000,    314496000),     # 5y res,  last ~10y  (ret ~10y)
    ("traffic-520w", 314496000,    314496000),     # 10y res, last ~10y  (ret infinite)
]

# a couple of interfaces so the twin view looks populated
SERIES = [
    ("r1", "ethernet-1/1", "172.20.20.7"),
    ("r2", "ethernet-1/1", "172.20.20.8"),
]


# Sub-samples per output window, i.e. how much intra-window structure exists to
# be summarised. 30 mirrors the real 1m tier: 60s of 2s-lattice rate samples.
SUBSAMPLES = 30

# Scaled to the 10 Mbit/s modelled link capacity of the experiments.
BASELINE_OCTETS_S = 4e6 / 8       # 4 Mbit/s
SWING_OCTETS_S = 2e6 / 8          # +-2 Mbit/s diurnal
SPIKE_OCTETS_S = 6e6 / 8          # one event reaching ~10 Mbit/s total


def rate_octets_per_s(x, phase, spike):
    """Synthetic rate in octets/s at fractional position x in [0,1): diurnal
    sine + noise, plus a saturation event when `spike` is set."""
    diurnal = SWING_OCTETS_S * math.sin(2 * math.pi * x * 3 + phase)
    noise = random.uniform(-SWING_OCTETS_S * 0.1, SWING_OCTETS_S * 0.1)
    return max(1e4, BASELINE_OCTETS_S + diurnal + noise
               + (SPIKE_OCTETS_S if spike else 0.0))


def aggregates(x0, x1, phase, spike):
    """mean/min/max/median of the rate across one window [x0, x1)."""
    vals = sorted(
        rate_octets_per_s(x0 + (x1 - x0) * (k / SUBSAMPLES), phase, spike)
        for k in range(SUBSAMPLES)
    )
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return {
        "mean": sum(vals) / len(vals),
        "min": vals[0],
        "max": vals[-1],
        "median": median,
    }


def build_lines(step, span):
    lines = []
    n = max(1, span // step)
    # Same epoch-aligned grid aggregateWindow uses, so backfilled points land on
    # the boundaries the cascade would have written to rather than between them.
    base = (NOW // step) * step
    # Snap the span to a whole number of windows: where retention is not an
    # exact multiple of the step (traffic-24w), base - span would otherwise sit
    # off-grid and every point with it.
    span = n * step
    for si, (host, intf, ip) in enumerate(SERIES):
        for i in range(n):
            # Stamped at the window's START, matching the cascade's uniform
            # timeSrc: "_start" (see generate_manifest.TIMESRC). Starting at
            # i+1 keeps the oldest point strictly INSIDE the retention window;
            # a point exactly on the lower bound is rejected as expired.
            ts = base - span + (i + 1) * step
            # The spike occupies part of ONE window, so that window's max is
            # well above its mean -- which is the whole point of storing both.
            spike = n > 4 and i == n // 2
            x0, x1 = i / n, (i + 1) / n
            out = aggregates(x0, x1, si, spike)
            inn = aggregates(x0, x1, si + 1.5, spike)
            fields = ",".join(
                [f"statistics_out-octets_{a}={out[a]:.0f}" for a in out]
                + [f"statistics_in-octets_{a}={inn[a]:.0f}" for a in inn]
            )
            lines.append(
                f"network_interface,hostname={host},interface_name={intf},"
                f"host=synthetic,ip={ip} {fields} {ts}"
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
