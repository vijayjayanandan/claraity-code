"""Manual test script for TaskAnalyzer with real API.

Run this to validate the TaskAnalyzer works with the actual LLM backend.
"""

import os
from src.workflow import TaskAnalyzer
from src.llm import OpenAIBackend, LLMConfig, LLMBackendType


def test_analyzer():
    """Test TaskAnalyzer with real API."""

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

    # Create analyzer
    print("🔧 Initializing TaskAnalyzer...")
    analyzer = TaskAnalyzer(llm)

    # Test cases
    test_requests = [
        "Explain how the memory system works",
        "Add a new tool for listing directories",
        "Refactor the memory system to use Redis",
        "Fix the bug where the agent re-reads files",
        "Search for all usages of LLMBackend",
    ]

    print("\n" + "="*70)
    print("Testing TaskAnalyzer with Real API")
    print("="*70 + "\n")

    for i, request in enumerate(test_requests, 1):
        print(f"\n{'─'*70}")
        print(f"Test {i}/{len(test_requests)}: {request}")
        print('─'*70)

        try:
            analysis = analyzer.analyze(request)

            print(f"\n{analysis}")

            # Validate
            assert analysis.task_type is not None
            assert analysis.complexity is not None
            assert analysis.estimated_files >= 0
            assert analysis.estimated_iterations > 0
            assert analysis.risk_level in ["low", "medium", "high"]

            print(f"\n✅ Test {i} passed")

        except Exception as e:
            print(f"\n❌ Test {i} failed: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*70)
    print("✅ All tests completed!")
    print("="*70)


if __name__ == "__main__":
    test_analyzer()
