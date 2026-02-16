"""Comprehensive tests for SubAgent class."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
from dataclasses import dataclass

from src.subagents.subagent import SubAgent, SubAgentResult
from src.subagents.config import SubAgentConfig, SubAgentLLMConfig
from src.tools.base import ToolResult, ToolStatus
from src.llm import LLMBackendType, LLMResponse


@pytest.fixture
def mock_main_agent():
    """Create a mock main CodingAgent."""
    agent = Mock()
    agent.model_name = "qwen-2.5"
    agent.context_window = 8192
    agent.working_directory = Path("/test/project")

    # Mock LLM
    agent.llm = Mock()
    agent.llm.config = Mock()
    agent.llm.config.backend_type = LLMBackendType.OPENAI
    agent.llm.config.model_name = "qwen-2.5"
    agent.llm.config.base_url = "http://localhost:8000"
    agent.llm.config.context_window = 8192
    agent.llm.config.temperature = 0.7
    agent.llm.config.max_tokens = 4096
    agent.llm.config.top_p = 0.95
    agent.llm.api_key = "test-key"
    agent.llm.api_key_env = "OPENAI_API_KEY"

    # Mock tool executor with basic tools
    agent.tool_executor = Mock()
    agent.tool_executor.tools = {
        "read_file": Mock(__class__=type('ReadFileTool', (), {})),
        "write_file": Mock(__class__=type('WriteFileTool', (), {})),
        "edit_file": Mock(__class__=type('EditFileTool', (), {}))
    }

    # Mock hook manager
    agent.hook_manager = None

    return agent


@pytest.fixture
def basic_config():
    """Create a basic SubAgentConfig."""
    return SubAgentConfig(
        name="test-agent",
        description="Test subagent for unit testing",
        system_prompt="You are a test subagent. Execute tasks efficiently.",
        tools=["Read", "Write"],
        llm=None,  # Inherit from main agent
    )


@pytest.fixture
def custom_model_config():
    """Create a SubAgentConfig with custom model."""
    return SubAgentConfig(
        name="custom-agent",
        description="Custom model agent",
        system_prompt="You are a custom agent.",
        tools=None,  # Inherit all tools
        llm=SubAgentLLMConfig(model="qwen-plus", context_window=16384),
    )


class TestSubAgentResult:
    """Test SubAgentResult dataclass."""

    def test_successful_result_str(self):
        """Test string representation of successful result."""
        result = SubAgentResult(
            success=True,
            subagent_name="test-agent",
            output="Task completed successfully",
            execution_time=1.5,
            tool_calls=[
                {"tool": "read_file", "success": True},
                {"tool": "write_file", "success": True}
            ]
        )

        str_repr = str(result)

        assert "[OK] SUCCESS" in str_repr
        assert "test-agent" in str_repr
        assert "1.50s" in str_repr
        assert "Tools Used: 2" in str_repr
        assert "Task completed" in str_repr

    def test_failed_result_str(self):
        """Test string representation of failed result."""
        result = SubAgentResult(
            success=False,
            subagent_name="test-agent",
            output="",
            error="Execution failed due to error",
            execution_time=0.8
        )

        str_repr = str(result)

        assert "[FAIL] FAILED" in str_repr
        assert "test-agent" in str_repr
        assert "0.80s" in str_repr
        assert "Error: Execution failed" in str_repr


class TestSubAgentInitialization:
    """Test SubAgent initialization."""

    def test_initialize_with_basic_config(self, basic_config, mock_main_agent):
        """Test basic subagent initialization."""
        subagent = SubAgent(basic_config, mock_main_agent)

        assert subagent.config == basic_config
        assert subagent.main_agent == mock_main_agent
        assert len(subagent.session_id) == 8
        assert subagent.execution_history == []

    def test_llm_initialization_inherit_model(self, basic_config, mock_main_agent):
        """Test that subagent inherits model from main agent when not specified."""
        subagent = SubAgent(basic_config, mock_main_agent)

        # Should use main agent's LLM (no overrides)
        assert subagent.llm.config.model_name == "qwen-2.5"
        assert subagent._override_llm is None

    def test_llm_initialization_custom_model(self, custom_model_config, mock_main_agent):
        """Test that subagent creates override LLM when custom model specified."""
        with patch('src.subagents.subagent.SubAgent._create_override_llm') as mock_create:
            mock_override = Mock(config=Mock(
                model_name="qwen-plus",
                context_window=16384,
                backend_type=LLMBackendType.OPENAI,
            ))
            mock_create.return_value = mock_override

            subagent = SubAgent(custom_model_config, mock_main_agent)

            # Verify override LLM was created
            mock_create.assert_called_once()
            assert subagent.llm.config.model_name == "qwen-plus"
            assert subagent.llm.config.context_window == 16384

    def test_message_store_independent(self, basic_config, mock_main_agent):
        """Test that subagent creates independent MessageStore."""
        subagent = SubAgent(basic_config, mock_main_agent)

        # Subagent should have its own message store
        assert subagent._message_store is not None
        assert subagent._message_store.message_count == 0

    def test_tool_executor_from_main_agent(self, basic_config, mock_main_agent):
        """Test that subagent uses main agent's tool executor."""
        subagent = SubAgent(basic_config, mock_main_agent)

        assert subagent._tool_executor == mock_main_agent.tool_executor

    def test_direct_injection_mode(self, basic_config):
        """Test subagent can be initialized with direct LLM/tool injection."""
        mock_llm = Mock(config=Mock(
            model_name="test-model",
            context_window=4096,
            backend_type=LLMBackendType.OPENAI,
        ))
        mock_tools = Mock(tools={"read_file": Mock()})

        subagent = SubAgent(
            basic_config,
            main_agent=None,
            llm=mock_llm,
            tool_executor=mock_tools,
            working_directory="/test",
        )

        assert subagent.main_agent is None
        assert subagent.llm == mock_llm
        assert subagent._tool_executor == mock_tools

    def test_direct_injection_requires_both(self, basic_config):
        """Test that direct injection requires both llm and tool_executor."""
        with pytest.raises(ValueError, match="requires either main_agent"):
            SubAgent(basic_config, main_agent=None, llm=Mock())


class TestSubAgentExecution:
    """Test SubAgent execution functionality."""

    def test_execute_success_returns_result(self, basic_config, mock_main_agent):
        """Test successful execution returns SubAgentResult."""
        subagent = SubAgent(basic_config, mock_main_agent)

        # Mock the internal _execute_with_tools and _build_context
        with patch.object(subagent, '_build_context', return_value=([], "uuid-1")), \
             patch.object(subagent, '_execute_with_tools', return_value=("Task done", [])):

            result = subagent.execute("Test task")

            assert result.success is True
            assert result.subagent_name == "test-agent"
            assert "Task done" in result.output
            assert result.execution_time >= 0
            assert len(subagent.execution_history) == 1

    def test_execute_with_tool_calls(self, basic_config, mock_main_agent):
        """Test execution records tool calls."""
        subagent = SubAgent(basic_config, mock_main_agent)

        tool_calls = [
            {"tool": "read_file", "success": True},
            {"tool": "write_file", "success": True},
        ]
        with patch.object(subagent, '_build_context', return_value=([], "uuid-1")), \
             patch.object(subagent, '_execute_with_tools', return_value=("Done", tool_calls)):

            result = subagent.execute("Read and write")

            assert result.success is True
            assert len(result.tool_calls) == 2
            assert result.tool_calls[0]["tool"] == "read_file"

    def test_execute_handles_failure(self, basic_config, mock_main_agent):
        """Test that execution handles failures gracefully."""
        subagent = SubAgent(basic_config, mock_main_agent)

        with patch.object(subagent, '_build_context', side_effect=Exception("Build error")):
            result = subagent.execute("Task")

            assert result.success is False
            assert result.error is not None
            assert "Build error" in result.error
            assert result.output == ""
            assert len(subagent.execution_history) == 1

    def test_execute_respects_max_iterations(self, basic_config, mock_main_agent):
        """Test that max_iterations is passed through."""
        subagent = SubAgent(basic_config, mock_main_agent)

        with patch.object(subagent, '_build_context', return_value=([], "uuid-1")), \
             patch.object(subagent, '_execute_with_tools', return_value=("Done", [])) as mock_exec:

            subagent.execute("Task", max_iterations=5)

            # Verify max_iterations was passed
            call_kwargs = mock_exec.call_args
            assert call_kwargs[1]['max_iterations'] == 5


class TestSubAgentStatistics:
    """Test SubAgent statistics functionality."""

    def test_statistics_with_executions(self, basic_config, mock_main_agent):
        """Test statistics calculation with execution history."""
        subagent = SubAgent(basic_config, mock_main_agent)

        # Add some execution results
        subagent.execution_history = [
            SubAgentResult(
                success=True,
                subagent_name="test-agent",
                output="Output 1",
                execution_time=1.5,
                tool_calls=[{"tool": "tool1"}]
            ),
            SubAgentResult(
                success=True,
                subagent_name="test-agent",
                output="Output 2",
                execution_time=2.0,
                tool_calls=[{"tool": "tool1"}, {"tool": "tool2"}]
            ),
            SubAgentResult(
                success=False,
                subagent_name="test-agent",
                output="",
                error="Failed",
                execution_time=0.5
            )
        ]

        stats = subagent.get_statistics()

        assert stats["subagent_name"] == "test-agent"
        assert stats["total_executions"] == 3
        assert stats["successful"] == 2
        assert stats["failed"] == 1
        assert stats["success_rate"] == pytest.approx(2/3, 0.01)
        assert stats["total_execution_time"] == pytest.approx(4.0, 0.01)
        assert stats["average_execution_time"] == pytest.approx(4.0/3, 0.01)
        assert stats["total_tool_calls"] == 3
        assert stats["average_tool_calls"] == pytest.approx(1.0, 0.01)
        assert stats["model"] == "qwen-2.5"

    def test_statistics_with_no_executions(self, basic_config, mock_main_agent):
        """Test statistics with no execution history."""
        subagent = SubAgent(basic_config, mock_main_agent)

        stats = subagent.get_statistics()

        assert stats["total_executions"] == 0
        assert stats["successful"] == 0
        assert stats["failed"] == 0
        assert stats["success_rate"] == 0
        assert stats["average_execution_time"] == 0
        assert stats["average_tool_calls"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
