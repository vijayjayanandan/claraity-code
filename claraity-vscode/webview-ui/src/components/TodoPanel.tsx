/**
 * Collapsible task/todo panel.
 */
import { useState, useEffect, useRef, useCallback } from "react";

interface TodoPanelProps {
  todos: unknown[];
}

interface TodoItem {
  id?: string;
  subject?: string;
  status?: string;
  activeForm?: string;
}

export function TodoPanel({ todos }: TodoPanelProps) {
  const [collapsed, setCollapsed] = useState(true);
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

  const items = todos as TodoItem[];
  const active = items.filter((t) => t.status === "in_progress").length;
  const completed = items.filter((t) => t.status === "completed").length;
  const total = items.length;

  // Find the active task's activeForm text for collapsed display
  const activeTask = items.find((t) => t.status === "in_progress");
  const collapsedText = activeTask?.activeForm
    ? `>>> ${activeTask.activeForm}`
    : `Tasks: ${completed}/${total} done`;

  return (
    <div className="todo-panel" ref={panelRef}>
      <div className="todo-header" onClick={() => setCollapsed(!collapsed)}>
        <span className="todo-summary">
          {collapsedText}
        </span>
        <span>{collapsed ? "+" : "-"}</span>
      </div>
      {!collapsed && (
        <div className="todo-list">
          {items.map((item, i) => (
            <div key={item.id ?? i} className={`todo-item ${item.status ?? ""}`}>
              <span className="todo-status">
                {item.status === "completed" ? "[x]" : item.status === "in_progress" ? "[>>>]" : "[ ]"}
              </span>
              <span>{item.status === "in_progress" ? item.activeForm : item.subject}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
