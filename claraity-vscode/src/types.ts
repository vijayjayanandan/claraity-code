/**
 * Wire protocol types for ClarAIty VS Code extension.
 *
 * These match the JSON messages defined in VSCODE_INTEGRATION_DESIGN.md Section 4.
 *
 * PARITY RULE: The ServerMessage discriminated union must cover every event type
 * emitted by serializers.py, ws_protocol.py, and subagent_bridge.py. When you add
 * a new event type on the Python side, add it here too — TypeScript will then error
 * in any switch/case that doesn't handle it (with exhaustive checking).
 */

// ============================================================================
// Server -> Client (WebSocket JSON) — Discriminated Union
// ============================================================================

// Tool execution lifecycle states (canonical: src/core/tool_status.py)
export type ToolStatus =
    | 'pending'
    | 'awaiting_approval'
    | 'approved'
    | 'rejected'
    | 'running'
    | 'success'
    | 'error'
    | 'timeout'
    | 'cancelled'
    | 'skipped';

// ── Data shapes ──

export interface ToolStateData {
    call_id: string;
    tool_name?: string;
    status: ToolStatus;
    arguments?: Record<string, any>;
    args_summary?: string;
    requires_approval?: boolean;
    result?: any;
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

// ── Store events (type: 'store') ──

export type StoreEvent =
    | { type: 'store'; event: 'tool_state_updated'; data: ToolStateData; subagent_id?: string }
    | { type: 'store'; event: 'message_added'; data: MessageData; subagent_id?: string }
    | { type: 'store'; event: 'message_updated'; data: MessageData; subagent_id?: string }
    | { type: 'store'; event: 'message_finalized'; data: MessageFinalizedData; subagent_id?: string };

// ── Streaming events ──

export type StreamEvent =
    | { type: 'stream_start' }
    | { type: 'stream_end'; tool_calls?: number; elapsed_s?: number; iterations?: number; total_tokens?: number; duration_ms?: number }
    | { type: 'text_delta'; content: string }
    | { type: 'code_block_start'; language?: string }
    | { type: 'code_block_delta'; content: string }
    | { type: 'code_block_end' }
    | { type: 'thinking_start' }
    | { type: 'thinking_delta'; content: string }
    | { type: 'thinking_end' }
    | { type: 'file_read'; file_path: string; content?: string }
    | { type: 'context_updated'; used: number; limit: number }
    | { type: 'context_compacting' }
    | { type: 'context_compacted'; old_tokens: number; new_tokens: number };

// ── Interactive events ──

export type InteractiveEvent =
    | { type: 'interactive'; event: 'clarify_request'; data: { uuid: string; call_id: string; questions: any[]; context?: string } }
    | { type: 'interactive'; event: 'plan_submitted'; data: { uuid: string; call_id: string; plan_hash: string; excerpt: string; truncated: boolean; plan_path?: string } }
    | { type: 'interactive'; event: 'director_plan_submitted'; data: { uuid: string; call_id: string; plan_hash: string; excerpt: string; truncated: boolean; plan_path?: string } }
    | { type: 'interactive'; event: 'permission_mode_changed'; data: { uuid?: string; old_mode?: string; new_mode: string } };

// ── Pause events ──

export type PauseEvent =
    | { type: 'pause_prompt_start'; reason: string; reason_code: string; stats: Record<string, any>; pending_todos?: string[] }
    | { type: 'pause_prompt_end'; continue_work: boolean; feedback?: string | null };

// ── Subagent lifecycle events ──

export type SubagentEvent =
    | { type: 'subagent'; event: 'registered'; data: { subagent_id: string; parent_tool_call_id: string; model_name: string; subagent_name: string; transcript_path: string } }
    | { type: 'subagent'; event: 'unregistered'; data: { subagent_id: string } };

// ── Session history types ──

export interface SessionSummary {
    session_id: string;
    first_message: string;     // First user message (title)
    message_count: number;
    updated_at: string;        // ISO datetime
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

// ── Misc server events ──

// ── Jira integration types ──

export interface JiraProfile {
    name: string;
    jira_url: string;
    username: string;
    enabled: boolean;
    has_token: boolean;
    is_configured: boolean;
}

export type MiscEvent =
    | { type: 'session_info'; session_id: string; model_name: string; permission_mode: string; working_directory: string; auto_approve_categories?: Record<string, boolean> }
    | { type: 'error'; error_type: string; user_message: string; recoverable: boolean }
    | { type: 'todos_updated'; todos: any[] }
    | { type: 'config_loaded'; [key: string]: any }
    | { type: 'models_list'; [key: string]: any }
    | { type: 'config_saved'; [key: string]: any }
    | { type: 'auto_approve_changed'; categories: Record<string, boolean> }
    | { type: 'sessions_list'; sessions: SessionSummary[] }
    | { type: 'session_history'; messages: ReplayMessage[] }
    | { type: 'jira_profiles'; profiles: JiraProfile[]; connected_profile: string | null; error?: string }
    | { type: 'jira_config_saved'; success: boolean; message: string; profile?: string }
    | { type: 'jira_connect_result'; success: boolean; message: string; profile?: string; tool_count?: number }
    | { type: 'jira_disconnect_result'; success: boolean; message: string }
    | { type: 'execute_in_terminal'; task_id: string; command: string; working_dir?: string; timeout?: number };

// ── Union of all server messages ──

export type ServerMessage =
    | StoreEvent
    | StreamEvent
    | InteractiveEvent
    | PauseEvent
    | SubagentEvent
    | MiscEvent;

// ============================================================================
// Client -> Server (WebSocket JSON)
// ============================================================================

// ── File attachment for @file context mentions ──

export interface FileAttachment {
    path: string;       // Absolute file path
    name: string;       // Display name (basename)
}

export interface ImageAttachment {
    data: string;       // Base64-encoded image data (without data URL prefix)
    mimeType: string;   // e.g., 'image/png', 'image/jpeg'
    name?: string;      // Optional filename
}

export interface ChatMessagePayload {
    type: 'chat_message';
    content: string;
    attachments?: FileAttachment[];
    images?: ImageAttachment[];
}

export interface ApprovalResultPayload {
    type: 'approval_result';
    call_id: string;
    approved: boolean;
    auto_approve_future?: boolean;
    feedback?: string | null;
}

export interface InterruptPayload {
    type: 'interrupt';
}

export interface PauseResultPayload {
    type: 'pause_result';
    continue_work: boolean;
    feedback?: string | null;
}

export interface ClarifyResultPayload {
    type: 'clarify_result';
    call_id: string;
    submitted: boolean;
    responses: Record<string, any> | null;
    chat_instead: boolean;
    chat_message: string | null;
}

export interface PlanApprovalResultPayload {
    type: 'plan_approval_result';
    plan_hash: string;
    approved: boolean;
    auto_accept_edits: boolean;
    feedback?: string | null;
}

export interface SetModePayload {
    type: 'set_mode';
    mode: string;
}

export interface GetConfigPayload {
    type: 'get_config';
}

export interface SaveConfigPayload {
    type: 'save_config';
    config: Record<string, any>;
}

export interface ListModelsPayload {
    type: 'list_models';
    backend: string;
    base_url: string;
    api_key: string;
}

export interface SetAutoApprovePayload {
    type: 'set_auto_approve';
    categories: { edit?: boolean; execute?: boolean; browser?: boolean };
}

export interface GetAutoApprovePayload {
    type: 'get_auto_approve';
}

export interface NewSessionPayload {
    type: 'new_session';
}

export interface ListSessionsPayload {
    type: 'list_sessions';
    limit?: number;
}

export interface ResumeSessionPayload {
    type: 'resume_session';
    session_id: string;
}

export interface GetJiraProfilesPayload {
    type: 'get_jira_profiles';
}

export interface SaveJiraConfigPayload {
    type: 'save_jira_config';
    profile: string;
    jira_url: string;
    username: string;
    api_token: string;
}

export interface ConnectJiraPayload {
    type: 'connect_jira';
    profile: string;
}

export interface DisconnectJiraPayload {
    type: 'disconnect_jira';
}

export interface TerminalResultPayload {
    type: 'terminal_result';
    task_id: string;
    exit_code: number;
    output: string;
    error?: string;
}

export type ClientMessage =
    | ChatMessagePayload
    | ApprovalResultPayload
    | InterruptPayload
    | PauseResultPayload
    | ClarifyResultPayload
    | PlanApprovalResultPayload
    | SetModePayload
    | GetConfigPayload
    | SaveConfigPayload
    | ListModelsPayload
    | SetAutoApprovePayload
    | GetAutoApprovePayload
    | NewSessionPayload
    | ListSessionsPayload
    | ResumeSessionPayload
    | GetJiraProfilesPayload
    | SaveJiraConfigPayload
    | ConnectJiraPayload
    | DisconnectJiraPayload
    | TerminalResultPayload;

// ============================================================================
// Extension <-> WebView postMessage types
// ============================================================================

export type ExtensionMessage =
    | { type: 'serverMessage'; payload: ServerMessage }
    | { type: 'connectionStatus'; status: 'connected' | 'disconnected' | 'reconnecting' }
    | { type: 'sessionInfo'; sessionId: string; model: string; permissionMode: string;
        autoApproveCategories?: { edit: boolean; execute: boolean; browser: boolean } }
    | { type: 'sessionsList'; sessions: SessionSummary[] }
    | { type: 'sessionHistory'; messages: ReplayMessage[] }
    | { type: 'fileSearchResults'; files: Array<{ path: string; name: string; relativePath: string }> }
    | { type: 'undoAvailable'; turnId: string; files: string[] }
    | { type: 'undoComplete'; turnId: string; restoredFiles: string[] }
    | { type: 'insertAndSend'; content: string };

export type WebViewMessage =
    | { type: 'chatMessage'; content: string; attachments?: FileAttachment[]; images?: ImageAttachment[] }
    | { type: 'searchFiles'; query: string }
    | { type: 'approvalResult'; callId: string; approved: boolean; autoApproveFuture?: boolean; feedback?: string }
    | { type: 'interrupt' }
    | { type: 'ready' }
    | { type: 'copyToClipboard'; text: string }
    | { type: 'pauseResult'; continueWork: boolean; feedback?: string | null }
    | { type: 'showDiff'; callId: string; toolName: string; arguments: Record<string, any> }
    | { type: 'clarifyResult'; callId: string; submitted: boolean; responses: Record<string, any> | null }
    | { type: 'planApprovalResult'; planHash: string; approved: boolean; autoAcceptEdits?: boolean; feedback?: string | null }
    | { type: 'setMode'; mode: string }
    | { type: 'getConfig' }
    | { type: 'saveConfig'; config: Record<string, any> }
    | { type: 'listModels'; backend: string; base_url: string; api_key: string }
    | { type: 'setAutoApprove'; categories: { edit?: boolean; execute?: boolean; browser?: boolean } }
    | { type: 'getAutoApprove' }
    | { type: 'newSession' }
    | { type: 'listSessions' }
    | { type: 'resumeSession'; sessionId: string }
    | { type: 'undoTurn'; turnId: string }
    | { type: 'pickFile' }
    | { type: 'getJiraProfiles' }
    | { type: 'saveJiraConfig'; profile: string; jira_url: string; username: string; api_token: string }
    | { type: 'connectJira'; profile: string }
    | { type: 'disconnectJira' };

// ============================================================================
// Exhaustive check helper — use in default case of switch statements
// ============================================================================

/**
 * Use in the default case of a switch to ensure all union members are handled.
 * TypeScript will error if a case is missing.
 *
 * Example:
 *   switch (event.type) {
 *     case 'stream_start': ...; break;
 *     case 'text_delta': ...; break;
 *     // ... all cases ...
 *     default: assertNever(event);
 *   }
 */
export function assertNever(x: never): never {
    throw new Error(`Unhandled discriminated union member: ${JSON.stringify(x)}`);
}
