"""Session Picker Screen - Interactive session resume UI.

A modal screen that displays available JSONL sessions for the user to resume.
Inspired by Claude Code's /resume UX.

Features:
- Lists sessions from .clarity/sessions/ directory
- Shows first user message as session title (truncated)
- Displays relative time, message count, git branch
- Keyboard navigation with arrow keys
- Enter to select, Escape to cancel
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from src.observability import get_logger

logger = get_logger("ui.session_picker")


@dataclass
class SessionDisplay:
    """Session information for display in picker."""
    session_id: str
    file_path: Path
    first_message: str
    message_count: int
    updated_at: datetime
    git_branch: str | None = None

    @property
    def time_ago(self) -> str:
        """Format updated_at as relative time."""
        now = datetime.now()
        delta = now - self.updated_at

        if delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "just now"

    @property
    def display_title(self) -> str:
        """Truncated first message for display."""
        max_len = 80
        title = self.first_message.replace("\n", " ").strip()
        if len(title) > max_len:
            return title[:max_len] + "..."
        return title

    @property
    def display_meta(self) -> str:
        """Metadata line: time ago - message count - branch."""
        parts = [self.time_ago, f"{self.message_count} messages"]
        if self.git_branch:
            parts.append(self.git_branch)
        return " - ".join(parts)


def scan_sessions(sessions_dir: Path, limit: int = 50) -> list[SessionDisplay]:
    """
    Scan sessions directory for available sessions.

    Args:
        sessions_dir: Path to .clarity/sessions directory
        limit: Maximum number of sessions to return

    Returns:
        list of SessionDisplay objects, sorted by updated_at (newest first)
    """
    sessions = []

    if not sessions_dir.exists():
        return sessions

    # Find all session directories or JSONL files
    for item in sessions_dir.iterdir():
        try:
            # Handle both directory structure and flat files
            if item.is_dir():
                jsonl_path = item / "session.jsonl"
                session_id = item.name
            elif item.suffix == ".jsonl":
                jsonl_path = item
                session_id = item.stem
            else:
                continue

            if not jsonl_path.exists():
                continue

            # Extract session info from JSONL
            session_info = _extract_session_info(jsonl_path, session_id)
            if session_info:
                sessions.append(session_info)

        except Exception as e:
            logger.debug(f"Error scanning session {item}: {e}")
            continue

    # Sort by updated_at (newest first)
    sessions.sort(key=lambda s: s.updated_at, reverse=True)

    return sessions[:limit]


def _extract_session_info(jsonl_path: Path, session_id: str) -> SessionDisplay | None:
    """
    Extract session info from JSONL file.

    Reads first few lines to find:
    - First user message (for title)
    - Git branch (from meta)
    - Message count (line count)
    - Updated time (file mtime)
    """
    first_user_message = None
    git_branch = None
    message_count = 0

    try:
        with open(jsonl_path, encoding='utf-8') as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                message_count += 1

                # Only parse first 20 lines to find first user message
                if i < 20 and first_user_message is None:
                    try:
                        data = json.loads(line)
                        role = data.get("role")

                        # Extract git branch from first message's meta
                        if i == 0:
                            meta = data.get("meta", {})
                            git_branch = meta.get("git_branch")

                        # Find first user message
                        if role == "user":
                            content = data.get("content", "")
                            if content and isinstance(content, str):
                                first_user_message = content
                    except json.JSONDecodeError:
                        continue

        # Get file modification time
        updated_at = datetime.fromtimestamp(jsonl_path.stat().st_mtime)

        # Default title if no user message found
        if not first_user_message:
            first_user_message = f"[Session {session_id[:8]}]"

        return SessionDisplay(
            session_id=session_id,
            file_path=jsonl_path,
            first_message=first_user_message,
            message_count=message_count,
            updated_at=updated_at,
            git_branch=git_branch
        )

    except Exception as e:
        logger.debug(f"Error extracting session info from {jsonl_path}: {e}")
        return None


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
        classes: str | None = None
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
            option_list.add_option(Option(
                "[No sessions found]",
                id="__none__",
                disabled=True
            ))
            return

        for session in self._filtered_sessions:
            # Create rich text for option
            # Title line + meta line
            prompt_text = f"{session.display_title}\n[dim]{session.display_meta}[/dim]"
            option_list.add_option(Option(
                prompt_text,
                id=session.session_id
            ))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter sessions based on search input."""
        query = event.value.lower().strip()

        if not query:
            self._filtered_sessions = self._sessions
        else:
            self._filtered_sessions = [
                s for s in self._sessions
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
