"""Tests for task planner.

Tests plan generation, validation, and formatting.
"""

import pytest
from src.workflow import (
    TaskPlanner,
    TaskAnalyzer,
    TaskType,
    TaskComplexity,
    TaskAnalysis,
    ExecutionPlan,
    PlanStep,
    ActionType
)


@pytest.fixture
def llm_backend():
    """Create LLM backend for testing."""
    from src.llm import OpenAIBackend, LLMConfig, LLMBackendType

    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768
    )

    return OpenAIBackend(config, api_key="sk-6ca5ca68942447c7a4c18d0ea63f75e7")


@pytest.fixture
def planner(llm_backend):
    """Create TaskPlanner instance."""
    return TaskPlanner(llm_backend)


@pytest.fixture
def sample_analysis():
    """Create sample TaskAnalysis for testing."""
    return TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=3,
        estimated_iterations=5,
        requires_git=True,
        requires_tests=True,
        risk_level="low",
        key_concepts=["tools"],
        affected_systems=["tools"]
    )


# ============================================================================
# Plan Generation Tests
# ============================================================================

def test_create_plan_simple_task(planner, sample_analysis):
    """Test creating plan for a simple task."""
    plan = planner.create_plan(
        "Add a new tool for listing directories",
        sample_analysis
    )

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) >= 2
    assert plan.task_description == "Add a new tool for listing directories"
    assert plan.task_type == TaskType.FEATURE
    assert all(isinstance(step, PlanStep) for step in plan.steps)


def test_create_plan_complex_task(planner):
    """Test creating plan for a complex task."""
    analysis = TaskAnalysis(
        task_type=TaskType.REFACTOR,
        complexity=TaskComplexity.COMPLEX,
        requires_planning=True,
        requires_approval=True,
        estimated_files=6,
        estimated_iterations=10,
        requires_git=True,
        requires_tests=True,
        risk_level="high",
        key_concepts=["memory", "redis"],
        affected_systems=["memory", "storage"]
    )

    plan = planner.create_plan(
        "Refactor memory system to use Redis",
        analysis
    )

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) >= 4  # Complex tasks need multiple steps
    assert plan.requires_approval is True
    assert plan.overall_risk in ["medium", "high"]


def test_create_plan_bugfix(planner):
    """Test creating plan for bug fix."""
    analysis = TaskAnalysis(
        task_type=TaskType.BUG_FIX,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=2,
        estimated_iterations=6,
        requires_git=True,
        requires_tests=True,
        risk_level="medium",
        key_concepts=["memory", "caching"],
        affected_systems=["agent"]
    )

    plan = planner.create_plan(
        "Fix bug where agent re-reads files unnecessarily",
        analysis
    )

    assert isinstance(plan, ExecutionPlan)
    assert plan.task_type == TaskType.BUG_FIX
    # Bug fixes should include investigation steps
    assert any("read" in step.action_type or "search" in step.action_type for step in plan.steps)


# ============================================================================
# Plan Validation Tests
# ============================================================================

def test_validate_plan_valid():
    """Test validation of valid plan."""
    planner = TaskPlanner(llm_backend=None)  # Validation doesn't need LLM
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read"),
            PlanStep(id=2, description="Step 2", action_type="write", dependencies=[1]),
            PlanStep(id=3, description="Step 3", action_type="verify", dependencies=[2])
        ],
        total_estimated_time="3 min",
        overall_risk="low",
        requires_approval=False
    )

    # Should not raise exception
    planner._validate_plan(plan)


def test_validate_plan_circular_dependency():
    """Test validation catches circular dependencies."""
    planner = TaskPlanner(llm_backend=None)
    # This creates invalid plan but we need to test validation
    # Note: Step 1 depends on 3 is also a forward dependency, caught first
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read", dependencies=[3]),
            PlanStep(id=2, description="Step 2", action_type="write", dependencies=[1]),
            PlanStep(id=3, description="Step 3", action_type="verify", dependencies=[2])
        ],
        total_estimated_time="3 min",
        overall_risk="low",
        requires_approval=False
    )

    # This will actually catch "forward dependency" first (step 1 depends on step 3)
    with pytest.raises(ValueError, match="forward dependency"):
        planner._validate_plan(plan)


def test_validate_plan_forward_dependency():
    """Test validation catches forward dependencies."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read", dependencies=[2]),
            PlanStep(id=2, description="Step 2", action_type="write")
        ],
        total_estimated_time="2 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError, match="forward dependency"):
        planner._validate_plan(plan)


def test_validate_plan_missing_dependency():
    """Test validation catches missing dependencies."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read"),
            PlanStep(id=2, description="Step 2", action_type="write", dependencies=[99])
        ],
        total_estimated_time="2 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError, match="non-existent step"):
        planner._validate_plan(plan)


def test_validate_plan_invalid_action_type():
    """Test validation catches invalid action types."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="invalid_action")
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError, match="invalid action_type"):
        planner._validate_plan(plan)


def test_validate_plan_invalid_risk():
    """Test validation catches invalid risk levels."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read", risk="invalid")
        ],
        total_estimated_time="1 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError, match="invalid risk"):
        planner._validate_plan(plan)


def test_validate_plan_empty_steps():
    """Test validation catches empty steps."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[],
        total_estimated_time="0 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError, match="at least one step"):
        planner._validate_plan(plan)


def test_validate_plan_non_sequential_ids():
    """Test validation catches non-sequential step IDs."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read"),
            PlanStep(id=3, description="Step 3", action_type="write")  # Missing ID 2
        ],
        total_estimated_time="2 min",
        overall_risk="low",
        requires_approval=False
    )

    with pytest.raises(ValueError, match="sequential"):
        planner._validate_plan(plan)


# ============================================================================
# Fallback Plan Tests
# ============================================================================

def test_simple_plan_fallback_explain():
    """Test fallback simple plan for explanation."""
    planner = TaskPlanner(llm_backend=None)
    analysis = TaskAnalysis(
        task_type=TaskType.EXPLAIN,
        complexity=TaskComplexity.TRIVIAL,
        requires_planning=False,
        requires_approval=False,
        estimated_files=2,
        estimated_iterations=2,
        requires_git=False,
        requires_tests=False,
        risk_level="low",
        key_concepts=["memory"],
        affected_systems=[]
    )

    plan = planner._create_simple_plan("Explain how memory works", analysis)

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) >= 2
    assert any(step.action_type == "read" for step in plan.steps)


def test_simple_plan_fallback_search():
    """Test fallback simple plan for search."""
    planner = TaskPlanner(llm_backend=None)
    analysis = TaskAnalysis(
        task_type=TaskType.SEARCH,
        complexity=TaskComplexity.SIMPLE,
        requires_planning=False,
        requires_approval=False,
        estimated_files=10,
        estimated_iterations=2,
        requires_git=False,
        requires_tests=False,
        risk_level="low",
        key_concepts=["search"],
        affected_systems=[]
    )

    plan = planner._create_simple_plan("Search for LLMBackend", analysis)

    assert isinstance(plan, ExecutionPlan)
    assert any(step.action_type == "search" for step in plan.steps)


def test_simple_plan_fallback_generic():
    """Test fallback simple plan for generic task."""
    planner = TaskPlanner(llm_backend=None)
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
        key_concepts=["feature"],
        affected_systems=["tools"]
    )

    plan = planner._create_simple_plan("Add a feature", analysis)

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) >= 3
    # Should have read, implement, verify
    action_types = [step.action_type for step in plan.steps]
    assert "read" in action_types
    assert "edit" in action_types
    assert "verify" in action_types


# ============================================================================
# Plan Formatting Tests
# ============================================================================

def test_format_plan_for_user():
    """Test plan formatting for user display."""
    planner = TaskPlanner(llm_backend=None)
    plan = ExecutionPlan(
        task_description="Add a new tool",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Read existing code", action_type="read", risk="low"),
            PlanStep(id=2, description="Create new file", action_type="write", dependencies=[1], risk="medium"),
            PlanStep(id=3, description="Verify it works", action_type="verify", dependencies=[2], risk="low")
        ],
        total_estimated_time="3 min",
        overall_risk="low",
        requires_approval=False,
        rollback_strategy="Delete new file",
        success_criteria=["File created", "Tests pass"]
    )

    formatted = planner.format_plan_for_user(plan)

    # Check all sections are present
    assert "Execution Plan" in formatted
    assert "Add a new tool" in formatted
    assert "**Total Time:**" in formatted
    assert "3 min" in formatted
    assert "**Risk Level:**" in formatted
    assert "### Steps:" in formatted
    assert "Read existing code" in formatted
    assert "Create new file" in formatted
    assert "### Rollback Strategy:" in formatted
    assert "Delete new file" in formatted
    assert "### Success Criteria:" in formatted
    assert "File created" in formatted


# ============================================================================
# ExecutionPlan Methods Tests
# ============================================================================

def test_get_step_by_id():
    """Test getting step by ID."""
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read"),
            PlanStep(id=2, description="Step 2", action_type="write")
        ],
        total_estimated_time="2 min",
        overall_risk="low",
        requires_approval=False
    )

    step1 = plan.get_step_by_id(1)
    assert step1 is not None
    assert step1.id == 1
    assert step1.description == "Step 1"

    step99 = plan.get_step_by_id(99)
    assert step99 is None


def test_get_next_pending_step():
    """Test getting next executable step."""
    plan = ExecutionPlan(
        task_description="Test",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(id=1, description="Step 1", action_type="read"),
            PlanStep(id=2, description="Step 2", action_type="write", dependencies=[1]),
            PlanStep(id=3, description="Step 3", action_type="verify", dependencies=[2])
        ],
        total_estimated_time="3 min",
        overall_risk="low",
        requires_approval=False
    )

    # Initially, only step 1 can execute (no dependencies)
    next_step = plan.get_next_pending_step(completed_ids=set())
    assert next_step.id == 1

    # After step 1, step 2 can execute
    next_step = plan.get_next_pending_step(completed_ids={1})
    assert next_step.id == 2

    # After steps 1 and 2, step 3 can execute
    next_step = plan.get_next_pending_step(completed_ids={1, 2})
    assert next_step.id == 3

    # After all steps, nothing left
    next_step = plan.get_next_pending_step(completed_ids={1, 2, 3})
    assert next_step is None


# ============================================================================
# PlanStep String Representation Tests
# ============================================================================

def test_plan_step_string_representation():
    """Test PlanStep string formatting."""
    step = PlanStep(
        id=1,
        description="Read the file",
        action_type="read",
        risk="low",
        estimated_time="< 1 min"
    )

    str_repr = str(step)

    assert "Step 1" in str_repr
    assert "Read the file" in str_repr
    assert "read" in str_repr
    assert "< 1 min" in str_repr


def test_plan_step_with_dependencies():
    """Test PlanStep string with dependencies."""
    step = PlanStep(
        id=3,
        description="Verify changes",
        action_type="verify",
        dependencies=[1, 2],
        risk="low"
    )

    str_repr = str(step)

    assert "depends on: 1, 2" in str_repr


# ============================================================================
# Edge Cases
# ============================================================================

def test_empty_request(sample_analysis):
    """Test that empty request raises ValueError."""
    planner = TaskPlanner(llm_backend=None)
    with pytest.raises(ValueError, match="cannot be empty"):
        planner.create_plan("", sample_analysis)


def test_whitespace_only_request(sample_analysis):
    """Test that whitespace-only request raises ValueError."""
    planner = TaskPlanner(llm_backend=None)
    with pytest.raises(ValueError, match="cannot be empty"):
        planner.create_plan("   \n\t  ", sample_analysis)


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_planning_workflow(planner):
    """Test complete planning workflow end-to-end."""
    # Create analysis
    analysis = TaskAnalysis(
        task_type=TaskType.FEATURE,
        complexity=TaskComplexity.MODERATE,
        requires_planning=True,
        requires_approval=False,
        estimated_files=2,
        estimated_iterations=4,
        requires_git=True,
        requires_tests=False,
        risk_level="low",
        key_concepts=["tools", "directory"],
        affected_systems=["tools"]
    )

    # Create plan
    plan = planner.create_plan(
        "Add a list_directory tool for browsing directories",
        analysis
    )

    # Validate plan structure
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) > 0
    assert all(isinstance(step, PlanStep) for step in plan.steps)

    # Validate plan is executable
    # Should not raise exception
    planner._validate_plan(plan)

    # Validate formatting works
    formatted = planner.format_plan_for_user(plan)
    assert isinstance(formatted, str)
    assert len(formatted) > 0
    assert "Execution Plan" in formatted


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
