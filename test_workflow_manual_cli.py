"""Manual CLI test script for workflow system validation.

This script tests the complete workflow integration by running 4 key scenarios:
1. Direct execution for simple explanation
2. Workflow execution for feature implementation
3. Direct execution for code search
4. Workflow execution with tool usage

Run this script to validate the workflow system works end-to-end.
"""

import sys
from src.core.agent import CodingAgent


def print_test_header(test_num: int, description: str):
    """Print test header."""
    print("\n" + "=" * 70)
    print(f"TEST {test_num}: {description}")
    print("=" * 70 + "\n")


def print_test_result(success: bool, execution_mode: str, expected_mode: str):
    """Print test result."""
    mode_match = execution_mode == expected_mode
    print("\n" + "-" * 70)
    print(f"✅ Test PASSED" if (success and mode_match) else f"❌ Test FAILED")
    print(f"Execution Mode: {execution_mode} (expected: {expected_mode})")
    print("-" * 70)


def main():
    """Run manual workflow tests."""
    print("\n" + "=" * 70)
    print("MANUAL WORKFLOW SYSTEM VALIDATION")
    print("=" * 70)

    # Initialize agent
    print("\nInitializing agent...")
    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key="sk-6ca5ca68942447c7a4c18d0ea63f75e7"
    )
    print("Agent initialized successfully!\n")

    results = []

    # Test 1: Simple Explanation (should use direct)
    print_test_header(1, "Simple Explanation Query (Expected: Direct Execution)")
    try:
        response = agent.execute_task(
            task_description="Explain what is 2+2",
            task_type="explain",
            stream=False
        )

        print(f"Response preview: {response.content[:200]}...")
        execution_mode = response.metadata.get("execution_mode", "unknown")
        print_test_result(True, execution_mode, "direct")
        results.append(("Test 1: Explanation", execution_mode == "direct"))
    except Exception as e:
        print(f"❌ Test 1 FAILED with error: {e}")
        results.append(("Test 1: Explanation", False))

    # Test 2: Feature Implementation (should use workflow)
    print_test_header(2, "Feature Implementation (Expected: Workflow Execution)")
    try:
        response = agent.execute_task(
            task_description="Create a simple function that adds two numbers",
            task_type="implement",
            stream=False
        )

        print(f"Response preview: {response.content[:200]}...")
        execution_mode = response.metadata.get("execution_mode", "unknown")
        print_test_result(True, execution_mode, "workflow")
        results.append(("Test 2: Implementation", execution_mode == "workflow"))
    except Exception as e:
        print(f"❌ Test 2 FAILED with error: {e}")
        results.append(("Test 2: Implementation", False))

    # Test 3: Code Search (should use direct)
    print_test_header(3, "Code Search Query (Expected: Direct Execution)")
    try:
        response = agent.execute_task(
            task_description="Find what files are in the src/workflow directory",
            task_type="explain",
            stream=False
        )

        print(f"Response preview: {response.content[:200]}...")
        execution_mode = response.metadata.get("execution_mode", "unknown")
        print_test_result(True, execution_mode, "direct")
        results.append(("Test 3: Search", execution_mode == "direct"))
    except Exception as e:
        print(f"❌ Test 3 FAILED with error: {e}")
        results.append(("Test 3: Search", False))

    # Test 4: Complex Task with Tools (should use workflow)
    print_test_header(4, "Complex Task with Tools (Expected: Workflow Execution)")
    try:
        response = agent.execute_task(
            task_description="Read the src/workflow/__init__.py file and tell me what it exports",
            task_type="implement",  # Force workflow
            stream=False
        )

        print(f"Response preview: {response.content[:200]}...")
        execution_mode = response.metadata.get("execution_mode", "unknown")
        print_test_result(True, execution_mode, "workflow")
        results.append(("Test 4: Complex with Tools", execution_mode == "workflow"))
    except Exception as e:
        print(f"❌ Test 4 FAILED with error: {e}")
        results.append(("Test 4: Complex with Tools", False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.0f}%)")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Workflow system is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review the output above.")
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
