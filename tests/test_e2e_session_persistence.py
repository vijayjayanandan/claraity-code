"""End-to-End tests for session persistence through Agent."""

import pytest
import tempfile
import shutil
from pathlib import Path
import sys

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory.memory_manager import MemoryManager
from src.memory.models import TaskContext
from src.core.session_manager import SessionManager


class TestE2ESessionPersistence:
    """End-to-end tests for complete session save/load cycle."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        tmpdir = Path(tempfile.mkdtemp())
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def memory_manager(self, temp_dir):
        """Create MemoryManager with temporary directory."""
        return MemoryManager(
            total_context_tokens=4096,
            persist_directory=str(temp_dir),
            load_file_memories=False,
        )

    # ==================== Full Conversation Cycle ====================

    def test_full_conversation_save_load_cycle(self, memory_manager):
        """Test complete conversation save and load cycle."""
        # Simulate a realistic conversation
        memory_manager.add_user_message("Hello, can you help me implement a feature?")
        memory_manager.add_assistant_message("Of course! I'd be happy to help. What feature are you working on?")

        memory_manager.add_user_message("I need to add JWT authentication to my API")
        memory_manager.add_assistant_message(
            "Great! I'll help you implement JWT authentication. Let me break this down into steps.",
            tool_calls=[{"tool": "analyze_code", "args": {"path": "api/"}}]
        )

        memory_manager.add_user_message("Can you read the current auth.py file?")
        memory_manager.add_assistant_message(
            "I'll read the auth.py file for you.",
            tool_calls=[{"tool": "read_file", "args": {"path": "auth.py"}}]
        )

        # Set task context
        task = TaskContext(
            task_id="jwt-auth-implementation",
            description="Implement JWT authentication for REST API",
            task_type="implement",
            status="in_progress",
            related_files=["auth.py", "user.py", "token.py"],
            key_concepts=["JWT", "authentication", "tokens", "security"],
            constraints=["Must use bcrypt for passwords", "Token expiry: 24h"],
        )
        memory_manager.set_task_context(task)

        # Add file memory
        memory_manager.file_memory_content = (
            "# Project Memory\n"
            "- Use 2-space indentation\n"
            "- Follow PEP 8 style guide\n"
            "- Add docstrings to all functions\n"
        )

        # Save session
        session_id = memory_manager.save_session(
            session_name="jwt-auth-feature",
            task_description="Implementing JWT authentication for REST API",
            tags=["feature", "auth", "backend", "security"]
        )

        # Create new manager and load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )

        new_manager.load_session(session_id)

        # Verify everything was restored
        # 1. Working memory messages
        assert len(new_manager.working_memory.messages) == 6
        assert "JWT authentication" in new_manager.working_memory.messages[2].content
        assert new_manager.working_memory.messages[0].content == "Hello, can you help me implement a feature?"

        # 2. Task context
        restored_task = new_manager.working_memory.task_context
        assert restored_task is not None
        assert restored_task.task_id == "jwt-auth-implementation"
        assert restored_task.description == "Implement JWT authentication for REST API"
        assert "JWT" in restored_task.key_concepts
        assert "auth.py" in restored_task.related_files
        assert "Must use bcrypt" in restored_task.constraints[0]

        # 4. File memories
        assert "Project Memory" in new_manager.file_memory_content
        assert "2-space indentation" in new_manager.file_memory_content

    def test_multiple_session_isolation(self, memory_manager):
        """Test that multiple sessions don't interfere with each other."""
        # Session 1: Auth feature
        memory_manager.add_user_message("Implement authentication")
        memory_manager.add_assistant_message("I'll help with authentication")

        session1_id = memory_manager.save_session(
            session_name="auth-feature",
            task_description="Authentication system",
            tags=["auth"]
        )

        # Clear and create Session 2: Database feature
        memory_manager.clear_working_memory()

        memory_manager.add_user_message("Optimize database queries")
        memory_manager.add_assistant_message("Let's optimize the database")

        session2_id = memory_manager.save_session(
            session_name="db-optimization",
            task_description="Database query optimization",
            tags=["database", "performance"]
        )

        # Load session 1
        new_manager1 = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager1.load_session(session1_id)

        # Verify session 1 content
        assert len(new_manager1.working_memory.messages) == 2
        assert "authentication" in new_manager1.working_memory.messages[0].content.lower()
        assert "database" not in new_manager1.working_memory.messages[0].content.lower()

        # Load session 2
        new_manager2 = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager2.load_session(session2_id)

        # Verify session 2 content
        assert len(new_manager2.working_memory.messages) == 2
        assert "database" in new_manager2.working_memory.messages[0].content.lower()
        assert "authentication" not in new_manager2.working_memory.messages[0].content.lower()

    def test_session_continuation(self, memory_manager):
        """Test continuing work after loading a session."""
        # Initial conversation
        memory_manager.add_user_message("Start implementing login endpoint")
        memory_manager.add_assistant_message("I'll create the login endpoint")

        session_id = memory_manager.save_session(
            session_name="login-endpoint",
            task_description="Login endpoint implementation",
        )

        # Load in new manager
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Continue conversation
        new_manager.add_user_message("Now add password validation")
        new_manager.add_assistant_message("Adding password validation logic")

        # Save again (update session)
        updated_session_id = new_manager.save_session(
            session_name="login-endpoint-v2",
            task_description="Login endpoint with validation",
        )

        # Load updated session
        final_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        final_manager.load_session(updated_session_id)

        # Verify full history
        assert len(final_manager.working_memory.messages) == 4
        assert "Start implementing" in final_manager.working_memory.messages[0].content
        assert "password validation" in final_manager.working_memory.messages[2].content

    def test_session_with_complex_tool_calls(self, memory_manager):
        """Test sessions with complex tool call history."""
        # Conversation with multiple tool calls
        memory_manager.add_user_message("Refactor the authentication module")
        memory_manager.add_assistant_message(
            "I'll analyze the current structure first.",
            tool_calls=[
                {"tool": "read_file", "args": {"path": "auth.py"}},
                {"tool": "analyze_code", "args": {"path": "auth.py"}},
            ]
        )

        memory_manager.add_user_message("Extract the JWT logic into a separate file")
        memory_manager.add_assistant_message(
            "I'll create a new jwt_utils.py file.",
            tool_calls=[
                {"tool": "write_file", "args": {"path": "jwt_utils.py", "content": "..."}},
                {"tool": "edit_file", "args": {"path": "auth.py", "changes": "..."}},
            ]
        )

        session_id = memory_manager.save_session(
            session_name="refactor-auth",
            task_description="Refactoring authentication module",
        )

        # Load and verify tool calls
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify working memory was restored
        assert len(new_manager.working_memory.messages) > 0

    # ==================== Session Management Integration ====================

    def test_list_sessions_after_multiple_saves(self, memory_manager):
        """Test listing sessions after creating multiple sessions."""
        # Create 3 sessions
        for i in range(3):
            memory_manager.clear_working_memory()

            memory_manager.add_user_message(f"Task {i}")
            memory_manager.add_assistant_message(f"Response {i}")

            memory_manager.save_session(
                session_name=f"session-{i}",
                task_description=f"Task number {i}",
                tags=[f"tag{i}", "common"]
            )

        # List sessions
        sessions_dir = memory_manager.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        sessions = session_manager.list_sessions()

        assert len(sessions) == 3
        names = [s.name for s in sessions]
        assert "session-0" in names
        assert "session-1" in names
        assert "session-2" in names

    def test_find_and_load_by_name(self, memory_manager):
        """Test finding and loading session by name."""
        # Create session with specific name
        memory_manager.add_user_message("Unique task")
        memory_manager.add_assistant_message("Unique response")

        memory_manager.save_session(
            session_name="unique-feature-name",
            task_description="A unique feature",
        )

        # Load by name (not ID)
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )

        # Load using name
        new_manager.load_session("unique-feature-name")

        assert len(new_manager.working_memory.messages) == 2
        assert "Unique task" in new_manager.working_memory.messages[0].content

    def test_session_metadata_accuracy(self, memory_manager):
        """Test that session metadata is accurate."""
        import time

        # Create conversation
        memory_manager.add_user_message("Message 1")
        memory_manager.add_assistant_message("Response 1")
        memory_manager.add_user_message("Message 2")
        memory_manager.add_assistant_message("Response 2")

        # Wait a moment for duration
        time.sleep(0.1)

        session_id = memory_manager.save_session(
            session_name="metadata-test",
            task_description="Testing metadata accuracy",
            tags=["test", "metadata", "e2e"]
        )

        # Get session info
        sessions_dir = memory_manager.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)
        info = session_manager.get_session_info(session_id)

        # Verify metadata
        assert info.name == "metadata-test"
        assert info.task_description == "Testing metadata accuracy"
        assert info.message_count == 4
        assert len(info.tags) == 3
        assert "test" in info.tags
        assert info.duration_minutes > 0

    # ==================== Edge Cases ====================

    def test_empty_session_save_load(self, memory_manager):
        """Test saving and loading an empty session."""
        # Save with no messages
        session_id = memory_manager.save_session(
            session_name="empty-session",
            task_description="Empty session test",
        )

        # Load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        assert len(new_manager.working_memory.messages) == 0

    def test_session_with_only_user_messages(self, memory_manager):
        """Test session with only user messages (no assistant responses)."""
        memory_manager.add_user_message("Question 1")
        memory_manager.add_user_message("Question 2")

        session_id = memory_manager.save_session(
            session_name="questions-only",
            task_description="Questions without responses",
        )

        # Load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        assert len(new_manager.working_memory.messages) == 2

    def test_very_long_conversation(self, memory_manager):
        """Test session with many messages."""
        # Create 50 message pairs
        for i in range(50):
            memory_manager.add_user_message(f"User message {i}")
            memory_manager.add_assistant_message(f"Assistant response {i}")

        session_id = memory_manager.save_session(
            session_name="long-conversation",
            task_description="Very long conversation test",
        )

        # Load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        assert len(new_manager.working_memory.messages) == 100

    def test_session_with_special_characters(self, memory_manager):
        """Test session with special characters in content."""
        special_content = "Test with special chars: 你好 🎉 <script> $€£ \n\t"

        memory_manager.add_user_message(special_content)
        memory_manager.add_assistant_message(f"Received: {special_content}")

        session_id = memory_manager.save_session(
            session_name="special-chars-test",
            task_description="Testing special characters",
        )

        # Load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify special characters preserved
        assert special_content in new_manager.working_memory.messages[0].content
        assert "你好" in new_manager.working_memory.messages[0].content
        assert "🎉" in new_manager.working_memory.messages[0].content

    # ==================== Error Handling ====================

    def test_load_nonexistent_session_raises_error(self, memory_manager):
        """Test that loading non-existent session raises error."""
        with pytest.raises(ValueError, match="Session not found"):
            memory_manager.load_session("nonexistent-session-id")

    def test_load_corrupted_session_directory(self, memory_manager, temp_dir):
        """Test handling of corrupted session directory."""
        # Create a corrupted session directory (missing metadata)
        corrupted_dir = temp_dir / "sessions" / "corrupted-session-id"
        corrupted_dir.mkdir(parents=True, exist_ok=True)

        # Try to load (should fail gracefully)
        with pytest.raises(ValueError):
            memory_manager.load_session("corrupted-session-id")


class TestSessionPersistenceIntegration:
    """Integration tests for session persistence with other systems."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        tmpdir = Path(tempfile.mkdtemp())
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def memory_manager(self, temp_dir):
        """Create MemoryManager with temporary directory."""
        return MemoryManager(
            persist_directory=str(temp_dir),
            load_file_memories=False,
        )

    def test_session_with_file_memory_integration(self, memory_manager):
        """Test session persistence with file-based memories."""
        # Set file memory content
        memory_manager.file_memory_content = (
            "# Enterprise Memory\n"
            "- Security policy: All passwords must be hashed\n"
            "# User Memory\n"
            "- Preferred language: Python\n"
            "# Project Memory\n"
            "- Use async/await for I/O operations\n"
        )

        memory_manager.add_user_message("Implement user login")
        memory_manager.add_assistant_message("I'll implement secure login")

        session_id = memory_manager.save_session(
            session_name="login-with-memory",
            task_description="Login implementation with memory",
        )

        # Load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Verify file memories restored
        assert "Enterprise Memory" in new_manager.file_memory_content
        assert "passwords must be hashed" in new_manager.file_memory_content
        assert "async/await" in new_manager.file_memory_content

    def test_context_building_after_load(self, memory_manager):
        """Test that context can be built correctly after loading."""
        # Create conversation
        memory_manager.add_user_message("Create API endpoint")
        memory_manager.add_assistant_message("I'll create the endpoint")

        session_id = memory_manager.save_session(
            session_name="api-endpoint",
            task_description="API endpoint creation",
        )

        # Load
        new_manager = MemoryManager(
            persist_directory=str(memory_manager.persist_directory),
            load_file_memories=False,
        )
        new_manager.load_session(session_id)

        # Build context (should work without errors)
        context = new_manager.get_context_for_llm(
            system_prompt="You are a helpful coding assistant.",
            include_episodic=True,
        )

        # Verify context structure
        assert len(context) > 0
        assert context[0]["role"] == "system"
        assert any("API endpoint" in str(msg.get("content", "")) for msg in context)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
