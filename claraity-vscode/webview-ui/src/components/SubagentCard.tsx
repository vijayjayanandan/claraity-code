/**
 * Subagent card.
 *
 * Wraps the delegate_to_subagent tool card, showing:
 * - Live status line: "current_tool — arg | N tools | Xs" (ticks every second while active)
 * - Final status: "Completed | N tools | Xs" on unregistered
 * - Collapsible <details> containing nested tool cards
 * - Auto-expands when any child tool needs approval
 */
import { useState, useEffect } from "react";
import type { SubagentInfo } from "../state/reducer";
import type { ToolStateData, WebViewMessage } from "../types";
import { ToolCard } from "./ToolCard";
import { getPrimaryArg } from "../utils/tools";

interface SubagentCardProps {
  info: SubagentInfo;
  toolCards: ToolStateData[];
  postMessage: (msg: WebViewMessage) => void;
}

export function SubagentCard({ info, toolCards, postMessage }: SubagentCardProps) {
  const [elapsed, setElapsed] = useState(
    info.finalElapsedMs != null
      ? Math.round(info.finalElapsedMs / 1000)
      : Math.round((Date.now() - info.startTime) / 1000),
  );

  // Tick the elapsed timer while the subagent is active
  useEffect(() => {
    if (!info.active) return;
    const interval = setInterval(() => {
      setElapsed(Math.round((Date.now() - info.startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [info.active, info.startTime]);

  // Sync elapsed when finalElapsedMs arrives (on unregistered)
  useEffect(() => {
    if (info.finalElapsedMs != null) {
      setElapsed(Math.round(info.finalElapsedMs / 1000));
    }
  }, [info.finalElapsedMs]);

  // Auto-expand when a child tool is awaiting approval
  const hasAwaitingApproval = toolCards.some((t) => t.status === "awaiting_approval");

  // Current running tool for status line
  const currentTool = toolCards.find((t) => t.status === "running" || t.status === "pending");
  const currentToolName = currentTool?.tool_name ?? "";
  const currentToolArg = currentTool
    ? getPrimaryArg(currentTool.tool_name ?? "", currentTool.arguments)
    : "";

  const statusText = info.active
    ? (currentToolName
        ? `${currentToolName}${currentToolArg ? ` \u2014 ${currentToolArg}` : ""}`
        : "Starting\u2026")
    : "Completed";
  const statsText = `${info.toolCount > 0 ? `${info.toolCount} tools | ` : ""}${elapsed}s`;

  return (
    <div className={`tool-card${info.active ? " subagent-active" : ""}`}>
      <details open={info.active || hasAwaitingApproval}>
        <summary className="tool-header" style={{ cursor: "pointer" }} aria-expanded={info.active || hasAwaitingApproval}>
          <span className="tool-icon">SA</span>
          <span className="tool-name">
            {info.subagentName}
            {info.modelName ? ` (${info.modelName})` : ""}
            {!info.active && info.toolCount > 0 ? ` | ${info.toolCount} tools` : ""}
          </span>
          <span className={`tool-badge ${info.active ? "running" : "success"}`}>
            {info.active ? "running" : "done"}
          </span>
        </summary>

        <div style={{ padding: "0 4px 4px" }}>
          {/* Subagent text messages (GAP 5) */}
          {info.messages && info.messages.map((text, i) => (
            <div key={`sa-msg-${i}`} className="subagent-text" style={{ padding: "4px 8px", opacity: 0.85, fontSize: "0.9em" }}>
              {text}
            </div>
          ))}
          {toolCards.map((tc) => (
            <ToolCard key={tc.call_id} data={tc} postMessage={postMessage} />
          ))}
        </div>
      </details>

      {/* Status line — visible whether expanded or collapsed */}
      <div className="subagent-status">
        <span className="sa-current-tool">{statusText}</span>
        <span className="sa-stats">{statsText}</span>
      </div>
    </div>
  );
}
