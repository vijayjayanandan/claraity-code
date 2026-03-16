/**
 * Wire protocol types shared between extension and React webview.
 *
 * IMPORTANT: These types are copied from claraity-vscode/src/types.ts.
 * Keep in sync when adding new message types.
 */

// ============================================================================
// Server -> Client (via extension -> webview postMessage)
// ============================================================================

export type ToolStatus =
  | "pending"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "running"
  | "success"
  | "error"
  | "timeout"
  | "cancelled"
  | "skipped";

export interface ToolStateData {
  call_id: string;
  tool_name?: string;
  status: ToolStatus;
  arguments?: Record<string, unknown>;
  args_summary?: string;
  requires_approval?: boolean;
  result?: unknown;
  error?: string | null;
  duration_ms?: number | null;
  message?: string | null;
  diff?: {
    original_content: string;
    modified_content: string;
  };
}

export interface MessageData {
  uuid: string;
  role: string;
  content: string;
  stream_id?: string;
}

export interface MessageFinalizedData {
  stream_id: string;
}

export interface SessionSummary {
  session_id: string;
  first_message: string;
  message_count: number;
  updated_at: string;
  git_branch?: string;
}

export interface ReplayMessage {
  role: string;
  content: string;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_call_id?: string;
  meta?: { status?: string; duration_ms?: number; tool_name?: string };
}

export interface JiraProfile {
  name: string;
  jira_url: string;
  username: string;
  enabled: boolean;
  has_token: boolean;
  is_configured: boolean;
}

// ── Server message (comes wrapped in ExtensionMessage.payload) ──

export type ServerMessage =
  // Store events
  | { type: "store"; event: "tool_state_updated"; data: ToolStateData; subagent_id?: string }
  | { type: "store"; event: "message_added"; data: MessageData; subagent_id?: string }
  | { type: "store"; event: "message_updated"; data: MessageData; subagent_id?: string }
  | { type: "store"; event: "message_finalized"; data: MessageFinalizedData; subagent_id?: string }
  // Streaming
  | { type: "stream_start" }
  | { type: "stream_end"; tool_calls?: number; elapsed_s?: number; iterations?: number; total_tokens?: number; duration_ms?: number }
  | { type: "text_delta"; content: string }
  | { type: "code_block_start"; language?: string }
  | { type: "code_block_delta"; content: string }
  | { type: "code_block_end" }
  | { type: "thinking_start" }
  | { type: "thinking_delta"; content: string }
  | { type: "thinking_end" }
  | { type: "file_read"; file_path: string; content?: string }
  | { type: "context_updated"; used: number; limit: number }
  | { type: "context_compacting" }
  | { type: "context_compacted"; old_tokens: number; new_tokens: number }
  // Interactive
  | { type: "interactive"; event: "clarify_request"; data: { uuid: string; call_id: string; questions: unknown[]; context?: string } }
  | { type: "interactive"; event: "plan_submitted"; data: { uuid: string; call_id: string; plan_hash: string; excerpt: string; truncated: boolean; plan_path?: string } }
  | { type: "interactive"; event: "director_plan_submitted"; data: { uuid: string; call_id: string; plan_hash: string; excerpt: string; truncated: boolean; plan_path?: string } }
  | { type: "interactive"; event: "permission_mode_changed"; data: { uuid?: string; old_mode?: string; new_mode: string } }
  // Pause
  | { type: "pause_prompt_start"; reason: string; reason_code: string; stats: Record<string, unknown>; pending_todos?: string[] }
  | { type: "pause_prompt_end"; continue_work: boolean; feedback?: string | null }
  // Subagent
  | { type: "subagent"; event: "registered"; data: { subagent_id: string; parent_tool_call_id: string; model_name: string; subagent_name: string; transcript_path: string } }
  | { type: "subagent"; event: "unregistered"; data: { subagent_id: string } }
  // Misc
  | { type: "session_info"; session_id: string; model_name: string; permission_mode: string; working_directory: string; auto_approve_categories?: Record<string, boolean> }
  | { type: "error"; error_type: string; user_message: string; recoverable: boolean }
  | { type: "todos_updated"; todos: unknown[] }
  | { type: "config_loaded"; [key: string]: unknown }
  | { type: "models_list"; [key: string]: unknown }
  | { type: "config_saved"; [key: string]: unknown }
  | { type: "auto_approve_changed"; categories: Record<string, boolean> }
  | { type: "sessions_list"; sessions: SessionSummary[] }
  | { type: "session_history"; messages: ReplayMessage[] }
  | { type: "jira_profiles"; profiles: JiraProfile[]; connected_profile: string | null; error?: string }
  | { type: "jira_config_saved"; success: boolean; message: string; profile?: string }
  | { type: "jira_connect_result"; success: boolean; message: string; profile?: string; tool_count?: number }
  | { type: "jira_disconnect_result"; success: boolean; message: string }
  | { type: "execute_in_terminal"; task_id: string; command: string; working_dir?: string; timeout?: number };

// ============================================================================
// Extension -> Webview (postMessage wrappers)
// ============================================================================

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

export interface FileAttachment {
  path: string;
  name: string;
}

export interface ImageAttachment {
  data: string;
  mimeType: string;
  name?: string;
}

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
