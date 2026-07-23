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
| `e1/` | `run_e1.sh <n> [n ...]` | flow-count sweep at fixed 10 Mbit/s total; finds the generator's flow-count envelope | `results/<ts>/` per-flow JSON + `*_hostcpu.log` / `*_containercpu.log`; `analyze_e1.py results/<ts>/` |
| `e2/` | `run_e2.sh <n_flows>` | endurance / duration sweep (`E2_DURATIONS` overridable); drift, CPU, loss over time | `results/<ts>/`; `analyze_e2.py results/<ts>/` |
| `rec/` | `record_event.sh <fluct\|burst> [dur]` | record a reference event through the pipeline (baseline + random 1.512 Mbit/s flows; `REC_MAX_DYN`, `REC_BURST_AT` overridable) | `events/<type>_<ts>.meta` + `.counter.csv` cache |
| `rec/` | `meta_check.py <event.meta>` | intended arrival schedule vs recorded trace (heterogeneous-generator validation) | stdout metrics |
| `rec/` | `run_sweep.sh` | REC concurrency sweep (`MAX_DYN ∈ {2,4,16}`) | `events/` + `sweep.log` |
| `e3/` | `run_e3.sh <event.meta> ...` | replay each event from tiers {raw, 60 s, 300 s}, analyze each replay vs the cached original | `results_<ts>.csv` |
| `e3/` | `aggregate_reps.py [csv ...]` | mean ± sample-std per (event, tier) over repetition CSVs | `aggregated_<n>reps.csv` |
| `.` | `run_rep.sh` | one full E3 repetition: record fresh fluct+burst, cache, run `run_e3.sh` over both | one `e3/results_<ts>.csv` |
| `burst_offset/` | `max_blindness.sh` | fire an identical burst at several offsets within separate 1-min windows; show tier `min`/`max` are invariant to placement | `blindness_<ts>.csv` |
| `burst_offset/` | `run_alignment.sh` | record a burst starting mid-window (`REC_BURST_AT=330`), replay per tier; tests window-alignment sensitivity | `burst_offset/alignment_*_result.csv` |

## Metric package (`analyze_e3.py`)

Per replay, against the raw-resolution original (zero-order hold of any coarse
tier — the lossy operator is never applied to the ground truth):

- **timing**: cross-correlation lag (s)
- **shape**: capacity-normalized NRMSE + MAE after alignment
- **characteristics**: preserved ratios for mean / max / std
- UDP loss + CPU act as guard rails — a run outside the E1/E2 envelope is
  invalid, not "low fidelity".

## The `rec/events/` retention trap

A multi-tier replay sequence outlives `infldb`'s 1 h retention, so each recorded
window's counter is cached to `<event>.counter.csv` immediately after recording.
Analysis reads originals from that cache; only replay traces (always < 1 h old)
are read live from InfluxDB.

## What is / isn't tracked

Committed: driver + analysis scripts, result CSVs, `.meta` files, `.counter.csv`
caches, replay traces, and per-second CPU logs. Ignored (`.gitignore`): raw
per-flow iperf3 JSON (bulky, regenerable from the scripts), `.err`, and run
transcripts. The CPU logs are kept because they are E1/E2's actual measurement.
