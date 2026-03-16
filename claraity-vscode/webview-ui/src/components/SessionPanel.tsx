/**
 * Session history browser panel.
 */
import { useState } from "react";
import type { SessionSummary } from "../types";

interface SessionPanelProps {
  sessions: SessionSummary[];
  onBack: () => void;
  onNewSession: () => void;
  onResumeSession: (sessionId: string) => void;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function SessionPanel({ sessions, onBack, onNewSession, onResumeSession }: SessionPanelProps) {
  const [search, setSearch] = useState("");

  const filtered = sessions.filter((s) =>
    s.first_message.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="session-panel">
      <div className="session-panel-header">
        <button className="btn-secondary" onClick={onBack}>
          <i className="codicon codicon-arrow-left" /> Back
        </button>
        <span style={{ fontWeight: 600, fontSize: 12 }}>Session History</span>
        <button className="toolbar-icon" onClick={onNewSession} title="New Chat">
          <i className="codicon codicon-add" />
        </button>
      </div>

      <input
        className="session-search"
        type="text"
        placeholder="Filter sessions..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="session-list">
        {filtered.length === 0 ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--vscode-descriptionForeground)", fontSize: 12 }}>
            No previous sessions found
          </div>
        ) : (
          filtered.map((session) => (
            <div
              key={session.session_id}
              className="session-card"
              onClick={() => onResumeSession(session.session_id)}
            >
              <div className="session-title">{session.first_message}</div>
              <div className="session-meta">
                {timeAgo(session.updated_at)} - {session.message_count} msgs
                {session.git_branch ? ` - ${session.git_branch}` : ""}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
