#!/usr/bin/env bash
# §19 alignment variant: does burst-60's raw-floor sweet spot come from
# duration-matching (the claim) or from the aligned burst starting exactly on
# a 60s window boundary (the caveat)?
#
# Records a burst whose 60s spike starts MID-WINDOW (+330s = 30s into the 6th
# 1m window, NOT on a boundary), then replays from tier {raw,60,300} exactly
# like E3. Compare the tier-60 cell against the aligned E3 reps' tier-60
# (peak ~1.02, NRMSE ~3%, at the raw floor).
#
# Expectation if it's ALIGNMENT LUCK: misaligned tier-60 peak drops (the spike
# straddles two windows, each window's mean dilutes it) toward the tier-300
# value. If it's DURATION-MATCHING: tier-60 stays ~1.0 regardless of phase.
#
# PRECONDITIONS: pipeline live, lab quiet (no rep/record/blindness running).
set -u
cd "$(dirname "$0")"
EXP="$(cd .. && pwd)"          # experiments/ (burst_offset's parent)
export E3_DIR="$EXP/e3"        # absolute, for the quoted heredoc python below

REC_BURST_AT=330 "$EXP/rec/record_event.sh" burst 900 || { echo "REC FAILED"; exit 1; }
meta=$(ls -t "$EXP/rec/events/burst_"*.meta | head -1)

python3 - "$meta" <<'EOF'
import os, sys
sys.path.insert(0, os.environ["E3_DIR"])
from pathlib import Path
from replay_tier import read_meta, get_counter
meta = Path(sys.argv[1])
s, e, t = read_meta(meta)
print(f"cached {len(get_counter(meta, s, e))} samples -> {meta}")
EOF

"$EXP/e3/run_e3.sh" "$meta"
echo "ALIGNMENT variant complete (misaligned burst +330s) — compare tier-60 vs aligned reps"
