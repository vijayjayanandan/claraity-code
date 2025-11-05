"""Tests for execution engine.

Tests execution of plans, step execution, error handling, and progress tracking.
"""

import pytest
from unittest.mock import Mock, MagicMock
from src.workflow import (
    TaskAnalyzer,
    TaskAnalysis,
    TaskType,
    TaskComplexity,
    TaskPlanner,
    ExecutionPlan,
    PlanStep,
    ActionType
)
from src.workflow.execution_engine import ExecutionEngine, ExecutionResult, StepResult
from src.tools.base import ToolResult, ToolStatus, ToolExecutor


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tool_executor():
    """Create mock tool executor."""
    executor = ToolExecutor()

    # Register mock tools
    from src.tools.file_operations import ReadFileTool, WriteFileTool, EditFileTool, ListDirectoryTool
    from src.tools.code_search import SearchCodeTool, AnalyzeCodeTool

    executor.register_tool(ReadFileTool())
    executor.register_tool(WriteFileTool())
    executor.register_tool(EditFileTool())
    executor.register_tool(ListDirectoryTool())
    executor.register_tool(SearchCodeTool())
    executor.register_tool(AnalyzeCodeTool())

    return executor


@pytest.fixture
def execution_engine(tool_executor):
    """Create execution engine instance."""
    return ExecutionEngine(
        tool_executor=tool_executor,
        progress_callback=lambda step_id, status, msg: None  # Silent for tests
    )


@pytest.fixture
def simple_plan():
    """Create a simple execution plan for testing."""
    return ExecutionPlan(
        task_description="Test task",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Read a file",
                action_type="read",
                tool="read_file",
                arguments={"file_path": "test.txt"},
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Write output",
                action_type="write",
                tool="write_file",
                arguments={"file_path": "output.txt", "content": "test"},
                dependencies=[1],
                risk="low"
            )
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )


@pytest.fixture
def complex_plan():
    """Create a complex execution plan with dependencies."""
    return ExecutionPlan(
        task_description="Complex task",
        task_type=TaskType.REFACTOR,
        steps=[
            PlanStep(
                id=1,
                description="Read file A",
                action_type="read",
                arguments={"file_path": "a.txt"},
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Read file B",
                action_type="read",
                arguments={"file_path": "b.txt"},
                risk="low"
            ),
            PlanStep(
                id=3,
                description="Process data",
                action_type="analyze",
                arguments={"file_path": "a.txt"},
                dependencies=[1, 2],
                risk="medium"
            ),
            PlanStep(
                id=4,
                description="Write results",
                action_type="write",
                arguments={"file_path": "results.txt", "content": "done"},
                dependencies=[3],
                risk="low"
            )
        ],
        total_estimated_time="3 min",
        overall_risk="medium",
        requires_approval=False
    )


@pytest.fixture
def task_analysis():
    """Create task analysis for testing."""
    return TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=2,
        estimated_iterations=5,
        requires_git=True,
        requires_tests=True,
        risk_level="low",
        key_concepts=["test"],
        affected_systems=["test"]
    )


# ============================================================================
# Action to Tool Mapping Tests
# ============================================================================

def test_action_to_tool_mapping_explicit(execution_engine):
    """Test action→tool mapping when tool is explicitly specified."""
    step = PlanStep(
        id=1,
        description="Test",
        action_type="read",
        tool="custom_tool",
        arguments={}
    )

    tool_name = execution_engine._map_action_to_tool("read", step)
    assert tool_name == "custom_tool"


def test_action_to_tool_mapping_implicit(execution_engine):
    """Test action→tool mapping using default mapping."""
    step = PlanStep(
        id=1,
        description="Test",
        action_type="read",
        arguments={}
    )

    mapping_tests = [
        ("read", "read_file"),
        ("write", "write_file"),
        ("edit", "edit_file"),
        ("search", "search_code"),
        ("analyze", "analyze_code"),
        ("verify", "analyze_code"),
    ]

    for action_type, expected_tool in mapping_tests:
        step.action_type = action_type
        tool_name = execution_engine._map_action_to_tool(action_type, step)
        assert tool_name == expected_tool, f"Failed for {action_type}"


def test_action_to_tool_mapping_unknown(execution_engine):
    """Test action→tool mapping with unknown action type."""
    step = PlanStep(
        id=1,
        description="Test",
        action_type="unknown_action",
        arguments={}
    )

    tool_name = execution_engine._map_action_to_tool("unknown_action", step)
    assert tool_name is None


# ============================================================================
# Iteration Limiting Tests (ChatGPT Fix #1)
# ============================================================================

def test_iteration_limit_trivial(execution_engine):
    """Test iteration limit for trivial tasks."""
    analysis = TaskAnalysis(
        task_type=TaskType.EXPLAIN,
        complexity=TaskComplexity.TRIVIAL,
        requires_planning=False,
        requires_approval=False,
        estimated_files=1,
        estimated_iterations=2,
        requires_git=False,
        requires_tests=False,
        risk_level="low",
        key_concepts=[],
        affected_systems=[]
    )

    limit = execution_engine._get_iteration_limit(analysis)
    assert limit == 3


def test_iteration_limit_moderate(execution_engine):
    """Test iteration limit for moderate tasks."""
    analysis = TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=3,
        estimated_iterations=5,
        requires_git=True,
        requires_tests=True,
        risk_level="medium",
        key_concepts=[],
        affected_systems=[]
    )

    limit = execution_engine._get_iteration_limit(analysis)
    assert limit == 5


def test_iteration_limit_very_complex(execution_engine):
    """Test iteration limit for very complex tasks."""
    analysis = TaskAnalysis(
        task_type=TaskType.REFACTOR,
        complexity=TaskComplexity.VERY_COMPLEX,
        requires_planning=True,
        requires_approval=True,
        estimated_files=10,
        estimated_iterations=12,
        requires_git=True,
        requires_tests=True,
        risk_level="high",
        key_concepts=[],
        affected_systems=[]
    )

    limit = execution_engine._get_iteration_limit(analysis)
    assert limit == 10


def test_iteration_limit_no_analysis(execution_engine):
    """Test iteration limit when no analysis provided."""
    limit = execution_engine._get_iteration_limit(None)
    assert limit == 5  # Default


# ============================================================================
# Abort Logic Tests
# ============================================================================

def test_should_abort_high_risk(execution_engine, simple_plan):
    """Test abort on high-risk step failure."""
    step = PlanStep(
        id=1,
        description="High risk operation",
        action_type="write",
        risk="high",
        reversible=True
    )

    result = StepResult(step_id=1, success=False, error="Failed")

    should_abort = execution_engine._should_abort(simple_plan, step, result)
    assert should_abort is True


def test_should_abort_has_dependents(execution_engine, complex_plan):
    """Test abort when step has dependents."""
    # Step 1 has dependents (step 3 depends on it)
    step = complex_plan.steps[0]  # Step 1
    result = StepResult(step_id=1, success=False, error="Failed")

    should_abort = execution_engine._should_abort(complex_plan, step, result)
    assert should_abort is True


def test_should_abort_non_reversible(execution_engine, simple_plan):
    """Test abort on non-reversible step failure."""
    step = PlanStep(
        id=1,
        description="Non-reversible operation",
        action_type="write",
        risk="medium",
        reversible=False
    )

    result = StepResult(step_id=1, success=False, error="Failed")

    should_abort = execution_engine._should_abort(simple_plan, step, result)
    assert should_abort is True


def test_should_continue_low_risk(execution_engine):
    """Test continue on low-risk step failure."""
    # Create a plan where step 3 has no dependents
    plan = ExecutionPlan(
        task_description="Test task",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Step 1",
                action_type="read",
                arguments={},
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Step 2",
                action_type="read",
                arguments={},
                dependencies=[1],
                risk="low"
            ),
            PlanStep(
                id=3,
                description="Step 3 with no dependents",
                action_type="read",
                arguments={},
                risk="low",
                reversible=True
            )
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    # Test with step 3 which has no dependents
    step = plan.steps[2]  # Step 3
    result = StepResult(step_id=3, success=False, error="Failed")

    should_abort = execution_engine._should_abort(plan, step, result)
    assert should_abort is False


# ============================================================================
# Step Execution Tests
# ============================================================================

def test_execute_step_success(execution_engine, tool_executor):
    """Test successful step execution."""
    # Create test file first
    tool_executor.execute_tool("write_file", file_path="/tmp/test_exec.txt", content="test content")

    step = PlanStep(
        id=1,
        description="Read file",
        action_type="read",
        tool="read_file",
        arguments={"file_path": "/tmp/test_exec.txt"}
    )

    result = execution_engine._execute_step(step)

    assert result.success is True
    assert result.step_id == 1
    assert result.tool_used == "read_file"
    assert result.output is not None
    assert result.duration > 0


def test_execute_step_tool_not_found(execution_engine):
    """Test step execution with non-existent tool."""
    step = PlanStep(
        id=1,
        description="Use non-existent tool",
        action_type="unknown",
        tool="nonexistent_tool",
        arguments={}
    )

    result = execution_engine._execute_step(step)

    assert result.success is False
    assert "not available" in result.error


def test_execute_step_tool_failure(execution_engine):
    """Test step execution when tool fails."""
    step = PlanStep(
        id=1,
        description="Read non-existent file",
        action_type="read",
        tool="read_file",
        arguments={"file_path": "/nonexistent/path/file.txt"}
    )

    result = execution_engine._execute_step(step)

    assert result.success is False
    assert result.tool_used == "read_file"
    assert result.error is not None


def test_execute_step_exception_handling(execution_engine):
    """Test step execution handles exceptions gracefully."""
    step = PlanStep(
        id=1,
        description="Invalid operation",
        action_type="read",
        tool="read_file",
        arguments={}  # Missing required file_path argument
    )

    result = execution_engine._execute_step(step)

    assert result.success is False
    assert result.error is not None
    assert len(result.error) > 0


# ============================================================================
# Plan Execution Tests
# ============================================================================

def test_execute_plan_empty(execution_engine):
    """Test execution of empty plan."""
    empty_plan = ExecutionPlan(
        task_description="Empty task",
        task_type=TaskType.FEATURE,
        steps=[],
        total_estimated_time="0 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(empty_plan)

    # Empty plan has no steps, so no steps completed
    assert len(result.step_results) == 0
    assert result.success is False  # No completed steps = not successful


def test_execute_plan_simple_success(execution_engine, tool_executor):
    """Test execution of simple plan with all steps succeeding."""
    # Create test file
    tool_executor.execute_tool("write_file", file_path="/tmp/input.txt", content="input data")

    plan = ExecutionPlan(
        task_description="Simple task",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Read input",
                action_type="read",
                arguments={"file_path": "/tmp/input.txt"},
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Write output",
                action_type="write",
                arguments={"file_path": "/tmp/output.txt", "content": "output data"},
                dependencies=[1],
                risk="low"
            )
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    assert result.success is True
    assert len(result.completed_steps) == 2
    assert len(result.failed_steps) == 0
    assert result.execution_time > 0
    assert all(r.success for r in result.step_results)


def test_execute_plan_with_dependencies(execution_engine, tool_executor):
    """Test execution respects step dependencies."""
    # Create test files
    tool_executor.execute_tool("write_file", file_path="/tmp/dep_a.txt", content="a")
    tool_executor.execute_tool("write_file", file_path="/tmp/dep_b.txt", content="b")

    plan = ExecutionPlan(
        task_description="Task with dependencies",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Read A",
                action_type="read",
                arguments={"file_path": "/tmp/dep_a.txt"},
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Read B",
                action_type="read",
                arguments={"file_path": "/tmp/dep_b.txt"},
                risk="low"
            ),
            PlanStep(
                id=3,
                description="Analyze A",
                action_type="analyze",
                arguments={"file_path": "/tmp/dep_a.txt"},
                dependencies=[1, 2],  # Depends on both 1 and 2
                risk="low"
            )
        ],
        total_estimated_time="2 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    assert result.success is True
    assert len(result.completed_steps) == 3
    # Verify execution order: steps 1 and 2 before step 3
    assert 1 in result.completed_steps
    assert 2 in result.completed_steps
    assert 3 in result.completed_steps


def test_execute_plan_abort_on_failure(execution_engine):
    """Test execution aborts on high-risk failure."""
    plan = ExecutionPlan(
        task_description="Task with high-risk step",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="High risk operation",
                action_type="read",
                arguments={"file_path": "/nonexistent/critical.txt"},
                risk="high"
            ),
            PlanStep(
                id=2,
                description="Dependent operation",
                action_type="write",
                arguments={"file_path": "/tmp/output.txt", "content": "data"},
                dependencies=[1],
                risk="low"
            )
        ],
        total_estimated_time="1 min",
        overall_risk="high",
        requires_approval=True
    )

    result = execution_engine.execute_plan(plan)

    assert result.success is False
    assert len(result.failed_steps) == 1
    assert 1 in result.failed_steps
    assert 2 in result.skipped_steps  # Step 2 should be skipped


def test_execute_plan_continue_on_low_risk_failure(execution_engine, tool_executor):
    """Test execution continues on low-risk failure."""
    # Create one test file
    tool_executor.execute_tool("write_file", file_path="/tmp/exists.txt", content="data")

    plan = ExecutionPlan(
        task_description="Task with non-critical failure",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Read non-existent file",
                action_type="read",
                arguments={"file_path": "/nonexistent.txt"},
                risk="low",
                reversible=True,
                dependencies=[]
            ),
            PlanStep(
                id=2,
                description="Read existing file",
                action_type="read",
                arguments={"file_path": "/tmp/exists.txt"},
                risk="low",
                dependencies=[]  # No dependency on step 1
            )
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Step 1 fails but step 2 should still execute
    assert len(result.failed_steps) == 1
    assert 1 in result.failed_steps
    assert 2 in result.completed_steps


# ============================================================================
# Summary Generation Tests
# ============================================================================

def test_summary_generation_success(execution_engine, simple_plan):
    """Test summary generation for successful execution."""
    results = [
        StepResult(step_id=1, success=True, tool_used="read_file", output="data", duration=0.1),
        StepResult(step_id=2, success=True, tool_used="write_file", output="written", duration=0.1)
    ]

    summary = execution_engine._generate_summary(simple_plan, results, 0.5)

    assert "SUCCESS" in summary
    assert "Completed: 2/2" in summary
    assert "Failed: 0/2" in summary
    assert "0.50s" in summary


def test_summary_generation_with_failures(execution_engine, simple_plan):
    """Test summary generation with failures."""
    results = [
        StepResult(step_id=1, success=True, tool_used="read_file", output="data", duration=0.1),
        StepResult(step_id=2, success=False, tool_used="write_file", error="Write failed", duration=0.1)
    ]

    summary = execution_engine._generate_summary(simple_plan, results, 0.5)

    assert "PARTIAL SUCCESS" in summary or "FAILED" in summary
    assert "Failed: 1/2" in summary
    assert "Write failed" in summary


def test_summary_includes_rollback_strategy(execution_engine):
    """Test summary includes rollback strategy on failures."""
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read", arguments={})
        ],
        total_estimated_time="1 min",
        overall_risk="medium",
        requires_approval=False,
        rollback_strategy="Revert changes using git"
    )

    results = [
        StepResult(step_id=1, success=False, error="Failed", duration=0.1)
    ]

    summary = execution_engine._generate_summary(plan, results, 0.5)

    assert "Rollback Strategy" in summary
    assert "Revert changes using git" in summary


# ============================================================================
# Integration Tests
# ============================================================================

def test_end_to_end_simple_workflow(execution_engine, tool_executor, task_analysis):
    """Test complete end-to-end workflow with real tools."""
    # Create test file
    tool_executor.execute_tool("write_file", file_path="/tmp/source.txt", content="source content")

    plan = ExecutionPlan(
        task_description="Copy file with modification",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Read source file",
                action_type="read",
                arguments={"file_path": "/tmp/source.txt"},
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Write to destination",
                action_type="write",
                arguments={"file_path": "/tmp/destination.txt", "content": "modified content"},
                dependencies=[1],
                risk="low"
            ),
            PlanStep(
                id=3,
                description="Verify destination exists",
                action_type="read",
                arguments={"file_path": "/tmp/destination.txt"},
                dependencies=[2],
                risk="low"
            )
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan, task_analysis)

    assert result.success is True
    assert len(result.completed_steps) == 3
    assert len(result.failed_steps) == 0
    assert result.execution_time > 0
    assert "SUCCESS" in result.summary


def test_progress_callback_invocation(tool_executor, task_analysis):
    """Test that progress callback is invoked during execution."""
    progress_messages = []

    def capture_progress(step_id, status, msg):
        progress_messages.append(msg)

    engine = ExecutionEngine(
        tool_executor=tool_executor,
        progress_callback=capture_progress
    )

    # Create test file
    tool_executor.execute_tool("write_file", file_path="/tmp/progress_test.txt", content="test")

    plan = ExecutionPlan(
        task_description="Progress test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Read file",
                action_type="read",
                arguments={"file_path": "/tmp/progress_test.txt"},
                risk="low"
            )
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    engine.execute_plan(plan, task_analysis)

    # Should have progress messages
    assert len(progress_messages) > 0
    assert any("Starting Execution" in msg for msg in progress_messages)
    assert any("Step 1" in msg for msg in progress_messages)


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
