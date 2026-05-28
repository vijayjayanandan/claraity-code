"""
Architecture HTML export -- generates a self-contained ARCHITECTURE.html
from a claraity_knowledge.jsonl file.

Usage:
    python -m src.claraity.export_html
    python -m src.claraity.export_html --jsonl path/to/knowledge.jsonl --out ARCHITECTURE.html
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# JSONL loader
# ---------------------------------------------------------------------------


def load_jsonl(path: str) -> tuple[dict, list[dict], list[dict]]:
    meta, nodes, edges = {}, [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            t = r.get("_t")
            if t == "meta":
                meta[r["key"]] = r["value"]
            elif t == "node":
                props = r.get("properties", {})
                if isinstance(props, str):
                    try:
                        props = json.loads(props)
                    except Exception:
                        props = {}
                r["properties"] = props
                nodes.append(r)
            elif t == "edge":
                edges.append(r)
    return meta, nodes, edges


# ---------------------------------------------------------------------------
# Layout  (Python port of ArchitecturePanel calculateLayout)
# ---------------------------------------------------------------------------

COMP_W, COMP_H, COMP_PAD = 140, 34, 10
MOD_PAD_TOP, MOD_PAD = 30, 12
COLLAPSED_W, COLLAPSED_H = 160, 44
ROW_GAP, COL_GAP = 36, 20
CANVAS_W = 1300


def _module_color(mod_id: str) -> str:
    h = 0
    for ch in mod_id:
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
    hue = h % 360
    s, l = 0.65, 0.60
    a = s * min(l, 1 - l)

    def f(n):
        k = (n + hue / 30) % 12
        color = l - a * max(min(k - 3, 9 - k, 1), -1)
        return format(round(255 * color), "02x")

    return f"#{f(0)}{f(8)}{f(4)}"


EDGE_COLORS = {
    "uses": "#58a6ff",
    "calls": "#3fb950",
    "writes": "#f85149",
    "reads": "#79c0ff",
    "spawns": "#bc8cff",
    "drives": "#f778ba",
    "renders": "#3fb950",
    "dispatches": "#79c0ff",
    "controls": "#d29922",
    "configures": "#d29922",
    "bridges": "#f778ba",
    "wraps": "#8b949e",
    "interacts": "#f778ba",
    "communicates": "#f778ba",
    "connects": "#8b949e",
    "fetches": "#79c0ff",
    "queries": "#79c0ff",
    "reads_writes": "#d29922",
    "related": "#8b949e",
}
RISK_COLORS = {"high": "#f85149", "medium": "#d29922", "low": "#3fb950"}
DEFAULT_COLOR = "#8b949e"
EDGE_PRIORITY = {"writes": 5, "calls": 4, "drives": 4, "spawns": 3, "uses": 2, "reads": 2}


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def curved_path(fx, fy, fw, fh, tx, ty, tw, th) -> str:
    dx, dy = tx - fx, ty - fy
    dist = math.sqrt(dx * dx + dy * dy)
    if dist == 0:
        return f"M{fx},{fy}L{tx},{ty}"
    ux, uy = dx / dist, dy / dist
    ft = min(abs(fw / 2 / ux) if ux else 1e9, abs(fh / 2 / uy) if uy else 1e9)
    tt = min(abs(tw / 2 / ux) if ux else 1e9, abs(th / 2 / uy) if uy else 1e9)
    x1 = fx + ux * ft
    y1 = fy + uy * ft
    x2 = tx - ux * (tt + 8)
    y2 = ty - uy * (tt + 8)
    mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
    curv = min(dist * 0.2, 60)
    cx1 = mid_x - uy * curv
    cy1 = mid_y + ux * curv
    return f"M{x1:.1f},{y1:.1f} Q{cx1:.1f},{cy1:.1f} {x2:.1f},{y2:.1f}"


def calculate_layout(nodes: list[dict], edges: list[dict]):
    node_map = {n["id"]: n for n in nodes}
    modules = [n for n in nodes if n["type"] == "module"]
    systems = [n for n in nodes if n["type"] == "system"]
    contains = [e for e in edges if e["type"] == "contains"]

    mod_children: dict[str, list[str]] = defaultdict(list)
    child_to_mod: dict[str, str] = {}
    for e in contains:
        if e["from_id"] in node_map and node_map[e["from_id"]]["type"] == "module":
            mod_children[e["from_id"]].append(e["to_id"])
            child_to_mod[e["to_id"]] = e["from_id"]

    mod_layouts = []
    for mod in modules:
        children = [node_map[c] for c in mod_children.get(mod["id"], []) if c in node_map]
        components = [c for c in children if c["type"] == "component"]
        if not children:
            continue
        p = mod["properties"]
        label = mod["name"].replace("src/", "").rstrip("/")

        child_layouts = []
        w, h = COLLAPSED_W, COLLAPSED_H

        files = [c for c in children if c["type"] == "file"]
        mod_layouts.append(
            {
                "id": mod["id"],
                "node": mod,
                "label": label,
                "w": w,
                "h": h,
                "children": child_layouts,
                "count": len(components),
                "file_count": len(files),
                "color": _module_color(mod["id"]),
                "flow_rank": p.get("flow_rank", 99),
                "flow_col": p.get("flow_col", 0),
                "x": 0,
                "y": 0,
            }
        )

    # Position modules by flow_rank rows
    rows: dict[int, list] = defaultdict(list)
    for ml in mod_layouts:
        rows[ml["flow_rank"]].append(ml)

    cy = 60
    pos_map: dict[str, dict] = {}
    for rank in sorted(rows):
        row = sorted(rows[rank], key=lambda m: m["flow_col"])
        total_w = sum(m["w"] for m in row) + (len(row) - 1) * COL_GAP
        cx = max(20, (CANVAS_W - total_w) / 2)
        max_h = 0
        for ml in row:
            ml["x"], ml["y"] = cx, cy
            pos_map[ml["id"]] = {
                "x": ml["x"] + ml["w"] / 2,
                "y": ml["y"] + ml["h"] / 2,
                "w": ml["w"],
                "h": ml["h"],
            }
            for cl in ml["children"]:
                cl["x"] = ml["x"] + cl["relX"]
                cl["y"] = ml["y"] + cl["relY"]
                pos_map[cl["id"]] = {
                    "x": cl["x"] + cl["w"] / 2,
                    "y": cl["y"] + cl["h"] / 2,
                    "w": cl["w"],
                    "h": cl["h"],
                }
            cx += ml["w"] + COL_GAP
            max_h = max(max_h, ml["h"])
        cy += max_h + ROW_GAP

    # System nodes at top
    sys_sorted = sorted(systems, key=lambda s: s["properties"].get("flow_col", 99))
    total_sw = len(sys_sorted) * 120 + (len(sys_sorted) - 1) * 16
    sx = max(20, (CANVAS_W - total_sw) / 2)
    sys_layouts = []
    for i, s in enumerate(sys_sorted):
        sys_layouts.append(
            {"id": s["id"], "node": s, "x": sx + i * 136, "y": 10, "w": 120, "h": 28}
        )
        pos_map[s["id"]] = {"x": sx + i * 136 + 60, "y": 24, "w": 120, "h": 28}

    # Visible edges (dedup by priority)
    def visible_id(nid):
        pm = child_to_mod.get(nid)
        return pm if pm else nid

    edge_map: dict[str, dict] = {}
    for e in edges:
        if e["type"] in ("contains", "constrains"):
            continue
        fn = node_map.get(e["from_id"])
        tn = node_map.get(e["to_id"])
        fv = visible_id(e["from_id"]) if fn and fn["type"] == "component" else e["from_id"]
        tv = visible_id(e["to_id"]) if tn and tn["type"] == "component" else e["to_id"]
        if fv == tv or fv not in pos_map or tv not in pos_map:
            continue
        key = f"{fv}:{tv}"
        pri = EDGE_PRIORITY.get(e["type"], 1)
        ex = edge_map.get(key)
        if not ex or pri > EDGE_PRIORITY.get(ex["type"], 1):
            edge_map[key] = {"from": fv, "to": tv, "type": e["type"], "label": e.get("label")}

    total_h = cy + 20
    return mod_layouts, sys_layouts, list(edge_map.values()), pos_map, total_h


# ---------------------------------------------------------------------------
# SVG builder
# ---------------------------------------------------------------------------


def build_svg(mod_layouts, sys_layouts, vis_edges, pos_map, total_h) -> str:
    parts = []
    w, h = CANVAS_W, total_h
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="max-width:100%;height:auto;">'
    )

    # Defs: arrowhead markers
    parts.append("<defs>")
    seen_colors = set()
    for etype, color in {**EDGE_COLORS, "default": DEFAULT_COLOR}.items():
        if color in seen_colors:
            continue
        seen_colors.add(color)
        mid = etype
        parts.append(
            f'<marker id="arr-{mid}" viewBox="0 -4 8 8" refX="8" refY="0" '
            f'markerWidth="6" markerHeight="6" orient="auto">'
            f'<path d="M0,-4L8,0L0,4Z" fill="{color}"/></marker>'
        )
    parts.append("</defs>")

    # Edges
    for e in vis_edges:
        fp = pos_map[e["from"]]
        tp = pos_map[e["to"]]
        color = EDGE_COLORS.get(e["type"], DEFAULT_COLOR)
        marker_color = EDGE_COLORS.get(e["type"], DEFAULT_COLOR)
        # find marker id
        marker_id = next(
            (k for k, v in {**EDGE_COLORS, "default": DEFAULT_COLOR}.items() if v == marker_color),
            "default",
        )
        d = curved_path(fp["x"], fp["y"], fp["w"], fp["h"], tp["x"], tp["y"], tp["w"], tp["h"])
        label_attr = f' data-label="{html_lib.escape(e["label"])}"' if e.get("label") else ""
        parts.append(
            f'<path d="{d}" stroke="{color}" stroke-width="1.3" fill="none" '
            f'stroke-opacity="0.5" stroke-dasharray="6 4" '
            f'marker-end="url(#arr-{marker_id})"{label_attr}/>'
        )

    # System nodes
    for s in sys_layouts:
        name = s["node"]["name"]
        display = name[:16] + ".." if len(name) > 16 else name
        parts.append(
            f'<rect x="{s["x"]}" y="{s["y"]}" width="{s["w"]}" height="{s["h"]}" '
            f'rx="14" fill="rgba(248,81,73,0.08)" stroke="#f85149" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{s["x"] + s["w"] / 2:.1f}" y="{s["y"] + s["h"] / 2 + 1:.1f}" '
            f'text-anchor="middle" dominant-baseline="central" '
            f'fill="#f85149" font-size="9" font-family="monospace">'
            f"{html_lib.escape(display)}</text>"
        )

    # Module boxes
    for ml in mod_layouts:
        color = ml["color"]
        fill = hex_to_rgba(color, 0.06)
        parts.append(
            f'<rect x="{ml["x"]}" y="{ml["y"]}" width="{ml["w"]}" height="{ml["h"]}" '
            f'rx="6" fill="{fill}" stroke="{color}" stroke-width="1.5" stroke-dasharray="4,3"/>'
        )
        parts.append(
            f'<text x="{ml["x"] + MOD_PAD}" y="{ml["y"] + 18}" '
            f'fill="{color}" font-size="11" font-weight="600" font-family="monospace">'
            f"{html_lib.escape(ml['label'])}</text>"
        )
        count_label = (
            f"{ml['count']} components"
            if ml["count"] > 0
            else f"{ml['file_count']} files"
            if ml["file_count"] > 0
            else ""
        )
        if count_label:
            parts.append(
                f'<text x="{ml["x"] + MOD_PAD}" y="{ml["y"] + ml["h"] / 2 + 8:.1f}" '
                f'fill="#8b949e" font-size="9" font-family="monospace">'
                f"{count_label}</text>"
            )

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML sections
# ---------------------------------------------------------------------------


def e(text) -> str:
    return html_lib.escape(str(text or ""))


def build_html(meta: dict, nodes: list[dict], edges: list[dict], svg: str) -> str:
    repo = meta.get("repo_name", "Unknown Project")
    lang = meta.get("repo_language", "")
    total_files = meta.get("total_files", "?")
    overview = meta.get("architecture_overview", "")
    scanned_by = meta.get("scanned_by", "")
    scanned_at = meta.get("scanned_at", "")[:10] if meta.get("scanned_at") else ""

    node_map = {n["id"]: n for n in nodes}
    modules = sorted(
        [n for n in nodes if n["type"] == "module" and n["properties"].get("flow_rank", 99) < 99],
        key=lambda m: (m["properties"].get("flow_rank", 99), m["properties"].get("flow_col", 99)),
    )
    decisions = [n for n in nodes if n["type"] == "decision"]
    invariants = [n for n in nodes if n["type"] == "invariant"]
    flows = [n for n in nodes if n["type"] == "flow"]

    contains = [e for e in edges if e["type"] == "contains"]
    mod_children: dict[str, list[str]] = defaultdict(list)
    for edge in contains:
        if edge["from_id"] in node_map and node_map[edge["from_id"]]["type"] == "module":
            mod_children[edge["from_id"]].append(edge["to_id"])

    dep_edges = [e for e in edges if e["type"] not in ("contains", "constrains")]

    # ---- Modules table ----
    rows_html = []
    for m in modules:
        child_ids = mod_children.get(m["id"], [])
        comps = [
            node_map[c] for c in child_ids if c in node_map and node_map[c]["type"] == "component"
        ]
        risk = m.get("risk_level", "low")
        risk_badge = f'<span class="badge badge-{risk}">{risk}</span>'
        rows_html.append(
            f"<tr>"
            f"<td><code>{e(m['name'])}</code></td>"
            f"<td>{e(m['description'])}</td>"
            f"<td>{len(comps)}</td>"
            f"<td>{risk_badge}</td>"
            f"</tr>"
        )

    modules_table = f"""
<table>
  <thead><tr><th>Module</th><th>Purpose</th><th>Components</th><th>Risk</th></tr></thead>
  <tbody>{"".join(rows_html)}</tbody>
</table>"""

    # ---- Module detail sections ----
    mod_details = []
    for m in modules:
        child_ids = mod_children.get(m["id"], [])
        comps = [
            node_map[c] for c in child_ids if c in node_map and node_map[c]["type"] == "component"
        ]
        files = [node_map[c] for c in child_ids if c in node_map and node_map[c]["type"] == "file"]
        out_edges = [
            ed
            for ed in dep_edges
            if ed["from_id"] == m["id"]
            or any(node_map.get(ed["from_id"], {}).get("id") == cid for cid in child_ids)
        ]
        in_edges = [ed for ed in dep_edges if ed["to_id"] == m["id"]]
        label = m["name"].replace("src/", "").rstrip("/")
        risk = m.get("risk_level", "low")

        comp_items = "".join(
            f'<li><span class="risk-dot" style="background:{RISK_COLORS.get(c.get("risk_level", "low"), DEFAULT_COLOR)}"></span>'
            f"<strong>{e(c['name'])}</strong>"
            f"{' -- ' + e(c['description'][:120]) + ('...' if len(c.get('description', '')) > 120 else '') if c.get('description') else ''}"
            f"</li>"
            for c in sorted(
                comps,
                key=lambda c: (
                    c["properties"].get("flow_rank", 0),
                    c["properties"].get("flow_col", 0),
                ),
            )
        )

        file_item_parts = []
        for fi in sorted(files, key=lambda x: x.get("name", "")):
            fname = e(fi.get("name", ""))
            fpath = (
                f'<span class="file-path">{e(fi["file_path"])}</span>'
                if fi.get("file_path")
                else ""
            )
            flines = (
                f'<span class="file-lines">{fi["line_count"]} lines</span>'
                if fi.get("line_count")
                else ""
            )
            fdesc = fi.get("description", "")
            fdesc_html = (
                f'<div class="file-desc">{e(fdesc[:150])}{"..." if len(fdesc) > 150 else ""}</div>'
                if fdesc
                else ""
            )
            file_item_parts.append(
                f'<li><div class="file-header"><code>{fname}</code>{fpath}{flines}</div>{fdesc_html}</li>'
            )
        file_items = "".join(file_item_parts)

        out_dep_items = ""
        for ed in dep_edges:
            if ed["from_id"] == m["id"]:
                target = node_map.get(ed["to_id"], {})
                tname = target.get("name", ed["to_id"]).replace("src/", "").rstrip("/")
                lbl = f" -- {e(ed['label'])}" if ed.get("label") else ""
                out_dep_items += f'<li><span class="edge-type edge-{e(ed["type"])}">{e(ed["type"])}</span> {e(tname)}{lbl}</li>'

        in_dep_items = ""
        for ed in dep_edges:
            if ed["to_id"] == m["id"]:
                src = node_map.get(ed["from_id"], {})
                sname = src.get("name", ed["from_id"]).replace("src/", "").rstrip("/")
                lbl = f" -- {e(ed['label'])}" if ed.get("label") else ""
                in_dep_items += f'<li><span class="edge-type edge-{e(ed["type"])}">{e(ed["type"])}</span> {e(sname)}{lbl}</li>'

        mod_details.append(f"""
<details class="mod-detail">
  <summary>
    <span class="mod-name" style="color:{_module_color(m["id"])}">{e(label)}</span>
    <span class="badge badge-{risk}">{risk}</span>
    <span class="comp-count">{len(comps)} components &bull; {len(files)} files</span>
  </summary>
  <div class="mod-body">
    <p class="mod-desc">{e(m.get("description", ""))}</p>
    {f'<div class="section-label">Components</div><ul class="comp-list">{comp_items}</ul>' if comps else ""}
    {f'<div class="section-label">Files</div><ul class="file-list">{file_items}</ul>' if files else ""}
    {f'<div class="section-label">Depends on</div><ul class="dep-list">{out_dep_items}</ul>' if out_dep_items else ""}
    {f'<div class="section-label">Used by</div><ul class="dep-list">{in_dep_items}</ul>' if in_dep_items else ""}
  </div>
</details>""")

    # ---- Decisions ----
    decision_items = "".join(
        f'<div class="card card-decision">'
        f'<div class="card-title">{e(d["name"])}</div>'
        f'<div class="card-body">{e(d["description"])}</div>'
        f"</div>"
        for d in decisions
    )

    # ---- Invariants ----
    inv_items = "".join(
        f'<div class="card card-inv-{inv.get("risk_level", "low")}">'
        f'<div class="card-title">'
        f'<span class="badge badge-{inv.get("risk_level", "low")}">{inv.get("risk_level", "low")}</span> '
        f"{e(inv['name'])}</div>"
        f'<div class="card-body">{e(inv["description"])}</div>'
        f"</div>"
        for inv in invariants
    )

    # ---- Flows ----
    flow_items = "".join(
        f'<details class="flow-detail">'
        f"<summary>{e(fl['name'])}</summary>"
        f'<p class="flow-body">{e(fl["description"])}</p>'
        f"</details>"
        for fl in flows
    )

    meta_line = " &bull; ".join(
        filter(
            None,
            [
                e(lang),
                f"{e(total_files)} files",
                f"Scanned by {e(scanned_by)}" if scanned_by else "",
                f"on {e(scanned_at)}" if scanned_at else "",
            ],
        )
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{e(repo)} -- Architecture</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --fg: #e6edf3; --fg2: #8b949e; --fg3: #6e7681;
    --accent: #58a6ff; --red: #f85149; --green: #3fb950; --yellow: #d29922;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--fg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 14px; line-height: 1.6; padding: 0 0 60px; }}
  a {{ color: var(--accent); }}

  /* Header */
  .site-header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
  .site-title {{ font-size: 20px; font-weight: 700; color: var(--fg); }}
  .site-meta {{ font-size: 12px; color: var(--fg2); }}

  /* Nav tabs */
  .nav {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 40px; display: flex; gap: 0; }}
  .nav a {{ display: block; padding: 10px 18px; color: var(--fg2); text-decoration: none; font-size: 13px; border-bottom: 2px solid transparent; }}
  .nav a:hover {{ color: var(--fg); border-color: var(--border); }}

  /* Main layout */
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 40px; }}
  section {{ margin-bottom: 48px; }}
  h2 {{ font-size: 16px; font-weight: 600; color: var(--fg); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px; }}

  /* Overview */
  .overview-text {{ color: var(--fg2); font-size: 13px; white-space: pre-wrap; word-break: break-word; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 16px; max-height: 300px; overflow-y: auto; }}

  /* Diagram */
  .diagram-wrap {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: auto; padding: 16px; }}

  /* Edge legend */
  .legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--fg2); }}
  .legend-line {{ width: 24px; height: 2px; border-top: 2px dashed; }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 8px 12px; border-bottom: 2px solid var(--border); color: var(--fg2); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  tr:hover td {{ background: rgba(255,255,255,0.02); }}
  code {{ background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 4px; font-family: monospace; font-size: 12px; }}

  /* Badges */
  .badge {{ display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .badge-high {{ background: rgba(248,81,73,.15); color: #f85149; }}
  .badge-medium {{ background: rgba(210,153,34,.15); color: #d29922; }}
  .badge-low {{ background: rgba(63,185,80,.15); color: #3fb950; }}

  /* Module details */
  .mod-detail {{ border: 1px solid var(--border); border-radius: 6px; margin-bottom: 8px; overflow: hidden; }}
  .mod-detail summary {{ padding: 10px 16px; cursor: pointer; display: flex; align-items: center; gap: 10px; background: var(--surface); list-style: none; user-select: none; }}
  .mod-detail summary:hover {{ background: rgba(255,255,255,0.03); }}
  .mod-detail summary::-webkit-details-marker {{ display: none; }}
  .mod-detail[open] summary {{ border-bottom: 1px solid var(--border); }}
  .mod-name {{ font-weight: 600; font-family: monospace; font-size: 13px; }}
  .comp-count {{ margin-left: auto; font-size: 12px; color: var(--fg3); }}
  .mod-body {{ padding: 16px; }}
  .mod-desc {{ color: var(--fg2); font-size: 13px; margin-bottom: 12px; }}
  .section-label {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--fg3); margin: 12px 0 6px; }}
  .comp-list, .dep-list, .file-list {{ list-style: none; display: flex; flex-direction: column; gap: 4px; }}
  .comp-list li {{ font-size: 12px; color: var(--fg2); display: flex; align-items: baseline; gap: 6px; }}
  .dep-list li {{ font-size: 12px; color: var(--fg2); display: flex; align-items: baseline; gap: 6px; }}
  .file-list li {{ font-size: 12px; color: var(--fg2); display: flex; flex-direction: column; gap: 2px; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }}
  .file-list li:last-child {{ border-bottom: none; }}
  .file-header {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
  .file-path {{ color: var(--fg3); font-size: 11px; }}
  .file-lines {{ color: var(--fg3); font-size: 11px; margin-left: auto; }}
  .file-desc {{ font-size: 11px; color: var(--fg3); padding-left: 4px; line-height: 1.5; }}
  .risk-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; display: inline-block; margin-top: 2px; }}

  /* Edge type badges */
  .edge-type {{ display: inline-block; padding: 0 5px; border-radius: 3px; font-size: 10px; font-weight: 600; background: rgba(255,255,255,0.07); color: var(--fg2); flex-shrink: 0; }}

  /* Cards (decisions/invariants) */
  .cards {{ display: flex; flex-direction: column; gap: 10px; }}
  .card {{ border-radius: 6px; padding: 14px 16px; border-left: 3px solid; }}
  .card-decision {{ background: rgba(88,166,255,.05); border-color: #58a6ff; }}
  .card-inv-high {{ background: rgba(248,81,73,.05); border-color: #f85149; }}
  .card-inv-medium {{ background: rgba(210,153,34,.05); border-color: #d29922; }}
  .card-inv-low {{ background: rgba(63,185,80,.05); border-color: #3fb950; }}
  .card-title {{ font-weight: 600; font-size: 13px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }}
  .card-body {{ font-size: 12px; color: var(--fg2); line-height: 1.6; }}

  /* Flows */
  .flow-detail {{ border: 1px solid var(--border); border-radius: 6px; margin-bottom: 6px; overflow: hidden; }}
  .flow-detail summary {{ padding: 8px 14px; cursor: pointer; font-size: 13px; font-weight: 500; background: var(--surface); list-style: none; }}
  .flow-detail summary:hover {{ background: rgba(255,255,255,0.03); }}
  .flow-detail summary::-webkit-details-marker {{ display: none; }}
  .flow-detail[open] summary {{ border-bottom: 1px solid var(--border); }}
  .flow-body {{ padding: 12px 14px; font-size: 12px; color: var(--fg2); white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>

<div class="site-header">
  <div class="site-title">{e(repo)}</div>
  <div class="site-meta">{meta_line}</div>
</div>

<nav class="nav">
  <a href="#overview">Overview</a>
  <a href="#diagram">Diagram</a>
  <a href="#modules">Modules</a>
  <a href="#decisions">Decisions</a>
  <a href="#invariants">Invariants</a>
  <a href="#flows">Flows</a>
</nav>

<div class="container">

  <section id="overview">
    <h2>Architecture Overview</h2>
    <div class="overview-text">{e(overview)}</div>
  </section>

  <section id="diagram">
    <h2>Module Dependency Diagram</h2>
    <div class="diagram-wrap">
      {svg}
    </div>
    <div class="legend">
      {"".join(f'<div class="legend-item"><div class="legend-line" style="border-color:{color}"></div>{etype}</div>' for etype, color in EDGE_COLORS.items())}
    </div>
  </section>

  <section id="modules">
    <h2>Modules ({len(modules)})</h2>
    {modules_table}
    <div style="margin-top:24px;">{"".join(mod_details)}</div>
  </section>

  <section id="decisions">
    <h2>Key Decisions ({len(decisions)})</h2>
    <div class="cards">{decision_items}</div>
  </section>

  <section id="invariants">
    <h2>Invariants ({len(invariants)})</h2>
    <div class="cards">{inv_items}</div>
  </section>

  <section id="flows">
    <h2>Flows ({len(flows)})</h2>
    {"".join(flow_items)}
  </section>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate(
    jsonl_path: str = ".claraity/claraity_knowledge.jsonl",
    out_path: str = ".claraity/ARCHITECTURE.html",
) -> str:
    meta, nodes, edges = load_jsonl(jsonl_path)
    mod_layouts, sys_layouts, vis_edges, pos_map, total_h = calculate_layout(nodes, edges)
    svg = build_svg(mod_layouts, sys_layouts, vis_edges, pos_map, total_h)
    html = build_html(meta, nodes, edges, svg)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate ARCHITECTURE.html from claraity_knowledge.jsonl"
    )
    parser.add_argument("--jsonl", default=".claraity/claraity_knowledge.jsonl")
    parser.add_argument("--out", default=".claraity/ARCHITECTURE.html")
    args = parser.parse_args()
    out = generate(args.jsonl, args.out)
    print(f"[OK] Written: {out}")
