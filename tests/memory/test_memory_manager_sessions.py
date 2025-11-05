"""Tests for MemoryManager session persistence with SessionManager integration."""

import pytest
import tempfile
import shutil
from pathlib import Path
import sys

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory.memory_manager import MemoryManager
from src.memory.models import MessageRole, TaskContext
from src.core.session_manager import SessionManager


class TestMemoryManagerSessions:
    """Test MemoryManager session save/load with SessionManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        tmpdir = Path(tempfile.mkdtemp())
        yield tmpdir
        shutil.rmtree(tmpdir)

    @pytest.fixture
    def memory_manager(self, temp_dir, monkeypatch):
        """Create MemoryManager with temporary persist directory."""
        # Disable semantic memory initialization to avoid ChromaDB conflicts
        def mock_semantic_init(self, **kwargs):
            self.collection = None
            self.persist_directory = kwargs.get('persist_directory')

        monkeypatch.setattr(
            "src.memory.semantic_memory.SemanticMemory.__init__",
            mock_semantic_init
        )

        return MemoryManager(
            total_context_tokens=4096,
            working_memory_tokens=2000,
            persist_directory=str(temp_dir),
            load_file_memories=False,  # Skip file loading for tests
        )

    @pytest.fixture
    def populated_manager(self, memory_manager):
        """Create MemoryManager with populated data."""
        # Add conversation
        memory_manager.add_user_message("Hello, can you help me with authentication?")
        memory_manager.add_assistant_message("Sure! I can help with authentication.")

        memory_manager.add_user_message("How do I implement JWT tokens?")
        memory_manager.add_assistant_message(
            "Here's how to implement JWT tokens...",
            tool_calls=[{"tool": "read_file", "args": {"path": "auth.py"}}]
        )

        # Set task context
        task = TaskContext(
            task_id="auth-task",
            description="Implement JWT authentication",
            task_type="implement",
            status="in_progress",
            related_files=["auth.py", "user.py"],
            key_concepts=["JWT", "tokens", "authentication"],
            constraints=["Must be secure"],
        )
        memory_manager.set_task_context(task)

        # Add file memory
        memory_manager.file_memory_content = "# Project Memory\nUse 2-space indentation"

        return memory_manager

    # ==================== Save Session Tests ====================

    def test_save_session_creates_session(self, populated_manager):
        """Test that save_session creates a new session."""
        session_id = populated_manager.save_session(
            session_name="test-session",
            task_description="Test task",
            tags=["test"],
        )

        # Should return a valid session ID (UUID format)
        assert session_id is not None
        assert len(session_id) == 36  # UUID length

    def test_save_session_saves_all_components(self, populated_manager, temp_dir):
        """Test that save_session saves all memory components."""
        session_id = populated_manager.save_session(
            session_name="complete-session",
            task_description="Complete test",
        )

        # Check that session directory exists
        sessions_dir = temp_dir / "sessions"
        session_dir = sessions_dir / session_id

        assert session_dir.exists()
        assert (session_dir / "metadata.json").exists()
        assert (session_dir / "working_memory.json").exists()
        assert (session_dir / "episodic_memory.json").exists()
        assert (session_dir / "task_context.json").exists()
        assert (session_dir / "file_memories.txt").exists()

    def test_save_session_with_tags(self, populated_manager):
        """Test saving session with tags."""
        session_id = populated_manager.save_session(
            session_name="tagged-session",
            task_description="Tagged test",
            tags=["feature", "auth", "backend"],
        )

        # Load via SessionManager to verify tags
        sessions_dir = populated_manager.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)
        metadata = session_manager.get_session_info(session_id)

        assert metadata is not None
        assert len(metadata.tags) == 3
        assert "feature" in metadata.tags

    def test_save_session_without_name(self, populated_manager):
        """Test saving session without explicit name."""
        session_id = populated_manager.save_session(
            task_description="No name test",
        )

        # Should still create session
        assert session_id is not None

    def test_save_session_captures_duration(self, populated_manager):
        """Test that save_session captures session duration."""
        import time

        # Wait a moment to ensure duration > 0
        time.sleep(0.1)

        session_id = populated_manager.save_session(
            session_name="duration-test",
            task_description="Duration test",
        )

        # Load and check metadata
        sessions_dir = populated_manager.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)
        metadata = session_manager.get_session_info(session_id)

        assert metadata.duration_minutes > 0

    # ==================== Load Session Tests ====================

    def test_load_session_by_full_id(self, populated_manager):
        """Test loading session by full ID."""
        # Save session
        session_id = populated_manager.save_session(
            session_name="full-id-test",
            task_description="Full ID test",
        )

        # Create new manager and load
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )

        new_manager.load_session(session_id)

        # Verify data restored
        assert len(new_manager.working_memory.messages) == 4
        assert new_manager.working_memory.task_context is not None
        assert new_manager.file_memory_content == "# Project Memory\nUse 2-space indentation"

    def test_load_session_by_short_id(self, populated_manager):
        """Test loading session by short ID (8 chars)."""
        # Save session
        session_id = populated_manager.save_session(
            session_name="short-id-test",
            task_description="Short ID test",
        )

        short_id = session_id[:8]

        # Create new manager and load with short ID
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )

        new_manager.load_session(short_id)

        # Verify data restored
        assert len(new_manager.working_memory.messages) == 4

    def test_load_session_by_name(self, populated_manager):
        """Test loading session by name."""
        # Save session with name
        session_id = populated_manager.save_session(
            session_name="my-feature",
            task_description="Name test",
        )

        # Create new manager and load by name
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )

        new_manager.load_session("my-feature")

        # Verify data restored
        assert len(new_manager.working_memory.messages) == 4
        assert new_manager.working_memory.task_context.task_id == "auth-task"

    def test_load_session_not_found(self, memory_manager):
        """Test loading non-existent session raises error."""
        with pytest.raises(ValueError, match="Session not found"):
            memory_manager.load_session("nonexistent-id")

    def test_load_session_preserves_working_memory(self, populated_manager):
        """Test that loading session preserves working memory."""
        # Save
        session_id = populated_manager.save_session(
            session_name="working-mem-test",
            task_description="Working memory test",
        )

        # Load into new manager
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify working memory
        assert len(new_manager.working_memory.messages) == 4

        # Check first user message
        user_msg = new_manager.working_memory.messages[0]
        assert user_msg.role == MessageRole.USER
        assert "authentication" in user_msg.content.lower()

    def test_load_session_preserves_episodic_memory(self, populated_manager):
        """Test that loading session preserves episodic memory."""
        # Save
        session_id = populated_manager.save_session(
            session_name="episodic-test",
            task_description="Episodic memory test",
        )

        # Load into new manager
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify episodic memory has conversation turns
        assert len(new_manager.episodic_memory.conversation_turns) == 2

        # Check first turn
        first_turn = new_manager.episodic_memory.conversation_turns[0]
        assert "authentication" in first_turn.user_message.content.lower()

    def test_load_session_preserves_task_context(self, populated_manager):
        """Test that loading session preserves task context."""
        # Save
        session_id = populated_manager.save_session(
            session_name="task-test",
            task_description="Task context test",
        )

        # Load into new manager
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify task context
        task = new_manager.working_memory.task_context
        assert task is not None
        assert task.task_id == "auth-task"
        assert task.description == "Implement JWT authentication"
        assert "JWT" in task.key_concepts

    def test_load_session_preserves_file_memories(self, populated_manager):
        """Test that loading session preserves file memories."""
        # Save
        session_id = populated_manager.save_session(
            session_name="file-mem-test",
            task_description="File memory test",
        )

        # Load into new manager
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify file memories
        assert new_manager.file_memory_content == "# Project Memory\nUse 2-space indentation"

    def test_round_trip_preserves_all_data(self, populated_manager):
        """Test that save/load round-trip preserves all data."""
        # Save
        session_id = populated_manager.save_session(
            session_name="round-trip-test",
            task_description="Round trip test",
            tags=["test", "complete"],
        )

        # Load into new manager
        new_manager = MemoryManager(
            persist_directory=str(populated_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify all components
        # Working memory
        assert len(new_manager.working_memory.messages) == len(
            populated_manager.working_memory.messages
        )

        # Episodic memory
        assert len(new_manager.episodic_memory.conversation_turns) == len(
            populated_manager.episodic_memory.conversation_turns
        )

        # Task context
        assert (
            new_manager.working_memory.task_context.task_id
            == populated_manager.working_memory.task_context.task_id
        )

        # File memories
        assert new_manager.file_memory_content == populated_manager.file_memory_content

    # ==================== Multiple Sessions Tests ====================

    def test_save_multiple_sessions(self, memory_manager):
        """Test saving multiple different sessions."""
        # Create first session
        memory_manager.add_user_message("First session")
        memory_manager.add_assistant_message("Response 1")

        session1_id = memory_manager.save_session(
            session_name="session-1",
            task_description="First session",
        )

        # Clear and create second session
        memory_manager.clear_working_memory()
        memory_manager.add_user_message("Second session")
        memory_manager.add_assistant_message("Response 2")

        session2_id = memory_manager.save_session(
            session_name="session-2",
            task_description="Second session",
        )

        # Verify both sessions exist
        sessions_dir = memory_manager.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        sessions = session_manager.list_sessions()
        assert len(sessions) == 2

        # Verify can load each independently
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )

        new_manager.load_session(session1_id)
        assert "First session" in new_manager.working_memory.messages[0].content

        new_manager.load_session(session2_id)
        assert "Second session" in new_manager.working_memory.messages[0].content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
