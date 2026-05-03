/**
 * Canonical wire protocol types for ClarAIty.
 *
 * SINGLE SOURCE OF TRUTH — imported by both:
 *   - Extension host (src/types.ts)
 *   - React webview (webview-ui/src/types.ts)
 *
 * When adding a new server event type, add it here. Both sides
 * will pick it up automatically.
 */

// ============================================================================
// Data shapes
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
  /** Prompt tokens from the subagent's most recent LLM call. */
  context_tokens?: number;
  /** 1-based line number where the edit starts (set on success for file-editing tools). */
  edit_line?: number;
  /** Number of lines in the replacement text. */
  edit_line_count?: number;
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

export interface TurnDeletedData {
  anchor_uuid: string;
  affected_uuids: string[];
  count: number;
  preview: string;
}

export interface TurnRestoredData {
  anchor_uuid: string;
  affected_uuids: string[];
  count: number;
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
  uuid?: string;
  deleted?: boolean;
  is_compact_summary?: boolean;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_call_id?: string;
  meta?: { status?: string; duration_ms?: number; tool_name?: string };
  /** Image attachments extracted from multimodal content (for replay). */
  images?: ImageAttachment[];
  /** File attachments extracted from multimodal content (for replay). */
  attachments?: FileAttachment[];
}

export interface JiraProfile {
  name: string;
  jira_url: string;
  username: string;
  enabled: boolean;
  has_token: boolean;
  is_configured: boolean;
}

export interface FileAttachment {
  path: string;
  name: string;
  /** Inline content for pasted/dropped files that have no filesystem path. */
  content?: string;
}

export interface ImageAttachment {
  data: string;
  mimeType: string;
  name?: string;
}

// ============================================================================
// ClarAIty Knowledge & Beads data shapes
// ============================================================================

export interface BeadNote {
  content: string;
  author: string;
  created_at: string;
}

export interface BeadData {
  id: string;
  title: string;
  description: string | null;
  status: "open" | "in_progress" | "blocked" | "deferred" | "closed" | "pinned" | "hooked";
  priority: number;
  tags: string[];
  parent_id: string | null;
  created_at: string;
  closed_at: string | null;
  summary: string | null;
  blockers: Array<{ id: string; title: string; status: string; dep_type?: string }>;
  // New fields from schema expansion
  issue_type: string;           // bug, feature, task, epic, chore, decision
  assignee: string | null;
  notes: BeadNote[];            // Latest 2-3 notes for context
  external_ref: string | null;  // e.g., jira-CC-42
  due_at: string | null;
  defer_until: string | null;
  estimated_minutes: number | null;
  close_reason: string | null;
  last_activity: string | null;
  design: string | null;
  acceptance_criteria: string | null;
}

export interface BeadsResponse {
  ready: BeadData[];
  in_progress: BeadData[];
  blocked: BeadData[];
  deferred?: BeadData[];   // Optional: older servers may not send
  pinned?: BeadData[];     // Optional: older servers may not send
  closed: BeadData[];
  stats: {
    total: number;
    open: number;
    in_progress: number;
    blocked?: number;      // Optional: older servers may not send
    deferred?: number;     // Optional: older servers may not send
    closed: number;
    dependencies: number;
  };
}

export interface ArchitectureNode {
  id: string;
  type: string;
  layer: string;
  name: string;
  description: string | null;
  file_path: string | null;
  properties: Record<string, unknown>;
}

export interface ArchitectureEdge {
  id: string;
  from_id: string;
  to_id: string;
  type: string;
  label: string | null;
}

export interface KnowledgeApproval {
  status: "draft" | "approved" | "rejected";
  approved_at: string | null;
  approved_by: string | null;
  version: number;
  comments: string | null;
}

export interface ScanInfo {
  scanned_at: string | null;
  scanned_by: string | null;
  repo_name: string | null;
  total_files: number | null;
}

export interface ArchitectureResponse {
  nodes: ArchitectureNode[];
  edges: ArchitectureEdge[];
  overview: string;
  stats: { node_count: number; edge_count: number; module_count: number };
  approval: KnowledgeApproval;
  scan: ScanInfo;
}

// ============================================================================
// Background task data shapes
// ============================================================================

export interface BackgroundTaskData {
  task_id: string;
  command: string;
  description: string;
  status: "running" | "completed" | "failed" | "timed_out" | "cancelled";
  elapsed_seconds: number;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
}

// ============================================================================
// Subagent data shapes
// ============================================================================

export interface SubAgentInfo {
  name: string;
  description: string;
  system_prompt: string;
  tools: string[] | null;
  /** Where the config came from. */
  source: "builtin" | "project" | "user";
  /** Absolute path to the .md file; null for built-ins (Python constants). */
  config_path: string | null;
}

// ============================================================================
// Skill data shapes
// ============================================================================

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  arguments?: string[];
  argumentHint?: string;
}

// ============================================================================
// Limits data shapes
// ============================================================================

export interface LimitsData {
  iteration_limit_enabled: boolean;
  max_iterations: number;
}

// ============================================================================
// MCP data shapes
// ============================================================================

export interface McpToolInfo {
  name: string;
  enabled: boolean;
  description?: string;
}

export interface McpServerInfo {
  name: string;
  transport: string;
  enabled: boolean;
  connected: boolean;
  toolCount: number;
  tools: McpToolInfo[];
  command?: string;
  args?: string[];
  serverUrl?: string;
  error?: string;
  docsUrl?: string;
  scope: "project" | "global";
}

export interface McpMarketplaceEntry {
  id: string;
  name: string;
  author: string;
  description: string;
  tags: string[];
  iconUrl: string;
  useCount: number;
  verified: boolean;
  isRemote: boolean;
  envVars: string[];
  source: string;
}

// ============================================================================
// Server -> Client messages (discriminated union)
// ============================================================================

export type ServerMessage =
  // Store events
  | { type: "store"; event: "tool_state_updated"; data: ToolStateData; subagent_id?: string }
  | { type: "store"; event: "message_added"; data: MessageData; subagent_id?: string }
  | { type: "store"; event: "message_updated"; data: MessageData; subagent_id?: string }
  | { type: "store"; event: "message_finalized"; data: MessageFinalizedData; subagent_id?: string }
  | { type: "store"; event: "turn_deleted"; data: TurnDeletedData }
  | { type: "store"; event: "turn_restored"; data: TurnRestoredData }
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
  | { type: "context_updated"; used: number; limit: number; iteration?: number }
  | { type: "context_compacting"; tokens_before: number }
  | { type: "context_compacted"; messages_removed: number; tokens_before: number; tokens_after: number }
  // Interactive
  | { type: "interactive"; event: "clarify_request"; data: { uuid: string; call_id: string; questions: unknown[]; context?: string } }
  | { type: "interactive"; event: "plan_submitted"; data: { uuid: string; call_id: string; plan_hash: string; excerpt: string; truncated: boolean; plan_path?: string } }
  | { type: "interactive"; event: "permission_mode_changed"; data: { uuid?: string; old_mode?: string; new_mode: string } }
  // Pause
  | { type: "pause_prompt_start"; reason: string; reason_code: string; stats: Record<string, unknown>; pending_todos?: string[] }
  | { type: "pause_prompt_end"; continue_work: boolean; feedback?: string | null }
  // Subagent
  | { type: "subagent"; event: "registered"; data: { subagent_id: string; parent_tool_call_id: string; model_name: string; subagent_name: string; transcript_path: string; context_window?: number } }
  | { type: "subagent"; event: "unregistered"; data: { subagent_id: string } }
  // Misc
  | { type: "session_info"; session_id: string; model_name: string; permission_mode: string; working_directory: string; auto_approve_categories?: Record<string, boolean>; limits?: LimitsData }
  | { type: "error"; error_type: string; user_message: string; recoverable: boolean }
  | { type: "todos_updated"; todos: unknown[] }
  | { type: "background_tasks_updated"; tasks: BackgroundTaskData[] }
  | { type: "config_loaded"; [key: string]: unknown }
  | { type: "models_list"; [key: string]: unknown }
  | { type: "config_saved"; [key: string]: unknown }
  | { type: "auto_approve_changed"; categories: Record<string, boolean> }
  | { type: "limits_loaded"; limits: LimitsData }
  | { type: "limits_saved"; success: boolean; message: string; limits?: LimitsData }
  | { type: "sessions_list"; sessions: SessionSummary[] }
  | { type: "session_history"; messages: ReplayMessage[] }
  | { type: "session_deleted"; session_id: string; success: boolean; message?: string }
  | { type: "jira_profiles"; profiles: JiraProfile[]; connected_profile: string | null; error?: string }
  | { type: "jira_config_saved"; success: boolean; message: string; profile?: string }
  | { type: "jira_connect_result"; success: boolean; message: string; profile?: string; tool_count?: number }
  | { type: "jira_disconnect_result"; success: boolean; message: string }
  | { type: "execute_in_terminal"; task_id: string; command: string; working_dir?: string; timeout?: number }
  // MCP
  | { type: "mcp_servers_list"; servers: McpServerInfo[]; notification?: { message: string; success: boolean } }
  | { type: "mcp_marketplace_results"; entries: McpMarketplaceEntry[]; totalCount: number; page: number; pageSize: number; hasNext: boolean }
  | { type: "mcp_install_result"; status: string; server?: string; toolCount?: number; message?: string; envVarsRequired?: string[]; envVarsMissing?: string[] }
  | { type: "mcp_uninstall_result"; status: string; server?: string; message?: string }
  // ClarAIty Knowledge & Beads
  | { type: "beads_data"; data: BeadsResponse }
  | { type: "architecture_data"; data: ArchitectureResponse }
  | { type: "knowledge_approved"; data: KnowledgeApproval }
  // Subagent management
  | { type: "subagents_list"; subagents: SubAgentInfo[]; available_tools: string[] }
  | { type: "subagent_saved"; success: boolean; name: string; message: string }
  | { type: "subagent_deleted"; success: boolean; name: string; message: string }
  // Skills
  | { type: "skills_list"; skills: SkillInfo[] }
  | { type: "skill_saved"; success: boolean; name: string; message: string }
  // Prompt Enrichment
  | { type: "enrichment_delta"; delta: string }
  | { type: "enrichment_complete"; original: string; enriched: string }
  | { type: "enrichment_error"; message: string }
  // Trace Viewer
  | { type: "trace_enabled"; enabled: boolean }
  | { type: "tool_list"; tools: Array<{ name: string; description: string; parameters: Record<string, unknown> }> };
