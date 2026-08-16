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
    """'1m'/'8h'/'4w' -> seconds."""
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

# The tier ladder. Retention is DERIVED (see retention() below), not written by
# hand: the previous hand-written table set every retention to 2x the consuming
# task's interval, which made the SCHEDULER decide how far back each resolution
# stays queryable. That is backwards — this paper's whole claim is that data AGE
# decides resolution — and at the coarse end it produced absurdities: traffic-260w
# retained for 20 years so that a task firing once per decade would always find
# its window, and the terminal traffic-520w retained for an arbitrary 10 years
# because no rule applied to it at all.
#
# (tier_name, every)
TIERS = [
    ("1m",   "1m"),
    ("5m",   "5m"),
    ("1h",   "1h"),
    ("8h",   "8h"),
    ("1d",   "1d"),
    ("1w",   "1w"),
    ("4w",   "4w"),
    ("12w",  "12w"),
    ("24w",  "24w"),
    ("52w",  "52w"),
    ("260w", "260w"),
    ("520w", "520w"),
]

# The time-machine depth this work claims. Every tier's coverage is capped here:
# retaining a resolution for longer than the deepest query the system offers is
# storage with no reader.
HORIZON_S = 314496000       # 520w ~ 10 years

# Points a tier must hold for its own trace to be readable rather than merely
# sufficient to feed the next task. Storage is then CONSTANT per tier
# (ROWS x |SERIES| x |AGGS| points), which is the property that makes the ladder
# cheap: a tier's span grows exactly as fast as its resolution coarsens.
ROWS = 24

INFLUX_MIN_RETENTION_S = 3600   # InfluxDB rejects anything shorter (except 0)

# --- Schedule decoupled from window -----------------------------------------
#
# A cascade task used to have ONE knob, `every`, doing two unrelated jobs: how
# often the task fires, AND how much history it summarises (via
# `range(start: -task.every)`). Tying them together has two costs:
#
#   * COLD START. traffic-520w's task fires once per 520 weeks, so the bucket
#     stays empty for a decade and the coarse tiers are reachable only by
#     backfill.py. Nothing about restart recovery fixes this -- the task was
#     never due, so there are no missed runs to catch up on.
#   * NO SELF-HEALING. Miss the single fire that covers a window (host down,
#     Influx restart, task error) and that window is gone permanently, because
#     the next fire looks at the NEXT window only.
#
# Both go away by separating the two: fire on REFRESH, summarise on W.
#
#   spec.every = refresh = min(W, REFRESH_CAP)
#   query range = the last K_WINDOWS *closed* windows of width W
#
# Rewriting a window is free: `to()` overwrites on identical
# (measurement, tags, field, timestamp), so every run simply restates the last
# K_WINDOWS windows with whatever source data now exists. A run missed during an
# outage is repaired by the next run, at any tier, with no operator action.
REFRESH_CAP_S = 86400   # never sleep longer than a day between refreshes
K_WINDOWS = 2           # closed windows recomputed per run; 1 window of catch-up

# Only CLOSED windows are published. The open one -- the window the present
# moment sits inside -- is deliberately skipped: publishing it would store an
# aggregate computed over a window that has not finished, which is precisely the
# truncated-window defect that OFFSET exists to prevent at tier 1. Costs one
# window of freshness at each tier, buys that every stored point is complete.
#
# Window boundaries are epoch-aligned, matching aggregateWindow's own default
# gridding, so the range and the windows it produces cannot drift apart.

# Stamp EVERY aggregate at its window's START, uniformly, at every tier.
#
# THIS IS A CORRECTNESS FIX, not a cosmetic one. aggregateWindow defaults to
# stamping a window at its STOP, and it will not emit a window whose stamp falls
# outside the source range. Tier 1's lattice already had to be switched to
# `_start` for exactly this reason (its final 2s cell was being dropped, biasing
# every aggregate). The same defect was still live at every tier >= 2: tier N-1
# writes a point stamped at its window's stop, tier N reads a W-wide range, and
# the source point stamped exactly on the closing boundary lands in the NEXT
# window and is dropped -- so each cascade stage silently summarised one source
# point fewer than it should.
#
# Uniform start-stamping makes every point mean "the window beginning here", so
# a half-open range [B-W, B) contains exactly the points belonging to it, at
# every stage. Values are unchanged; only the timestamp label moves, by one
# window. Mixing tier data written before and after this change is therefore
# wrong -- wipe the tier buckets when migrating (the same wipe the rate-first
# migration already requires).
TIMESRC = "_start"


def retention(idx):
    """Two-term retention for tier `idx`. Returns (seconds, comment);
    0 seconds == infinite (the bucket then carries no retentionRules).

        pipeline_N  = K_WINDOWS x every_{N+1}
                                       -- the consuming task recomputes its last
                                          K_WINDOWS closed windows on every run,
                                          so this tier must still hold them. This
                                          is what makes an outage self-repairing:
                                          the window missed while the host was
                                          down is rebuilt from source data that
                                          is still here.
                      Dropped when every_{N+1} >= HORIZON_S: a task slower than
                      the horizon never fires inside the system's own lifetime,
                      so sizing storage for it is fiction.
        coverage_N  = min(ROWS x every_N, HORIZON_S)   -- the policy term, i.e.
                      the retention the granularity argument actually asks for.

        retention_N = max(pipeline_N, coverage_N), floored to InfluxDB's minimum.

    max() is load-bearing: the policy term can only ever ADD retention, never
    undercut what the cascade needs to keep running.
    """
    name, every = TIERS[idx]
    own = every_seconds(every)

    if idx + 1 < len(TIERS):
        nxt_name, nxt_every = TIERS[idx + 1]
        nxt = every_seconds(nxt_every)
        if nxt < HORIZON_S:
            pipeline, pipe_why = (K_WINDOWS * nxt,
                                  f"{K_WINDOWS} windows of the {nxt_name} consuming task")
        else:
            pipeline, pipe_why = 0, None    # consumer slower than the horizon
    else:
        pipeline, pipe_why = 0, None        # terminal tier, no consumer
        # A terminal tier has no downstream deadline and no coarser tier to fall
        # back on, so its coverage IS the end of the chain: infinite. One point
        # per decade per series costs nothing, and expiring it would silently
        # cap the "10 years into the past" claim.
        return 0, "infinite: terminal tier, no consumer and no coarser fallback"

    capped = ROWS * own >= HORIZON_S
    coverage = min(ROWS * own, HORIZON_S)
    cov_why = ("capped at the 10y horizon" if capped
               else f"{ROWS} points at {every} resolution")

    if coverage >= pipeline:
        secs, why = coverage, f"coverage: {cov_why}"
    else:
        secs, why = pipeline, f"pipeline: {pipe_why}"

    if secs < INFLUX_MIN_RETENTION_S:
        return INFLUX_MIN_RETENTION_S, f"floored to InfluxDB 1h minimum ({why} -> {secs}s)"
    return secs, why

def cascade_capable(idx):
    """Can tier `idx` be built by the cascade at all, or only by backfill.py?

    Publishing only CLOSED windows means the newest window a task can write is
    the one that ended most recently -- whose START is between W and 2W old,
    depending where in the cycle the task fires. The source tier must therefore
    still hold 2W of history, or the window gets summarised from whatever
    fraction has not yet expired and a truncated aggregate is written silently.

    That is the same defect OFFSET prevents at tier 1 and that uniform
    start-stamping prevents between tiers -- so it is not acceptable here
    either. Where the condition fails, NO task is generated: the bucket exists
    and is populated by backfill.py, and says so in its description.

    In the current ladder exactly one tier fails: traffic-520w needs 20 years of
    traffic-260w and the horizon caps retention at 10. A 520w-wide window can
    never fit inside a 10-year retention, so no scheduling choice fixes it --
    the terminal tier is structurally beyond the cascade's reach.
    """
    if idx == 0:
        return True
    w = every_seconds(TIERS[idx][1])
    src_ret, _ = retention(idx - 1)
    dst_ret, _ = retention(idx)
    ok_src = src_ret == 0 or src_ret >= K_WINDOWS * w
    ok_dst = dst_ret == 0 or dst_ret >= 2 * w
    return ok_src and ok_dst


def schedule(idx):
    """Refresh cadence and read-back span for tier `idx` (idx >= 1).

    Returns (refresh_seconds, lookback_seconds, note).

    lookback is clamped twice, and both clamps are load-bearing:

      * by the SOURCE tier's retention -- asking for windows that have already
        expired upstream reads nothing and only makes the query look like it
        covers more than it does;
      * by the DESTINATION tier's retention, minus one window. Points are
        stamped at their window's START, so the oldest point a run writes is
        already `lookback + (time since the boundary)` old, and that trailing
        term reaches a full window just before the next boundary. Ignore it and
        the run does not merely skip that point -- InfluxDB fails the WHOLE run
        with "dropped N points outside retention policy", so ONE unwritable old
        window takes the fresh ones down with it. Measured, not predicted:
        downsample-52w-to-260w failed exactly this way, trying to stamp a window
        at 2014-11-06 against a 10-year retention.

    The result is floored to one window: a task that cannot even rewrite its own
    newest closed window has nothing useful to do, and cascade_capable() has
    already excluded that case.
    """
    name, every = TIERS[idx]
    w = every_seconds(every)
    refresh = min(w, REFRESH_CAP_S)

    want = K_WINDOWS * w
    src_ret, _ = retention(idx - 1)
    dst_ret, _ = retention(idx)

    limits = [want]
    if src_ret:
        limits.append(src_ret)
    if dst_ret:
        limits.append(dst_ret - w)
    lookback = max(w, (min(limits) // w) * w)

    windows = lookback // w
    note = f"{windows} closed window(s) of {every}"
    if lookback < want:
        note += ", clamped by retention"
    return refresh, lookback, note


HEADER = """\
# GENERATED by generate_manifest.py — DO NOT hand-edit. Change the tier table
# in the generator and re-run instead.
#
# Cascading downsample chain. Each tier = one Bucket (storage + retention) plus
# one Task (scheduled Flux downsample). Tier N reads tier N-1, applies
# mean/min/max/median over its window, writes suffixed fields (_mean/_min/_max/
# _median) into its bucket.
#
# Each task's SCHEDULE is independent of its WINDOW: it fires at most a day
# apart and rewrites its last 2 closed windows every run. Rewrites are free
# (`to()` overwrites on identical tags+field+timestamp), so a run missed during
# an outage is repaired by the next one, and a tier whose window is measured in
# years is populated from its first day instead of after a decade of uptime.
# Only CLOSED windows are published — never the one the present sits inside.
#
# All aggregates are stamped at their window's START (timeSrc: "_start"),
# uniformly, at every tier: with the default stop-stamping each stage silently
# dropped the source point landing on its closing boundary.
#
# Retention is DERIVED, two terms, whichever is larger:
#   pipeline = 2 windows of the task that READS this tier, so the windows it
#              rewrites are still here (dropped where that task is slower than
#              the 10y horizon and so never fires in practice);
#   coverage = 24 points at this tier's own resolution, capped at the 10y
#              horizon — the term the granularity argument actually asks for.
# Floored to InfluxDB's 3600s minimum. The terminal tier carries no
# retentionRules at all, i.e. infinite. Init bucket "infldb"
# (DOCKER_INFLUXDB_INIT_BUCKET) is the raw source — not defined here.
"""


def bucket_block(name, every_ret_secs, comment, capable=True):
    source = ("" if capable else
              " NO cascade task writes this tier: a {n}-wide window cannot fit"
              " inside the source tier's retention, so it would only ever be"
              " summarised from a fraction of itself. Populated by"
              " backfill.py.".format(n=name))
    head = f"""\
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
    multiply by 8 for bits/s and must NOT apply derivative().{source}
"""
    if every_ret_secs == 0:
        # Omitting retentionRules is how the pkger spec expresses infinite
        # retention; `everySeconds: 0` is accepted too but reads as a mistake.
        return head + f"  # retention: {comment}\n"
    return head + f"""\
  retentionRules:
    - type: expire
      everySeconds: {every_ret_secs}   # {comment}
"""


def field_filter(fields):
    return " or ".join(f'r._field == "{f}"' for f in fields)


def tier1_task(name, every):
    """First tier: raw counters -> rate on a fixed lattice -> 4 suffixed
    aggregates OF THE RATE (octets/s). See LATTICE_S for why the derivative
    comes first and why the lattice is needed.

    Deliberately NOT converted to the decoupled schedule the cascade tiers use.
    Its lookback is tuned to one lattice cell past the window because
    derivative() consumes the first sample, and its correctness (mean x window
    == the raw counter delta, exactly) was verified against that specific range.
    It also gains the least: it already fires every 60s, and its source `infldb`
    retains 1h, so there is barely anything to re-read. The cost is that tier 1
    alone is not self-healing -- an outage loses raw-resolution points, which are
    the shortest-lived points in the system anyway.
    """
    writes = []
    for agg in AGGS:
        writes.append(
            f"""\
    rate
      |> aggregateWindow(every: {every}, fn: {agg}, createEmpty: false, timeSrc: "{TIMESRC}")
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


def tierN_task(name, every, prev, refresh_s, lookback_s, note):
    """Later tiers: read prev tier's suffixed fields, aggregate like-with-like.

    The schedule (`every: refresh`) is independent of the window (`every` in the
    aggregateWindow calls) -- see REFRESH_CAP_S / K_WINDOWS. The query pins its
    own range to the last closed window boundary rather than using task.every,
    so re-running mid-window recomputes the same closed windows and overwrites
    them, instead of publishing a partial one.
    """
    writes = []
    for agg in AGGS:
        agg_fields = [f"{f}_{agg}" for f in BASE_FIELDS]
        writes.append(
            f"""\
    src
      |> filter(fn: (r) => {field_filter(agg_fields)})
      |> aggregateWindow(every: {every}, fn: {agg}, createEmpty: false, timeSrc: "{TIMESRC}")
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
  description: >-
    Downsamples the {prev} tier to {name} (mean/min/max/median cascade).
    Refreshes every {refresh_s}s and rewrites {note}, so a run missed
    during an outage is repaired by the next one.
  every: {refresh_s}s
  offset: {OFFSET}
  query: |

    // Last CLOSED window boundary, epoch-aligned exactly as aggregateWindow
    // grids its own windows. now() is pinned to the task's scheduled time, so
    // this is deterministic and identical across retries.
    w     = int(v: {every})
    n     = int(v: now())
    stop  = n - n % w
    start = stop - int(v: {lookback_s}s)

    src = from(bucket: "traffic-{prev}")
      |> range(start: time(v: start), stop: time(v: stop))
      |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")

{body}"""


def human(secs):
    if secs == 0:
        return "infinite"
    for unit, n in (("y", 31449600), ("w", 604800), ("d", 86400), ("h", 3600)):
        if secs >= n:
            v = secs / n
            return f"{v:.0f}{unit}" if abs(v - round(v)) < 0.05 else f"~{v:.1f}{unit}"
    return f"{secs}s"


def main():
    docs = [HEADER]
    prev = None
    table = []
    for idx, (name, every) in enumerate(TIERS):
        ret, comment = retention(idx)
        capable = cascade_capable(idx)
        docs.append(bucket_block(name, ret, comment, capable))
        if prev is None:
            docs.append(tier1_task(name, every))
            table.append((name, every, ret, comment, every, "tier 1: not decoupled"))
        elif capable:
            refresh_s, lookback_s, note = schedule(idx)
            docs.append(tierN_task(name, every, prev, refresh_s, lookback_s, note))
            table.append((name, every, ret, comment, human(refresh_s), note))
        else:
            table.append((name, every, ret, comment, "none",
                          f"NO TASK: needs {K_WINDOWS}x{every} of traffic-{prev}"))
        prev = name
    out = "\n---\n".join(docs)
    with open("manifest.yml", "w") as f:
        f.write(out)
    n_tasks = sum(1 for d in docs if d.lstrip().startswith("apiVersion")
                  and "kind: Task" in d)
    print(f"Wrote manifest.yml: {len(TIERS)} buckets, {n_tasks} tasks, "
          f"{len(AGGS)} aggregates each.")
    print(f"{'tier':>6}  {'window':>7}  {'refresh':>8}  {'retention':>10}  "
          f"{'rewrites':<28}  retention reason")
    for name, every, ret, comment, refresh, note in table:
        print(f"{name:>6}  {every:>7}  {refresh:>8}  {human(ret):>10}  "
              f"{note:<28}  {comment}")


if __name__ == "__main__":
    main()
