"""Manual test script for TaskPlanner with real API.

Run this to validate the TaskPlanner works with the actual LLM backend.
"""

import os
from src.workflow import TaskPlanner, TaskAnalyzer, TaskType, TaskComplexity, TaskAnalysis
from src.llm import OpenAIBackend, LLMConfig, LLMBackendType


def test_planner():
    """Test TaskPlanner with real API."""

    # Check API key
    if not os.getenv("DASHSCOPE_API_KEY"):
        print("❌ DASHSCOPE_API_KEY not set. Skipping API tests.")
        return

    # Create LLM backend
    print("🔧 Initializing LLM backend...")
    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768
    )

    llm = OpenAIBackend(config, api_key_env="DASHSCOPE_API_KEY")

    # Create planner
    print("🔧 Initializing TaskPlanner...")
    planner = TaskPlanner(llm)

    # Test cases with pre-analyzed task types
    test_cases = [
        {
            "request": "Add a new tool for listing directories",
            "analysis": TaskAnalysis(
                task_type=TaskType.FEATURE,
                complexity=TaskComplexity.MODERATE,
                requires_planning=True,
                requires_approval=False,
                estimated_files=3,
                estimated_iterations=5,
                requires_git=True,
                requires_tests=True,
                risk_level="low",
                key_concepts=["tools", "directory"],
                affected_systems=["tools"]
            )
        },
        {
            "request": "Fix the bug where the agent re-reads files unnecessarily",
            "analysis": TaskAnalysis(
                task_type=TaskType.BUG_FIX,
                complexity=TaskComplexity.MODERATE,
                requires_planning=True,
                requires_approval=False,
                estimated_files=3,
                estimated_iterations=6,
                requires_git=True,
                requires_tests=True,
                risk_level="medium",
                key_concepts=["memory", "caching"],
                affected_systems=["agent", "context"]
            )
        },
        {
            "request": "Refactor the memory system to use Redis instead of in-memory storage",
            "analysis": TaskAnalysis(
                task_type=TaskType.REFACTOR,
                complexity=TaskComplexity.VERY_COMPLEX,
                requires_planning=True,
                requires_approval=True,
                estimated_files=8,
                estimated_iterations=12,
                requires_git=True,
                requires_tests=True,
                risk_level="high",
                key_concepts=["memory", "redis", "storage"],
                affected_systems=["memory", "storage", "config"]
            )
        },
        {
            "request": "Delete all unused test files from the tests/ directory",
            "analysis": TaskAnalysis(
                task_type=TaskType.REFACTOR,
                complexity=TaskComplexity.MODERATE,
                requires_planning=True,
                requires_approval=True,
                estimated_files=10,
                estimated_iterations=4,
                requires_git=True,
                requires_tests=False,
                risk_level="high",
                key_concepts=["cleanup", "tests"],
                affected_systems=["tests"]
            )
        },
        {
            "request": "Explain how the RAG system works",
            "analysis": TaskAnalysis(
                task_type=TaskType.EXPLAIN,
                complexity=TaskComplexity.SIMPLE,
                requires_planning=False,
                requires_approval=False,
                estimated_files=3,
                estimated_iterations=2,
                requires_git=False,
                requires_tests=False,
                risk_level="low",
                key_concepts=["rag", "embeddings"],
                affected_systems=[]
            )
        }
    ]

    print("\n" + "="*70)
    print("Testing TaskPlanner with Real API")
    print("="*70 + "\n")

    for i, test_case in enumerate(test_cases, 1):
        request = test_case["request"]
        analysis = test_case["analysis"]

        print(f"\n{'─'*70}")
        print(f"Test {i}/{len(test_cases)}: {request}")
        print(f"Task Type: {analysis.task_type.value} | Complexity: {analysis.complexity.value}/5")
        print('─'*70)

        try:
            plan = planner.create_plan(request, analysis)

            # Display formatted plan
            formatted = planner.format_plan_for_user(plan)
            print(f"\n{formatted}")

            # Validate plan structure
            assert len(plan.steps) > 0, "Plan must have steps"
            assert plan.task_description == request, "Task description mismatch"
            assert plan.task_type == analysis.task_type, "Task type mismatch"
            assert plan.overall_risk in ["low", "medium", "high"], "Invalid risk level"

            # Validate each step
            for step in plan.steps:
                assert step.id > 0, "Step ID must be positive"
                assert step.description, "Step must have description"
                assert step.action_type, "Step must have action type"
                assert step.risk in ["low", "medium", "high"], "Invalid step risk"

                # Check dependencies are valid
                for dep_id in step.dependencies:
                    assert dep_id < step.id, f"Step {step.id} has forward dependency on {dep_id}"

            # Validate execution order
            completed = set()
            for step in plan.steps:
                next_step = plan.get_next_pending_step(completed)
                if next_step:
                    assert all(dep in completed for dep in next_step.dependencies), \
                        f"Step {next_step.id} dependencies not met"
                    completed.add(next_step.id)

            print(f"\n✅ Test {i} passed - Plan has {len(plan.steps)} steps")

        except Exception as e:
            print(f"\n❌ Test {i} failed: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*70)
    print("✅ All tests completed!")
    print("="*70)


if __name__ == "__main__":
    test_planner()
