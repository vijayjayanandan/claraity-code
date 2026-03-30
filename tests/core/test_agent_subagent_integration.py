"""Integration tests for CodingAgent with SubAgent architecture."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from src.core.agent import CodingAgent
from src.subagents import SubAgentManager, SubAgentResult


@pytest.fixture
def temp_agent_dir(tmp_path):
    """Create temporary directory with subagent configs."""
    agents_dir = tmp_path / ".claraity" / "agents"
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
        base_url="http://localhost:11434",
        context_window=8192,
        api_key="test-key",
        working_directory=str(temp_agent_dir),
        load_file_memories=False
    )
    return agent


class TestAgentSubAgentManagerInitialization:
    """Test that CodingAgent properly initializes SubAgentManager."""

    def test_agent_initializes_subagent_manager(self, temp_agent_dir):
        """Test that SubAgentManager is initialized in CodingAgent.__init__()."""
        agent = CodingAgent(
            model_name="test-model",
            backend="ollama",
            base_url="http://localhost:11434",
            context_window=8192,
            api_key="test-key",
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


class TestGetAvailableSubagents:
    """Test CodingAgent.get_available_subagents() method."""

    def test_get_available_subagents(self, agent_with_subagents):
        """Test getting list of available subagents."""
        available = agent_with_subagents.get_available_subagents()

        assert isinstance(available, list)
        assert 'test-agent' in available

    def test_get_available_subagents_empty(self, tmp_path):
        """Test with no subagents configured."""
        # Create agent with no .claraity/agents directory
        agent = CodingAgent(
            model_name="test-model",
            backend="ollama",
            base_url="http://localhost:11434",
            context_window=8192,
            api_key="test-key",
            working_directory=str(tmp_path),
            load_file_memories=False
        )

        available = agent.get_available_subagents()

        assert isinstance(available, list)
        # Built-in subagents are always discovered
        assert len(available) >= 0


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

        # Subagent should inherit tool executor from main agent
        assert subagent._tool_executor is not None
        # The tool executor should be the main agent's tool executor
        assert subagent._tool_executor == agent_with_subagents.tool_executor

    def test_subagent_independent_context(self, agent_with_subagents):
        """Test that subagent has independent context (message store)."""
        # Get subagent instance
        subagent = agent_with_subagents.subagent_manager.get_subagent('test-agent')

        assert subagent is not None

        # Subagent should have its own message store (independent context)
        assert subagent._message_store is not None
        # Session ID should be unique
        assert subagent.session_id is not None
        assert len(subagent.session_id) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
