"""Manual test script for ExecutionEngine with real tools.

Run this to validate the ExecutionEngine works with actual tool execution.
"""

import os
import tempfile
from src.workflow import (
    TaskAnalyzer,
    TaskAnalysis,
    TaskType,
    TaskComplexity,
    TaskPlanner,
    ExecutionPlan,
    PlanStep
)
from src.workflow.execution_engine import ExecutionEngine, ExecutionResult, StepResult
from src.tools.base import ToolExecutor
from src.tools.file_operations import ReadFileTool, WriteFileTool, EditFileTool, ListDirectoryTool
from src.tools.code_search import SearchCodeTool, AnalyzeCodeTool
from src.llm import OpenAIBackend, LLMConfig, LLMBackendType


def setup_tools():
    """Set up tool executor with all tools."""
    executor = ToolExecutor()

    # Register all tools
    executor.register_tool(ReadFileTool())
    executor.register_tool(WriteFileTool())
    executor.register_tool(EditFileTool())
    executor.register_tool(ListDirectoryTool())
    executor.register_tool(SearchCodeTool())
    executor.register_tool(AnalyzeCodeTool())

    return executor


def test_execution_engine():
    """Test ExecutionEngine with real tools."""

    print("🔧 Setting up ExecutionEngine...")
    tool_executor = setup_tools()

    # Progress callback for visibility
    def progress_callback(msg):
        print(msg)

    execution_engine = ExecutionEngine(
        tool_executor=tool_executor,
        progress_callback=progress_callback
    )

    # Test cases with pre-created plans
    test_cases = [
        {
            "name": "Simple File Copy",
            "plan": ExecutionPlan(
                task_description="Copy file with modification",
                task_type=TaskType.FEATURE,
                steps=[
                    PlanStep(
                        id=1,
                        description="Create source file",
                        action_type="write",
                        arguments={
                            "file_path": "/tmp/test_source.txt",
                            "content": "Original content from test"
                        },
                        risk="low"
                    ),
                    PlanStep(
                        id=2,
                        description="Read source file",
                        action_type="read",
                        arguments={"file_path": "/tmp/test_source.txt"},
                        dependencies=[1],
                        risk="low"
                    ),
                    PlanStep(
                        id=3,
                        description="Write to destination",
                        action_type="write",
                        arguments={
                            "file_path": "/tmp/test_destination.txt",
                            "content": "Modified content for destination"
                        },
                        dependencies=[2],
                        risk="low"
                    ),
                    PlanStep(
                        id=4,
                        description="Verify destination exists",
                        action_type="read",
                        arguments={"file_path": "/tmp/test_destination.txt"},
                        dependencies=[3],
                        risk="low"
                    )
                ],
                total_estimated_time="1 min",
                overall_risk="low",
                requires_approval=False
            ),
            "analysis": TaskAnalysis(
                task_type=TaskType.FEATURE,
                complexity=TaskComplexity.SIMPLE,
                requires_planning=True,
                requires_approval=False,
                estimated_files=2,
                estimated_iterations=4,
                requires_git=False,
                requires_tests=False,
                risk_level="low",
                key_concepts=["file", "copy"],
                affected_systems=[]
            )
        },
        {
            "name": "Edit File in Place",
            "plan": ExecutionPlan(
                task_description="Edit configuration file",
                task_type=TaskType.REFACTOR,
                steps=[
                    PlanStep(
                        id=1,
                        description="Create config file",
                        action_type="write",
                        arguments={
                            "file_path": "/tmp/config.txt",
                            "content": "setting1=value1\nsetting2=value2\nsetting3=value3"
                        },
                        risk="low"
                    ),
                    PlanStep(
                        id=2,
                        description="Read config",
                        action_type="read",
                        arguments={"file_path": "/tmp/config.txt"},
                        dependencies=[1],
                        risk="low"
                    ),
                    PlanStep(
                        id=3,
                        description="Update setting2",
                        action_type="edit",
                        arguments={
                            "file_path": "/tmp/config.txt",
                            "old_text": "setting2=value2",
                            "new_text": "setting2=updated_value"
                        },
                        dependencies=[2],
                        risk="medium"
                    ),
                    PlanStep(
                        id=4,
                        description="Verify changes",
                        action_type="read",
                        arguments={"file_path": "/tmp/config.txt"},
                        dependencies=[3],
                        risk="low"
                    )
                ],
                total_estimated_time="2 min",
                overall_risk="medium",
                requires_approval=False
            ),
            "analysis": TaskAnalysis(
                task_type=TaskType.REFACTOR,
                complexity=TaskComplexity.MODERATE,
                requires_planning=True,
                requires_approval=False,
                estimated_files=1,
                estimated_iterations=4,
                requires_git=False,
                requires_tests=False,
                risk_level="medium",
                key_concepts=["edit", "config"],
                affected_systems=[]
            )
        },
        {
            "name": "Analyze Code Structure",
            "plan": ExecutionPlan(
                task_description="Analyze Python file structure",
                task_type=TaskType.EXPLAIN,
                steps=[
                    PlanStep(
                        id=1,
                        description="Create Python file",
                        action_type="write",
                        arguments={
                            "file_path": "/tmp/sample.py",
                            "content": """def hello(name):
    '''Say hello to someone'''
    return f'Hello, {name}!'

class Greeter:
    def __init__(self, greeting='Hi'):
        self.greeting = greeting

    def greet(self, name):
        return f'{self.greeting}, {name}!'
"""
                        },
                        risk="low"
                    ),
                    PlanStep(
                        id=2,
                        description="Analyze code structure",
                        action_type="analyze",
                        arguments={"file_path": "/tmp/sample.py"},
                        dependencies=[1],
                        risk="low"
                    )
                ],
                total_estimated_time="30 seconds",
                overall_risk="low",
                requires_approval=False
            ),
            "analysis": TaskAnalysis(
                task_type=TaskType.EXPLAIN,
                complexity=TaskComplexity.SIMPLE,
                requires_planning=True,
                requires_approval=False,
                estimated_files=1,
                estimated_iterations=2,
                requires_git=False,
                requires_tests=False,
                risk_level="low",
                key_concepts=["analyze", "python"],
                affected_systems=[]
            )
        },
        {
            "name": "Abort on High-Risk Failure",
            "plan": ExecutionPlan(
                task_description="Test abort on critical failure",
                task_type=TaskType.FEATURE,
                steps=[
                    PlanStep(
                        id=1,
                        description="Attempt to read non-existent critical file",
                        action_type="read",
                        arguments={"file_path": "/nonexistent/critical/file.txt"},
                        risk="high"
                    ),
                    PlanStep(
                        id=2,
                        description="This step should be skipped",
                        action_type="write",
                        arguments={
                            "file_path": "/tmp/should_not_exist.txt",
                            "content": "This should never be written"
                        },
                        dependencies=[1],
                        risk="low"
                    )
                ],
                total_estimated_time="30 seconds",
                overall_risk="high",
                requires_approval=True,
                rollback_strategy="No rollback needed for read-only operation"
            ),
            "analysis": TaskAnalysis(
                task_type=TaskType.FEATURE,
                complexity=TaskComplexity.SIMPLE,
                requires_planning=True,
                requires_approval=True,
                estimated_files=1,
                estimated_iterations=2,
                requires_git=False,
                requires_tests=False,
                risk_level="high",
                key_concepts=["error handling"],
                affected_systems=[]
            )
        },
        {
            "name": "Continue on Low-Risk Failure",
            "plan": ExecutionPlan(
                task_description="Test continue on non-critical failure",
                task_type=TaskType.FEATURE,
                steps=[
                    PlanStep(
                        id=1,
                        description="Try to read optional file",
                        action_type="read",
                        arguments={"file_path": "/tmp/optional_file.txt"},
                        risk="low",
                        reversible=True,
                        dependencies=[]
                    ),
                    PlanStep(
                        id=2,
                        description="Create fallback file",
                        action_type="write",
                        arguments={
                            "file_path": "/tmp/fallback.txt",
                            "content": "Fallback content"
                        },
                        risk="low",
                        dependencies=[]  # Not dependent on step 1
                    ),
                    PlanStep(
                        id=3,
                        description="Verify fallback exists",
                        action_type="read",
                        arguments={"file_path": "/tmp/fallback.txt"},
                        dependencies=[2],
                        risk="low"
                    )
                ],
                total_estimated_time="1 min",
                overall_risk="low",
                requires_approval=False
            ),
            "analysis": TaskAnalysis(
                task_type=TaskType.FEATURE,
                complexity=TaskComplexity.MODERATE,
                requires_planning=True,
                requires_approval=False,
                estimated_files=2,
                estimated_iterations=3,
                requires_git=False,
                requires_tests=False,
                risk_level="low",
                key_concepts=["error recovery"],
                affected_systems=[]
            )
        }
    ]

    print("\n" + "="*70)
    print("Testing ExecutionEngine with Real Tools")
    print("="*70 + "\n")

    results = []
    for i, test_case in enumerate(test_cases, 1):
        name = test_case["name"]
        plan = test_case["plan"]
        analysis = test_case["analysis"]

        print(f"\n{'─'*70}")
        print(f"Test {i}/{len(test_cases)}: {name}")
        print(f"Task Type: {plan.task_type.value} | Complexity: {analysis.complexity.value}")
        print(f"Steps: {len(plan.steps)} | Risk: {plan.overall_risk}")
        print('─'*70)

        try:
            # Execute the plan
            result = execution_engine.execute_plan(plan, analysis)

            # Display results
            print(result.summary)

            # Validate results
            assert result.plan == plan, "Plan mismatch in result"
            assert len(result.step_results) > 0, "No step results"
            assert result.execution_time > 0, "No execution time recorded"

            # Validate step result structure
            for step_result in result.step_results:
                assert step_result.step_id > 0, "Invalid step ID"
                assert step_result.duration >= 0, "Invalid duration"

                if step_result.success:
                    assert step_result.output is not None, "Successful step has no output"
                else:
                    assert step_result.error is not None, "Failed step has no error message"

            # Test-specific validations
            if name == "Simple File Copy":
                assert result.success is True, "Simple file copy should succeed"
                assert len(result.completed_steps) == 4, "All 4 steps should complete"
                # Verify destination file was created
                verify_result = tool_executor.execute_tool("read_file", file_path="/tmp/test_destination.txt")
                assert verify_result.is_success(), "Destination file should exist"

            elif name == "Edit File in Place":
                assert result.success is True, "File edit should succeed"
                assert len(result.completed_steps) == 4, "All 4 steps should complete"
                # Verify edit was applied
                verify_result = tool_executor.execute_tool("read_file", file_path="/tmp/config.txt")
                assert "updated_value" in verify_result.output, "Edit should be applied"

            elif name == "Analyze Code Structure":
                assert result.success is True, "Code analysis should succeed"
                assert len(result.completed_steps) == 2, "Both steps should complete"

            elif name == "Abort on High-Risk Failure":
                assert result.success is False, "High-risk failure should fail overall"
                assert 1 in result.failed_steps, "Step 1 should fail"
                assert 2 in result.skipped_steps, "Step 2 should be skipped"

            elif name == "Continue on Low-Risk Failure":
                # Step 1 fails (optional file doesn't exist)
                # But steps 2 and 3 should still execute
                assert 1 in result.failed_steps, "Step 1 should fail"
                assert 2 in result.completed_steps, "Step 2 should complete"
                assert 3 in result.completed_steps, "Step 3 should complete"

            print(f"\n✅ Test {i} passed - {name}")
            results.append(("PASS", name))

        except Exception as e:
            print(f"\n❌ Test {i} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(("FAIL", name))

    # Summary
    print("\n" + "="*70)
    print("Test Summary")
    print("="*70)

    passed = sum(1 for status, _ in results if status == "PASS")
    failed = sum(1 for status, _ in results if status == "FAIL")

    print(f"\nTotal Tests: {len(results)}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")

    if failed == 0:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {failed} test(s) failed:")
        for status, name in results:
            if status == "FAIL":
                print(f"  - {name}")

    print("="*70)

    return failed == 0


if __name__ == "__main__":
    success = test_execution_engine()
    exit(0 if success else 1)
