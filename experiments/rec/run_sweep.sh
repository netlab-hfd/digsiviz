#!/usr/bin/env bash
# REC-cal sweep: heterogeneous-generator delivery vs concurrency cap.
# MAX_DYN in {2,4,16} x 300s fluct events (the 8-cap point = the main
# 900s fluct event). Each run: record -> cache counter -> meta_check.
set -u
cd "$(dirname "$0")"
for md in 2 4 16; do
  echo "=== sweep MAX_DYN=$md ==="
  REC_MAX_DYN=$md ./record_event.sh fluct 300
  meta=$(ls -t events/fluct_*.meta | head -1)
  python3 - "$meta" <<'EOF'
import sys
sys.path.insert(0, '/home/allan/uni/research_project/experiments/e3')
from pathlib import Path
from replay_tier import read_meta, get_counter
meta = Path(sys.argv[1])
s, e, t = read_meta(meta)
print(f"cached {len(get_counter(meta, s, e))} samples -> {meta}")
EOF
  python3 meta_check.py "$meta"
done
echo "SWEEP complete"
