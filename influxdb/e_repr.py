#!/usr/bin/env python3
"""
E_repr — the representation error introduced by downsampling, measured WITHOUT
any replay (PROJECT_JOURNAL.md 12a).

  r_raw ──[downsampling]──> r_tier ──[iperf3 + twin]──> r_replay
        └─ E_repr (THIS) ─┘        └─ E_real (Task E) ┘

E_repr compares the 0.5s ground truth against its downsampled encoding. It needs
no clab, no iperf3 and no twin — only data already in InfluxDB. Task E later adds
E_real on top; keeping them separate is what makes the claim falsifiable rather
than anecdotal ("is that downsampling loss, or just a bad twin?").

THREE DESIGN DECISIONS, each load-bearing:

1. COMPARE AT RAW RESOLUTION (12b). The coarse value is held flat across its
   window (zero-order hold) and laid against the 0.5s truth. Comparing instead on
   the coarse time base would apply the lossy operator to BOTH sides and drive the
   error to ~0 by construction — a unit test of aggregateWindow(), not a result.
   The ground truth is never downsampled.

2. SIMULATE THE CASCADE HERE rather than reading the traffic-* buckets. Raw
   `infldb` retains only 1h, so for every tier of 1h or coarser there is no
   overlapping ground truth left to compare against — E_repr for those tiers is
   simply not measurable from stored data. Re-deriving each tier from the same raw
   window sidesteps that and keeps every tier comparable against the same truth.

3. DEDUPE BEFORE DIFFERENTIATING. The ingest writes each poll twice (~90ms
   apart, exactly 2.00x — see verify_counter_aggregation.py). A per-sample
   derivative over the raw series therefore alternates between 0 and the true
   rate, biasing every rate ~40% low. Skipping this silently corrupts every
   number below.

TWO ORDERINGS ARE REPORTED, because the difference is the point (12d):
  * agg->deriv : aggregate the cumulative counter, then differentiate.
                 THIS IS WHAT THE PIPELINE CURRENTLY DOES.
  * deriv->agg : differentiate to a rate first, then aggregate the rate.
                 The proposed fix.
They do not commute, and the cascade currently uses the losing order.

FIDELITY IS A VECTOR, NOT A SCALAR (12e). Five families are reported. Headline is
Event + Peak (the NDT question: "was the link hot?"). Volume is a sanity check —
it must be ~0 for a mean, or the pipeline is broken. Shape-NRMSE is reported but
is NOT the headline: it degrades for every coarse tier and says little.

Run:  python3 e_repr.py [--minutes 55] [--threshold-mbits 20]
"""

import argparse
import csv
import io
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

ORG = "myorg"
TOKEN = "mytoken"
CONTAINER = "influxdb"
RAW_BUCKET = "infldb"
MEASUREMENT = "network_interface"
FIELD = "statistics_out-octets"

# Tier windows to evaluate, in seconds. Kept to tiers that can actually be
# resolved inside a 1h raw window; coarser tiers would have one sample or none.
TIERS = [60, 300, 900, 3600]

DEDUPE_GAP = 0.2  # seconds; collapses the ~90ms duplicate pair per poll


def parse_ts(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def flux(query):
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "influx", "query",
         "--org", ORG, "--token", TOKEN, "--raw", "-"],
        input=query, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"influx query failed:\n{proc.stderr}")
    rows, header = [], None
    for line in io.StringIO(proc.stdout):
        line = line.rstrip("\n")
        if not line.strip():
            header = None
            continue
        if line.startswith("#"):
            continue
        fields = next(csv.reader([line]))
        if header is None:
            header = fields
            continue
        rows.append(dict(zip(header, fields)))
    return rows


def fetch_raw(minutes):
    rows = flux(f'''
from(bucket: "{RAW_BUCKET}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r._field == "{FIELD}")
  |> keep(columns: ["_time", "_value", "hostname", "interface_name"])
''')
    out = defaultdict(list)
    for r in rows:
        out[(r["hostname"], r["interface_name"])].append(
            (parse_ts(r["_time"]), float(r["_value"])))
    for k in out:
        out[k].sort()
    return out


def dedupe(samples, gap=DEDUPE_GAP):
    out = [samples[0]]
    for t, v in samples[1:]:
        if (t - out[-1][0]).total_seconds() >= gap:
            out.append((t, v))
    return out


def resample(counter, grid, t0):
    """Snap the counter onto a fixed `grid`-second lattice, taking the LAST
    value in each cell.

    WHY THIS IS NEEDED, and why it is not "downsampling the ground truth":
    gNMI polls are jittery and the counter itself only advances in packet-sized
    steps, so a derivative taken across consecutive raw samples divides a ~0.5s
    counter delta by whatever dt the jitter produced. Two samples 0.2s apart
    carrying 0.5s of traffic read ~2.5x the true rate — measured: a 155.8 Mbit/s
    "peak" on a 40 Mbit/s offered load, above the twin's own ~50-55 Mbit/s knee,
    i.e. physically impossible and therefore an artefact.

    Snapping to a fixed lattice makes dt exact, which is the only way to get an
    unbiased rate out of a counter. This is the practical form of the earlier
    finding that polling interval != rate-computation window: the ground truth is
    the finest rate the pipeline can *honestly* report, not the finest timestamp
    it happens to store. It stays 2 orders of magnitude finer than any tier under
    test, so the 12b rule (never apply the lossy operator to the truth) holds —
    this is estimation, not coarsening.
    """
    cells = {}
    for t, v in counter:
        cells[int((t - t0).total_seconds() // grid)] = v
    return cells


def to_rate(counter, grid, t0):
    """Cumulative counter -> (time, bits/s) on a fixed grid.

    dt comes from the GRID INDICES, never from the sample timestamps: taking the
    real timestamps back out would re-import the very jitter the lattice exists
    to remove (a cell whose last sample lands early followed by one landing late
    yields a dt far from `grid`, and the rate blows up by that ratio).

    Skips intervals containing a counter reset rather than emitting a huge
    negative spike (Flux's nonNegative).
    """
    cells = resample(counter, grid, t0)
    out = []
    idx = sorted(cells)
    for j in range(1, len(idx)):
        i_prev, i_cur = idx[j - 1], idx[j]
        dt = (i_cur - i_prev) * grid
        d = cells[i_cur] - cells[i_prev]
        if dt > 0 and d >= 0:
            out.append((t0 + timedelta(seconds=i_cur * grid), d * 8.0 / dt))
    return out


def window_index(t, t0, every):
    return int((t - t0).total_seconds() // every)


def agg_then_deriv(counter, every, t0):
    """What the pipeline does now: mean() the COUNTER per window, then
    differentiate across window means."""
    buckets = defaultdict(list)
    for t, v in counter:
        buckets[window_index(t, t0, every)].append(v)
    idx = sorted(buckets)
    means = [(i, sum(buckets[i]) / len(buckets[i])) for i in idx]
    out = {}
    for j in range(1, len(means)):
        i_prev, v_prev = means[j - 1]
        i_cur, v_cur = means[j]
        dt = (i_cur - i_prev) * every
        d = v_cur - v_prev
        if dt > 0 and d >= 0:
            out[i_cur] = d * 8.0 / dt
    return out


def deriv_then_agg(rate, every, t0):
    """The fix: differentiate to a rate first, then mean() the RATE per window."""
    buckets = defaultdict(list)
    for t, v in rate:
        buckets[window_index(t, t0, every)].append(v)
    return {i: sum(vs) / len(vs) for i, vs in buckets.items()}


def hold(tier_map, rate, t0, every):
    """Zero-order hold: give every raw sample the value of the coarse window it
    falls in. This is what an operator actually sees scrolling the time machine —
    a flat line across the window. Raw stays at 0.5s (12b)."""
    out = []
    for t, _ in rate:
        v = tier_map.get(window_index(t, t0, every))
        out.append(v if v is not None else 0.0)
    return out


def metrics(truth, approx, times, thr):
    n = len(truth)
    dt = []
    for i in range(n):
        if i == 0:
            dt.append((times[1]-times[0]).total_seconds() if n > 1 else 1.0)
        else:
            dt.append(max((times[i] - times[i - 1]).total_seconds(), 1e-9))

    vol_t = sum(truth[i] * dt[i] for i in range(n))
    vol_a = sum(approx[i] * dt[i] for i in range(n))
    volume = abs(vol_a - vol_t) / vol_t if vol_t > 0 else float("nan")

    pk_t, pk_a = max(truth), max(approx)
    peak = abs(pk_a - pk_t) / pk_t if pk_t > 0 else float("nan")

    rng = max(truth) - min(truth)
    mse = sum((approx[i] - truth[i]) ** 2 for i in range(n)) / n
    nrmse = (mse ** 0.5) / rng if rng > 0 else float("nan")

    # Event: does the operator still find the incident? Threshold-crossing
    # precision/recall over samples, plus how wrong the duration is.
    tp = sum(1 for i in range(n) if truth[i] >= thr and approx[i] >= thr)
    fp = sum(1 for i in range(n) if truth[i] < thr and approx[i] >= thr)
    fn = sum(1 for i in range(n) if truth[i] >= thr and approx[i] < thr)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = (2 * prec * rec / (prec + rec)
          if prec == prec and rec == rec and prec + rec > 0 else 0.0)
    dur_t = sum(dt[i] for i in range(n) if truth[i] >= thr)
    dur_a = sum(dt[i] for i in range(n) if approx[i] >= thr)
    dur_err = abs(dur_a - dur_t) / dur_t if dur_t > 0 else float("nan")

    # Distribution: 1-Wasserstein between the rate CDFs, timing-blind.
    st, sa = sorted(truth), sorted(approx)
    emd = sum(abs(st[i] - sa[i]) for i in range(n)) / n
    emd_n = emd / (sum(st) / n) if sum(st) > 0 else float("nan")

    return dict(volume=volume, peak=peak, nrmse=nrmse, f1=f1,
                dur_err=dur_err, emd=emd_n, event_secs=dur_t)


def pct(x):
    return "  n/a " if x != x else f"{x*100:6.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=55)
    ap.add_argument("--threshold-mbits", type=float, default=20.0,
                    help="'link is hot' threshold for the event metric")
    ap.add_argument("--series", default=None,
                    help="hostname:interface, e.g. r1:ethernet-1/1")
    ap.add_argument("--truth-grid", type=float, default=2.0,
                    help="seconds; lattice the ground-truth rate is estimated on")
    args = ap.parse_args()
    thr = args.threshold_mbits * 1e6

    raw = fetch_raw(args.minutes)
    if not raw:
        sys.exit("No raw data. Is the lab deployed and backend/main.py running?")

    # Pick the busiest series by default — E_repr is only interesting where
    # there is traffic to lose.
    if args.series:
        h, i = args.series.split(":", 1)
        key = (h, i)
    else:
        key = max(raw, key=lambda k: raw[k][-1][1] - raw[k][0][1])

    counter = dedupe(raw[key])
    t0 = counter[0][0]
    rate = to_rate(counter, args.truth_grid, t0)
    if len(rate) < 10:
        sys.exit("Not enough raw samples.")
    times = [t for t, _ in rate]
    truth = [v for _, v in rate]

    span = (times[-1] - times[0]).total_seconds()
    print(f"series      : {key[0]} {key[1]}")
    print(f"raw window  : {span/60:.1f} min, {len(rate)} rate samples on a "
          f"{args.truth_grid:g}s grid (from {len(raw[key])} points, "
          f"{len(counter)} after dedupe)")
    print(f"raw peak    : {max(truth)/1e6:.1f} Mbit/s   "
          f"mean {sum(truth)/len(truth)/1e6:.2f} Mbit/s")
    print(f"event thresh: {args.threshold_mbits:.0f} Mbit/s  -> "
          f"{sum(1 for v in truth if v>=thr)*args.truth_grid:.0f}s above "
          f"threshold in truth")
    print("\nE_repr — each tier vs the 0.5s ground truth, compared at raw")
    print("resolution (coarse value held flat across its window).\n")

    hdr = (f"{'tier':>6} {'order':>11} {'volume':>7} {'peak':>7} "
           f"{'shape':>7} {'event F1':>9} {'dur err':>8} {'distrib':>8}")
    print(hdr)
    print("-" * len(hdr))
    for every in TIERS:
        if every > span / 2:
            print(f"{every:>5}s  (window too short to resolve — skipped)")
            continue
        a = hold(agg_then_deriv(counter, every, t0), rate, t0, every)
        b = hold(deriv_then_agg(rate, every, t0), rate, t0, every)
        for label, approx in (("agg->deriv", a), ("deriv->agg", b)):
            m = metrics(truth, approx, times, thr)
            name = f"{every}s" if every < 3600 else f"{every//3600}h"
            print(f"{name:>6} {label:>11} {pct(m['volume'])} {pct(m['peak'])} "
                  f"{pct(m['nrmse'])} {m['f1']:>8.2f}  {pct(m['dur_err'])} "
                  f"{pct(m['emd'])}")
    print("\nagg->deriv = what the cascade does today (aggregates the cumulative")
    print("counter). deriv->agg = the 12d fix (rate first, then aggregate).")
    print("Headline metrics are event F1 and peak; volume ~0% is a sanity check.")


if __name__ == "__main__":
    main()
