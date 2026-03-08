"""
Tests for AgentInterface, MockAgent, and helper utilities.

Covers:
- AgentInterface abstract contract
- MockAgent implementation
- AgentContextProvider
- AgentLLMProxy
- AgentToolProxy
"""

import pytest
from typing import List, Dict, Any
from src.core import (
    AgentInterface,
    MockAgent,
    AgentContextProvider,
    AgentLLMProxy,
    AgentToolProxy,
)


class TestAgentInterface:
    """Tests for AgentInterface abstract base class."""

    def test_interface_is_abstract(self):
        """AgentInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AgentInterface()

    def test_interface_defines_required_methods(self):
        """AgentInterface defines all 4 required methods."""
        required_methods = ['call_llm', 'execute_tool', 'get_context', 'update_memory']
        for method in required_methods:
            assert hasattr(AgentInterface, method)
            assert callable(getattr(AgentInterface, method))


class TestMockAgent:
    """Tests for MockAgent implementation."""

    def test_mock_agent_implements_interface(self):
        """MockAgent is an instance of AgentInterface."""
        mock = MockAgent()
        assert isinstance(mock, AgentInterface)

    def test_call_llm_records_history(self):
        """call_llm records invocations in history."""
        mock = MockAgent(mock_llm_response="Test response")
        messages = [{"role": "user", "content": "Hello"}]

        response = mock.call_llm(messages, temperature=0.5)

        assert response == "Test response"
        assert len(mock.call_history) == 1
        assert mock.call_history[0][0] == messages
        assert mock.call_history[0][1] == 0.5  # temperature

    def test_call_llm_multiple_calls(self):
        """call_llm records multiple invocations."""
        mock = MockAgent(mock_llm_response="Response")

        mock.call_llm([{"role": "user", "content": "First"}])
        mock.call_llm([{"role": "user", "content": "Second"}])
        mock.call_llm([{"role": "user", "content": "Third"}])

        assert len(mock.call_history) == 3
        assert mock.call_history[0][0][0]["content"] == "First"
        assert mock.call_history[1][0][0]["content"] == "Second"
        assert mock.call_history[2][0][0]["content"] == "Third"

    def test_execute_tool_records_history(self):
        """execute_tool records invocations in history."""
        mock = MockAgent(mock_tool_result={"status": "ok"})

        result = mock.execute_tool('write_file', file_path='test.py', content='print(1)')

        assert result == {"status": "ok"}
        assert len(mock.tool_history) == 1
        assert mock.tool_history[0][0] == 'write_file'
        assert mock.tool_history[0][1] == {'file_path': 'test.py', 'content': 'print(1)'}

    def test_execute_tool_multiple_tools(self):
        """execute_tool records multiple tool invocations."""
        mock = MockAgent()

        mock.execute_tool('write_file', file_path='a.py')
        mock.execute_tool('read_file', file_path='b.py')
        mock.execute_tool('run_command', command='ls')

        assert len(mock.tool_history) == 3
        assert mock.tool_history[0][0] == 'write_file'
        assert mock.tool_history[1][0] == 'read_file'
        assert mock.tool_history[2][0] == 'run_command'

    def test_get_context_returns_default_context(self):
        """get_context returns default context dictionary."""
        mock = MockAgent()
        context = mock.get_context()

        assert 'working_directory' in context
        assert 'conversation_history' in context
        assert 'session_id' in context
        assert 'active_task' in context
        assert context['session_id'] == 'mock_session'

    def test_get_context_returns_custom_context(self):
        """get_context returns custom context when provided."""
        custom_context = {
            "working_directory": "/custom/dir",
            "session_id": "custom_session"
        }
        mock = MockAgent(mock_context=custom_context)

        context = mock.get_context()

        assert context == custom_context

    def test_update_memory_stores_in_dict(self):
        """update_memory stores key-value pairs in internal dictionary."""
        mock = MockAgent()

        mock.update_memory('test_key', 'test_value')
        mock.update_memory('number', 42)
        mock.update_memory('dict', {'nested': 'data'})

        assert mock.memory['test_key'] == 'test_value'
        assert mock.memory['number'] == 42
        assert mock.memory['dict'] == {'nested': 'data'}

    def test_reset_clears_all_history(self):
        """reset() clears call history, tool history, and memory."""
        mock = MockAgent()

        # Add some data
        mock.call_llm([{"role": "user", "content": "test"}])
        mock.execute_tool('some_tool', param='value')
        mock.update_memory('key', 'value')

        # Reset
        mock.reset()

        assert len(mock.call_history) == 0
        assert len(mock.tool_history) == 0
        assert len(mock.memory) == 0

    def test_set_llm_response_changes_response(self):
        """set_llm_response() changes the mocked LLM response."""
        mock = MockAgent(mock_llm_response="Original")

        response1 = mock.call_llm([{"role": "user", "content": "test"}])
        mock.set_llm_response("Updated")
        response2 = mock.call_llm([{"role": "user", "content": "test"}])

        assert response1 == "Original"
        assert response2 == "Updated"

    def test_set_tool_result_changes_result(self):
        """set_tool_result() changes the mocked tool result."""
        mock = MockAgent(mock_tool_result={"status": "original"})

        result1 = mock.execute_tool('tool')
        mock.set_tool_result({"status": "updated"})
        result2 = mock.execute_tool('tool')

        assert result1 == {"status": "original"}
        assert result2 == {"status": "updated"}

    def test_set_context_changes_context(self):
        """set_context() changes the mocked context."""
        mock = MockAgent()

        context1 = mock.get_context()
        mock.set_context({"custom": "context"})
        context2 = mock.get_context()

        assert context1 != context2
        assert context2 == {"custom": "context"}


class TestAgentContextProvider:
    """Tests for AgentContextProvider helper utility."""

    def test_get_full_context(self):
        """get_full_context returns agent context."""
        mock = MockAgent(mock_context={"key": "value"})
        provider = AgentContextProvider(mock)

        context = provider.get_full_context()

        assert context == {"key": "value"}

    def test_get_conversation_length_empty(self):
        """get_conversation_length returns 0 for empty conversation."""
        mock = MockAgent(mock_context={"conversation_history": []})
        provider = AgentContextProvider(mock)

        length = provider.get_conversation_length()

        assert length == 0

    def test_get_conversation_length_with_messages(self):
        """get_conversation_length returns correct count."""
        mock = MockAgent(mock_context={
            "conversation_history": [
                {"role": "user", "content": "1"},
                {"role": "assistant", "content": "2"},
                {"role": "user", "content": "3"},
            ]
        })
        provider = AgentContextProvider(mock)

        length = provider.get_conversation_length()

        assert length == 3

    def test_get_working_directory(self):
        """get_working_directory returns directory from context."""
        mock = MockAgent(mock_context={"working_directory": "/test/dir"})
        provider = AgentContextProvider(mock)

        directory = provider.get_working_directory()

        assert directory == "/test/dir"

    def test_get_session_id(self):
        """get_session_id returns session ID from context."""
        mock = MockAgent(mock_context={"session_id": "test_session_123"})
        provider = AgentContextProvider(mock)

        session_id = provider.get_session_id()

        assert session_id == "test_session_123"


class TestAgentLLMProxy:
    """Tests for AgentLLMProxy helper utility."""

    def test_call_llm_increments_counter(self):
        """call_llm increments call counter."""
        mock = MockAgent()
        proxy = AgentLLMProxy(mock)

        assert proxy.call_count == 0

        proxy.call_llm([{"role": "user", "content": "test"}])

        assert proxy.call_count == 1

    def test_call_llm_multiple_calls_increment_counter(self):
        """Multiple call_llm invocations increment counter."""
        mock = MockAgent()
        proxy = AgentLLMProxy(mock)

        proxy.call_llm([{"role": "user", "content": "1"}])
        proxy.call_llm([{"role": "user", "content": "2"}])
        proxy.call_llm([{"role": "user", "content": "3"}])

        assert proxy.call_count == 3

    def test_call_llm_passes_through_to_agent(self):
        """call_llm passes through to underlying agent."""
        mock = MockAgent(mock_llm_response="Test response")
        proxy = AgentLLMProxy(mock)

        messages = [{"role": "user", "content": "Hello"}]
        response = proxy.call_llm(messages, temperature=0.5)

        assert response == "Test response"
        assert len(mock.call_history) == 1
        assert mock.call_history[0][0] == messages

    def test_call_llm_error_increments_error_counter(self):
        """call_llm increments error counter on exception."""
        class FailingAgent(AgentInterface):
            def call_llm(self, messages, **kwargs):
                raise RuntimeError("LLM failed")
            def execute_tool(self, tool_name, **params):
                pass
            def get_context(self):
                pass
            def update_memory(self, key, value):
                pass

        proxy = AgentLLMProxy(FailingAgent())

        assert proxy.error_count == 0

        with pytest.raises(RuntimeError):
            proxy.call_llm([{"role": "user", "content": "test"}])

        assert proxy.error_count == 1

    def test_call_with_retry_succeeds_first_try(self):
        """call_with_retry succeeds on first attempt."""
        mock = MockAgent(mock_llm_response="Success")
        proxy = AgentLLMProxy(mock)

        response = proxy.call_with_retry([{"role": "user", "content": "test"}])

        assert response == "Success"
        assert proxy.call_count == 1

    def test_call_with_retry_retries_on_failure(self):
        """call_with_retry retries on failure."""
        class FlakeyAgent(AgentInterface):
            def __init__(self):
                self.attempts = 0
            def call_llm(self, messages, **kwargs):
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("Temporary failure")
                return "Success on retry"
            def execute_tool(self, tool_name, **params):
                pass
            def get_context(self):
                pass
            def update_memory(self, key, value):
                pass

        flakey = FlakeyAgent()
        proxy = AgentLLMProxy(flakey)

        response = proxy.call_with_retry([{"role": "user", "content": "test"}], max_retries=5)

        assert response == "Success on retry"
        assert proxy.call_count == 3

    def test_call_with_retry_returns_none_after_max_retries(self):
        """call_with_retry returns None after exhausting retries."""
        class AlwaysFailingAgent(AgentInterface):
            def call_llm(self, messages, **kwargs):
                raise RuntimeError("Always fails")
            def execute_tool(self, tool_name, **params):
                pass
            def get_context(self):
                pass
            def update_memory(self, key, value):
                pass

        proxy = AgentLLMProxy(AlwaysFailingAgent())

        response = proxy.call_with_retry([{"role": "user", "content": "test"}], max_retries=3)

        assert response is None
        assert proxy.call_count == 3

    def test_get_statistics(self):
        """get_statistics returns call and error counts."""
        mock = MockAgent()
        proxy = AgentLLMProxy(mock)

        # Make some calls
        proxy.call_llm([{"role": "user", "content": "1"}])
        proxy.call_llm([{"role": "user", "content": "2"}])

        stats = proxy.get_statistics()

        assert stats['call_count'] == 2
        assert stats['error_count'] == 0
        assert stats['success_rate'] == 1.0


class TestCriticalFixes:
    """Tests for critical fixes from code review."""

    def test_call_llm_validates_empty_messages(self):
        """call_llm validates empty messages (Critical Fix #2)."""
        from src.core import CodingAgent
        import os

        # Create real agent
        agent = CodingAgent(
            model_name=os.getenv("LLM_MODEL", "deepseek-coder"),
            backend=os.getenv("LLM_BACKEND", "openai"),
            base_url=os.getenv("LLM_HOST", "http://localhost:8000"),
            context_window=int(os.getenv("MAX_CONTEXT_TOKENS", "4096")),
            api_key=os.getenv("DASHSCOPE_API_KEY", os.getenv("OPENAI_API_KEY", "sk-test-placeholder")),
            load_file_memories=False,
        )

        # Empty messages should raise ValueError
        with pytest.raises(ValueError, match="Invalid messages"):
            agent.call_llm([])

    def test_call_llm_validates_missing_role(self):
        """call_llm validates missing role (Critical Fix #2)."""
        from src.core import CodingAgent
        import os

        agent = CodingAgent(
            model_name=os.getenv("LLM_MODEL", "deepseek-coder"),
            backend=os.getenv("LLM_BACKEND", "openai"),
            base_url=os.getenv("LLM_HOST", "http://localhost:8000"),
            context_window=int(os.getenv("MAX_CONTEXT_TOKENS", "4096")),
            api_key=os.getenv("DASHSCOPE_API_KEY", os.getenv("OPENAI_API_KEY", "sk-test-placeholder")),
            load_file_memories=False,
        )

        # Message without role should raise ValueError
        with pytest.raises(ValueError, match="Invalid messages"):
            agent.call_llm([{"content": "hello"}])

    def test_mock_agent_thread_safety(self):
        """MockAgent is thread-safe (Critical Fix #3)."""
        import threading

        mock = MockAgent()

        def make_calls(n):
            for i in range(n):
                mock.call_llm([{"role": "user", "content": f"Thread call {i}"}])

        # Run 10 threads, 100 calls each
        threads = [threading.Thread(target=make_calls, args=(100,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 1000 calls recorded
        assert len(mock.call_history) == 1000

    def test_update_memory_preserves_structure(self):
        """update_memory preserves structured data (Critical Fix #4)."""
        from src.core import CodingAgent
        import os

        agent = CodingAgent(
            model_name=os.getenv("LLM_MODEL", "deepseek-coder"),
            backend=os.getenv("LLM_BACKEND", "openai"),
            base_url=os.getenv("LLM_HOST", "http://localhost:8000"),
            context_window=int(os.getenv("MAX_CONTEXT_TOKENS", "4096")),
            api_key=os.getenv("DASHSCOPE_API_KEY", os.getenv("OPENAI_API_KEY", "sk-test-placeholder")),
            load_file_memories=False,
        )

        # Store structured data
        test_data = {'passed': 10, 'failed': 2, 'coverage': 0.85}
        agent.update_memory('test_results', test_data)

        # Retrieve and verify structure is preserved
        retrieved = agent.get_memory('test_results')
        assert retrieved == test_data
        assert isinstance(retrieved, dict)
        assert retrieved['passed'] == 10

    def test_get_memory_with_default(self):
        """get_memory returns default for missing key (Critical Fix #4)."""
        from src.core import CodingAgent
        import os

        agent = CodingAgent(
            model_name=os.getenv("LLM_MODEL", "deepseek-coder"),
            backend=os.getenv("LLM_BACKEND", "openai"),
            base_url=os.getenv("LLM_HOST", "http://localhost:8000"),
            context_window=int(os.getenv("MAX_CONTEXT_TOKENS", "4096")),
            api_key=os.getenv("DASHSCOPE_API_KEY", os.getenv("OPENAI_API_KEY", "sk-test-placeholder")),
            load_file_memories=False,
        )

        # Get non-existent key with default
        result = agent.get_memory('nonexistent_key', {'default': 'value'})
        assert result == {'default': 'value'}


class TestAgentToolProxy:
    """Tests for AgentToolProxy helper utility."""

    def test_execute_tool_records_history(self):
        """execute_tool records execution history."""
        mock = MockAgent(mock_tool_result={"status": "ok"})
        proxy = AgentToolProxy(mock)

        proxy.execute_tool('write_file', file_path='test.py', content='code')

        assert len(proxy.execution_history) == 1
        assert proxy.execution_history[0]['tool'] == 'write_file'
        assert proxy.execution_history[0]['params'] == {'file_path': 'test.py', 'content': 'code'}
        assert proxy.execution_history[0]['result'] == {"status": "ok"}

    def test_execute_tool_passes_through_to_agent(self):
        """execute_tool passes through to underlying agent."""
        mock = MockAgent(mock_tool_result={"result": "success"})
        proxy = AgentToolProxy(mock)

        result = proxy.execute_tool('some_tool', param1='value1')

        assert result == {"result": "success"}
        assert len(mock.tool_history) == 1
        assert mock.tool_history[0][0] == 'some_tool'
        assert mock.tool_history[0][1] == {'param1': 'value1'}

    def test_execute_with_validation_validates_write_file(self):
        """execute_with_validation validates write_file parameters."""
        mock = MockAgent()
        proxy = AgentToolProxy(mock)

        # Missing content parameter
        with pytest.raises(ValueError, match="write_file requires file_path and content"):
            proxy.execute_with_validation('write_file', file_path='test.py')

        # Missing file_path parameter
        with pytest.raises(ValueError, match="write_file requires file_path and content"):
            proxy.execute_with_validation('write_file', content='code')

    def test_execute_with_validation_succeeds_with_valid_params(self):
        """execute_with_validation succeeds with valid parameters."""
        mock = MockAgent(mock_tool_result={"status": "ok"})
        proxy = AgentToolProxy(mock)

        result = proxy.execute_with_validation('write_file', file_path='test.py', content='code')

        assert result == {"status": "ok"}
        assert len(proxy.execution_history) == 1

    def test_get_execution_count(self):
        """get_execution_count returns number of executions."""
        mock = MockAgent()
        proxy = AgentToolProxy(mock)

        assert proxy.get_execution_count() == 0

        proxy.execute_tool('tool1')
        proxy.execute_tool('tool2')
        proxy.execute_tool('tool3')

        assert proxy.get_execution_count() == 3

    def test_get_tool_usage(self):
        """get_tool_usage returns usage statistics."""
        mock = MockAgent()
        proxy = AgentToolProxy(mock)

        proxy.execute_tool('write_file', file_path='a.py')
        proxy.execute_tool('read_file', file_path='b.py')
        proxy.execute_tool('write_file', file_path='c.py')
        proxy.execute_tool('write_file', file_path='d.py')
        proxy.execute_tool('run_command', command='ls')

        usage = proxy.get_tool_usage()

        assert usage['write_file'] == 3
        assert usage['read_file'] == 1
        assert usage['run_command'] == 1
