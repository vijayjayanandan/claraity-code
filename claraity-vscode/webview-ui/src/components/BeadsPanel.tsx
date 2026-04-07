/**
 * Beads task panel — Queue view (action-oriented) and Epics view (progress-oriented).
 *
 * Both views are built purely from the flat BeadsResponse arrays using
 * client-side grouping on parent_id. No backend changes required.
 */
import { memo, useState, useMemo, useCallback } from "react";
import type { BeadsResponse, BeadData } from "../types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ViewMode = "queue" | "epics";

interface Filters {
  search: string;
  priorities: Set<number>;
}

interface BeadsPanelProps {
  data: BeadsResponse | null;
  onBack: () => void;
  onRefresh: () => void;
}

/** Recursive tree node for multi-level hierarchy. */
interface TreeNode {
  bead: BeadData;
  children: TreeNode[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const priorityLabel = (p: number): string => `P${p}`;

/** Filter beads by text search and priority chips. */
function filterBeads(beads: BeadData[], filters: Filters): BeadData[] {
  return beads.filter((b) => {
    if (filters.search && !b.title.toLowerCase().includes(filters.search.toLowerCase())) {
      return false;
    }
    const bucket = b.priority >= 3 ? 3 : b.priority;
    return filters.priorities.has(bucket);
  });
}

/** Issue type badge colors. */
const issueTypeClass = (t: string): string => {
  switch (t) {
    case "bug": return "issue-type-bug";
    case "feature": return "issue-type-feature";
    case "epic": return "issue-type-epic";
    case "chore": return "issue-type-chore";
    case "decision": return "issue-type-decision";
    default: return "issue-type-task";
  }
};

/** Map each bead ID to its effective display status (uses array membership). */
function buildStatusMap(data: BeadsResponse): Map<string, string> {
  const m = new Map<string, string>();
  for (const b of data.in_progress) m.set(b.id, "in_progress");
  for (const b of data.blocked) m.set(b.id, "blocked");
  for (const b of (data.deferred ?? [])) m.set(b.id, "deferred");
  for (const b of (data.pinned ?? [])) m.set(b.id, "pinned");
  for (const b of data.closed) m.set(b.id, "closed");
  for (const b of data.ready) if (!m.has(b.id)) m.set(b.id, "ready");
  return m;
}

/**
 * Build a recursive tree from flat beads using parent_id.
 * Supports arbitrary nesting depth (epic → task → subtask → ...).
 * Returns root-level trees + orphans (beads whose parent isn't in the dataset).
 */
function buildTree(data: BeadsResponse, statusMap: Map<string, string>): { roots: TreeNode[]; orphans: BeadData[] } {
  const all = [...data.ready, ...data.in_progress, ...data.blocked, ...(data.deferred ?? []), ...(data.pinned ?? []), ...data.closed];
  // Deduplicate in case backend returns a bead in multiple arrays
  const seen = new Set<string>();
  const unique = all.filter((b) => { if (seen.has(b.id)) return false; seen.add(b.id); return true; });
  const byId = new Map(unique.map((b) => [b.id, b]));

  // Build parent → children map
  const childrenMap = new Map<string, BeadData[]>();
  for (const b of unique) {
    if (b.parent_id && byId.has(b.parent_id)) {
      const list = childrenMap.get(b.parent_id) ?? [];
      list.push(b);
      childrenMap.set(b.parent_id, list);
    }
  }

  // Sort function: non-closed by priority first, closed last
  const sortBeads = (arr: BeadData[]) => {
    arr.sort((a, b) => {
      const aClose = statusMap.get(a.id) === "closed" ? 1 : 0;
      const bClose = statusMap.get(b.id) === "closed" ? 1 : 0;
      if (aClose !== bClose) return aClose - bClose;
      return a.priority - b.priority;
    });
  };

  // Recursively build tree nodes (with cycle guard)
  const visited = new Set<string>();
  const buildNode = (bead: BeadData): TreeNode => {
    if (visited.has(bead.id)) return { bead, children: [] }; // break cycle
    visited.add(bead.id);
    const kids = childrenMap.get(bead.id) ?? [];
    sortBeads(kids);
    return { bead, children: kids.map(buildNode) };
  };

  // Roots = beads with no parent or whose parent isn't in the dataset
  // Also beads that HAVE children (epics/parents) at any level
  const hasParentInSet = new Set<string>();
  for (const b of unique) {
    if (b.parent_id && byId.has(b.parent_id)) {
      hasParentInSet.add(b.id);
    }
  }

  const roots: TreeNode[] = [];
  const orphans: BeadData[] = [];

  for (const b of unique) {
    if (hasParentInSet.has(b.id)) continue; // will be nested under its parent
    if (childrenMap.has(b.id)) {
      // This is a root-level parent (epic or nested parent)
      roots.push(buildNode(b));
    } else {
      // Leaf with no parent in dataset
      orphans.push(b);
    }
  }

  // Sort roots: incomplete first (by priority), complete last
  roots.sort((a, b) => {
    const aDone = isTreeComplete(a, statusMap);
    const bDone = isTreeComplete(b, statusMap);
    if (aDone !== bDone) return aDone ? 1 : -1;
    return a.bead.priority - b.bead.priority;
  });

  return { roots, orphans };
}

/** Count all leaf descendants (recursive). */
function countLeaves(node: TreeNode, statusMap: Map<string, string>): { total: number; closed: number } {
  if (node.children.length === 0) {
    return { total: 1, closed: statusMap.get(node.bead.id) === "closed" ? 1 : 0 };
  }
  let total = 0, closed = 0;
  for (const child of node.children) {
    const c = countLeaves(child, statusMap);
    total += c.total;
    closed += c.closed;
  }
  return { total, closed };
}

/** Check if all descendants are closed. */
function isTreeComplete(node: TreeNode, statusMap: Map<string, string>): boolean {
  const { total, closed } = countLeaves(node, statusMap);
  return total > 0 && closed === total;
}

// ---------------------------------------------------------------------------
// BeadItem — a single bead row (used in Queue view)
// ---------------------------------------------------------------------------

function BeadItem({ bead, parentTitle }: { bead: BeadData; parentTitle?: string }) {
  const [expanded, setExpanded] = useState(false);
  const toggle = () => setExpanded((v) => !v);
  const onKeyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };

  const issueType = bead.issue_type ?? "task";
  const showType = issueType !== "task";
  const notes = bead.notes ?? [];
  const hasDueDate = !!bead.due_at;
  const isOverdue = hasDueDate && new Date(bead.due_at!) < new Date();

  return (
    <div className="bead-item" onClick={toggle} onKeyDown={onKeyDown} tabIndex={0} role="button" aria-expanded={expanded}>
      <div className="bead-header">
        <span className={`bead-priority priority-${bead.priority}`}>{priorityLabel(bead.priority)}</span>
        {showType && <span className={`bead-issue-type ${issueTypeClass(issueType)}`}>{issueType}</span>}
        <span className="bead-title">{bead.title}</span>
        <span className="bead-id">{bead.id}</span>
      </div>
      {/* Meta row: parent crumb, tags, assignee, due date */}
      {(parentTitle || bead.tags.length > 0 || bead.assignee || hasDueDate || bead.external_ref) && (
        <div className="bead-meta-row">
          {parentTitle && (
            <span className="bead-epic-crumb">
              <i className="codicon codicon-list-tree" /> {parentTitle}
            </span>
          )}
          {bead.tags.map((tag) => (
            <span key={tag} className="bead-tag">{tag}</span>
          ))}
          {bead.assignee && bead.assignee !== "agent" && (
            <span className="bead-assignee" title={`Assigned: ${bead.assignee}`}>
              <i className="codicon codicon-person" /> {bead.assignee.replace("claraity:session-", "session:")}
            </span>
          )}
          {hasDueDate && (
            <span className={`bead-due ${isOverdue ? "overdue" : ""}`} title={`Due: ${bead.due_at}`}>
              <i className="codicon codicon-calendar" /> {new Date(bead.due_at!).toLocaleDateString()}
            </span>
          )}
          {bead.external_ref && (
            <span className="bead-external-ref" title={bead.external_ref}>
              <i className="codicon codicon-link-external" /> {bead.external_ref}
            </span>
          )}
        </div>
      )}
      {/* Inline notes for in-progress tasks (visible without expanding) */}
      {bead.status === "in_progress" && notes.length > 0 && !expanded && (
        <div className="bead-inline-notes">
          {notes.slice(-1).map((n, i) => (
            <div key={i} className="bead-inline-note">
              <i className="codicon codicon-note" />
              <span>{n.content}</span>
            </div>
          ))}
        </div>
      )}
      {/* Defer info */}
      {bead.status === "deferred" && bead.defer_until && !expanded && (
        <div className="bead-defer-info">
          <i className="codicon codicon-clock" /> Until {new Date(bead.defer_until).toLocaleDateString()}
        </div>
      )}
      {expanded && (
        <div className="bead-details">
          {bead.description && <p className="bead-description">{bead.description}</p>}
          {bead.design && (
            <div className="bead-design">
              <span className="bead-detail-label">Design:</span> {bead.design}
            </div>
          )}
          {bead.acceptance_criteria && (
            <div className="bead-acceptance">
              <span className="bead-detail-label">Acceptance:</span> {bead.acceptance_criteria}
            </div>
          )}
          {bead.estimated_minutes && (
            <span className="bead-estimate">
              <i className="codicon codicon-clock" /> {bead.estimated_minutes} min
            </span>
          )}
          {bead.blockers.length > 0 && (
            <div className="bead-blockers">
              <span className="bead-blockers-label">Blocked by:</span>
              {bead.blockers.map((b) => (
                <span key={b.id} className={`bead-blocker ${b.status}`}>{b.title}</span>
              ))}
            </div>
          )}
          {notes.length > 0 && (
            <div className="bead-notes">
              <span className="bead-detail-label">Notes:</span>
              {notes.map((n, i) => (
                <div key={i} className="bead-note">
                  <span className="bead-note-author">[{n.author}]</span> {n.content}
                </div>
              ))}
            </div>
          )}
          {bead.summary && <p className="bead-summary">Summary: {bead.summary}</p>}
          {bead.close_reason && <p className="bead-close-reason">Reason: {bead.close_reason}</p>}
          <span className="bead-created">Created: {new Date(bead.created_at).toLocaleDateString()}</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BeadSection — collapsible section (used in Queue view)
// ---------------------------------------------------------------------------

function BeadSection({ title, icon, beads, defaultOpen = true, parentLookup }: {
  title: string;
  icon: string;
  beads: BeadData[];
  defaultOpen?: boolean;
  parentLookup?: (bead: BeadData) => string | undefined;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (beads.length === 0) return null;

  return (
    <div className="bead-section">
      <button className="bead-section-header" onClick={() => setOpen(!open)} aria-expanded={open}>
        <i className={`codicon codicon-chevron-${open ? "down" : "right"}`} />
        <i className={`codicon ${icon} bead-section-status-icon`} />
        <span className="bead-section-title">{title}</span>
        <span className="bead-section-count">{beads.length}</span>
      </button>
      {open && (
        <div className="bead-section-body">
          {beads.map((bead) => (
            <BeadItem key={bead.id} bead={bead} parentTitle={parentLookup?.(bead)} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FilterBar
// ---------------------------------------------------------------------------

function FilterBar({ filters, setFilters }: {
  filters: Filters;
  setFilters: React.Dispatch<React.SetStateAction<Filters>>;
}) {
  const togglePriority = (p: number) => {
    setFilters((f) => {
      const next = new Set(f.priorities);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return { ...f, priorities: next };
    });
  };

  return (
    <div className="beads-filter-bar">
      <div className="beads-search">
        <i className="codicon codicon-search" />
        <input
          className="beads-search-input"
          type="text"
          placeholder="Filter by title..."
          value={filters.search}
          onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
        />
        {filters.search && (
          <button
            className="beads-search-clear"
            onClick={() => setFilters((f) => ({ ...f, search: "" }))}
            aria-label="Clear search"
          >
            <i className="codicon codicon-close" />
          </button>
        )}
      </div>
      <div className="beads-priority-filters">
        {[0, 1, 2, 3].map((p) => (
          <button
            key={p}
            className={`beads-priority-chip priority-${p} ${filters.priorities.has(p) ? "active" : ""}`}
            onClick={() => togglePriority(p)}
          >
            P{p}{p === 3 ? "+" : ""}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// QueueView — action-oriented (In Progress > Up Next > Blocked)
// ---------------------------------------------------------------------------

function QueueView({ data, filters, showClosed, setShowClosed }: {
  data: BeadsResponse;
  filters: Filters;
  showClosed: boolean;
  setShowClosed: (v: boolean) => void;
}) {
  const allBeads = useMemo(
    () => [...data.ready, ...data.in_progress, ...data.blocked, ...(data.deferred ?? []), ...(data.pinned ?? []), ...data.closed],
    [data],
  );
  const beadMap = useMemo(() => new Map(allBeads.map((b) => [b.id, b])), [allBeads]);
  const parentLookup = useCallback((bead: BeadData): string | undefined => {
    if (!bead.parent_id) return undefined;
    return beadMap.get(bead.parent_id)?.title;
  }, [beadMap]);

  const { inProgress, upNext, blocked, deferred, pinned, closed } = useMemo(() => ({
    inProgress: filterBeads(data.in_progress, filters),
    upNext: filterBeads(data.ready, filters),
    blocked: filterBeads(data.blocked, filters),
    deferred: filterBeads(data.deferred ?? [], filters),
    pinned: filterBeads(data.pinned ?? [], filters),
    closed: filterBeads(data.closed, filters),
  }), [data, filters]);

  const hasVisible = inProgress.length > 0 || upNext.length > 0 || blocked.length > 0 || deferred.length > 0 || pinned.length > 0;

  return (
    <div className="beads-list">
      <BeadSection title="In Progress" icon="codicon-play" beads={inProgress} parentLookup={parentLookup} />
      <BeadSection title="Up Next" icon="codicon-arrow-right" beads={upNext} parentLookup={parentLookup} />
      <BeadSection title="Blocked" icon="codicon-error" beads={blocked} parentLookup={parentLookup} />
      {pinned.length > 0 && (
        <BeadSection title="Pinned" icon="codicon-pin" beads={pinned} parentLookup={parentLookup} defaultOpen={false} />
      )}
      {deferred.length > 0 && (
        <BeadSection title="Deferred" icon="codicon-clock" beads={deferred} parentLookup={parentLookup} defaultOpen={false} />
      )}
      {!hasVisible && closed.length === 0 && (
        <div className="bead-empty">No beads match your filters</div>
      )}
      {showClosed && (
        <BeadSection title="Closed" icon="codicon-pass" beads={closed} parentLookup={parentLookup} defaultOpen={false} />
      )}
      {closed.length > 0 && (
        <div className="beads-closed-toggle">
          <button className="beads-closed-link" onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? "Hide" : "Show"} {closed.length} closed
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TreeNodeCard — recursive hierarchy renderer (epic → task → subtask → ...)
// ---------------------------------------------------------------------------

function statusIcon(status: string): { icon: string; cls: string } {
  switch (status) {
    case "in_progress": return { icon: "codicon-circle-filled", cls: "status-in-progress" };
    case "blocked":     return { icon: "codicon-error", cls: "status-blocked" };
    case "deferred":    return { icon: "codicon-clock", cls: "status-deferred" };
    case "pinned":      return { icon: "codicon-pin", cls: "status-pinned" };
    case "closed":      return { icon: "codicon-pass-filled", cls: "status-closed" };
    default:            return { icon: "codicon-circle-outline", cls: "status-ready" };
  }
}

/** Recursive tree node card. Depth 0 = epic (full card), depth 1+ = nested children. */
function TreeNodeCard({ node, statusMap, depth = 0 }: {
  node: TreeNode;
  statusMap: Map<string, string>;
  depth?: number;
}) {
  const bead = node.bead;
  const { total, closed: closedCount } = countLeaves(node, statusMap);
  const isComplete = total > 0 && closedCount === total;
  const [expanded, setExpanded] = useState(!isComplete);
  const status = statusMap.get(bead.id) ?? "ready";
  const si = statusIcon(status);
  const issueType = bead.issue_type ?? "task";
  const showType = issueType !== "task";
  const notes = bead.notes ?? [];
  const hasChildren = node.children.length > 0;

  // Status counts for collapsed summary dots
  const statusCounts: Record<string, number> = {};
  if (hasChildren) {
    for (const child of node.children) {
      const st = statusMap.get(child.bead.id) ?? "ready";
      statusCounts[st] = (statusCounts[st] ?? 0) + 1;
    }
  }

  // Depth 0: full epic-style card with progress bar
  if (depth === 0) {
    return (
      <div className={`epic-card ${isComplete ? "epic-complete" : ""}`}>
        <button className="epic-header" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          <i className={`codicon codicon-chevron-${expanded ? "down" : "right"}`} />
          <span className={`bead-priority priority-${bead.priority}`}>{priorityLabel(bead.priority)}</span>
          {showType && <span className={`bead-issue-type ${issueTypeClass(issueType)}`}>{issueType}</span>}
          <span className="epic-title">{bead.title}</span>
          {total > 0 && <span className="epic-progress-label">{closedCount}/{total}</span>}
        </button>
        {total > 0 && (
          <div className="epic-progress-bar-track">
            <div
              className={`epic-progress-bar-fill ${isComplete ? "complete" : ""}`}
              style={{ width: `${(closedCount / total) * 100}%` }}
            />
          </div>
        )}
        {!expanded && total > 0 && (
          <div className="epic-status-dots">
            {statusCounts.in_progress && <span className="epic-dot status-in-progress" title={`${statusCounts.in_progress} in progress`}>{statusCounts.in_progress}</span>}
            {statusCounts.ready && <span className="epic-dot status-ready" title={`${statusCounts.ready} ready`}>{statusCounts.ready}</span>}
            {statusCounts.blocked && <span className="epic-dot status-blocked" title={`${statusCounts.blocked} blocked`}>{statusCounts.blocked}</span>}
            {statusCounts.deferred && <span className="epic-dot status-deferred" title={`${statusCounts.deferred} deferred`}>{statusCounts.deferred}</span>}
            {statusCounts.closed && <span className="epic-dot status-closed" title={`${statusCounts.closed} closed`}>{statusCounts.closed}</span>}
          </div>
        )}
        {expanded && (
          <div className="epic-children">
            {node.children.map((child) => (
              <TreeNodeCard key={child.bead.id} node={child} statusMap={statusMap} depth={1} />
            ))}
          </div>
        )}
      </div>
    );
  }

  // Depth 1+: nested child row with indent
  const indent = depth * 16;
  const childProgress = hasChildren ? countLeaves(node, statusMap) : null;
  return (
    <div className="tree-node" style={{ paddingLeft: `${indent}px` }}>
      <div
        className={`epic-child ${si.cls} ${hasChildren ? "has-children" : ""}`}
        onClick={hasChildren ? () => setExpanded(!expanded) : undefined}
        role={hasChildren ? "button" : undefined}
        tabIndex={hasChildren ? 0 : undefined}
        onKeyDown={hasChildren ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(!expanded); } } : undefined}
      >
        {hasChildren && <i className={`codicon codicon-chevron-${expanded ? "down" : "right"} tree-chevron`} />}
        <i className={`codicon ${si.icon} ${si.cls}`} />
        {showType && <span className={`bead-issue-type ${issueTypeClass(issueType)}`}>{issueType}</span>}
        <span className="epic-child-title">{bead.title}</span>
        <span className={`bead-priority priority-${bead.priority}`}>{priorityLabel(bead.priority)}</span>
        {childProgress && <span className="epic-progress-label">{childProgress.closed}/{childProgress.total}</span>}
        {bead.assignee && bead.assignee !== "agent" && (
          <span className="bead-assignee tree-meta">
            <i className="codicon codicon-person" />
          </span>
        )}
      </div>
      {/* Inline note for in-progress nodes */}
      {status === "in_progress" && notes.length > 0 && !expanded && (
        <div className="bead-inline-notes" style={{ paddingLeft: `${indent + 24}px` }}>
          {notes.slice(-1).map((n, i) => (
            <div key={i} className="bead-inline-note">
              <i className="codicon codicon-note" />
              <span>{n.content}</span>
            </div>
          ))}
        </div>
      )}
      {/* Blockers for blocked nodes */}
      {status === "blocked" && bead.blockers.length > 0 && !expanded && (
        <div className="tree-blockers" style={{ paddingLeft: `${indent + 24}px` }}>
          <span className="bead-blockers-label">Blocked by:</span>
          {bead.blockers.map((bl) => (
            <span key={bl.id} className="bead-blocker-pill">{bl.title}</span>
          ))}
        </div>
      )}
      {/* Recurse into children */}
      {expanded && hasChildren && (
        <div className="tree-children">
          {node.children.map((child) => (
            <TreeNodeCard key={child.bead.id} node={child} statusMap={statusMap} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EpicsView — progress-oriented, grouped by epic
// ---------------------------------------------------------------------------

function EpicsView({ data, filters, showClosed, setShowClosed }: {
  data: BeadsResponse;
  filters: Filters;
  showClosed: boolean;
  setShowClosed: (v: boolean) => void;
}) {
  const statusMap = useMemo(() => buildStatusMap(data), [data]);
  const { roots, orphans } = useMemo(() => buildTree(data, statusMap), [data, statusMap]);

  const filteredOrphans = filterBeads(orphans, filters);
  const openOrphans = filteredOrphans.filter((b) => statusMap.get(b.id) !== "closed");
  const closedOrphanCount = filteredOrphans.filter((b) => statusMap.get(b.id) === "closed").length;
  const visibleOrphans = showClosed ? filteredOrphans : openOrphans;

  // Filter roots: hide if search doesn't match title and no descendants match
  const matchesFilter = (node: TreeNode): boolean => {
    if (!filters.search) return true;
    const q = filters.search.toLowerCase();
    if (node.bead.title.toLowerCase().includes(q)) return true;
    return node.children.some(matchesFilter);
  };
  const visibleRoots = roots.filter(matchesFilter);

  const hasAnything = visibleRoots.length > 0 || visibleOrphans.length > 0;

  return (
    <div className="beads-list">
      {visibleRoots.map((root) => (
        <TreeNodeCard key={root.bead.id} node={root} statusMap={statusMap} depth={0} />
      ))}
      {!hasAnything && (
        <div className="bead-empty">No beads match your filters</div>
      )}
      {visibleOrphans.length > 0 && (
        <div className="bead-section">
          <div className="bead-section-header epic-ungrouped-header">
            <span className="bead-section-title">Ungrouped</span>
            <span className="bead-section-count">{visibleOrphans.length}</span>
          </div>
          <div className="bead-section-body">
            {visibleOrphans.map((bead) => (
              <BeadItem key={bead.id} bead={bead} />
            ))}
          </div>
        </div>
      )}
      {closedOrphanCount > 0 && (
        <div className="beads-closed-toggle">
          <button className="beads-closed-link" onClick={() => setShowClosed(!showClosed)}>
            {showClosed ? "Hide" : "Show"} {closedOrphanCount} closed ungrouped
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BeadsPanel — main component
// ---------------------------------------------------------------------------

export const BeadsPanel = memo(function BeadsPanel({ data, onBack, onRefresh }: BeadsPanelProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("queue");
  const [filters, setFilters] = useState<Filters>({
    search: "",
    priorities: new Set([0, 1, 2, 3]),
  });
  const [showClosed, setShowClosed] = useState(false);

  return (
    <div className="beads-panel">
      <div className="panel-header">
        <button className="panel-back" onClick={onBack} title="Back to chat" aria-label="Back to chat">
          <i className="codicon codicon-arrow-left" />
        </button>
        <span className="panel-title">Beads</span>
        <button
          className={`panel-action ${viewMode === "queue" ? "active" : ""}`}
          onClick={() => setViewMode("queue")}
          title="Queue view"
          aria-label="Queue view"
        >
          <i className="codicon codicon-list-flat" />
        </button>
        <button
          className={`panel-action ${viewMode === "epics" ? "active" : ""}`}
          onClick={() => setViewMode("epics")}
          title="Epics view"
          aria-label="Epics view"
        >
          <i className="codicon codicon-list-tree" />
        </button>
        <button className="panel-action" onClick={onRefresh} title="Refresh" aria-label="Refresh beads">
          <i className="codicon codicon-refresh" />
        </button>
      </div>

      {!data ? (
        <div className="beads-loading">Loading beads...</div>
      ) : (
        <>
          <div className="beads-stats">
            {data.stats.total} tasks:
            {" "}{data.stats.open} open,
            {" "}{data.stats.in_progress} in progress,
            {" "}{data.stats.closed} closed
            {(data.stats.blocked ?? 0) > 0 && `, ${data.stats.blocked} blocked`}
            {(data.stats.deferred ?? 0) > 0 && `, ${data.stats.deferred} deferred`}
            {data.stats.dependencies > 0 && ` | ${data.stats.dependencies} deps`}
          </div>

          <FilterBar filters={filters} setFilters={setFilters} />

          {viewMode === "queue" ? (
            <QueueView data={data} filters={filters} showClosed={showClosed} setShowClosed={setShowClosed} />
          ) : (
            <EpicsView data={data} filters={filters} showClosed={showClosed} setShowClosed={setShowClosed} />
          )}
        </>
      )}
    </div>
  );
});
