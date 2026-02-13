"""End-to-end integration tests for subagent system."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from src.subagents import SubAgentManager, SubAgentConfig, SubAgent, SubAgentResult
from src.llm import LLMBackendType, LLMResponse


@pytest.fixture
def temp_agent_configs(tmp_path):
    """Create temporary agent configuration files."""
    agents_dir = tmp_path / ".clarity" / "agents"
    agents_dir.mkdir(parents=True)

    # Code reviewer agent
    reviewer_config = agents_dir / "code-reviewer.md"
    reviewer_config.write_text("""---
name: code-reviewer
description: Expert code reviewer for quality and security
tools: Read, Grep, AnalyzeCode
model: inherit
---

# Code Reviewer

You are an expert code reviewer specializing in:
- Security vulnerabilities
- Code quality and best practices
- Performance optimization
""")

    # Test writer agent
    test_writer_config = agents_dir / "test-writer.md"
    test_writer_config.write_text("""---
name: test-writer
description: Expert test writer for unit and integration tests
tools: Read, Write, RunCommand
model: inherit
---

# Test Writer

You are an expert at writing comprehensive tests:
- Unit tests with pytest
- Integration tests
- Edge case coverage
""")

    return tmp_path


@pytest.fixture
def mock_main_agent():
    """Create a fully mocked main agent."""
    agent = Mock()
    agent.model_name = "qwen-2.5"
    agent.context_window = 8192
    agent.working_directory = Path("/test/project")
    agent.hook_manager = None

    # Mock LLM
    agent.llm = Mock()
    agent.llm.config = Mock()
    agent.llm.config.backend_type = LLMBackendType.OPENAI
    agent.llm.config.model_name = "qwen-2.5"
    agent.llm.config.base_url = "http://localhost:8000"
    agent.llm.config.context_window = 8192
    agent.llm.api_key = "test-key"
    agent.llm.api_key_env = "OPENAI_API_KEY"

    # Mock tool executor
    agent.tool_executor = Mock()
    agent.tool_executor.tools = {
        "read_file": Mock(),
        "write_file": Mock(),
        "grep": Mock(),
        "analyze_code": Mock(),
        "run_command": Mock()
    }

    return agent


class TestEndToEndWorkflow:
    """Test complete end-to-end workflows."""

    def test_discover_and_delegate_workflow(self, mock_main_agent, temp_agent_configs):
        """Test full workflow: discover subagents → delegate task → get result."""
        # Initialize manager with temp directory
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        # Discover subagents
        configs = manager.discover_subagents()

        assert len(configs) == 2
        assert "code-reviewer" in configs
        assert "test-writer" in configs

        # Mock SubAgent execution
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            mock_result = SubAgentResult(
                success=True,
                subagent_name="code-reviewer",
                output="Code review complete: no issues found",
                execution_time=2.0,
                tool_calls=[{"tool": "read_file", "success": True}]
            )
            mock_instance.execute = Mock(return_value=mock_result)
            MockSubAgent.return_value = mock_instance

            # Delegate to subagent
            result = manager.delegate(
                "code-reviewer",
                "Review src/api.py for security issues"
            )

            assert result is not None
            assert result.success is True
            assert result.subagent_name == "code-reviewer"
            assert "Code review complete" in result.output
            assert manager.total_delegations == 1

    def test_auto_delegation_workflow(self, mock_main_agent, temp_agent_configs):
        """Test auto-delegation selecting the best subagent."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs,
            enable_auto_delegation=True
        )

        # Discover subagents
        manager.discover_subagents()

        # Mock SubAgent execution
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            mock_result = SubAgentResult(
                success=True,
                subagent_name="test-writer",
                output="Tests written successfully",
                execution_time=3.0
            )
            mock_instance.execute = Mock(return_value=mock_result)
            MockSubAgent.return_value = mock_instance

            # Auto-delegate - should select test-writer based on keywords
            result = manager.auto_delegate(
                "Write comprehensive unit tests for the authentication module"
            )

            assert result is not None
            assert result.success is True
            # Should have selected test-writer based on "tests" keyword
            assert manager.total_delegations == 1

    def test_parallel_execution_workflow(self, mock_main_agent, temp_agent_configs):
        """Test parallel execution of multiple subagents."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs,
            max_parallel_workers=2
        )

        # Discover subagents
        manager.discover_subagents()

        # Mock SubAgent execution
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            def create_mock_instance(config, **kwargs):
                mock_instance = Mock(spec=SubAgent)

                def mock_execute(task_description, context=None, max_iterations=5):
                    return SubAgentResult(
                        success=True,
                        subagent_name=config.name,
                        output=f"Completed: {task_description}",
                        execution_time=1.5
                    )

                mock_instance.execute = mock_execute
                return mock_instance

            MockSubAgent.side_effect = create_mock_instance

            # Execute multiple tasks in parallel
            tasks = [
                ("code-reviewer", "Review api.py", None),
                ("test-writer", "Write tests for api.py", None)
            ]

            result = manager.execute_parallel(tasks)

            assert result.success is True
            assert len(result.subagent_results) == 2
            assert result.metadata['tasks_submitted'] == 2
            assert result.metadata['tasks_completed'] == 2
            assert manager.total_delegations == 2

    def test_reload_workflow(self, mock_main_agent, temp_agent_configs):
        """Test reload workflow: discover → reload → delegate again."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        # Initial discovery
        configs1 = manager.discover_subagents()
        assert len(configs1) == 2

        # Create a cached instance
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            MockSubAgent.return_value = mock_instance

            subagent = manager.get_subagent("code-reviewer")
            assert "code-reviewer" in manager.subagent_instances

            # Reload - should clear cache
            configs2 = manager.reload_subagents()

            assert len(configs2) == 2
            assert len(manager.subagent_instances) == 0  # Cache cleared


class TestErrorHandling:
    """Test error handling in E2E workflows."""

    def test_delegation_to_nonexistent_subagent(self, mock_main_agent, temp_agent_configs):
        """Test graceful handling of delegation to non-existent subagent."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        manager.discover_subagents()

        # Try to delegate to non-existent subagent
        result = manager.delegate("non-existent-agent", "Some task")

        assert result is None
        assert manager.total_delegations == 0

    def test_subagent_execution_failure(self, mock_main_agent, temp_agent_configs):
        """Test handling of subagent execution failures."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        manager.discover_subagents()

        # Mock SubAgent that fails
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            mock_result = SubAgentResult(
                success=False,
                subagent_name="code-reviewer",
                output="",
                error="Failed to complete code review",
                execution_time=0.5
            )
            mock_instance.execute = Mock(return_value=mock_result)
            MockSubAgent.return_value = mock_instance

            # Delegate to subagent
            result = manager.delegate("code-reviewer", "Review api.py")

            assert result is not None
            assert result.success is False
            assert result.error == "Failed to complete code review"
            assert manager.total_delegations == 1

    def test_parallel_execution_with_partial_failures(self, mock_main_agent, temp_agent_configs):
        """Test parallel execution when some subagents fail."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        manager.discover_subagents()

        # Mock SubAgent execution with one failure
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            def create_mock_instance(config, **kwargs):
                mock_instance = Mock(spec=SubAgent)

                def mock_execute(task_description, context=None, max_iterations=5):
                    # test-writer fails
                    if config.name == "test-writer":
                        return SubAgentResult(
                            success=False,
                            subagent_name=config.name,
                            output="",
                            error="Test generation failed",
                            execution_time=0.5
                        )
                    # code-reviewer succeeds
                    return SubAgentResult(
                        success=True,
                        subagent_name=config.name,
                        output=f"Completed: {task_description}",
                        execution_time=2.0
                    )

                mock_instance.execute = mock_execute
                return mock_instance

            MockSubAgent.side_effect = create_mock_instance

            # Execute tasks
            tasks = [
                ("code-reviewer", "Review api.py", None),
                ("test-writer", "Write tests", None)
            ]

            result = manager.execute_parallel(tasks)

            # Overall should fail if any subagent fails
            assert result.success is False
            assert len(result.subagent_results) == 2
            # One success, one failure
            successes = [r for r in result.subagent_results if r.success]
            failures = [r for r in result.subagent_results if not r.success]
            assert len(successes) == 1
            assert len(failures) == 1


class TestStatistics:
    """Test statistics tracking across E2E workflows."""

    def test_statistics_tracking_across_delegations(self, mock_main_agent, temp_agent_configs):
        """Test that statistics are correctly tracked across multiple delegations."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        manager.discover_subagents()

        # Mock SubAgent execution
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            mock_result = SubAgentResult(
                success=True,
                subagent_name="code-reviewer",
                output="Done",
                execution_time=1.0
            )
            mock_instance.execute = Mock(return_value=mock_result)
            MockSubAgent.return_value = mock_instance

            # Perform multiple delegations
            manager.delegate("code-reviewer", "Task 1")
            manager.delegate("code-reviewer", "Task 2")
            manager.delegate("test-writer", "Task 3")

            # Check statistics
            stats = manager.get_statistics()

            assert stats['total_delegations'] == 3
            assert stats['subagents_available'] == 2
            assert stats['subagents_used'] == 2
            assert stats['delegation_by_subagent']['code-reviewer'] == 2
            assert stats['delegation_by_subagent']['test-writer'] == 1


class TestContextPassing:
    """Test context passing through the system."""

    def test_context_passed_to_subagent(self, mock_main_agent, temp_agent_configs):
        """Test that additional context is passed correctly to subagents."""
        manager = SubAgentManager(
            mock_main_agent,
            working_directory=temp_agent_configs
        )

        manager.discover_subagents()

        # Mock SubAgent execution
        with patch('src.subagents.manager.SubAgent') as MockSubAgent:
            mock_instance = Mock(spec=SubAgent)
            mock_result = SubAgentResult(
                success=True,
                subagent_name="code-reviewer",
                output="Review complete",
                execution_time=1.0
            )
            mock_instance.execute = Mock(return_value=mock_result)
            MockSubAgent.return_value = mock_instance

            # Delegate with context
            context = {
                "file_path": "src/api.py",
                "focus_areas": ["security", "performance"],
                "previous_issues": ["SQL injection vulnerability"]
            }

            result = manager.delegate(
                "code-reviewer",
                "Review the API file",
                context=context,
                max_iterations=10
            )

            # Verify context was passed to subagent.execute()
            mock_instance.execute.assert_called_once_with(
                task_description="Review the API file",
                context=context,
                max_iterations=10
            )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
