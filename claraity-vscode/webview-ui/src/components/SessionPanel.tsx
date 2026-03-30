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
  onDeleteSession: (sessionId: string) => void;
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

export function SessionPanel({ sessions, onBack, onNewSession, onResumeSession, onDeleteSession }: SessionPanelProps) {
  const [search, setSearch] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

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
              onClick={() => {
                if (confirmDeleteId === session.session_id) return;
                onResumeSession(session.session_id);
              }}
            >
              <div className="session-card-content">
                <div className="session-title">{session.first_message}</div>
                <div className="session-meta">
                  {timeAgo(session.updated_at)} - {session.message_count} msgs
                  {session.git_branch ? ` - ${session.git_branch}` : ""}
                </div>
              </div>
              {confirmDeleteId === session.session_id ? (
                <div className="session-delete-confirm" onClick={(e) => e.stopPropagation()}>
                  <span style={{ fontSize: 11, color: "var(--vscode-descriptionForeground)" }}>Delete?</span>
                  <button
                    className="session-delete-confirm-yes"
                    title="Confirm delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(session.session_id);
                      setConfirmDeleteId(null);
                    }}
                  >
                    Yes
                  </button>
                  <button
                    className="session-delete-confirm-no"
                    title="Cancel"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDeleteId(null);
                    }}
                  >
                    No
                  </button>
                </div>
              ) : (
                <button
                  className="session-delete-btn"
                  title="Delete session"
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDeleteId(session.session_id);
                  }}
                >
                  <i className="codicon codicon-trash" />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
