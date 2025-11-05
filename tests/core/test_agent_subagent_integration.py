"""Integration tests for CodingAgent with SubAgent architecture."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from src.core.agent import CodingAgent
from src.subagents import SubAgentManager, SubAgentResult


@pytest.fixture
def temp_agent_dir(tmp_path):
    """Create temporary directory with subagent configs."""
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)

    # Create a simple test subagent config
    test_agent_config = agents_dir / "test-agent.md"
    test_agent_config.write_text("""---
name: test-agent
description: Test subagent for unit testing
tools: Read, Write
model: inherit
---

# Test Agent

You are a test subagent.
""")

    return tmp_path


@pytest.fixture
def agent_with_subagents(temp_agent_dir):
    """Create CodingAgent with subagent support in temp directory."""
    agent = CodingAgent(
        model_name="test-model",
        backend="ollama",
        working_directory=str(temp_agent_dir),
        load_file_memories=False
    )
    return agent


class TestAgentSubAgentManagerInitialization:
    """Test that CodingAgent properly initializes SubAgentManager."""

    def test_agent_initializes_subagent_manager(self, temp_agent_dir):
        """Test that SubAgentManager is initialized in CodingAgent.__init__()."""
        agent = CodingAgent(
            working_directory=str(temp_agent_dir),
            load_file_memories=False
        )

        # Check SubAgentManager exists
        assert hasattr(agent, 'subagent_manager')
        assert isinstance(agent.subagent_manager, SubAgentManager)

        # Check SubAgentManager is configured correctly
        assert agent.subagent_manager.main_agent == agent
        assert agent.subagent_manager.working_directory == temp_agent_dir
        assert agent.subagent_manager.enable_auto_delegation is True

    def test_agent_discovers_subagents_on_init(self, agent_with_subagents):
        """Test that subagents are discovered during initialization."""
        # Should have discovered the test-agent
        available = agent_with_subagents.get_available_subagents()

        assert isinstance(available, list)
        assert 'test-agent' in available


class TestDelegateToSubagent:
    """Test CodingAgent.delegate_to_subagent() method."""

    def test_delegate_to_subagent_success(self, agent_with_subagents):
        """Test successful delegation to a subagent."""
        # Mock the subagent execution
        mock_result = SubAgentResult(
            success=True,
            subagent_name='test-agent',
            output='Test output from subagent',
            execution_time=1.5
        )

        with patch.object(
            agent_with_subagents.subagent_manager,
            'delegate',
            return_value=mock_result
        ) as mock_delegate:
            result = agent_with_subagents.delegate_to_subagent(
                subagent_name='test-agent',
                task_description='Test task'
            )

            # Verify delegation was called
            mock_delegate.assert_called_once_with(
                subagent_name='test-agent',
                task_description='Test task',
                context=None,
                max_iterations=5
            )

            # Verify result
            assert result.success is True
            assert result.subagent_name == 'test-agent'
            assert result.output == 'Test output from subagent'

    def test_delegate_to_subagent_not_found(self, agent_with_subagents):
        """Test delegation to non-existent subagent."""
        result = agent_with_subagents.delegate_to_subagent(
            subagent_name='non-existent',
            task_description='Test task'
        )

        # Should return error result
        assert result.success is False
        assert result.subagent_name == 'non-existent'
        assert 'not found' in result.error.lower()
        assert 'test-agent' in result.error  # Should list available

    def test_delegate_with_context(self, agent_with_subagents):
        """Test delegation with additional context."""
        context = {'key': 'value'}
        mock_result = SubAgentResult(
            success=True,
            subagent_name='test-agent',
            output='Output',
            execution_time=1.0
        )

        with patch.object(
            agent_with_subagents.subagent_manager,
            'delegate',
            return_value=mock_result
        ):
            result = agent_with_subagents.delegate_to_subagent(
                subagent_name='test-agent',
                task_description='Task',
                context=context,
                max_iterations=3
            )

            assert result.success is True

    def test_delegate_emits_subagent_stop_hook(self, agent_with_subagents):
        """Test that SubagentStop hook is emitted after successful delegation."""
        # Add mock hook manager
        agent_with_subagents.hook_manager = Mock()

        mock_result = SubAgentResult(
            success=True,
            subagent_name='test-agent',
            output='Output',
            execution_time=2.5
        )

        with patch.object(
            agent_with_subagents.subagent_manager,
            'delegate',
            return_value=mock_result
        ):
            agent_with_subagents.delegate_to_subagent(
                subagent_name='test-agent',
                task_description='Task'
            )

            # Verify hook was emitted
            agent_with_subagents.hook_manager.emit_subagent_stop.assert_called_once_with(
                subagent_name='test-agent',
                result='Output',
                duration=2.5
            )

    def test_delegate_hook_error_doesnt_crash(self, agent_with_subagents):
        """Test that hook errors don't crash delegation."""
        # Add mock hook manager that raises exception
        agent_with_subagents.hook_manager = Mock()
        agent_with_subagents.hook_manager.emit_subagent_stop.side_effect = Exception("Hook error")

        mock_result = SubAgentResult(
            success=True,
            subagent_name='test-agent',
            output='Output',
            execution_time=1.0
        )

        with patch.object(
            agent_with_subagents.subagent_manager,
            'delegate',
            return_value=mock_result
        ):
            # Should not raise exception
            result = agent_with_subagents.delegate_to_subagent(
                subagent_name='test-agent',
                task_description='Task'
            )

            assert result.success is True


class TestGetAvailableSubagents:
    """Test CodingAgent.get_available_subagents() method."""

    def test_get_available_subagents(self, agent_with_subagents):
        """Test getting list of available subagents."""
        available = agent_with_subagents.get_available_subagents()

        assert isinstance(available, list)
        assert 'test-agent' in available

    def test_get_available_subagents_empty(self, tmp_path):
        """Test with no subagents configured."""
        # Create agent with no .claude/agents directory
        agent = CodingAgent(
            working_directory=str(tmp_path),
            load_file_memories=False
        )

        available = agent.get_available_subagents()

        assert isinstance(available, list)
        assert len(available) == 0


class TestSubagentIntegration:
    """Test complete integration scenarios."""

    def test_subagent_inherits_llm_backend(self, agent_with_subagents):
        """Test that subagent inherits LLM backend from main agent."""
        # Get subagent instance
        subagent = agent_with_subagents.subagent_manager.get_subagent('test-agent')

        assert subagent is not None
        # Should inherit backend type
        assert subagent.llm.config.backend_type == agent_with_subagents.llm.config.backend_type

    def test_subagent_inherits_hook_manager(self, agent_with_subagents):
        """Test that subagent inherits hook manager from main agent."""
        # Add hook manager to main agent
        agent_with_subagents.hook_manager = Mock()

        # Recreate subagent manager to pick up hook manager
        from src.subagents import SubAgentManager
        agent_with_subagents.subagent_manager = SubAgentManager(
            main_agent=agent_with_subagents,
            working_directory=agent_with_subagents.working_directory
        )
        agent_with_subagents.subagent_manager.discover_subagents()

        # Get subagent instance
        subagent = agent_with_subagents.subagent_manager.get_subagent('test-agent')

        # Tool executor should have hook manager
        assert subagent.tool_executor.hook_manager == agent_with_subagents.hook_manager

    def test_subagent_independent_context(self, agent_with_subagents):
        """Test that subagent has independent context (memory)."""
        # Get subagent instance
        subagent = agent_with_subagents.subagent_manager.get_subagent('test-agent')

        assert subagent is not None

        # Memory should be different instances
        assert subagent.memory is not agent_with_subagents.memory
        # But should have same structure
        assert hasattr(subagent.memory, 'working_memory')
        assert hasattr(subagent.memory, 'episodic_memory')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
