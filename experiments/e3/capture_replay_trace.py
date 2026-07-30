#!/usr/bin/env python3
"""Cache a replay's recorded trace to disk before infldb's 1h retention drops it.

analyze_e3.py reads each replay trace live and keeps only the metrics, so the
traces themselves are unrecoverable an hour after the run — which makes
original-vs-replay line plots impossible after the fact. This dumps the counter
window named by a `.replay_tierN` file to `<same name>.counter.csv`, the same
format (epoch,counter) the original event caches use.

Usage:
  capture_replay_trace.py <event>.replay_tier60 [...]
  capture_replay_trace.py --watch <dir>   # poll, capture anything new, until
                                          # nothing uncaptured is left in reach
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_tier import fetch_window, save_counter_cache  # noqa: E402

RETENTION_S = 3600
SAFETY_S = 600          # stop trying once the window is this close to expiry


def cache_for(replay_meta: Path) -> Path:
    return replay_meta.with_suffix(replay_meta.suffix + ".counter.csv")


def capture(replay_meta: Path) -> bool:
    out = cache_for(replay_meta)
    if out.exists():
        return False
    kv = {}
    for line in replay_meta.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k] = v
    start, end = int(kv["replay_start_epoch"]), int(kv["replay_end_epoch"])
    age = time.time() - end
    if age > RETENTION_S - SAFETY_S:
        print(f"SKIP {replay_meta.name}: {age/60:.0f} min old, past reach")
        return False
    counter = fetch_window(start, end)
    # save_counter_cache derives its path from a .meta name; write directly.
    with out.open("w") as f:
        for t, v in counter:
            f.write(f"{t.timestamp()},{v}\n")
    print(f"captured {len(counter)} samples -> {out.name}")
    return True


def watch(dirpath: Path, interval=120):
    """Poll until every replay meta young enough to still be in InfluxDB has a
    cache. Runs alongside a live E3 sequence; each tier is captured minutes
    after its replay ends rather than an hour later."""
    while True:
        pending = []
        for m in sorted(dirpath.glob("*.replay_tier*")):
            if m.suffix.endswith("csv") or cache_for(m).exists():
                continue
            kv = dict(l.split("=", 1) for l in m.read_text().splitlines() if "=" in l)
            age = time.time() - int(kv["replay_end_epoch"])
            if age < RETENTION_S - SAFETY_S:
                pending.append(m)
        for m in pending:
            try:
                capture(m)
            except SystemExit as e:      # fetch_window exits when a window is empty
                print(f"FAILED {m.name}: {e}")
        print(f"[watch] {time.strftime('%H:%M:%S')} "
              f"{len(pending)} captured this pass", flush=True)
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--watch", default=None, help="directory to poll")
    args = ap.parse_args()
    if args.watch:
        watch(Path(args.watch))
    else:
        for t in args.targets:
            capture(Path(t))


if __name__ == "__main__":
    main()
