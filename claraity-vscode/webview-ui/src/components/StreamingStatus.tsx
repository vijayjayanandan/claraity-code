/**
 * Streaming status bar — shows current activity phase and elapsed time.
 *
 * Displays a spinning icon, dynamic status text (Thinking / tool name /
 * activeForm / Streaming...), and an elapsed timer that ticks every second.
 * Only visible while isStreaming is true.
 */
import { useState, useEffect, useRef } from "react";
import type { ToolStateData } from "../types";

interface StreamingStatusProps {
  isStreaming: boolean;
  currentThinking: { content: string; open: boolean } | null;
  toolCards: Record<string, ToolStateData>;
  todos: unknown[];
}

interface TodoItem {
  status?: string;
  activeForm?: string;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function StreamingStatus({
  isStreaming,
  currentThinking,
  toolCards,
  todos,
}: StreamingStatusProps) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Start/stop elapsed timer when streaming state changes
  useEffect(() => {
    if (isStreaming) {
      startRef.current = Date.now();
      setElapsed(0);
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
      }, 1000);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isStreaming]);

  if (!isStreaming) return null;

  // Derive status text: thinking > running tool > activeForm > default
  let statusText = "Streaming...";

  if (currentThinking) {
    statusText = "Thinking...";
  } else {
    // Find the most recent running tool
    const entries = Object.values(toolCards);
    const running = entries.filter((t) => t.status === "running");
    if (running.length > 0) {
      const latest = running[running.length - 1];
      statusText = latest.tool_name || "Running tool...";
    } else {
      // Check for active todo form
      const items = todos as TodoItem[];
      const active = items.find((t) => t.status === "in_progress" && t.activeForm);
      if (active?.activeForm) {
        statusText = active.activeForm;
      }
    }
  }

  return (
    <div className="streaming-status" role="status" aria-live="polite" aria-label="Streaming status">
      <span className="status-spinner" aria-hidden="true">&#x27F3;</span>
      <span className="status-text">{statusText}</span>
      <span className="status-elapsed">{formatElapsed(elapsed)}</span>
    </div>
  );
}
