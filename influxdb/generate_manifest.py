#!/usr/bin/env python3
"""
Generate influxdb/manifest.yml (the `influx apply` spec) for the cascading
downsample chain, from a compact tier table. Regenerate instead of hand-editing
12+ near-identical YAML blocks — that hand-editing is what produced the
_measurement/_field filter bug.

What it fixes / adds vs the old hand-written manifest:
  * CORRECT filter: _measurement == "network_interface" AND
    _field in {statistics_out-octets, statistics_in-octets}
    (the old manifest filtered _measurement == "statistics_out-octets", which
    is a FIELD, so every task read nothing and every tier stayed empty).
  * min/max/median in addition to mean. Each aggregate stored as its own field
    suffix (_mean/_min/_max/_median) in the SAME tier bucket, so no point
    collisions. min/max cascade exactly; mean ~exactly; median-of-medians is an
    approximation (acceptable for downsampling — disclose in the paper).
  * RATE-FIRST ordering. The tiers store aggregates of the RATE (octets/s), not
    of the cumulative counter: the derivative is taken on a fixed LATTICE_S
    lattice before the first aggregateWindow. This is what makes min/max carry
    the burst envelope instead of the window's endpoints, and what makes the
    mean conserve volume exactly. See LATTICE_S below for the measurements
    behind both claims.
    CONSUMERS MUST NOT apply derivative() to a tier bucket, and existing tier
    data written by the old counter-first cascade is NOT comparable with data
    written after this change -- wipe the tier buckets when migrating.

Run:  python3 generate_manifest.py   ->  writes manifest.yml
Then: docker compose up (influx-setup applies it) or `influx apply -f manifest.yml`
"""

RAW_BUCKET = "infldb"
MEASUREMENT = "network_interface"
BASE_FIELDS = ["statistics_out-octets", "statistics_in-octets"]
AGGS = ["mean", "min", "max", "median"]  # suffix == flux aggregate fn name

# Rate estimation lattice, in seconds, applied before the first aggregation.
#
# WHY THIS EXISTS AT ALL (the ordering fix): the tiers used to aggregate the raw
# CUMULATIVE COUNTER directly. On a monotone series min == the counter at the
# window's start and max == the counter at its end, always, so min/max recorded
# where the window boundaries were and carried no information about the traffic
# inside it -- verified in 36/36 windows, and an identical burst fired at +3s,
# +28s and +50s inside a window produced identical stored aggregates. Worse,
# aggregating counters then differentiating loses volume (measured 6 % at the 1m
# tier, 30 % at 5m) because derivative() and aggregateWindow() do not commute.
# The rate must therefore be derived BEFORE the first aggregation.
#
# WHY A LATTICE AND NOT A PER-SAMPLE DERIVATIVE: a per-sample derivative divides
# a counter delta by whatever dt the poll jitter produced, so two samples 0.2s
# apart carrying 0.5s of traffic read ~2.5x the true rate (measured: a
# 155.8 Mbit/s peak on a 40 Mbit/s offered load, i.e. above the twin's own
# forwarding knee and therefore impossible). Snapping to a fixed lattice with
# fn: last makes dt exact.
#
# 2s matches --truth-grid in e_repr.py, deliberately: the deployed cascade and
# the analysis path must apply the SAME operator, or the evaluation measures a
# different pipeline than the one that is running.
LATTICE_S = 2

# Fields in the tier buckets are RATES IN OCTETS PER SECOND, not counters.
# The names are unchanged (statistics_out-octets_mean, ...) because renaming
# would ripple through every dashboard, backfill.py and the flow generator; the
# unit is a property of the whole tier family and is recorded in each bucket's
# description. Consumers multiply by 8 for bits/s and must NOT apply
# derivative() to a tier bucket.


def every_seconds(every):
    """'1m'/'8h'/'4w' -> seconds. Only used for the tier-1 lookback."""
    unit = every[-1]
    n = int(every[:-1])
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]

# Delay each task's execution past the ingestion lag, WITHOUT shifting the
# window it reads: InfluxDB keeps a task's `now()` pinned to its scheduled time
# and only defers when the task actually runs, so `range(start: -task.every)`
# still covers the intended window.
#
# WHY: telegraf.conf sets no flush_interval, so Telegraf batches at its 10s
# default. A task firing exactly on the window boundary therefore reads a
# window whose last few seconds have not been written yet (measured lag
# oscillates ~1.6-7.5s). Every tier point was being computed from a truncated
# window — for the 1m tier, up to ~17% of the window missing, biasing
# mean/min/max/median. Verified by verify_counter_aggregation.py: tier `max`
# consistently sat below the window's true last counter value.
#
# 30s > the observed lag with margin, and stays below the smallest tier's
# 1m `every`.
OFFSET = "30s"

# (tier_name, every, retention_seconds, retention_comment)
TIERS = [
    ("1m",   "1m",   3600,      "floored to InfluxDB 1h minimum (2x rule -> 600s, rejected)"),
    ("5m",   "5m",   7200,      "2h = 2x the 1h consuming task"),
    ("1h",   "1h",   57600,     "16h = 2x the 8h consuming task"),
    ("8h",   "8h",   172800,    "2d = 2x the 1d consuming task"),
    ("1d",   "1d",   1209600,   "2w = 2x the 1w consuming task"),
    ("1w",   "1w",   4838400,   "8w = 2x the 4w consuming task"),
    ("4w",   "4w",   14515200,  "24w = 2x the 12w consuming task"),
    ("12w",  "12w",  29030400,  "48w = 2x the 24w consuming task"),
    ("24w",  "24w",  62899200,  "~2y = 2x the 52w consuming task"),
    ("52w",  "52w",  314496000, "~10y = 2x the 260w consuming task"),
    ("260w", "260w", 628992000, "~20y = 2x the 520w consuming task"),
    ("520w", "520w", 314496000, "~10y terminal tier, no downstream task"),
]

HEADER = """\
# GENERATED by generate_manifest.py — DO NOT hand-edit. Change the tier table
# in the generator and re-run instead.
#
# Cascading downsample chain. Each tier = one Bucket (storage + retention) plus
# one Task (scheduled Flux downsample). Tier N reads tier N-1, applies
# mean/min/max/median over its window, writes suffixed fields (_mean/_min/_max/
# _median) into its bucket.
#
# Retention rule: a tier's retention >= the `every` of the task that reads FROM
# it, or the source expires before consumption. Each below = 2x that interval
# (floored to InfluxDB's 3600s minimum). Init bucket "infldb"
# (DOCKER_INFLUXDB_INIT_BUCKET) is the raw source — not defined here.
"""


def bucket_block(name, every_ret_secs, comment):
    return f"""\
apiVersion: influxdata.com/v2alpha1
kind: Bucket
metadata:
  name: traffic-{name}
spec:
  name: traffic-{name}
  description: >-
    Traffic RATES in octets/s at {name} resolution, stored as
    mean/min/max/median fields. NOT counters: the rate is derived on a
    {LATTICE_S}s lattice before the first aggregation, so consumers must
    multiply by 8 for bits/s and must NOT apply derivative().
  retentionRules:
    - type: expire
      everySeconds: {every_ret_secs}   # {comment}
"""


def field_filter(fields):
    return " or ".join(f'r._field == "{f}"' for f in fields)


def tier1_task(name, every):
    """First tier: raw counters -> rate on a fixed lattice -> 4 suffixed
    aggregates OF THE RATE (octets/s). See LATTICE_S for why the derivative
    comes first and why the lattice is needed."""
    writes = []
    for agg in AGGS:
        writes.append(
            f"""\
    rate
      |> aggregateWindow(every: {every}, fn: {agg}, createEmpty: false)
      |> map(fn: (r) => ({{r with _field: r._field + "_{agg}"}}))
      |> to(bucket: "traffic-{name}")
"""
        )
    body = "\n".join(writes)
    # Read one lattice cell further back than the window, because derivative()
    # consumes the first sample: without this the tier's first cell is missing
    # and every aggregate is computed over one cell fewer, biased toward the
    # window's later traffic. The stream is trimmed back to the intended window
    # after differentiating, so exactly one output window is written.
    #
    # `timeSrc: "_start"` on the lattice is load-bearing, and it is the ONLY
    # thing that fixes a one-cell loss at the end of every window.
    #
    # By default aggregateWindow stamps each cell at its STOP, and it will not
    # emit a cell whose stamp falls outside the source range. For a window
    # [T, T+60) the cell covering [T+58, T+60) would be stamped exactly T+60 ==
    # the range stop, so it is dropped: the window yields 29 cells covering only
    # [T, T+58), and the final two seconds never enter the stream.
    #
    # Reading two seconds further (`stop: LATTICE_S s`, i.e. into the future
    # relative to the task's now()) looks like the fix and IS NOT: **InfluxDB
    # clamps a task query's range to the task's pinned now()**, so the future
    # stop is silently ignored. Verified the hard way -- the deployed task
    # carried `stop: 2s` in its Flux and still stored the 29-cell value.
    #
    # Stamping cells at their START instead keeps every stamp inside the range:
    # cells land on T-2 .. T+58, the derivative drops the first, and the window
    # gets 30 cells covering exactly [T, T+60).
    #
    # Measured cost of getting this wrong, both directions verified: for a burst
    # running at the window's close the stored mean came out ~20 % low (71.6 vs
    # 89.9 Mbit of volume, exactly one 2s cell of a 10.333 Mbit/s burst); for a
    # burst safely inside the window it read 3.4 % HIGH, because the mean was
    # taken over 29 cells while reconstructing volume assumes 30 (30/29 =
    # 1.034). With timeSrc as written, mean x window == the raw counter delta
    # EXACTLY: 154.8 == 154.8 Mbit contained, 89.9 == 89.9 Mbit straddling.
    #
    # The lookback of one extra cell is still needed, for a different reason:
    # derivative() consumes the first sample, so without it the window's first
    # cell would be missing instead of its last.
    lookback = every_seconds(every) + LATTICE_S
    return f"""\
apiVersion: influxdata.com/v2alpha1
kind: Task
metadata:
  name: downsample-raw-to-{name}
spec:
  name: downsample-raw-to-{name}
  description: >-
    Derives the rate from raw {RAW_BUCKET} counters on a {LATTICE_S}s lattice,
    then stores {name} mean/min/max/median OF THE RATE (octets/s).
  every: {every}
  offset: {OFFSET}
  query: |

    rate = from(bucket: "{RAW_BUCKET}")
      |> range(start: -{lookback}s)
      |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
      |> filter(fn: (r) => {field_filter(BASE_FIELDS)})
      |> aggregateWindow(every: {LATTICE_S}s, fn: last, createEmpty: false, timeSrc: "_start")
      |> derivative(unit: 1s, nonNegative: true)
      |> range(start: -task.every)

{body}"""


def tierN_task(name, every, prev):
    """Later tiers: read prev tier's suffixed fields, aggregate like-with-like."""
    writes = []
    for agg in AGGS:
        agg_fields = [f"{f}_{agg}" for f in BASE_FIELDS]
        writes.append(
            f"""\
    src
      |> filter(fn: (r) => {field_filter(agg_fields)})
      |> aggregateWindow(every: {every}, fn: {agg}, createEmpty: false)
      |> to(bucket: "traffic-{name}")
"""
        )
    body = "\n".join(writes)
    return f"""\
apiVersion: influxdata.com/v2alpha1
kind: Task
metadata:
  name: downsample-{prev}-to-{name}
spec:
  name: downsample-{prev}-to-{name}
  description: Downsamples the {prev} tier to {name} (mean/min/max/median cascade).
  every: {every}
  offset: {OFFSET}
  query: |

    src = from(bucket: "traffic-{prev}")
      |> range(start: -task.every)
      |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")

{body}"""


def main():
    docs = [HEADER]
    prev = None
    for name, every, ret, comment in TIERS:
        docs.append(bucket_block(name, ret, comment))
        if prev is None:
            docs.append(tier1_task(name, every))
        else:
            docs.append(tierN_task(name, every, prev))
        prev = name
    out = "\n---\n".join(docs)
    with open("manifest.yml", "w") as f:
        f.write(out)
    print(f"Wrote manifest.yml: {len(TIERS)} tiers x (1 bucket + 1 task), "
          f"{len(AGGS)} aggregates each.")


if __name__ == "__main__":
    main()
