"""Tests for session manager."""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import sys

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.session_manager import SessionManager, SessionMetadata


class TestSessionMetadata:
    """Test SessionMetadata dataclass."""

    def test_create_metadata(self):
        """Test creating SessionMetadata."""
        now = datetime.now().isoformat()
        metadata = SessionMetadata(
            session_id="abc12345-1234-5678-90ab-1234567890ab",
            name="test-session",
            created_at=now,
            updated_at=now,
            task_description="Test task",
            model_name="test-model",
            message_count=42,
            tags=["test", "feature"],
            duration_minutes=135.5,
        )

        assert metadata.session_id == "abc12345-1234-5678-90ab-1234567890ab"
        assert metadata.name == "test-session"
        assert metadata.task_description == "Test task"
        assert metadata.message_count == 42
        assert len(metadata.tags) == 2

    def test_short_id(self):
        """Test short ID property."""
        metadata = SessionMetadata(
            session_id="abc12345-1234-5678-90ab-1234567890ab",
            name="test",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            task_description="Test",
            model_name="test",
            message_count=0,
            tags=[],
            duration_minutes=0.0,
        )

        assert metadata.short_id == "abc12345"

    def test_to_dict(self):
        """Test converting to dictionary."""
        now = datetime.now().isoformat()
        metadata = SessionMetadata(
            session_id="test-id",
            name="test",
            created_at=now,
            updated_at=now,
            task_description="Test",
            model_name="test",
            message_count=5,
            tags=["tag1"],
            duration_minutes=10.0,
        )

        data = metadata.to_dict()

        assert isinstance(data, dict)
        assert data["session_id"] == "test-id"
        assert data["name"] == "test"
        assert data["message_count"] == 5

    def test_from_dict(self):
        """Test creating from dictionary."""
        now = datetime.now().isoformat()
        data = {
            "session_id": "test-id",
            "name": "test",
            "created_at": now,
            "updated_at": now,
            "task_description": "Test",
            "model_name": "test",
            "message_count": 10,
            "tags": ["tag1", "tag2"],
            "duration_minutes": 20.5,
        }

        metadata = SessionMetadata.from_dict(data)

        assert metadata.session_id == "test-id"
        assert metadata.name == "test"
        assert len(metadata.tags) == 2


class TestSessionManager:
    """Test SessionManager class."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        tmpdir = Path(tempfile.mkdtemp())
        yield tmpdir
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def manager(self, temp_dir):
        """Create SessionManager with temporary directory."""
        return SessionManager(sessions_dir=temp_dir)

    @pytest.fixture
    def sample_state(self):
        """Create sample session state."""
        return {
            "working_memory": {
                "messages": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ]
            },
            "episodic_memory": {
                "turns": [
                    {"user": "Hello", "assistant": "Hi there!"}
                ]
            },
            "task_context": {
                "task_id": "task-123",
                "description": "Test task"
            },
            "file_memories": "# Project Memory\nUse 2-space indent",
            "model_name": "test-model",
            "message_count": 2,
            "duration_minutes": 15.0,
        }

    # ==================== Initialization Tests ====================

    def test_init_creates_directory(self, temp_dir):
        """Test that initialization creates sessions directory."""
        sessions_dir = temp_dir / "sessions"
        manager = SessionManager(sessions_dir=sessions_dir)

        assert sessions_dir.exists()
        assert sessions_dir.is_dir()

    def test_init_creates_manifest(self, temp_dir):
        """Test that initialization creates manifest file."""
        sessions_dir = temp_dir / "sessions"
        manager = SessionManager(sessions_dir=sessions_dir)

        manifest_path = sessions_dir / "manifest.json"
        assert manifest_path.exists()

    def test_init_default_location(self):
        """Test initialization with default location."""
        manager = SessionManager()

        # Should create in .clarity/sessions
        expected_path = Path.cwd() / ".clarity" / "sessions"
        assert manager.sessions_dir == expected_path

    # ==================== Save Session Tests ====================

    def test_save_session_basic(self, manager, sample_state):
        """Test saving a basic session."""
        session_id = manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task"
        )

        assert session_id is not None
        assert len(session_id) == 36  # UUID length

        # Check session directory created
        session_dir = manager.sessions_dir / session_id
        assert session_dir.exists()

    def test_save_session_creates_files(self, manager, sample_state):
        """Test that save_session creates all expected files."""
        session_id = manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task"
        )

        session_dir = manager.sessions_dir / session_id

        # Check all files exist
        assert (session_dir / "metadata.json").exists()
        assert (session_dir / "working_memory.json").exists()
        assert (session_dir / "episodic_memory.json").exists()
        assert (session_dir / "task_context.json").exists()
        assert (session_dir / "file_memories.txt").exists()

    def test_save_session_with_tags(self, manager, sample_state):
        """Test saving session with tags."""
        session_id = manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task",
            tags=["feature", "auth", "backend"]
        )

        # Load metadata and check tags
        metadata = manager.get_session_info(session_id)
        assert metadata is not None
        assert len(metadata.tags) == 3
        assert "feature" in metadata.tags
        assert "auth" in metadata.tags

    def test_save_session_without_name(self, manager, sample_state):
        """Test saving session without name."""
        session_id = manager.save_session(
            name=None,
            state=sample_state,
            task_description="Test task"
        )

        metadata = manager.get_session_info(session_id)
        assert metadata.name is None

    def test_save_session_partial_state(self, manager):
        """Test saving session with partial state."""
        partial_state = {
            "working_memory": {"messages": []},
            "model_name": "test-model",
            "message_count": 0,
            "duration_minutes": 0.0,
        }

        session_id = manager.save_session(
            name="partial",
            state=partial_state,
            task_description="Partial test"
        )

        session_dir = manager.sessions_dir / session_id

        # Only working_memory and metadata should exist
        assert (session_dir / "metadata.json").exists()
        assert (session_dir / "working_memory.json").exists()
        assert not (session_dir / "episodic_memory.json").exists()
        assert not (session_dir / "task_context.json").exists()

    # ==================== Load Session Tests ====================

    def test_load_session_full_id(self, manager, sample_state):
        """Test loading session with full ID."""
        session_id = manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task"
        )

        # Load session
        loaded_state = manager.load_session(session_id)

        assert "metadata" in loaded_state
        assert "working_memory" in loaded_state
        assert "episodic_memory" in loaded_state
        assert "task_context" in loaded_state
        assert "file_memories" in loaded_state

    def test_load_session_short_id(self, manager, sample_state):
        """Test loading session with short ID (8 chars)."""
        session_id = manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task"
        )

        short_id = session_id[:8]

        # Load with short ID
        loaded_state = manager.load_session(short_id)

        assert "metadata" in loaded_state
        assert loaded_state["metadata"]["session_id"] == session_id

    def test_load_session_not_found(self, manager):
        """Test loading non-existent session raises error."""
        with pytest.raises(ValueError, match="Session not found"):
            manager.load_session("nonexistent-id")

    def test_load_session_preserves_data(self, manager, sample_state):
        """Test that loaded data matches saved data."""
        session_id = manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task"
        )

        loaded_state = manager.load_session(session_id)

        # Check working memory
        assert loaded_state["working_memory"] == sample_state["working_memory"]

        # Check episodic memory
        assert loaded_state["episodic_memory"] == sample_state["episodic_memory"]

        # Check task context
        assert loaded_state["task_context"] == sample_state["task_context"]

        # Check file memories
        assert loaded_state["file_memories"] == sample_state["file_memories"]

    # ==================== List Sessions Tests ====================

    def test_list_sessions_empty(self, manager):
        """Test listing sessions when none exist."""
        sessions = manager.list_sessions()
        assert len(sessions) == 0

    def test_list_sessions_single(self, manager, sample_state):
        """Test listing with single session."""
        manager.save_session(
            name="test-session",
            state=sample_state,
            task_description="Test task"
        )

        sessions = manager.list_sessions()

        assert len(sessions) == 1
        assert sessions[0].name == "test-session"

    def test_list_sessions_multiple(self, manager, sample_state):
        """Test listing multiple sessions."""
        # Create 3 sessions
        for i in range(3):
            manager.save_session(
                name=f"session-{i}",
                state=sample_state,
                task_description=f"Task {i}"
            )

        sessions = manager.list_sessions()

        assert len(sessions) == 3
        names = [s.name for s in sessions]
        assert "session-0" in names
        assert "session-1" in names
        assert "session-2" in names

    def test_list_sessions_sorted_by_updated(self, manager, sample_state):
        """Test that sessions are sorted by updated_at (newest first)."""
        import time

        # Create sessions with delay to ensure different timestamps
        id1 = manager.save_session("first", sample_state, "Task 1")
        time.sleep(0.1)
        id2 = manager.save_session("second", sample_state, "Task 2")
        time.sleep(0.1)
        id3 = manager.save_session("third", sample_state, "Task 3")

        sessions = manager.list_sessions()

        # Newest should be first
        assert sessions[0].name == "third"
        assert sessions[1].name == "second"
        assert sessions[2].name == "first"

    def test_list_sessions_filter_by_tags(self, manager, sample_state):
        """Test filtering sessions by tags."""
        # Create sessions with different tags
        manager.save_session(
            "auth-work", sample_state, "Auth", tags=["auth", "backend"]
        )
        manager.save_session(
            "ui-work", sample_state, "UI", tags=["ui", "frontend"]
        )
        manager.save_session(
            "api-work", sample_state, "API", tags=["api", "backend"]
        )

        # Filter by backend tag
        backend_sessions = manager.list_sessions(tags=["backend"])
        assert len(backend_sessions) == 2

        # Filter by ui tag
        ui_sessions = manager.list_sessions(tags=["ui"])
        assert len(ui_sessions) == 1
        assert ui_sessions[0].name == "ui-work"

    # ==================== Delete Session Tests ====================

    def test_delete_session_exists(self, manager, sample_state):
        """Test deleting an existing session."""
        session_id = manager.save_session(
            "test-session", sample_state, "Test"
        )

        # Delete
        result = manager.delete_session(session_id)

        assert result is True

        # Verify deleted
        with pytest.raises(ValueError):
            manager.load_session(session_id)

    def test_delete_session_not_found(self, manager):
        """Test deleting non-existent session."""
        result = manager.delete_session("nonexistent-id")
        assert result is False

    def test_delete_session_removes_from_manifest(self, manager, sample_state):
        """Test that delete removes session from manifest."""
        session_id = manager.save_session(
            "test-session", sample_state, "Test"
        )

        # Delete
        manager.delete_session(session_id)

        # Check manifest
        sessions = manager.list_sessions()
        assert len(sessions) == 0

    def test_delete_session_short_id(self, manager, sample_state):
        """Test deleting with short ID."""
        session_id = manager.save_session(
            "test-session", sample_state, "Test"
        )

        short_id = session_id[:8]

        # Delete with short ID
        result = manager.delete_session(short_id)

        assert result is True

    # ==================== Get Session Info Tests ====================

    def test_get_session_info_exists(self, manager, sample_state):
        """Test getting info for existing session."""
        session_id = manager.save_session(
            "test-session", sample_state, "Test task"
        )

        info = manager.get_session_info(session_id)

        assert info is not None
        assert info.session_id == session_id
        assert info.name == "test-session"
        assert info.task_description == "Test task"

    def test_get_session_info_not_found(self, manager):
        """Test getting info for non-existent session."""
        info = manager.get_session_info("nonexistent-id")
        assert info is None

    def test_get_session_info_short_id(self, manager, sample_state):
        """Test getting info with short ID."""
        session_id = manager.save_session(
            "test-session", sample_state, "Test"
        )

        short_id = session_id[:8]
        info = manager.get_session_info(short_id)

        assert info is not None
        assert info.session_id == session_id

    # ==================== Find Session Tests ====================

    def test_find_session_by_name_exists(self, manager, sample_state):
        """Test finding session by name."""
        manager.save_session(
            "my-feature", sample_state, "Feature work"
        )

        session = manager.find_session_by_name("my-feature")

        assert session is not None
        assert session.name == "my-feature"

    def test_find_session_by_name_not_found(self, manager):
        """Test finding non-existent session by name."""
        session = manager.find_session_by_name("nonexistent")
        assert session is None

    def test_find_session_by_name_multiple(self, manager, sample_state):
        """Test finding when multiple sessions exist."""
        # Create multiple sessions
        manager.save_session("session-1", sample_state, "Task 1")
        manager.save_session("session-2", sample_state, "Task 2")
        manager.save_session("session-3", sample_state, "Task 3")

        # Find specific one
        session = manager.find_session_by_name("session-2")

        assert session is not None
        assert session.name == "session-2"

    # ==================== Get Latest Session Tests ====================

    def test_get_latest_session_none(self, manager):
        """Test getting latest when no sessions exist."""
        latest = manager.get_latest_session()
        assert latest is None

    def test_get_latest_session_single(self, manager, sample_state):
        """Test getting latest with single session."""
        manager.save_session("only-session", sample_state, "Task")

        latest = manager.get_latest_session()

        assert latest is not None
        assert latest.name == "only-session"

    def test_get_latest_session_multiple(self, manager, sample_state):
        """Test getting latest with multiple sessions."""
        import time

        # Create sessions with delay
        manager.save_session("old", sample_state, "Old")
        time.sleep(0.1)
        manager.save_session("newer", sample_state, "Newer")
        time.sleep(0.1)
        manager.save_session("newest", sample_state, "Newest")

        latest = manager.get_latest_session()

        assert latest is not None
        assert latest.name == "newest"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
