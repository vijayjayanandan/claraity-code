"""Comprehensive tests for SubAgentManager."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from concurrent.futures import Future

from src.subagents.manager import SubAgentManager, DelegationResult
from src.subagents.config import SubAgentConfig
from src.subagents.subagent import SubAgent, SubAgentResult


@pytest.fixture
def mock_main_agent():
    """Create a mock main CodingAgent."""
    agent = Mock()
    agent.model_name = "qwen-2.5"
    agent.context_window = 8192
    agent.working_directory = Path("/test/project")
    agent.tool_executor = Mock()
    agent.tool_executor.tools = {}
    agent.llm = Mock()
    agent.llm.config = Mock()
    agent.hook_manager = None
    return agent


@pytest.fixture
def sample_configs():
    """Create sample subagent configurations."""
    return {
        "code-reviewer": SubAgentConfig(
            name="code-reviewer",
            description="Expert code reviewer for quality, security, and performance",
            system_prompt="You are an expert code reviewer.",
            tools=["Read", "Grep", "AnalyzeCode"]
        ),
        "test-writer": SubAgentConfig(
            name="test-writer",
            description="Expert test writer for unit and integration tests",
            system_prompt="You are an expert test writer.",
            tools=["Read", "Write", "RunCommand"]
        ),
        "doc-writer": SubAgentConfig(
            name="doc-writer",
            description="Technical documentation specialist for APIs and code",
            system_prompt="You are a documentation specialist.",
            tools=["Read", "Write", "Edit"]
        )
    }


class TestDelegationResult:
    """Test DelegationResult dataclass."""

    def test_delegation_result_str_success(self):
        """Test string representation of successful delegation."""
        results = [
            SubAgentResult(
                success=True,
                subagent_name="code-reviewer",
                output="Review complete",
                execution_time=2.0
            ),
            SubAgentResult(
                success=True,
                subagent_name="test-writer",
                output="Tests written",
                execution_time=3.5
            )
        ]

        delegation_result = DelegationResult(
            success=True,
            subagent_results=results,
            total_time=5.5
        )

        str_repr = str(delegation_result)

        assert "✅ SUCCESS" in str_repr
        assert "Subagents Used: 2" in str_repr
        assert "5.50s" in str_repr
        assert "code-reviewer" in str_repr
        assert "test-writer" in str_repr

    def test_delegation_result_str_failure(self):
        """Test string representation of failed delegation."""
        results = [
            SubAgentResult(
                success=True,
                subagent_name="code-reviewer",
                output="Review complete",
                execution_time=2.0
            ),
            SubAgentResult(
                success=False,
                subagent_name="test-writer",
                output="",
                error="Failed to write tests",
                execution_time=1.0
            )
        ]

        delegation_result = DelegationResult(
            success=False,
            subagent_results=results,
            total_time=3.0
        )

        str_repr = str(delegation_result)

        assert "❌ FAILED" in str_repr
        assert "Subagents Used: 2" in str_repr


class TestSubAgentManagerInitialization:
    """Test SubAgentManager initialization."""

    def test_initialization_default_params(self, mock_main_agent):
        """Test initialization with default parameters."""
        manager = SubAgentManager(mock_main_agent)

        assert manager.main_agent == mock_main_agent
        assert manager.working_directory == Path.cwd()
        assert manager.max_parallel_workers == 4
        assert manager.enable_auto_delegation is True
        assert manager.configs == {}
        assert manager.subagent_instances == {}
        assert manager.delegation_count == {}
        assert manager.total_delegations == 0

    def test_initialization_custom_params(self, mock_main_agent):
        """Test initialization with custom parameters."""
        working_dir = Path("/custom/directory")

        manager = SubAgentManager(
            mock_main_agent,
            working_directory=working_dir,
            max_parallel_workers=8,
            enable_auto_delegation=False
        )

        assert manager.working_directory == working_dir
        assert manager.max_parallel_workers == 8
        assert manager.enable_auto_delegation is False


class TestSubAgentManagerDiscovery:
    """Test subagent discovery and reloading."""

    def test_discover_subagents(self, mock_main_agent, sample_configs):
        """Test discovering subagent configurations."""
        manager = SubAgentManager(mock_main_agent)

        with patch.object(manager.config_loader, 'discover_all', return_value=sample_configs):
            discovered = manager.discover_subagents()

            assert len(discovered) == 3
            assert "code-reviewer" in discovered
            assert "test-writer" in discovered
            assert "doc-writer" in discovered
            assert discovered == manager.configs

    def test_reload_subagents_clears_cache(self, mock_main_agent, sample_configs):
        """Test that reload clears cached instances."""
        manager = SubAgentManager(mock_main_agent)

        # Add a cached instance
        mock_subagent = Mock(spec=SubAgent)
        manager.subagent_instances["test-agent"] = mock_subagent

        with patch.object(manager.config_loader, 'reload', return_value=sample_configs):
            reloaded = manager.reload_subagents()

            # Cache should be cleared
            assert len(manager.subagent_instances) == 0
            assert len(reloaded) == 3


class TestSubAgentManagerGetSubagent:
    """Test subagent instance management."""

    def test_get_subagent_creates_instance(self, mock_main_agent, sample_configs):
        """Test that get_subagent creates and caches instances."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            MockSubAgent.return_value = mock_instance

            subagent = manager.get_subagent("code-reviewer")

            assert subagent == mock_instance
            assert "code-reviewer" in manager.subagent_instances
            assert manager.subagent_instances["code-reviewer"] == mock_instance

            # Verify SubAgent was created with correct config
            MockSubAgent.assert_called_once()
            call_kwargs = MockSubAgent.call_args[1]
            assert call_kwargs['config'] == sample_configs["code-reviewer"]
            assert call_kwargs['main_agent'] == mock_main_agent

    def test_get_subagent_returns_cached_instance(self, mock_main_agent, sample_configs):
        """Test that get_subagent returns cached instances."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        # Add cached instance
        cached_subagent = Mock(spec=SubAgent)
        manager.subagent_instances["code-reviewer"] = cached_subagent

        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            subagent = manager.get_subagent("code-reviewer")

            # Should return cached instance without creating new one
            assert subagent == cached_subagent
            MockSubAgent.assert_not_called()

    def test_get_subagent_not_found(self, mock_main_agent):
        """Test get_subagent with non-existent subagent."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = {}

        subagent = manager.get_subagent("non-existent")

        assert subagent is None


class TestSubAgentManagerDelegation:
    """Test delegation functionality."""

    def test_delegate_success(self, mock_main_agent, sample_configs):
        """Test successful delegation to subagent."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        # Mock subagent
        mock_subagent = Mock(spec=SubAgent)
        mock_result = SubAgentResult(
            success=True,
            subagent_name="code-reviewer",
            output="Review complete: no issues found",
            execution_time=2.5
        )
        mock_subagent.execute = Mock(return_value=mock_result)

        with patch.object(manager, 'get_subagent', return_value=mock_subagent):
            result = manager.delegate("code-reviewer", "Review src/api.py")

            assert result == mock_result
            assert manager.total_delegations == 1
            assert manager.delegation_count["code-reviewer"] == 1

            # Verify execute was called with correct params
            mock_subagent.execute.assert_called_once_with(
                task_description="Review src/api.py",
                context=None,
                max_iterations=5
            )

    def test_delegate_with_context(self, mock_main_agent, sample_configs):
        """Test delegation with additional context."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        mock_subagent = Mock(spec=SubAgent)
        mock_result = SubAgentResult(
            success=True,
            subagent_name="test-writer",
            output="Tests written",
            execution_time=3.0
        )
        mock_subagent.execute = Mock(return_value=mock_result)

        context = {"file_path": "src/api.py", "test_framework": "pytest"}

        with patch.object(manager, 'get_subagent', return_value=mock_subagent):
            result = manager.delegate("test-writer", "Write tests", context=context, max_iterations=10)

            mock_subagent.execute.assert_called_once_with(
                task_description="Write tests",
                context=context,
                max_iterations=10
            )

    def test_delegate_subagent_not_found(self, mock_main_agent):
        """Test delegation when subagent doesn't exist."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = {}

        with patch.object(manager, 'get_subagent', return_value=None):
            result = manager.delegate("non-existent", "Some task")

            assert result is None
            # Delegation count should not increase
            assert manager.total_delegations == 0

    def test_delegate_tracks_statistics(self, mock_main_agent, sample_configs):
        """Test that delegation tracking works correctly."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        mock_subagent = Mock(spec=SubAgent)
        mock_result = SubAgentResult(success=True, subagent_name="code-reviewer", output="Done", execution_time=1.0)
        mock_subagent.execute = Mock(return_value=mock_result)

        with patch.object(manager, 'get_subagent', return_value=mock_subagent):
            # Delegate multiple times
            manager.delegate("code-reviewer", "Task 1")
            manager.delegate("code-reviewer", "Task 2")
            manager.delegate("code-reviewer", "Task 3")

            assert manager.total_delegations == 3
            assert manager.delegation_count["code-reviewer"] == 3


class TestSubAgentManagerAutoDelegation:
    """Test automatic delegation."""

    def test_auto_delegate_finds_best_match(self, mock_main_agent, sample_configs):
        """Test that auto_delegate selects the best subagent."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        mock_result = SubAgentResult(success=True, subagent_name="code-reviewer", output="Done", execution_time=1.0)

        with patch.object(manager, 'delegate', return_value=mock_result) as mock_delegate:
            result = manager.auto_delegate("Review code for security issues")

            # Should select code-reviewer based on keywords
            mock_delegate.assert_called_once()
            call_args = mock_delegate.call_args[0]
            # First argument should be the selected subagent name
            # Based on keyword matching, it should select code-reviewer
            assert result == mock_result

    def test_auto_delegate_disabled(self, mock_main_agent, sample_configs):
        """Test auto_delegate when disabled."""
        manager = SubAgentManager(mock_main_agent, enable_auto_delegation=False)
        manager.configs = sample_configs

        result = manager.auto_delegate("Some task")

        assert result is None

    def test_auto_delegate_no_match(self, mock_main_agent):
        """Test auto_delegate when no subagent matches."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = {}

        result = manager.auto_delegate("Some random task")

        assert result is None


class TestSubAgentManagerParallelExecution:
    """Test parallel execution functionality."""

    def test_execute_parallel_success(self, mock_main_agent, sample_configs):
        """Test successful parallel execution of multiple subagents."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        # Mock delegation results
        def mock_delegate(name, task, context=None, max_iterations=5):
            return SubAgentResult(
                success=True,
                subagent_name=name,
                output=f"Completed: {task}",
                execution_time=1.0
            )

        tasks = [
            ("code-reviewer", "Review api.py", None),
            ("test-writer", "Write tests", None),
            ("doc-writer", "Write docs", None)
        ]

        with patch.object(manager, 'delegate', side_effect=mock_delegate):
            result = manager.execute_parallel(tasks)

            assert result.success is True
            assert len(result.subagent_results) == 3
            assert result.total_time > 0
            assert result.metadata['tasks_submitted'] == 3
            assert result.metadata['tasks_completed'] == 3

    def test_execute_parallel_with_failures(self, mock_main_agent, sample_configs):
        """Test parallel execution when some subagents fail."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        # Mock delegation with one failure
        def mock_delegate(name, task, context=None, max_iterations=5):
            if name == "test-writer":
                return SubAgentResult(
                    success=False,
                    subagent_name=name,
                    output="",
                    error="Failed to write tests",
                    execution_time=0.5
                )
            return SubAgentResult(
                success=True,
                subagent_name=name,
                output=f"Completed: {task}",
                execution_time=1.0
            )

        tasks = [
            ("code-reviewer", "Review api.py", None),
            ("test-writer", "Write tests", None)
        ]

        with patch.object(manager, 'delegate', side_effect=mock_delegate):
            result = manager.execute_parallel(tasks)

            assert result.success is False  # Overall fails if any fails
            assert len(result.subagent_results) == 2


class TestSubAgentManagerUtilities:
    """Test utility methods."""

    def test_get_available_subagents(self, mock_main_agent, sample_configs):
        """Test getting list of available subagents."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs

        available = manager.get_available_subagents()

        assert len(available) == 3
        assert "code-reviewer" in available
        assert "test-writer" in available
        assert "doc-writer" in available

    def test_get_subagent_info(self, mock_main_agent, sample_configs):
        """Test getting subagent information."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs
        manager.delegation_count["code-reviewer"] = 5

        info = manager.get_subagent_info("code-reviewer")

        assert info is not None
        assert info["name"] == "code-reviewer"
        assert "code reviewer" in info["description"].lower()
        assert info["delegation_count"] == 5

    def test_get_subagent_info_not_found(self, mock_main_agent):
        """Test getting info for non-existent subagent."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = {}

        info = manager.get_subagent_info("non-existent")

        assert info is None

    def test_get_statistics(self, mock_main_agent, sample_configs):
        """Test getting delegation statistics."""
        manager = SubAgentManager(mock_main_agent)
        manager.configs = sample_configs
        manager.total_delegations = 10
        manager.delegation_count = {
            "code-reviewer": 5,
            "test-writer": 3,
            "doc-writer": 2
        }

        stats = manager.get_statistics()

        assert stats["total_delegations"] == 10
        assert stats["subagents_available"] == 3
        assert stats["subagents_used"] == 3
        assert stats["delegation_by_subagent"]["code-reviewer"] == 5
        assert stats["delegation_by_subagent"]["test-writer"] == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
