/**
 * Types for the ClarAIty VS Code extension host.
 *
 * Shared wire protocol types are imported from the canonical source
 * at shared/protocol.ts. This file adds extension-specific types
 * (ClientMessage payloads, ExtensionMessage, WebViewMessage, assertNever).
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
  SubAgentInfo,
} from '../shared/protocol';

// Import for use in local type definitions
import type { ServerMessage, SessionSummary, ReplayMessage, FileAttachment, ImageAttachment } from '../shared/protocol';

// ============================================================================
// Client -> Server (JSON-RPC payloads)
// ============================================================================

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

export interface WebviewErrorPayload {
    type: 'webview_error';
    error: string;
    stack?: string;
    component_stack?: string;
    session_id?: string;
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
    | TerminalResultPayload
    | WebviewErrorPayload
    // MCP
    | { type: 'get_mcp_servers' }
    | { type: 'mcp_marketplace_search'; query: string; page: number }
    | { type: 'mcp_install'; server_id: string; name?: string; scope?: string }
    | { type: 'mcp_uninstall'; server_name: string }
    | { type: 'mcp_toggle_server'; server_name: string; enabled: boolean }
    | { type: 'mcp_save_tools'; server_name: string; tools: Record<string, boolean> }
    | { type: 'mcp_reconnect'; server_name: string }
    | { type: 'mcp_reload' }
    // ClarAIty Knowledge & Beads
    | { type: 'get_beads' }
    | { type: 'get_architecture' }
    | { type: 'approve_knowledge'; approved_by: string; status: string; comments: string }
    | { type: 'export_knowledge' }
    // Subagent management
    | { type: 'list_subagents' }
    | { type: 'save_subagent'; name: string; description: string; system_prompt: string; tools?: string[] | null; is_fork?: boolean }
    | { type: 'delete_subagent'; name: string }
    | { type: 'reload_subagents' }
    // Limits
    | { type: 'get_limits' }
    | { type: 'save_limits'; limits: import('../shared/protocol').LimitsData };

// ============================================================================
// Extension <-> WebView postMessage types
// ============================================================================

export type ExtensionMessage =
    | { type: 'serverMessage'; payload: ServerMessage }
    | { type: 'connectionStatus'; status: 'connected' | 'disconnected' | 'reconnecting' }
    | { type: 'sessionInfo'; sessionId: string; model: string; permissionMode: string;
        autoApproveCategories?: Record<string, boolean> }
    | { type: 'sessionsList'; sessions: SessionSummary[] }
    | { type: 'sessionHistory'; messages: ReplayMessage[] }
    | { type: 'showSessionHistory' }
    | { type: 'fileSearchResults'; files: Array<{ path: string; name: string; relativePath: string }> }
    | { type: 'undoAvailable'; turnId: string; files: string[] }
    | { type: 'undoComplete'; turnId: string; restoredFiles: string[] }
    | { type: 'fileSelected'; path: string; name: string }
    | { type: 'insertAndSend'; content: string };

export type WebViewMessage =
    | { type: 'chatMessage'; content: string; attachments?: FileAttachment[]; images?: ImageAttachment[]; systemContext?: string }
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
    | { type: 'openFile'; path: string }
    | { type: 'getJiraProfiles' }
    | { type: 'saveJiraConfig'; profile: string; jira_url: string; username: string; api_token: string }
    | { type: 'connectJira'; profile: string }
    | { type: 'disconnectJira' }
    | { type: 'webviewError'; error: string; stack?: string; componentStack?: string; sessionId?: string }
    // MCP
    | { type: 'getMcpServers' }
    | { type: 'mcpMarketplaceSearch'; query: string; page: number }
    | { type: 'mcpInstall'; serverId: string; name: string; scope?: 'project' | 'global' }
    | { type: 'mcpUninstall'; serverName: string }
    | { type: 'mcpToggleServer'; serverName: string; enabled: boolean }
    | { type: 'mcpSaveTools'; serverName: string; tools: Record<string, boolean> }
    | { type: 'mcpReconnect'; serverName: string }
    | { type: 'mcpOpenDocs'; url: string }
    | { type: 'mcpOpenConfig'; scope?: 'project' | 'global' }
    | { type: 'mcpReload' }
    // ClarAIty Knowledge & Beads
    | { type: 'getBeads' }
    | { type: 'getArchitecture' }
    | { type: 'approveKnowledge'; approvedBy: string }
    | { type: 'exportKnowledge' }
    // Subagent management
    | { type: 'listSubagents' }
    | { type: 'saveSubagent'; name: string; description: string; systemPrompt: string; tools?: string[] | null; isFork?: boolean }
    | { type: 'deleteSubagent'; name: string }
    | { type: 'forkSubagent'; name: string; basePrompt: string; baseDescription: string; baseTools?: string[] | null }
    | { type: 'openSubagentFile'; name: string }
    // Limits
    | { type: 'getLimits' }
    | { type: 'saveLimits'; limits: import('../shared/protocol').LimitsData };

// ============================================================================
// Exhaustive check helper
// ============================================================================

export function assertNever(x: never): never {
    throw new Error(`Unhandled discriminated union member: ${JSON.stringify(x)}`);
}
