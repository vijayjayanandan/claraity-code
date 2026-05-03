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
import { useRef, useEffect, useCallback, useMemo, useState, createRef } from "react";
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
import { ChatSearchBar } from "./ChatSearchBar";
import { stripProjectContext } from "../utils/text";

/**
 * Wrap query matches in already-rendered HTML with <mark> tags.
 * Operates only on text nodes (not inside HTML tag attributes).
 * Case-insensitive.
 */
function highlightSearchInHtml(html: string, query: string): string {
  if (!query.trim()) return html;
  // Use a regex that skips HTML tags, replacing only text node content
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(?![^<]*>)(${escaped})`, "gi");
  return html.replace(re, '<mark class="search-highlight">$1</mark>');
}

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
  } | null;
  undoAvailable: { turnId: string; files: string[] } | null;
  undoCompleted: boolean;
  lastTurnStats: { tokens: number; durationMs: number } | null;
  onSendPrompt?: (prompt: string) => void;
  onDismissClarify?: () => void;
  onDismissPlan?: () => void;
  onOpenSettings?: () => void;
  connected?: boolean;
  modelName?: string;
  workingDirectory?: string;
  searchOpen?: boolean;
  searchQuery?: string;
  onSearchQuery?: (q: string) => void;
  onSearchClose?: () => void;
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
  onDismissClarify,
  onDismissPlan,
  onOpenSettings,
  connected,
  modelName,
  workingDirectory,
  searchOpen = false,
  searchQuery = "",
  onSearchQuery,
  onSearchClose,
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

  // ── Search ──
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);

  // Compute which timeline entries match the search query
  const matchingEntryIds = useMemo<string[]>(() => {
    if (!searchOpen || !searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    const ids: string[] = [];
    for (const entry of timeline) {
      if (entry.type === "user_message") {
        const text = stripProjectContext(entry.content).toLowerCase();
        if (text.includes(q)) ids.push(entry.id);
      } else if (entry.type === "assistant_text") {
        if (entry.content.toLowerCase().includes(q)) ids.push(entry.id);
      }
    }
    return ids;
  }, [timeline, searchQuery, searchOpen]);

  const matchCount = matchingEntryIds.length;

  // Clamp currentMatchIndex when matchCount changes
  useEffect(() => {
    setCurrentMatchIndex(0);
  }, [searchQuery, searchOpen]);

  // Refs for scrolling to matched entries
  const matchRefsMap = useMemo<Record<string, React.RefObject<HTMLDivElement>>>(() => {
    const map: Record<string, React.RefObject<HTMLDivElement>> = {};
    for (const id of matchingEntryIds) {
      map[id] = createRef<HTMLDivElement>();
    }
    return map;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchingEntryIds.join(",")]);

  // Scroll to current match
  useEffect(() => {
    if (matchingEntryIds.length === 0) return;
    const id = matchingEntryIds[currentMatchIndex];
    matchRefsMap[id]?.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [currentMatchIndex, matchingEntryIds, matchRefsMap]);

  const handleSearchNavigate = useCallback((dir: "prev" | "next") => {
    setCurrentMatchIndex((prev) => {
      if (matchCount === 0) return 0;
      if (dir === "next") return (prev + 1) % matchCount;
      return (prev - 1 + matchCount) % matchCount;
    });
  }, [matchCount]);

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
      <>
        {searchOpen && (
          <ChatSearchBar
            query={searchQuery}
            matchCount={0}
            currentMatch={0}
            onQueryChange={onSearchQuery ?? (() => {})}
            onNavigate={handleSearchNavigate}
            onClose={onSearchClose ?? (() => {})}
          />
        )}
        <div className="chat-history" ref={containerRef} onScroll={handleScroll}>
          <WelcomeScreen
            onSendPrompt={onSendPrompt}
            connected={connected}
            modelName={modelName}
            workingDirectory={workingDirectory}
          />
        </div>
      </>
    );
  }

  return (
    <>
      {searchOpen && (
        <ChatSearchBar
          query={searchQuery}
          matchCount={matchCount}
          currentMatch={currentMatchIndex}
          onQueryChange={onSearchQuery ?? (() => {})}
          onNavigate={handleSearchNavigate}
          onClose={onSearchClose ?? (() => {})}
        />
      )}
    <div className="chat-history" ref={containerRef} onScroll={handleScroll}>
      {/* Timeline — ordered sequence of all UI elements */}
      {timeline.map((entry) => {
        switch (entry.type) {
          case "user_message": {
            const isMatch = matchingEntryIds.includes(entry.id);
            const isCurrentMatch = isMatch && matchingEntryIds[currentMatchIndex] === entry.id;
            return (
              <div
                key={entry.id}
                className={`user-message-wrapper${isCurrentMatch ? " search-current-match" : ""}`}
                ref={isMatch ? matchRefsMap[entry.id] : undefined}
              >
                <MessageBubble
                  message={{
                    id: entry.id,
                    role: "user",
                    content: entry.content,
                    finalized: true,
                  }}
                  attachments={entry.attachments}
                  images={entry.images}
                  searchQuery={searchOpen ? searchQuery : ""}
                />
                {entry.uuid && !isStreaming && (
                  <div className="user-message-actions">
                    <button
                      title="Delete this turn"
                      aria-label="Delete this turn"
                      className="delete-turn-btn"
                      onClick={() => postMessage({ type: "deleteTurn", anchorUuid: entry.uuid! })}
                    >
                      <i className="codicon codicon-trash" />
                    </button>
                  </div>
                )}
              </div>
            );
          }

          case "assistant_text": {
            const isMatch = matchingEntryIds.includes(entry.id);
            const isCurrentMatch = isMatch && matchingEntryIds[currentMatchIndex] === entry.id;
            const content = searchOpen && searchQuery.trim()
              ? highlightSearchInHtml(renderMarkdown(entry.content), searchQuery)
              : renderMarkdown(entry.content);
            return (
              <div
                key={entry.id}
                className={`message-wrapper${isCurrentMatch ? " search-current-match" : ""}`}
                ref={isMatch ? matchRefsMap[entry.id] : undefined}
              >
                <div className="message assistant">
                  <div
                    className="content"
                    dangerouslySetInnerHTML={{ __html: content }}
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
          }

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
                <span>{entry.message}</span>
                {entry.errorType === "config_error" && onOpenSettings && (
                  <button className="error-settings-link" onClick={onOpenSettings}>
                    Open Settings
                  </button>
                )}
              </div>
            );

          case "deleted_turn":
            return (
              <div key={entry.id} className="deleted-turn-placeholder">
                <i className="codicon codicon-trash" aria-hidden="true" />
                <span className="deleted-turn-text">
                  {entry.count} message{entry.count !== 1 ? "s" : ""} removed
                  {entry.preview && <span className="deleted-turn-preview"> &mdash; {entry.preview}</span>}
                </span>
                <button
                  className="restore-turn-btn"
                  onClick={() => postMessage({ type: "restoreTurn", anchorUuid: entry.anchorUuid })}
                >
                  Restore
                </button>
              </div>
            );

          case "compaction_summary":
            return (
              <details key={entry.id} className="compaction-summary-card">
                <summary>
                  <span className="compaction-summary-pill">
                    <i className="codicon codicon-history" aria-hidden="true" />
                    Conversation compacted
                    <span className="compaction-summary-chevron">&#9658;</span>
                  </span>
                </summary>
                <div className="compaction-summary-content">
                  {entry.content.replace(/^\[Conversation summary[^\]]*\]\n\n/, "")}
                </div>
              </details>
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
          key={clarifyRequest.callId}
          callId={clarifyRequest.callId}
          questions={clarifyRequest.questions}
          context={clarifyRequest.context}
          postMessage={postMessage}
          onDismiss={onDismissClarify ?? (() => {})}
        />
      )}

      {planApproval && (
        <PlanWidget
          callId={planApproval.callId}
          planHash={planApproval.planHash}
          excerpt={planApproval.excerpt}
          truncated={planApproval.truncated}
          planPath={planApproval.planPath}
          postMessage={postMessage}
          onDismiss={onDismissPlan ?? (() => {})}
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
    </>
  );
}
