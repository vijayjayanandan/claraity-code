/**
 * Collapsible thinking/reasoning block.
 */
import { memo } from "react";
import type { ThinkingBlock as ThinkingBlockType } from "../state/reducer";

interface ThinkingBlockProps {
  thinking: ThinkingBlockType;
  isActive?: boolean;
}

export const ThinkingBlock = memo(function ThinkingBlock({ thinking, isActive }: ThinkingBlockProps) {
  const className = `thinking-block${isActive ? " active" : ""}`;

  return (
    <details className={className} open={thinking.open}>
      <summary>
        Thinking{thinking.tokenCount ? ` (${thinking.tokenCount} tokens)` : ""}
        {thinking.open ? "..." : ""}
      </summary>
      <div className="thinking-content">{thinking.content}</div>
    </details>
  );
});
