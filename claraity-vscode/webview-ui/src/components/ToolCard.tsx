/**
 * Tool execution card with status badge, arguments, result, and approval buttons.
 *
 * Features:
 * - Summary prominence: if args contain a `summary` field, show it above params
 * - Collapsible parameters: long values collapsed by default, short values inline
 * - Error details: error results shown in red-tinted collapsible section
 */
import { useState, useCallback, useEffect, useRef, memo } from "react";
import type { ToolStateData, WebViewMessage } from "../types";
import { TOOL_ICONS, getPrimaryArg, getPrimaryArgKey, formatDuration } from "../utils/tools";

/** Params to hide from the collapsible params list (already shown elsewhere). */
const HIDDEN_PARAMS = new Set(["summary"]);

interface ToolCardProps {
  data: ToolStateData;
  postMessage: (msg: WebViewMessage) => void;
}

export const ToolCard = memo(function ToolCard({ data, postMessage }: ToolCardProps) {
  const [feedback, setFeedback] = useState("");
  const [showResult, setShowResult] = useState(false);
  // Optimistic status: immediately reflect user's approval/rejection click
  // so the widget updates without waiting for the backend round-trip.
  const [optimisticStatus, setOptimisticStatus] = useState<"approved" | "rejected" | null>(null);

  const toolName = data.tool_name || "tool";
  const icon = TOOL_ICONS[toolName] || "T";
  const primaryArg = toolName === "delegate_to_subagent"
    ? (typeof data.arguments?.subagent === "string" ? data.arguments.subagent : "")
    : getPrimaryArg(toolName, data.arguments);

  const summary = data.arguments?.summary;
  const hasSummary = typeof summary === "string" && summary.length > 0;

  // Use optimistic status only while server still reports awaiting_approval;
  // once the server catches up, its status takes precedence.
  const displayStatus = optimisticStatus && data.status === "awaiting_approval"
    ? optimisticStatus
    : data.status;

  const handleApprove = useCallback(() => {
    setOptimisticStatus("approved");
    postMessage({ type: "approvalResult", callId: data.call_id, approved: true });
  }, [data.call_id, postMessage]);

  const handleReject = useCallback(() => {
    setOptimisticStatus("rejected");
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

  // Build visible params: exclude summary, primary arg key (already shown inline),
  // and skip entirely for delegate_to_subagent (SubagentCard handles its own display).
  const isSubagent = toolName === "delegate_to_subagent";
  const delegateTask = isSubagent && typeof data.arguments?.task === "string"
    ? data.arguments.task : "";
  const primaryArgKey = getPrimaryArgKey(toolName, data.arguments);
  const hiddenKeys = new Set([...HIDDEN_PARAMS]);
  if (!hasSummary && primaryArgKey) hiddenKeys.add(primaryArgKey);

  const visibleParams = !isSubagent && data.arguments
    ? Object.entries(data.arguments).filter(([key]) => !hiddenKeys.has(key))
    : [];
  const hasParams = visibleParams.length > 0;

  // Unified result content: prefer data.result (actual output), fall back to
  // data.error string. For run_command errors, result contains the actual
  // stderr/stdout while error only has "Command failed with exit code N".
  const isError = displayStatus === "error";
  const resultContent = data.result != null
    ? String(data.result)
    : (isError && data.error ? data.error : null);
  const hasResult = resultContent != null;

  return (
    <div className="tool-card">
      {/* Header */}
      <div className="tool-header">
        <span className="tool-icon">{icon}</span>
        <span className="tool-name">{toolName}</span>
        {data.duration_ms != null && (
          <span className="tool-duration">{formatDuration(data.duration_ms)}</span>
        )}
        <span className={`tool-badge ${displayStatus}`}>{displayStatus}</span>
      </div>

      {/* Summary — shown prominently when present */}
      {hasSummary && (
        <div className="tool-summary">{summary}</div>
      )}

      {/* Primary arg (file path, command, etc.) — only if no summary */}
      {!hasSummary && primaryArg && (
        <div className="tool-args" title={primaryArg}>
          {primaryArg}
        </div>
      )}

      {/* Delegate task — shown for delegate_to_subagent so user can review */}
      {isSubagent && delegateTask && (
        <div className="tool-summary">{delegateTask}</div>
      )}

      {/* Collapsible parameters */}
      {hasParams && (
        <details className="tool-params-details">
          <summary>
            Parameters ({visibleParams.length})
          </summary>
          <div className="tool-params-body">
            {visibleParams.map(([key, value]) => {
              const strValue = typeof value === "string" ? value : JSON.stringify(value, null, 2);
              return (
                <div key={key} className="tool-param-row">
                  <span className="tool-param-key">{key}</span>
                  <span className="tool-param-value">{strValue}</span>
                </div>
              );
            })}
          </div>
        </details>
      )}

      {/* Approval buttons */}
      {displayStatus === "awaiting_approval" && (
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

      {/* Expandable result — same section for success and error */}
      {hasResult && (
        <details
          className="tool-result-details"
          open={showResult}
          onToggle={(e) => setShowResult((e.target as HTMLDetailsElement).open)}
        >
          <summary>Result</summary>
          <div className="result-body">{resultContent}</div>
        </details>
      )}
    </div>
  );
});

