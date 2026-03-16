"""Session scanner -- find and summarise JSONL session files.

Extracted from ``src/ui/session_picker.py`` so it can be imported
without pulling in Textual (which is excluded from the bundled binary).
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.observability import get_logger

logger = get_logger("session.scanner")


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
    """Scan sessions directory for available sessions.

    Args:
        sessions_dir: Path to .clarity/sessions directory
        limit: Maximum number of sessions to return

    Returns:
        list of SessionDisplay objects, sorted by updated_at (newest first)
    """
    sessions: list[SessionDisplay] = []

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
    """Extract session info from JSONL file.

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
        with open(jsonl_path, encoding="utf-8") as f:
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
            git_branch=git_branch,
        )

    except Exception as e:
        logger.debug(f"Error extracting session info from {jsonl_path}: {e}")
        return None
