#!/usr/bin/env python3
"""Aggregate E3 repetitions: merge all results_*.csv in this directory and
report mean +/- sample std per (event, tier) cell for every metric.

Each run_e3.sh invocation writes one results_<stamp>.csv = one repetition.
EXPERIMENT_MATRIX.md asks for >= 3 reps; this produces the paper table
(JOURNAL 19 caveat: "1 rep per cell - variance unknown").

NOTE: only the aligned E3 reps belong in e3/results_*.csv. The alignment
variant (misaligned burst, JOURNAL 19b) is a DIFFERENT event and lives in
../burst_offset/ so this default glob does not mix it into the aligned
aggregate.

Usage: aggregate_reps.py [results_csv ...]   (default: e3/results_*.csv)
Output: stdout table + aggregated_<n>reps.csv next to the inputs.

Stdlib only (repo convention: backend venv has no numpy/pandas).
"""
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
METRICS = ["lag_s", "nrmse_pct", "mae_pct", "mean_ratio", "max_ratio", "std_ratio"]
TIER_ORDER = {"0": 0, "60": 1, "300": 2}


def main():
    files = [Path(a) for a in sys.argv[1:]] or sorted(HERE.glob("results_*.csv"))
    if not files:
        sys.exit("no results_*.csv found")

    # cells[(event, tier)][metric] -> list of values, one per rep
    cells = defaultdict(lambda: defaultdict(list))
    for f in files:
        with f.open() as fh:
            for row in csv.DictReader(fh):
                for m in METRICS:
                    cells[(row["event"], row["tier"])][m].append(float(row[m]))

    reps = {len(v[METRICS[0]]) for v in cells.values()}
    print(f"# {len(files)} result files: " + ", ".join(f.name for f in files))
    if len(reps) > 1:
        print(f"# WARNING: unbalanced cells (reps per cell: {sorted(reps)})")

    # Write beside the inputs, not beside this script: aggregating the
    # alignment variant in ../burst_offset/ must not overwrite the aligned E3
    # aggregate that lives here.
    out = files[0].resolve().parent / f"aggregated_{max(reps)}reps.csv"
    header = ["event", "tier", "n"]
    for m in METRICS:
        header += [f"{m}_mean", f"{m}_std"]

    keys = sorted(cells, key=lambda k: (k[0], TIER_ORDER.get(k[1], 99)))
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        print(f"{'event':<6} {'tier':<5} {'n':<2} " +
              " ".join(f"{m:>18}" for m in METRICS))
        for key in keys:
            event, tier = key
            n = len(cells[key][METRICS[0]])
            rec = [event, tier, n]
            disp = []
            for m in METRICS:
                vals = cells[key][m]
                mean = statistics.mean(vals)
                std = statistics.stdev(vals) if len(vals) > 1 else 0.0
                rec += [f"{mean:.4f}", f"{std:.4f}"]
                disp.append(f"{mean:>9.3f}±{std:<7.3f}")
            w.writerow(rec)
            print(f"{event:<6} {tier:<5} {n:<2} " + " ".join(disp))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
