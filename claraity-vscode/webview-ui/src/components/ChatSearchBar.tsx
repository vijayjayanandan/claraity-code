/**
 * Sticky search bar for in-session message search.
 * Appears below the context bar when the search icon is clicked in the VS Code toolbar.
 */
import { useRef, useEffect } from "react";

interface ChatSearchBarProps {
  query: string;
  matchCount: number;
  currentMatch: number; // 0-based
  onQueryChange: (q: string) => void;
  onNavigate: (dir: "prev" | "next") => void;
  onClose: () => void;
}

export function ChatSearchBar({
  query,
  matchCount,
  currentMatch,
  onQueryChange,
  onNavigate,
  onClose,
}: ChatSearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus when the bar appears
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const countLabel = matchCount === 0
    ? "No results"
    : `${currentMatch + 1} of ${matchCount}`;

  return (
    <div className="chat-search-bar">
      <i className="codicon codicon-search chat-search-icon" aria-hidden="true" />
      <input
        ref={inputRef}
        className="chat-search-input"
        type="text"
        placeholder="Search messages..."
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.shiftKey ? onNavigate("prev") : onNavigate("next");
          } else if (e.key === "Escape") {
            onClose();
          }
        }}
        aria-label="Search chat messages"
      />
      {query.length > 0 && (
        <span className="chat-search-count">{countLabel}</span>
      )}
      <button
        className="chat-search-nav-btn"
        title="Previous match (Shift+Enter)"
        disabled={matchCount === 0}
        onClick={() => onNavigate("prev")}
        aria-label="Previous match"
      >
        <i className="codicon codicon-arrow-up" />
      </button>
      <button
        className="chat-search-nav-btn"
        title="Next match (Enter)"
        disabled={matchCount === 0}
        onClick={() => onNavigate("next")}
        aria-label="Next match"
      >
        <i className="codicon codicon-arrow-down" />
      </button>
      <button
        className="chat-search-nav-btn chat-search-close"
        title="Close search (Escape)"
        onClick={onClose}
        aria-label="Close search"
      >
        <i className="codicon codicon-close" />
      </button>
    </div>
  );
}
