"""
BackgroundTaskBar - Collapsible bar showing running background tasks.

Similar to AttachmentBar. Hidden when no tasks are running.
Shows running tasks only (completed tasks get inline chat notifications).
Collapsed: summary line. Expanded: per-task rows with keyboard navigation.

Keyboard (when focused):
- Up/Down: navigate tasks
- k: kill selected task
- Escape: collapse and return focus to input
"""

import time
from typing import Any

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from src.core.background_tasks import (
    BackgroundTaskInfo,
    BackgroundTaskRegistry,
    BackgroundTaskStatus,
)


class BackgroundTaskBar(Widget, can_focus=True):
    """Collapsible bar showing running background tasks with keyboard navigation."""

    DEFAULT_CSS = ""

    BINDINGS = [
        Binding("up", "select_prev", "Previous", show=False),
        Binding("down", "select_next", "Next", show=False),
        Binding("k", "kill_selected", "Kill", show=False),
        Binding("escape", "collapse", "Collapse", show=False),
    ]

    tasks: reactive[list[dict[str, Any]]] = reactive([])
    is_expanded: reactive[bool] = reactive(False)
    selected_index: reactive[int] = reactive(0)

    class KillTask(Message):
        """Sent when user wants to kill a task."""

        def __init__(self, task_id: str) -> None:
            self.task_id = task_id
            super().__init__()

    class CollapseBar(Message):
        """Sent when user collapses the bar."""

        pass

    def watch_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Show/hide based on whether running tasks exist."""
        if tasks:
            self.add_class("has-tasks")
        else:
            self.remove_class("has-tasks")
            self.is_expanded = False

        # Clamp selected index
        if self.selected_index >= len(tasks):
            self.selected_index = max(0, len(tasks) - 1)

        self.refresh()

    def watch_is_expanded(self, is_expanded: bool) -> None:
        """Update styling when expanded/collapsed."""
        if is_expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")
        self.refresh()

    def watch_selected_index(self, new_index: int) -> None:
        """React to selection changes."""
        self.refresh()

    def render(self) -> Text:
        """Render the bar content."""
        if not self.tasks:
            return Text("")

        count = len(self.tasks)

        if self.is_expanded:
            result = Text()
            result.append(f" Background Tasks ({count} running)\n", style="bold #3794ff")

            is_focused = self.has_focus
            for i, task in enumerate(self.tasks):
                task_id = task["task_id"]
                cmd = task["command"]
                if len(cmd) > 65:
                    cmd = cmd[:62] + "..."
                elapsed = task.get("elapsed", 0)

                is_selected = (i == self.selected_index) and is_focused

                if is_selected:
                    result.append(f"  > {task_id}", style="bold reverse cyan")
                    result.append(f"  {cmd}", style="reverse cyan")
                    result.append(f"  ({elapsed:.0f}s)\n", style="reverse cyan")
                else:
                    result.append(f"    {task_id}", style="bold")
                    result.append(f"  {cmd}", style="#9cdcfe")
                    result.append(f"  ({elapsed:.0f}s)\n", style="#6e7681")

            # Hint line
            if is_focused:
                result.append("  Up/Down: nav | k: kill | Esc: close", style="dim")
            else:
                result.append("  [Ctrl+B] to interact", style="dim")

            return result
        else:
            # Collapsed: single summary line
            result = Text()
            result.append(" [Ctrl+B] ", style="dim")
            result.append(f"Background Tasks: {count} running", style="#3794ff")

            # Preview first task
            if count == 1:
                cmd = self.tasks[0]["command"]
                if len(cmd) > 40:
                    cmd = cmd[:37] + "..."
                result.append(f" - {cmd}", style="#6e7681")

            return result

    def toggle(self) -> None:
        """Toggle expanded/collapsed state. Focus when expanding."""
        self.is_expanded = not self.is_expanded
        if self.is_expanded and self.tasks:
            self.focus()

    def action_select_prev(self) -> None:
        """Select previous task."""
        if self.tasks and self.selected_index > 0:
            self.selected_index -= 1

    def action_select_next(self) -> None:
        """Select next task."""
        if self.tasks and self.selected_index < len(self.tasks) - 1:
            self.selected_index += 1

    def action_kill_selected(self) -> None:
        """Kill the selected task."""
        if self.tasks and 0 <= self.selected_index < len(self.tasks):
            task_id = self.tasks[self.selected_index]["task_id"]
            self.post_message(self.KillTask(task_id))

    def action_collapse(self) -> None:
        """Collapse and return focus to input."""
        self.is_expanded = False
        self.post_message(self.CollapseBar())

    def on_click(self, event: events.Click) -> None:
        """Handle click - focus and select task row."""
        if not self.tasks or not self.is_expanded:
            return

        # Row 0 is the header, rows 1..N are tasks
        row = event.y - 1  # offset for header line
        if 0 <= row < len(self.tasks):
            self.selected_index = row
            self.focus()

    def update_from_registry(self, registry: BackgroundTaskRegistry) -> None:
        """Refresh task list from BackgroundTaskRegistry. Only shows running tasks."""
        running = [t for t in registry.all_tasks() if t.status == BackgroundTaskStatus.RUNNING]

        self.tasks = [
            {
                "task_id": t.task_id,
                "command": t.command,
                "description": t.description,
                "elapsed": time.monotonic() - t.start_time,
            }
            for t in running
        ]
