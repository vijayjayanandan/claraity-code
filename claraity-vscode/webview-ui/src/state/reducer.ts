/**
 * Central state management for the ClarAIty webview.
 *
 * Uses useReducer pattern to handle all server messages.
 * Each ServerMessage type maps to an action that updates state.
 *
 * Timeline architecture: UI elements are rendered in chronological order
 * via a flat timeline[] array. commitMarkdownBuffer() flushes accumulated
 * text before inserting tool cards, thinking blocks, code blocks, etc.
 * This mirrors the inline HTML's flushAndNewContentDiv() pattern.
 */
import type {
  ServerMessage,
  ToolStateData,
  SessionSummary,
  ReplayMessage,
  FileAttachment,
  ImageAttachment,
  JiraProfile,
} from "../types";

// ============================================================================
// Silent tools — internal tools hidden from timeline (mirrors src/ui/app.py)
// ============================================================================

const SILENT_TOOLS = new Set([
  "task_create",
  "task_update",
  "task_list",
  "task_get",
  "enter_plan_mode",
  "director_complete_understand",
  "director_complete_plan",
  "director_complete_slice",
  "director_complete_integration",
]);

// ============================================================================
// Timeline entry — ordered sequence of UI elements
// ============================================================================

export type TimelineEntry =
  | { type: "user_message"; id: string; content: string }
  | { type: "assistant_text"; id: string; content: string }
  | { type: "tool"; id: string; callId: string }
  | { type: "thinking"; id: string; content: string; tokenCount?: number }
  | { type: "code"; id: string; language: string; content: string }
  | { type: "subagent"; id: string; subagentId: string }
  | { type: "error"; id: string; message: string };

// ============================================================================
// State shape
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
}

export interface AppState {
  // Connection
  connected: boolean;
  sessionId: string | null;
  modelName: string;
  permissionMode: string;
  workingDirectory: string;

  // Chat
  messages: ChatMessage[];
  isStreaming: boolean;
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

  // Panels
  activePanel: "chat" | "config" | "jira" | "sessions" | null;
  sessions: SessionSummary[];

  // Context
  contextUsed: number;
  contextLimit: number;
  sessionTotalTokens: number;
  sessionTurnCount: number;

  // Auto-approve
  autoApprove: { edit: boolean; execute: boolean; browser: boolean };

  // Todos
  todos: unknown[];

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
}

export const initialState: AppState = {
  connected: false,
  sessionId: null,
  modelName: "",
  permissionMode: "normal",
  workingDirectory: "",

  messages: [],
  isStreaming: false,
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

  activePanel: "chat",
  sessions: [],

  contextUsed: 0,
  contextLimit: 0,
  sessionTotalTokens: 0,
  sessionTurnCount: 0,

  autoApprove: { edit: false, execute: false, browser: false },
  todos: [],

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
};

// ============================================================================
// Timeline counter + flush helper
// ============================================================================

/** Module-level counter for unique timeline entry IDs. */
let timelineCounter = 0;

/**
 * Session nonce — incremented on each session switch.
 * Appended to timeline IDs to prevent React key collisions when
 * old session components haven't unmounted yet.
 */
let sessionNonce = 0;

/** Exported for testing — reset the counter between tests. */
export function resetTimelineCounter(): void {
  timelineCounter = 0;
  sessionNonce = 0;
}

/**
 * Flush the current markdownBuffer into a timeline entry.
 * Mirrors the inline HTML's flushAndNewContentDiv() — called before inserting
 * tool cards, thinking blocks, code blocks, subagent cards, and errors.
 */
/** Generate a session-scoped timeline ID (e.g., "text-3-1"). */
function timelineId(prefix: string): string {
  return `${prefix}-${++timelineCounter}-${sessionNonce}`;
}

function commitMarkdownBuffer(state: AppState): AppState {
  if (!state.markdownBuffer.trim()) return state;
  return {
    ...state,
    timeline: [
      ...state.timeline,
      {
        type: "assistant_text" as const,
        id: timelineId("text"),
        content: state.markdownBuffer,
      },
    ],
    markdownBuffer: "",
  };
}

// ============================================================================
// Actions
// ============================================================================

export type Action =
  // Connection
  | { type: "SET_CONNECTED"; connected: boolean }
  | { type: "SET_SESSION_INFO"; sessionId: string; model: string; permissionMode: string; workingDirectory?: string; autoApprove?: Record<string, boolean> }
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
  | { type: "ADD_USER_MESSAGE"; content: string }
  | { type: "MESSAGE_ADDED"; data: { uuid: string; role: string; content: string; stream_id?: string }; subagentId?: string }
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
  | { type: "PLAN_APPROVAL"; callId: string; planHash: string; excerpt: string; truncated: boolean; planPath?: string; isDirector?: boolean }
  | { type: "PLAN_APPROVAL_DISMISS" }
  | { type: "PERMISSION_MODE_CHANGED"; mode: string }
  // Context
  | { type: "CONTEXT_UPDATED"; used: number; limit: number }
  // Panels
  | { type: "SET_ACTIVE_PANEL"; panel: AppState["activePanel"] }
  | { type: "SET_SESSIONS"; sessions: SessionSummary[] }
  | { type: "REPLAY_MESSAGES"; messages: ReplayMessage[] }
  // Auto-approve
  | { type: "AUTO_APPROVE_CHANGED"; categories: Record<string, boolean> }
  // Todos
  | { type: "TODOS_UPDATED"; todos: unknown[] }
  // Input
  | { type: "ADD_ATTACHMENT"; attachment: FileAttachment }
  | { type: "REMOVE_ATTACHMENT"; index: number }
  | { type: "ADD_IMAGE"; image: ImageAttachment }
  | { type: "REMOVE_IMAGE"; index: number }
  | { type: "CLEAR_INPUT" }
  | { type: "SET_MENTION_RESULTS"; files: Array<{ path: string; name: string; relativePath: string }> }
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
  // Error
  | { type: "ERROR"; errorType: string; message: string };

// ============================================================================
// Reducer
// ============================================================================

export function appReducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    // ── Connection ──
    case "SET_CONNECTED":
      return { ...state, connected: action.connected };

    case "SET_SESSION_INFO": {
      // Reset conversation state when switching to a different session (GAP 16)
      const isNewSession = action.sessionId !== state.sessionId && state.sessionId !== null;
      const base = isNewSession
        ? {
            ...state,
            messages: [],
            timeline: [],
            toolCards: {},
            toolOrder: [],
            toolCardOwners: {},
            subagents: {},
            promotedApprovals: {},
            pausePrompt: null,
            clarifyRequest: null,
            planApproval: null,
            undoAvailable: null,
            undoCompleted: false,
            lastTurnStats: null,
            markdownBuffer: "",
            currentThinking: null,
            currentCodeBlock: null,
          }
        : state;

      if (isNewSession) {
        timelineCounter = 0;
        sessionNonce++;
      }

      return {
        ...base,
        sessionId: action.sessionId,
        modelName: action.model,
        permissionMode: action.permissionMode,
        workingDirectory: action.workingDirectory ?? base.workingDirectory,
        autoApprove: action.autoApprove
          ? {
              edit: !!action.autoApprove.edit,
              execute: !!action.autoApprove.execute,
              browser: !!action.autoApprove.browser,
            }
          : base.autoApprove,
      };
    }

    // ── Streaming ──
    case "STREAM_START":
      return {
        ...state,
        isStreaming: true,
        markdownBuffer: "",
        currentThinking: null,
        currentCodeBlock: null,
        lastTurnStats: null,
      };

    case "STREAM_END": {
      // Flush any trailing text to timeline (GAP 3)
      const flushed = commitMarkdownBuffer(state);
      return {
        ...flushed,
        isStreaming: false,
        lastTurnStats: action.tokens != null
          ? { tokens: action.tokens, durationMs: action.durationMs ?? 0 }
          : null,
        sessionTurnCount: flushed.sessionTurnCount + 1,
        sessionTotalTokens: flushed.sessionTotalTokens + (action.tokens ?? 0),
      };
    }

    case "TEXT_DELTA":
      return { ...state, markdownBuffer: state.markdownBuffer + action.content };

    // ── Code blocks ──
    case "CODE_BLOCK_START": {
      // Flush text before code block (GAP 9)
      const flushed = commitMarkdownBuffer(state);
      return {
        ...flushed,
        currentCodeBlock: {
          language: action.language ?? "",
          content: "",
          complete: false,
        },
      };
    }

    case "CODE_BLOCK_DELTA":
      if (!state.currentCodeBlock) return state;
      return {
        ...state,
        currentCodeBlock: {
          ...state.currentCodeBlock,
          content: state.currentCodeBlock.content + action.content,
        },
      };

    case "CODE_BLOCK_END": {
      if (!state.currentCodeBlock) return { ...state, currentCodeBlock: null };
      // Commit completed code block to timeline (GAP 9)
      const completedBlock = { ...state.currentCodeBlock, complete: true };
      return {
        ...state,
        currentCodeBlock: null,
        timeline: [
          ...state.timeline,
          {
            type: "code" as const,
            id: timelineId("code"),
            language: completedBlock.language,
            content: completedBlock.content,
          },
        ],
      };
    }

    // ── Thinking ──
    case "THINKING_START": {
      // Flush text before thinking block (GAP 10)
      const flushed = commitMarkdownBuffer(state);
      return { ...flushed, currentThinking: { content: "", open: true } };
    }

    case "THINKING_DELTA":
      if (!state.currentThinking) return state;
      return {
        ...state,
        currentThinking: {
          ...state.currentThinking,
          content: state.currentThinking.content + action.content,
        },
      };

    case "THINKING_END": {
      if (!state.currentThinking) return state;
      // Commit completed thinking block to timeline (GAP 10)
      const thinkingContent = state.currentThinking.content;
      const thinkingTokenCount = state.currentThinking.tokenCount;
      return {
        ...state,
        currentThinking: null,
        timeline: [
          ...state.timeline,
          {
            type: "thinking" as const,
            id: timelineId("thinking"),
            content: thinkingContent,
            tokenCount: thinkingTokenCount,
          },
        ],
      };
    }

    // ── Messages ──
    case "ADD_USER_MESSAGE": {
      // Add to both messages[] (backward compat) and timeline[] (GAP 3)
      const userId = `user-${Date.now()}`;
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: userId,
            role: "user",
            content: action.content,
            finalized: true,
          },
        ],
        timeline: [
          ...state.timeline,
          {
            type: "user_message" as const,
            id: userId,
            content: action.content,
          },
        ],
      };
    }

    case "MESSAGE_ADDED": {
      // Route subagent messages to subagent's messages[] (GAP 5)
      if (action.subagentId) {
        const sa = state.subagents[action.subagentId];
        if (sa && (action.data.role === "assistant" || action.data.role === "user")) {
          return {
            ...state,
            subagents: {
              ...state.subagents,
              [action.subagentId]: {
                ...sa,
                messages: [...sa.messages, action.data.content],
              },
            },
          };
        }
        return state;
      }

      // Ignore system messages — not displayed (GAP 7)
      if (action.data.role === "system") return state;

      // Ignore user messages — already added locally by ADD_USER_MESSAGE
      if (action.data.role === "user") return state;

      // Ignore assistant messages — built from streaming events (text_delta, etc.)
      if (action.data.role === "assistant") return state;

      // Fallback: add unknown roles to messages[] for backward compat
      const existing = state.messages.find((m) => m.id === action.data.uuid);
      if (existing) return state;
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: action.data.uuid,
            role: action.data.role as "user" | "assistant" | "system",
            content: action.data.content,
            streamId: action.data.stream_id,
            finalized: false,
          },
        ],
      };
    }

    case "MESSAGE_UPDATED": {
      // Route subagent message updates (GAP 5)
      if (action.subagentId) {
        const sa = state.subagents[action.subagentId];
        if (sa) {
          // Update the last message from this subagent (best effort)
          const updatedMessages = [...sa.messages];
          if (updatedMessages.length > 0) {
            updatedMessages[updatedMessages.length - 1] = action.data.content;
          }
          return {
            ...state,
            subagents: {
              ...state.subagents,
              [action.subagentId]: {
                ...sa,
                messages: updatedMessages,
              },
            },
          };
        }
        return state;
      }

      // Update in messages[] (backward compat)
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.data.uuid
            ? { ...m, content: action.data.content }
            : m
        ),
      };
    }

    case "MESSAGE_FINALIZED": {
      const flushed = commitMarkdownBuffer(state);
      return {
        ...flushed,
        messages: flushed.messages.map((m) =>
          m.streamId === action.streamId ? { ...m, finalized: true } : m
        ),
      };
    }

    // ── Tools ──
    case "TOOL_STATE_UPDATED": {
      const callId = action.data.call_id;
      const isNew = !(callId in state.toolCards);
      const subagentId = action.subagentId;

      // Merge incoming data with existing entry, preserving tool_name and arguments (GAP 2)
      const existingCard = state.toolCards[callId];
      const mergedData = existingCard
        ? {
            ...existingCard,
            ...action.data,
            tool_name: action.data.tool_name || existingCard.tool_name,
            arguments: action.data.arguments ?? existingCard.arguments,
          }
        : action.data;

      // Track which subagent owns this tool card
      const toolCardOwners = subagentId && isNew
        ? { ...state.toolCardOwners, [callId]: subagentId }
        : state.toolCardOwners;

      // Increment subagent tool count on first appearance
      let subagents = state.subagents;
      if (subagentId && isNew && subagents[subagentId]) {
        subagents = {
          ...subagents,
          [subagentId]: {
            ...subagents[subagentId],
            toolCount: subagents[subagentId].toolCount + 1,
          },
        };
      }

      // Promote subagent approvals to conversation level
      let promotedApprovals = state.promotedApprovals;
      if (subagentId && action.data.status === "awaiting_approval") {
        promotedApprovals = {
          ...promotedApprovals,
          [callId]: { data: mergedData, subagentId },
        };
      } else if (callId in promotedApprovals && action.data.status !== "awaiting_approval") {
        const { [callId]: _, ...rest } = promotedApprovals;
        promotedApprovals = rest;
      }

      // Flush text and add timeline entry on first appearance for main-agent tools (GAP 3)
      // Skip timeline entry for silent/internal tools (task_*, plan, director)
      let baseState = state;
      let timeline = state.timeline;
      if (isNew && !subagentId && !SILENT_TOOLS.has(mergedData.tool_name ?? "")) {
        baseState = commitMarkdownBuffer(state);
        timeline = [
          ...baseState.timeline,
          {
            type: "tool" as const,
            id: timelineId("tool"),
            callId,
          },
        ];
      }

      return {
        ...baseState,
        toolCards: { ...baseState.toolCards, [callId]: mergedData },
        toolOrder: isNew ? [...baseState.toolOrder, callId] : baseState.toolOrder,
        toolCardOwners,
        subagents,
        promotedApprovals,
        timeline,
      };
    }

    // ── Subagents ──
    case "SUBAGENT_REGISTERED": {
      // Flush text and add timeline entry (GAP 6)
      const flushed = commitMarkdownBuffer(state);
      return {
        ...flushed,
        subagents: {
          ...flushed.subagents,
          [action.data.subagentId]: {
            ...action.data,
            messages: action.data.messages ?? [],
          },
        },
        timeline: [
          ...flushed.timeline,
          {
            type: "subagent" as const,
            id: timelineId("subagent"),
            subagentId: action.data.subagentId,
          },
        ],
      };
    }

    case "SUBAGENT_UNREGISTERED": {
      const existingSa = state.subagents[action.subagentId];
      if (!existingSa) {
        const { [action.subagentId]: _, ...rest } = state.subagents;
        return { ...state, subagents: rest };
      }
      return {
        ...state,
        subagents: {
          ...state.subagents,
          [action.subagentId]: {
            ...existingSa,
            active: false,
            finalElapsedMs: Date.now() - existingSa.startTime,
          },
        },
      };
    }

    case "DISMISS_SUBAGENT_APPROVAL": {
      const { [action.callId]: _, ...rest } = state.promotedApprovals;
      return { ...state, promotedApprovals: rest };
    }

    // ── Interactive ──
    case "PAUSE_PROMPT_START":
      return {
        ...state,
        pausePrompt: {
          reason: action.reason,
          reasonCode: action.reasonCode,
          stats: action.stats,
          pendingTodos: action.pendingTodos,
        },
      };

    case "PAUSE_PROMPT_END":
      return { ...state, pausePrompt: null };

    case "CLARIFY_REQUEST":
      return {
        ...state,
        clarifyRequest: {
          callId: action.callId,
          questions: action.questions,
          context: action.context,
        },
      };

    case "CLARIFY_DISMISS":
      return { ...state, clarifyRequest: null };

    case "PLAN_APPROVAL":
      return {
        ...state,
        planApproval: {
          callId: action.callId,
          planHash: action.planHash,
          excerpt: action.excerpt,
          truncated: action.truncated,
          planPath: action.planPath,
          isDirector: action.isDirector,
        },
      };

    case "PLAN_APPROVAL_DISMISS":
      return { ...state, planApproval: null };

    case "PERMISSION_MODE_CHANGED":
      return { ...state, permissionMode: action.mode };

    // ── Context ──
    case "CONTEXT_UPDATED":
      return { ...state, contextUsed: action.used, contextLimit: action.limit };

    // ── Panels ──
    case "SET_ACTIVE_PANEL":
      return { ...state, activePanel: action.panel };

    case "SET_SESSIONS":
      return { ...state, sessions: action.sessions };

    case "REPLAY_MESSAGES": {
      // Filter system messages, reconstruct tool cards from replay data (GAPs 7, 8)
      const replayTimeline: TimelineEntry[] = [];
      const replayToolCards: Record<string, ToolStateData> = {};
      const replayToolOrder: string[] = [];
      const replayMessages: ChatMessage[] = [];

      for (let i = 0; i < action.messages.length; i++) {
        const m = action.messages[i];

        // Skip system messages (GAP 7)
        if (m.role === "system") continue;

        // Create ChatMessage for backward compat
        const msgId = `replay-${i}`;
        replayMessages.push({
          id: msgId,
          role: m.role as "user" | "assistant" | "system",
          content: m.content,
          finalized: true,
        });

        // Build timeline entries
        if (m.role === "user") {
          replayTimeline.push({
            type: "user_message",
            id: msgId,
            content: m.content,
          });
        } else if (m.role === "assistant") {
          // If message has tool_calls, create tool card entries
          if (m.tool_calls && m.tool_calls.length > 0) {
            // Add assistant text first if content is non-empty
            if (m.content.trim()) {
              replayTimeline.push({
                type: "assistant_text",
                id: timelineId("replay-text"),
                content: m.content,
              });
            }
            for (const tc of m.tool_calls) {
              let parsedArgs: Record<string, unknown> = {};
              try {
                parsedArgs = JSON.parse(tc.function.arguments);
              } catch { /* empty */ }
              const toolData: ToolStateData = {
                call_id: tc.id,
                tool_name: tc.function.name,
                status: "pending",
                arguments: parsedArgs,
              };
              replayToolCards[tc.id] = toolData;
              replayToolOrder.push(tc.id);
              replayTimeline.push({
                type: "tool",
                id: timelineId("replay-tool"),
                callId: tc.id,
              });
            }
          } else if (m.content.trim()) {
            replayTimeline.push({
              type: "assistant_text",
              id: timelineId("replay-text"),
              content: m.content,
            });
          }
        } else if (m.role === "tool" && m.tool_call_id) {
          // Tool result — update existing tool card with result info
          const existing = replayToolCards[m.tool_call_id];
          if (existing) {
            replayToolCards[m.tool_call_id] = {
              ...existing,
              status: m.meta?.status === "error" ? "error" : "success",
              duration_ms: m.meta?.duration_ms ?? null,
              result: m.content,
            };
          }
        }
      }

      return {
        ...state,
        messages: replayMessages,
        timeline: replayTimeline,
        toolCards: { ...state.toolCards, ...replayToolCards },
        toolOrder: [...state.toolOrder, ...replayToolOrder],
      };
    }

    // ── Auto-approve ──
    case "AUTO_APPROVE_CHANGED":
      return {
        ...state,
        autoApprove: {
          edit: !!action.categories.edit,
          execute: !!action.categories.execute,
          browser: !!action.categories.browser,
        },
      };

    // ── Todos ──
    case "TODOS_UPDATED":
      return { ...state, todos: action.todos };

    // ── Input ──
    case "ADD_ATTACHMENT":
      return { ...state, attachments: [...state.attachments, action.attachment] };

    case "REMOVE_ATTACHMENT":
      return {
        ...state,
        attachments: state.attachments.filter((_, i) => i !== action.index),
      };

    case "ADD_IMAGE":
      return { ...state, images: [...state.images, action.image] };

    case "REMOVE_IMAGE":
      return {
        ...state,
        images: state.images.filter((_, i) => i !== action.index),
      };

    case "CLEAR_INPUT":
      return { ...state, attachments: [], images: [], mentionResults: [] };

    case "SET_MENTION_RESULTS":
      return { ...state, mentionResults: action.files };

    // ── Undo ──
    case "UNDO_AVAILABLE":
      return { ...state, undoAvailable: { turnId: action.turnId, files: action.files }, undoCompleted: false };

    case "UNDO_COMPLETE":
      return { ...state, undoCompleted: true };

    // ── Config ──
    case "CONFIG_LOADED":
      return {
        ...state,
        configData: action.config,
        configSubagentNames: action.subagentNames,
        configModels: null,
        configNotification: null,
      };

    case "MODELS_LIST":
      return {
        ...state,
        configModels: { models: action.models, error: action.error },
      };

    case "CONFIG_SAVED":
      return {
        ...state,
        configNotification: { message: action.message, success: action.success },
        modelName: action.success && action.model ? action.model : state.modelName,
      };

    // ── Jira ──
    case "JIRA_PROFILES":
      return {
        ...state,
        jiraProfiles: action.profiles,
        jiraConnectedProfile: action.connectedProfile,
        jiraNotification: action.error ? { message: action.error, success: false } : state.jiraNotification,
      };

    case "JIRA_NOTIFICATION":
      return {
        ...state,
        jiraNotification: { message: action.message, success: action.success },
      };

    case "JIRA_CONNECTED":
      return {
        ...state,
        jiraConnectedProfile: action.success ? action.profile : state.jiraConnectedProfile,
        jiraNotification: { message: action.message, success: action.success },
      };

    // ── Error ──
    case "ERROR": {
      // Flush text and add error to timeline (GAP 15)
      const flushed = commitMarkdownBuffer(state);
      return {
        ...flushed,
        timeline: [
          ...flushed.timeline,
          {
            type: "error" as const,
            id: timelineId("error"),
            message: action.message,
          },
        ],
      };
    }

    default:
      return state;
  }
}

// ============================================================================
// ServerMessage -> Action dispatcher
// ============================================================================

export function dispatchServerMessage(
  dispatch: React.Dispatch<Action>,
  msg: ServerMessage,
): void {
  switch (msg.type) {
    case "stream_start":
      dispatch({ type: "STREAM_START" });
      break;

    case "stream_end":
      dispatch({ type: "STREAM_END", tokens: msg.total_tokens, durationMs: msg.duration_ms });
      break;

    case "text_delta":
      dispatch({ type: "TEXT_DELTA", content: msg.content });
      break;

    case "code_block_start":
      dispatch({ type: "CODE_BLOCK_START", language: msg.language });
      break;

    case "code_block_delta":
      dispatch({ type: "CODE_BLOCK_DELTA", content: msg.content });
      break;

    case "code_block_end":
      dispatch({ type: "CODE_BLOCK_END" });
      break;

    case "thinking_start":
      dispatch({ type: "THINKING_START" });
      break;

    case "thinking_delta":
      dispatch({ type: "THINKING_DELTA", content: msg.content });
      break;

    case "thinking_end":
      dispatch({ type: "THINKING_END" });
      break;

    case "context_updated":
      dispatch({ type: "CONTEXT_UPDATED", used: msg.used, limit: msg.limit });
      break;

    case "pause_prompt_start":
      dispatch({
        type: "PAUSE_PROMPT_START",
        reason: msg.reason,
        reasonCode: msg.reason_code,
        stats: msg.stats,
        pendingTodos: msg.pending_todos,
      });
      break;

    case "pause_prompt_end":
      dispatch({ type: "PAUSE_PROMPT_END" });
      break;

    case "error":
      dispatch({ type: "ERROR", errorType: msg.error_type, message: msg.user_message });
      break;

    case "todos_updated":
      dispatch({ type: "TODOS_UPDATED", todos: msg.todos });
      break;

    case "auto_approve_changed":
      dispatch({ type: "AUTO_APPROVE_CHANGED", categories: msg.categories });
      break;

    case "sessions_list":
      dispatch({ type: "SET_SESSIONS", sessions: msg.sessions });
      break;

    case "session_history":
      dispatch({ type: "REPLAY_MESSAGES", messages: msg.messages });
      break;

    case "store":
      switch (msg.event) {
        case "tool_state_updated":
          dispatch({ type: "TOOL_STATE_UPDATED", data: msg.data, subagentId: msg.subagent_id });
          break;
        case "message_added":
          dispatch({ type: "MESSAGE_ADDED", data: msg.data, subagentId: msg.subagent_id });
          break;
        case "message_updated":
          dispatch({ type: "MESSAGE_UPDATED", data: msg.data, subagentId: msg.subagent_id });
          break;
        case "message_finalized":
          dispatch({ type: "MESSAGE_FINALIZED", streamId: msg.data.stream_id });
          break;
      }
      break;

    case "interactive":
      switch (msg.event) {
        case "clarify_request":
          dispatch({
            type: "CLARIFY_REQUEST",
            callId: msg.data.call_id,
            questions: msg.data.questions,
            context: msg.data.context,
          });
          break;
        case "plan_submitted":
        case "director_plan_submitted":
          dispatch({
            type: "PLAN_APPROVAL",
            callId: msg.data.call_id,
            planHash: msg.data.plan_hash,
            excerpt: msg.data.excerpt,
            truncated: msg.data.truncated,
            planPath: msg.data.plan_path,
            isDirector: msg.event === "director_plan_submitted",
          });
          break;
        case "permission_mode_changed":
          dispatch({ type: "PERMISSION_MODE_CHANGED", mode: msg.data.new_mode });
          break;
      }
      break;

    case "subagent":
      if (msg.event === "registered") {
        dispatch({
          type: "SUBAGENT_REGISTERED",
          data: {
            subagentId: msg.data.subagent_id,
            parentToolCallId: msg.data.parent_tool_call_id,
            modelName: msg.data.model_name,
            subagentName: msg.data.subagent_name,
            startTime: Date.now(),
            toolCount: 0,
            active: true,
            messages: [],
          },
        });
      } else if (msg.event === "unregistered") {
        dispatch({ type: "SUBAGENT_UNREGISTERED", subagentId: msg.data.subagent_id });
      }
      break;

    case "config_loaded":
      dispatch({
        type: "CONFIG_LOADED",
        config: (msg as Record<string, unknown>).config as Record<string, unknown> ?? {},
        subagentNames: ((msg as Record<string, unknown>).subagent_names as string[]) ?? [],
      });
      break;

    case "models_list": {
      const ml = msg as Record<string, unknown>;
      dispatch({
        type: "MODELS_LIST",
        models: (ml.models as string[]) ?? [],
        error: ml.error as string | undefined,
      });
      break;
    }

    case "config_saved": {
      const cs = msg as Record<string, unknown>;
      dispatch({
        type: "CONFIG_SAVED",
        success: !!cs.success,
        message: (cs.message as string) ?? "",
        model: (cs.model as string) ?? undefined,
      });
      break;
    }

    case "jira_profiles": {
      const jp = msg as { profiles: JiraProfile[]; connected_profile: string | null; error?: string };
      dispatch({
        type: "JIRA_PROFILES",
        profiles: jp.profiles ?? [],
        connectedProfile: jp.connected_profile ?? null,
        error: jp.error,
      });
      break;
    }

    case "jira_config_saved": {
      const jcs = msg as { success: boolean; message: string };
      dispatch({ type: "JIRA_NOTIFICATION", success: !!jcs.success, message: jcs.message ?? "" });
      break;
    }

    case "jira_connect_result": {
      const jcr = msg as { success: boolean; message: string; profile?: string };
      dispatch({ type: "JIRA_CONNECTED", success: !!jcr.success, message: jcr.message ?? "", profile: jcr.profile ?? null });
      break;
    }

    case "jira_disconnect_result": {
      const jdr = msg as { success: boolean; message: string };
      dispatch({ type: "JIRA_CONNECTED", success: !!jdr.success, message: jdr.message ?? "", profile: null });
      break;
    }

    // These are handled at a higher level or don't affect state
    case "session_info":
    case "context_compacting":
    case "context_compacted":
    case "file_read":
    case "execute_in_terminal":
      break;
  }
}
