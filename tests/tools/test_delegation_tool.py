"""Unit tests for DelegateToSubagentTool."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from src.tools.delegation import DelegateToSubagentTool
from src.tools.base import ToolStatus
from src.subagents import SubAgentManager, SubAgentResult


@pytest.fixture
def temp_agent_dir(tmp_path):
    """Create temporary directory with subagent configs."""
    agents_dir = tmp_path / ".clarity" / "agents"
    agents_dir.mkdir(parents=True)

    # Create test subagent config
    test_agent = agents_dir / "test-agent.md"
    test_agent.write_text("""---
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
def mock_subagent_manager():
    """Create mock SubAgentManager."""
    manager = Mock(spec=SubAgentManager)
    manager.get_available_subagents.return_value = ['test-agent', 'code-reviewer']
    manager.get_subagent_info.return_value = {
        'name': 'test-agent',
        'description': 'Test subagent for unit testing',
        'tools': 'Read, Write',
        'model': 'inherit'
    }
    return manager


class TestDelegationToolInitialization:
    """Test DelegateToSubagentTool initialization."""

    def test_tool_initialization(self, mock_subagent_manager):
        """Test that tool initializes correctly."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        assert tool.name == "delegate_to_subagent"
        assert tool.subagent_manager == mock_subagent_manager
        assert "subagent" in tool.description.lower()

    def test_description_includes_available_subagents(self, mock_subagent_manager):
        """Test that description lists available subagents."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        # Should call get_available_subagents during init
        mock_subagent_manager.get_available_subagents.assert_called_once()

        # Description should include subagents
        assert 'test-agent' in tool.description or 'Test subagent' in tool.description

    def test_description_with_no_subagents(self):
        """Test description when no subagents are available."""
        manager = Mock(spec=SubAgentManager)
        manager.get_available_subagents.return_value = []

        tool = DelegateToSubagentTool(manager)

        assert "No subagents currently available" in tool.description


class TestDelegationToolExecution:
    """Test DelegateToSubagentTool execution."""

    def test_execute_success(self, mock_subagent_manager):
        """Test successful delegation to subagent."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        # Mock successful subagent result
        mock_result = SubAgentResult(
            success=True,
            subagent_name='test-agent',
            output='Test output from subagent',
            execution_time=1.5,
            tool_calls=[
                {'tool': 'read_file', 'success': True},
                {'tool': 'write_file', 'success': True}
            ]
        )
        mock_subagent_manager.delegate.return_value = mock_result

        # Execute tool
        result = tool.execute(subagent='test-agent', task='Test task')

        # Verify delegation was called
        mock_subagent_manager.delegate.assert_called_once_with(
            subagent_name='test-agent',
            task_description='Test task'
        )

        # Verify result
        assert result.status == ToolStatus.SUCCESS
        assert result.output == 'Test output from subagent'
        assert result.metadata['subagent'] == 'test-agent'
        assert result.metadata['execution_time'] == 1.5
        assert result.metadata['tools_used'] == 2

    def test_execute_subagent_not_found(self, mock_subagent_manager):
        """Test execution when subagent doesn't exist."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        # Mock subagent not found
        mock_subagent_manager.delegate.return_value = None

        # Execute tool
        result = tool.execute(subagent='non-existent', task='Test task')

        # Verify error result
        assert result.status == ToolStatus.ERROR
        assert result.output is None
        assert 'not found' in result.error.lower()
        assert 'test-agent' in result.error  # Should list available

    def test_execute_subagent_fails(self, mock_subagent_manager):
        """Test execution when subagent execution fails."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        # Mock failed subagent result
        mock_result = SubAgentResult(
            success=False,
            subagent_name='test-agent',
            output='',
            error='Subagent execution failed',
            execution_time=0.5
        )
        mock_subagent_manager.delegate.return_value = mock_result

        # Execute tool
        result = tool.execute(subagent='test-agent', task='Test task')

        # Verify error result
        assert result.status == ToolStatus.ERROR
        assert result.output is None
        assert 'failed' in result.error.lower()

    def test_execute_empty_subagent_name(self, mock_subagent_manager):
        """Test execution with empty subagent name."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        # Execute with empty name
        result = tool.execute(subagent='', task='Test task')

        # Should not call delegate
        mock_subagent_manager.delegate.assert_not_called()

        # Verify error result
        assert result.status == ToolStatus.ERROR
        assert 'required' in result.error.lower()

    def test_execute_empty_task(self, mock_subagent_manager):
        """Test execution with empty task."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        # Execute with empty task
        result = tool.execute(subagent='test-agent', task='')

        # Should not call delegate
        mock_subagent_manager.delegate.assert_not_called()

        # Verify error result
        assert result.status == ToolStatus.ERROR
        assert 'required' in result.error.lower()

    def test_execute_with_whitespace_trimming(self, mock_subagent_manager):
        """Test that whitespace is trimmed from inputs."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        mock_result = SubAgentResult(
            success=True,
            subagent_name='test-agent',
            output='Output',
            execution_time=1.0
        )
        mock_subagent_manager.delegate.return_value = mock_result

        # Execute with whitespace
        result = tool.execute(
            subagent='  test-agent  ',
            task='  Test task with spaces  '
        )

        # Verify trimmed values were used
        mock_subagent_manager.delegate.assert_called_once_with(
            subagent_name='test-agent',
            task_description='Test task with spaces'
        )

        assert result.status == ToolStatus.SUCCESS


class TestDelegationToolParameters:
    """Test DelegateToSubagentTool parameter schema."""

    def test_get_parameters(self, mock_subagent_manager):
        """Test parameter schema."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        params = tool._get_parameters()

        # Verify schema structure
        assert params['type'] == 'object'
        assert 'properties' in params
        assert 'subagent' in params['properties']
        assert 'task' in params['properties']
        assert params['required'] == ['subagent', 'task']

        # Verify parameter details
        assert params['properties']['subagent']['type'] == 'string'
        assert params['properties']['task']['type'] == 'string'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
