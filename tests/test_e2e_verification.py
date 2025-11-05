"""End-to-end tests for workflow + verification integration.

These tests validate the complete workflow system works in practice:
- Task analysis → Planning → Execution → Verification
- Real file operations with verification
- Multi-language support
- Error detection and reporting
"""

import pytest
import tempfile
from pathlib import Path
from src.workflow import (
    TaskAnalyzer,
    TaskPlanner,
    ExecutionEngine,
    VerificationLayer
)
from src.tools.base import ToolExecutor
from src.tools.file_operations import WriteFileTool, ReadFileTool, EditFileTool


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def tool_executor():
    """Create tool executor with real tools."""
    executor = ToolExecutor()
    executor.register_tool(WriteFileTool())
    executor.register_tool(ReadFileTool())
    executor.register_tool(EditFileTool())
    return executor


@pytest.fixture
def execution_engine(tool_executor):
    """Create execution engine with verification enabled."""
    return ExecutionEngine(
        tool_executor=tool_executor,
        progress_callback=lambda step_id, status, msg: None,  # Silent
        enable_verification=True,
        enable_rollback=False  # Disable rollback for verification-only tests
    )


@pytest.fixture
def verifier():
    """Create verification layer."""
    return VerificationLayer(show_recommendations=False)


# ============================================================================
# E2E Test 1: Python Syntax Error Detection
# ============================================================================

def test_e2e_python_syntax_error_detection(temp_dir, tool_executor, execution_engine):
    """Test that verification catches Python syntax errors."""
    # Create file with syntax error
    test_file = temp_dir / "broken.py"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create Python file with syntax error",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Write file with syntax error",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(test_file),
                    "content": "def hello(\n    return 'broken'"  # Missing closing paren
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Step should succeed (file written)
    assert result.success is True
    assert len(result.completed_steps) == 1

    # But verification should catch the syntax error
    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    assert verification.passed is False
    assert verification.has_errors is True
    assert any('syntax' in e.message.lower() for e in verification.errors)


def test_e2e_python_valid_syntax_passes(temp_dir, tool_executor, execution_engine):
    """Test that valid Python passes verification."""
    test_file = temp_dir / "good.py"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create valid Python file",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Write valid Python file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(test_file),
                    "content": "def hello():\n    return 'world'\n"
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Step and verification should both succeed
    assert result.success is True

    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    assert verification.passed is True
    assert verification.has_errors is False
    assert 'python-syntax' in verification.tools_run


# ============================================================================
# E2E Test 2: Multi-Step File Modification
# ============================================================================

def test_e2e_multi_step_with_verification(temp_dir, tool_executor, execution_engine):
    """Test multi-step plan with verification at each step."""
    file1 = temp_dir / "step1.py"
    file2 = temp_dir / "step2.py"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create two Python files",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Create first file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(file1),
                    "content": "def add(a, b):\n    return a + b\n"
                },
                risk="low"
            ),
            PlanStep(
                id=2,
                description="Create second file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(file2),
                    "content": "def multiply(a, b):\n    return a * b\n"
                },
                dependencies=[1],
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Both steps should succeed
    assert result.success is True
    assert len(result.completed_steps) == 2

    # Both files should be verified
    for step_result in result.step_results:
        assert 'verification' in step_result.metadata
        verification = step_result.metadata['verification']
        assert verification.passed is True
        assert 'python-syntax' in verification.tools_run


# ============================================================================
# E2E Test 3: Edit Operation with Verification
# ============================================================================

def test_e2e_edit_with_verification(temp_dir, tool_executor, execution_engine):
    """Test that file edits are verified."""
    test_file = temp_dir / "greeting.py"  # Avoid "test" in filename (pytest would try to run it)

    # First create the file
    tool_executor.execute_tool(
        "write_file",
        file_path=str(test_file),
        content="def greet(name):\n    return f'Hello, {name}!'\n"
    )

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    # Edit the file
    plan = ExecutionPlan(
        task_description="Edit Python file",
        task_type=TaskType.REFACTOR,
        steps=[
            PlanStep(
                id=1,
                description="Update greeting function",
                action_type="edit",
                tool="edit_file",
                arguments={
                    "file_path": str(test_file),
                    "old_text": "Hello",
                    "new_text": "Hi"
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Edit should succeed and be verified
    assert result.success is True

    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    assert verification.passed is True

    # Verify file was actually edited
    content = test_file.read_text()
    assert "Hi" in content
    assert "Hello" not in content


# ============================================================================
# E2E Test 4: Verification Detects Introduced Errors
# ============================================================================

def test_e2e_verification_catches_edit_errors(temp_dir, tool_executor, execution_engine):
    """Test that verification catches syntax errors introduced by edits."""
    test_file = temp_dir / "will_break.py"

    # Create valid file
    tool_executor.execute_tool(
        "write_file",
        file_path=str(test_file),
        content="def calculate(x, y):\n    return x + y\n"
    )

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    # Edit that breaks syntax
    plan = ExecutionPlan(
        task_description="Break the file with bad edit",
        task_type=TaskType.REFACTOR,
        steps=[
            PlanStep(
                id=1,
                description="Make breaking edit",
                action_type="edit",
                tool="edit_file",
                arguments={
                    "file_path": str(test_file),
                    "old_text": "return x + y",
                    "new_text": "return x +"  # Incomplete expression
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Edit succeeds but verification fails
    assert result.success is True  # Step completed

    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    assert verification.passed is False
    assert verification.has_errors is True


# ============================================================================
# E2E Test 5: Multi-Language Support
# ============================================================================

def test_e2e_javascript_basic_verification(temp_dir, tool_executor, execution_engine):
    """Test JavaScript file basic verification."""
    js_file = temp_dir / "test.js"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create JavaScript file",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Write JavaScript file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(js_file),
                    "content": "function hello() { return 'world'; }\n"
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Should succeed with basic verification
    assert result.success is True

    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    # JavaScript gets basic checks (Tier 1)
    assert verification.tier >= 1
    assert 'basic-check' in verification.tools_run


def test_e2e_typescript_basic_verification(temp_dir, tool_executor, execution_engine):
    """Test TypeScript file basic verification."""
    ts_file = temp_dir / "test.ts"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create TypeScript file",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Write TypeScript file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(ts_file),
                    "content": "function hello(): string { return 'world'; }\n"
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    # Should succeed with basic verification
    assert result.success is True

    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    assert verification.tier >= 1


# ============================================================================
# E2E Test 6: Verification Without Tools (Tier 1 Only)
# ============================================================================

def test_e2e_verification_works_without_tools(temp_dir, tool_executor):
    """Test that verification works even without external tools."""
    # Create engine with verification that has no tools
    engine = ExecutionEngine(
        tool_executor=tool_executor,
        progress_callback=lambda step_id, status, msg: None,
        enable_verification=True,
        enable_rollback=False  # Disable rollback for verification-only test
    )

    # Disable all tools in verifier to simulate environment without tools
    if engine.verifier:
        engine.verifier.available_tools = {k: False for k in engine.verifier.available_tools}

    test_file = temp_dir / "tier1_only.py"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create file with Tier 1 verification only",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Write Python file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(test_file),
                    "content": "def test():\n    return True\n"
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = engine.execute_plan(plan)

    # Should still verify with Tier 1 (syntax check)
    assert result.success is True

    step_result = result.step_results[0]
    assert 'verification' in step_result.metadata

    verification = step_result.metadata['verification']
    assert verification.passed is True
    assert verification.tier == 1  # Only Tier 1 available
    assert 'python-syntax' in verification.tools_run
    assert len(verification.tools_skipped) > 0  # ruff, pytest skipped


# ============================================================================
# E2E Test 7: Verification Disabled
# ============================================================================

def test_e2e_verification_can_be_disabled(temp_dir, tool_executor):
    """Test that verification can be disabled."""
    engine = ExecutionEngine(
        tool_executor=tool_executor,
        progress_callback=lambda step_id, status, msg: None,
        enable_verification=False,  # Disabled
        enable_rollback=False  # Also disable rollback
    )

    test_file = temp_dir / "no_verify.py"

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Create file without verification",
        task_type=TaskType.FEATURE,
        steps=[
            PlanStep(
                id=1,
                description="Write file",
                action_type="write",
                tool="write_file",
                arguments={
                    "file_path": str(test_file),
                    "content": "def test():\n    return True\n"
                },
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = engine.execute_plan(plan)

    assert result.success is True

    # No verification should have run
    step_result = result.step_results[0]
    assert 'verification' not in step_result.metadata


# ============================================================================
# E2E Test 8: Read Operations Don't Trigger Verification
# ============================================================================

def test_e2e_read_operations_skip_verification(temp_dir, tool_executor, execution_engine):
    """Test that read operations don't trigger verification."""
    test_file = temp_dir / "read_test.py"
    test_file.write_text("def hello():\n    return 'world'\n")

    from src.workflow import ExecutionPlan, PlanStep, TaskType

    plan = ExecutionPlan(
        task_description="Read file",
        task_type=TaskType.SEARCH,
        steps=[
            PlanStep(
                id=1,
                description="Read Python file",
                action_type="read",
                tool="read_file",
                arguments={"file_path": str(test_file)},
                risk="low"
            )
        ],
        total_estimated_time="< 1 min",
        overall_risk="low",
        requires_approval=False
    )

    result = execution_engine.execute_plan(plan)

    assert result.success is True

    # Read operations shouldn't trigger verification
    step_result = result.step_results[0]
    assert 'verification' not in step_result.metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
