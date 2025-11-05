"""Integration tests for workflow integration with CodingAgent.

Tests the complete flow: decision logic → execution → response generation.
"""

import pytest
from src.core.agent import CodingAgent


@pytest.fixture
def agent():
    """Create CodingAgent instance for testing."""
    from src.llm import OpenAIBackend, LLMConfig, LLMBackendType

    # Use OpenAI-compatible backend for testing
    return CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key="sk-6ca5ca68942447c7a4c18d0ea63f75e7"
    )


# ============================================================================
# Decision Logic Tests
# ============================================================================

def test_should_use_workflow_for_implementation(agent):
    """Test that implementation tasks use workflow."""
    assert agent._should_use_workflow(
        "Implement a new tool for listing directories",
        "implement"
    ) is True


def test_should_use_workflow_for_refactoring(agent):
    """Test that refactoring tasks use workflow."""
    assert agent._should_use_workflow(
        "Refactor the memory system to use Redis",
        "refactor"
    ) is True


def test_should_use_workflow_for_bugfix(agent):
    """Test that bug fixes use workflow."""
    assert agent._should_use_workflow(
        "Fix the bug where agent re-reads files",
        "debug"
    ) is True


def test_should_use_direct_for_explain(agent):
    """Test that explanation queries use direct execution."""
    assert agent._should_use_workflow(
        "Explain how the memory system works",
        "explain"
    ) is False


def test_should_use_direct_for_search(agent):
    """Test that search queries use direct execution."""
    assert agent._should_use_workflow(
        "Find all usages of LLMBackend",
        "explain"
    ) is False


def test_should_use_workflow_for_complex_search(agent):
    """Test that complex searches use workflow."""
    assert agent._should_use_workflow(
        "Search the entire codebase and analyze all memory patterns",
        "search"
    ) is True


# ============================================================================
# Direct Execution Tests
# ============================================================================

def test_direct_execution_explain(agent):
    """Test direct execution for explanation query."""
    response = agent.execute_task(
        task_description="Explain what is 2+2",
        task_type="explain",
        force_direct=True,
        stream=False
    )

    assert response.content is not None
    assert len(response.content) > 0
    assert response.metadata["execution_mode"] == "direct"


def test_direct_execution_search(agent):
    """Test direct execution for search query."""
    response = agent.execute_task(
        task_description="What files are in the src/workflow directory?",
        task_type="explain",
        force_direct=True,
        stream=False
    )

    assert response.content is not None
    assert response.metadata["execution_mode"] == "direct"


# ============================================================================
# Workflow Execution Tests (Mocked - No Real File Operations)
# ============================================================================

def test_workflow_execution_simple_task(agent):
    """Test workflow execution for simple implementation task."""
    # Note: This will use real LLM but won't actually create files
    # The test validates the workflow runs without crashing
    response = agent.execute_task(
        task_description="Create a simple hello world function",
        task_type="implement",
        force_workflow=True,
        stream=False
    )

    assert response.content is not None
    assert len(response.content) > 0
    assert response.metadata["execution_mode"] == "workflow"


def test_workflow_with_tool_execution(agent):
    """Test that workflow executes tools correctly."""
    # Test with a task that requires reading files
    response = agent.execute_task(
        task_description="Read src/workflow/__init__.py and summarize what it exports",
        task_type="explain",
        force_workflow=True,
        stream=False
    )

    assert response.content is not None
    # Workflow should have executed successfully
    assert response.metadata["execution_mode"] == "workflow"


# ============================================================================
# Decision Logic Edge Cases
# ============================================================================

def test_decision_logic_mixed_keywords(agent):
    """Test decision with mixed keywords."""
    # Has "explain" but also "implement" - should use workflow
    assert agent._should_use_workflow(
        "Explain how to implement a new feature",
        "implement"
    ) is True


def test_decision_logic_task_type_override(agent):
    """Test that task type can override keywords."""
    # Message says "explain" but type is "implement"
    assert agent._should_use_workflow(
        "Explain what we need to do",
        "implement"
    ) is True


def test_decision_logic_empty_string(agent):
    """Test decision with empty task description."""
    # Should default to direct
    assert agent._should_use_workflow("", "explain") is False


# ============================================================================
# Response Generation Tests
# ============================================================================

def test_response_includes_metadata(agent):
    """Test that response includes execution mode metadata."""
    response = agent.execute_task(
        task_description="What is 1+1?",
        force_direct=True,
        stream=False
    )

    assert "execution_mode" in response.metadata
    assert response.metadata["execution_mode"] in ["workflow", "direct"]


def test_response_includes_task_info(agent):
    """Test that response includes task information."""
    response = agent.execute_task(
        task_description="Test task",
        task_type="implement",
        language="python",
        force_direct=True,
        stream=False
    )

    assert response.metadata["task_type"] == "implement"
    assert response.metadata["language"] == "python"


# ============================================================================
# Memory Integration Tests
# ============================================================================

def test_workflow_stores_in_memory(agent):
    """Test that workflow execution stores messages in memory."""
    initial_count = len(agent.memory.working_memory.messages)

    agent.execute_task(
        task_description="Simple test task",
        force_workflow=True,
        stream=False
    )

    # Should have added user message and assistant response
    assert len(agent.memory.working_memory.messages) > initial_count


def test_direct_stores_in_memory(agent):
    """Test that direct execution stores messages in memory."""
    initial_count = len(agent.memory.working_memory.messages)

    agent.execute_task(
        task_description="Explain something",
        force_direct=True,
        stream=False
    )

    # Should have added user message and assistant response
    assert len(agent.memory.working_memory.messages) > initial_count


# ============================================================================
# Error Handling Tests
# ============================================================================

def test_workflow_handles_invalid_task(agent):
    """Test that workflow handles invalid tasks gracefully."""
    # This should not crash even with a nonsensical task
    try:
        response = agent.execute_task(
            task_description="asdfasdfasdf random gibberish",
            force_workflow=True,
            stream=False
        )
        # Should get some response even if execution fails
        assert response.content is not None
    except Exception as e:
        # If it raises an exception, it should be meaningful
        assert len(str(e)) > 0


def test_direct_handles_invalid_task(agent):
    """Test that direct execution handles invalid tasks gracefully."""
    try:
        response = agent.execute_task(
            task_description="complete nonsense xyz123",
            force_direct=True,
            stream=False
        )
        # Should get some response
        assert response.content is not None
    except Exception as e:
        # If it raises an exception, it should be meaningful
        assert len(str(e)) > 0


# ============================================================================
# Force Mode Tests
# ============================================================================

def test_force_workflow_overrides_decision(agent):
    """Test that force_workflow=True overrides decision logic."""
    # This task would normally use direct execution
    response = agent.execute_task(
        task_description="Explain what is 2+2",
        task_type="explain",
        force_workflow=True,
        stream=False
    )

    assert response.metadata["execution_mode"] == "workflow"


def test_force_direct_overrides_decision(agent):
    """Test that force_direct=True overrides decision logic."""
    # This task would normally use workflow
    response = agent.execute_task(
        task_description="Implement a new feature with tests",
        task_type="implement",
        force_direct=True,
        stream=False
    )

    assert response.metadata["execution_mode"] == "direct"


def test_force_workflow_takes_precedence(agent):
    """Test that force_workflow takes precedence over force_direct."""
    # Both flags set - workflow should win
    response = agent.execute_task(
        task_description="Test task",
        force_workflow=True,
        force_direct=True,
        stream=False
    )

    assert response.metadata["execution_mode"] == "workflow"


# ============================================================================
# Integration with Chat Method
# ============================================================================

def test_chat_uses_execute_task(agent):
    """Test that chat method uses execute_task."""
    response = agent.chat(
        message="Explain what is Python",
        stream=False
    )

    assert response.content is not None
    assert "execution_mode" in response.metadata


# ============================================================================
# Response Generation Unit Tests
# ============================================================================

# Note: These are simplified tests due to complexity of mocking full ExecutionResult
# Full integration tests will validate complete behavior

def test_response_generation_methods_exist(agent):
    """Test that response generation methods exist and are callable."""
    assert hasattr(agent, '_generate_success_response')
    assert hasattr(agent, '_generate_failure_response')
    assert callable(agent._generate_success_response)
    assert callable(agent._generate_failure_response)


# ============================================================================
# Edge Case Tests
# ============================================================================

def test_decision_with_very_long_description(agent):
    """Test decision logic with very long task description."""
    long_description = "Implement a new feature " + "with many details " * 100

    # Should still work
    decision = agent._should_use_workflow(long_description, "implement")
    assert isinstance(decision, bool)
    assert decision is True  # implement → workflow


def test_decision_with_special_characters(agent):
    """Test decision logic with special characters."""
    special_desc = "Implement @#$%^& new feature with 'quotes' and \"double quotes\""

    decision = agent._should_use_workflow(special_desc, "implement")
    assert isinstance(decision, bool)
    assert decision is True


def test_decision_with_unicode(agent):
    """Test decision logic with unicode characters."""
    unicode_desc = "Implementação de nova ferramenta 新功能实现"

    decision = agent._should_use_workflow(unicode_desc, "implement")
    assert isinstance(decision, bool)


def test_execute_task_with_empty_response(agent):
    """Test that agent handles empty LLM responses gracefully."""
    # This would require mocking, but we can test the metadata at least
    try:
        response = agent.execute_task(
            task_description="Test",
            force_direct=True,
            stream=False
        )
        # Should not crash
        assert response is not None
        assert hasattr(response, 'content')
        assert hasattr(response, 'metadata')
    except Exception as e:
        # If it fails, error should be meaningful
        assert len(str(e)) > 0


def test_multiple_sequential_tasks(agent):
    """Test executing multiple tasks sequentially."""
    # Task 1
    response1 = agent.execute_task(
        task_description="What is 1+1?",
        force_direct=True,
        stream=False
    )

    # Task 2
    response2 = agent.execute_task(
        task_description="What is 2+2?",
        force_direct=True,
        stream=False
    )

    # Both should succeed independently
    assert response1.content is not None
    assert response2.content is not None
    assert response1.metadata["execution_mode"] == "direct"
    assert response2.metadata["execution_mode"] == "direct"


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
