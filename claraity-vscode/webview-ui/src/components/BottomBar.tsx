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
  beadsReadyCount?: number;
}

export const BottomBar = memo(function BottomBar({
  connected,
  modelName,
  permissionMode,
  onSetMode,
  onShowArchitecture,
  onShowBeads,
  beadsReadyCount,
}: BottomBarProps) {
  return (
    <div className="bottom-bar" role="status">
      <div className="bottom-left">
        <span className={`connection-status ${connected ? "connected" : "disconnected"}`} aria-live="polite">
          {connected ? "Connected" : "Disconnected"}
        </span>
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
        </div>
        <div className="mode-toggle-group" role="radiogroup" aria-label="Agent mode">
          <button
            className={permissionMode === "plan" ? "active" : ""}
            onClick={() => onSetMode("plan")}
            role="radio"
            aria-checked={permissionMode === "plan"}
          >
            Plan
          </button>
          <button
            className={permissionMode !== "plan" ? "active" : ""}
            onClick={() => onSetMode("normal")}
            role="radio"
            aria-checked={permissionMode !== "plan"}
          >
            Act
          </button>
        </div>
      </div>
    </div>
  );
});
