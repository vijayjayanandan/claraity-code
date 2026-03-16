"""Session lifecycle management.

Manages session lifecycle: create, resume, persist.

Key responsibilities:
- Session file path management
- New session creation (Store starts at seq=0)
- Session resume from JSONL (Store seq continues from file)
- Writer lifecycle management

Per v3.1 Patch 1: NO calls to reset_seq(). Store owns seq authority.
"""

import os
import random
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.observability import get_logger

from ..models.base import SessionContext, generate_uuid

# Security: Valid session ID pattern (UUID format)
SESSION_ID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.IGNORECASE
)
from ..persistence.parser import get_session_info, load_session, validate_session_file
from ..persistence.writer import SessionWriter, create_session_file
from ..store.memory_store import MessageStore

logger = get_logger("session.manager")


@dataclass
class SessionInfo:
    """Session metadata."""

    session_id: str
    file_path: Path
    created_at: datetime
    message_count: int
    is_new: bool


class SessionManager:
    """
    Manages session lifecycle: create, resume, persist.

    Responsibilities:
    - Session file path management
    - New session creation (Store starts at _max_seq=0)
    - Session resume from JSONL (Store seq continues from file)
    - Writer lifecycle management

    Per v3.1 Patch 1: Store owns seq authority. No global reset_seq() calls.
    """

    def __init__(self, sessions_dir: str = ".claraity/sessions", version: str = "1.0.0"):
        self._sessions_dir = Path(sessions_dir)
        self._version = version

        # Current session state
        self._store: MessageStore | None = None
        self._writer: SessionWriter | None = None
        self._context: SessionContext | None = None
        self._session_info: SessionInfo | None = None

        # Ensure sessions directory exists
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Session Lifecycle
    # =========================================================================

    def create_session(
        self, cwd: str | None = None, git_branch: str | None = None, slug: str | None = None
    ) -> SessionInfo:
        """
        Create a new session.

        Store starts with _max_seq=0, so first message gets seq=1.
        Per v3.1 Patch 1: NO reset_seq() call - Store handles this internally.

        Note: Session file is NOT created until the first message is written.
        This prevents empty session files from cluttering the sessions directory.
        """
        session_id = generate_uuid()
        file_path = self._sessions_dir / f"{session_id}.jsonl"

        # Create context
        self._context = SessionContext(
            session_id=session_id,
            cwd=cwd or os.getcwd(),
            git_branch=git_branch or self._detect_git_branch(),
            version=self._version,
            slug=slug or self._generate_slug(),
        )

        # Create store (starts at _max_seq=0)
        self._store = MessageStore()

        # DO NOT create file yet - it will be created on first write
        # This prevents empty session files from appearing in /resume

        # Create writer (not opened yet - call start_writer())
        self._writer = SessionWriter(file_path)

        # Session info
        self._session_info = SessionInfo(
            session_id=session_id,
            file_path=file_path,
            created_at=datetime.utcnow(),
            message_count=0,
            is_new=True,
        )

        logger.info(f"Created new session: {session_id}")
        return self._session_info

    def resume_session(
        self, session_id: str, on_progress: Callable[[int, int], None] | None = None
    ) -> SessionInfo:
        """
        Resume an existing session from JSONL file.

        Store's _max_seq is set during load_session() from line numbers.
        Per v3.1 Patch 1: NO reset_seq() call - Store already has correct max.

        Raises:
            ValueError: If session_id is not a valid UUID format
            FileNotFoundError: If session file does not exist
        """
        # Security: Validate session ID to prevent path traversal
        self._validate_session_id(session_id)

        file_path = self._sessions_dir / f"{session_id}.jsonl"

        if not file_path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        # Validate file first (optional, logs warnings)
        is_valid, errors = validate_session_file(file_path)
        if not is_valid:
            logger.warning(f"Session file has issues: {errors[:3]}")

        # Create store and load (store._max_seq set from file)
        self._store = MessageStore()
        load_session(file_path, self._store, on_progress)

        # Extract context from first message
        messages = self._store.get_ordered_messages()
        if messages:
            first_msg = messages[0]
            self._context = SessionContext(
                session_id=session_id,
                cwd=getattr(first_msg, "cwd", os.getcwd()),
                git_branch=getattr(first_msg, "git_branch", ""),
                version=getattr(first_msg, "version", self._version),
                slug=getattr(first_msg, "slug", None),
            )
        else:
            self._context = SessionContext(
                session_id=session_id,
                cwd=os.getcwd(),
                git_branch=self._detect_git_branch(),
                version=self._version,
            )

        # Create writer (not opened yet - call start_writer())
        self._writer = SessionWriter(file_path)

        # Session info
        self._session_info = SessionInfo(
            session_id=session_id,
            file_path=file_path,
            created_at=datetime.utcnow(),
            message_count=self._store.message_count,
            is_new=False,
        )

        logger.info(f"Resumed session: {session_id} with {self._store.message_count} messages")
        return self._session_info

    async def start_writer(self) -> None:
        """
        Start the async writer and bind to store.

        MUST be called from the async context where the app runs.
        """
        if self._writer and self._store:
            await self._writer.open()
            self._writer.bind_to_store(self._store)
            logger.debug("Writer started and bound to store")

    async def close(self) -> None:
        """Close the current session gracefully."""
        if self._writer:
            await self._writer.close()
            self._writer = None

        self._store = None
        self._context = None
        self._session_info = None
        logger.debug("Session closed")

    # =========================================================================
    # Session Discovery
    # =========================================================================

    def list_sessions(self, limit: int | None = None) -> list[SessionInfo]:
        """list all available sessions, sorted by modification time (newest first)."""
        sessions = []

        for file_path in self._sessions_dir.glob("*.jsonl"):
            session_id = file_path.stem

            try:
                # Get line count efficiently
                line_count = sum(1 for line in open(file_path, encoding="utf-8") if line.strip())
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                sessions.append(
                    SessionInfo(
                        session_id=session_id,
                        file_path=file_path,
                        created_at=mtime,
                        message_count=line_count,
                        is_new=False,
                    )
                )
            except Exception as e:
                logger.warning(f"Error reading session {session_id}: {e}")
                continue

        # Sort by modification time (newest first)
        sessions.sort(key=lambda s: s.created_at, reverse=True)

        if limit:
            sessions = sessions[:limit]

        return sessions

    def get_recent_session(self) -> str | None:
        """Get the most recent session ID."""
        sessions = self.list_sessions(limit=1)
        return sessions[0].session_id if sessions else None

    def session_exists(self, session_id: str) -> bool:
        """
        Check if a session file exists.

        Args:
            session_id: Session ID to check

        Returns:
            True if session file exists

        Raises:
            ValueError: If session_id is not a valid UUID format
        """
        # Security: Validate session ID to prevent path traversal
        self._validate_session_id(session_id)
        file_path = self._sessions_dir / f"{session_id}.jsonl"
        return file_path.exists()

    def get_session_file_path(self, session_id: str) -> Path:
        """
        Get file path for a session ID.

        Args:
            session_id: Session ID

        Returns:
            Path to session file

        Raises:
            ValueError: If session_id is not a valid UUID format
        """
        # Security: Validate session ID to prevent path traversal
        self._validate_session_id(session_id)
        return self._sessions_dir / f"{session_id}.jsonl"

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session file.

        Args:
            session_id: Session ID to delete

        Returns:
            True if session was deleted, False if not found

        Raises:
            ValueError: If session_id is not a valid UUID format
        """
        # Security: Validate session ID to prevent path traversal
        self._validate_session_id(session_id)
        file_path = self._sessions_dir / f"{session_id}.jsonl"

        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted session: {session_id}")
            return True
        return False

    # =========================================================================
    # Accessors
    # =========================================================================

    @property
    def store(self) -> MessageStore | None:
        return self._store

    @property
    def context(self) -> SessionContext | None:
        return self._context

    @property
    def info(self) -> SessionInfo | None:
        return self._session_info

    @property
    def is_active(self) -> bool:
        return self._store is not None

    @property
    def sessions_dir(self) -> Path:
        return self._sessions_dir

    # =========================================================================
    # Helpers
    # =========================================================================

    def _validate_session_id(self, session_id: str) -> None:
        """
        Validate session ID format to prevent path traversal attacks.

        Args:
            session_id: Session ID to validate

        Raises:
            ValueError: If session_id is not a valid UUID format
        """
        if not session_id or not SESSION_ID_PATTERN.match(session_id):
            raise ValueError(
                f"Invalid session ID format: '{session_id}'. "
                "Session ID must be a valid UUID (e.g., 'a1b2c3d4-e5f6-7890-abcd-ef1234567890')"
            )

    def _detect_git_branch(self) -> str:
        """Detect current Git branch."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "main"

    def _generate_slug(self) -> str:
        """Generate a human-readable session slug."""
        adjectives = ["swift", "bright", "calm", "eager", "fair", "glad", "keen", "neat"]
        nouns = ["fox", "owl", "elk", "bee", "ant", "jay", "cod", "emu"]

        adj = random.choice(adjectives)
        noun = random.choice(nouns)
        num = random.randint(100, 999)

        return f"{adj}-{noun}-{num}"
