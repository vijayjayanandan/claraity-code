/**
 * Beads task panel — shows ready/in-progress/blocked/closed task groups.
 */
import { memo, useState } from "react";
import type { BeadsResponse, BeadData } from "../types";

interface BeadsPanelProps {
  data: BeadsResponse | null;
  onBack: () => void;
  onRefresh: () => void;
}

const priorityLabel = (p: number): string => `P${p}`;

function BeadItem({ bead }: { bead: BeadData }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bead-item" onClick={() => setExpanded(!expanded)}>
      <div className="bead-header">
        <span className={`bead-priority priority-${bead.priority}`}>{priorityLabel(bead.priority)}</span>
        <span className="bead-title">{bead.title}</span>
        <span className="bead-id">{bead.id}</span>
      </div>
      {expanded && (
        <div className="bead-details">
          {bead.description && <p className="bead-description">{bead.description}</p>}
          {bead.tags.length > 0 && (
            <div className="bead-tags">
              {bead.tags.map((tag) => (
                <span key={tag} className="bead-tag">{tag}</span>
              ))}
            </div>
          )}
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

function BeadSection({ title, icon, beads, defaultOpen = true }: {
  title: string;
  icon: string;
  beads: BeadData[];
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bead-section">
      <button className="bead-section-header" onClick={() => setOpen(!open)}>
        <i className={`codicon codicon-chevron-${open ? "down" : "right"}`} />
        <span className="bead-section-icon">{icon}</span>
        <span className="bead-section-title">{title}</span>
        <span className="bead-section-count">{beads.length}</span>
      </button>
      {open && (
        <div className="bead-section-body">
          {beads.length === 0 ? (
            <div className="bead-empty">No tasks</div>
          ) : (
            beads.map((bead) => <BeadItem key={bead.id} bead={bead} />)
          )}
        </div>
      )}
    </div>
  );
}

export const BeadsPanel = memo(function BeadsPanel({ data, onBack, onRefresh }: BeadsPanelProps) {
  return (
    <div className="beads-panel">
      <div className="panel-header">
        <button className="panel-back" onClick={onBack} title="Back to chat" aria-label="Back to chat">
          <i className="codicon codicon-arrow-left" />
        </button>
        <span className="panel-title">Beads</span>
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

          <div className="beads-list">
            <BeadSection title="Ready" icon=">" beads={data.ready} />
            <BeadSection title="In Progress" icon="~" beads={data.in_progress} />
            <BeadSection title="Blocked" icon="x" beads={data.blocked} />
            <BeadSection title="Closed" icon="+" beads={data.closed} defaultOpen={false} />
          </div>
        </>
      )}
    </div>
  );
});
