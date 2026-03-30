"""Session Picker Screen - Interactive session resume UI.

A modal screen that displays available JSONL sessions for the user to resume.
Inspired by Claude Code's /resume UX.

Features:
- Lists sessions from .claraity/sessions/ directory
- Shows first user message as session title (truncated)
- Displays relative time, message count, git branch
- Keyboard navigation with arrow keys
- Enter to select, Escape to cancel
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from src.session.scanner import SessionDisplay, scan_sessions  # noqa: F401


class SessionPickerScreen(ModalScreen[str | None]):
    """
    Modal screen for selecting a session to resume.

    Returns:
        Selected session_id on selection, None on cancel
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "select", "Select", show=False),
    ]

    DEFAULT_CSS = """
    SessionPickerScreen {
        align: center middle;
    }

    SessionPickerScreen > Vertical {
        width: 90%;
        max-width: 120;
        height: 80%;
        max-height: 40;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    SessionPickerScreen #title {
        text-align: center;
        text-style: bold;
        color: $text;
        padding-bottom: 1;
    }

    SessionPickerScreen #search {
        margin-bottom: 1;
    }

    SessionPickerScreen OptionList {
        height: 1fr;
        scrollbar-gutter: stable;
    }

    SessionPickerScreen OptionList > .option-list--option {
        padding: 0 1;
    }

    SessionPickerScreen .session-title {
        color: $text;
    }

    SessionPickerScreen .session-meta {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        sessions_dir: Path,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self._sessions_dir = sessions_dir
        self._sessions: list[SessionDisplay] = []
        self._filtered_sessions: list[SessionDisplay] = []

    def compose(self) -> ComposeResult:
        """Compose the session picker UI."""
        with Vertical():
            yield Static("Resume Session", id="title")
            yield Input(placeholder="Search...", id="search")
            yield OptionList(id="session-list")

    def on_mount(self) -> None:
        """Load sessions when screen mounts."""
        self._sessions = scan_sessions(self._sessions_dir)
        self._filtered_sessions = self._sessions
        self._populate_list()

        # Focus search input
        self.query_one("#search", Input).focus()

    def _populate_list(self) -> None:
        """Populate the option list with sessions."""
        option_list = self.query_one("#session-list", OptionList)
        option_list.clear_options()

        if not self._filtered_sessions:
            option_list.add_option(Option("[No sessions found]", id="__none__", disabled=True))
            return

        for session in self._filtered_sessions:
            # Create rich text for option
            # Title line + meta line
            prompt_text = f"{session.display_title}\n[dim]{session.display_meta}[/dim]"
            option_list.add_option(Option(prompt_text, id=session.session_id))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter sessions based on search input."""
        query = event.value.lower().strip()

        if not query:
            self._filtered_sessions = self._sessions
        else:
            self._filtered_sessions = [
                s
                for s in self._sessions
                if query in s.first_message.lower()
                or query in s.session_id.lower()
                or (s.git_branch and query in s.git_branch.lower())
            ]

        self._populate_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle session selection."""
        if event.option_id and event.option_id != "__none__":
            self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        """Cancel and close the picker."""
        self.dismiss(None)

    def action_select(self) -> None:
        """Select the highlighted option."""
        option_list = self.query_one("#session-list", OptionList)
        if option_list.highlighted is not None:
            option = option_list.get_option_at_index(option_list.highlighted)
            if option and option.id and option.id != "__none__":
                self.dismiss(option.id)
