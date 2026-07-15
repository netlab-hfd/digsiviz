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

# Traffic thresholds in bits/s, driving link stroke colour.
# NOTE: calibrated for this lab (iperf3 saturation reaches ~70 Mbit/s over veth).
# Nokia's reference lab uses 200k/500k/1M/5M because it paces traffic to
# 1.6 Mbit/s total; these are scaled up accordingly and should be revisited once
# the P1 steady-load rate is settled.
THRESHOLDS = [
    ("#bec8d2", 0),  # grey   - idle
    ("#4BDD33", 100_000),  # green  - light
    ("#FFFF00", 1_000_000),  # yellow - moderate
    ("#FF8000", 10_000_000),  # orange - heavy
    ("#FF3154", 50_000_000),  # red    - saturated
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

    svg.append('</svg>')

    # ---- panelConfig -----------------------------------------------------
    thresholds = "\n".join(
        f'      - color: "{c}"\n        level: {lvl}' for c, lvl in THRESHOLDS
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
    lines.append("")

    return "\n".join(svg), "\n".join(lines)


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
    """
    return (
        'from(bucket: "${bucket}")\n'
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        '  |> filter(fn: (r) => r._measurement == "network_interface")\n'
        '  |> filter(fn: (r) => r._field == "statistics_out-octets" or '
        'r._field == "statistics_out-octets_mean")\n'
        '  |> group(columns: ["hostname", "interface_name"])\n'
        '  |> sort(columns: ["_time"])\n'
        "  |> derivative(unit: 1s, nonNegative: true)\n"
        "  |> map(fn: (r) => ({_time: r._time, _value: r._value * 8.0,\n"
        '                      name: r.hostname + ":" + r.interface_name + ":out"}))\n'
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
                "targets": [{"datasource": ds, "query": flux_query(), "refId": "A"}],
            }
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
