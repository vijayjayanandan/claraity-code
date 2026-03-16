/**
 * Plan approval widget.
 *
 * Renders the plan excerpt as markdown with Approve / Auto-accept / Reject actions.
 */
import { useState, useMemo, useCallback } from "react";
import { renderMarkdown } from "../utils/markdown";
import type { WebViewMessage } from "../types";

interface PlanWidgetProps {
  callId: string;
  planHash: string;
  excerpt: string;
  truncated: boolean;
  planPath?: string;
  isDirector?: boolean;
  postMessage: (msg: WebViewMessage) => void;
}

export function PlanWidget({
  planHash,
  excerpt,
  truncated,
  planPath,
  isDirector,
  postMessage,
}: PlanWidgetProps) {
  const [dismissed, setDismissed] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [result, setResult] = useState<string | null>(null);

  const planHtml = useMemo(() => renderMarkdown(excerpt), [excerpt]);

  const handleApprove = useCallback(
    (autoAccept: boolean) => {
      postMessage({
        type: "planApprovalResult",
        planHash,
        approved: true,
        autoAcceptEdits: autoAccept,
      });
      setResult(autoAccept ? "[Plan approved (auto-accept edits)]" : "[Plan approved]");
      setDismissed(true);
    },
    [planHash, postMessage],
  );

  const handleReject = useCallback(() => {
    postMessage({
      type: "planApprovalResult",
      planHash,
      approved: false,
      feedback: feedback.trim() || null,
    });
    setResult("[Plan rejected]");
    setDismissed(true);
  }, [planHash, feedback, postMessage]);

  if (dismissed) {
    return (
      <div className="interactive-widget plan-widget">
        <div
          className="widget-body"
          style={{
            fontSize: 12,
            color: result?.includes("approved")
              ? "var(--vscode-testing-iconPassed)"
              : "var(--vscode-testing-iconFailed)",
          }}
        >
          {result}
        </div>
      </div>
    );
  }

  return (
    <div className="interactive-widget plan-widget">
      <div className="widget-header">{isDirector ? "Director Plan Approval" : "Plan Approval"}</div>
      <div className="widget-body">
        <div
          className="plan-content"
          dangerouslySetInnerHTML={{ __html: planHtml }}
        />
      </div>

      {truncated && (
        <div className="truncation-note">
          Plan was truncated. Full plan saved to: {planPath || "plan file"}
        </div>
      )}

      <div className="widget-actions">
        <button className="btn-primary" onClick={() => handleApprove(false)}>
          Approve
        </button>
        <button
          className="btn-primary"
          style={{ fontSize: 11 }}
          onClick={() => handleApprove(true)}
        >
          Approve + Auto-accept Edits
        </button>
        <button className="btn-danger" onClick={handleReject}>
          Reject
        </button>
      </div>

      <div style={{ padding: "6px 10px" }}>
        <textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Feedback for the agent (sent with Reject)..."
          style={{
            width: "100%",
            minHeight: 36,
            maxHeight: 80,
            resize: "vertical",
            background: "var(--vscode-input-background)",
            color: "var(--vscode-input-foreground)",
            border: "1px solid var(--vscode-input-border, transparent)",
            borderRadius: 2,
            padding: "4px 6px",
            fontFamily: "var(--vscode-font-family)",
            fontSize: "var(--vscode-font-size)",
          }}
        />
      </div>
    </div>
  );
}
