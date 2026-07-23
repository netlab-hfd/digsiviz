#!/usr/bin/env bash
# One full E3 repetition: fresh REC events (fluct + burst, 900s each,
# MAX_DYN=8 like rep 1) -> cache counters (retention trap: originals must
# be on disk before infldb's 1h retention eats them) -> run_e3.sh over both.
set -u
cd "$(dirname "$0")"

REC=rec
E3=e3
export E3_DIR="$PWD/$E3"   # absolute, for the quoted heredoc python below
DUR=900
METAS=()

for type in fluct burst; do
  "$REC/record_event.sh" "$type" "$DUR" || { echo "REC $type FAILED"; exit 1; }
  meta=$(ls -t "$REC/events/${type}"_*.meta | head -1)
  python3 - "$meta" <<'EOF'
import os, sys
sys.path.insert(0, os.environ["E3_DIR"])
from pathlib import Path
from replay_tier import read_meta, get_counter
meta = Path(sys.argv[1])
s, e, t = read_meta(meta)
print(f"cached {len(get_counter(meta, s, e))} samples -> {meta}")
EOF
  METAS+=("$(cd "$(dirname "$meta")" && pwd)/$(basename "$meta")")
done

"$E3/run_e3.sh" "${METAS[@]}"
echo "REP complete"
