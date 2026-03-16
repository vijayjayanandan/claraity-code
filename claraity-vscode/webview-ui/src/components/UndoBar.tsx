/**
 * Undo notification bar for file modifications.
 *
 * Shows "Undo" button while available, then "Undoing..." while waiting
 * for the server's undoComplete event (driven by the `undone` prop).
 */
import { useState, useCallback } from "react";
import type { WebViewMessage } from "../types";

interface UndoBarProps {
  turnId: string;
  files: string[];
  undone: boolean;
  postMessage: (msg: WebViewMessage) => void;
}

export function UndoBar({ turnId, files, undone, postMessage }: UndoBarProps) {
  const [undoing, setUndoing] = useState(false);

  const names = files.map((f) => f.split(/[/\\]/).pop() || f);

  const handleUndo = useCallback(() => {
    setUndoing(true);
    postMessage({ type: "undoTurn", turnId });
  }, [turnId, postMessage]);

  return (
    <div className={`undo-bar ${undone ? "undone" : ""}`}>
      <span className="undo-info" title={files.join("\n")}>
        {undone
          ? `${files.length} file(s) restored`
          : `${files.length} file${files.length !== 1 ? "s" : ""} modified: ${names.join(", ")}`}
      </span>
      {!undone && (
        <button
          className="undo-btn"
          onClick={handleUndo}
          disabled={undoing}
          title={`Revert ${files.length} file(s) to their state before this turn`}
        >
          {undoing ? "Undoing..." : "Undo"}
        </button>
      )}
    </div>
  );
}
