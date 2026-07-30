# DigSiViz traffic-replay experiments

Measurement scripts for the traffic-replay / storage-granularity study on the
`feature/store-replay-traffic-tsdb` branch. All experiments drive the live
pipeline (SR Linux lab → gNMI poller → Kafka → Telegraf → InfluxDB) and read
back through InfluxDB. They depend on the stack in `../docker` being up and the
`ma-fp-stumpf` containerlab topology deployed (see the repo root README).

Run every script from its own directory. The Python analysis scripts use only
the standard library plus the shared `../../influxdb/e_repr.py` helper (Flux
query + counter→rate conversion on a fixed lattice); no venv packages required.

## Stages (run in order)

| dir | script | what it does | output |
|---|---|---|---|
| `e1/` | `run_e1.sh <n> [n ...]` | flow-count sweep at fixed 10 Mbit/s total; finds the generator's flow-count envelope | `results/<ts>/` per-flow JSON + `*_hostcpu.log` / `*_containercpu.log`; `analyze_e1.py results/<ts>/ [summary.csv]` |
| `e2/` | `run_e2.sh <n_flows>` | endurance / duration sweep (`E2_DURATIONS` overridable); drift, CPU, loss over time | `results/<ts>/`; `analyze_e2.py results/<ts>/ [summary.csv]` |
| `rec/` | `record_event.sh <fluct\|burst> [dur]` | record a reference event through the pipeline (baseline + random 1.512 Mbit/s flows; `REC_MAX_DYN`, `REC_BURST_AT` overridable) | `events/<type>_<ts>.meta` + `.counter.csv` cache |
| `rec/` | `meta_check.py <event.meta>` | intended arrival schedule vs recorded trace (heterogeneous-generator validation) | stdout metrics |
| `rec/` | `run_sweep.sh` | REC concurrency sweep (`MAX_DYN ∈ {2,4,16}`) | `events/` + `sweep.log` |
| `e3/` | `run_e3.sh <event.meta> ...` | replay each event from tiers {raw, 60 s, 300 s}, analyze each replay vs the cached original | `results_<ts>.csv` |
| `e3/` | `aggregate_reps.py [csv ...]` | mean ± sample-std per (event, tier) over repetition CSVs | `aggregated_<n>reps.csv` **beside the inputs** |
| `e3/` | `capture_replay_trace.py --watch ../rec/events` | dump each replay's recorded trace to disk before retention drops it | `<event>.replay_tier<N>.counter.csv` |
| `.` | `run_rep.sh` | one full E3 repetition: record fresh fluct+burst, cache, run `run_e3.sh` over both | one `e3/results_<ts>.csv` |
| `burst_offset/` | `max_blindness.sh` | fire an identical burst at several offsets within separate 1-min windows; show tier `min`/`max` are invariant to placement | `blindness_<ts>.csv` |
| `burst_offset/` | `run_alignment.sh` | record a burst starting mid-window (`REC_BURST_AT=330`), replay per tier; tests window-alignment sensitivity | `burst_offset/alignment_*_result.csv` |
| `e_repr/` | `../../influxdb/e_repr.py --counter-csv <event>.counter.csv` | storage error alone (no replay): each tier vs. the raw truth, both aggregation orders | `e_repr/e_repr_events.csv` (via `--csv-out`) |

`e_repr.py` also runs live (`--minutes 55`) against InfluxDB; `--counter-csv`
replays it offline over a recorded event's cached counter, which is how
`e_repr/e_repr_events.csv` was produced — one row set per E3 event, so E_repr
(storage) and E3 (storage + replay) refer to exactly the same traces.

## Metric package (`analyze_e3.py`)

Per replay, against the raw-resolution original (zero-order hold of any coarse
tier — the lossy operator is never applied to the ground truth):

- **timing**: cross-correlation lag (s)
- **shape**: capacity-normalized NRMSE + MAE after alignment
- **characteristics**: preserved ratios for mean / max / std
- UDP loss + CPU act as guard rails — a run outside the E1/E2 envelope is
  invalid, not "low fidelity".

## Aggregation order: the deployed cascade and the replay driver differ

Two orders exist and they do not commute:

- **agg→deriv** — aggregate the cumulative counter, then differentiate. This is
  what the deployed InfluxDB cascade (`../influxdb/manifest.yml`) does today.
- **deriv→agg** — differentiate to a rate first, then aggregate the rate. This
  is what `e3/replay_tier.py` uses to build its tier traces, and what
  `e_repr.py` reports as the fix.

The experiments deliberately drive replay from **deriv→agg** so that E3 measures
the granularity boundary itself rather than the known counter-aggregation defect.
`e_repr/e_repr_events.csv` quantifies the gap between the two orders on the same
events (volume error 6 % at 60 s / 30 % at 300 s for agg→deriv, exactly 0 % for
deriv→agg), which is the argument for changing the cascade. Any writeup must
state this: the manifest and the replay driver are not yet the same operator.

## The `rec/events/` retention trap

A multi-tier replay sequence outlives `infldb`'s 1 h retention, so each recorded
window's counter is cached to `<event>.counter.csv` immediately after recording.
Analysis reads originals from that cache; only replay traces (always < 1 h old)
are read live from InfluxDB.

The replay traces themselves expire the same way. `analyze_e3.py` reads each one
live and keeps only the metrics, so an hour later the trace behind a number is
gone — which makes original-vs-replay plots impossible after the fact. Run
`e3/capture_replay_trace.py --watch ../rec/events` alongside a replay sequence
to cache each trace as it lands; `analyze_e3.py` then prefers that cache, so a
run can also be re-analyzed later.

## What is / isn't tracked

Committed: driver + analysis scripts, result CSVs, `.meta` files, `.counter.csv`
caches, replay traces, and per-second CPU logs. Ignored (`.gitignore`): raw
per-flow iperf3 JSON (bulky, regenerable from the scripts), `.err`, and run
transcripts. The CPU logs are kept because they are E1/E2's actual measurement.

Because the per-flow JSON is not tracked, E1/E2's achieved-rate, loss and drift
numbers are committed in derived form as `e1/results/<ts>/summary.csv` and
`e2/results/<ts>/summary.csv` (written by the analysis scripts' optional second
argument). Those CSVs, not the JSON, are the citable E1/E2 record.
