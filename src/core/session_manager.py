"""Session manager for save/resume functionality.

This module provides comprehensive session persistence allowing users to:
- Save current coding session with all context
- Resume previous sessions seamlessly
- List, manage, and organize saved sessions
- Share sessions with team members

Session Storage Structure:
    .opencodeagent/
      sessions/
        manifest.json                 # Index of all sessions
        <session-id>/
          metadata.json               # Session info
          working_memory.json         # Current conversation
          episodic_memory.json        # Conversation history
          task_context.json           # Current task
          file_memories.txt           # Loaded CLAUDE.md content
"""

import json
import shutil
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    """Metadata about a saved session.

    Attributes:
        session_id: Unique session identifier (UUID)
        name: Optional human-readable name
        created_at: Session creation timestamp
        updated_at: Last update timestamp
        task_description: Description of the task being worked on
        model_name: LLM model used
        message_count: Number of messages in conversation
        tags: Optional list of tags for organization
        duration_minutes: Total time spent on session
        permission_mode: Permission mode when session was saved (plan/normal/auto)
    """
    session_id: str
    name: Optional[str]
    created_at: str  # ISO format
    updated_at: str  # ISO format
    task_description: str
    model_name: str
    message_count: int
    tags: List[str]
    duration_minutes: float
    permission_mode: str = "normal"  # Default to normal mode for backward compatibility

    @property
    def short_id(self) -> str:
        """Get short ID (first 8 chars) for display."""
        return self.session_id[:8]

    @property
    def created_datetime(self) -> datetime:
        """Get created_at as datetime object."""
        return datetime.fromisoformat(self.created_at)

    @property
    def updated_datetime(self) -> datetime:
        """Get updated_at as datetime object."""
        return datetime.fromisoformat(self.updated_at)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMetadata":
        """Create from dictionary."""
        return cls(**data)


class SessionManager:
    """Manages session persistence and retrieval.

    Handles saving/loading complete agent state including:
    - Conversation history (working + episodic memory)
    - Task context
    - File memories (loaded CLAUDE.md files)
    - Model configuration

    Example:
        >>> manager = SessionManager()
        >>> session_id = manager.save_session("my-feature", agent)
        >>> print(f"Saved: {session_id[:8]}")
        >>>
        >>> # Later...
        >>> state = manager.load_session(session_id)
        >>> # Apply state to agent
    """

    def __init__(self, sessions_dir: Optional[Path] = None):
        """Initialize session manager.

        Args:
            sessions_dir: Directory for session storage
                         (default: .opencodeagent/sessions)
        """
        if sessions_dir is None:
            sessions_dir = Path.cwd() / ".opencodeagent" / "sessions"

        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.manifest_path = self.sessions_dir / "manifest.json"

        # Initialize manifest if doesn't exist
        if not self.manifest_path.exists():
            self._save_manifest({})

        logger.info(f"SessionManager initialized (dir: {self.sessions_dir})")

    def save_session(
        self,
        name: Optional[str],
        state: Dict[str, Any],
        task_description: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Save a session with complete state.

        Args:
            name: Optional human-readable name
            state: Complete session state dictionary containing:
                  - working_memory: Current conversation
                  - episodic_memory: Conversation history
                  - task_context: Current task info
                  - file_memories: Loaded CLAUDE.md content
                  - model_name: LLM model name
                  - message_count: Number of messages
                  - duration_minutes: Session duration
            task_description: Description of task being worked on
            tags: Optional list of tags

        Returns:
            session_id: Unique session identifier

        Example:
            >>> state = {
            ...     "working_memory": {...},
            ...     "episodic_memory": {...},
            ...     "task_context": {...},
            ...     "file_memories": "...",
            ...     "model_name": "qwen3-coder:30b",
            ...     "message_count": 42,
            ...     "duration_minutes": 135.5
            ... }
            >>> session_id = manager.save_session("feature-auth", state)
        """
        # Generate session ID
        session_id = str(uuid.uuid4())

        # Create metadata
        now = datetime.now().isoformat()
        metadata = SessionMetadata(
            session_id=session_id,
            name=name,
            created_at=now,
            updated_at=now,
            task_description=task_description,
            model_name=state.get("model_name", "unknown"),
            message_count=state.get("message_count", 0),
            tags=tags or [],
            duration_minutes=state.get("duration_minutes", 0.0),
            permission_mode=state.get("permission_mode", "normal"),
        )

        # Create session directory
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata_path = session_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

        # Save state components
        if "working_memory" in state:
            with open(session_dir / "working_memory.json", "w") as f:
                json.dump(state["working_memory"], f, indent=2)

        if "episodic_memory" in state:
            with open(session_dir / "episodic_memory.json", "w") as f:
                json.dump(state["episodic_memory"], f, indent=2)

        if "task_context" in state:
            with open(session_dir / "task_context.json", "w") as f:
                json.dump(state["task_context"], f, indent=2)

        if "file_memories" in state:
            with open(session_dir / "file_memories.txt", "w") as f:
                f.write(state["file_memories"])

        # Update manifest
        self._add_to_manifest(metadata)

        logger.info(f"Saved session: {metadata.short_id} ({name})")
        return session_id

    def load_session(self, session_id: str) -> Dict[str, Any]:
        """Load a session by ID.

        Args:
            session_id: Full or short (8 chars) session ID

        Returns:
            Complete session state dictionary

        Raises:
            ValueError: If session not found

        Example:
            >>> state = manager.load_session("abc12345")
            >>> working_memory = state["working_memory"]
            >>> metadata = state["metadata"]
        """
        # Find session directory
        session_dir = self._find_session_dir(session_id)
        if not session_dir:
            raise ValueError(f"Session not found: {session_id}")

        # Load metadata
        metadata_path = session_dir / "metadata.json"
        if not metadata_path.exists():
            raise ValueError(f"Session metadata not found: {session_id}")

        with open(metadata_path, "r") as f:
            metadata = SessionMetadata.from_dict(json.load(f))

        # Load state components
        state = {"metadata": metadata.to_dict()}

        working_memory_path = session_dir / "working_memory.json"
        if working_memory_path.exists():
            with open(working_memory_path, "r") as f:
                state["working_memory"] = json.load(f)

        episodic_memory_path = session_dir / "episodic_memory.json"
        if episodic_memory_path.exists():
            with open(episodic_memory_path, "r") as f:
                state["episodic_memory"] = json.load(f)

        task_context_path = session_dir / "task_context.json"
        if task_context_path.exists():
            with open(task_context_path, "r") as f:
                state["task_context"] = json.load(f)

        file_memories_path = session_dir / "file_memories.txt"
        if file_memories_path.exists():
            with open(file_memories_path, "r") as f:
                state["file_memories"] = f.read()

        logger.info(f"Loaded session: {metadata.short_id} ({metadata.name})")
        return state

    def list_sessions(self, tags: Optional[List[str]] = None) -> List[SessionMetadata]:
        """List all saved sessions.

        Args:
            tags: Optional filter by tags (sessions with ANY of these tags)

        Returns:
            List of SessionMetadata objects, sorted by updated_at (newest first)

        Example:
            >>> sessions = manager.list_sessions()
            >>> for session in sessions:
            ...     print(f"{session.short_id}: {session.name}")
        """
        manifest = self._load_manifest()

        sessions = []
        for session_data in manifest.values():
            metadata = SessionMetadata.from_dict(session_data)

            # Filter by tags if specified
            if tags:
                if not any(tag in metadata.tags for tag in tags):
                    continue

            sessions.append(metadata)

        # Sort by updated_at (newest first)
        sessions.sort(key=lambda s: s.updated_datetime, reverse=True)

        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Full or short session ID

        Returns:
            True if deleted, False if not found

        Example:
            >>> manager.delete_session("abc12345")
            True
        """
        session_dir = self._find_session_dir(session_id)
        if not session_dir:
            logger.warning(f"Session not found: {session_id}")
            return False

        # Get full ID from directory name
        full_id = session_dir.name

        # Remove from manifest
        self._remove_from_manifest(full_id)

        # Delete directory
        shutil.rmtree(session_dir)

        logger.info(f"Deleted session: {session_id[:8]}")
        return True

    def get_session_info(self, session_id: str) -> Optional[SessionMetadata]:
        """Get session metadata without loading full state.

        Args:
            session_id: Full or short session ID

        Returns:
            SessionMetadata or None if not found

        Example:
            >>> info = manager.get_session_info("abc12345")
            >>> print(f"Task: {info.task_description}")
        """
        session_dir = self._find_session_dir(session_id)
        if not session_dir:
            return None

        metadata_path = session_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        with open(metadata_path, "r") as f:
            return SessionMetadata.from_dict(json.load(f))

    def find_session_by_name(self, name: str) -> Optional[SessionMetadata]:
        """Find a session by name.

        Args:
            name: Session name to search for

        Returns:
            SessionMetadata or None if not found

        Example:
            >>> session = manager.find_session_by_name("feature-auth")
            >>> if session:
            ...     state = manager.load_session(session.session_id)
        """
        sessions = self.list_sessions()

        for session in sessions:
            if session.name == name:
                return session

        return None

    def get_latest_session(self) -> Optional[SessionMetadata]:
        """Get the most recently updated session.

        Returns:
            SessionMetadata or None if no sessions exist

        Example:
            >>> latest = manager.get_latest_session()
            >>> if latest:
            ...     state = manager.load_session(latest.session_id)
        """
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def _find_session_dir(self, session_id: str) -> Optional[Path]:
        """Find session directory by full or short ID.

        Args:
            session_id: Full or short (8 chars) session ID

        Returns:
            Path to session directory or None if not found
        """
        # Try exact match first
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            return session_dir

        # Try short ID match (first 8 chars)
        if len(session_id) == 8:
            for child in self.sessions_dir.iterdir():
                if child.is_dir() and child.name.startswith(session_id):
                    return child

        return None

    def _load_manifest(self) -> Dict[str, Dict[str, Any]]:
        """Load session manifest.

        Returns:
            Dictionary mapping session_id to metadata dict
        """
        if not self.manifest_path.exists():
            return {}

        try:
            with open(self.manifest_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load manifest: {e}")
            return {}

    def _save_manifest(self, manifest: Dict[str, Dict[str, Any]]) -> None:
        """Save session manifest.

        Args:
            manifest: Dictionary mapping session_id to metadata dict
        """
        try:
            with open(self.manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save manifest: {e}")

    def _add_to_manifest(self, metadata: SessionMetadata) -> None:
        """Add session to manifest.

        Args:
            metadata: Session metadata to add
        """
        manifest = self._load_manifest()
        manifest[metadata.session_id] = metadata.to_dict()
        self._save_manifest(manifest)

    def _remove_from_manifest(self, session_id: str) -> None:
        """Remove session from manifest.

        Args:
            session_id: Full session ID to remove
        """
        manifest = self._load_manifest()
        if session_id in manifest:
            del manifest[session_id]
            self._save_manifest(manifest)
