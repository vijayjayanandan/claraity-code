/**
 * Tool execution card with status badge, arguments, result, and approval buttons.
 */
import { useState, useCallback, useEffect, useRef, memo } from "react";
import type { ToolStateData, WebViewMessage } from "../types";
import { TOOL_ICONS, getPrimaryArg, formatDuration } from "../utils/tools";

interface ToolCardProps {
  data: ToolStateData;
  postMessage: (msg: WebViewMessage) => void;
}

export const ToolCard = memo(function ToolCard({ data, postMessage }: ToolCardProps) {
  const [feedback, setFeedback] = useState("");
  const [showResult, setShowResult] = useState(false);

  const toolName = data.tool_name || "tool";
  const icon = TOOL_ICONS[toolName] || "T";
  const primaryArg = toolName === "delegate_to_subagent"
    ? ""
    : getPrimaryArg(toolName, data.arguments);

  const handleApprove = useCallback(() => {
    postMessage({ type: "approvalResult", callId: data.call_id, approved: true });
  }, [data.call_id, postMessage]);

  const handleReject = useCallback(() => {
    postMessage({
      type: "approvalResult",
      callId: data.call_id,
      approved: false,
      feedback: feedback.trim() || undefined,
    });
  }, [data.call_id, feedback, postMessage]);

  const handleShowDiff = useCallback(() => {
    if (data.arguments && (toolName === "write_file" || toolName === "edit_file" || toolName === "append_to_file")) {
      postMessage({
        type: "showDiff",
        callId: data.call_id,
        toolName,
        arguments: data.arguments,
      });
    }
  }, [data.call_id, data.arguments, toolName, postMessage]);

  // Auto-open diff when a file tool reaches awaiting_approval.
  // Uses a fire-once ref instead of transition detection to avoid
  // React 18 batching race: if PENDING and AWAITING_APPROVAL dispatches
  // are batched, the component mounts with status already at
  // "awaiting_approval" and no transition is ever observed.
  const didAutoOpenRef = useRef(false);
  useEffect(() => {
    if (didAutoOpenRef.current) return;
    const isFileTool =
      toolName === "write_file" ||
      toolName === "edit_file" ||
      toolName === "append_to_file";
    if (data.status === "awaiting_approval" && isFileTool && data.arguments) {
      handleShowDiff();
      didAutoOpenRef.current = true;
    }
  }, [data.status, toolName, data.arguments, handleShowDiff]);

  return (
    <div className="tool-card">
      {/* Header */}
      <div className="tool-header">
        <span className="tool-icon">{icon}</span>
        <span className="tool-name">{toolName}</span>
        {data.duration_ms != null && (
          <span className="tool-duration">{formatDuration(data.duration_ms)}</span>
        )}
        <span className={`tool-badge ${data.status}`}>{data.status}</span>
      </div>

      {/* Arguments summary */}
      {primaryArg && (
        <div className="tool-args" title={primaryArg}>
          {primaryArg}
        </div>
      )}

      {/* Approval buttons */}
      {data.status === "awaiting_approval" && (
        <div className="approval-section">
          <div className="approval-buttons" role="group" aria-label="Tool approval actions">
            <button className="btn-approve" onClick={handleApprove}>Accept</button>
            {(toolName === "write_file" || toolName === "edit_file" || toolName === "append_to_file") && data.arguments && (
              <button className="btn-secondary" onClick={handleShowDiff}>View Diff</button>
            )}
            <button className="btn-reject" onClick={handleReject}>Reject</button>
          </div>
          <div style={{ padding: "6px 10px" }}>
            <textarea
              className="tool-feedback-textarea"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Feedback for the agent (sent with Reject)..."
            />
          </div>
        </div>
      )}

      {/* Expandable result */}
      {data.result != null && (
        <details
          className="tool-result-details"
          open={showResult}
          onToggle={(e) => setShowResult((e.target as HTMLDetailsElement).open)}
        >
          <summary>Result</summary>
          <div className="result-body">{String(data.result)}</div>
        </details>
      )}
    </div>
  );
});
