/**
 * Collapsible background task panel.
 *
 * Shows running/completed background commands with:
 * - Colored status badge per task
 * - Cancel button for running tasks
 * - Expandable output (stdout/stderr) for finished tasks
 * - Dismiss button to remove finished tasks from the panel
 * - Auto-clear of completed tasks after 60 seconds
 */
import { useState, useEffect, useRef, useCallback } from "react";
import type { BackgroundTaskData } from "../types";

interface BackgroundTaskPanelProps {
  tasks: BackgroundTaskData[];
  onCancel: (taskId: string) => void;
  onDismiss: (taskId: string) => void;
}

const AUTO_CLEAR_MS = 60_000; // 60 seconds

const STATUS_LABELS: Record<string, string> = {
  running: "running",
  completed: "done",
  failed: "failed",
  timed_out: "timed out",
  cancelled: "cancelled",
};

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m${s}s`;
}

export function BackgroundTaskPanel({ tasks, onCancel, onDismiss }: BackgroundTaskPanelProps) {
  const [collapsed, setCollapsed] = useState(true);
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set());
  // Track when each finished task was first seen so we can auto-clear it
  const completionTimes = useRef<Map<string, number>>(new Map());
  const panelRef = useRef<HTMLDivElement>(null);

  // Close panel when clicking outside
  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
      setCollapsed(true);
    }
  }, []);

  useEffect(() => {
    if (!collapsed) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [collapsed, handleClickOutside]);

  // Auto-clear completed tasks after AUTO_CLEAR_MS
  useEffect(() => {
    const finished = tasks.filter((t) => t.status !== "running");
    if (finished.length === 0) return;

    const now = Date.now();
    finished.forEach((t) => {
      if (!completionTimes.current.has(t.task_id)) {
        completionTimes.current.set(t.task_id, now);
      }
    });

    // Find the earliest expiry among finished tasks
    const earliest = Math.min(
      ...finished.map((t) => (completionTimes.current.get(t.task_id) ?? now) + AUTO_CLEAR_MS)
    );
    const delay = Math.max(0, earliest - Date.now());

    const timer = setTimeout(() => {
      const now2 = Date.now();
      finished.forEach((t) => {
        const completedAt = completionTimes.current.get(t.task_id) ?? now2;
        if (now2 - completedAt >= AUTO_CLEAR_MS) {
          completionTimes.current.delete(t.task_id);
          onDismiss(t.task_id);
        }
      });
    }, delay);

    return () => clearTimeout(timer);
  }, [tasks, onDismiss]);

  const running = tasks.filter((t) => t.status === "running");
  const done = tasks.filter((t) => t.status !== "running");

  const summaryParts: string[] = [];
  if (running.length > 0) summaryParts.push(`${running.length} running`);
  if (done.length > 0) summaryParts.push(`${done.length} done`);
  const summaryText = `BG Tasks: ${summaryParts.join(", ")}`;

  const toggleExpand = (taskId: string) => {
    setExpandedTasks((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  const isFinished = (status: string) => status !== "running";
  const hasOutput = (task: BackgroundTaskData) => !!(task.stdout || task.stderr);

  return (
    <div className="bg-task-panel" ref={panelRef}>
      <div className="bg-task-header" onClick={() => setCollapsed(!collapsed)}>
        <span className="bg-task-summary">
          {running.length > 0 && <span className="bg-task-dot" />}
          {summaryText}
        </span>
        <span>{collapsed ? "+" : "-"}</span>
      </div>
      {!collapsed && (
        <div className="bg-task-list">
          {tasks.map((task) => {
            const expanded = expandedTasks.has(task.task_id);
            const canExpand = isFinished(task.status) && hasOutput(task);
            return (
              <div key={task.task_id} className={`bg-task-entry ${task.status}`}>
                <div
                  className={`bg-task-item${canExpand ? " expandable" : ""}`}
                  onClick={canExpand ? () => toggleExpand(task.task_id) : undefined}
                >
                  <span className={`bg-task-badge bg-task-badge--${task.status}`}>
                    {STATUS_LABELS[task.status] ?? task.status}
                  </span>
                  <span className="bg-task-id">{task.task_id}</span>
                  <span className="bg-task-desc" title={task.command}>
                    {task.description || task.command}
                  </span>
                  <span className="bg-task-elapsed">{formatElapsed(task.elapsed_seconds)}</span>
                  {task.status === "running" && (
                    <button
                      className="bg-task-cancel"
                      onClick={(e) => { e.stopPropagation(); onCancel(task.task_id); }}
                      title="Cancel task"
                    >
                      x
                    </button>
                  )}
                  {isFinished(task.status) && (
                    <button
                      className="bg-task-dismiss"
                      onClick={(e) => { e.stopPropagation(); onDismiss(task.task_id); }}
                      title="Dismiss"
                    >
                      x
                    </button>
                  )}
                </div>
                {expanded && (
                  <div className="bg-task-output">
                    {task.stdout && (
                      <pre className="bg-task-stdout">{task.stdout}</pre>
                    )}
                    {task.stderr && (
                      <pre className="bg-task-stderr">{task.stderr}</pre>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
