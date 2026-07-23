# Burst-at-offset — two experiments, one directory

Both address "burst placement", but they are different claims:

## 1. `max_blindness.sh` — the §12d figure (counter aggregation blindness)

Fires an identical 5 s @40M burst at offsets {3, 28, 50} s inside separate
1-minute windows, then shows tier-1m `min`/`max` are invariant to placement
while the raw peak position tracks the offset. Pure counter/storage claim —
no replay involved. Runtime ≈ 5 min + 45 s task wait.

Run: `./max_blindness.sh` (pipeline live, lab otherwise quiet).

## 2. §19 alignment variant — replay fidelity vs window alignment

§19 caveat: burst's tier-60 sweet spot (NRMSE 3.4 %, peak 1.009) may partly
reflect *alignment luck* — the event starts exactly at +300 s, a 60 s window
boundary. Test: record a burst event whose burst starts mid-window (e.g.
+330 s), replay from tier-60, compare against the aligned reps.

**Patch to apply to `rec/record_event.sh` AFTER rep runs finish** (the file
is being executed by run_rep.sh — editing a running bash script corrupts it):

```bash
# was:
BURST_AT=$((DUR / 3))              # burst: start offset
# becomes:
BURST_AT=${REC_BURST_AT:-$((DUR / 3))}   # burst: start offset (env-overridable)
```

Then:

```bash
cd experiments
REC_BURST_AT=330 rec/record_event.sh burst 900
meta=$(ls -t rec/events/burst_*.meta | head -1)
# cache counter (same snippet as run_rep.sh), then:
e3/run_e3.sh "$PWD/$meta"
```

Expectation: tier-60 peak/std ratios land between the aligned tier-60 and
tier-300 cells. If instead they stay at the aligned values, the sweet spot is
duration-matching alone and the alignment caveat can be dropped from §19.

## Do-not-run conditions (both experiments)

- Any REC or E3 rep in flight (contaminates both directions).
- Poller down / telegraf down (tier-1m would have no raw to aggregate).
