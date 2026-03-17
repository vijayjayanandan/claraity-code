/**
 * Footer bar with connection status, model name, and Plan/Act mode toggle.
 */
import { memo } from "react";

interface BottomBarProps {
  connected: boolean;
  modelName: string;
  permissionMode: string;
  onSetMode: (mode: string) => void;
}

export const BottomBar = memo(function BottomBar({ connected, modelName, permissionMode, onSetMode }: BottomBarProps) {
  return (
    <div className="bottom-bar" role="status">
      <div className="bottom-left">
        <span className={`connection-status ${connected ? "connected" : "disconnected"}`} aria-live="polite">
          {connected ? "Connected" : "Disconnected"}
        </span>
        {modelName && <span className="model-name">{modelName}</span>}
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
  );
});
