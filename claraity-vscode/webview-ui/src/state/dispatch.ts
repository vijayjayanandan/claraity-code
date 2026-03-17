/**
 * ServerMessage -> Action dispatcher.
 *
 * Maps wire protocol messages from the Python agent into reducer actions.
 * This is the translation layer between the server's snake_case JSON
 * and the webview's camelCase React state.
 */
import type { ServerMessage, JiraProfile } from "../types";
import type { Action } from "./actions";

export function dispatchServerMessage(
  dispatch: React.Dispatch<Action>,
  msg: ServerMessage,
): void {
  switch (msg.type) {
    // ── Streaming ──
    case "stream_start":
      dispatch({ type: "STREAM_START" });
      break;

    case "stream_end":
      dispatch({ type: "STREAM_END", tokens: msg.total_tokens, durationMs: msg.duration_ms });
      break;

    case "text_delta":
      dispatch({ type: "TEXT_DELTA", content: msg.content });
      break;

    // ── Code blocks ──
    case "code_block_start":
      dispatch({ type: "CODE_BLOCK_START", language: msg.language });
      break;

    case "code_block_delta":
      dispatch({ type: "CODE_BLOCK_DELTA", content: msg.content });
      break;

    case "code_block_end":
      dispatch({ type: "CODE_BLOCK_END" });
      break;

    // ── Thinking ──
    case "thinking_start":
      dispatch({ type: "THINKING_START" });
      break;

    case "thinking_delta":
      dispatch({ type: "THINKING_DELTA", content: msg.content });
      break;

    case "thinking_end":
      dispatch({ type: "THINKING_END" });
      break;

    // ── Context ──
    case "context_updated":
      dispatch({ type: "CONTEXT_UPDATED", used: msg.used, limit: msg.limit });
      break;

    // ── Pause ──
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

    // ── Error ──
    case "error":
      dispatch({ type: "ERROR", errorType: msg.error_type, message: msg.user_message });
      break;

    // ── Todos ──
    case "todos_updated":
      dispatch({ type: "TODOS_UPDATED", todos: msg.todos });
      break;

    // ── Auto-approve ──
    case "auto_approve_changed":
      dispatch({ type: "AUTO_APPROVE_CHANGED", categories: msg.categories });
      break;

    // ── Sessions ──
    case "sessions_list":
      dispatch({ type: "SET_SESSIONS", sessions: msg.sessions });
      break;

    case "session_history":
      dispatch({ type: "REPLAY_MESSAGES", messages: msg.messages });
      break;

    // ── Store events ──
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

    // ── Interactive events ──
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

    // ── Subagent lifecycle ──
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

    // ── Config ──
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

    // ── Jira ──
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
