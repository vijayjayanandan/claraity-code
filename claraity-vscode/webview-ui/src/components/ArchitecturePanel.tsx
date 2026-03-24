/**
 * Architecture panel — D3.js grouped architecture diagram.
 *
 * Progressive disclosure:
 *   L1 — All modules collapsed, edges hidden. Overview of the system.
 *   L2 — Expand a module to see its components. Hover to see edges.
 *   L3 — Click a component to see detail drawer (files, relationships).
 */
import { memo, useRef, useEffect, useCallback, useState, type MouseEvent as ReactMouseEvent } from "react";
import * as d3 from "d3";
import type { ArchitectureResponse, ArchitectureNode, ArchitectureEdge } from "../types";

interface ArchitecturePanelProps {
  data: ArchitectureResponse | null;
  onBack: () => void;
  onRefresh: () => void;
  onDiscuss: (message: string) => void;
  onReview: (reviewedBy: string, status: string, comments: string) => void;
  onOpenFile: (path: string) => void;
}

// ============================================================================
// Config
// ============================================================================

const MODULE_COLORS: Record<string, string> = {
  "mod-core": "#58a6ff", "mod-memory": "#3fb950", "mod-session": "#3fb950",
  "mod-ui": "#bc8cff", "mod-tools": "#79c0ff", "mod-llm": "#d29922",
  "mod-server": "#f778ba", "mod-observability": "#8b949e", "mod-prompts": "#8b949e",
  "mod-subagents": "#79c0ff", "mod-director": "#f778ba", "mod-code-intel": "#8b949e",
  "mod-integrations": "#8b949e", "mod-platform": "#8b949e", "mod-hooks": "#8b949e",
};
const EDGE_COLORS: Record<string, string> = {
  uses: "#58a6ff", calls: "#3fb950", writes: "#f85149", reads: "#79c0ff",
  spawns: "#bc8cff", drives: "#f778ba", renders: "#3fb950", dispatches: "#79c0ff",
  controls: "#d29922", configures: "#d29922", bridges: "#f778ba", wraps: "#8b949e",
  interacts: "#f778ba", communicates: "#f778ba", connects: "#8b949e",
  fetches: "#79c0ff", queries: "#79c0ff", reads_writes: "#d29922",
};
const RISK_COLORS: Record<string, string> = { high: "#f85149", medium: "#d29922", low: "#3fb950" };
// Change #5: Single column layout — component width fills sidebar better
const COMP_W = 130, COMP_H = 34, COMP_PAD = 10, MOD_PAD_TOP = 30, MOD_PAD = 12;
const COLLAPSED_W = 150, COLLAPSED_H = 44;
const ROW_GAP = 28, COL_GAP = 20;
const DEFAULT_COLOR = "#8b949e";

// ============================================================================
// Helpers
// ============================================================================

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function curvedPath(from: PosInfo, to: PosInfo): string {
  const dx = to.x - from.x, dy = to.y - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist === 0) return `M${from.x},${from.y}L${to.x},${to.y}`;

  const ux = dx / dist, uy = dy / dist;
  const ft = Math.min(ux ? Math.abs(from.w / 2 / ux) : 1e9, uy ? Math.abs(from.h / 2 / uy) : 1e9);
  const tt = Math.min(ux ? Math.abs(to.w / 2 / ux) : 1e9, uy ? Math.abs(to.h / 2 / uy) : 1e9);
  const x1 = from.x + ux * ft, y1 = from.y + uy * ft;
  const x2 = to.x - ux * (tt + 8), y2 = to.y - uy * (tt + 8);

  const midX = (x1 + x2) / 2, midY = (y1 + y2) / 2;
  const curv = Math.min(dist * 0.2, 60);
  const cx1 = midX - uy * curv, cy1 = midY + ux * curv;

  return `M${x1},${y1} Q${cx1},${cy1} ${x2},${y2}`;
}

// ============================================================================
// Types
// ============================================================================

interface PosInfo { x: number; y: number; w: number; h: number }

interface ChildLayout {
  id: string;
  node: Record<string, unknown>;
  relX: number; relY: number;
  x: number; y: number;
  w: number; h: number;
}

interface ModuleLayout {
  id: string;
  node: Record<string, unknown>;
  label: string;
  expanded: boolean;
  w: number; h: number;
  children: ChildLayout[];
  count?: number;
  color: string;
  flow_rank: number; flow_col: number;
  x: number; y: number;
}

interface SysLayout {
  id: string;
  node: Record<string, unknown>;
  x: number; y: number; w: number; h: number;
}

interface VisibleEdge {
  from: string; to: string;
  type: string; label: string | null;
  fromPos: PosInfo; toPos: PosInfo;
}

interface Layout {
  moduleLayouts: ModuleLayout[];
  sysLayouts: SysLayout[];
  visibleEdges: VisibleEdge[];
  posMap: Record<string, PosInfo>;
  nodeMap: Record<string, Record<string, unknown>>;
  childToModule: Record<string, string>;
}

/** Detail info for drawer — works for module, system, and component nodes */
interface NodeDetail {
  id: string;
  name: string;
  nodeType: string;
  description: string;
  riskLevel: string;
  components: Array<{ name: string }>;
  files: Array<{ name: string; path: string; lines: number | null }>;
  outgoing: Array<{ type: string; name: string; label: string | null }>;
  incoming: Array<{ type: string; name: string; label: string | null }>;
}

/** Detail info for a clicked edge */
interface EdgeDetail {
  fromName: string;
  toName: string;
  type: string;
  label: string | null;
}

/** Focus context — what the user is looking at */
type FocusContext =
  | { kind: "overview" }
  | { kind: "node"; detail: NodeDetail }
  | { kind: "edge"; detail: EdgeDetail };

function focusLabel(focus: FocusContext): string {
  switch (focus.kind) {
    case "overview": return "Architecture Overview";
    case "node": return `${focus.detail.name} (${focus.detail.nodeType})`;
    case "edge": return `${focus.detail.fromName} --${focus.detail.type}--> ${focus.detail.toName}`;
  }
}

function focusContextForAgent(focus: FocusContext): string {
  const instruction = "Architecture Discussion: Use claraity_module, claraity_search, claraity_impact, and claraity_brief tools to answer from the knowledge DB. Only read source files if you need implementation details beyond what the knowledge DB provides.";

  switch (focus.kind) {
    case "overview":
      return `${instruction}\nFocused on: Architecture Overview`;
    case "node": {
      const d = focus.detail;
      const lines = [
        `${instruction}`,
        `Focused on: ${d.name} (${d.nodeType}, id: ${d.id})`,
      ];
      if (d.description) lines.push(`Description: ${d.description}`);
      if (d.components.length > 0) lines.push(`Components: ${d.components.map((c) => c.name).join(", ")}`);
      if (d.files.length > 0) lines.push(`Files: ${d.files.map((f) => f.name).join(", ")}`);
      if (d.outgoing.length > 0) {
        lines.push("Outgoing:");
        d.outgoing.forEach((e) => lines.push(`  -> ${e.type} ${e.name}${e.label ? ` ("${e.label}")` : ""}`));
      }
      if (d.incoming.length > 0) {
        lines.push("Incoming:");
        d.incoming.forEach((e) => lines.push(`  <- ${e.type} ${e.name}${e.label ? ` ("${e.label}")` : ""}`));
      }
      return lines.join("\n");
    }
    case "edge": {
      const e = focus.detail;
      return `${instruction}\nFocused on edge: ${e.fromName} --${e.type}--> ${e.toName}${e.label ? `\nDescription: "${e.label}"` : ""}`;
    }
  }
}

// ============================================================================
// Layout calculation
// ============================================================================

function calculateLayout(
  data: ArchitectureResponse,
  expandedModules: Set<string>,
  dragPositions: Record<string, { x: number; y: number }>,
): Layout {
  const nodeMap: Record<string, Record<string, unknown>> = {};
  data.nodes.forEach((n) => { nodeMap[n.id] = n as unknown as Record<string, unknown>; });

  const modules = data.nodes.filter((n) => n.type === "module");
  const systems = data.nodes.filter((n) => n.type === "system");
  const containsEdges = data.edges.filter((e) => e.type === "contains");
  const moduleChildren: Record<string, string[]> = {};
  const childToModule: Record<string, string> = {};
  containsEdges.forEach((e) => {
    if (!moduleChildren[e.from_id]) moduleChildren[e.from_id] = [];
    moduleChildren[e.from_id].push(e.to_id);
    childToModule[e.to_id] = e.from_id;
  });

  const moduleLayouts: ModuleLayout[] = [];
  modules.forEach((mod) => {
    const allChildren = (moduleChildren[mod.id] || []).map((cid) => nodeMap[cid]).filter(Boolean);
    if (allChildren.length === 0) return;

    // Change #2: Only show components in expanded view, not files
    const components = allChildren.filter((c) => (c.type as string) === "component");
    const expanded = expandedModules.has(mod.id);
    const label = mod.name.replace("src/", "").replace(/\/$/, "");
    const props = mod.properties || {};

    if (expanded && components.length > 0) {
      // Change #5: Single column layout for narrow sidebar
      const cols = 1;
      const rows = Math.ceil(components.length / cols);
      const w = cols * (COMP_W + COMP_PAD) + MOD_PAD * 2 - COMP_PAD;
      const h = rows * (COMP_H + COMP_PAD) + MOD_PAD_TOP + MOD_PAD - COMP_PAD;
      const childLayouts: ChildLayout[] = components.map((c, i) => ({
        id: c.id as string, node: c,
        relX: MOD_PAD + (i % cols) * (COMP_W + COMP_PAD),
        relY: MOD_PAD_TOP + Math.floor(i / cols) * (COMP_H + COMP_PAD),
        x: 0, y: 0, w: COMP_W, h: COMP_H,
      }));
      moduleLayouts.push({
        id: mod.id, node: mod as unknown as Record<string, unknown>, label, expanded: true,
        w, h, children: childLayouts, color: MODULE_COLORS[mod.id] || DEFAULT_COLOR,
        flow_rank: (props as Record<string, unknown>).flow_rank as number ?? 99,
        flow_col: (props as Record<string, unknown>).flow_col as number ?? 0,
        x: 0, y: 0,
      });
    } else {
      // Show component count in collapsed view
      const compCount = components.length;
      const fileCount = allChildren.length - compCount;
      moduleLayouts.push({
        id: mod.id, node: mod as unknown as Record<string, unknown>, label, expanded: false,
        w: COLLAPSED_W, h: COLLAPSED_H, children: [],
        count: compCount > 0 ? compCount : fileCount,
        color: MODULE_COLORS[mod.id] || DEFAULT_COLOR,
        flow_rank: (props as Record<string, unknown>).flow_rank as number ?? 99,
        flow_col: (props as Record<string, unknown>).flow_col as number ?? 0,
        x: 0, y: 0,
      });
    }
  });

  // Position by flow_rank/flow_col
  const rows: Record<number, ModuleLayout[]> = {};
  moduleLayouts.forEach((ml) => {
    const r = ml.flow_rank;
    if (!rows[r]) rows[r] = [];
    rows[r].push(ml);
  });

  const sortedRanks = Object.keys(rows).map(Number).sort((a, b) => a - b);
  let cy = 60;
  sortedRanks.forEach((rank) => {
    const row = rows[rank].sort((a, b) => a.flow_col - b.flow_col);
    const totalW = row.reduce((s, ml) => s + ml.w, 0) + (row.length - 1) * COL_GAP;
    let cx = Math.max(20, (800 - totalW) / 2);
    let maxH = 0;

    row.forEach((ml) => {
      if (dragPositions[ml.id]) {
        ml.x = dragPositions[ml.id].x;
        ml.y = dragPositions[ml.id].y;
      } else {
        ml.x = cx;
        ml.y = cy;
      }
      cx += ml.w + COL_GAP;
      maxH = Math.max(maxH, ml.h);
      ml.children.forEach((cl) => {
        cl.x = ml.x + cl.relX;
        cl.y = ml.y + cl.relY;
      });
    });
    cy += maxH + ROW_GAP;
  });

  // System nodes
  const sysSorted = systems.slice().sort((a, b) => {
    const pa = (a.properties || {}) as Record<string, unknown>;
    const pb = (b.properties || {}) as Record<string, unknown>;
    return ((pa.flow_col as number) ?? 99) - ((pb.flow_col as number) ?? 99);
  });
  const totalSysW = sysSorted.length * 120 + (sysSorted.length - 1) * 16;
  const sysStartX = Math.max(20, (800 - totalSysW) / 2);
  const sysLayouts: SysLayout[] = sysSorted.map((s, i) => {
    const pos = dragPositions[s.id];
    return {
      id: s.id, node: s as unknown as Record<string, unknown>,
      x: pos ? pos.x : sysStartX + i * 136,
      y: pos ? pos.y : 10,
      w: 120, h: 28,
    };
  });

  // Position map for edges
  const posMap: Record<string, PosInfo> = {};
  sysLayouts.forEach((s) => { posMap[s.id] = { x: s.x + s.w / 2, y: s.y + s.h / 2, w: s.w, h: s.h }; });
  moduleLayouts.forEach((ml) => {
    posMap[ml.id] = { x: ml.x + ml.w / 2, y: ml.y + ml.h / 2, w: ml.w, h: ml.h };
    ml.children.forEach((cl) => {
      posMap[cl.id] = { x: cl.x + cl.w / 2, y: cl.y + cl.h / 2, w: cl.w, h: cl.h };
    });
  });

  // Build visible edges with dedup
  function visibleId(id: string): string {
    const pm = childToModule[id];
    return (pm && !expandedModules.has(pm)) ? pm : id;
  }
  const EDGE_PRIORITY: Record<string, number> = { writes: 5, calls: 4, drives: 4, spawns: 3, uses: 2, reads: 2 };
  const edgeMap = new Map<string, VisibleEdge>();
  data.edges.filter((e) => e.type !== "contains" && e.type !== "constrains").forEach((e) => {
    const fromNode = nodeMap[e.from_id];
    const toNode = nodeMap[e.to_id];
    const fv = fromNode?.type === "component" ? visibleId(e.from_id) : e.from_id;
    const tv = toNode?.type === "component" ? visibleId(e.to_id) : e.to_id;
    if (fv === tv || !posMap[fv] || !posMap[tv]) return;
    const key = `${fv}:${tv}`;
    const pri = EDGE_PRIORITY[e.type] || 1;
    const ex = edgeMap.get(key);
    if (!ex || pri > (EDGE_PRIORITY[ex.type] || 1)) {
      edgeMap.set(key, { from: fv, to: tv, type: e.type, label: e.label, fromPos: posMap[fv], toPos: posMap[tv] });
    }
  });

  return { moduleLayouts, sysLayouts, visibleEdges: Array.from(edgeMap.values()), posMap, nodeMap, childToModule };
}

// ============================================================================
// Build node detail (works for module, system, and component)
// ============================================================================

function buildNodeDetail(
  nodeId: string,
  data: ArchitectureResponse,
): NodeDetail | null {
  const node = data.nodes.find((n) => n.id === nodeId);
  if (!node) return null;

  const nodeMap = new Map(data.nodes.map((n) => [n.id, n]));

  // Find contained children
  const childIds = data.edges
    .filter((e) => e.type === "contains" && e.from_id === nodeId)
    .map((e) => e.to_id);
  const childNodes = childIds
    .map((cid) => nodeMap.get(cid))
    .filter((n): n is ArchitectureNode => n != null);

  // Components contained by this node (for modules)
  const components = childNodes
    .filter((n) => n.type === "component")
    .map((n) => ({ name: n.name }));

  // Files contained by this node (for components, or files directly in modules)
  const files = childNodes
    .filter((n) => n.type === "file")
    .map((n) => ({
      name: n.name,
      path: n.file_path || "",
      lines: (n as unknown as Record<string, unknown>).line_count as number | null,
    }));

  // Outgoing edges (from this node)
  const outgoing = data.edges
    .filter((e) => e.from_id === nodeId && e.type !== "contains" && e.type !== "constrains")
    .map((e) => ({
      type: e.type,
      name: nodeMap.get(e.to_id)?.name || e.to_id,
      label: e.label,
    }));

  // Incoming edges (to this node)
  const incoming = data.edges
    .filter((e) => e.to_id === nodeId && e.type !== "contains" && e.type !== "constrains")
    .map((e) => ({
      type: e.type,
      name: nodeMap.get(e.from_id)?.name || e.from_id,
      label: e.label,
    }));

  return {
    id: node.id,
    name: node.name,
    nodeType: node.type,
    description: node.description || "",
    riskLevel: (node as unknown as Record<string, unknown>).risk_level as string || "",
    components,
    files,
    outgoing,
    incoming,
  };
}

// ============================================================================
// D3 render function
// ============================================================================

function renderGraph(
  container: HTMLDivElement,
  data: ArchitectureResponse,
  expandedModules: Set<string>,
  dragPositions: Record<string, { x: number; y: number }>,
  onToggleModule: (id: string) => void,
  onSelectNode: (id: string | null) => void,
  onSelectEdge: (edge: VisibleEdge | null) => void,
) {
  d3.select(container).selectAll("*").remove();

  const svgEl = d3.select(container).append("svg")
    .attr("width", "100%").attr("height", "100%")
    .style("background", "transparent");

  const layout = calculateLayout(data, expandedModules, dragPositions);

  // Arrow markers
  const defs = svgEl.append("defs");
  const allEdgeTypes: Record<string, string> = { ...EDGE_COLORS, default: DEFAULT_COLOR };
  Object.entries(allEdgeTypes).forEach(([type, color]) => {
    defs.append("marker").attr("id", `arr-${type}`)
      .attr("viewBox", "0 -4 8 8").attr("refX", 8).attr("refY", 0)
      .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
      .append("path").attr("d", "M0,-4L8,0L0,4Z").attr("fill", color);
  });

  // Zoom
  const g = svgEl.append("g");
  const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.1, 3])
    .on("zoom", (e) => g.attr("transform", e.transform));
  svgEl.call(zoomBehavior);

  // ---- Selection state: click locks edges, click background unlocks ----
  let lockedNodeId: string | null = null;

  function lockNode(nodeId: string) {
    lockedNodeId = nodeId;
    highlightEdges(nodeId);
  }
  function unlockNode() {
    lockedNodeId = null;
    clearHighlight();
    onSelectNode(null);
    onSelectEdge(null);
  }

  // Click background to deselect
  svgEl.on("click", () => unlockNode());

  // ---- Tooltip ----
  const tooltip = d3.select(container).append("div")
    .style("position", "absolute")
    .style("background", "var(--app-surface, #161b22)")
    .style("border", "1px solid var(--app-border, #30363d)")
    .style("border-radius", "6px")
    .style("padding", "6px 10px")
    .style("font-size", "11px")
    .style("pointer-events", "none")
    .style("opacity", "0")
    .style("max-width", "250px")
    .style("z-index", "100")
    .style("color", "var(--app-fg, #e6edf3)");

  function showTooltip(event: MouseEvent, node: Record<string, unknown>) {
    const name = node.name as string || "";
    const desc = node.description as string || "";
    tooltip.html(`<strong>${name}</strong>${desc ? `<br/><span style="opacity:.7">${desc}</span>` : ""}`)
      .style("opacity", "1");
    moveTooltip(event);
  }
  function moveTooltip(event: MouseEvent) {
    const r = container.getBoundingClientRect();
    tooltip.style("left", `${event.clientX - r.left + 12}px`)
      .style("top", `${event.clientY - r.top - 8}px`);
  }
  function hideTooltip() { tooltip.style("opacity", "0"); }

  // ---- Edge highlighting ----
  // Default: low opacity so structure is visible. Hover/click: bright + animated.
  const EDGE_OPACITY_DEFAULT = 0.15;
  const EDGE_OPACITY_DIMMED = 0.04;
  const EDGE_OPACITY_HIGHLIGHT = 0.9;

  function highlightEdges(nodeId: string) {
    g.selectAll<SVGPathElement, VisibleEdge>(".edge-path").each(function () {
      const e = d3.select<SVGPathElement, VisibleEdge>(this).datum();
      const connected = e && (e.from === nodeId || e.to === nodeId);
      d3.select(this)
        .attr("stroke-opacity", connected ? EDGE_OPACITY_HIGHLIGHT : EDGE_OPACITY_DIMMED)
        .attr("stroke-width", connected ? 2.2 : 1.3);
      if (connected) {
        d3.select(this).attr("stroke-dasharray", "8 4")
          .style("animation", "arch-dash-flow 0.7s linear infinite");
      } else {
        d3.select(this).style("animation", null);
      }
    });
  }
  function clearHighlight() {
    g.selectAll<SVGPathElement, VisibleEdge>(".edge-path")
      .attr("stroke-opacity", EDGE_OPACITY_DEFAULT)
      .attr("stroke-width", 1.3)
      .style("animation", null);
  }

  // ---- Edges (hidden by default) ----
  const edgeGroup = g.append("g");
  interface EdgeEl {
    path: d3.Selection<SVGPathElement, VisibleEdge, null, undefined>;
    hitArea: d3.Selection<SVGPathElement, VisibleEdge, null, undefined>;
    data: VisibleEdge;
  }
  const edgeEls: EdgeEl[] = [];

  layout.visibleEdges.forEach((e) => {
    const color = EDGE_COLORS[e.type] || DEFAULT_COLOR;
    const mid = EDGE_COLORS[e.type] ? `arr-${e.type}` : "arr-default";

    const path = edgeGroup.append("path")
      .attr("class", "edge-path")
      .attr("d", curvedPath(e.fromPos, e.toPos))
      .attr("stroke", color)
      .attr("fill", "none")
      .attr("stroke-width", 1.3)
      .attr("stroke-opacity", EDGE_OPACITY_DEFAULT)
      .attr("stroke-dasharray", "6 4")
      .attr("marker-end", `url(#${mid})`)
      .datum(e);

    // Invisible wider hit area for clicking thin edges
    const hitArea = edgeGroup.append("path")
      .attr("d", curvedPath(e.fromPos, e.toPos))
      .attr("stroke", "transparent")
      .attr("fill", "none")
      .attr("stroke-width", 12)
      .style("cursor", "pointer")
      .datum(e)
      .on("click", (ev: MouseEvent) => {
        ev.stopPropagation();
        lockedNodeId = null;
        // Dim all edges, then highlight just this one
        clearHighlight();
        path.attr("stroke-opacity", EDGE_OPACITY_HIGHLIGHT)
          .attr("stroke-width", 2.5)
          .attr("stroke-dasharray", "8 4")
          .style("animation", "arch-dash-flow 0.7s linear infinite");
        lockedNodeId = "__edge__";  // prevent hover from clearing
        onSelectEdge(e);
        onSelectNode(null);
      })
      .on("mouseover", () => {
        if (!lockedNodeId) {
          path.attr("stroke-opacity", EDGE_OPACITY_HIGHLIGHT)
            .attr("stroke-width", 2.2)
            .style("animation", "arch-dash-flow 0.7s linear infinite");
        }
      })
      .on("mouseout", () => {
        if (!lockedNodeId) {
          path.attr("stroke-opacity", EDGE_OPACITY_DEFAULT)
            .attr("stroke-width", 1.3)
            .style("animation", null);
        }
      });

    edgeEls.push({ path, hitArea, data: e });
  });

  // ---- System nodes ----
  layout.sysLayouts.forEach((s) => {
    const sg = g.append("g")
      .attr("transform", `translate(${s.x},${s.y})`)
      .style("cursor", "grab");
    sg.append("rect").attr("width", s.w).attr("height", s.h)
      .attr("rx", 14).attr("ry", 14)
      .attr("fill", "rgba(248,81,73,0.08)").attr("stroke", "#f85149").attr("stroke-width", 1);
    const sName = (s.node.name as string) || "";
    sg.append("text").attr("x", s.w / 2).attr("y", s.h / 2 + 1)
      .attr("text-anchor", "middle").attr("dominant-baseline", "central")
      .attr("fill", "#f85149").attr("font-size", "9px")
      .text(sName.length > 16 ? sName.substring(0, 14) + ".." : sName);

    sg.on("mouseover", (ev: MouseEvent) => { showTooltip(ev, s.node); if (!lockedNodeId) highlightEdges(s.id); })
      .on("mousemove", (ev: MouseEvent) => moveTooltip(ev))
      .on("mouseout", () => { hideTooltip(); if (!lockedNodeId) clearHighlight(); })
      .on("click", (ev: MouseEvent) => { ev.stopPropagation(); lockNode(s.id); onSelectNode(s.id); onSelectEdge(null); });

    sg.call(d3.drag<SVGGElement, unknown>()
      .on("start", function () { d3.select(this).raise(); })
      .on("drag", function (event) {
        const nx = (dragPositions[s.id]?.x ?? s.x) + event.dx;
        const ny = (dragPositions[s.id]?.y ?? s.y) + event.dy;
        dragPositions[s.id] = { x: nx, y: ny };
        d3.select(this).attr("transform", `translate(${nx},${ny})`);
        layout.posMap[s.id] = { x: nx + s.w / 2, y: ny + s.h / 2, w: s.w, h: s.h };
        edgeEls.forEach((el) => {
          const fp = layout.posMap[el.data.from], tp = layout.posMap[el.data.to];
          if (fp && tp) { el.data.fromPos = fp; el.data.toPos = tp; const d = curvedPath(fp, tp); el.path.attr("d", d); el.hitArea.attr("d", d); }
        });
      })
    );
  });

  // ---- Module groups ----
  layout.moduleLayouts.forEach((ml) => {
    const mg = g.append("g")
      .attr("transform", `translate(${ml.x},${ml.y})`)
      .style("cursor", "grab");

    mg.append("rect")
      .attr("width", ml.w).attr("height", ml.h)
      .attr("rx", 6).attr("ry", 6)
      .attr("fill", hexToRgba(ml.color, 0.06))
      .attr("stroke", ml.color).attr("stroke-width", 1.5)
      .attr("stroke-dasharray", ml.expanded ? "none" : "4,3");

    mg.append("text")
      .attr("x", MOD_PAD).attr("y", ml.expanded ? 18 : ml.h / 2 - 5)
      .attr("fill", ml.color).attr("font-size", "11px").attr("font-weight", "600")
      .style("pointer-events", "none")
      .text(ml.label);

    // Expand/collapse button
    const btnG = mg.append("g").style("cursor", "pointer");
    if (ml.expanded) {
      btnG.append("rect").attr("x", ml.w - 32).attr("y", 4).attr("width", 24).attr("height", 16)
        .attr("rx", 3).attr("fill", "rgba(255,255,255,0.06)").attr("stroke", "rgba(255,255,255,0.15)");
      btnG.append("text").attr("x", ml.w - 20).attr("y", 15).attr("text-anchor", "middle")
        .attr("font-size", "9px").attr("fill", "#8b949e").text("[-]");
    } else {
      mg.append("text")
        .attr("x", MOD_PAD).attr("y", ml.h / 2 + 9)
        .attr("fill", "#8b949e").attr("font-size", "9px")
        .style("pointer-events", "none")
        .text(`${ml.count} components`);
      btnG.append("rect").attr("x", ml.w - 32).attr("y", ml.h / 2 - 8).attr("width", 24).attr("height", 16)
        .attr("rx", 3).attr("fill", "rgba(255,255,255,0.06)").attr("stroke", "rgba(255,255,255,0.15)");
      btnG.append("text").attr("x", ml.w - 20).attr("y", ml.h / 2 + 4).attr("text-anchor", "middle")
        .attr("font-size", "9px").attr("fill", "#8b949e").text("[+]");
    }

    btnG.on("click", (ev: MouseEvent) => {
      ev.stopPropagation();
      onToggleModule(ml.id);
    });

    mg.on("mouseover", (ev: MouseEvent) => { showTooltip(ev, ml.node); if (!lockedNodeId) highlightEdges(ml.id); })
      .on("mousemove", (ev: MouseEvent) => moveTooltip(ev))
      .on("mouseout", () => { hideTooltip(); if (!lockedNodeId) clearHighlight(); })
      .on("click", (ev: MouseEvent) => { ev.stopPropagation(); lockNode(ml.id); onSelectNode(ml.id); onSelectEdge(null); });

    // Component nodes inside expanded modules
    const compGroups: Array<{ el: d3.Selection<SVGGElement, unknown, null, undefined>; relX: number; relY: number }> = [];
    ml.children.forEach((cl) => {
      const rc = RISK_COLORS[(cl.node.risk_level as string)] || RISK_COLORS.low;
      const isHigh = (cl.node.risk_level as string) === "high";
      const cg = g.append("g")
        .attr("transform", `translate(${cl.x},${cl.y})`)
        .style("cursor", "pointer");

      cg.append("rect").attr("width", cl.w).attr("height", cl.h)
        .attr("rx", 3).attr("ry", 3)
        .attr("fill", hexToRgba(rc, 0.08)).attr("stroke", rc).attr("stroke-width", isHigh ? 2 : 1);
      const nm = (cl.node.name as string) || "";
      cg.append("text").attr("x", cl.w / 2).attr("y", cl.h / 2 + 1)
        .attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("fill", "var(--app-fg, #e6edf3)").attr("font-size", "9px")
        .text(nm.length > 15 ? nm.substring(0, 13) + ".." : nm);

      cg.on("click", (ev: MouseEvent) => {
        ev.stopPropagation();
        lockNode(cl.id);
        onSelectNode(cl.id); onSelectEdge(null);
      });
      cg.on("mouseover", (ev: MouseEvent) => { showTooltip(ev, cl.node); if (!lockedNodeId) highlightEdges(cl.id); })
        .on("mousemove", (ev: MouseEvent) => moveTooltip(ev))
        .on("mouseout", () => { hideTooltip(); if (!lockedNodeId) clearHighlight(); });

      compGroups.push({ el: cg, relX: cl.relX, relY: cl.relY });
    });

    // Drag module (children follow) — filter out clicks on expand button
    const btnNode = btnG.node();
    mg.call(d3.drag<SVGGElement, unknown>()
      .filter((event: MouseEvent) => {
        let el = event.target as Element | null;
        while (el && el !== mg.node()) {
          if (el === btnNode) return false;
          el = el.parentElement;
        }
        return true;
      })
      .on("start", function () {
        d3.select(this).raise().style("cursor", "grabbing");
        compGroups.forEach((c) => c.el.raise());
      })
      .on("drag", function (event) {
        const nx = (dragPositions[ml.id]?.x ?? ml.x) + event.dx;
        const ny = (dragPositions[ml.id]?.y ?? ml.y) + event.dy;
        dragPositions[ml.id] = { x: nx, y: ny };
        d3.select(this).attr("transform", `translate(${nx},${ny})`);
        compGroups.forEach((c) => {
          c.el.attr("transform", `translate(${nx + c.relX},${ny + c.relY})`);
        });
        layout.posMap[ml.id] = { x: nx + ml.w / 2, y: ny + ml.h / 2, w: ml.w, h: ml.h };
        ml.children.forEach((cl, i) => {
          layout.posMap[cl.id] = {
            x: nx + compGroups[i].relX + cl.w / 2,
            y: ny + compGroups[i].relY + cl.h / 2,
            w: cl.w, h: cl.h,
          };
        });
        edgeEls.forEach((el) => {
          const fp = layout.posMap[el.data.from], tp = layout.posMap[el.data.to];
          if (fp && tp) { el.data.fromPos = fp; el.data.toPos = tp; const d = curvedPath(fp, tp); el.path.attr("d", d); el.hitArea.attr("d", d); }
        });
      })
      .on("end", function () { d3.select(this).style("cursor", "grab"); })
    );
  });

  // Auto-fit zoom
  setTimeout(() => {
    const bounds = (g.node() as SVGGElement)?.getBBox();
    if (!bounds || bounds.width === 0) return;
    const w = container.clientWidth, h = container.clientHeight;
    const scale = 0.85 / Math.max(bounds.width / w, bounds.height / h);
    const tx = w / 2 - (bounds.x + bounds.width / 2) * scale;
    const ty = h / 2 - (bounds.y + bounds.height / 2) * scale;
    const t = d3.zoomIdentity.translate(tx, ty).scale(Math.min(scale, 1.5));
    svgEl.transition().duration(400).call(zoomBehavior.transform, t);
  }, 50);
}

// ============================================================================
// CSS injection
// ============================================================================

const GRAPH_STYLES = `
@keyframes arch-dash-flow { to { stroke-dashoffset: -20; } }
`;

let stylesInjected = false;
function injectStyles() {
  if (stylesInjected) return;
  const style = document.createElement("style");
  style.textContent = GRAPH_STYLES;
  document.head.appendChild(style);
  stylesInjected = true;
}

// ============================================================================
// L3 Detail Drawer (React component)
// ============================================================================

// ============================================================================
// Overview Drawer (shown by default when no node is selected)
// ============================================================================

function OverviewDrawer({ data }: { data: ArchitectureResponse }) {
  const flows = data.nodes.filter((n) => n.type === "flow");
  const decisions = data.nodes.filter((n) => n.type === "decision");
  const invariants = data.nodes.filter((n) => n.type === "invariant");

  // Split overview into sections by ## headers
  const overviewSections: Array<{ title: string; content: string }> = [];
  if (data.overview) {
    const lines = data.overview.split("\n");
    let currentTitle = "";
    let currentContent: string[] = [];
    for (const line of lines) {
      if (line.startsWith("## ")) {
        if (currentTitle || currentContent.length > 0) {
          overviewSections.push({ title: currentTitle, content: currentContent.join("\n").trim() });
        }
        currentTitle = line.replace("## ", "");
        currentContent = [];
      } else {
        currentContent.push(line);
      }
    }
    if (currentTitle || currentContent.length > 0) {
      overviewSections.push({ title: currentTitle, content: currentContent.join("\n").trim() });
    }
  }

  return (
    <div className="arch-detail-drawer arch-overview-drawer">
      <div className="arch-detail-header">
        <span className="arch-detail-name">Architecture Overview</span>
        <span className="arch-detail-type">system</span>
      </div>

      {overviewSections.map((s, i) => (
        <div key={i} className="arch-overview-section">
          {s.title && <div className="arch-detail-section-title">{s.title}</div>}
          <p className="arch-detail-desc">{s.content}</p>
        </div>
      ))}

      {flows.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Flows ({flows.length})</div>
          {flows.map((f) => (
            <div key={f.id} className="arch-detail-edge-row">
              <div className="arch-detail-edge">
                <span className="arch-overview-flow-name">{f.name}</span>
              </div>
              {f.description && <div className="arch-detail-edge-label">{f.description}</div>}
            </div>
          ))}
        </div>
      )}

      {decisions.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Key Decisions ({decisions.length})</div>
          {decisions.map((d) => (
            <div key={d.id} className="arch-detail-edge-row">
              <div className="arch-detail-edge">
                <span className="arch-overview-decision-name">{d.name}</span>
              </div>
              {d.description && <div className="arch-detail-edge-label">{d.description}</div>}
            </div>
          ))}
        </div>
      )}

      {invariants.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Invariants ({invariants.length})</div>
          {invariants.map((inv) => (
            <div key={inv.id} className="arch-detail-edge-row">
              <div className="arch-detail-edge">
                <span className="arch-overview-invariant-name">{inv.name}</span>
              </div>
              {inv.description && <div className="arch-detail-edge-label">{inv.description}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Node Detail Drawer (shown when a specific node is clicked)
// ============================================================================

function DetailDrawer({ detail, onClose, onOpenFile }: { detail: NodeDetail; onClose: () => void; onOpenFile: (path: string) => void }) {
  return (
    <div className="arch-detail-drawer">
      <div className="arch-detail-header">
        <span className="arch-detail-name">{detail.name}</span>
        <span className="arch-detail-type">{detail.nodeType}</span>
        {detail.riskLevel && (
          <span className={`arch-detail-risk risk-${detail.riskLevel}`}>{detail.riskLevel}</span>
        )}
        <button className="arch-detail-close" onClick={onClose} aria-label="Close detail">
          <i className="codicon codicon-close" />
        </button>
      </div>
      {detail.description && <p className="arch-detail-desc">{detail.description}</p>}

      {detail.components.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Components ({detail.components.length})</div>
          {detail.components.map((c, i) => (
            <div key={i} className="arch-detail-file">
              <i className="codicon codicon-symbol-class" />
              <span>{c.name}</span>
            </div>
          ))}
        </div>
      )}

      {detail.files.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Files ({detail.files.length})</div>
          {detail.files.map((f) => (
            <div
              key={f.path}
              className={`arch-detail-file ${f.path ? "arch-file-link" : ""}`}
              onClick={() => f.path && onOpenFile(f.path)}
              title={f.path || undefined}
            >
              <i className="codicon codicon-file" />
              <span>{f.name}</span>
              {f.lines != null && <span className="arch-detail-lines">{f.lines} lines</span>}
            </div>
          ))}
        </div>
      )}

      {detail.outgoing.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Outgoing ({detail.outgoing.length})</div>
          {detail.outgoing.map((d, i) => (
            <div key={i} className="arch-detail-edge-row">
              <div className="arch-detail-edge">
                <span className="arch-detail-arrow">-&gt;</span>
                <span className="arch-detail-edge-type">{d.type}</span>
                <span>{d.name}</span>
              </div>
              {d.label && <div className="arch-detail-edge-label">{d.label}</div>}
            </div>
          ))}
        </div>
      )}

      {detail.incoming.length > 0 && (
        <div className="arch-detail-section">
          <div className="arch-detail-section-title">Incoming ({detail.incoming.length})</div>
          {detail.incoming.map((d, i) => (
            <div key={i} className="arch-detail-edge-row">
              <div className="arch-detail-edge">
                <span className="arch-detail-arrow">&lt;-</span>
                <span className="arch-detail-edge-type">{d.type}</span>
                <span>{d.name}</span>
              </div>
              {d.label && <div className="arch-detail-edge-label">{d.label}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Edge Detail Drawer
// ============================================================================

function EdgeDrawer({ detail, onClose }: { detail: EdgeDetail; onClose: () => void }) {
  return (
    <div className="arch-detail-drawer">
      <div className="arch-detail-header">
        <span className="arch-detail-name">{detail.fromName} → {detail.toName}</span>
        <span className="arch-detail-type">edge</span>
        <button className="arch-detail-close" onClick={onClose} aria-label="Close detail">
          <i className="codicon codicon-close" />
        </button>
      </div>
      <div className="arch-detail-section">
        <div className="arch-detail-edge-row">
          <div className="arch-detail-edge">
            <span className="arch-detail-edge-type">{detail.type}</span>
          </div>
          {detail.label && <div className="arch-detail-edge-label">{detail.label}</div>}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// React component
// ============================================================================

export const ArchitecturePanel = memo(function ArchitecturePanel({ data, onBack, onRefresh, onDiscuss, onReview, onOpenFile }: ArchitecturePanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const expandedRef = useRef(new Set<string>());
  const dragPosRef = useRef<Record<string, { x: number; y: number }>>({});
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<EdgeDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [drawerFullscreen, setDrawerFullscreen] = useState(false);
  const [drawerHeight, setDrawerHeight] = useState(200);
  const [textZoom, setTextZoom] = useState(100);
  const [discussInput, setDiscussInput] = useState("");
  const [statsExpanded, setStatsExpanded] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewName, setReviewName] = useState("");
  const [reviewStatus, setReviewStatus] = useState<"approved" | "rejected">("approved");
  const [reviewComments, setReviewComments] = useState("");
  const resizingRef = useRef(false);
  const drawerContentRef = useRef<HTMLDivElement>(null);
  const discussInputRef = useRef<HTMLInputElement>(null);

  // Current focus context
  const focus: FocusContext = selectedEdge
    ? { kind: "edge", detail: selectedEdge }
    : selectedNode
    ? { kind: "node", detail: selectedNode }
    : { kind: "overview" };

  // Drag-to-resize handler
  const handleResizeStart = useCallback((e: ReactMouseEvent) => {
    e.preventDefault();
    resizingRef.current = true;
    const startY = e.clientY;
    const startHeight = drawerHeight;

    const onMouseMove = (ev: globalThis.MouseEvent) => {
      if (!resizingRef.current) return;
      const delta = startY - ev.clientY;
      const newHeight = Math.max(80, Math.min(window.innerHeight - 120, startHeight + delta));
      setDrawerHeight(newHeight);
    };
    const onMouseUp = () => {
      resizingRef.current = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }, [drawerHeight]);

  // Ctrl+scroll text zoom on drawer
  useEffect(() => {
    const el = drawerContentRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setTextZoom((prev) => Math.max(60, Math.min(200, prev + (e.deltaY < 0 ? 10 : -10))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [drawerOpen]);

  // Focus discuss input on mount
  useEffect(() => {
    if (discussInputRef.current) {
      discussInputRef.current.focus();
    }
  }, []);

  // Build EdgeDetail from VisibleEdge using node names from data
  const buildEdgeDetail = useCallback((e: VisibleEdge): EdgeDetail | null => {
    if (!data) return null;
    const nodeMap = new Map(data.nodes.map((n) => [n.id, n]));
    return {
      fromName: nodeMap.get(e.from)?.name || e.from,
      toName: nodeMap.get(e.to)?.name || e.to,
      type: e.type,
      label: e.label,
    };
  }, [data]);

  const doRender = useCallback(() => {
    if (!containerRef.current || !data) return;
    injectStyles();
    renderGraph(
      containerRef.current, data, expandedRef.current, dragPosRef.current,
      (id) => {
        if (expandedRef.current.has(id)) expandedRef.current.delete(id);
        else expandedRef.current.add(id);
        delete dragPosRef.current[id];
        doRender();
      },
      (id) => {
        if (id && data) {
          setSelectedNode(buildNodeDetail(id, data));
          setSelectedEdge(null);  // clear edge only when selecting a node
        } else {
          setSelectedNode(null);
        }
      },
      (edge) => {
        if (edge) {
          setSelectedEdge(buildEdgeDetail(edge));
          setSelectedNode(null);
        } else {
          setSelectedEdge(null);
        }
      },
    );
  }, [data, buildEdgeDetail]);

  useEffect(() => {
    doRender();
  }, [doRender]);

  const handleDiscussSubmit = () => {
    const q = discussInput.trim();
    if (!q) return;
    const context = focusContextForAgent(focus);
    onDiscuss(JSON.stringify({ question: q, context }));
    setDiscussInput("");
  };

  return (
    <div className="arch-panel">
      <div className="panel-header">
        <button className="panel-back" onClick={onBack} title="Back to chat" aria-label="Back to chat">
          <i className="codicon codicon-arrow-left" />
        </button>
        <span className="panel-title">Architecture</span>
        <button className="panel-action" onClick={() => {
          expandedRef.current = new Set<string>();
          dragPosRef.current = {};
          setSelectedNode(null);
          setSelectedEdge(null);
          doRender();
        }} title="Reset layout" aria-label="Reset layout">
          <i className="codicon codicon-discard" />
        </button>
        <button className="panel-action" onClick={onRefresh} title="Refresh" aria-label="Refresh architecture">
          <i className="codicon codicon-refresh" />
        </button>
        {/* Discuss button removed — input always visible below drawer */}
      </div>

      {!data ? (
        <div className="arch-loading">Loading architecture...</div>
      ) : (
        <>
          <div className="arch-stats-bar" onClick={() => !reviewOpen && setStatsExpanded(!statsExpanded)}>
            <div className="arch-stats-row">
              <span>
                <i className={`codicon codicon-chevron-${statsExpanded ? "down" : "right"} arch-stats-chevron`} />
                {data.stats.node_count} nodes, {data.stats.edge_count} edges
              </span>
              <span className="arch-approval-status">
                {data.approval?.status === "approved" ? (
                  <span className="arch-approved">v{data.approval.version} approved</span>
                ) : data.approval?.status === "rejected" ? (
                  <span className="arch-rejected">rejected</span>
                ) : (
                  <span className="arch-status-draft">Draft</span>
                )}
              </span>
            </div>
            {statsExpanded && (
              <div className="arch-stats-detail" onClick={(e) => e.stopPropagation()}>
                <div className="arch-stats-grid">
                  <span className="arch-stats-label">Scanned</span>
                  <span>{data.scan?.scanned_at ? new Date(data.scan.scanned_at).toLocaleString() : "—"}</span>
                  <span className="arch-stats-label">Scanned By</span>
                  <span>{data.scan?.scanned_by || "—"}</span>
                  <span className="arch-stats-label">Files</span>
                  <span>{data.scan?.total_files ?? "—"}</span>
                  <span className="arch-stats-label">Status</span>
                  <span className={`arch-status-${data.approval?.status || "draft"}`}>
                    {data.approval?.status || "draft"}
                  </span>
                  {data.approval?.approved_by && (
                    <>
                      <span className="arch-stats-label">Reviewed By</span>
                      <span>{data.approval.approved_by}</span>
                    </>
                  )}
                  {data.approval?.approved_at && (
                    <>
                      <span className="arch-stats-label">Reviewed On</span>
                      <span>{new Date(data.approval.approved_at).toLocaleString()}</span>
                    </>
                  )}
                  <span className="arch-stats-label">Version</span>
                  <span>{data.approval?.version || 0}</span>
                  {data.approval?.comments && (
                    <>
                      <span className="arch-stats-label">Comments</span>
                      <span className="arch-review-comments-display">{data.approval.comments}</span>
                    </>
                  )}
                </div>
                {!reviewOpen && (
                  <button className="arch-review-btn" onClick={() => setReviewOpen(true)}>
                    Review
                  </button>
                )}
                {reviewOpen && (
                  <div className="arch-review-form">
                    <div className="arch-review-title">Review Knowledge Base</div>
                    <div className="arch-review-field">
                      <label className="arch-stats-label">Status</label>
                      <div className="arch-review-radios">
                        <label>
                          <input type="radio" name="reviewStatus" checked={reviewStatus === "approved"}
                            onChange={() => setReviewStatus("approved")} />
                          Approved
                        </label>
                        <label>
                          <input type="radio" name="reviewStatus" checked={reviewStatus === "rejected"}
                            onChange={() => setReviewStatus("rejected")} />
                          Rejected
                        </label>
                      </div>
                    </div>
                    <div className="arch-review-field">
                      <label className="arch-stats-label">Comments</label>
                      <textarea
                        className="arch-review-textarea"
                        rows={3}
                        placeholder="Review comments..."
                        value={reviewComments}
                        onChange={(e) => setReviewComments(e.target.value)}
                      />
                    </div>
                    <div className="arch-review-field">
                      <label className="arch-stats-label">Reviewed By</label>
                      <input
                        className="arch-review-input"
                        type="text"
                        placeholder="Your name"
                        value={reviewName}
                        onChange={(e) => setReviewName(e.target.value)}
                      />
                    </div>
                    <div className="arch-review-actions">
                      <button className="arch-review-cancel" onClick={() => {
                        setReviewOpen(false);
                        setReviewName("");
                        setReviewComments("");
                        setReviewStatus("approved");
                      }}>Cancel</button>
                      <button
                        className="arch-review-submit"
                        disabled={!reviewName.trim()}
                        onClick={() => {
                          onReview(reviewName.trim(), reviewStatus, reviewComments.trim());
                          setReviewOpen(false);
                          setReviewName("");
                          setReviewComments("");
                          setReviewStatus("approved");
                        }}
                      >Submit</button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          {!drawerFullscreen && (
            <div
              ref={containerRef}
              className="arch-graph-container"
            />
          )}
          {drawerOpen && !drawerFullscreen && (
            <div className="arch-drawer-resize-handle" onMouseDown={handleResizeStart} />
          )}
          <div className="arch-drawer-toggle" onClick={() => setDrawerOpen(!drawerOpen)}>
            <i className={`codicon codicon-chevron-${drawerOpen ? "down" : "up"}`} />
            <span className="arch-drawer-toggle-label">{focusLabel(focus)}</span>
            {drawerOpen && (
              <>
                {textZoom !== 100 && (
                  <button
                    className="arch-drawer-fullscreen-btn"
                    onClick={(e) => { e.stopPropagation(); setTextZoom(100); }}
                    title="Reset zoom"
                    aria-label="Reset text zoom"
                  >
                    <span style={{ fontSize: "9px" }}>{textZoom}%</span>
                  </button>
                )}
                <button
                  className="arch-drawer-fullscreen-btn"
                  onClick={(e) => { e.stopPropagation(); setDrawerFullscreen(!drawerFullscreen); }}
                  title={drawerFullscreen ? "Restore" : "Maximize"}
                  aria-label={drawerFullscreen ? "Restore drawer" : "Maximize drawer"}
                >
                  <i className={`codicon codicon-${drawerFullscreen ? "screen-normal" : "screen-full"}`} />
                </button>
              </>
            )}
          </div>
          {drawerOpen && (
            <div
              ref={drawerContentRef}
              className={`arch-drawer-content ${drawerFullscreen ? "fullscreen" : ""}`}
              style={drawerFullscreen ? undefined : { height: `${drawerHeight}px` }}
            >
              <div style={{ fontSize: `${textZoom}%` }}>
                {selectedEdge ? (
                  <EdgeDrawer detail={selectedEdge} onClose={() => setSelectedEdge(null)} />
                ) : selectedNode ? (
                  <DetailDrawer detail={selectedNode} onClose={() => setSelectedNode(null)} onOpenFile={onOpenFile} />
                ) : (
                  <OverviewDrawer data={data} />
                )}
              </div>
            </div>
          )}
          <div className="arch-discuss-bar">
              <span className="arch-discuss-focus">{focusLabel(focus)}</span>
              <div className="arch-discuss-input-row">
                <input
                  ref={discussInputRef}
                  className="arch-discuss-input"
                  type="text"
                  placeholder="Ask about or suggest changes to the architecture..."
                  value={discussInput}
                  onChange={(e) => setDiscussInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleDiscussSubmit(); }}
                />
                <button
                  className="arch-discuss-send"
                  onClick={handleDiscussSubmit}
                  disabled={!discussInput.trim()}
                  aria-label="Send"
                >
                  <i className="codicon codicon-send" />
                </button>
              </div>
            </div>
        </>
      )}
    </div>
  );
});
