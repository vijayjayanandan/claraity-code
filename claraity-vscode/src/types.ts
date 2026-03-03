/**
 * Wire protocol types for ClarAIty VS Code extension.
 *
 * These match the JSON messages defined in VSCODE_INTEGRATION_DESIGN.md Section 4.
 */

// ============================================================================
// Server -> Client (WebSocket JSON)
// ============================================================================

export interface ServerMessage {
    type: string;
    [key: string]: any;
}

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

// Store notification data types
export interface ToolStateData {
    call_id: string;
    tool_name?: string;
    status: ToolStatus;
    arguments?: Record<string, any>;
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

// ============================================================================
// Client -> Server (WebSocket JSON)
// ============================================================================

export interface ChatMessagePayload {
    type: 'chat_message';
    content: string;
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
    | GetAutoApprovePayload;

// ============================================================================
// Extension <-> WebView postMessage types
// ============================================================================

export type ExtensionMessage =
    | { type: 'serverMessage'; payload: ServerMessage }
    | { type: 'connectionStatus'; status: 'connected' | 'disconnected' | 'reconnecting' }
    | { type: 'sessionInfo'; sessionId: string; model: string; permissionMode: string;
        autoApproveCategories?: { edit: boolean; execute: boolean; browser: boolean } };

export type WebViewMessage =
    | { type: 'chatMessage'; content: string }
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
    | { type: 'getAutoApprove' };
