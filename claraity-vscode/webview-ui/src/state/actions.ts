/**
 * Action types for the ClarAIty webview reducer.
 *
 * Each action represents a user interaction or server event
 * that triggers a state transition.
 */
import type { ToolStateData, SessionSummary, ReplayMessage, FileAttachment, ImageAttachment, JiraProfile, McpServerInfo, McpMarketplaceEntry, BeadsResponse, ArchitectureResponse, SubAgentInfo, SkillInfo, LimitsData, BackgroundTaskData } from "../types";
import type { AppState, SubagentInfo } from "./state";

export type Action =
  // Connection
  | { type: "SET_CONNECTED"; connected: boolean }
  | { type: "SET_SESSION_INFO"; sessionId: string; model: string; permissionMode: string; workingDirectory?: string; autoApprove?: Record<string, boolean>; limits?: LimitsData }
  // Streaming
  | { type: "STREAM_START" }
  | { type: "STREAM_END"; tokens?: number; durationMs?: number }
  | { type: "TEXT_DELTA"; content: string }
  // Code blocks
  | { type: "CODE_BLOCK_START"; language?: string }
  | { type: "CODE_BLOCK_DELTA"; content: string }
  | { type: "CODE_BLOCK_END" }
  // Thinking
  | { type: "THINKING_START" }
  | { type: "THINKING_DELTA"; content: string }
  | { type: "THINKING_END" }
  // Messages
  | { type: "ADD_USER_MESSAGE"; content: string; attachments?: FileAttachment[]; images?: ImageAttachment[] }
  | { type: "MESSAGE_ADDED"; data: { uuid: string; role: string; content: string; stream_id?: string; is_compact_summary?: boolean }; subagentId?: string }
  | { type: "MESSAGE_UPDATED"; data: { uuid: string; content: string }; subagentId?: string }
  | { type: "MESSAGE_FINALIZED"; streamId: string }
  // Tools
  | { type: "TOOL_STATE_UPDATED"; data: ToolStateData; subagentId?: string }
  // Subagents
  | { type: "SUBAGENT_REGISTERED"; data: SubagentInfo }
  | { type: "SUBAGENT_UNREGISTERED"; subagentId: string }
  | { type: "DISMISS_SUBAGENT_APPROVAL"; callId: string }
  // Interactive
  | { type: "PAUSE_PROMPT_START"; reason: string; reasonCode: string; stats: Record<string, unknown>; pendingTodos?: string[] }
  | { type: "PAUSE_PROMPT_END" }
  | { type: "CLARIFY_REQUEST"; callId: string; questions: unknown[]; context?: string }
  | { type: "CLARIFY_DISMISS" }
  | { type: "PLAN_APPROVAL"; callId: string; planHash: string; excerpt: string; truncated: boolean; planPath?: string }
  | { type: "PLAN_APPROVAL_DISMISS" }
  | { type: "PERMISSION_MODE_CHANGED"; mode: string }
  // Context
  | { type: "CONTEXT_UPDATED"; used: number; limit: number; iteration?: number }
  | { type: "CONTEXT_COMPACTING" }
  | { type: "CONTEXT_COMPACTED" }
  // Panels
  | { type: "SET_CHAT_DRAFT"; draft: string }
  | { type: "SET_ACTIVE_PANEL"; panel: AppState["activePanel"] }
  | { type: "SET_SESSIONS"; sessions: SessionSummary[] }
  | { type: "REPLAY_MESSAGES"; messages: ReplayMessage[] }
  // Auto-approve
  | { type: "AUTO_APPROVE_CHANGED"; categories: Record<string, boolean> }
  // Todos
  | { type: "TODOS_UPDATED"; todos: unknown[] }
  // Background tasks
  | { type: "BACKGROUND_TASKS_UPDATED"; tasks: BackgroundTaskData[] }
  | { type: "DISMISS_BACKGROUND_TASK"; taskId: string }
  // Input
  | { type: "ADD_ATTACHMENT"; attachment: FileAttachment }
  | { type: "REMOVE_ATTACHMENT"; index: number }
  | { type: "ADD_IMAGE"; image: ImageAttachment }
  | { type: "REMOVE_IMAGE"; index: number }
  | { type: "CLEAR_INPUT" }
  | { type: "SET_MENTION_RESULTS"; files: Array<{ path: string; name: string; relativePath: string }> }
  // Turn deletion
  | { type: "TURN_DELETED"; anchorUuid: string; affectedUuids: string[]; count: number; preview: string }
  | { type: "TURN_RESTORED"; anchorUuid: string; affectedUuids: string[] }
  // Undo
  | { type: "UNDO_AVAILABLE"; turnId: string; files: string[] }
  | { type: "UNDO_COMPLETE"; turnId: string }
  // Config
  | { type: "CONFIG_LOADED"; config: Record<string, unknown>; subagentNames: string[] }
  | { type: "MODELS_LIST"; models: string[]; error?: string }
  | { type: "CONFIG_SAVED"; success: boolean; message: string; model?: string }
  // Jira
  | { type: "JIRA_PROFILES"; profiles: JiraProfile[]; connectedProfile: string | null; error?: string }
  | { type: "JIRA_NOTIFICATION"; success: boolean; message: string }
  | { type: "JIRA_CONNECTED"; profile: string | null; success: boolean; message: string }
  // MCP
  | { type: "MCP_SERVERS_LIST"; servers: McpServerInfo[]; notification?: { message: string; success: boolean } }
  | { type: "MCP_MARKETPLACE_RESULTS"; entries: McpMarketplaceEntry[]; totalCount: number; page: number; hasNext: boolean }
  | { type: "MCP_NOTIFICATION"; message: string; success: boolean }
  // ClarAIty Knowledge & Beads
  | { type: "BEADS_LOADED"; data: BeadsResponse }
  | { type: "ARCHITECTURE_LOADED"; data: ArchitectureResponse }
  | { type: "TRACE_LOADED"; steps: import('../types').TraceStepData[] }
  | { type: "TRACE_ENABLED"; enabled: boolean }
  | { type: "TOOL_LIST_LOADED"; tools: { name: string; description: string; parameters: Record<string, unknown> }[] }
  // Subagents panel
  | { type: "SUBAGENTS_LIST"; subagents: SubAgentInfo[]; availableTools: string[] }
  | { type: "SUBAGENT_NOTIFICATION"; success: boolean; message: string }
  | { type: "CLEAR_SUBAGENT_NOTIFICATION" }
  // Limits
  | { type: "LIMITS_LOADED"; limits: LimitsData }
  | { type: "LIMITS_SAVED"; success: boolean; message: string; limits?: LimitsData }
  // Skills
  | { type: "SKILLS_LOADED"; skills: SkillInfo[] }
  | { type: "TOGGLE_SKILL"; skillId: string }
  | { type: "CLEAR_ACTIVE_SKILLS" }
  // Prompt Enrichment
  | { type: "SET_ENRICHMENT_ENABLED"; enabled: boolean }
  | { type: "SET_ENRICHMENT_LOADING"; loading: boolean }
  | { type: "ENRICHMENT_DELTA"; delta: string }
  | { type: "ENRICHMENT_COMPLETE"; original: string; enriched: string }
  | { type: "CLEAR_ENRICHED_PREVIEW" }
  // Error
  | { type: "ERROR"; errorType: string; message: string };
