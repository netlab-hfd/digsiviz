#!/usr/bin/env python3
"""Generate the flow-panel topology weathermap from the clab topology.

Every output is derived from backend/ma-fp-stumpf.clab.yml so the weathermap can
never drift from the lab that is actually deployed. Same rationale as
influxdb/generate_manifest.py: the config is large and repetitive, so it is
derived rather than authored.

Outputs (regenerate after changing the clab topology):
    grafana/flow/topology.svg    - one SVG cell per node and per link direction
    grafana/flow/panelconfig.yml - maps SVG cell ids -> query series names
    grafana/provisioning/dashboards/topology.json
                                 - provisioned dashboard, SVG + panelConfig
                                   inlined so the repo needs no network at
                                   render time

topology.json is fully generated; traffic.json is hand-maintained. Keeping the
generated and authored dashboards in separate files avoids the fragile
"partly generated" state.

Usage:  python3 generate_flow.py
"""

import json
import math
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CLAB = REPO / "backend" / "ma-fp-stumpf.clab.yml"
OUT_SVG = Path(__file__).parent / "topology.svg"
OUT_YML = Path(__file__).parent / "panelconfig.yml"
OUT_DASH = REPO / "grafana" / "provisioning" / "dashboards" / "topology.json"

# Granularity tiers, in cascade order. Doubles as the bucket dropdown: picking a
# tier re-renders the same topology at that tier's resolution, which is the
# RQ2 demonstration -- the fidelity loss becomes directly visible.
BUCKETS = [
    "infldb",
    "traffic-1m",
    "traffic-5m",
    "traffic-1h",
    "traffic-8h",
    "traffic-1d",
    "traffic-1w",
    "traffic-4w",
    "traffic-12w",
    "traffic-24w",
    "traffic-52w",
    "traffic-260w",
    "traffic-520w",
]

# Hand-placed positions. Auto-layout is overkill for six nodes, and a stable
# hand-placed map keeps diffs readable when the topology changes.
POS = {
    "r1": (400, 150),
    "r2": (200, 400),
    "r3": (600, 400),
    "h1": (400, 45),
    "h2": (95, 525),
    "h3": (705, 525),
}

BOX_W, BOX_H = 92, 44
CANVAS = (800, 600)

# Window the counter is collapsed onto before the rate is derived. See
# flux_query() for why this is required rather than cosmetic. Too small and the
# weathermap reads 0 between counter steps; too large and short bursts are
# averaged away. 10s is a compromise for a live view.
RATE_WINDOW = "10s"

# Traffic thresholds in bits/s, driving link stroke colour.
# Calibrated to the 10 Mbit/s scale-model cap (meeting 2026-07-17: treat the
# link as a gigabit divided by 100). Levels are fractions of that capacity:
# 1% / 25% / 50% / 80% — red means "saturated relative to the modelled link".
THRESHOLDS = [
    ("#bec8d2", 0),  # grey   - idle
    ("#4BDD33", 100_000),  # green  - light      (>1%)
    ("#FFFF00", 2_500_000),  # yellow - moderate  (>25%)
    ("#FF8000", 5_000_000),  # orange - heavy     (>50%)
    ("#FF3154", 8_000_000),  # red    - saturated (>80%)
]

# Node-fill thresholds: same levels, darker tints so the white node label stays
# readable. Drives "highlight the node where the traffic is" (meeting
# 2026-07-17, directive 1): a node lights up when its busiest interface does.
NODE_THRESHOLDS = [
    ("#2b3a4a", 0),  # idle    - the normal router fill
    ("#1e4d2b", 100_000),  # green tint
    ("#5c5416", 2_500_000),  # yellow tint
    ("#66391a", 5_000_000),  # orange tint
    ("#7a1f2e", 8_000_000),  # red tint - this node is where the traffic is
]


def load_topology():
    """Return (nodes, links) where nodes maps name -> kind."""
    topo = yaml.safe_load(CLAB.read_text())["topology"]
    kinds = {n: (spec or {}).get("kind", "nokia_srlinux") for n, spec in topo["nodes"].items()}
    links = []
    for link in topo["links"]:
        (a, b) = link["endpoints"]
        a_node, a_if = a.split(":", 1)
        b_node, b_if = b.split(":", 1)
        links.append(((a_node, a_if), (b_node, b_if)))
    return kinds, links


def edge_point(center, toward, halfw=BOX_W / 2, halfh=BOX_H / 2):
    """Point where the line center->toward exits the node's box."""
    cx, cy = center
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return center
    # Scale the direction vector until it hits the box edge.
    scale = min(
        halfw / abs(dx) if dx else math.inf,
        halfh / abs(dy) if dy else math.inf,
    )
    return (cx + dx * scale, cy + dy * scale)


def build(kinds, links):
    svg = []
    cells = {}

    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS[0]} {CANVAS[1]}" width="{CANVAS[0]}" height="{CANVAS[1]}">'
    )
    svg.append(
        '<style>'
        '.nlabel{font:600 13px sans-serif;fill:#e6e9ed;text-anchor:middle;dominant-baseline:middle}'
        '.rate{font:500 11px sans-serif;fill:#c8d0d9;text-anchor:middle}'
        '</style>'
    )

    # ---- links (drawn first so node boxes sit on top) --------------------
    for (a_node, a_if), (b_node, b_if) in links:
        ca, cb = POS[a_node], POS[b_node]
        mid = ((ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2)

        for (near, near_if), (far, far_if), near_c in (
            ((a_node, a_if), (b_node, b_if), ca),
            ((b_node, b_if), (a_node, a_if), cb),
        ):
            start = edge_point(near_c, mid)
            name = f"link_id:{near}:{near_if}:{far}:{far_if}"

            # Only SRLinux routers stream gNMI counters. Host-side half-links
            # are drawn but carry no data, so they get no cell binding.
            drivable = kinds.get(near) == "nokia_srlinux"

            # Label sits partway out from the node so the two directions of one
            # link do not overlap, and is pushed perpendicular to the line so it
            # does not sit on top of it.
            lx = start[0] + (mid[0] - start[0]) * 0.5
            ly = start[1] + (mid[1] - start[1]) * 0.5
            vx, vy = mid[0] - start[0], mid[1] - start[1]
            vlen = math.hypot(vx, vy) or 1.0
            lx += -vy / vlen * 14
            ly += vx / vlen * 14

            if drivable:
                svg.append(f'<g id="cell-{name}">')
                svg.append(
                    f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
                    f'x2="{mid[0]:.1f}" y2="{mid[1]:.1f}" '
                    f'stroke="#98a2ae" stroke-width="4" stroke-linecap="round"/>'
                )
                # The label drive only rewrites an existing <text>; it never
                # creates one. This element must be present or the label is a
                # silent no-op.
                svg.append(f'<text class="rate" x="{lx:.1f}" y="{ly:.1f}">-</text>')
                svg.append('</g>')
                cells[name] = f"{near}:{near_if}:out"
            else:
                svg.append(
                    f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
                    f'x2="{mid[0]:.1f}" y2="{mid[1]:.1f}" '
                    f'stroke="#5a636d" stroke-width="4" stroke-linecap="round"/>'
                )

    # ---- nodes -----------------------------------------------------------
    # Router nodes are data-driven: fill colour follows the node's busiest
    # interface (`<node>:hot` series from node_query()), so the topology
    # answers "where is the traffic" at a glance. Host nodes stay static —
    # they stream no gNMI.
    node_cells = []
    for node, (cx, cy) in POS.items():
        is_router = kinds.get(node) == "nokia_srlinux"
        fill = "#2b3a4a" if is_router else "#3a3040"
        stroke = "#7d8b99" if is_router else "#6d5f7a"
        svg.append(f'<g id="cell-{node}">')
        svg.append(
            f'<rect x="{cx - BOX_W/2:.1f}" y="{cy - BOX_H/2:.1f}" '
            f'width="{BOX_W}" height="{BOX_H}" rx="6" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        svg.append(f'<text class="nlabel" x="{cx:.1f}" y="{cy:.1f}">{node}</text>')
        svg.append('</g>')
        if is_router:
            node_cells.append(node)

    svg.append('</svg>')

    # ---- panelConfig -----------------------------------------------------
    thresholds = "\n".join(
        f'      - color: "{c}"\n        level: {lvl}' for c, lvl in THRESHOLDS
    )
    node_thresholds = "\n".join(
        f'      - color: "{c}"\n        level: {lvl}' for c, lvl in NODE_THRESHOLDS
    )
    lines = [
        "---",
        "# GENERATED by grafana/flow/generate_flow.py - do not edit by hand.",
        "# Maps SVG cell ids to query series names. The series name is produced by",
        "# the panel's Flux query via pivot(), which turns each series into its own",
        "# named column (Grafana names fields after columns).",
        "",
        "anchors:",
        "  thresholds-traffic: &thresholds-traffic",
        thresholds,
        "  thresholds-node: &thresholds-node",
        node_thresholds,
        "  label-config: &label-config",
        "    separator: replace",
        "    units: bps",
        "    decimalPoints: 1",
        "",
        'cellIdPreamble: "cell-"',
        "",
        "cells:",
    ]
    for cell, dataref in cells.items():
        lines.append(f"  {cell}:")
        lines.append(f'    dataRef: "{dataref}"')
        lines.append("    label: *label-config")
        lines.append("    strokeColor:")
        lines.append("      thresholds: *thresholds-traffic")
    # Router node fills follow their `<node>:hot` series (busiest interface).
    # No label config: the label drive would overwrite the node-name <text>.
    for node in node_cells:
        lines.append(f"  {node}:")
        lines.append(f'    dataRef: "{node}:hot"')
        lines.append("    fillColor:")
        lines.append("      thresholds: *thresholds-node")
    lines.append("")

    return "\n".join(svg), "\n".join(lines)


def rate_source(base_field):
    """Flux that yields a RATE stream grouped per (hostname, interface_name),
    for whichever bucket `${bucket}` happens to be.

    The dropdown spans the raw bucket AND the tier buckets, and since the
    2026-08-08 rate-first migration those two hold different things:
      * infldb        -> cumulative COUNTERS under the base field name, so a
                        rate must be derived here (on a regular grid: see the
                        step-function and duplicate-point reasons in
                        flux_query's docstring).
      * traffic-*     -> RATES already, in octets/s, under `<base>_mean`.
                        Differentiating these AGAIN would differentiate a rate.

    Rather than branch on the bucket name, both pipelines are built and unioned:
    a bucket contains one field naming convention or the other, so exactly one
    branch is non-empty and the union is the correct stream either way. That
    keeps a single query valid across the whole dropdown, which is what the flow
    panel needs -- it binds series by NAME, so the shape of the result must not
    depend on which bucket is selected.
    """
    grp = '  |> group(columns: ["hostname", "interface_name"])\n'
    return (
        "counters = from(bucket: \"${bucket}\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        '  |> filter(fn: (r) => r._measurement == "network_interface")\n'
        f'  |> filter(fn: (r) => r._field == "{base_field}")\n'
        + grp +
        f"  |> aggregateWindow(every: {RATE_WINDOW}, fn: last, createEmpty: false)\n"
        "  |> derivative(unit: 1s, nonNegative: true)\n"
        "\n"
        "rates = from(bucket: \"${bucket}\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        '  |> filter(fn: (r) => r._measurement == "network_interface")\n'
        f'  |> filter(fn: (r) => r._field == "{base_field}_mean")\n'
        + grp +
        "\n"
        "union(tables: [counters, rates])\n"
    )


def flux_query():
    """Series named `<host>:<iface>:out`, which is what panelConfig dataRefs match.

    Grafana presents Flux results as an unnamed frame whose _value field carries
    the tags as *labels*, so the plugin would see `_value {hostname="r1", ...}`.
    pivot() turns each series into its own named column instead, and Grafana
    names fields after columns -- giving the plugin the exact string it needs
    without any panel-level override.

    The _field filter accepts both the raw/backfill name and the cascade's
    `_mean` suffix so one query serves every bucket. A bucket holding *both*
    would collide in pivot(); in practice a bucket has one or the other.

    aggregateWindow(fn: last) before derivative() is load-bearing, for two
    reasons that only show up on the weathermap:
      1. out-octets is a *step function* at low rates -- the counter sits still
         for seconds at a time. Differentiating consecutive 0.5s samples
         therefore yields 0 for most samples, with occasional spikes. A time
         series panel hides this (you see the spikes among 1800 plotted points),
         but the flow panel renders ONE instant at the time-slider position, so
         it would read 0 almost always.
      2. the raw bucket contains duplicate points (same value, timestamps
         microseconds apart). Differentiating across a duplicate pair gives a
         ~0 delta over a ~0 interval. `last` collapses each window to one value.
    Collapsing to a regular grid first makes the delta meaningful. On the coarse
    tier buckets this is effectively a no-op -- their points are already further
    apart than the window.
    """
    return (
        rate_source("statistics_out-octets") +
        "  |> map(fn: (r) => ({_time: r._time, _value: r._value * 8.0,\n"
        '                      name: r.hostname + ":" + r.interface_name + ":out"}))\n'
        "  |> group()\n"
        '  |> pivot(rowKey: ["_time"], columnKey: ["name"], valueColumn: "_value")'
    )


def node_query():
    """Per-node hot series: `<host>:hot` = the node's busiest interface rate.

    Drives router node fill colour ("highlight the node where the traffic is",
    meeting 2026-07-17 directive 1). max() across the node's interfaces rather
    than sum(): a node with one saturated link should light fully, not be
    diluted by its idle links — same reasoning as activity_query().

    Same rate pipeline as flux_query() (aggregateWindow last -> derivative),
    then collapsed per (hostname, _time) and pivoted to `<host>:hot` columns.
    """
    return (
        rate_source("statistics_out-octets") +
        '  |> group(columns: ["hostname", "_time"])\n'
        "  |> max()\n"
        "  |> map(fn: (r) => ({_time: r._time, _value: r._value * 8.0,\n"
        '                      name: r.hostname + ":hot"}))\n'
        "  |> group()\n"
        '  |> pivot(rowKey: ["_time"], columnKey: ["name"], valueColumn: "_value")'
    )


def activity_query():
    """Per-NODE busiest-interface rate over time -- the 'where is the traffic'
    strip (meeting 2026-07-17, directive 1).

    One series per router, so a spike carries its location: the bar's colour /
    tooltip / legend name the node. Workflow: spot a spike, read (or
    legend-click to isolate) which node, drag the flow panel's time slider to
    that instant -- the same node lights up on the topology via its `<host>:hot`
    fill. This is the closest Grafana-native equivalent of "click the spike and
    highlight the node": the strip identifies, the slider position highlights.

    max() across each node's interfaces rather than sum(), so a single busy
    link still shows at full height instead of being diluted by idle ones --
    same reasoning as node_query().
    """
    return (
        rate_source("statistics_out-octets") +
        '  |> group(columns: ["hostname", "_time"])\n'
        "  |> max()\n"
        "  |> map(fn: (r) => ({_time: r._time, _value: r._value * 8.0, name: r.hostname}))\n"
        "  |> group()\n"
        '  |> pivot(rowKey: ["_time"], columnKey: ["name"], valueColumn: "_value")'
    )


def build_dashboard(svg, cfg):
    ds = {"type": "influxdb", "uid": "influxdb"}
    return {
        "annotations": {"list": []},
        "editable": True,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "panels": [
            {
                "type": "andrewbmchugh-flow-panel",
                "title": "Topology — link load (drag the time slider to replay)",
                "description": (
                    "Weathermap of the clab topology. Link stroke colour and label "
                    "follow the outbound bit rate of the router-side interface. Use "
                    "the $bucket dropdown to switch granularity tier and the built-in "
                    "time slider to scrub through history — this is the DigSiViz "
                    "time machine."
                ),
                "datasource": ds,
                "gridPos": {"h": 18, "w": 24, "x": 0, "y": 0},
                "id": 1,
                "options": {
                    # SVG + panelConfig inlined (both accept content or a URL) so
                    # the dashboard renders with no network access.
                    "svg": svg,
                    "panelConfig": cfg,
                    "siteConfig": "",
                    "timeSliderEnabled": True,
                    "panZoomEnabled": True,
                    "highlighterEnabled": True,
                    "animationsEnabled": True,
                    "animationControlEnabled": True,
                    "testDataEnabled": False,
                    "debuggingCtr": {
                        "colorsCtr": 0,
                        "dataCtr": 0,
                        "displaySvgCtr": 0,
                        "mappingsCtr": 0,
                        "timingsCtr": 0,
                    },
                },
                "targets": [
                    {"datasource": ds, "query": flux_query(), "refId": "A"},
                    # B feeds the router node fills (`<host>:hot`); the flow
                    # panel matches dataRefs across all frames of all queries.
                    {"datasource": ds, "query": node_query(), "refId": "B"},
                ],
            },
            {
                "type": "timeseries",
                "title": "Where is the traffic? — per-node load (spot a spike → its colour names the node → drag the slider there, the node lights up)",
                "description": (
                    "One series per router: a spike's colour/tooltip identifies "
                    "WHICH node carried the traffic. Legend-click isolates one "
                    "node. Drag the weathermap's time slider to the spike and the "
                    "same node's box lights up on the topology. Shares the "
                    "dashboard time range, so peaks line up with slider positions."
                ),
                "datasource": ds,
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": 18},
                "id": 2,
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "palette-classic"},
                        "custom": {
                            "drawStyle": "bars",
                            "fillOpacity": 70,
                            "lineWidth": 1,
                            "pointSize": 4,
                            "showPoints": "auto",
                            "axisPlacement": "auto",
                            "barAlignment": 0,
                            "gradientMode": "none",
                            "scaleDistribution": {"type": "linear"},
                            "stacking": {"group": "A", "mode": "none"},
                            "thresholdsStyle": {"mode": "off"},
                        },
                        "mappings": [],
                        "thresholds": {
                            "mode": "absolute",
                            "steps": [{"color": "green", "value": None}],
                        },
                        "unit": "bps",
                    },
                    "overrides": [],
                },
                "options": {
                    "legend": {
                        "calcs": ["max"],
                        "displayMode": "list",
                        "placement": "bottom",
                        "showLegend": True,
                    },
                    "tooltip": {"mode": "single", "sort": "none"},
                },
                "targets": [{"datasource": ds, "query": activity_query(), "refId": "A"}],
            },
        ],
        "refresh": "10s",
        "schemaVersion": 39,
        "tags": ["digsiviz", "topology"],
        "templating": {
            "list": [
                {
                    "name": "bucket",
                    "label": "Granularity tier",
                    "type": "custom",
                    "multi": False,
                    "includeAll": False,
                    "query": ",".join(BUCKETS),
                    "current": {"text": BUCKETS[0], "value": BUCKETS[0]},
                    "options": [
                        {"text": b, "value": b, "selected": i == 0}
                        for i, b in enumerate(BUCKETS)
                    ],
                }
            ]
        },
        "time": {"from": "now-15m", "to": "now"},
        "timepicker": {},
        "timezone": "",
        "title": "DigSiViz Topology",
        "uid": "digsiviz-topology",
        "version": 1,
        "weekStart": "",
    }


def main():
    kinds, links = load_topology()
    svg, cfg = build(kinds, links)
    OUT_SVG.write_text(svg + "\n")
    OUT_YML.write_text(cfg)
    OUT_DASH.write_text(json.dumps(build_dashboard(svg, cfg), indent=2) + "\n")
    driven = cfg.count("dataRef:")
    print(f"wrote {OUT_SVG.relative_to(REPO)} ({len(svg)} bytes)")
    print(f"wrote {OUT_YML.relative_to(REPO)} ({driven} driven cells)")
    print(f"wrote {OUT_DASH.relative_to(REPO)} (svg + panelConfig inlined)")


if __name__ == "__main__":
    main()
