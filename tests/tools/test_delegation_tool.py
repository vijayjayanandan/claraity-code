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
    agents_dir = tmp_path / ".claraity" / "agents"
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

    def test_sync_execute_returns_error_stub(self, mock_subagent_manager):
        """Sync execute() returns error directing to async path."""
        tool = DelegateToSubagentTool(mock_subagent_manager)

        result = tool.execute(subagent='test-agent', task='Test task')

        assert result.status == ToolStatus.ERROR
        assert 'async' in result.error.lower()


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
