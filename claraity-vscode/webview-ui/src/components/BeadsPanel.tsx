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

interface EpicGroup {
  epic: BeadData;
  children: BeadData[];
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

/** Map each bead ID to its effective display status (uses array membership). */
function buildStatusMap(data: BeadsResponse): Map<string, string> {
  const m = new Map<string, string>();
  for (const b of data.in_progress) m.set(b.id, "in_progress");
  for (const b of data.blocked) m.set(b.id, "blocked");
  for (const b of data.closed) m.set(b.id, "closed");
  for (const b of data.ready) if (!m.has(b.id)) m.set(b.id, "ready");
  return m;
}

/**
 * Group all beads into epic trees + orphans.
 * Uses statusMap (derived from array membership) as the single source of truth
 * for display status, avoiding divergence with BeadData.status field.
 */
function buildEpicTree(data: BeadsResponse, statusMap: Map<string, string>): { epics: EpicGroup[]; orphans: BeadData[] } {
  const all = [...data.ready, ...data.in_progress, ...data.blocked, ...data.closed];
  // Deduplicate in case backend returns a bead in multiple arrays
  const seen = new Set<string>();
  const unique = all.filter((b) => { if (seen.has(b.id)) return false; seen.add(b.id); return true; });
  const byId = new Map(unique.map((b) => [b.id, b]));

  // Determine which IDs are referenced as parent_id
  const parentIds = new Set<string>();
  for (const b of unique) {
    if (b.parent_id) parentIds.add(b.parent_id);
  }

  // Epics = beads that ARE a parent AND have no parent themselves
  const epicIds = new Set<string>();
  for (const pid of parentIds) {
    const parent = byId.get(pid);
    if (parent && !parent.parent_id) epicIds.add(pid);
  }

  // Group children under their epic
  const childrenMap = new Map<string, BeadData[]>();
  const orphans: BeadData[] = [];

  for (const b of unique) {
    if (epicIds.has(b.id)) continue; // epic bead itself
    if (b.parent_id && epicIds.has(b.parent_id)) {
      const list = childrenMap.get(b.parent_id) ?? [];
      list.push(b);
      childrenMap.set(b.parent_id, list);
    } else {
      orphans.push(b);
    }
  }

  const epics: EpicGroup[] = [];
  for (const eid of epicIds) {
    const epic = byId.get(eid)!;
    const children = childrenMap.get(eid) ?? [];
    // Sort children: non-closed first (by priority), then closed
    children.sort((a, b) => {
      const aClose = statusMap.get(a.id) === "closed" ? 1 : 0;
      const bClose = statusMap.get(b.id) === "closed" ? 1 : 0;
      if (aClose !== bClose) return aClose - bClose;
      return a.priority - b.priority;
    });
    epics.push({ epic, children });
  }

  // Sort epics: incomplete first (by priority), complete last
  epics.sort((a, b) => {
    const aDone = a.children.length > 0 && a.children.every((c) => statusMap.get(c.id) === "closed");
    const bDone = b.children.length > 0 && b.children.every((c) => statusMap.get(c.id) === "closed");
    if (aDone !== bDone) return aDone ? 1 : -1;
    return a.epic.priority - b.epic.priority;
  });

  return { epics, orphans };
}

// ---------------------------------------------------------------------------
// BeadItem — a single bead row (used in Queue view)
// ---------------------------------------------------------------------------

function BeadItem({ bead, parentTitle }: { bead: BeadData; parentTitle?: string }) {
  const [expanded, setExpanded] = useState(false);
  const toggle = () => setExpanded((v) => !v);
  const onKeyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };

  return (
    <div className="bead-item" onClick={toggle} onKeyDown={onKeyDown} tabIndex={0} role="button" aria-expanded={expanded}>
      <div className="bead-header">
        <span className={`bead-priority priority-${bead.priority}`}>{priorityLabel(bead.priority)}</span>
        <span className="bead-title">{bead.title}</span>
        <span className="bead-id">{bead.id}</span>
      </div>
      {(parentTitle || bead.tags.length > 0) && (
        <div className="bead-meta-row">
          {parentTitle && (
            <span className="bead-epic-crumb">
              <i className="codicon codicon-list-tree" /> {parentTitle}
            </span>
          )}
          {bead.tags.map((tag) => (
            <span key={tag} className="bead-tag">{tag}</span>
          ))}
        </div>
      )}
      {expanded && (
        <div className="bead-details">
          {bead.description && <p className="bead-description">{bead.description}</p>}
          {bead.blockers.length > 0 && (
            <div className="bead-blockers">
              <span className="bead-blockers-label">Blocked by:</span>
              {bead.blockers.map((b) => (
                <span key={b.id} className={`bead-blocker ${b.status}`}>{b.title}</span>
              ))}
            </div>
          )}
          {bead.summary && <p className="bead-summary">Summary: {bead.summary}</p>}
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
    () => [...data.ready, ...data.in_progress, ...data.blocked, ...data.closed],
    [data],
  );
  const beadMap = useMemo(() => new Map(allBeads.map((b) => [b.id, b])), [allBeads]);
  const parentLookup = useCallback((bead: BeadData): string | undefined => {
    if (!bead.parent_id) return undefined;
    return beadMap.get(bead.parent_id)?.title;
  }, [beadMap]);

  const { inProgress, upNext, blocked, closed } = useMemo(() => ({
    inProgress: filterBeads(data.in_progress, filters),
    upNext: filterBeads(data.ready, filters),
    blocked: filterBeads(data.blocked, filters),
    closed: filterBeads(data.closed, filters),
  }), [data, filters]);

  const hasVisible = inProgress.length > 0 || upNext.length > 0 || blocked.length > 0;

  return (
    <div className="beads-list">
      <BeadSection title="In Progress" icon="codicon-play" beads={inProgress} parentLookup={parentLookup} />
      <BeadSection title="Up Next" icon="codicon-arrow-right" beads={upNext} parentLookup={parentLookup} />
      <BeadSection title="Blocked" icon="codicon-error" beads={blocked} parentLookup={parentLookup} />
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
// EpicCard — a single epic with progress bar and children
// ---------------------------------------------------------------------------

function statusIcon(status: string): { icon: string; cls: string } {
  switch (status) {
    case "in_progress": return { icon: "codicon-circle-filled", cls: "status-in-progress" };
    case "blocked":     return { icon: "codicon-error", cls: "status-blocked" };
    case "closed":      return { icon: "codicon-pass-filled", cls: "status-closed" };
    default:            return { icon: "codicon-circle-outline", cls: "status-ready" };
  }
}

function EpicCard({ epic, children, statusMap }: {
  epic: BeadData;
  children: BeadData[];
  statusMap: Map<string, string>;
}) {
  const closedCount = children.filter((c) => statusMap.get(c.id) === "closed").length;
  const total = children.length;
  const isComplete = total > 0 && closedCount === total;
  const [expanded, setExpanded] = useState(!isComplete);

  // Count children per status for summary dots
  const statusCounts: Record<string, number> = {};
  for (const c of children) {
    const st = statusMap.get(c.id) ?? "ready";
    statusCounts[st] = (statusCounts[st] ?? 0) + 1;
  }

  return (
    <div className={`epic-card ${isComplete ? "epic-complete" : ""}`}>
      <button className="epic-header" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <i className={`codicon codicon-chevron-${expanded ? "down" : "right"}`} />
        <span className={`bead-priority priority-${epic.priority}`}>{priorityLabel(epic.priority)}</span>
        <span className="epic-title">{epic.title}</span>
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
      {!expanded && total === 0 && (
        <div className="bead-empty">No tasks match filters</div>
      )}
      {!expanded && total > 0 && (
        <div className="epic-status-dots">
          {statusCounts.in_progress && (
            <span className="epic-dot status-in-progress" title={`${statusCounts.in_progress} in progress`}>
              {statusCounts.in_progress}
            </span>
          )}
          {statusCounts.ready && (
            <span className="epic-dot status-ready" title={`${statusCounts.ready} ready`}>
              {statusCounts.ready}
            </span>
          )}
          {statusCounts.blocked && (
            <span className="epic-dot status-blocked" title={`${statusCounts.blocked} blocked`}>
              {statusCounts.blocked}
            </span>
          )}
          {statusCounts.closed && (
            <span className="epic-dot status-closed" title={`${statusCounts.closed} closed`}>
              {statusCounts.closed}
            </span>
          )}
        </div>
      )}
      {expanded && (
        <div className="epic-children">
          {children.map((child) => {
            const si = statusIcon(statusMap.get(child.id) ?? "ready");
            return (
              <div key={child.id} className={`epic-child ${si.cls}`}>
                <i className={`codicon ${si.icon} ${si.cls}`} />
                <span className="epic-child-title">{child.title}</span>
                <span className={`bead-priority priority-${child.priority}`}>{priorityLabel(child.priority)}</span>
              </div>
            );
          })}
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
  const { epics, orphans } = useMemo(() => buildEpicTree(data, statusMap), [data, statusMap]);

  const filteredOrphans = filterBeads(orphans, filters);
  const openOrphans = filteredOrphans.filter((b) => statusMap.get(b.id) !== "closed");
  const closedOrphanCount = filteredOrphans.filter((b) => statusMap.get(b.id) === "closed").length;
  const visibleOrphans = showClosed ? filteredOrphans : openOrphans;

  // Pre-filter epics to count visible ones for empty state
  const visibleEpics = epics.map(({ epic, children }) => {
    const filteredChildren = filterBeads(children, filters);
    const hidden = filters.search &&
      !epic.title.toLowerCase().includes(filters.search.toLowerCase()) &&
      filteredChildren.length === 0;
    return hidden ? null : { epic, filteredChildren };
  }).filter(Boolean) as { epic: BeadData; filteredChildren: BeadData[] }[];

  const hasAnything = visibleEpics.length > 0 || visibleOrphans.length > 0;

  return (
    <div className="beads-list">
      {visibleEpics.map(({ epic, filteredChildren }) => (
        <EpicCard key={epic.id} epic={epic} children={filteredChildren} statusMap={statusMap} />
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
