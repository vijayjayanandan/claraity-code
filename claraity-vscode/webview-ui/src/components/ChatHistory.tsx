/**
 * Scrollable chat history.
 *
 * Renders the timeline — an ordered sequence of user messages, assistant text,
 * tool cards, thinking blocks, code blocks, subagent cards, and errors.
 *
 * After the timeline, renders currently-streaming elements (thinking, code,
 * markdown buffer), interactive widgets, undo bar, and turn stats.
 *
 * Auto-scrolls to bottom unless the user has scrolled up.
 */
import { useRef, useEffect, useCallback, useMemo, useState, memo } from "react";
import type {
  TimelineEntry,
  ThinkingBlock as ThinkingBlockType,
  CodeBlock as CodeBlockType,
} from "../state/reducer";
import { useChatContext } from "../state/ChatContext";
import type { ToolStateData } from "../types";
import { renderMarkdown } from "../utils/markdown";
import { MessageBubble } from "./MessageBubble";
import { ToolCard } from "./ToolCard";
import { SubagentCard } from "./SubagentCard";
import { SubagentApprovalWidget } from "./SubagentApprovalWidget";
import { CodeBlock } from "./CodeBlock";
import { ThinkingBlock } from "./ThinkingBlock";
import { PauseWidget } from "./PauseWidget";
import { ClarifyWidget } from "./ClarifyWidget";
import { PlanWidget } from "./PlanWidget";
import { UndoBar } from "./UndoBar";
import { TurnStats } from "./TurnStats";
import { WelcomeScreen } from "./WelcomeScreen";

interface ChatHistoryProps {
  timeline: TimelineEntry[];
  isStreaming: boolean;
  markdownBuffer: string;
  currentThinking: ThinkingBlockType | null;
  currentCodeBlock: CodeBlockType | null;
  pausePrompt: {
    reason: string;
    reasonCode: string;
    stats: Record<string, unknown>;
    pendingTodos?: string[];
  } | null;
  clarifyRequest: {
    callId: string;
    questions: unknown[];
    context?: string;
  } | null;
  planApproval: {
    callId: string;
    planHash: string;
    excerpt: string;
    truncated: boolean;
    planPath?: string;
    isDirector?: boolean;
  } | null;
  undoAvailable: { turnId: string; files: string[] } | null;
  undoCompleted: boolean;
  lastTurnStats: { tokens: number; durationMs: number } | null;
  onSendPrompt?: (prompt: string) => void;
  connected?: boolean;
  modelName?: string;
  workingDirectory?: string;
}

export function ChatHistory({
  timeline,
  isStreaming,
  markdownBuffer,
  currentThinking,
  currentCodeBlock,
  pausePrompt,
  clarifyRequest,
  planApproval,
  undoAvailable,
  undoCompleted,
  lastTurnStats,
  onSendPrompt,
  connected,
  modelName,
  workingDirectory,
}: ChatHistoryProps) {
  const { postMessage, toolCards, toolOrder, toolCardOwners, subagents, promotedApprovals, onDismissApproval } = useChatContext();
  const containerRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);
  const [showScrollPill, setShowScrollPill] = useState(false);
  const showScrollPillRef = useRef(false);

  // Auto-scroll to bottom
  const scrollToBottom = useCallback(() => {
    if (!userScrolledUp.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, []);

  // Detect user scroll
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    userScrolledUp.current = !atBottom;
    if (atBottom && showScrollPillRef.current) {
      showScrollPillRef.current = false;
      setShowScrollPill(false);
    }
  }, []);

  // Auto-scroll on content changes
  useEffect(() => {
    scrollToBottom();
  }, [timeline, markdownBuffer, currentThinking, currentCodeBlock, pausePrompt, clarifyRequest, planApproval, scrollToBottom]);

  // Show/hide scroll pill during streaming
  useEffect(() => {
    if (userScrolledUp.current && isStreaming) {
      if (!showScrollPillRef.current) {
        showScrollPillRef.current = true;
        setShowScrollPill(true);
      }
    }
    if (!isStreaming && showScrollPillRef.current) {
      showScrollPillRef.current = false;
      setShowScrollPill(false);
    }
  }, [timeline, markdownBuffer, isStreaming]);

  const handleScrollToBottom = useCallback(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      userScrolledUp.current = false;
      showScrollPillRef.current = false;
      setShowScrollPill(false);
    }
  }, []);

  // Pre-compute set of tool callIds for O(1) subagent dedup lookups
  const toolCallIds = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of timeline) {
      if (entry.type === "tool") ids.add(entry.callId);
    }
    return ids;
  }, [timeline]);

  // Build subagent tool lists: group tool cards by owning subagent.
  // Uses toolOrder for deterministic insertion-order iteration.
  const subagentToolCards = useMemo(() => {
    const result: Record<string, ToolStateData[]> = {};
    for (const sa of Object.values(subagents)) {
      result[sa.subagentId] = [];
    }
    for (const callId of toolOrder) {
      const ownerId = toolCardOwners[callId];
      const tc = toolCards[callId];
      if (ownerId && tc && result[ownerId]) {
        result[ownerId].push(tc);
      }
    }
    return result;
  }, [subagents, toolCards, toolCardOwners, toolOrder]);

  // Welcome screen when empty
  if (timeline.length === 0 && !isStreaming && onSendPrompt) {
    return (
      <div className="chat-history" ref={containerRef} onScroll={handleScroll}>
        <WelcomeScreen
          onSendPrompt={onSendPrompt}
          connected={connected}
          modelName={modelName}
          workingDirectory={workingDirectory}
        />
      </div>
    );
  }

  return (
    <div className="chat-history" ref={containerRef} onScroll={handleScroll}>
      {/* Timeline — ordered sequence of all UI elements */}
      {timeline.map((entry) => {
        switch (entry.type) {
          case "user_message":
            return (
              <MessageBubble
                key={entry.id}
                message={{
                  id: entry.id,
                  role: "user",
                  content: entry.content,
                  finalized: true,
                }}
                attachments={entry.attachments}
                images={entry.images}
              />
            );

          case "assistant_text":
            return (
              <div key={entry.id} className="message-wrapper">
                <div className="message assistant">
                  <div
                    className="content"
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(entry.content),
                    }}
                  />
                </div>
                <div className="message-actions">
                  <button
                    title="Copy"
                    onClick={() =>
                      postMessage({
                        type: "copyToClipboard",
                        text: entry.content,
                      })
                    }
                  >
                    <i className="codicon codicon-copy" />
                  </button>
                </div>
              </div>
            );

          case "tool": {
            const tc = toolCards[entry.callId];
            if (!tc) return null;
            // Check if this tool is a delegation — render SubagentCard instead
            const sa = Object.values(subagents).find(
              (s) => s.parentToolCallId === entry.callId,
            );
            if (sa) {
              return (
                <SubagentCard
                  key={entry.id}
                  info={sa}
                  toolCards={subagentToolCards[sa.subagentId] ?? []}
                  postMessage={postMessage}
                />
              );
            }
            return <ToolCard key={entry.id} data={tc} postMessage={postMessage} />;
          }

          case "thinking":
            return (
              <ThinkingBlock
                key={entry.id}
                thinking={{
                  content: entry.content,
                  tokenCount: entry.tokenCount,
                  open: false,
                }}
              />
            );

          case "code":
            return (
              <CodeBlock
                key={entry.id}
                block={{
                  language: entry.language,
                  content: entry.content,
                  complete: true,
                }}
                postMessage={postMessage}
              />
            );

          case "subagent": {
            const saInfo = subagents[entry.subagentId];
            if (!saInfo) return null;
            // Skip if already rendered via a 'tool' entry (delegation tool) — O(1) lookup
            if (toolCallIds.has(saInfo.parentToolCallId)) return null;
            return (
              <SubagentCard
                key={entry.id}
                info={saInfo}
                toolCards={subagentToolCards[saInfo.subagentId] ?? []}
                postMessage={postMessage}
              />
            );
          }

          case "error":
            return (
              <div key={entry.id} className="error-message">
                {entry.message}
              </div>
            );

          default:
            return null;
        }
      })}

      {/* Promoted subagent approval widgets (rendered at conversation level) */}
      {Object.entries(promotedApprovals).map(([callId, { data, subagentId }]) => {
        const sa = subagents[subagentId];
        return (
          <SubagentApprovalWidget
            key={callId}
            callId={callId}
            data={data}
            subagentName={sa ? `${sa.subagentName}${sa.modelName ? ` (${sa.modelName})` : ""}` : "Subagent"}
            postMessage={postMessage}
            onDismiss={() => onDismissApproval(callId)}
          />
        );
      })}

      {/* Currently-streaming thinking block */}
      {currentThinking && <ThinkingBlock thinking={currentThinking} isActive />}

      {/* Currently-streaming code block */}
      {currentCodeBlock && (
        <CodeBlock block={currentCodeBlock} postMessage={postMessage} />
      )}

      {/* Streaming markdown buffer */}
      {isStreaming && markdownBuffer && (
        <div className="message assistant" aria-live="polite">
          <div
            className="content"
            dangerouslySetInnerHTML={{
              __html: renderMarkdown(markdownBuffer),
            }}
          />
          <span className="streaming-cursor" />
        </div>
      )}

      {/* Streaming dots (when waiting for first content) */}
      {isStreaming && !markdownBuffer && !currentThinking && !currentCodeBlock && (
        <div className="message assistant streaming-dots" />
      )}

      {/* Interactive widgets */}
      {pausePrompt && (
        <PauseWidget
          reason={pausePrompt.reason}
          reasonCode={pausePrompt.reasonCode}
          stats={pausePrompt.stats}
          pendingTodos={pausePrompt.pendingTodos}
          postMessage={postMessage}
        />
      )}

      {clarifyRequest && (
        <ClarifyWidget
          callId={clarifyRequest.callId}
          questions={clarifyRequest.questions}
          context={clarifyRequest.context}
          postMessage={postMessage}
        />
      )}

      {planApproval && (
        <PlanWidget
          callId={planApproval.callId}
          planHash={planApproval.planHash}
          excerpt={planApproval.excerpt}
          truncated={planApproval.truncated}
          planPath={planApproval.planPath}
          isDirector={planApproval.isDirector}
          postMessage={postMessage}
        />
      )}

      {/* Undo bar */}
      {undoAvailable && (
        <UndoBar
          turnId={undoAvailable.turnId}
          files={undoAvailable.files}
          undone={undoCompleted}
          postMessage={postMessage}
        />
      )}

      {/* Turn stats */}
      {!isStreaming && lastTurnStats && (
        <TurnStats
          tokens={lastTurnStats.tokens}
          durationMs={lastTurnStats.durationMs}
        />
      )}

      {/* Scroll-to-bottom pill */}
      {showScrollPill && (
        <button className="scroll-pill" onClick={handleScrollToBottom}>
          <i className="codicon codicon-arrow-down" /> New content
        </button>
      )}
    </div>
  );
}
