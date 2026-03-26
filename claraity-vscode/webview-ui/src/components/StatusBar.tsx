/**
 * Top header bar with ClarAIty title and toolbar icons.
 */
import { memo } from "react";

interface StatusBarProps {
  onNewChat: () => void;
  onShowHistory: () => void;
  onShowConfig: () => void;
  onShowJira: () => void;
  onShowMcp: () => void;
  onShowSubagents: () => void;
}

export const StatusBar = memo(function StatusBar({ onNewChat, onShowHistory, onShowConfig, onShowJira, onShowMcp, onShowSubagents }: StatusBarProps) {
  return (
    <div className="status-bar" role="toolbar" aria-label="ClarAIty toolbar">
      <span className="title">ClarAIty</span>
      <div className="toolbar-icons">
        <button className="toolbar-icon" onClick={onNewChat} title="New Chat" aria-label="New Chat">
          <i className="codicon codicon-add" />
        </button>
        <button className="toolbar-icon" onClick={onShowHistory} title="Session History" aria-label="Session History">
          <i className="codicon codicon-history" />
        </button>
        <button className="toolbar-icon" onClick={onShowSubagents} title="Subagents" aria-label="Subagents">
          <i className="codicon codicon-robot" />
        </button>
        <button className="toolbar-icon" onClick={onShowMcp} title="MCP Servers" aria-label="MCP Servers">
          <i className="codicon codicon-extensions" />
        </button>
        <button className="toolbar-icon" onClick={onShowJira} title="Jira Integration" aria-label="Jira Integration">
          <i className="codicon codicon-plug" />
        </button>
        <button className="toolbar-icon" onClick={onShowConfig} title="LLM Configuration" aria-label="LLM Configuration">
          <i className="codicon codicon-gear" />
        </button>
      </div>
    </div>
  );
});
