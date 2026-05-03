/**
 * Root component for ClarAIty VS Code webview.
 *
 * Manages:
 * - Central state via useReducer
 * - PostMessage bridge via useVSCode hook
 * - Message dispatch from extension -> state
 * - Layout orchestration
 */
import { useEffect, useReducer, useMemo } from "react";
import { useVSCode } from "./hooks/useVSCode";
import { appReducer, initialState, dispatchServerMessage } from "./state/reducer";
import { ChatContext, type ChatContextValue } from "./state/ChatContext";
import { setCurrentSessionId } from "./state/currentContext";
import type { ExtensionMessage, FileAttachment, ImageAttachment } from "./types";

// StatusBar removed — icons now live in VS Code native view/title bar
import { ContextBar } from "./components/ContextBar";
import { ChatHistory } from "./components/ChatHistory";
import { TodoPanel } from "./components/TodoPanel";
import { BackgroundTaskPanel } from "./components/BackgroundTaskPanel";
import { AutoApprovePanel } from "./components/AutoApprovePanel";
import { StreamingStatus } from "./components/StreamingStatus";
import { InputBox } from "./components/InputBox";
import { BottomBar } from "./components/BottomBar";
import { SessionPanel } from "./components/SessionPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { JiraPanel } from "./components/JiraPanel";
import { MCPPanel } from "./components/MCPPanel";
import { BeadsPanel } from "./components/BeadsPanel";
import { ArchitecturePanel } from "./components/ArchitecturePanel";
import { SubagentsPanel } from "./components/SubagentsPanel";
import { TracePanel } from "./components/TracePanel";

export function App() {
  const [state, dispatch] = useReducer(appReducer, initialState);

  const { postMessage, onReady } = useVSCode((msg: ExtensionMessage) => {
    switch (msg.type) {
      case "connectionStatus": {
        const wasConnected = state.connected;
        const nowConnected = msg.status === "connected";
        dispatch({ type: "SET_CONNECTED", connected: nowConnected });

        // Stuck-streaming recovery: if connection drops during active stream,
        // force-end the stream and show an error so UI doesn't hang forever
        if (wasConnected && !nowConnected && state.isStreaming) {
          dispatch({ type: "STREAM_END" });
          dispatch({
            type: "ERROR",
            errorType: "connection_lost",
            message: "Connection to agent lost during streaming. The agent may have crashed.",
          });
        }
        break;
      }

      case "sessionInfo":
        setCurrentSessionId(msg.sessionId);
        dispatch({
          type: "SET_SESSION_INFO",
          sessionId: msg.sessionId,
          model: msg.model,
          permissionMode: msg.permissionMode,
          autoApprove: msg.autoApproveCategories,
          limits: msg.limits,
        });
        // Fetch available skills on connection
        postMessage({ type: "getSkills" });
        break;

      case "sessionsList":
        dispatch({ type: "SET_SESSIONS", sessions: msg.sessions });
        break;

      case "sessionHistory":
        dispatch({ type: "REPLAY_MESSAGES", messages: msg.messages });
        dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" });
        break;

      case "fileSearchResults":
        dispatch({ type: "SET_MENTION_RESULTS", files: msg.files });
        break;

      case "fileSelected":
        dispatch({ type: "ADD_ATTACHMENT", attachment: { path: msg.path, name: msg.name } });
        break;

      case "undoAvailable":
        dispatch({ type: "UNDO_AVAILABLE", turnId: msg.turnId, files: msg.files });
        break;

      case "undoComplete":
        dispatch({ type: "UNDO_COMPLETE", turnId: msg.turnId });
        break;

      case "showSessionHistory":
        postMessage({ type: "listSessions" });
        dispatch({ type: "SET_ACTIVE_PANEL", panel: "sessions" });
        break;

      case "showConfig":
        dispatch({ type: "SET_ACTIVE_PANEL", panel: "config" });
        break;

      case "showMcp":
        dispatch({ type: "SET_ACTIVE_PANEL", panel: "mcp" });
        break;

      case "showSubagents":
        postMessage({ type: "listSubagents" });
        dispatch({ type: "SET_ACTIVE_PANEL", panel: "subagents" });
        break;

      case "insertAndSend":
        // Add to timeline locally first, then send to server (GAP 18)
        dispatch({ type: "ADD_USER_MESSAGE", content: msg.content });
        postMessage({ type: "chatMessage", content: msg.content });
        break;

      case "enrichmentDelta":
        dispatch({ type: "ENRICHMENT_DELTA", delta: msg.delta });
        break;

      case "enrichmentComplete":
        dispatch({ type: "ENRICHMENT_COMPLETE", original: msg.original, enriched: msg.enriched });
        break;

      case "enrichmentError":
        dispatch({ type: "CLEAR_ENRICHED_PREVIEW" });
        dispatch({ type: "ERROR", errorType: "enrichment_error", message: msg.message ?? "Prompt enrichment failed." });
        break;

      case "toggleSearch":
        dispatch({ type: "TOGGLE_SEARCH" });
        break;

      case "traceData":
        dispatch({ type: "TRACE_LOADED", steps: msg.steps });
        break;

      case "traceEnabled":
        dispatch({ type: "TRACE_ENABLED", enabled: msg.enabled });
        break;

      case "toolList":
        dispatch({ type: "TOOL_LIST_LOADED", tools: msg.tools });
        break;

      case "serverMessage":
        dispatchServerMessage(dispatch, msg.payload);

        // Surface delete failures to the user
        if (msg.payload.type === "session_deleted" && !msg.payload.success) {
          dispatch({
            type: "ERROR",
            errorType: "session_delete_error",
            message: msg.payload.message ?? "Failed to delete session.",
          });
        }

        // Handle session_info at top level (not in reducer)
        if (msg.payload.type === "session_info") {
          dispatch({
            type: "SET_SESSION_INFO",
            sessionId: msg.payload.session_id,
            model: msg.payload.model_name,
            permissionMode: msg.payload.permission_mode,
            workingDirectory: msg.payload.working_directory,
            autoApprove: msg.payload.auto_approve_categories,
          });
        }
        break;
    }
  });

  // Signal readiness on mount
  useEffect(() => {
    onReady();
  }, [onReady]);

  const handleSendMessage = (content: string, attachments?: FileAttachment[], images?: ImageAttachment[]) => {
    const resolvedAttachments = attachments ?? state.attachments;
    const resolvedImages = images ?? state.images;
    dispatch({
      type: "ADD_USER_MESSAGE",
      content,
      attachments: resolvedAttachments.length > 0 ? resolvedAttachments : undefined,
      images: resolvedImages.length > 0 ? resolvedImages : undefined,
    });
    postMessage({
      type: "chatMessage",
      content,
      attachments: resolvedAttachments.length > 0 ? resolvedAttachments : undefined,
      images: resolvedImages.length > 0 ? resolvedImages : undefined,
      activeSkill: state.activeSkill || undefined,
    });
    dispatch({ type: "CLEAR_INPUT" });
  };

  const handleInterrupt = () => {
    postMessage({ type: "interrupt" });
  };

  // Escape key: stops the stream (priority) or closes search bar.
  // Uses capture phase so the webview catches it before VS Code can intercept it at the iframe level.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (state.isStreaming) {
          e.preventDefault();
          postMessage({ type: "interrupt" });
        } else if (state.searchOpen) {
          e.preventDefault();
          dispatch({ type: "CLOSE_SEARCH" });
        }
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [state.isStreaming, state.searchOpen, postMessage]);

  // Memoized context value for ChatHistory's child components
  const chatContextValue = useMemo<ChatContextValue>(() => ({
    postMessage,
    toolCards: state.toolCards,
    toolOrder: state.toolOrder,
    toolCardOwners: state.toolCardOwners,
    subagents: state.subagents,
    promotedApprovals: state.promotedApprovals,
    onDismissApproval: (callId: string) => dispatch({ type: "DISMISS_SUBAGENT_APPROVAL", callId }),
  }), [postMessage, state.toolCards, state.toolOrder, state.toolCardOwners, state.subagents, state.promotedApprovals]);

  // Session panel view
  if (state.activePanel === "sessions") {
    return (
      <div className="app">
        <SessionPanel
          sessions={state.sessions}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          onNewSession={() => postMessage({ type: "newSession" })}
          onResumeSession={(id) => postMessage({ type: "resumeSession", sessionId: id })}
          onDeleteSession={(id) => postMessage({ type: "deleteSession", sessionId: id })}
        />
      </div>
    );
  }

  // Config panel view
  if (state.activePanel === "config") {
    return (
      <div className="app">
        <ConfigPanel
          postMessage={postMessage}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          configData={state.configData}
          configSubagentNames={state.configSubagentNames}
          configModels={state.configModels}
          configNotification={state.configNotification}
        />
      </div>
    );
  }

  // Jira panel view
  if (state.activePanel === "jira") {
    return (
      <div className="app">
        <JiraPanel
          postMessage={postMessage}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          profiles={state.jiraProfiles}
          connectedProfile={state.jiraConnectedProfile}
          notification={state.jiraNotification}
        />
      </div>
    );
  }

  // MCP panel view
  if (state.activePanel === "mcp") {
    return (
      <div className="app">
        <MCPPanel
          postMessage={postMessage}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          servers={state.mcpServers}
          marketplace={state.mcpMarketplace}
          marketplaceMeta={state.mcpMarketplaceMeta}
          notification={state.mcpNotification}
        />
      </div>
    );
  }

  // Architecture panel view
  if (state.activePanel === "architecture") {
    return (
      <div className="app">
        <ArchitecturePanel
          data={state.architectureData}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          onRefresh={() => postMessage({ type: "getArchitecture" })}
          onDiscuss={(message) => {
            const { question, context } = JSON.parse(message);
            dispatch({ type: "ADD_USER_MESSAGE", content: question });
            postMessage({ type: "chatMessage", content: question, systemContext: context });
            dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" });
          }}
          onReview={(reviewedBy, status, comments) => {
            postMessage({ type: "approveKnowledge", approvedBy: reviewedBy, status, comments });
            setTimeout(() => postMessage({ type: "getArchitecture" }), 500);
          }}
          onOpenFile={(path) => postMessage({ type: "openFile", path })}
          onExport={() => postMessage({ type: "exportKnowledge" })}
          onScan={() => {
            const userMsg = "Scan this codebase and build the architecture knowledge graph.";
            const systemContext = "The user clicked 'Scan Codebase' from the Architecture panel. " +
              "Delegate this to the knowledge-builder subagent to scan the project and populate " +
              "the ClarAIty knowledge database with modules, components, files, data flows, and relationships.";
            dispatch({ type: "ADD_USER_MESSAGE", content: userMsg });
            postMessage({ type: "chatMessage", content: userMsg, systemContext });
            dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" });
          }}
          onImport={() => postMessage({ type: "importKnowledge" })}
        />
      </div>
    );
  }

  // Trace panel view
  if (state.activePanel === "trace") {
    return (
      <div className="app">
        <TracePanel
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          steps={state.traceSteps}
          traceEnabled={state.traceEnabled}
          onToggleTrace={(enabled) => postMessage({ type: "setTraceEnabled", enabled })}
          onClearTrace={() => postMessage({ type: "clearTrace", sessionId: state.sessionId })}
          toolList={state.toolList}
          onGetToolList={() => postMessage({ type: "getToolList" })}
        />
      </div>
    );
  }

  // Subagents panel view
  if (state.activePanel === "subagents") {
    return (
      <div className="app">
        <SubagentsPanel
          postMessage={postMessage}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          subagents={state.subagentsList}
          availableTools={state.subagentsAvailableTools}
          notification={state.subagentNotification}
          onClearNotification={() => dispatch({ type: "CLEAR_SUBAGENT_NOTIFICATION" })}
        />
      </div>
    );
  }

  // Beads panel view
  if (state.activePanel === "beads") {
    return (
      <div className="app">
        <BeadsPanel
          data={state.beadsData}
          onBack={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "chat" })}
          onRefresh={() => postMessage({ type: "getBeads" })}
        />
      </div>
    );
  }

  // Main chat view
  return (
    <div className="app">
      {state.contextLimit > 0 && (
        <ContextBar
          used={state.contextUsed}
          limit={state.contextLimit}
          totalTokens={state.sessionTotalTokens}
          turnCount={state.sessionTurnCount}
          modelName={state.modelName}
        />
      )}

      <ChatContext.Provider value={chatContextValue}>
        <ChatHistory
          timeline={state.timeline}
          isStreaming={state.isStreaming}
          markdownBuffer={state.markdownBuffer}
          currentThinking={state.currentThinking}
          currentCodeBlock={state.currentCodeBlock}
          pausePrompt={state.pausePrompt}
          clarifyRequest={state.clarifyRequest}
          planApproval={state.planApproval}
          undoAvailable={state.undoAvailable}
          undoCompleted={state.undoCompleted}
          lastTurnStats={state.lastTurnStats}
          onSendPrompt={(prompt) => handleSendMessage(prompt)}
          onDismissClarify={() => dispatch({ type: "CLARIFY_DISMISS" })}
          onDismissPlan={() => dispatch({ type: "PLAN_APPROVAL_DISMISS" })}
          onOpenSettings={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "config" })}
          connected={state.connected}
          modelName={state.modelName}
          workingDirectory={state.workingDirectory}
          searchOpen={state.searchOpen}
          searchQuery={state.searchQuery}
          onSearchQuery={(q) => dispatch({ type: "SET_SEARCH_QUERY", query: q })}
          onSearchClose={() => dispatch({ type: "CLOSE_SEARCH" })}
        />
      </ChatContext.Provider>

      <AutoApprovePanel
        autoApprove={state.autoApprove}
        onChange={(categories) =>
          postMessage({ type: "setAutoApprove", categories })
        }
        limits={state.limits}
        onSaveLimits={(limits) => postMessage({ type: "saveLimits", limits })}
        onLoadLimits={() => postMessage({ type: "getLimits" })}
        lastIterations={state.lastIterations}
      />

      {state.todos.length > 0 && (
        <TodoPanel todos={state.todos} />
      )}

      {state.backgroundTasks.length > 0 && (
        <BackgroundTaskPanel
          tasks={state.backgroundTasks}
          onCancel={(taskId) => postMessage({ type: "cancelBackgroundTask", taskId })}
          onDismiss={(taskId) => dispatch({ type: "DISMISS_BACKGROUND_TASK", taskId })}
        />
      )}

      <StreamingStatus
        isStreaming={state.isStreaming}
        isCompacting={state.isCompacting}
        currentThinking={state.currentThinking}
        toolCards={state.toolCards}
      />

      <InputBox
        isStreaming={state.isStreaming}
        connected={state.connected}
        attachments={state.attachments}
        images={state.images}
        mentionResults={state.mentionResults}
        onSend={handleSendMessage}
        onInterrupt={handleInterrupt}
        onAddAttachment={(a) => dispatch({ type: "ADD_ATTACHMENT", attachment: a })}
        onRemoveAttachment={(i) => dispatch({ type: "REMOVE_ATTACHMENT", index: i })}
        onAddImage={(img) => dispatch({ type: "ADD_IMAGE", image: img })}
        onRemoveImage={(i) => dispatch({ type: "REMOVE_IMAGE", index: i })}
        onSearchFiles={(query) => postMessage({ type: "searchFiles", query })}
        postMessage={postMessage}
        enrichmentEnabled={state.promptEnrichmentEnabled}
        enrichmentLoading={state.enrichmentLoading}
        enrichedPreview={state.enrichedPromptPreview}
        enrichedOriginal={state.enrichedPromptOriginal}
        onToggleEnrichment={(enabled) => dispatch({ type: "SET_ENRICHMENT_ENABLED", enabled })}
        onRequestEnrichment={(content) => {
          dispatch({ type: "SET_ENRICHMENT_LOADING", loading: true });
          // Send the last 6 finalized user/assistant messages as context so the
          // enrichment LLM understands what the conversation is already about.
          const history = state.messages
            .filter((m) => m.finalized && (m.role === "user" || m.role === "assistant"))
            .slice(-6)
            .map((m) => ({ role: m.role, content: m.content }));
          postMessage({ type: "enrichPrompt", content, history: history.length > 0 ? history : undefined });
        }}
        onClearEnrichment={() => dispatch({ type: "CLEAR_ENRICHED_PREVIEW" })}
        draft={state.chatDraft}
        onDraftChange={(draft) => dispatch({ type: "SET_CHAT_DRAFT", draft })}
        skillsList={state.skillsList}
        activeSkill={state.activeSkill}
        onSelectSkill={(skillId) => dispatch({ type: "SELECT_SKILL", skillId })}
        onRequestSkills={() => postMessage({ type: "getSkills" })}
        onCreateSkill={() => {
          handleSendMessage("I want to create a new skill. Help me define it.");
        }}
      />

      <BottomBar
        connected={state.connected}
        modelName={state.modelName}
        permissionMode={state.permissionMode}
        onSetMode={(mode) => {
          postMessage({ type: "setMode", mode });
        }}
        onShowArchitecture={() => {
          postMessage({ type: "getArchitecture" });
          dispatch({ type: "SET_ACTIVE_PANEL", panel: "architecture" });
        }}
        onShowBeads={() => {
          postMessage({ type: "getBeads" });
          dispatch({ type: "SET_ACTIVE_PANEL", panel: "beads" });
        }}
        onShowTrace={() => {
          postMessage({ type: "getTrace", sessionId: state.sessionId });
          postMessage({ type: "getTraceEnabled" });
          dispatch({ type: "SET_ACTIVE_PANEL", panel: "trace" });
        }}
        beadsReadyCount={state.beadsData?.ready.length}
        onDisconnect={() => postMessage({ type: "disconnectServer" })}
        onReconnect={() => postMessage({ type: "reconnectServer" })}
      />
    </div>
  );
}
