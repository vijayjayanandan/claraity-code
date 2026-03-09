"""
TodoBar - Collapsible todo list display widget.

Shows the agent's todo list (from TodoWrite tool) in a collapsible bar
above the status bar. Hidden until first todo is created.
"""

from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class TodoBar(Static):
    """Collapsible todo list display above status bar."""

    todos: reactive[list[dict[str, Any]]] = reactive([])
    is_expanded: reactive[bool] = reactive(False)

    # CSS handled by src/ui/styles.tcss (#todo-bar styles)
    DEFAULT_CSS = ""

    def watch_todos(self, todos: list[dict[str, Any]]) -> None:
        """Show/hide based on whether todos exist and not all completed."""
        if todos:
            # Check if all tasks are completed
            completed = sum(1 for t in todos if t.get('status') == 'completed')
            total = len(todos)
            if completed == total and total > 0:
                # All completed - hide the bar
                self.remove_class("has-todos")
            else:
                self.add_class("has-todos")
        else:
            self.remove_class("has-todos")

    def watch_is_expanded(self, is_expanded: bool) -> None:
        """Update styling when expanded/collapsed."""
        if is_expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")

    def render(self) -> Text:
        """Render the todo bar content."""
        if not self.todos:
            return Text("")

        completed = sum(1 for t in self.todos if t.get('status') == 'completed')
        in_progress = sum(1 for t in self.todos if t.get('status') == 'in_progress')
        total = len(self.todos)

        # All completed case is handled by watch_todos removing has-todos class
        if completed == total and total > 0:
            return Text("")

        if self.is_expanded:
            # Show all todos with Claude Code-style indicators
            result = Text()
            result.append(f"Tasks ({completed}/{total})\n", style="bold")

            # Sort: in_progress first, then pending, then completed at bottom
            status_order = {"in_progress": 0, "pending": 1, "completed": 2}
            sorted_todos = sorted(
                self.todos,
                key=lambda t: status_order.get(t.get("status", "pending"), 1)
            )

            for todo in sorted_todos:
                status = todo.get('status', 'pending')
                content = todo.get('subject', todo.get('content', ''))
                active_form = todo.get('activeForm', content)

                if status == 'completed':
                    result.append("  [x] ", style="green")
                    result.append(f"{content}\n", style="dim strike")  # Strikethrough
                elif status == 'in_progress':
                    result.append("  [>>>] ", style="bold yellow")
                    result.append(f"{active_form}\n", style="yellow")
                else:  # pending
                    result.append("  [ ] ", style="dim")
                    result.append(f"{content}\n")

            return result
        else:
            # Collapsed: show summary with shortcut hint
            result = Text()
            result.append("[Ctrl+t] ", style="dim")
            result.append("Tasks: ", style="bold")

            if in_progress > 0:
                result.append(f"{in_progress} active", style="yellow")
                result.append(", ")

            result.append(f"{completed}/{total} done", style="green" if completed == total else "")

            return result

    def toggle(self) -> None:
        """Toggle expanded/collapsed state."""
        self.is_expanded = not self.is_expanded

    def update_todos(self, todos: list[dict[str, Any]]) -> None:
        """Update the todo list."""
        self.todos = todos.copy() if todos else []

    def get_current_task(self) -> str:
        """Get the activeForm of the current in_progress task."""
        for todo in self.todos:
            if todo.get('status') == 'in_progress':
                return todo.get('activeForm', todo.get('subject', todo.get('content', '')))
        return ""
