"""
Attachment bar widget with keyboard navigation and mouse support.

Displays attachments horizontally with selection highlighting.
Supports:
- Keyboard: Left/Right to navigate, Backspace to remove, Escape to exit
- Mouse: Click to select, click X to remove
"""

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

if TYPE_CHECKING:
    from src.core.attachment import Attachment


class AttachmentBar(Widget, can_focus=True):
    """
    Horizontal bar showing attachments with selection support.

    When focused:
    - Left/Right arrows navigate between attachments
    - Backspace removes selected attachment
    - Escape returns focus to input

    Mouse:
    - Click to select
    - Click [x] to remove
    """

    DEFAULT_CSS = """
    AttachmentBar {
        height: 1;
        width: 100%;
        background: $surface;
        padding: 0 1;
        display: none;
    }

    AttachmentBar.-has-attachments {
        display: block;
    }

    AttachmentBar:focus {
        background: $surface-lighten-1;
    }
    """

    BINDINGS = [
        Binding("left", "select_prev", "Previous", show=False),
        Binding("right", "select_next", "Next", show=False),
        Binding("backspace", "remove_selected", "Remove", show=False),
        Binding("delete", "remove_selected", "Remove", show=False),
        Binding("escape", "exit_to_input", "Exit", show=False),
        Binding("down", "exit_to_input", "Exit", show=False),
        Binding("enter", "exit_to_input", "Exit", show=False),
    ]

    selected_index: reactive[int] = reactive(0)

    class AttachmentRemoved(Message):
        """Sent when an attachment is removed."""

        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    class ExitToInput(Message):
        """Sent when user wants to return to input."""

        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attachments: list[Attachment] = []
        self._hover_index: int = -1  # Track mouse hover

    def update_attachments(self, attachments: list["Attachment"]) -> None:
        """Update the list of attachments."""
        self._attachments = attachments

        # Show/hide based on attachment count
        if attachments:
            self.add_class("-has-attachments")
        else:
            self.remove_class("-has-attachments")

        # Clamp selected index
        if self.selected_index >= len(attachments):
            self.selected_index = max(0, len(attachments) - 1)

        self.refresh()

    def render(self) -> Text:
        """Render the attachment bar."""
        if not self._attachments:
            return Text("")

        result = Text()
        is_focused = self.has_focus

        for i, att in enumerate(self._attachments):
            # Determine display name
            if att.kind == "image":
                name = f"Image #{i + 1}"
            else:
                # Truncate long filenames
                name = att.filename
                if len(name) > 20:
                    name = name[:17] + "..."

            # Build the attachment chip
            is_selected = (i == self.selected_index) and is_focused
            is_hovered = i == self._hover_index

            if is_selected:
                # Selected: inverse colors
                result.append(" [", style="bold cyan")
                result.append(name, style="bold reverse cyan")
                result.append(" x]", style="bold cyan")
            elif is_hovered:
                # Hovered: highlighted
                result.append(" [", style="yellow")
                result.append(name, style="yellow")
                result.append(" x]", style="bold yellow")
            else:
                # Normal
                result.append(" [", style="dim")
                result.append(name, style="")
                result.append(" x]", style="dim red")

            result.append(" ")

        # Add hint when focused
        if is_focused:
            result.append("| ", style="dim")
            result.append("</>: nav  ", style="dim cyan")
            result.append("Bksp: remove  ", style="dim red")
            result.append("Esc: back", style="dim")

        return result

    def action_select_prev(self) -> None:
        """Select previous attachment."""
        if self._attachments and self.selected_index > 0:
            self.selected_index -= 1

    def action_select_next(self) -> None:
        """Select next attachment."""
        if self._attachments and self.selected_index < len(self._attachments) - 1:
            self.selected_index += 1

    def action_remove_selected(self) -> None:
        """Remove the selected attachment."""
        if self._attachments and 0 <= self.selected_index < len(self._attachments):
            self.post_message(self.AttachmentRemoved(self.selected_index))

    def action_exit_to_input(self) -> None:
        """Return focus to input."""
        self.post_message(self.ExitToInput())

    def on_click(self, event: events.Click) -> None:
        """Handle mouse click - select or remove attachment."""
        # Calculate which attachment was clicked based on x position
        if not self._attachments:
            return

        # Find attachment at click position
        click_index = self._get_attachment_at_x(event.x)

        if click_index >= 0:
            # Check if click was on the 'x' (remove button)
            if self._is_click_on_remove(event.x, click_index):
                self.post_message(self.AttachmentRemoved(click_index))
            else:
                # Just select it
                self.selected_index = click_index
                self.focus()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Track hover for visual feedback."""
        old_hover = self._hover_index
        self._hover_index = self._get_attachment_at_x(event.x)
        if old_hover != self._hover_index:
            self.refresh()

    def on_leave(self, event: events.Leave) -> None:
        """Clear hover when mouse leaves."""
        if self._hover_index >= 0:
            self._hover_index = -1
            self.refresh()

    def _get_attachment_at_x(self, x: int) -> int:
        """Get attachment index at x coordinate, or -1 if none."""
        if not self._attachments:
            return -1

        # Calculate positions (approximate based on rendering)
        current_x = 1  # Start after padding

        for i, att in enumerate(self._attachments):
            if att.kind == "image":
                name = f"Image #{i + 1}"
            else:
                name = att.filename[:20] if len(att.filename) > 20 else att.filename

            # Width: " [" + name + " x] " = len(name) + 6
            width = len(name) + 6

            if current_x <= x < current_x + width:
                return i

            current_x += width + 1

        return -1

    def _is_click_on_remove(self, x: int, index: int) -> bool:
        """Check if click x is on the 'x' remove button of attachment at index."""
        if not self._attachments or index < 0:
            return False

        # Calculate position of attachment
        current_x = 1

        for i, att in enumerate(self._attachments):
            if att.kind == "image":
                name = f"Image #{i + 1}"
            else:
                name = att.filename[:20] if len(att.filename) > 20 else att.filename

            width = len(name) + 6

            if i == index:
                # The 'x' is at the end: " [name x] "
                # x button is at current_x + len(" [") + len(name) + len(" ") = current_x + 3 + len(name)
                x_button_start = current_x + 3 + len(name)
                x_button_end = x_button_start + 2  # "x]"
                return x_button_start <= x <= x_button_end

            current_x += width + 1

        return False

    def watch_selected_index(self, new_index: int) -> None:
        """React to selection changes."""
        self.refresh()
