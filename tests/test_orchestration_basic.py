"""
Unit tests for agent-to-agent orchestration Phase 1.

Tests the basic communication layer between Claude Code (testing agent)
and AI Coding Agent (subject under test).

Test Coverage:
- AgentMessage: Creation, serialization, deserialization
- AgentResponse: Creation, serialization, deserialization
- ConversationLog: Full lifecycle (to_dict, from_dict, to_json, from_json)
- ConversationSession: Message passing, file extraction, logging
- AgentOrchestrator: Session management, workspace creation, message routing
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
import tempfile
import shutil

from src.orchestration.models import AgentMessage, AgentResponse, ConversationLog
from src.orchestration.conversation import ConversationSession
from src.orchestration.agent_orchestrator import AgentOrchestrator
from src.core.agent import CodingAgent


# ====================
# Fixtures
# ====================

@pytest.fixture
def temp_dir():
    """Create temporary directory for testing."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    # Cleanup
    if temp_path.exists():
        shutil.rmtree(temp_path)


@pytest.fixture
def mock_agent():
    """Create mock CodingAgent for testing."""
    agent = Mock(spec=CodingAgent)
    agent.model_name = "test-model"
    mock_response = Mock(content="Test agent response")
    agent.execute_task = Mock(return_value=mock_response)
    agent.tool_execution_history = []
    return agent


@pytest.fixture
def sample_timestamp():
    """Fixed timestamp for consistent testing."""
    return datetime(2025, 11, 5, 12, 0, 0)


# ====================
# AgentMessage Tests
# ====================

class TestAgentMessage:
    """Test suite for AgentMessage data model."""

    def test_creation(self, sample_timestamp):
        """Test AgentMessage can be created with required fields."""
        msg = AgentMessage(
            role="user",
            content="Test message",
            timestamp=sample_timestamp
        )

        assert msg.role == "user"
        assert msg.content == "Test message"
        assert msg.timestamp == sample_timestamp
        assert msg.metadata == {}

    def test_creation_with_metadata(self, sample_timestamp):
        """Test AgentMessage creation with metadata."""
        metadata = {"key": "value", "count": 42}
        msg = AgentMessage(
            role="assistant",
            content="Response",
            timestamp=sample_timestamp,
            metadata=metadata
        )

        assert msg.metadata == metadata

    def test_to_dict(self, sample_timestamp):
        """Test AgentMessage serialization to dictionary."""
        msg = AgentMessage(
            role="user",
            content="Test",
            timestamp=sample_timestamp,
            metadata={"test": True}
        )

        result = msg.to_dict()

        assert result["role"] == "user"
        assert result["content"] == "Test"
        assert result["timestamp"] == "2025-11-05T12:00:00"
        assert result["metadata"] == {"test": True}

    def test_from_dict(self):
        """Test AgentMessage deserialization from dictionary."""
        data = {
            "role": "assistant",
            "content": "Response",
            "timestamp": "2025-11-05T12:00:00",
            "metadata": {"success": True}
        }

        msg = AgentMessage.from_dict(data)

        assert msg.role == "assistant"
        assert msg.content == "Response"
        assert msg.timestamp == datetime(2025, 11, 5, 12, 0, 0)
        assert msg.metadata == {"success": True}

    def test_from_dict_without_metadata(self):
        """Test AgentMessage deserialization with missing metadata."""
        data = {
            "role": "user",
            "content": "Test",
            "timestamp": "2025-11-05T12:00:00"
        }

        msg = AgentMessage.from_dict(data)

        assert msg.metadata == {}

    def test_roundtrip_serialization(self, sample_timestamp):
        """Test to_dict/from_dict roundtrip preserves data."""
        original = AgentMessage(
            role="user",
            content="Original message",
            timestamp=sample_timestamp,
            metadata={"key": "value"}
        )

        # Serialize and deserialize
        data = original.to_dict()
        restored = AgentMessage.from_dict(data)

        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.timestamp == original.timestamp
        assert restored.metadata == original.metadata


# ====================
# AgentResponse Tests
# ====================

class TestAgentResponse:
    """Test suite for AgentResponse data model."""

    def test_creation_defaults(self):
        """Test AgentResponse creation with minimal fields."""
        response = AgentResponse(content="Test response")

        assert response.content == "Test response"
        assert response.files_generated == []
        assert response.tool_calls == []
        assert response.success is True
        assert response.error is None
        assert response.metadata == {}

    def test_creation_full(self):
        """Test AgentResponse creation with all fields."""
        response = AgentResponse(
            content="Full response",
            files_generated=["file1.py", "file2.py"],
            tool_calls=[{"tool": "write_file", "args": {}}],
            success=False,
            error="Test error",
            metadata={"duration": 1.5}
        )

        assert response.content == "Full response"
        assert response.files_generated == ["file1.py", "file2.py"]
        assert len(response.tool_calls) == 1
        assert response.success is False
        assert response.error == "Test error"
        assert response.metadata == {"duration": 1.5}

    def test_to_dict(self):
        """Test AgentResponse serialization to dictionary."""
        response = AgentResponse(
            content="Response",
            files_generated=["test.py"],
            tool_calls=[{"tool": "test"}],
            success=True,
            error=None,
            metadata={"key": "value"}
        )

        result = response.to_dict()

        assert result["content"] == "Response"
        assert result["files_generated"] == ["test.py"]
        assert result["tool_calls"] == [{"tool": "test"}]
        assert result["success"] is True
        assert result["error"] is None
        assert result["metadata"] == {"key": "value"}

    def test_from_dict(self):
        """Test AgentResponse deserialization from dictionary."""
        data = {
            "content": "Test",
            "files_generated": ["a.py", "b.py"],
            "tool_calls": [{"tool": "write"}],
            "success": False,
            "error": "Error message",
            "metadata": {"test": True}
        }

        response = AgentResponse.from_dict(data)

        assert response.content == "Test"
        assert response.files_generated == ["a.py", "b.py"]
        assert response.tool_calls == [{"tool": "write"}]
        assert response.success is False
        assert response.error == "Error message"
        assert response.metadata == {"test": True}

    def test_from_dict_with_defaults(self):
        """Test AgentResponse deserialization with missing optional fields."""
        data = {"content": "Minimal"}

        response = AgentResponse.from_dict(data)

        assert response.content == "Minimal"
        assert response.files_generated == []
        assert response.tool_calls == []
        assert response.success is True
        assert response.error is None
        assert response.metadata == {}

    def test_roundtrip_serialization(self):
        """Test to_dict/from_dict roundtrip preserves data."""
        original = AgentResponse(
            content="Original",
            files_generated=["file.py"],
            tool_calls=[{"tool": "test", "success": True}],
            success=True,
            error=None,
            metadata={"test": "value"}
        )

        data = original.to_dict()
        restored = AgentResponse.from_dict(data)

        assert restored.content == original.content
        assert restored.files_generated == original.files_generated
        assert restored.tool_calls == original.tool_calls
        assert restored.success == original.success
        assert restored.error == original.error
        assert restored.metadata == original.metadata


# ====================
# ConversationLog Tests
# ====================

class TestConversationLog:
    """Test suite for ConversationLog data model."""

    def test_creation(self, sample_timestamp):
        """Test ConversationLog creation with required fields."""
        messages = [
            AgentMessage("user", "Hello", sample_timestamp),
            AgentMessage("assistant", "Hi", sample_timestamp)
        ]

        log = ConversationLog(
            conversation_id="test-123",
            messages=messages,
            started_at=sample_timestamp
        )

        assert log.conversation_id == "test-123"
        assert len(log.messages) == 2
        assert log.started_at == sample_timestamp
        assert log.ended_at is None
        assert log.total_turns == 0
        assert log.metadata == {}

    def test_creation_with_all_fields(self, sample_timestamp):
        """Test ConversationLog creation with all fields."""
        ended = datetime(2025, 11, 5, 13, 0, 0)
        log = ConversationLog(
            conversation_id="test-456",
            messages=[],
            started_at=sample_timestamp,
            ended_at=ended,
            total_turns=5,
            metadata={"test": "data"}
        )

        assert log.ended_at == ended
        assert log.total_turns == 5
        assert log.metadata == {"test": "data"}

    def test_to_dict(self, sample_timestamp):
        """Test ConversationLog serialization to dictionary."""
        messages = [AgentMessage("user", "Test", sample_timestamp)]
        log = ConversationLog(
            conversation_id="conv-1",
            messages=messages,
            started_at=sample_timestamp,
            total_turns=1,
            metadata={"key": "value"}
        )

        result = log.to_dict()

        assert result["conversation_id"] == "conv-1"
        assert len(result["messages"]) == 1
        assert result["started_at"] == "2025-11-05T12:00:00"
        assert result["ended_at"] is None
        assert result["total_turns"] == 1
        assert result["metadata"] == {"key": "value"}

    def test_to_dict_with_ended_at(self, sample_timestamp):
        """Test ConversationLog serialization with ended_at."""
        ended = datetime(2025, 11, 5, 13, 0, 0)
        log = ConversationLog(
            conversation_id="conv-2",
            messages=[],
            started_at=sample_timestamp,
            ended_at=ended
        )

        result = log.to_dict()

        assert result["ended_at"] == "2025-11-05T13:00:00"

    def test_from_dict(self, sample_timestamp):
        """Test ConversationLog deserialization from dictionary."""
        data = {
            "conversation_id": "conv-3",
            "messages": [
                {
                    "role": "user",
                    "content": "Test",
                    "timestamp": "2025-11-05T12:00:00",
                    "metadata": {}
                }
            ],
            "started_at": "2025-11-05T12:00:00",
            "ended_at": "2025-11-05T13:00:00",
            "total_turns": 1,
            "metadata": {"test": True}
        }

        log = ConversationLog.from_dict(data)

        assert log.conversation_id == "conv-3"
        assert len(log.messages) == 1
        assert log.messages[0].role == "user"
        assert log.started_at == sample_timestamp
        assert log.ended_at == datetime(2025, 11, 5, 13, 0, 0)
        assert log.total_turns == 1
        assert log.metadata == {"test": True}

    def test_from_dict_without_ended_at(self):
        """Test ConversationLog deserialization with null ended_at."""
        data = {
            "conversation_id": "conv-4",
            "messages": [],
            "started_at": "2025-11-05T12:00:00",
            "ended_at": None
        }

        log = ConversationLog.from_dict(data)

        assert log.ended_at is None

    def test_to_json(self, sample_timestamp):
        """Test ConversationLog JSON serialization."""
        log = ConversationLog(
            conversation_id="json-test",
            messages=[],
            started_at=sample_timestamp,
            total_turns=0
        )

        json_str = log.to_json(pretty=True)

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert parsed["conversation_id"] == "json-test"
        assert "  " in json_str  # Pretty printed with indentation

    def test_to_json_not_pretty(self, sample_timestamp):
        """Test ConversationLog JSON serialization without formatting."""
        log = ConversationLog(
            conversation_id="compact",
            messages=[],
            started_at=sample_timestamp
        )

        json_str = log.to_json(pretty=False)

        # Should be compact (no indentation)
        assert "\n" not in json_str or json_str.count("\n") == 0

    def test_from_json(self):
        """Test ConversationLog JSON deserialization."""
        json_str = '''
        {
            "conversation_id": "from-json",
            "messages": [],
            "started_at": "2025-11-05T12:00:00",
            "ended_at": null,
            "total_turns": 0,
            "metadata": {}
        }
        '''

        log = ConversationLog.from_json(json_str)

        assert log.conversation_id == "from-json"
        assert log.messages == []
        assert log.total_turns == 0

    def test_json_roundtrip(self, sample_timestamp):
        """Test to_json/from_json roundtrip preserves data."""
        original = ConversationLog(
            conversation_id="roundtrip",
            messages=[AgentMessage("user", "Test", sample_timestamp)],
            started_at=sample_timestamp,
            total_turns=1,
            metadata={"key": "value"}
        )

        json_str = original.to_json()
        restored = ConversationLog.from_json(json_str)

        assert restored.conversation_id == original.conversation_id
        assert len(restored.messages) == len(original.messages)
        assert restored.started_at == original.started_at
        assert restored.total_turns == original.total_turns
        assert restored.metadata == original.metadata


# ====================
# ConversationSession Tests
# ====================

class TestConversationSession:
    """Test suite for ConversationSession."""

    def test_initialization(self, temp_dir, mock_agent):
        """Test ConversationSession initializes correctly."""
        session = ConversationSession(
            conversation_id="test-session",
            working_directory=temp_dir,
            agent=mock_agent,
            log_file=temp_dir / "log.json"
        )

        assert session.conversation_id == "test-session"
        assert session.working_directory == temp_dir
        assert session.agent == mock_agent
        assert session.log_file == temp_dir / "log.json"
        assert session.messages == []
        assert temp_dir.exists()

    def test_initialization_without_log_file(self, temp_dir, mock_agent):
        """Test ConversationSession can be created without log file."""
        session = ConversationSession(
            conversation_id="no-log",
            working_directory=temp_dir,
            agent=mock_agent
        )

        assert session.log_file is None

    def test_send_message_success(self, temp_dir, mock_agent):
        """Test sending message and getting successful response."""
        mock_agent.execute_task.return_value = Mock(content="Agent response text")
        mock_agent.tool_execution_history = [
            {
                "tool": "write_file",
                "arguments": {"file_path": "test.py"},
                "success": True
            }
        ]

        session = ConversationSession("test", temp_dir, mock_agent)
        response = session.send_message("Create a test file")

        # Verify response
        assert response.success is True
        assert response.content == "Agent response text"
        assert response.files_generated == ["test.py"]
        assert len(response.tool_calls) == 1
        assert response.error is None

        # Verify message history
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Create a test file"
        assert session.messages[1].role == "assistant"
        assert session.messages[1].content == "Agent response text"

        # Verify agent was called
        mock_agent.execute_task.assert_called_once_with("Create a test file", stream=True)

    def test_send_message_agent_failure(self, temp_dir, mock_agent):
        """Test sending message when agent execution fails."""
        mock_agent.execute_task.side_effect = ValueError("Agent error")

        session = ConversationSession("test", temp_dir, mock_agent)
        response = session.send_message("Trigger error")

        # Verify error response
        assert response.success is False
        assert "Agent execution failed" in response.content
        assert response.error == "ValueError: Agent error"
        assert response.files_generated == []

        # Verify message history still recorded
        assert len(session.messages) == 2

    def test_extract_files_from_history(self, temp_dir, mock_agent):
        """Test file extraction from tool execution history."""
        mock_agent.execute_task.return_value = Mock(content="Done")
        mock_agent.tool_execution_history = [
            {"tool": "write_file", "arguments": {"file_path": "a.py"}, "success": True},
            {"tool": "edit_file", "arguments": {"file_path": "b.py"}, "success": True},
            {"tool": "write_file", "arguments": {"file_path": "a.py"}, "success": True},  # Duplicate
            {"tool": "read_file", "arguments": {"file_path": "c.py"}, "success": True},  # Not write/edit
            {"tool": "write_file", "arguments": {"file_path": "d.py"}, "success": False}  # Failed
        ]

        session = ConversationSession("test", temp_dir, mock_agent)
        response = session.send_message("Test")

        # Should only include write_file and edit_file that succeeded, deduplicated
        assert response.files_generated == ["a.py", "b.py"]

    def test_extract_files_no_tool_history(self, temp_dir, mock_agent):
        """Test file extraction when agent has no tool history."""
        mock_agent.execute_task.return_value = Mock(content="Done")
        # Remove tool_execution_history attribute
        del mock_agent.tool_execution_history

        session = ConversationSession("test", temp_dir, mock_agent)
        response = session.send_message("Test")

        assert response.files_generated == []

    def test_extract_tool_calls(self, temp_dir, mock_agent):
        """Test tool call extraction from history."""
        tool_history = [
            {"tool": "write_file", "args": {}, "success": True},
            {"tool": "grep", "args": {}, "success": True}
        ]
        mock_agent.execute_task.return_value = Mock(content="Done")
        mock_agent.tool_execution_history = tool_history

        session = ConversationSession("test", temp_dir, mock_agent)
        response = session.send_message("Test")

        assert len(response.tool_calls) == 2
        assert response.tool_calls[0]["tool"] == "write_file"
        assert response.tool_calls[1]["tool"] == "grep"

    def test_get_history(self, temp_dir, mock_agent):
        """Test retrieving conversation history."""
        mock_agent.execute_task.return_value = Mock(content="Response")

        session = ConversationSession("test", temp_dir, mock_agent)
        session.send_message("Message 1")
        session.send_message("Message 2")

        history = session.get_history()

        assert len(history) == 4  # 2 user + 2 assistant
        assert history[0].role == "user"
        assert history[1].role == "assistant"
        assert history[2].role == "user"
        assert history[3].role == "assistant"
        # Verify it's a copy
        assert history is not session.messages

    def test_save_log_with_log_file(self, temp_dir, mock_agent):
        """Test saving conversation log to configured file."""
        log_file = temp_dir / "conversation.json"
        session = ConversationSession("test", temp_dir, mock_agent, log_file=log_file)

        saved_path = session.save_log()

        assert saved_path == log_file
        assert log_file.exists()

        # Verify content
        with open(log_file) as f:
            data = json.load(f)
        assert data["conversation_id"] == "test"

    def test_save_log_with_custom_path(self, temp_dir, mock_agent):
        """Test saving conversation log to custom path."""
        custom_path = temp_dir / "custom.json"
        session = ConversationSession("test", temp_dir, mock_agent)

        saved_path = session.save_log(custom_path=custom_path)

        assert saved_path == custom_path
        assert custom_path.exists()

    def test_save_log_default_path(self, temp_dir, mock_agent):
        """Test saving conversation log with default path."""
        session = ConversationSession("test-id", temp_dir, mock_agent)

        saved_path = session.save_log()

        # Should create file in working directory
        assert saved_path == temp_dir / "conversation_test-id.json"
        assert saved_path.exists()

    def test_auto_save_on_send_message(self, temp_dir, mock_agent):
        """Test that send_message auto-saves log if log_file is configured."""
        log_file = temp_dir / "auto_save.json"
        mock_agent.execute_task.return_value = Mock(content="Response")

        session = ConversationSession("test", temp_dir, mock_agent, log_file=log_file)
        session.send_message("Test message")

        # Log should be auto-saved
        assert log_file.exists()

    def test_get_log(self, temp_dir, mock_agent):
        """Test retrieving conversation log object."""
        mock_agent.execute_task.return_value = Mock(content="Response")

        session = ConversationSession("test", temp_dir, mock_agent)
        session.send_message("First message")
        session.send_message("Second message")

        log = session.get_log()

        assert log.conversation_id == "test"
        assert len(log.messages) == 4  # 2 user + 2 assistant
        assert log.total_turns == 2  # 2 user messages
        assert log.ended_at is None
        assert log.metadata["working_directory"] == str(temp_dir)
        assert log.metadata["agent_model"] == "test-model"


# ====================
# AgentOrchestrator Tests
# ====================

class TestAgentOrchestrator:
    """Test suite for AgentOrchestrator."""

    @patch.dict('os.environ', {
        'OPENAI_API_KEY': 'test-api-key',
        'LLM_MODEL': 'qwen3-coder-plus',
        'LLM_HOST': 'https://test-host.com/v1'
    })
    def test_initialization_with_env_var(self, temp_dir):
        """Test AgentOrchestrator initialization with environment variable."""
        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        assert orchestrator.api_key == "test-api-key"
        assert orchestrator.model_name == "qwen3-coder-plus"
        assert orchestrator.base_url == "https://test-host.com/v1"
        assert orchestrator.backend == "openai"
        assert orchestrator.output_dir.exists()
        assert orchestrator.working_directory.exists()
        assert orchestrator.active_sessions == {}

    def test_initialization_with_api_key_param(self, temp_dir):
        """Test AgentOrchestrator initialization with API key parameter."""
        orchestrator = AgentOrchestrator(
            api_key="param-key",
            model_name="test-model",
            base_url="https://test-host.com/v1",
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        assert orchestrator.api_key == "param-key"
        assert orchestrator.model_name == "test-model"
        assert orchestrator.base_url == "https://test-host.com/v1"

    @patch.dict('os.environ', {}, clear=True)
    def test_initialization_without_api_key_raises_error(self, temp_dir):
        """Test AgentOrchestrator raises error when no API key available."""
        with pytest.raises(ValueError, match="No API key found"):
            AgentOrchestrator(
                model_name="test-model",
                base_url="https://test-host.com/v1",
                output_dir=str(temp_dir / "logs"),
                working_directory=str(temp_dir / "workspace")
            )

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_start_conversation_isolated_workspace(self, mock_coding_agent_class, temp_dir):
        """Test starting conversation with isolated workspace."""
        mock_agent_instance = Mock(spec=CodingAgent)
        mock_agent_instance.tool_executor = Mock()
        mock_agent_instance.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent_instance

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        session = orchestrator.start_conversation(
            task_description="Test task",
            isolated_workspace=True
        )

        # Verify session created
        assert session.conversation_id in orchestrator.active_sessions
        assert session.agent == mock_agent_instance

        # Verify isolated workspace created
        workspace_name = f"conv_{session.conversation_id}"
        expected_workspace = temp_dir / "workspace" / workspace_name
        assert session.working_directory == expected_workspace
        assert expected_workspace.exists()

        # Verify CodingAgent initialized correctly
        mock_coding_agent_class.assert_called_once()
        call_kwargs = mock_coding_agent_class.call_args[1]
        assert call_kwargs["model_name"] == "qwen3-coder-plus"
        assert call_kwargs["backend"] == "openai"
        assert call_kwargs["api_key"] == "test-key"
        assert call_kwargs["permission_mode"] == "auto"
        assert call_kwargs["enable_clarity"] is False

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_start_conversation_shared_workspace(self, mock_coding_agent_class, temp_dir):
        """Test starting conversation with shared workspace."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        session = orchestrator.start_conversation(isolated_workspace=False)

        # Verify shared workspace used
        assert session.working_directory == temp_dir / "workspace"

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_get_session(self, mock_coding_agent_class, temp_dir):
        """Test retrieving active session by ID."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        session = orchestrator.start_conversation()
        conv_id = session.conversation_id

        # Retrieve session
        retrieved = orchestrator.get_session(conv_id)
        assert retrieved == session

        # Non-existent session
        assert orchestrator.get_session("nonexistent") is None

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_end_conversation(self, mock_coding_agent_class, temp_dir):
        """Test ending conversation and saving log."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        session = orchestrator.start_conversation()
        conv_id = session.conversation_id

        # End conversation
        log = orchestrator.end_conversation(conv_id)

        # Verify log returned
        assert log.conversation_id == conv_id
        assert log.ended_at is not None

        # Verify session removed
        assert conv_id not in orchestrator.active_sessions

        # Verify log file saved
        log_file = temp_dir / "logs" / f"conversation_{conv_id}.json"
        assert log_file.exists()

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_end_conversation_nonexistent_raises_error(self, mock_coding_agent_class, temp_dir):
        """Test ending nonexistent conversation raises KeyError."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        with pytest.raises(KeyError, match="not found in active sessions"):
            orchestrator.end_conversation("nonexistent-id")

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_list_active_conversations(self, mock_coding_agent_class, temp_dir):
        """Test listing all active conversations."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        # Start multiple conversations
        session1 = orchestrator.start_conversation()
        session2 = orchestrator.start_conversation()

        # List conversations
        active = orchestrator.list_active_conversations()

        assert len(active) == 2
        assert session1.conversation_id in active
        assert session2.conversation_id in active

        # Verify info structure
        info1 = active[session1.conversation_id]
        assert info1["conversation_id"] == session1.conversation_id
        assert "started_at" in info1
        assert "working_directory" in info1
        assert info1["message_count"] == 0
        assert info1["turns"] == 0

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_send_message_ephemeral(self, mock_coding_agent_class, temp_dir):
        """Test simple send_message API creates ephemeral session."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_response = Mock()
        mock_response.content = "Ephemeral response"
        mock_agent.execute_task.return_value = mock_response
        mock_agent.tool_execution_history = []
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        # Send single message
        response = orchestrator.send_message("Build something")

        # Verify response received
        assert response.content == "Ephemeral response"
        assert response.success is True

        # Verify no active sessions (ephemeral session removed)
        assert len(orchestrator.active_sessions) == 0

        # Verify agent was called
        mock_agent.execute_task.assert_called_once_with("Build something", stream=True)

    @patch('src.orchestration.agent_orchestrator.CodingAgent')
    @patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key', 'LLM_MODEL': 'qwen3-coder-plus', 'LLM_HOST': 'https://test-host.com/v1'})
    def test_list_empty_conversations(self, mock_coding_agent_class, temp_dir):
        """Test listing conversations when none are active."""
        mock_agent = Mock(spec=CodingAgent)
        mock_agent.tool_executor = Mock()
        mock_agent.tool_executor.tools = {}
        mock_coding_agent_class.return_value = mock_agent

        orchestrator = AgentOrchestrator(
            output_dir=str(temp_dir / "logs"),
            working_directory=str(temp_dir / "workspace")
        )

        active = orchestrator.list_active_conversations()

        assert active == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
