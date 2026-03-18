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
import type { ExtensionMessage } from "./types";

import { StatusBar } from "./components/StatusBar";
import { ContextBar } from "./components/ContextBar";
import { ChatHistory } from "./components/ChatHistory";
import { TodoPanel } from "./components/TodoPanel";
import { AutoApprovePanel } from "./components/AutoApprovePanel";
import { StreamingStatus } from "./components/StreamingStatus";
import { InputBox } from "./components/InputBox";
import { BottomBar } from "./components/BottomBar";
import { SessionPanel } from "./components/SessionPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { JiraPanel } from "./components/JiraPanel";

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
        });
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

      case "insertAndSend":
        // Add to timeline locally first, then send to server (GAP 18)
        dispatch({ type: "ADD_USER_MESSAGE", content: msg.content });
        postMessage({ type: "chatMessage", content: msg.content });
        break;

      case "serverMessage":
        dispatchServerMessage(dispatch, msg.payload);

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

  const handleSendMessage = (content: string, attachments?: unknown[], images?: unknown[]) => {
    dispatch({ type: "ADD_USER_MESSAGE", content });
    postMessage({
      type: "chatMessage",
      content,
      attachments: (attachments ?? state.attachments) as never[],
      images: (images ?? state.images) as never[],
    });
    dispatch({ type: "CLEAR_INPUT" });
  };

  const handleInterrupt = () => {
    postMessage({ type: "interrupt" });
  };

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

  // Main chat view
  return (
    <div className="app">
      <StatusBar
        onNewChat={() => postMessage({ type: "newSession" })}
        onShowHistory={() => {
          postMessage({ type: "listSessions" });
          dispatch({ type: "SET_ACTIVE_PANEL", panel: "sessions" });
        }}
        onShowConfig={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "config" })}
        onShowJira={() => dispatch({ type: "SET_ACTIVE_PANEL", panel: "jira" })}
      />

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
          connected={state.connected}
          modelName={state.modelName}
          workingDirectory={state.workingDirectory}
        />
      </ChatContext.Provider>

      <AutoApprovePanel
        autoApprove={state.autoApprove}
        onChange={(categories) =>
          postMessage({ type: "setAutoApprove", categories })
        }
      />

      {state.todos.length > 0 && (
        <TodoPanel todos={state.todos} />
      )}

      <StreamingStatus
        isStreaming={state.isStreaming}
        currentThinking={state.currentThinking}
        toolCards={state.toolCards}
        todos={state.todos}
      />

      <InputBox
        isStreaming={state.isStreaming}
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
      />

      <BottomBar
        connected={state.connected}
        modelName={state.modelName}
        permissionMode={state.permissionMode}
        onSetMode={(mode) => postMessage({ type: "setMode", mode })}
      />
    </div>
  );
}
