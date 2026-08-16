#!/usr/bin/env python3
"""12d burst-placement analysis: per window, compare tier-1m min/max against
the raw counter window and locate the true rate peak.

Expected result (the figure's data): min == window's first raw sample and
max == its last in EVERY window, byte volume (max-min) ~constant, while the
raw peak's position inside the window tracks the burst offset — i.e. the
stored aggregates cannot distinguish burst-at-3s from burst-at-50s.

Usage: analyze_blindness.py [--rate] <out.csv> <T:offset> [...]
       (T = window start epoch)

--rate switches to the RATE-FIRST cascade (2026-08-08 migration): the tier now
stores mean/min/max/median OF THE RATE in octets/s, so the counter-endpoint
checks above are meaningless and the interesting question is the opposite one —
does the stored max now equal the true peak, at every placement? Same driver,
same windows, same figure; the two modes produce the before/after pair.
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


def tier_aggs(t_stop):
    """All four tier-1m aggregates for the window stamped at t_stop.
    Under the rate-first cascade these are octets/s, not counter values."""
    rows = flux(f'''
from(bucket: "traffic-1m")
  |> range(start: {t_stop - 1}, stop: {t_stop + 1})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r._field =~ /^{RAW_FIELD}_/)
  |> filter(fn: (r) => r.hostname == "{HOSTNAME}" and r.interface_name == "{IFACE}")
  |> keep(columns: ["_time", "_field", "_value"])
''')
    out = {}
    for r in rows:
        if parse_ts(r["_time"]) == dt(t_stop):
            out[r["_field"].rsplit("_", 1)[1]] = float(r["_value"])
    return out


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
    args = sys.argv[1:]
    rate_mode = "--rate" in args
    if rate_mode:
        args.remove("--rate")
    out_path = Path(args[0])

    if rate_mode:
        header = ["offset_s", "tier_mean_mbps", "tier_min_mbps", "tier_max_mbps",
                  "tier_median_mbps", "raw_mean_mbps", "raw_peak_mbps",
                  "peak_pos_s", "max_err_pct", "max_over_mean"]
    else:
        header = ["offset_s", "tier_min", "tier_max", "raw_first", "raw_last",
                  "min_is_first", "max_is_last", "volume_MB",
                  "true_peak_mbps", "peak_pos_s"]
    print(("{:>16} " * len(header)).format(*header))
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for spec in args[1:]:
            t0_e, off = (int(x) for x in spec.split(":"))
            t1_e = t0_e + 60
            raw = raw_window(t0_e, t1_e)
            if not raw:
                print(f"window {t0_e}: MISSING raw data — skipped")
                continue
            rate = to_rate(raw, GRID, dt(t0_e))  # [(datetime, bits/s)]
            if not rate:
                print(f"window {t0_e}: rate lattice empty — skipped")
                continue
            pk_t, pk_v = max(rate, key=lambda p: p[1])
            peak_pos = round((pk_t - dt(t0_e)).total_seconds(), 1)

            if rate_mode:
                a = tier_aggs(t1_e)
                if not all(k in a for k in ("mean", "min", "max", "median")):
                    print(f"window {t0_e}: MISSING tier aggregates — skipped")
                    continue
                # tier values are octets/s; to_rate() already returns bits/s
                mb = {k: v * 8.0 / 1e6 for k, v in a.items()}
                raw_mean = sum(v for _, v in rate) / len(rate) / 1e6
                row = [off,
                       round(mb["mean"], 3), round(mb["min"], 3),
                       round(mb["max"], 3), round(mb["median"], 3),
                       round(raw_mean, 3), round(pk_v / 1e6, 3),
                       peak_pos,
                       round((mb["max"] - pk_v / 1e6) / (pk_v / 1e6) * 100, 1),
                       round(mb["max"] / mb["mean"], 2) if mb["mean"] else None]
            else:
                tmin, tmax = tier_minmax(t1_e)
                if tmin is None or tmax is None:
                    print(f"window {t0_e}: MISSING tier point — skipped")
                    continue
                first, last = raw[0][1], raw[-1][1]
                row = [off, tmin, tmax, first, last,
                       tmin == first, tmax == last,
                       round((tmax - tmin) / 1e6, 2),
                       round(pk_v / 1e6, 1), peak_pos]
            w.writerow(row)
            print(("{:>16} " * len(row)).format(*(str(x) for x in row)))


if __name__ == "__main__":
    main()
