"""Tests for WorkingMemory serialization."""

import pytest
from datetime import datetime
import sys
from pathlib import Path

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory.working_memory import WorkingMemory
from src.memory.models import Message, MessageRole, CodeContext, TaskContext


class TestWorkingMemorySerialization:
    """Test WorkingMemory serialization methods."""

    @pytest.fixture
    def working_memory(self):
        """Create WorkingMemory instance."""
        return WorkingMemory(max_tokens=2000)

    @pytest.fixture
    def populated_memory(self, working_memory):
        """Create WorkingMemory with data."""
        # Add messages
        working_memory.add_message(
            role=MessageRole.USER,
            content="Hello, how are you?",
            metadata={"test": "data"}
        )
        working_memory.add_message(
            role=MessageRole.ASSISTANT,
            content="I'm doing well, thank you!",
        )

        # Add task context
        task = TaskContext(
            task_id="task-123",
            description="Implement authentication",
            task_type="implement",
            status="in_progress",
            related_files=["auth.py", "user.py"],
            key_concepts=["JWT", "OAuth"],
            constraints=["Must be secure", "Must be fast"],
        )
        working_memory.set_task_context(task)

        # Add code context
        code_ctx = CodeContext(
            file_path="/path/to/file.py",
            content="def hello(): pass",
            language="python",
            start_line=1,
            end_line=10,
            summary="Simple hello function",
            functions=["hello"],
            classes=[],
            imports=["os", "sys"],
        )
        working_memory.add_code_context(code_ctx)

        return working_memory

    # ==================== to_dict Tests ====================

    def test_to_dict_empty(self, working_memory):
        """Test serializing empty working memory."""
        data = working_memory.to_dict()

        assert isinstance(data, dict)
        assert "messages" in data
        assert "task_context" in data
        assert "code_contexts" in data
        assert "metadata" in data
        assert "max_tokens" in data

        assert len(data["messages"]) == 0
        assert data["task_context"] is None
        assert len(data["code_contexts"]) == 0

    def test_to_dict_with_messages(self, working_memory):
        """Test serializing working memory with messages."""
        working_memory.add_message(MessageRole.USER, "Hello")
        working_memory.add_message(MessageRole.ASSISTANT, "Hi there")

        data = working_memory.to_dict()

        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "Hi there"

    def test_to_dict_with_task_context(self, working_memory):
        """Test serializing working memory with task context."""
        task = TaskContext(
            task_id="test-task",
            description="Test description",
            task_type="test",
        )
        working_memory.set_task_context(task)

        data = working_memory.to_dict()

        assert data["task_context"] is not None
        assert data["task_context"]["task_id"] == "test-task"
        assert data["task_context"]["description"] == "Test description"

    def test_to_dict_with_code_contexts(self, working_memory):
        """Test serializing working memory with code contexts."""
        ctx1 = CodeContext(file_path="/path/1.py", language="python")
        ctx2 = CodeContext(file_path="/path/2.py", language="python")

        working_memory.add_code_context(ctx1)
        working_memory.add_code_context(ctx2)

        data = working_memory.to_dict()

        assert len(data["code_contexts"]) == 2
        assert data["code_contexts"][0]["file_path"] == "/path/1.py"
        assert data["code_contexts"][1]["file_path"] == "/path/2.py"

    def test_to_dict_complete(self, populated_memory):
        """Test serializing fully populated working memory."""
        data = populated_memory.to_dict()

        assert len(data["messages"]) == 2
        assert data["task_context"] is not None
        assert len(data["code_contexts"]) == 1
        assert data["max_tokens"] == 2000

    # ==================== from_dict Tests ====================

    def test_from_dict_empty(self, working_memory):
        """Test restoring empty working memory."""
        data = {
            "messages": [],
            "task_context": None,
            "code_contexts": [],
            "metadata": {},
            "max_tokens": 2000,
        }

        working_memory.from_dict(data)

        assert len(working_memory.messages) == 0
        assert working_memory.task_context is None
        assert len(working_memory.code_contexts) == 0

    def test_from_dict_with_messages(self, working_memory):
        """Test restoring working memory with messages."""
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": "Hello",
                    "timestamp": datetime.now().isoformat(),
                    "metadata": {},
                    "token_count": 5,
                },
                {
                    "role": "assistant",
                    "content": "Hi there",
                    "timestamp": datetime.now().isoformat(),
                    "metadata": {},
                    "token_count": 6,
                },
            ],
            "task_context": None,
            "code_contexts": [],
            "metadata": {},
            "max_tokens": 2000,
        }

        working_memory.from_dict(data)

        assert len(working_memory.messages) == 2
        assert working_memory.messages[0].role == MessageRole.USER
        assert working_memory.messages[0].content == "Hello"
        assert working_memory.messages[1].role == MessageRole.ASSISTANT

    def test_from_dict_with_task_context(self, working_memory):
        """Test restoring working memory with task context."""
        data = {
            "messages": [],
            "task_context": {
                "task_id": "test-task",
                "description": "Test description",
                "task_type": "test",
                "status": "in_progress",
                "related_files": [],
                "key_concepts": [],
                "constraints": [],
                "metadata": {},
            },
            "code_contexts": [],
            "metadata": {},
            "max_tokens": 2000,
        }

        working_memory.from_dict(data)

        assert working_memory.task_context is not None
        assert working_memory.task_context.task_id == "test-task"
        assert working_memory.task_context.description == "Test description"

    def test_from_dict_with_code_contexts(self, working_memory):
        """Test restoring working memory with code contexts."""
        data = {
            "messages": [],
            "task_context": None,
            "code_contexts": [
                {
                    "file_path": "/path/1.py",
                    "content": None,
                    "language": "python",
                    "start_line": None,
                    "end_line": None,
                    "summary": None,
                    "functions": [],
                    "classes": [],
                    "imports": [],
                    "metadata": {},
                }
            ],
            "metadata": {},
            "max_tokens": 2000,
        }

        working_memory.from_dict(data)

        assert len(working_memory.code_contexts) == 1
        assert working_memory.code_contexts[0].file_path == "/path/1.py"

    def test_from_dict_complete(self, working_memory, populated_memory):
        """Test full round-trip serialization."""
        # Serialize populated memory
        data = populated_memory.to_dict()

        # Restore to fresh memory
        working_memory.from_dict(data)

        # Verify all data restored
        assert len(working_memory.messages) == 2
        assert working_memory.messages[0].content == "Hello, how are you?"

        assert working_memory.task_context is not None
        assert working_memory.task_context.task_id == "task-123"

        assert len(working_memory.code_contexts) == 1
        assert working_memory.code_contexts[0].file_path == "/path/to/file.py"

    def test_round_trip_preserves_data(self, populated_memory):
        """Test that serialization round-trip preserves all data."""
        # Serialize
        data = populated_memory.to_dict()

        # Create new instance and restore
        new_memory = WorkingMemory(max_tokens=2000)
        new_memory.from_dict(data)

        # Verify exact match
        assert len(new_memory.messages) == len(populated_memory.messages)
        assert len(new_memory.code_contexts) == len(populated_memory.code_contexts)

        # Check message content
        for i, msg in enumerate(new_memory.messages):
            original_msg = populated_memory.messages[i]
            assert msg.content == original_msg.content
            assert msg.role == original_msg.role

        # Check task context
        assert new_memory.task_context.task_id == populated_memory.task_context.task_id
        assert new_memory.task_context.description == populated_memory.task_context.description

    def test_from_dict_handles_missing_fields(self, working_memory):
        """Test that from_dict handles missing optional fields gracefully."""
        data = {
            "messages": [],
            "code_contexts": [],
            # Missing: task_context, metadata, max_tokens
        }

        working_memory.from_dict(data)

        # Should not crash, should use defaults
        assert len(working_memory.messages) == 0
        assert working_memory.task_context is None
        assert len(working_memory.code_contexts) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
