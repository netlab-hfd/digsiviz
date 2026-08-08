#!/usr/bin/env python3
"""
Measure the storage cost of the pipeline: series cardinality, point counts, and
on-disk bytes, per bucket. This is the RQ1 evidence, and it is what makes the
"dry the dataseries up" claim a measurement instead of an assertion.

Why not `influxdb.cardinality()`: in InfluxDB 2.7 OSS it reported 13 series for
a bucket that demonstrably held 713. Series are enumerated here by grouping on
every tag key and counting the resulting tables, which agrees with the schema
and is reproducible.

What the numbers mean (measured 2026-08-08, before any field filtering):
  * infldb held 713 series -- 701 network_interface + 12 stats -- because
    gnmiclient.py flattens the whole gNMI interface subtree into 78 numeric
    fields per interface, while the entire study reads 2 of them.
  * every tier bucket holds exactly 72 series = 9 tag-sets (3 routers x 3
    interfaces) x 8 fields (2 base x mean/min/max/median). Independent of
    traffic volume and flow count; linear in the number of tiers.
  * 90.5 % of on-disk bytes were the fixed _series index: each bucket
    preallocates 8 partitions x 4 MiB = 32 MiB whether it holds anything or
    not (traffic-8h had zero series and still occupied 32.0 MiB).

Usage:
    # with the stack up (only the influxdb service is required):
    python3 measure_storage.py --label before
    # ... apply the telegraf fieldinclude filter, let traffic run, then:
    python3 measure_storage.py --label after --csv-out storage_before_after.csv

Rows accumulate in the CSV, so one file holds the before/after comparison.
"""

import argparse
import csv
import io
import os
import subprocess
import sys

ORG = os.environ.get("INFLUX_ORG", "myorg")
TOKEN = os.environ.get("INFLUX_TOKEN", "mytoken")
CONTAINER = os.environ.get("INFLUX_CONTAINER", "influxdb")

DATA_DIR = "/var/lib/influxdb2/engine/data"
# Tags that make up a series key here. Grouping on all of them and counting the
# resulting tables IS the series count.
TAG_KEYS = ["_measurement", "_field", "host", "hostname", "interface_name", "ip"]
# Wide enough to cover the backfilled year-scale tiers.
RANGE_START = "-25y"

TIERS = ["1m", "5m", "1h", "8h", "1d", "1w", "4w", "12w", "24w", "52w", "260w", "520w"]
BUCKETS = ["infldb"] + [f"traffic-{t}" for t in TIERS]


def sh(args, stdin=None):
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"command failed: {' '.join(args)}\n{proc.stderr}")
    return proc.stdout


def flux(query):
    """Run a Flux query in the influxdb container, return parsed rows."""
    out = sh(
        ["docker", "exec", "-i", CONTAINER,
         "influx", "query", "--org", ORG, "--token", TOKEN, "--raw", "-"],
        stdin=query,
    )
    return parse_annotated_csv(out)


def parse_annotated_csv(text):
    """InfluxDB annotated CSV -> list of dicts."""
    rows, header = [], None
    for line in io.StringIO(text):
        line = line.rstrip("\n")
        if not line.strip():
            header = None
            continue
        if line.startswith("#"):
            continue
        cells = next(csv.reader([line]))
        if header is None:
            header = cells
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def series_count(bucket):
    group_cols = ", ".join(f'"{k}"' for k in TAG_KEYS)
    rows = flux(
        f'from(bucket:"{bucket}") |> range(start:{RANGE_START})\n'
        f'  |> group(columns:[{group_cols}]) |> count() |> group()\n'
        f'  |> keep(columns:["_value"])'
    )
    return len(rows)


def point_count(bucket):
    rows = flux(
        f'from(bucket:"{bucket}") |> range(start:{RANGE_START})\n'
        f'  |> group() |> count()'
    )
    return int(rows[0]["_value"]) if rows else 0


def field_count(bucket, measurement="network_interface"):
    rows = flux(
        f'import "influxdata/influxdb/schema"\n'
        f'schema.measurementFieldKeys(bucket:"{bucket}", measurement:"{measurement}",'
        f' start:{RANGE_START})'
    )
    return len(rows)


def bucket_ids():
    """name -> id, from `influx bucket list`."""
    out = sh(["docker", "exec", CONTAINER,
              "influx", "bucket", "list", "--org", ORG, "--token", TOKEN])
    ids = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            ids[parts[1]] = parts[0]
    return ids


def disk_bytes(bucket_id):
    """(total, series_index, data) bytes for one bucket's shard directory."""
    out = sh(["docker", "exec", CONTAINER, "sh", "-c",
              f'du -sb {DATA_DIR}/{bucket_id} 2>/dev/null; '
              f'du -sb {DATA_DIR}/{bucket_id}/_series 2>/dev/null'])
    vals = [int(l.split()[0]) for l in out.splitlines() if l.strip()]
    if not vals:
        return (0, 0, 0)
    total = vals[0]
    series = vals[1] if len(vals) > 1 else 0
    return (total, series, total - series)


MIB = 1024 * 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="",
                    help="tag these rows, e.g. before / after")
    ap.add_argument("--csv-out", default="",
                    help="append rows to this CSV (created with a header if new)")
    args = ap.parse_args()

    ids = bucket_ids()
    rows = []
    for b in BUCKETS:
        bid = ids.get(b)
        if bid is None:
            print(f"  (skipping {b}: no such bucket)", file=sys.stderr)
            continue
        total, series_idx, data = disk_bytes(bid)
        rows.append({
            "label": args.label,
            "bucket": b,
            "series": series_count(b),
            "fields": field_count(b),
            "points": point_count(b),
            "total_bytes": total,
            "series_index_bytes": series_idx,
            "data_bytes": data,
        })

    hdr = f"{'bucket':14s} {'series':>7s} {'fields':>7s} {'points':>12s} " \
          f"{'total MiB':>10s} {'_series MiB':>12s} {'data MiB':>9s}"
    print(hdr)
    print("-" * len(hdr))
    tot = {k: 0 for k in ("series", "points", "total_bytes",
                          "series_index_bytes", "data_bytes")}
    for r in rows:
        print(f"{r['bucket']:14s} {r['series']:7d} {r['fields']:7d} {r['points']:12d} "
              f"{r['total_bytes']/MIB:10.1f} {r['series_index_bytes']/MIB:12.1f} "
              f"{r['data_bytes']/MIB:9.2f}")
        for k in tot:
            tot[k] += r[k]
    print("-" * len(hdr))
    print(f"{'TOTAL':14s} {tot['series']:7d} {'':>7s} {tot['points']:12d} "
          f"{tot['total_bytes']/MIB:10.1f} {tot['series_index_bytes']/MIB:12.1f} "
          f"{tot['data_bytes']/MIB:9.2f}")

    if tot["total_bytes"]:
        pct = tot["series_index_bytes"] / tot["total_bytes"] * 100
        print(f"\nfixed _series index = {pct:.1f} % of on-disk bytes")
    if tot["data_bytes"] and tot["points"]:
        print(f"compressed size    = {tot['data_bytes']/tot['points']:.2f} bytes/point")

    if args.csv_out:
        parent = os.path.dirname(os.path.abspath(args.csv_out))
        os.makedirs(parent, exist_ok=True)
        new = not os.path.exists(args.csv_out)
        with open(args.csv_out, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            if new:
                w.writeheader()
            w.writerows(rows)
        print(f"\nappended {len(rows)} rows to {args.csv_out}")


if __name__ == "__main__":
    main()
