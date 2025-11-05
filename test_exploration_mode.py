"""Test exploration mode with weather CLI scenario."""

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

from src.llm import OpenAIBackend, LLMConfig, LLMBackendType
from src.workflow.task_analyzer import TaskAnalyzer
from src.workflow.task_planner import TaskPlanner

def test_weather_cli():
    """Test weather CLI planning with exploration mode."""

    print("=" * 80)
    print("Testing Weather CLI with Exploration Mode")
    print("=" * 80)

    # Initialize LLM
    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        temperature=0.2,
        max_tokens=4000
    )

    llm = OpenAIBackend(config, api_key_env="DASHSCOPE_API_KEY")
    print("[OK] LLM initialized\n")

    # Initialize components
    analyzer = TaskAnalyzer(llm)
    planner = TaskPlanner(llm)
    print("[OK] TaskAnalyzer and TaskPlanner initialized\n")

    # Test request
    request = """Build a weather CLI tool in Python that:
1. Uses the OpenWeatherMap API to fetch weather data
2. Takes city name as command-line argument
3. Displays temperature, humidity, and conditions
4. Includes error handling for API failures
5. Has a README with setup instructions
6. Includes unit tests
7. Uses requests library with caching"""

    print(f"Request: {request[:100]}...\n")

    # Analyze task
    print("Step 1: Analyzing task...")
    analysis = analyzer.analyze(request)
    print(f"[OK] Task Analysis:")
    print(f"  - Type: {analysis.task_type}")
    print(f"  - Complexity: {analysis.complexity}")
    print(f"  - Estimated files: {analysis.estimated_files}")
    print(f"  - Risk level: {analysis.risk_level}\n")

    # Create plan
    print("Step 2: Creating execution plan with exploration mode...")
    try:
        plan = planner.create_plan(request, analysis)

        print(f"\n[OK] Execution Plan Generated:")
        print(f"  - Total steps: {len(plan.steps)}")
        print(f"  - Estimated time: {plan.total_estimated_time}")
        print(f"  - Overall risk: {plan.overall_risk}\n")

        print("Plan Steps:\n")
        for step in plan.steps:
            print(f"  Step {step.id}: {step.description}")
            print(f"    - Action: {step.action_type}")
            print(f"    - Tool: {step.tool}")
            print(f"    - Risk: {step.risk}")
            if step.arguments:
                # Show first 100 chars of file_path or content
                args_summary = {}
                for k, v in step.arguments.items():
                    if isinstance(v, str) and len(v) > 100:
                        args_summary[k] = v[:100] + "..."
                    else:
                        args_summary[k] = v
                print(f"    - Arguments: {args_summary}")
            print()

        # Check if we got multiple write_file calls
        write_file_count = sum(1 for step in plan.steps if step.tool == "write_file")

        print("=" * 80)
        if write_file_count >= 4:
            print(f"[SUCCESS] Generated {write_file_count} write_file calls!")
            print("Exploration mode working correctly!")
        elif write_file_count >= 2:
            print(f"[PARTIAL] Generated {write_file_count} write_file calls (expected 4+)")
        else:
            print(f"[FAIL] Only {write_file_count} write_file calls (expected 4+)")
        print("=" * 80)

        return write_file_count >= 4

    except Exception as e:
        print(f"\n[FAIL] Plan generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_weather_cli()
    print(f"\nResult: {'PASS' if success else 'FAIL'}")
