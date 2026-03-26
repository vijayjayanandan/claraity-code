/**
 * Pause/Continue interactive widget.
 *
 * Displayed when the agent pauses for user input.
 * Shows reason, stats, pending tasks, and optional feedback.
 */
import { useState, useCallback } from "react";
import type { WebViewMessage } from "../types";

interface PauseWidgetProps {
  reason: string;
  reasonCode: string;
  stats: Record<string, unknown>;
  pendingTodos?: string[];
  postMessage: (msg: WebViewMessage) => void;
}

export function PauseWidget({
  reason,
  stats,
  pendingTodos,
  postMessage,
}: PauseWidgetProps) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState("");

  const handleContinue = useCallback(() => {
    postMessage({
      type: "pauseResult",
      continueWork: true,
      feedback: feedback.trim() || null,
    });
  }, [feedback, postMessage]);

  const handleStop = useCallback(() => {
    postMessage({
      type: "pauseResult",
      continueWork: false,
      feedback: feedback.trim() || null,
    });
  }, [feedback, postMessage]);

  return (
    <div className="interactive-widget pause-widget" role="alertdialog" aria-label="Agent paused">
      <div className="widget-header">Agent Paused</div>
      <div className="widget-body">
        <div className="reason">{reason || "Agent has paused."}</div>

        {/* Stats row */}
        {stats && Object.keys(stats).length > 0 && (
          <div className="stats-row">
            {Object.entries(stats).map(([key, val]) => (
              <span key={key}>
                {key.replace(/_/g, " ")}: {String(val)}
              </span>
            ))}
          </div>
        )}

        {/* Pending todos */}
        {Array.isArray(pendingTodos) && pendingTodos.length > 0 && (
          <>
            <div style={{ fontSize: 11, color: "var(--vscode-descriptionForeground)" }}>
              Pending tasks:
            </div>
            <ol className="pending-list">
              {pendingTodos.map((todo, i) => (
                <li key={i}>{String(todo)}</li>
              ))}
            </ol>
          </>
        )}

        {/* Feedback toggle */}
        <button
          className="feedback-toggle"
          onClick={() => setShowFeedback(!showFeedback)}
        >
          {showFeedback ? "- Hide feedback" : "+ Add feedback"}
        </button>

        {showFeedback && (
          <div className="feedback-section" style={{ display: "block" }}>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Optional: add guidance for the agent..."
            />
          </div>
        )}
      </div>

      <div className="widget-actions">
        <button className="btn-primary" onClick={handleContinue}>
          Continue
        </button>
        <button className="btn-danger" onClick={handleStop}>
          Stop
        </button>
      </div>
    </div>
  );
}
