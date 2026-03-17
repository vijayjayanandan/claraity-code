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
} from "../../shared/protocol";

// ============================================================================
// Extension -> Webview (postMessage wrappers)
// ============================================================================

import type { ServerMessage, SessionSummary, ReplayMessage } from "../../shared/protocol";

export type ExtensionMessage =
  | { type: "serverMessage"; payload: ServerMessage }
  | { type: "connectionStatus"; status: "connected" | "disconnected" | "reconnecting" }
  | { type: "sessionInfo"; sessionId: string; model: string; permissionMode: string; autoApproveCategories?: Record<string, boolean> }
  | { type: "sessionsList"; sessions: SessionSummary[] }
  | { type: "sessionHistory"; messages: ReplayMessage[] }
  | { type: "showSessionHistory" }
  | { type: "fileSearchResults"; files: Array<{ path: string; name: string; relativePath: string }> }
  | { type: "undoAvailable"; turnId: string; files: string[] }
  | { type: "undoComplete"; turnId: string; restoredFiles: string[] }
  | { type: "fileSelected"; path: string; name: string }
  | { type: "insertAndSend"; content: string };

// ============================================================================
// Webview -> Extension (postMessage)
// ============================================================================

import type { FileAttachment, ImageAttachment } from "../../shared/protocol";

export type WebViewMessage =
  | { type: "chatMessage"; content: string; attachments?: FileAttachment[]; images?: ImageAttachment[] }
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
  | { type: "undoTurn"; turnId: string }
  | { type: "pickFile" }
  | { type: "getJiraProfiles" }
  | { type: "saveJiraConfig"; profile: string; jira_url: string; username: string; api_token: string }
  | { type: "connectJira"; profile: string }
  | { type: "disconnectJira" };
