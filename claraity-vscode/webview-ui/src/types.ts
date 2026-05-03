/**
 * Types for the ClarAIty webview.
 *
 * Shared wire protocol types are imported from the canonical source
 * at shared/protocol.ts. This file adds webview-specific types
 * (ExtensionMessage, WebViewMessage).
 */

// Re-export all shared types so existing imports work unchanged
export type {
  ToolStatus,
  ToolStateData,
  MessageData,
  MessageFinalizedData,
  SessionSummary,
  ReplayMessage,
  JiraProfile,
  FileAttachment,
  ImageAttachment,
  ServerMessage,
  McpServerInfo,
  McpToolInfo,
  McpMarketplaceEntry,
  BeadData,
  BeadsResponse,
  ArchitectureNode,
  ArchitectureEdge,
  ArchitectureResponse,
  KnowledgeApproval,
  SubAgentInfo,
  SkillInfo,
  LimitsData,
  BackgroundTaskData,
} from "../../shared/protocol";

// ============================================================================
// Extension -> Webview (postMessage wrappers)
// ============================================================================

import type { ServerMessage, SessionSummary, ReplayMessage } from "../../shared/protocol";

export type ExtensionMessage =
  | { type: "serverMessage"; payload: ServerMessage }
  | { type: "connectionStatus"; status: "connected" | "disconnected" | "reconnecting" }
  | { type: "sessionInfo"; sessionId: string; model: string; permissionMode: string; autoApproveCategories?: Record<string, boolean>; limits?: LimitsData }
  | { type: "sessionsList"; sessions: SessionSummary[] }
  | { type: "sessionHistory"; messages: ReplayMessage[] }
  | { type: "showSessionHistory" }
  | { type: "showConfig" }
  | { type: "showMcp" }
  | { type: "showSubagents" }
  | { type: "fileSearchResults"; files: Array<{ path: string; name: string; relativePath: string }> }
  | { type: "undoAvailable"; turnId: string; files: string[] }
  | { type: "undoComplete"; turnId: string; restoredFiles: string[] }
  | { type: "fileSelected"; path: string; name: string }
  | { type: "insertAndSend"; content: string }
  | { type: "enrichmentDelta"; delta: string }
  | { type: "enrichmentComplete"; original: string; enriched: string }
  | { type: "enrichmentError"; message: string }
  | { type: "traceData"; steps: TraceStepData[] }
  | { type: "traceEnabled"; enabled: boolean }
  | { type: "toolList"; tools: { name: string; description: string; parameters: Record<string, unknown> }[] }
  | { type: "toggleSearch" };

/** A single trace event from the agent pipeline .trace.jsonl file. */
export interface TraceStepData {
  id: number;
  from: string;
  to: string;
  label: string;
  type: string;
  data: string;
  durationMs: number;
  timestamp?: number;
  sections?: Record<string, string>;
  thinking?: string;
  /** Subagent name (only on steps inlined from a subagent trace) */
  _subagent?: string;
  /** True for steps that belong to a subagent's trace */
  _isSubagentStep?: boolean;
}

// ============================================================================
// Webview -> Extension (postMessage)
// ============================================================================

import type { FileAttachment, ImageAttachment, LimitsData } from "../../shared/protocol";

export type WebViewMessage =
  | { type: "chatMessage"; content: string; attachments?: FileAttachment[]; images?: ImageAttachment[]; systemContext?: string; activeSkill?: string }
  | { type: "searchFiles"; query: string }
  | { type: "approvalResult"; callId: string; approved: boolean; autoApproveFuture?: boolean; feedback?: string }
  | { type: "interrupt" }
  | { type: "ready" }
  | { type: "copyToClipboard"; text: string }
  | { type: "pauseResult"; continueWork: boolean; feedback?: string | null }
  | { type: "showDiff"; callId: string; toolName: string; arguments: Record<string, unknown> }
  | { type: "clarifyResult"; callId: string; submitted: boolean; responses: Record<string, unknown> | null }
  | { type: "planApprovalResult"; planHash: string; approved: boolean; autoAcceptEdits?: boolean; feedback?: string | null }
  | { type: "setMode"; mode: string }
  | { type: "getConfig" }
  | { type: "saveConfig"; config: Record<string, unknown> }
  | { type: "listModels"; backend: string; base_url: string; api_key: string }
  | { type: "setAutoApprove"; categories: { edit?: boolean; execute?: boolean; browser?: boolean } }
  | { type: "getAutoApprove" }
  | { type: "newSession" }
  | { type: "listSessions" }
  | { type: "resumeSession"; sessionId: string }
  | { type: "deleteSession"; sessionId: string }
  | { type: "undoTurn"; turnId: string }
  | { type: "pickFile" }
  | { type: "openFile"; path: string }
  | { type: "getJiraProfiles" }
  | { type: "saveJiraConfig"; profile: string; jira_url: string; username: string; api_token: string }
  | { type: "connectJira"; profile: string }
  | { type: "disconnectJira" }
  // MCP
  | { type: "getMcpServers" }
  | { type: "mcpMarketplaceSearch"; query: string; page: number }
  | { type: "mcpInstall"; serverId: string; name: string; scope?: "project" | "global" }
  | { type: "mcpUninstall"; serverName: string }
  | { type: "mcpToggleServer"; serverName: string; enabled: boolean }
  | { type: "mcpSaveTools"; serverName: string; tools: Record<string, boolean> }
  | { type: "mcpReconnect"; serverName: string }
  | { type: "mcpOpenDocs"; url: string }
  | { type: "mcpOpenConfig"; scope?: "project" | "global" }
  | { type: "mcpReload" }
  // ClarAIty Knowledge & Beads
  | { type: "getBeads" }
  | { type: "getArchitecture" }
  | { type: "getTrace"; sessionId: string | null }
  | { type: "getTraceEnabled" }
  | { type: "setTraceEnabled"; enabled: boolean }
  | { type: "clearTrace"; sessionId: string | null }
  | { type: "getToolList" }
  | { type: "approveKnowledge"; approvedBy: string; status: string; comments: string }
  | { type: "exportKnowledge" }
  | { type: "importKnowledge" }
  // Subagents panel
  | { type: "listSubagents" }
  | { type: "saveSubagent"; name: string; description: string; systemPrompt: string; tools?: string[] | null; isFork?: boolean }
  | { type: "deleteSubagent"; name: string }
  | { type: "forkSubagent"; name: string; baseDescription: string; basePrompt: string; baseTools?: string[] | null }
  | { type: "openSubagentFile"; name: string }
  // Limits
  | { type: "getLimits" }
  | { type: "saveLimits"; limits: LimitsData }
  // Skills
  | { type: "getSkills" }
  | { type: "createSkill"; name: string; description: string; category: string; tags: string[]; body: string }
  // Prompt Enrichment
  | { type: "enrichPrompt"; content: string; history?: Array<{ role: string; content: string }> }
  // Background tasks
  | { type: "cancelBackgroundTask"; taskId: string }
  // Turn deletion (context cleanup)
  | { type: "deleteTurn"; anchorUuid: string }
  | { type: "restoreTurn"; anchorUuid: string }
  // Server connection control
  | { type: "disconnectServer" }
  | { type: "reconnectServer" };
