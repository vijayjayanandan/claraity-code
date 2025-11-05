"""Comprehensive tests for SubAgent class."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
from dataclasses import dataclass

from src.subagents.subagent import SubAgent, SubAgentResult
from src.subagents.config import SubAgentConfig
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
        model=None,  # Inherit from main agent
        context_window=None
    )


@pytest.fixture
def custom_model_config():
    """Create a SubAgentConfig with custom model."""
    return SubAgentConfig(
        name="custom-agent",
        description="Custom model agent",
        system_prompt="You are a custom agent.",
        tools=None,  # Inherit all tools
        model="qwen-plus",
        context_window=16384
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

        assert "✅ SUCCESS" in str_repr
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

        assert "❌ FAILED" in str_repr
        assert "test-agent" in str_repr
        assert "0.80s" in str_repr
        assert "Error: Execution failed" in str_repr


class TestSubAgentInitialization:
    """Test SubAgent initialization."""

    def test_initialize_with_basic_config(self, basic_config, mock_main_agent):
        """Test basic subagent initialization."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()
            MockToolExecutor.return_value = Mock(tools={})
            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))

            subagent = SubAgent(basic_config, mock_main_agent)

            assert subagent.config == basic_config
            assert subagent.main_agent == mock_main_agent
            assert subagent.enable_verification is True
            assert subagent.enable_rollback is False
            assert len(subagent.session_id) == 8
            assert subagent.execution_history == []

    def test_llm_initialization_inherit_model(self, basic_config, mock_main_agent):
        """Test that subagent inherits model from main agent when not specified."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()
            MockToolExecutor.return_value = Mock(tools={})
            mock_llm = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))
            MockBackend.return_value = mock_llm

            subagent = SubAgent(basic_config, mock_main_agent)

            # Verify LLM was created with main agent's model
            assert subagent.llm.config.model_name == "qwen-2.5"

    def test_llm_initialization_custom_model(self, custom_model_config, mock_main_agent):
        """Test that subagent uses custom model when specified."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()
            MockToolExecutor.return_value = Mock(tools={})

            # Mock LLM with custom model
            mock_llm = Mock(config=Mock(
                backend_type=LLMBackendType.OPENAI,
                model_name="qwen-plus",
                context_window=16384
            ))
            MockBackend.return_value = mock_llm

            subagent = SubAgent(custom_model_config, mock_main_agent)

            # Verify custom model was used
            MockBackend.assert_called_once()
            call_args = MockBackend.call_args
            llm_config = call_args[0][0]
            assert llm_config.model_name == "qwen-plus"
            assert llm_config.context_window == 16384

    def test_memory_initialization_independent(self, basic_config, mock_main_agent):
        """Test that subagent creates independent memory system."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            mock_memory = Mock()
            MockMemory.return_value = mock_memory
            MockToolExecutor.return_value = Mock(tools={})
            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))

            subagent = SubAgent(basic_config, mock_main_agent)

            # Verify MemoryManager was created with correct parameters
            MockMemory.assert_called_once()
            call_kwargs = MockMemory.call_args[1]

            assert call_kwargs['total_context_tokens'] == 8192
            assert call_kwargs['working_memory_tokens'] == int(8192 * 0.4)
            assert call_kwargs['episodic_memory_tokens'] == int(8192 * 0.2)
            assert call_kwargs['load_file_memories'] is False

    def test_tool_initialization_restricted(self, basic_config, mock_main_agent):
        """Test that subagent restricts tools based on config."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()

            # Create mock tool executor
            mock_tool_executor = Mock()
            mock_tool_executor.tools = {}
            MockToolExecutor.return_value = mock_tool_executor

            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))

            subagent = SubAgent(basic_config, mock_main_agent)

            # Verify ToolExecutor was created
            MockToolExecutor.assert_called_once()

            # Verify tools were registered (checking register_tool was called)
            # Note: In actual code, tools matching "Read" and "Write" would be registered
            # For this test, we just verify the executor was created with hook_manager
            call_kwargs = MockToolExecutor.call_args[1]
            assert 'hook_manager' in call_kwargs

    def test_tool_initialization_inherit_all(self, custom_model_config, mock_main_agent):
        """Test that subagent inherits all tools when config.tools is None."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()

            mock_tool_executor = Mock()
            mock_tool_executor.tools = {}
            MockToolExecutor.return_value = mock_tool_executor

            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-plus",
                context_window=16384
            ))

            subagent = SubAgent(custom_model_config, mock_main_agent)

            # Verify ToolExecutor was created
            MockToolExecutor.assert_called_once()


class TestSubAgentExecution:
    """Test SubAgent execution functionality."""

    def test_execute_success_without_tools(self, basic_config, mock_main_agent):
        """Test successful execution without tool calls."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend, \
             patch('src.tools.tool_parser.ToolCallParser') as MockParser:

            # Setup mocks
            mock_memory = Mock()
            mock_memory.working_memory = Mock(messages=[])
            MockMemory.return_value = mock_memory

            mock_tool_executor = Mock()
            mock_tool_executor.tools = {}
            mock_tool_executor.get_tools_description = Mock(return_value="Available tools")
            MockToolExecutor.return_value = mock_tool_executor

            mock_llm = Mock()
            mock_llm.config = Mock(
                model_name="qwen-2.5",
                context_window=8192
            )
            mock_llm.generate = Mock(return_value=LLMResponse(
                content="Task completed successfully",
                model="qwen-2.5",
                usage={"input_tokens": 100, "output_tokens": 50}
            ))
            MockBackend.return_value = mock_llm

            # Mock parser to indicate no tool calls
            mock_parsed = Mock()
            mock_parsed.has_tool_calls = False
            MockParser.return_value.parse = Mock(return_value=mock_parsed)

            subagent = SubAgent(basic_config, mock_main_agent)
            result = subagent.execute("Test task")

            assert result.success is True
            assert result.subagent_name == "test-agent"
            assert "Task completed successfully" in result.output
            assert len(result.tool_calls) == 0
            assert result.execution_time > 0
            assert len(subagent.execution_history) == 1

    def test_execute_success_with_tools(self, basic_config, mock_main_agent):
        """Test successful execution with tool calls."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend, \
             patch('src.tools.tool_parser.ToolCallParser') as MockParser:

            # Setup mocks
            mock_memory = Mock()
            mock_memory.working_memory = Mock(messages=[])
            MockMemory.return_value = mock_memory

            mock_tool_executor = Mock()
            mock_tool_executor.tools = {"read_file": Mock()}
            mock_tool_executor.get_tools_description = Mock(return_value="Available tools")
            mock_tool_executor.execute_tool = Mock(return_value=ToolResult(
                tool_name="read_file",
                status=ToolStatus.SUCCESS,
                output="File contents"
            ))
            MockToolExecutor.return_value = mock_tool_executor

            mock_llm = Mock()
            mock_llm.config = Mock(
                model_name="qwen-2.5",
                context_window=8192
            )

            # First response with tool call, second without
            responses = [
                LLMResponse(
                    content="<TOOL_CALL>\ntool: read_file\narguments:\n  path: test.txt\n</TOOL_CALL>",
                    model="qwen-2.5",
                    usage={"input_tokens": 100, "output_tokens": 50}
                ),
                LLMResponse(
                    content="File read successfully: File contents",
                    model="qwen-2.5",
                    usage={"input_tokens": 150, "output_tokens": 30}
                )
            ]
            mock_llm.generate = Mock(side_effect=responses)
            MockBackend.return_value = mock_llm

            # Mock parser
            mock_tool_call = Mock()
            mock_tool_call.tool = "read_file"
            mock_tool_call.arguments = {"path": "test.txt"}

            mock_parsed_with_tools = Mock()
            mock_parsed_with_tools.has_tool_calls = True
            mock_parsed_with_tools.tool_calls = [mock_tool_call]

            mock_parsed_no_tools = Mock()
            mock_parsed_no_tools.has_tool_calls = False

            MockParser.return_value.parse = Mock(side_effect=[
                mock_parsed_with_tools,
                mock_parsed_no_tools
            ])

            subagent = SubAgent(basic_config, mock_main_agent)
            result = subagent.execute("Read test.txt")

            assert result.success is True
            assert result.subagent_name == "test-agent"
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["tool"] == "read_file"
            assert result.tool_calls[0]["success"] is True

    def test_execute_max_iterations_reached(self, basic_config, mock_main_agent):
        """Test execution when max iterations is reached."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend, \
             patch('src.tools.tool_parser.ToolCallParser') as MockParser:

            # Setup mocks
            mock_memory = Mock()
            mock_memory.working_memory = Mock(messages=[])
            MockMemory.return_value = mock_memory

            mock_tool_executor = Mock()
            mock_tool_executor.tools = {"read_file": Mock()}
            mock_tool_executor.get_tools_description = Mock(return_value="Tools")
            mock_tool_executor.execute_tool = Mock(return_value=ToolResult(
                tool_name="read_file",
                status=ToolStatus.SUCCESS,
                output="Data"
            ))
            MockToolExecutor.return_value = mock_tool_executor

            mock_llm = Mock()
            mock_llm.config = Mock(
                model_name="qwen-2.5",
                context_window=8192
            )

            # Always return tool calls until max iterations
            mock_llm.generate = Mock(return_value=LLMResponse(
                content="<TOOL_CALL>\ntool: read_file\narguments:\n  path: test.txt\n</TOOL_CALL>",
                model="qwen-2.5",
                usage={"input_tokens": 100, "output_tokens": 50}
            ))
            MockBackend.return_value = mock_llm

            # Mock parser to always return tool calls
            mock_tool_call = Mock()
            mock_tool_call.tool = "read_file"
            mock_tool_call.arguments = {"path": "test.txt"}

            mock_parsed = Mock()
            mock_parsed.has_tool_calls = True
            mock_parsed.tool_calls = [mock_tool_call]

            MockParser.return_value.parse = Mock(return_value=mock_parsed)

            subagent = SubAgent(basic_config, mock_main_agent)
            result = subagent.execute("Task", max_iterations=3)

            # Should have 3 tool calls (max iterations)
            assert result.success is True
            assert len(result.tool_calls) == 3

    def test_execute_handles_failure(self, basic_config, mock_main_agent):
        """Test that execution handles failures gracefully."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            # Setup mocks
            mock_memory = Mock()
            mock_memory.working_memory = Mock(messages=[])
            mock_memory.set_task_context = Mock(side_effect=Exception("Memory error"))
            MockMemory.return_value = mock_memory

            MockToolExecutor.return_value = Mock(tools={})
            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))

            subagent = SubAgent(basic_config, mock_main_agent)
            result = subagent.execute("Task")

            assert result.success is False
            assert result.error is not None
            assert "Memory error" in result.error
            assert result.output == ""
            assert len(subagent.execution_history) == 1


class TestSubAgentStatistics:
    """Test SubAgent statistics functionality."""

    def test_statistics_with_executions(self, basic_config, mock_main_agent):
        """Test statistics calculation with execution history."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()
            MockToolExecutor.return_value = Mock(tools={"tool1": Mock(), "tool2": Mock()})
            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))

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
            assert stats["context_window"] == 8192
            assert stats["tools_available"] == 2

    def test_statistics_with_no_executions(self, basic_config, mock_main_agent):
        """Test statistics with no execution history."""
        with patch('src.subagents.subagent.MemoryManager') as MockMemory, \
             patch('src.subagents.subagent.ToolExecutor') as MockToolExecutor, \
             patch('src.subagents.subagent.OpenAIBackend') as MockBackend:

            MockMemory.return_value = Mock()
            MockToolExecutor.return_value = Mock(tools={})
            MockBackend.return_value = Mock(config=Mock(
                model_name="qwen-2.5",
                context_window=8192
            ))

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
