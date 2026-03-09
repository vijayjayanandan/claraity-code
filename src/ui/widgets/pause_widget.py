"""
PausePromptWidget - Simple pause/continue UI.

Shows when agent hits budget limits or timeout and needs user decision to continue or stop.
Simple two-option design: Continue or Stop.
"""

from rich.console import RenderableType
from rich.text import Text
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Static

from ..messages import PauseResponseMessage


class PausePromptWidget(Static, can_focus=True):
    """
    Simple pause/continue UI.

    Shows:
        [PAUSED] Request timed out
        Tools: 5 | Time: 62.3s

        > 1. Continue
          2. Stop

        Esc to stop | c=continue s=stop

    Posts PauseResponseMessage when user makes selection.
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("enter", "select", "Select", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
    ]

    selected_index = reactive(0)  # 0 = Continue, 1 = Stop

    DEFAULT_CSS = """
    PausePromptWidget {
        height: auto;
        padding: 1;
        margin: 1 0;
        background: #1a1a2e;
        border: solid #4a9eff;
        color: #e0e0e0;
    }

    PausePromptWidget:focus {
        border: solid #6bb3ff;
        background: #16213e;
    }
    """

    def __init__(
        self,
        reason: str,
        reason_code: str,
        pending_todos: list[str],
        stats: dict,
        **kwargs
    ):
        """
        Initialize pause prompt widget.

        Args:
            reason: Human-readable reason (e.g., "Request timed out")
            reason_code: Machine code (e.g., "timeout", "max_tool_calls")
            pending_todos: List of incomplete task descriptions
            stats: Execution stats dict (tool_calls, elapsed_s, iterations)
        """
        super().__init__(**kwargs)
        self.reason = reason
        self.reason_code = reason_code
        self.pending_todos = pending_todos
        self.stats = stats

    def on_mount(self) -> None:
        """Focus on mount to capture key events."""
        self.call_after_refresh(self._ensure_focus)
        self.set_timer(0.1, self._ensure_focus)

    def _ensure_focus(self) -> None:
        """Ensure this widget has focus for key events."""
        if not self.has_focus:
            self.focus()
            self.scroll_visible()

    def on_key(self, event) -> None:
        """Handle key presses for shortcuts."""
        if event.is_printable and event.character:
            if event.character == "1":
                self.selected_index = 0
                self._submit_selection()
                event.prevent_default()
                event.stop()
            elif event.character == "2":
                self.selected_index = 1
                self._submit_selection()
                event.prevent_default()
                event.stop()
            elif event.character == "c":  # 'c' for continue
                self.selected_index = 0
                self._submit_selection()
                event.prevent_default()
                event.stop()
            elif event.character == "s":  # 's' for stop
                self.selected_index = 1
                self._submit_selection()
                event.prevent_default()
                event.stop()
            elif event.character == "k":
                self.selected_index = max(0, self.selected_index - 1)
                event.prevent_default()
                event.stop()
            elif event.character == "j":
                self.selected_index = min(1, self.selected_index + 1)
                event.prevent_default()
                event.stop()

    def render(self) -> RenderableType:
        """Render the pause prompt."""
        lines = []

        # Header with reason - bright cyan for visibility
        tool_calls = self.stats.get('tool_calls', '?')
        elapsed_s = self.stats.get('elapsed_s', 0)
        lines.append(Text(f"[PAUSED] {self.reason}\n", style="bold bright_cyan"))

        # Stats line - light gray
        stats_text = f"Tools: {tool_calls} | Time: {elapsed_s:.1f}s"
        lines.append(Text(f"{stats_text}\n", style="bright_black"))

        # Pending todos (if any) - yellow for visibility
        if self.pending_todos:
            pending_preview = ", ".join(self.pending_todos[:3])
            if len(pending_preview) > 60:
                pending_preview = pending_preview[:57] + "..."
            if len(self.pending_todos) > 3:
                pending_preview += f" (+{len(self.pending_todos) - 3} more)"
            lines.append(Text(f"Pending: {pending_preview}\n\n", style="italic bright_yellow"))
        else:
            lines.append(Text("\n"))

        # Option 1: Continue - green when selected
        prefix1 = "> " if self.selected_index == 0 else "  "
        style1 = "bold bright_green reverse" if self.selected_index == 0 else "white"
        lines.append(Text(f"{prefix1}1. Continue\n", style=style1))

        # Option 2: Stop - red when selected
        prefix2 = "> " if self.selected_index == 1 else "  "
        style2 = "bold bright_red reverse" if self.selected_index == 1 else "white"
        lines.append(Text(f"{prefix2}2. Stop\n", style=style2))

        # Footer - subdued but readable
        lines.append(Text("\nEsc to stop | c=continue s=stop", style="bright_black"))

        return Text("").join(lines)

    def action_move_up(self) -> None:
        """Move selection up."""
        self.selected_index = max(0, self.selected_index - 1)

    def action_move_down(self) -> None:
        """Move selection down."""
        self.selected_index = min(1, self.selected_index + 1)

    def action_select(self) -> None:
        """Confirm current selection."""
        self._submit_selection()

    def action_cancel(self) -> None:
        """Cancel (stop) the session."""
        self.post_message(PauseResponseMessage(continue_work=False))

    def _submit_selection(self) -> None:
        """Submit the current selection."""
        if self.selected_index == 0:
            # Continue
            self.post_message(PauseResponseMessage(continue_work=True))
        else:
            # Stop
            self.post_message(PauseResponseMessage(continue_work=False))


# Export
__all__ = ['PausePromptWidget']
