# Grafana — visualization layer

How the twin is visualized, why it is built this way, and what bites you.
The [root README](../README.md) covers *running* the stack; this file covers
*understanding* the visualization.

| File | Purpose |
|---|---|
| `provisioning/datasources/influxdb.yml` | InfluxDB data source (Flux, `uid: influxdb`) |
| `provisioning/dashboards/dashboards.yml` | File-based dashboard provider |
| `provisioning/dashboards/traffic.json` | **DigSiViz Traffic** — live + time-machine time series (hand-maintained) |
| `provisioning/dashboards/topology.json` | **DigSiViz Topology** — weathermap (**generated**, do not hand-edit) |
| `flow/generate_flow.py` | Generates the SVG, panelConfig and `topology.json` from the clab topology |
| `flow/topology.svg`, `flow/panelconfig.yml` | Generated artifacts |

---

## 1. What is plugged into Grafana, and why

Everything is provisioned from files at startup — no manual UI clicking. This is
not just convenience: it is what makes the Grafana state **disposable**, which in
turn makes version bumps cheap to test and cheap to undo. A hand-built dashboard
was lost once to a `docker compose down -v`; that is the origin of this design.

`docker/docker-compose.yml` mounts `grafana/provisioning/` into the container and
passes InfluxDB credentials from `docker/.env`:

- **`INFLUX_TOKEN` / `INFLUX_ORG` / `INFLUX_BUCKET`** — interpolated into the
  datasource YAML via `$VAR`, so no credentials are committed.
- **`GF_PLUGINS_PREINSTALL_SYNC=andrewbmchugh-flow-panel`** — installs the flow
  panel at boot. **`SYNC` matters**: the plugin must exist *before* dashboards
  provision, or `topology.json` references a panel type Grafana does not have
  yet. (`GF_INSTALL_PLUGINS` is the deprecated spelling as of Grafana 11.)

### Version policy

Pinned to an exact tag (`grafana/grafana:13.0.3`), never `latest` — but pinned to
the **newest that works**, not frozen. Pinning is for reproducibility, not
stasis. Verified on 13.0.3: DB migration, Flux queries, datasource health,
dashboard provisioning, plugin install.

Two clarifications that matter:

- **Flux is *not* deprecated in Grafana.** InfluxData deprecated Flux in
  **InfluxDB 3.x**; that does not affect Grafana against InfluxDB 2.x, which is
  what we run. All panel queries here are Flux and are supported.
- **InfluxDB is deliberately *not* upgraded past 2.7.** InfluxDB 3 is a ground-up
  Rust rewrite that cannot run Flux at all *and has no Tasks*, so the entire
  12-tier downsample cascade would have no equivalent (InfluxData's guidance is
  to "rewrite your tasks using whatever technologies your team prefers"). 2.7 is
  the newest version that supports this design. Contrast Kafka/Zookeeper, pinned
  at `7.5.0` because they are tightly-coupled peers with a version-sensitive
  protocol.

---

## 2. How the historical (old-bucket) data is made visible

Raw data lives in `infldb` with ~1h retention. Everything older lives in the 12
downsample tier buckets (`traffic-1m` … `traffic-520w`). Three mechanisms expose
them:

**a) The `$tier` / `$bucket` dropdown.** Both dashboards carry a variable listing
the tiers, so one panel can be re-pointed at any granularity.

**b) `union()` across tiers, tagged by tier** (`traffic.json` time-machine
panels). Each bucket is tagged with `set(key: "tier", ...)` and grouped by it, so
series from different buckets never mix. Historically this also kept
`derivative()` from spanning two buckets, whose counters have independent
baselines; since the rate-first migration (2026-08-08) the tiers store **rates**
and the panels apply no derivative at all.

**c) Bars, not lines,** for downsampled data. Each bar is the aggregate for that
window. A line between points years apart falsely implies interpolation.

> **Gotcha: the query range must match the tier.** `traffic-52w` over `now-60d`
> returns *nothing* — its points are ~a year apart, so a 60-day window may contain
> no points at all. Over `now-20y` it returns fine. This looks like a broken panel
> and is not. (Before the rate-first migration the same symptom had a second
> cause: `derivative()` needs two points, so a range holding one showed nothing.)

> **UNITS (changed 2026-08-08).** The `traffic-*` buckets hold **rates in
> octets/s** under suffixed field names (`statistics_out-octets_{mean,min,max,
> median}`), *not* cumulative counters. Multiply by 8 for bits/s and **never
> apply `derivative()`** to a tier bucket. The raw bucket `infldb` is unchanged:
> cumulative counters under the base field names, so a rate still has to be
> derived there. Queries that must serve both — the flow panel's, since its
> `$bucket` dropdown spans raw *and* tiers — build both pipelines and `union()`
> them; a bucket holds one naming convention or the other, so exactly one branch
> is non-empty. See `rate_source()` in `flow/generate_flow.py`.

---

## 3. How the buckets get emptied, and how to refill them

Two independent ways to lose tier data. Both are fixed by re-running the backfill.

1. **`influx apply` recreating a bucket clears it.** Re-applying an *unchanged*
   manifest is safe (verified: an apply leaves row counts untouched). But any
   manifest edit that touches a bucket spec recreates that bucket and drops its
   data.
2. **Historically: no named volume.** InfluxDB data used to live in the
   container's writable layer, so a plain `docker compose down` — *no `-v`
   needed* — destroyed everything. **Fixed:** `influxdb-data` and
   `influxdb-config` are now named volumes. `down`/`up` is safe; only
   `down -v` clears them.

```bash
# refill the tiers with synthetic backdated points
cd "$(git rev-parse --show-toplevel)/influxdb"
python3 backfill.py
```

The cascade only downsamples *forward* from now, and raw retention is 1h, so it
can never build years of history on its own — hence backfill writes directly into
each tier bucket. See [`../influxdb/`](../influxdb/) and the root README.

> `DOCKER_INFLUXDB_INIT_RETENTION` only applies at **init**, so changing it needs
> `docker compose down -v` — which clears the volumes, per (2). Re-run backfill.

---

## 4. The topology weathermap (`DigSiViz Topology`)

Renders the clab topology as a weathermap: each link is coloured and labelled by
the outbound bit rate of its router-side interface, and a built-in **time slider**
scrubs the whole topology through the dashboard's time range. With the granularity
dropdown, this is the DigSiViz time machine — and pointed at a coarse tier, a time
machine over years.

Switching `$bucket` re-renders the *same topology* at a different tier's
resolution, which makes downsampling fidelity loss directly visible.

### Provenance: srl-telemetry-lab

Modelled on Nokia's reference telemetry lab,
[`srl-labs/srl-telemetry-lab`](https://github.com/srl-labs/srl-telemetry-lab),
which drives the same
[`andrewbmchugh-flow-panel`](https://grafana.com/grafana/plugins/andrewbmchugh-flow-panel/)
plugin from SRLinux telemetry. Adopted: the plugin itself, the two-cells-per-link
(directional) model, and the threshold-ladder idea. Two deliberate differences:

- **They feed it from Prometheus (via gnmic); we feed it from InfluxDB/Flux.**
  The plugin is datasource-agnostic — see §5. No Prometheus is required.
- **They query `interface_traffic_rate_out_bps`, a device-computed rate** exposed
  by SRLinux over gNMI. We poll `statistics_out-octets`, a **cumulative counter**,
  and derive the rate. These are *not* equivalent under downsampling
  (mean-of-rates ≠ derivative-of-mean-of-counters) — which quantity you store
  determines what downsampling does to it. **As of 2026-08-08 the cascade derives
  the rate before the first aggregation**, so the stored quantity is now the same
  *kind* of thing Nokia stores: a rate. The remaining difference is who computes
  it — their device, our pipeline (on a 2s lattice).

Nokia also paces traffic hard: `iperf3 -P 8 -b 200K -M 1480 -l 1480` ≈ 1.6 Mbit/s
total. Their thresholds (200k/500k/1M/5M) are scaled to that; ours are scaled up
for this lab and live in `THRESHOLDS` in the generator.

---

## 5. The Flux naming contract (the crux)

The panel binds a query series to an SVG cell **by name**: each cell declares a
`dataRef` which must equal the series name Grafana hands the plugin (the plugin
reads `getFieldDisplayName()`).

Nokia gets clean names for free — Prometheus `legendFormat` templates them
(`{{source}}:{{interface_name}}:out` → `spine1:e1-1:out`). **Flux does not.**
Grafana presents Flux results as an *unnamed* frame whose `_value` field carries
the tags as **labels**, so the plugin would see `_value {hostname="r1", …}` —
useless as a `dataRef`.

Fixed Flux-side, no panel override needed: `pivot()` turns each series into its
own **named column**, and Grafana names fields after columns.

```flux
  |> map(fn: (r) => ({_time: r._time, _value: r._value * 8.0,
                      name: r.hostname + ":" + r.interface_name + ":out"}))
  |> group()
  |> pivot(rowKey: ["_time"], columnKey: ["name"], valueColumn: "_value")
```

This yields fields named exactly `r1:ethernet-1/1:out` — what the generated
panelConfig references.

### Why `aggregateWindow` before `derivative` is load-bearing

> Applies to the **raw** bucket only. Tier buckets already store rates.


```flux
  |> aggregateWindow(every: 10s, fn: last, createEmpty: false)
  |> derivative(unit: 1s, nonNegative: true)
```

Without it the weathermap reads `0.0 b/s` almost always, for two reasons:

1. **`out-octets` is a step function at low rates.** The counter sits still for
   seconds, so differentiating consecutive 0.5s samples yields 0 for most
   samples, with occasional spikes. A time-series panel *hides* this — you see
   the spikes among 1800 plotted points — but the flow panel renders **one
   instant** (the slider position), so it reads whatever is true right then,
   which is usually 0.
2. **The raw bucket contains duplicate points** (identical values, timestamps
   microseconds apart — ~32–35 points per 10s window where 0.5s polling should
   give ~20). Differentiating across a duplicate pair gives a ~0 delta over a ~0
   interval. `fn: last` collapses each window to one value.

Tuning: too small a window and the map reads 0 between counter steps; too large
and short bursts are averaged away. On coarse tiers it is a no-op (their points
are already further apart than the window). At genuine idle, alternating 0 is
*correct* — there really is no traffic.

The companion **"Where is the traffic?"** strip below the weathermap shares the
dashboard time range, so peaks line up with slider positions: find a bar, drag
the slider to it.

---

## 6. Regenerating the weathermap

The SVG, panelConfig and dashboard are generated **from the clab topology file**,
so the drawing cannot drift from the lab that is actually deployed. (Hand-editing
repetitive config is what caused an earlier downsample-filter bug.)

```bash
cd "$(git rev-parse --show-toplevel)/grafana/flow"
python3 generate_flow.py
cd ../../docker && docker compose restart grafana
```

- Node positions live in `POS`; everything else (nodes, links, interface names)
  is read from `backend/ma-fp-stumpf.clab.yml`.
- Each physical link is drawn as **two half-lines**, one per direction, each
  bound to that endpoint's `:out` rate — utilisation is directional.
- Only SRLinux routers stream gNMI, so **host-side half-links are drawn but not
  data-bound** (dimmer grey). 9 cells are driven: 3 router↔router × 2 directions
  + 3 router→host.
- SVG and panelConfig are **inlined** into `topology.json` (the panel accepts
  content or a URL), so it renders with no network access. Nokia fetches theirs
  from raw.githubusercontent.
- A label only works if a `<text>` element **already exists** in the cell — the
  label drive rewrites existing text, it never creates it.

---

## 7. Debugging gotchas

- **Drop `_start`/`_stop` in any custom Flux feeding a timeseries panel.**
  `range()` adds them; they survive union/group/derivative, and Grafana — seeing
  multiple time-typed columns — may plot on `_start`, stacking every bar at the
  left edge regardless of its real date. Live panels mask it (small range →
  `_start` ≈ `_time`).
- **To check whether a panel really has data, POST its query to
  `/api/ds/query`** — do not trust the rendered tab. A "blank panel" was once
  just a stale browser tab; hard-refresh (Ctrl+Shift+R).
- **Datasource health is `/api/datasources/uid/influxdb/health`**, not
  `/api/datasources/proxy/...` (that path gives misleading "auth failed").
- **Rendering panels to PNG** (useful for paper figures) needs
  `grafana/grafana-image-renderer` plus `GF_RENDERING_SERVER_URL` **and** a
  non-default `GF_RENDERING_RENDERER_TOKEN` — Grafana **refuses to start**
  without the token. Not part of the committed stack.
