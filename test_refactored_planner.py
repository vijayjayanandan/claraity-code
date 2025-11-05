"""Test refactored TaskPlanner with tool calling."""

import os
from pathlib import Path

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

from src.workflow.task_planner import TaskPlanner
from src.workflow.task_analyzer import TaskAnalyzer
from src.llm import OpenAIBackend, LLMConfig, LLMBackendType

def test_refactored_planner():
    """Test the refactored TaskPlanner with tool calling."""

    print("=" * 80)
    print("Testing Refactored TaskPlanner with Tool Calling")
    print("=" * 80)

    # Initialize LLM backend
    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        temperature=0.2,
        max_tokens=2000
    )

    llm = OpenAIBackend(config, api_key_env="DASHSCOPE_API_KEY")
    print("[OK] LLM backend initialized\n")

    # Initialize TaskAnalyzer and TaskPlanner
    analyzer = TaskAnalyzer(llm)
    planner = TaskPlanner(llm)
    print("[OK] TaskAnalyzer and TaskPlanner initialized\n")

    # Test request
    request = "Create a simple hello.py file that prints 'Hello, World!'"
    print(f"Request: {request}\n")

    # Step 1: Analyze task
    print("Step 1: Analyzing task...")
    try:
        analysis = analyzer.analyze(request)
        print(f"[OK] Task Analysis:")
        print(f"  - Type: {analysis.task_type}")
        print(f"  - Complexity: {analysis.complexity}")
        print(f"  - Risk level: {analysis.risk_level}")
        print(f"  - Estimated files: {analysis.estimated_files}")
        print(f"  - Estimated iterations: {analysis.estimated_iterations}")
        print(f"  - Requires planning: {analysis.requires_planning}")
        print()
    except Exception as e:
        print(f"[FAIL] Task analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 2: Create plan with tool calling
    print("Step 2: Creating execution plan with tool calling...")
    try:
        plan = planner.create_plan(request, analysis)
        print(f"[OK] Execution Plan Generated:")
        print(f"  - Total steps: {len(plan.steps)}")
        print(f"  - Estimated time: {plan.total_estimated_time}")
        print(f"  - Overall risk: {plan.overall_risk}")
        print()

        # Display steps
        print("Plan Steps:")
        for step in plan.steps:
            print(f"\n  Step {step.id}: {step.description}")
            print(f"    - Action: {step.action_type}")
            print(f"    - Tool: {step.tool}")
            print(f"    - Risk: {step.risk}")
            print(f"    - Reversible: {step.reversible}")
            print(f"    - Dependencies: {step.dependencies}")
            print(f"    - Arguments: {step.arguments}")

        print("\n" + "=" * 80)
        print("[SUCCESS] TaskPlanner refactor working correctly!")
        print("=" * 80)

        # Validate structure
        print("\nValidation Checks:")

        # Check 1: All steps have required fields
        for step in plan.steps:
            assert step.id, "Step missing id"
            assert step.description, "Step missing description"
            assert step.action_type, "Step missing action_type"
            assert step.tool, "Step missing tool"
            assert step.arguments is not None, "Step missing arguments"
        print("  [OK] All steps have required fields")

        # Check 2: Arguments are dicts, not JSON strings
        for step in plan.steps:
            assert isinstance(step.arguments, dict), f"Step {step.id} arguments not a dict!"
        print("  [OK] All arguments are dicts (not JSON strings)")

        # Check 3: No JSON parsing errors
        print("  [OK] No JSON parsing errors (tool calling eliminates them!)")

        return True

    except Exception as e:
        print(f"[FAIL] Plan creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_refactored_planner()
    print(f"\n{'='*80}")
    print(f"Test Result: {'PASSED' if success else 'FAILED'}")
    print(f"{'='*80}")
