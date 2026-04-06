/**
 * State types, interfaces, and initial state for the ClarAIty webview.
 *
 * This module defines the shape of the application state and all
 * supporting data types (TimelineEntry, ChatMessage, etc.).
 */
import type {
  ToolStateData,
  SessionSummary,
  FileAttachment,
  ImageAttachment,
  JiraProfile,
  McpServerInfo,
  McpMarketplaceEntry,
  BeadsResponse,
  ArchitectureResponse,
  SubAgentInfo,
  LimitsData,
  BackgroundTaskData,
} from "../types";

export type { FileAttachment, ImageAttachment };

// ============================================================================
// Timeline entry — ordered sequence of UI elements
// ============================================================================

export type TimelineEntry =
  | { type: "user_message"; id: string; content: string; attachments?: FileAttachment[]; images?: ImageAttachment[] }
  | { type: "assistant_text"; id: string; content: string }
  | { type: "tool"; id: string; callId: string }
  | { type: "thinking"; id: string; content: string; tokenCount?: number }
  | { type: "code"; id: string; language: string; content: string }
  | { type: "subagent"; id: string; subagentId: string }
  | { type: "error"; id: string; message: string }
  | { type: "compaction_summary"; id: string; content: string };

// ============================================================================
// Supporting types
// ============================================================================

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  streamId?: string;
  finalized: boolean;
}

export interface ThinkingBlock {
  content: string;
  tokenCount?: number;
  open: boolean;
}

export interface CodeBlock {
  language: string;
  content: string;
  complete: boolean;
}

/** Ordered entry inside a subagent card — mirrors the main TimelineEntry concept. */
export type SubagentTimelineEntry =
  | { type: "text"; index: number }
  | { type: "tool"; callId: string };

export interface SubagentInfo {
  subagentId: string;
  parentToolCallId: string;
  modelName: string;
  subagentName: string;
  startTime: number;
  toolCount: number;
  active: boolean;
  finalElapsedMs?: number;
  messages: string[];
  /** Chronological ordering of text messages and tool cards within the card. */
  timeline: SubagentTimelineEntry[];
  /** Cumulative tokens consumed across all LLM calls. */
  totalTokens: number;
  /** Prompt tokens from the most recent LLM call (current context size). */
  contextTokens: number;
  /** Model's context window limit. */
  contextWindow: number;
}

// ============================================================================
// AppState
// ============================================================================

export interface AppState {
  // Connection
  connected: boolean;
  sessionId: string | null;
  modelName: string;
  permissionMode: string;
  workingDirectory: string;

  // Timeline ID generation (must be in state for reducer purity)
  timelineCounter: number;
  sessionNonce: number;

  // Chat
  messages: ChatMessage[];
  isStreaming: boolean;
  isCompacting: boolean;
  markdownBuffer: string;

  // Timeline — ordered sequence of UI elements
  timeline: TimelineEntry[];

  // Thinking
  currentThinking: ThinkingBlock | null;

  // Code blocks
  currentCodeBlock: CodeBlock | null;

  // Tools
  toolCards: Record<string, ToolStateData>;
  toolOrder: string[]; // Preserves insertion order (kept for backward compat)
  toolCardOwners: Record<string, string>; // call_id -> subagent_id

  // Subagents
  subagents: Record<string, SubagentInfo>;
  promotedApprovals: Record<string, { data: ToolStateData; subagentId: string }>;

  // Interactive
  pendingApproval: ToolStateData | null;
  pausePrompt: { reason: string; reasonCode: string; stats: Record<string, unknown>; pendingTodos?: string[] } | null;
  clarifyRequest: { callId: string; questions: unknown[]; context?: string } | null;
  planApproval: { callId: string; planHash: string; excerpt: string; truncated: boolean; planPath?: string; isDirector?: boolean } | null;

  // Chat input draft — preserved across panel switches
  chatDraft: string;

  // Panels
  activePanel: "chat" | "config" | "jira" | "sessions" | "mcp" | "architecture" | "beads" | "subagents" | "trace" | null;
  sessions: SessionSummary[];

  // Context
  contextUsed: number;
  contextLimit: number;
  sessionTotalTokens: number;
  sessionTurnCount: number;

  // Auto-approve
  autoApprove: { read: boolean; edit: boolean; execute: boolean; browser: boolean; knowledge_update: boolean; subagent: boolean };

  // Todos
  todos: unknown[];

  // Background tasks
  backgroundTasks: BackgroundTaskData[];
  /** Task IDs dismissed by user — prevents re-adding on next server update. */
  _dismissedBgTasks: Set<string>;

  // Input
  attachments: FileAttachment[];
  images: ImageAttachment[];
  mentionResults: Array<{ path: string; name: string; relativePath: string }>;

  // Undo
  undoAvailable: { turnId: string; files: string[] } | null;
  undoCompleted: boolean;

  // Turn stats
  lastTurnStats: { tokens: number; durationMs: number } | null;

  // Config panel
  configData: Record<string, unknown> | null;
  configSubagentNames: string[];
  configModels: { models: string[]; error?: string } | null;
  configNotification: { message: string; success: boolean } | null;

  // Jira panel
  jiraProfiles: JiraProfile[];
  jiraConnectedProfile: string | null;
  jiraNotification: { message: string; success: boolean } | null;

  // MCP panel
  mcpServers: McpServerInfo[];
  mcpMarketplace: McpMarketplaceEntry[];
  mcpMarketplaceMeta: { totalCount: number; page: number; hasNext: boolean } | null;
  mcpNotification: { message: string; success: boolean } | null;

  // ClarAIty Knowledge & Beads
  beadsData: BeadsResponse | null;
  architectureData: ArchitectureResponse | null;

  // Trace
  traceSteps: import('../types').TraceStepData[] | null;
  traceEnabled: boolean;

  // Subagents panel
  subagentsList: SubAgentInfo[];
  subagentsAvailableTools: string[];
  subagentNotification: { message: string; success: boolean } | null;

  // Limits
  limits: LimitsData;
  lastIterations: number | null;

  // Prompt Enrichment
  promptEnrichmentEnabled: boolean;
  enrichmentLoading: boolean;
  enrichedPromptPreview: string | null;
  enrichedPromptOriginal: string | null;
}

// ============================================================================
// Initial state
// ============================================================================

export const initialState: AppState = {
  connected: false,
  sessionId: null,
  modelName: "",
  permissionMode: "normal",
  workingDirectory: "",

  timelineCounter: 0,
  sessionNonce: 0,

  messages: [],
  isStreaming: false,
  isCompacting: false,
  markdownBuffer: "",

  timeline: [],

  currentThinking: null,
  currentCodeBlock: null,

  toolCards: {},
  toolOrder: [],
  toolCardOwners: {},

  subagents: {},
  promotedApprovals: {},

  pendingApproval: null,
  pausePrompt: null,
  clarifyRequest: null,
  planApproval: null,

  chatDraft: "",

  activePanel: "chat",
  sessions: [],

  contextUsed: 0,
  contextLimit: 0,
  sessionTotalTokens: 0,
  sessionTurnCount: 0,

  autoApprove: { read: true, edit: false, execute: false, browser: false, knowledge_update: false, subagent: false },
  todos: [],
  backgroundTasks: [],
  _dismissedBgTasks: new Set<string>(),

  attachments: [],
  images: [],
  mentionResults: [],

  undoAvailable: null,
  undoCompleted: false,
  lastTurnStats: null,

  configData: null,
  configSubagentNames: [],
  configModels: null,
  configNotification: null,

  jiraProfiles: [],
  jiraConnectedProfile: null,
  jiraNotification: null,

  mcpServers: [],
  mcpMarketplace: [],
  mcpMarketplaceMeta: null,
  mcpNotification: null,

  beadsData: null,
  architectureData: null,
  traceSteps: null,
  traceEnabled: false,

  subagentsList: [],
  subagentsAvailableTools: [],
  subagentNotification: null,

  limits: {
    iteration_limit_enabled: true,
    max_iterations: 50,
  },
  lastIterations: null,

  promptEnrichmentEnabled: false,
  enrichmentLoading: false,
  enrichedPromptPreview: null,
  enrichedPromptOriginal: null,
};
