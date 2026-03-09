"""
PlanApprovalWidget - Inline widget for plan approval.

Shows the plan in a scrollable area with approval options pinned below.
Supports inline feedback text capture (no separate Input widget).
"""

from typing import Optional

from rich.console import RenderableType
from rich.text import Text
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

from ..messages import PlanApprovalResponseMessage


class _PlanContent(Static):
    """Renders the plan text (placed inside a scrollable container)."""

    def __init__(self, excerpt: str, truncated: bool, plan_path: str | None, **kwargs):
        super().__init__(**kwargs)
        self.excerpt = excerpt
        self.truncated = truncated
        self.plan_path = plan_path

    def render(self) -> RenderableType:
        lines = []
        for line in self.excerpt.split("\n"):
            lines.append(Text(line, style="dim"))

        if self.truncated:
            lines.append(Text())
            lines.append(
                Text(
                    f"[Plan exceeded context limit - full plan at: {self.plan_path}]",
                    style="italic dim",
                )
            )

        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append("\n")
            result.append(line)
        return result


class _PlanOptionsDisplay(Static, can_focus=True):
    """Renders the approval options (pinned below the scroll area)."""

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("enter", "select", "Select", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("backspace", "backspace", show=False, priority=True),
    ]

    current_option = reactive(0)
    feedback_text = reactive("")

    OPTIONS = [
        {
            "id": "approve_manual",
            "label": "Approve (manual edits)",
            "description": "Review each file change before applying",
            "approved": True,
            "auto_accept_edits": False,
        },
        {
            "id": "approve_auto",
            "label": "Approve (auto-accept edits)",
            "description": "Apply file changes automatically",
            "approved": True,
            "auto_accept_edits": True,
        },
        {
            "id": "feedback",
            "label": "Provide feedback",
            "description": "Type specific feedback for the agent",
            "approved": False,
            "auto_accept_edits": False,
        },
    ]

    def on_mount(self) -> None:
        self.call_after_refresh(self._ensure_focus)

    def _ensure_focus(self) -> None:
        if not self.has_focus:
            self.focus()
            self.scroll_visible()

    def on_key(self, event) -> None:
        # Check if we're in feedback mode (typing text)
        in_feedback_mode = self.current_option == 2 or self.feedback_text

        if event.is_printable and event.character:
            if not in_feedback_mode:
                # Handle shortcut keys when NOT in feedback mode
                if event.character.isdigit():
                    num = int(event.character)
                    if 1 <= num <= len(self.OPTIONS):
                        self.current_option = num - 1
                        if num != 3:  # Options 1 and 2 submit immediately
                            self.action_select()
                        event.prevent_default()
                        event.stop()
                        return

            # Any other printable character (or any char in feedback mode) -> type it
            self.current_option = 2
            self.feedback_text += event.character
            event.prevent_default()
            event.stop()

    def action_backspace(self) -> None:
        """Handle backspace in feedback mode."""
        if self.current_option == 2 and self.feedback_text:
            self.feedback_text = self.feedback_text[:-1]

    def action_move_up(self) -> None:
        if self.current_option > 0:
            self.current_option -= 1

    def action_move_down(self) -> None:
        if self.current_option < len(self.OPTIONS) - 1:
            self.current_option += 1

    def action_select(self) -> None:
        option = self.OPTIONS[self.current_option]
        parent = self.parent
        if isinstance(parent, PlanApprovalWidget):
            if option["id"] == "feedback":
                # Feedback mode - send feedback text (or None if empty)
                feedback = self.feedback_text.strip() if self.feedback_text else None
                parent.post_message(
                    PlanApprovalResponseMessage(
                        plan_hash=parent.plan_hash,
                        approved=False,
                        auto_accept_edits=False,
                        feedback=feedback,
                    )
                )
            else:
                # Approve options (1 or 2)
                parent.post_message(
                    PlanApprovalResponseMessage(
                        plan_hash=parent.plan_hash,
                        approved=option["approved"],
                        auto_accept_edits=option["auto_accept_edits"],
                        feedback=None,
                    )
                )

    def action_cancel(self) -> None:
        parent = self.parent
        if isinstance(parent, PlanApprovalWidget):
            parent.post_message(
                PlanApprovalResponseMessage(
                    plan_hash=parent.plan_hash,
                    approved=False,
                    auto_accept_edits=False,
                    feedback=None,
                )
            )

    def render(self) -> RenderableType:
        lines = []
        lines.append(Text("Ready to implement?", style="bold green"))
        lines.append(Text())

        for i, option in enumerate(self.OPTIONS):
            is_selected = i == self.current_option

            # For option 3 (feedback), show inline text input
            if i == 2:
                if self.feedback_text or is_selected:
                    if is_selected:
                        prefix = Text("> ", style="bold green")
                        num = Text(f"{i + 1}  ", style="bold green")
                        if self.feedback_text:
                            # Show typed text + cursor
                            label = Text(self.feedback_text, style="bold green")
                            cursor = Text("_", style="blink bold green")
                            line = Text()
                            line.append(prefix)
                            line.append(num)
                            line.append(label)
                            line.append(cursor)
                        else:
                            # Show just cursor (no text)
                            cursor = Text("_", style="blink bold green")
                            line = Text()
                            line.append(prefix)
                            line.append(num)
                            line.append(cursor)
                        lines.append(line)
                    else:
                        # Not selected but has text
                        prefix = Text("  ", style="dim")
                        num = Text(f"{i + 1}  ", style="dim")
                        label = Text(self.feedback_text or "Provide feedback", style="italic dim")

                        line = Text()
                        line.append(prefix)
                        line.append(num)
                        line.append(label)
                        lines.append(line)
                else:
                    # Not selected, no text yet
                    prefix = Text("  ", style="dim")
                    num = Text(f"{i + 1}  ", style="dim")
                    label = Text(option["label"], style="white")

                    line = Text()
                    line.append(prefix)
                    line.append(num)
                    line.append(label)
                    lines.append(line)

                desc_line = Text("     " + option["description"], style="dim italic")
                lines.append(desc_line)
            else:
                # Options 1 and 2 - regular display
                if is_selected:
                    prefix = Text("> ", style="bold green")
                    num = Text(f"{i + 1}  ", style="bold green")
                    label = Text(option["label"], style="bold green")
                else:
                    prefix = Text("  ", style="dim")
                    num = Text(f"{i + 1}  ", style="dim")
                    label = Text(option["label"], style="white")

                line = Text()
                line.append(prefix)
                line.append(num)
                line.append(label)
                lines.append(line)

                desc_line = Text("     " + option["description"], style="dim italic")
                lines.append(desc_line)

        lines.append(Text())

        footer = Text()
        footer.append("1-3", style="bold cyan")
        footer.append(" select   ", style="dim")
        footer.append("Enter", style="bold cyan")
        footer.append(" confirm   ", style="dim")
        footer.append("Esc", style="bold cyan")
        footer.append(" cancel", style="dim")
        lines.append(footer)

        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append("\n")
            result.append(line)
        return result

    def watch_current_option(self, value: int) -> None:
        self.refresh()

    def watch_feedback_text(self, value: str) -> None:
        """Refresh display when feedback text changes."""
        self.refresh()


class PlanApprovalWidget(Container, can_focus=False):
    """
    Inline widget for plan approval.

    Layout:
    - Scrollable plan content area (max 60% viewport height)
    - Fixed options bar below (3 options with inline feedback capture)
    """

    DEFAULT_CSS = """
    PlanApprovalWidget {
        height: auto;
        padding: 1;
        margin: 1 0;
        background: #1a1a2e;
        border: solid #22c55e;
        color: #e0e0e0;
    }

    PlanApprovalWidget:focus-within {
        border: solid #4ade80;
        background: #16213e;
    }

    PlanApprovalWidget #plan-scroll-area {
        max-height: 50vh;
        height: auto;
        border-bottom: dashed #333;
        margin-bottom: 1;
    }

    PlanApprovalWidget _PlanOptionsDisplay {
        height: auto;
        min-height: 14;
    }
    """

    def __init__(
        self,
        plan_hash: str,
        excerpt: str,
        truncated: bool = False,
        plan_path: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.plan_hash = plan_hash
        self.excerpt = excerpt
        self.truncated = truncated
        self.plan_path = plan_path

    def compose(self):
        with VerticalScroll(id="plan-scroll-area"):
            yield _PlanContent(
                excerpt=self.excerpt,
                truncated=self.truncated,
                plan_path=self.plan_path,
            )
        yield _PlanOptionsDisplay()


# Export
__all__ = ["PlanApprovalWidget"]
