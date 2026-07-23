#!/usr/bin/env python3
"""12d burst-placement analysis: per window, compare tier-1m min/max against
the raw counter window and locate the true rate peak.

Expected result (the figure's data): min == window's first raw sample and
max == its last in EVERY window, byte volume (max-min) ~constant, while the
raw peak's position inside the window tracks the burst offset — i.e. the
stored aggregates cannot distinguish burst-at-3s from burst-at-50s.

Usage: analyze_blindness.py <out.csv> <T:offset> [...]   (T = window start epoch)
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "influxdb"))
from e_repr import flux, dedupe, to_rate, parse_ts, MEASUREMENT  # noqa: E402

HOSTNAME = "r1"
IFACE = "ethernet-1/1"
RAW_FIELD = "statistics_out-octets"
GRID = 2  # s; honest rate lattice (JOURNAL 14)


def dt(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def tier_minmax(t_stop):
    """tier-1m min/max stamped at the window's STOP time (JOURNAL 13)."""
    rows = flux(f'''
from(bucket: "traffic-1m")
  |> range(start: {t_stop - 1}, stop: {t_stop + 1})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r._field == "{RAW_FIELD}_min" or r._field == "{RAW_FIELD}_max")
  |> filter(fn: (r) => r.hostname == "{HOSTNAME}" and r.interface_name == "{IFACE}")
  |> keep(columns: ["_time", "_field", "_value"])
''')
    out = {}
    for r in rows:
        if parse_ts(r["_time"]) == dt(t_stop):
            out[r["_field"].rsplit("_", 1)[1]] = float(r["_value"])
    return out.get("min"), out.get("max")


def raw_window(t0, t1):
    rows = flux(f'''
from(bucket: "infldb")
  |> range(start: {t0}, stop: {t1})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r._field == "{RAW_FIELD}")
  |> filter(fn: (r) => r.hostname == "{HOSTNAME}" and r.interface_name == "{IFACE}")
  |> keep(columns: ["_time", "_value"])
''')
    return dedupe(sorted((parse_ts(r["_time"]), float(r["_value"])) for r in rows))


def main():
    out_path = Path(sys.argv[1])
    header = ["offset_s", "tier_min", "tier_max", "raw_first", "raw_last",
              "min_is_first", "max_is_last", "volume_MB",
              "true_peak_mbps", "peak_pos_s"]
    print(("{:>10} " * len(header)).format(*header))
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for spec in sys.argv[2:]:
            t0_e, off = (int(x) for x in spec.split(":"))
            t1_e = t0_e + 60
            tmin, tmax = tier_minmax(t1_e)
            raw = raw_window(t0_e, t1_e)
            if tmin is None or tmax is None or not raw:
                print(f"window {t0_e}: MISSING tier point or raw data — skipped")
                continue
            first, last = raw[0][1], raw[-1][1]
            rate = to_rate(raw, GRID, dt(t0_e))  # [(datetime, bits/s)]
            if not rate:
                print(f"window {t0_e}: rate lattice empty — skipped")
                continue
            pk_t, pk_v = max(rate, key=lambda p: p[1])
            row = [off, tmin, tmax, first, last,
                   tmin == first, tmax == last,
                   round((tmax - tmin) / 1e6, 2),
                   round(pk_v / 1e6, 1),
                   round((pk_t - dt(t0_e)).total_seconds(), 1)]
            w.writerow(row)
            print(("{:>10} " * len(row)).format(*(str(x) for x in row)))


if __name__ == "__main__":
    main()
