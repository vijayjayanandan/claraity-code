/**
 * Footer bar with connection status, model name, and Plan/Act mode toggle.
 */

interface BottomBarProps {
  connected: boolean;
  modelName: string;
  permissionMode: string;
  onSetMode: (mode: string) => void;
}

export function BottomBar({ connected, modelName, permissionMode, onSetMode }: BottomBarProps) {
  return (
    <div className="bottom-bar">
      <div className="bottom-left">
        <span className={`connection-status ${connected ? "connected" : "disconnected"}`}>
          {connected ? "Connected" : "Disconnected"}
        </span>
        {modelName && <span className="model-name">{modelName}</span>}
      </div>
      <div className="mode-toggle-group">
        <button
          className={permissionMode === "plan" ? "active" : ""}
          onClick={() => onSetMode("plan")}
        >
          Plan
        </button>
        <button
          className={permissionMode !== "plan" ? "active" : ""}
          onClick={() => onSetMode("normal")}
        >
          Act
        </button>
      </div>
    </div>
  );
}
