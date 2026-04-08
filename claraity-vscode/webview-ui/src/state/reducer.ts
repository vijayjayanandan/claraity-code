/**
 * Central reducer for the ClarAIty webview.
 *
 * Pure function: (AppState, Action) => AppState.
 * Uses timeline architecture where UI elements are rendered in chronological
 * order via a flat timeline[] array.
 *
 * Split into modules:
 *   state.ts    — AppState interface, types, initialState
 *   actions.ts  — Action union type
 *   reducer.ts  — appReducer + helpers (this file)
 *   dispatch.ts — dispatchServerMessage (ServerMessage -> Action mapper)
 */
import type { ToolStateData } from "../types";
import type { AppState, TimelineEntry, ChatMessage } from "./state";
import type { Action } from "./actions";

// Re-export everything so existing imports from "./state/reducer" still work
export { type TimelineEntry, type ChatMessage, type ThinkingBlock, type CodeBlock, type SubagentInfo, type SubagentTimelineEntry, type AppState, initialState } from "./state";
export { type Action } from "./actions";
export { dispatchServerMessage } from "./dispatch";

// ============================================================================
// Constants
// ============================================================================

/** Maximum timeline entries kept in memory. */
const MAX_TIMELINE_ENTRIES = 500;

/** Maximum messages kept (backward compat array). */
const MAX_MESSAGES = 500;

/** Internal tools hidden from timeline (mirrors src/ui/app.py). */
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
// Helpers
// ============================================================================

/** Exported for testing — no-op since counters are now in AppState. */
export function resetTimelineCounter(): void {
  // No-op: counters are now in AppState. Tests should use initialState directly.
}

/**
 * Generate a session-scoped timeline ID (e.g., "text-3-1").
 * Returns [id, updatedState] to keep the reducer pure.
 */
function nextTimelineId(state: AppState, prefix: string): [string, AppState] {
  const counter = state.timelineCounter + 1;
  return [
    `${prefix}-${counter}-${state.sessionNonce}`,
    { ...state, timelineCounter: counter },
  ];
}

/**
 * Flush the current markdownBuffer into a timeline entry.
 * Called before inserting tool cards, thinking blocks, code blocks, etc.
 */
function commitMarkdownBuffer(state: AppState): AppState {
  if (!state.markdownBuffer.trim()) return state;
  const [id, s] = nextTimelineId(state, "text");
  return {
    ...s,
    timeline: [
      ...s.timeline,
      {
        type: "assistant_text" as const,
        id,
        content: s.markdownBuffer,
      },
    ],
    markdownBuffer: "",
  };
}

/**
 * Trim timeline from the front if it exceeds MAX_TIMELINE_ENTRIES.
 * Also cleans up toolCards for removed tool entries.
 */
function trimTimeline(state: AppState): AppState {
  if (state.timeline.length <= MAX_TIMELINE_ENTRIES) return state;

  const excess = state.timeline.length - MAX_TIMELINE_ENTRIES;
  const removed = state.timeline.slice(0, excess);
  const trimmed = state.timeline.slice(excess);

  const removedCallIds = new Set<string>();
  for (const entry of removed) {
    if (entry.type === "tool") removedCallIds.add(entry.callId);
  }

  let toolCards = state.toolCards;
  let toolOrder = state.toolOrder;
  if (removedCallIds.size > 0) {
    const newToolCards: Record<string, ToolStateData> = {};
    for (const [id, card] of Object.entries(toolCards)) {
      if (!removedCallIds.has(id)) newToolCards[id] = card;
    }
    toolCards = newToolCards;
    toolOrder = toolOrder.filter(id => !removedCallIds.has(id));
  }

  const messages = state.messages.length > MAX_MESSAGES
    ? state.messages.slice(state.messages.length - MAX_MESSAGES)
    : state.messages;

  return { ...state, timeline: trimmed, toolCards, toolOrder, messages };
}

// ============================================================================
// Reducer
// ============================================================================

export function appReducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    // ── Connection ──
    case "SET_CONNECTED":
      return { ...state, connected: action.connected };

    case "SET_SESSION_INFO": {
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
            traceSteps: null,
            markdownBuffer: "",
            currentThinking: null,
            currentCodeBlock: null,
            isCompacting: false,
            backgroundTasks: [],
            _dismissedBgTasks: new Set<string>(),
          }
        : state;

      return {
        ...base,
        sessionId: action.sessionId,
        modelName: action.model,
        permissionMode: action.permissionMode,
        workingDirectory: action.workingDirectory ?? base.workingDirectory,
        timelineCounter: isNewSession ? 0 : base.timelineCounter,
        sessionNonce: isNewSession ? base.sessionNonce + 1 : base.sessionNonce,
        autoApprove: action.autoApprove
          ? {
              read: !!action.autoApprove.read,
              edit: !!action.autoApprove.edit,
              execute: !!action.autoApprove.execute,
              browser: !!action.autoApprove.browser,
              knowledge_update: !!action.autoApprove.knowledge_update,
              subagent: !!action.autoApprove.subagent,
            }
          : base.autoApprove,
        limits: action.limits ?? base.limits,
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
      const flushed = commitMarkdownBuffer(state);
      const endState = {
        ...flushed,
        isStreaming: false,
        isCompacting: false,  // safety reset: clears stuck state if context_compacted was missed
        lastTurnStats: action.tokens != null
          ? { tokens: action.tokens, durationMs: action.durationMs ?? 0 }
          : null,
        sessionTurnCount: flushed.sessionTurnCount + 1,
        sessionTotalTokens: flushed.sessionTotalTokens + (action.tokens ?? 0),
        // Clear interactive widgets so they don't persist after the turn ends
        clarifyRequest: null,
        planApproval: null,
        pausePrompt: null,
      };
      return trimTimeline(endState);
    }

    case "TEXT_DELTA":
      return { ...state, markdownBuffer: state.markdownBuffer + action.content };

    // ── Code blocks ──
    case "CODE_BLOCK_START": {
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
      const completedBlock = { ...state.currentCodeBlock, complete: true };
      const [codeId, codeState] = nextTimelineId(state, "code");
      return {
        ...codeState,
        currentCodeBlock: null,
        timeline: [
          ...codeState.timeline,
          {
            type: "code" as const,
            id: codeId,
            language: completedBlock.language,
            content: completedBlock.content,
          },
        ],
      };
    }

    // ── Thinking ──
    case "THINKING_START": {
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
      const thinkingContent = state.currentThinking.content;
      const thinkingTokenCount = state.currentThinking.tokenCount;
      const [thinkId, thinkState] = nextTimelineId(state, "thinking");
      return {
        ...thinkState,
        currentThinking: null,
        timeline: [
          ...thinkState.timeline,
          {
            type: "thinking" as const,
            id: thinkId,
            content: thinkingContent,
            tokenCount: thinkingTokenCount,
          },
        ],
      };
    }

    // ── Messages ──
    case "ADD_USER_MESSAGE": {
      const userId = `user-${Date.now()}`;
      const userEntry: TimelineEntry = {
        type: "user_message" as const,
        id: userId,
        content: action.content,
        ...(action.attachments && action.attachments.length > 0 ? { attachments: action.attachments } : {}),
        ...(action.images && action.images.length > 0 ? { images: action.images } : {}),
      };
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: userId, role: "user", content: action.content, finalized: true },
        ],
        timeline: [
          ...state.timeline,
          userEntry,
        ],
      };
    }

    case "MESSAGE_ADDED": {
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
                timeline: [...sa.timeline, { type: "text" as const, index: sa.messages.length }],
              },
            },
          };
        }
        return state;
      }
      // Compaction summary: add as a special timeline entry, not a regular message
      if (!action.subagentId && action.data.is_compact_summary) {
        return {
          ...state,
          timeline: [
            ...state.timeline,
            { type: "compaction_summary" as const, id: action.data.uuid, content: action.data.content },
          ],
        };
      }
      if (action.data.role === "system" || action.data.role === "user" || action.data.role === "assistant") return state;
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
      if (action.subagentId) {
        const sa = state.subagents[action.subagentId];
        if (sa) {
          const updatedMessages = [...sa.messages];
          if (updatedMessages.length > 0) {
            updatedMessages[updatedMessages.length - 1] = action.data.content;
          }
          return {
            ...state,
            subagents: { ...state.subagents, [action.subagentId]: { ...sa, messages: updatedMessages } },
          };
        }
        return state;
      }
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.data.uuid ? { ...m, content: action.data.content } : m
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

      const existingCard = state.toolCards[callId];
      const mergedData = existingCard
        ? {
            ...existingCard,
            ...action.data,
            tool_name: action.data.tool_name || existingCard.tool_name,
            arguments: action.data.arguments ?? existingCard.arguments,
          }
        : action.data;

      const toolCardOwners = subagentId && isNew
        ? { ...state.toolCardOwners, [callId]: subagentId }
        : state.toolCardOwners;

      let subagents = state.subagents;
      if (subagentId && subagents[subagentId]) {
        const sa = subagents[subagentId];
        const tokenUpdate: Partial<typeof sa> = {};
        // Update context tokens from metadata (sent with every RUNNING tool_state)
        if (action.data.context_tokens != null) {
          tokenUpdate.contextTokens = action.data.context_tokens;
        }
        subagents = {
          ...subagents,
          [subagentId]: {
            ...sa,
            ...tokenUpdate,
            ...(isNew ? {
              toolCount: sa.toolCount + 1,
              timeline: [...sa.timeline, { type: "tool" as const, callId }],
            } : {}),
          },
        };
      }

      let promotedApprovals = state.promotedApprovals;
      if (subagentId && action.data.status === "awaiting_approval") {
        promotedApprovals = { ...promotedApprovals, [callId]: { data: mergedData, subagentId } };
      } else if (callId in promotedApprovals && action.data.status !== "awaiting_approval") {
        const { [callId]: _, ...rest } = promotedApprovals;
        promotedApprovals = rest;
      }

      let baseState = state;
      let timeline = state.timeline;
      if (isNew && !subagentId && !SILENT_TOOLS.has(mergedData.tool_name ?? "")) {
        baseState = commitMarkdownBuffer(state);
        const [toolId, toolState] = nextTimelineId(baseState, "tool");
        baseState = toolState;
        timeline = [
          ...toolState.timeline,
          { type: "tool" as const, id: toolId, callId },
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
      const flushed = commitMarkdownBuffer(state);
      const [saId, saState] = nextTimelineId(flushed, "subagent");
      return {
        ...saState,
        subagents: {
          ...saState.subagents,
          [action.data.subagentId]: { ...action.data, messages: action.data.messages ?? [], timeline: action.data.timeline ?? [] },
        },
        timeline: [
          ...saState.timeline,
          { type: "subagent" as const, id: saId, subagentId: action.data.subagentId },
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
          [action.subagentId]: { ...existingSa, active: false, finalElapsedMs: Date.now() - existingSa.startTime },
        },
      };
    }

    case "DISMISS_SUBAGENT_APPROVAL": {
      const { [action.callId]: _, ...rest } = state.promotedApprovals;
      return { ...state, promotedApprovals: rest };
    }

    // ── Interactive ──
    case "PAUSE_PROMPT_START":
      return { ...state, pausePrompt: { reason: action.reason, reasonCode: action.reasonCode, stats: action.stats, pendingTodos: action.pendingTodos } };
    case "PAUSE_PROMPT_END":
      return { ...state, pausePrompt: null };
    case "CLARIFY_REQUEST":
      return { ...state, clarifyRequest: { callId: action.callId, questions: action.questions, context: action.context } };
    case "CLARIFY_DISMISS":
      return { ...state, clarifyRequest: null };
    case "PLAN_APPROVAL":
      return { ...state, planApproval: { callId: action.callId, planHash: action.planHash, excerpt: action.excerpt, truncated: action.truncated, planPath: action.planPath, isDirector: action.isDirector } };
    case "PLAN_APPROVAL_DISMISS":
      return { ...state, planApproval: null };
    case "PERMISSION_MODE_CHANGED":
      return { ...state, permissionMode: action.mode };

    // ── Context ──
    case "CONTEXT_UPDATED":
      return {
        ...state,
        contextUsed: action.used,
        contextLimit: action.limit,
        ...(action.iteration != null ? { lastIterations: action.iteration } : {}),
      };
    case "CONTEXT_COMPACTING":
      return { ...state, isCompacting: true };
    case "CONTEXT_COMPACTED":
      return { ...state, isCompacting: false };

    // ── Panels ──
    case "SET_CHAT_DRAFT":
      return { ...state, chatDraft: action.draft };
    case "SET_ACTIVE_PANEL":
      return { ...state, activePanel: action.panel };
    case "SET_SESSIONS":
      return { ...state, sessions: action.sessions };

    case "REPLAY_MESSAGES": {
      const replayTimeline: TimelineEntry[] = [];
      const replayToolCards: Record<string, ToolStateData> = {};
      const replayToolOrder: string[] = [];
      const replayMessages: ChatMessage[] = [];

      let replayCounter = state.timelineCounter;
      const replayNonce = state.sessionNonce;
      const replayId = (prefix: string): string => {
        replayCounter++;
        return `${prefix}-${replayCounter}-${replayNonce}`;
      };

      for (let i = 0; i < action.messages.length; i++) {
        const m = action.messages[i];
        if (m.role === "system") continue;

        const msgId = `replay-${i}`;
        replayMessages.push({ id: msgId, role: m.role as "user" | "assistant" | "system", content: m.content, finalized: true });

        if (m.role === "user") {
          const userEntry: TimelineEntry = { type: "user_message", id: msgId, content: m.content };
          if (m.images && m.images.length > 0) userEntry.images = m.images;
          if (m.attachments && m.attachments.length > 0) userEntry.attachments = m.attachments;
          replayTimeline.push(userEntry);
        } else if (m.role === "assistant") {
          if (m.tool_calls && m.tool_calls.length > 0) {
            if (m.content.trim()) {
              replayTimeline.push({ type: "assistant_text", id: replayId("replay-text"), content: m.content });
            }
            for (const tc of m.tool_calls) {
              let parsedArgs: Record<string, unknown> = {};
              try { parsedArgs = JSON.parse(tc.function.arguments); } catch { /* empty */ }
              const toolData: ToolStateData = { call_id: tc.id, tool_name: tc.function.name, status: "pending", arguments: parsedArgs };
              replayToolCards[tc.id] = toolData;
              replayToolOrder.push(tc.id);
              replayTimeline.push({ type: "tool", id: replayId("replay-tool"), callId: tc.id });
            }
          } else if (m.content.trim()) {
            replayTimeline.push({ type: "assistant_text", id: replayId("replay-text"), content: m.content });
          }
        } else if (m.role === "tool" && m.tool_call_id) {
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

      return trimTimeline({
        ...state,
        messages: replayMessages,
        timeline: replayTimeline,
        toolCards: { ...state.toolCards, ...replayToolCards },
        toolOrder: [...state.toolOrder, ...replayToolOrder],
        timelineCounter: replayCounter,
      });
    }

    // ── Simple state updates ──
    case "AUTO_APPROVE_CHANGED":
      return { ...state, autoApprove: { read: !!action.categories.read, edit: !!action.categories.edit, execute: !!action.categories.execute, browser: !!action.categories.browser, knowledge_update: !!action.categories.knowledge_update, subagent: !!action.categories.subagent } };
    case "TODOS_UPDATED":
      return { ...state, todos: action.todos };
    case "BACKGROUND_TASKS_UPDATED": {
      // Preserve client-side dismissals: don't re-add tasks the user dismissed
      const dismissed = state._dismissedBgTasks;
      const filtered = dismissed.size > 0
        ? action.tasks.filter((t) => !dismissed.has(t.task_id))
        : action.tasks;
      return { ...state, backgroundTasks: filtered };
    }
    case "DISMISS_BACKGROUND_TASK":
      return {
        ...state,
        backgroundTasks: state.backgroundTasks.filter((t) => t.task_id !== action.taskId),
        _dismissedBgTasks: new Set([...state._dismissedBgTasks, action.taskId]),
      };
    case "ADD_ATTACHMENT":
      return { ...state, attachments: [...state.attachments, action.attachment] };
    case "REMOVE_ATTACHMENT":
      return { ...state, attachments: state.attachments.filter((_, i) => i !== action.index) };
    case "ADD_IMAGE":
      return { ...state, images: [...state.images, action.image] };
    case "REMOVE_IMAGE":
      return { ...state, images: state.images.filter((_, i) => i !== action.index) };
    case "CLEAR_INPUT":
      return { ...state, attachments: [], images: [], mentionResults: [] };
    case "SET_MENTION_RESULTS":
      return { ...state, mentionResults: action.files };
    case "UNDO_AVAILABLE":
      return { ...state, undoAvailable: { turnId: action.turnId, files: action.files }, undoCompleted: false };
    case "UNDO_COMPLETE":
      return { ...state, undoCompleted: true };
    case "CONFIG_LOADED":
      return { ...state, configData: action.config, configSubagentNames: action.subagentNames, configNotification: null };
    case "MODELS_LIST":
      return { ...state, configModels: { models: action.models, error: action.error } };
    case "CONFIG_SAVED":
      return { ...state, configNotification: { message: action.message, success: action.success }, modelName: action.success && action.model ? action.model : state.modelName };
    case "JIRA_PROFILES":
      return { ...state, jiraProfiles: action.profiles, jiraConnectedProfile: action.connectedProfile, jiraNotification: action.error ? { message: action.error, success: false } : state.jiraNotification };
    case "JIRA_NOTIFICATION":
      return { ...state, jiraNotification: { message: action.message, success: action.success } };
    case "JIRA_CONNECTED":
      return { ...state, jiraConnectedProfile: action.success ? action.profile : state.jiraConnectedProfile, jiraNotification: { message: action.message, success: action.success } };

    // ── MCP ──
    case "MCP_SERVERS_LIST":
      return { ...state, mcpServers: action.servers, mcpNotification: action.notification ?? state.mcpNotification };
    case "MCP_MARKETPLACE_RESULTS":
      return {
        ...state,
        mcpMarketplace: action.page > 1
          ? [...state.mcpMarketplace, ...action.entries]
          : action.entries,
        mcpMarketplaceMeta: { totalCount: action.totalCount, page: action.page, hasNext: action.hasNext },
      };
    case "MCP_NOTIFICATION":
      return { ...state, mcpNotification: { message: action.message, success: action.success } };

    // ── ClarAIty Knowledge & Beads ──
    case "BEADS_LOADED":
      return { ...state, beadsData: action.data };
    case "ARCHITECTURE_LOADED":
      return { ...state, architectureData: action.data };
    case "TRACE_LOADED":
      return { ...state, traceSteps: action.steps };
    case "TRACE_ENABLED":
      return { ...state, traceEnabled: action.enabled };

    // ── Subagents panel ──
    case "SUBAGENTS_LIST":
      return { ...state, subagentsList: action.subagents, subagentsAvailableTools: action.availableTools };
    case "SUBAGENT_NOTIFICATION":
      return { ...state, subagentNotification: { message: action.message, success: action.success } };
    case "CLEAR_SUBAGENT_NOTIFICATION":
      return { ...state, subagentNotification: null };

    // ── Limits ──
    case "LIMITS_LOADED":
      return { ...state, limits: action.limits };
    case "LIMITS_SAVED":
      return { ...state, ...(action.limits ? { limits: action.limits } : {}) };

    // ── Prompt Enrichment ──
    case "SET_ENRICHMENT_ENABLED":
      return { ...state, promptEnrichmentEnabled: action.enabled, enrichedPromptPreview: null, enrichedPromptOriginal: null, enrichmentLoading: false };
    case "SET_ENRICHMENT_LOADING":
      return { ...state, enrichmentLoading: action.loading };
    case "ENRICHMENT_DELTA":
      // First delta clears the loading spinner and starts accumulating live text
      return { ...state, enrichmentLoading: false, enrichedPromptPreview: (state.enrichedPromptPreview ?? "") + action.delta };
    case "ENRICHMENT_COMPLETE":
      // Final message — replace accumulated preview with the canonical full text
      return { ...state, enrichedPromptPreview: action.enriched, enrichedPromptOriginal: action.original, enrichmentLoading: false };
    case "CLEAR_ENRICHED_PREVIEW":
      return { ...state, enrichedPromptPreview: null, enrichedPromptOriginal: null, enrichmentLoading: false };

    // ── Error ──
    case "ERROR": {
      const flushed = commitMarkdownBuffer(state);
      const [errId, errState] = nextTimelineId(flushed, "error");
      return {
        ...errState,
        timeline: [
          ...errState.timeline,
          { type: "error" as const, id: errId, message: action.message },
        ],
      };
    }

    default:
      return state;
  }
}
