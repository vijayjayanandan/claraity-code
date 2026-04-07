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
      dispatch({ type: "CONTEXT_UPDATED", used: msg.used, limit: msg.limit, iteration: msg.iteration });
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

    // ── Background tasks ──
    case "background_tasks_updated":
      dispatch({ type: "BACKGROUND_TASKS_UPDATED", tasks: msg.tasks });
      break;

    // ── Auto-approve ──
    case "auto_approve_changed":
      dispatch({ type: "AUTO_APPROVE_CHANGED", categories: msg.categories });
      break;

    // ── Limits ──
    case "limits_loaded":
      dispatch({ type: "LIMITS_LOADED", limits: msg.limits });
      break;
    case "limits_saved":
      dispatch({ type: "LIMITS_SAVED", success: msg.success, message: msg.message, limits: msg.limits });
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
            timeline: [],
            contextTokens: 0,
            contextWindow: msg.data.context_window ?? 0,
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

    // ── MCP ──
    case "mcp_servers_list": {
      const msl = msg as { servers: unknown[]; notification?: { message: string; success: boolean } };
      dispatch({
        type: "MCP_SERVERS_LIST",
        servers: (msl.servers ?? []) as import("../types").McpServerInfo[],
        notification: msl.notification,
      });
      break;
    }

    case "mcp_marketplace_results": {
      const mmr = msg as Record<string, unknown>;
      dispatch({
        type: "MCP_MARKETPLACE_RESULTS",
        entries: (mmr.entries ?? []) as import("../types").McpMarketplaceEntry[],
        totalCount: (mmr.totalCount as number) ?? 0,
        page: (mmr.page as number) ?? 1,
        hasNext: !!(mmr.hasNext),
      });
      break;
    }

    case "mcp_install_result": {
      const mir = msg as { status: string; server?: string; toolCount?: number; message?: string };
      const success = mir.status === "connected" || mir.status === "installed";
      const text = mir.status === "connected"
        ? `${mir.server} installed (${mir.toolCount ?? 0} tools)`
        : mir.message ?? `${mir.server} installed`;
      dispatch({ type: "MCP_NOTIFICATION", message: text, success });
      break;
    }

    case "mcp_uninstall_result": {
      const mur = msg as { status: string; server?: string };
      dispatch({
        type: "MCP_NOTIFICATION",
        message: mur.status === "uninstalled" ? `${mur.server} removed` : `Server not found`,
        success: mur.status === "uninstalled",
      });
      break;
    }

    // ── Subagents panel ──
    case "subagents_list":
      dispatch({ type: "SUBAGENTS_LIST", subagents: msg.subagents, availableTools: msg.available_tools ?? [] });
      break;

    case "subagent_saved":
      dispatch({ type: "SUBAGENT_NOTIFICATION", success: msg.success, message: msg.message });
      break;

    case "subagent_deleted":
      dispatch({ type: "SUBAGENT_NOTIFICATION", success: msg.success, message: msg.message });
      break;

    // ── ClarAIty Knowledge & Beads ──
    case "beads_data":
      dispatch({ type: "BEADS_LOADED", data: msg.data });
      break;

    case "architecture_data":
      dispatch({ type: "ARCHITECTURE_LOADED", data: msg.data });
      break;

    case "knowledge_approved":
      // Refresh architecture data to pick up new approval status
      break;

    case "context_compacting":
      dispatch({ type: "CONTEXT_COMPACTING" });
      break;
    case "context_compacted":
      dispatch({ type: "CONTEXT_COMPACTED" });
      break;

    // These are handled at a higher level or don't affect state
    case "session_info":
    case "file_read":
    case "execute_in_terminal":
      break;
  }
}
