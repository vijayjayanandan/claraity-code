/**
 * Footer bar with connection status, view buttons (Architecture, Beads),
 * model name, and Plan/Act mode toggle.
 */
import { memo } from "react";

interface BottomBarProps {
  connected: boolean;
  modelName: string;
  permissionMode: string;
  onSetMode: (mode: string) => void;
  onShowArchitecture: () => void;
  onShowBeads: () => void;
  onShowTrace: () => void;
  beadsReadyCount?: number;
  onDisconnect: () => void;
  onReconnect: () => void;
}

export const BottomBar = memo(function BottomBar({
  connected,
  modelName,
  permissionMode,
  onSetMode,
  onShowArchitecture,
  onShowBeads,
  onShowTrace,
  beadsReadyCount,
  onDisconnect,
  onReconnect,
}: BottomBarProps) {
  return (
    <div className="bottom-bar" role="status">
      <div className="bottom-left">
        <span className={`connection-status ${connected ? "connected" : "disconnected"}`} aria-live="polite">
          {connected ? "Connected" : "Disconnected"}
        </span>
        <button
          className={`connection-toggle-btn ${connected ? "connection-toggle-on" : "connection-toggle-off"}`}
          onClick={connected ? onDisconnect : onReconnect}
          title={connected ? "Disconnect" : "Reconnect"}
          aria-label={connected ? "Disconnect from server" : "Reconnect to server"}
          aria-pressed={connected}
        />
        {modelName && <span className="model-name">{modelName}</span>}
      </div>
      <div className="bottom-right">
        <div className="bottom-views">
          <button
            className="bottom-view-btn"
            onClick={onShowArchitecture}
            title="Architecture"
            aria-label="Architecture"
          >
            <i className="codicon codicon-type-hierarchy" />
          </button>
          <button
            className="bottom-view-btn"
            onClick={onShowBeads}
            title="Beads"
            aria-label="Beads"
          >
            <i className="codicon codicon-checklist" />
            {beadsReadyCount != null && beadsReadyCount > 0 && (
              <span className="beads-badge">{beadsReadyCount}</span>
            )}
          </button>
          <button
            className="bottom-view-btn"
            onClick={onShowTrace}
            title="Behind the Scenes"
            aria-label="Behind the Scenes"
          >
            <i className="codicon codicon-pulse" />
          </button>
        </div>
        <div className="mode-toggle-group" role="radiogroup" aria-label="Agent mode">
          <button
            className={permissionMode === "plan" ? "active" : ""}
            onClick={() => onSetMode("plan")}
            role="radio"
            aria-checked={permissionMode === "plan"}
            title="Plan mode: read-only exploration, no file edits"
          >
            Plan
          </button>
          <button
            className={permissionMode !== "plan" ? "active" : ""}
            onClick={() => onSetMode("normal")}
            role="radio"
            aria-checked={permissionMode !== "plan"}
            title="Act mode: full read/write access, risky tools require approval"
          >
            Act
          </button>
        </div>
      </div>
    </div>
  );
});
