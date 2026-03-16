/**
 * Individual chat message bubble with markdown rendering.
 *
 * Strips <project_context>...</project_context> blocks from user messages
 * (injected by the extension for LLM context, not meant to be displayed).
 */
import { useMemo } from "react";
import type { ChatMessage } from "../state/reducer";
import { renderMarkdown } from "../utils/markdown";
import { stripProjectContext } from "../utils/text";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const html = useMemo(() => {
    const displayContent = message.role === "user"
      ? stripProjectContext(message.content)
      : message.content;
    return renderMarkdown(displayContent);
  }, [message.content, message.role]);

  return (
    <div className={`message ${message.role}`}>
      <div
        className="content"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
