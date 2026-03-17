/**
 * Promoted subagent approval widget.
 *
 * When a subagent tool reaches awaiting_approval status, this widget
 * is rendered at conversation level (outside the collapsed subagent card)
 * so the user can approve/reject without expanding the subagent details.
 */
import { useState } from "react";
import type { ToolStateData, WebViewMessage } from "../types";
import { getPrimaryArg } from "../utils/tools";

interface SubagentApprovalWidgetProps {
  callId: string;
  data: ToolStateData;
  subagentName: string;
  postMessage: (msg: WebViewMessage) => void;
  onDismiss: () => void;
}

export function SubagentApprovalWidget({
  callId,
  data,
  subagentName,
  postMessage,
  onDismiss,
}: SubagentApprovalWidgetProps) {
  const [feedback, setFeedback] = useState("");

  const toolName = data.tool_name ?? "tool";
  const primaryArg = getPrimaryArg(toolName, data.arguments);

  const handleShowDiff = () => {
    if ((toolName === "write_file" || toolName === "edit_file" || toolName === "append_to_file") && data.arguments) {
      postMessage({
        type: "showDiff",
        callId,
        toolName,
        arguments: data.arguments as Record<string, unknown>,
      });
    }
  };

  const handleAccept = () => {
    postMessage({ type: "approvalResult", callId, approved: true });
    onDismiss();
  };

  const handleReject = () => {
    postMessage({
      type: "approvalResult",
      callId,
      approved: false,
      feedback: feedback.trim() || undefined,
    });
    onDismiss();
  };

  return (
    <div className="interactive-widget subagent-approval-widget">
      <div className="widget-header">
        Approval: {subagentName}
      </div>
      <div className="widget-body">
        {toolName}{primaryArg ? ` \u2014 ${primaryArg}` : ""}
      </div>
      <div className="widget-actions">
        <button className="btn-primary" onClick={handleAccept}>Accept</button>
        {(toolName === "write_file" || toolName === "edit_file" || toolName === "append_to_file") && data.arguments && (
          <button className="btn-secondary" onClick={handleShowDiff}>View Diff</button>
        )}
        <button className="btn-danger" onClick={handleReject}>Reject</button>
      </div>
      <div style={{ padding: "6px 10px" }}>
        <textarea
          className="feedback-input"
          placeholder="Feedback for the agent (sent with Reject)..."
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
        />
      </div>
    </div>
  );
}
