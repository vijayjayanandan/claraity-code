"""Test if Qwen3 supports parallel tool calling (multiple tools in one response)."""

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
from src.tools.tool_schemas import WRITE_FILE_TOOL, READ_FILE_TOOL

def test_parallel_tool_calls():
    """Test if model can generate multiple tool calls in single response."""

    print("=" * 80)
    print("Testing Parallel Tool Calling with Qwen3-coder-plus")
    print("=" * 80)

    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        temperature=0.2,
        max_tokens=2000
    )

    llm = OpenAIBackend(config, api_key_env="DASHSCOPE_API_KEY")
    print("[OK] LLM initialized\n")

    # Test with explicit instructions to generate MULTIPLE tool calls
    messages = [
        {
            "role": "system",
            "content": """You are a coding assistant. When given a task, generate ALL necessary tool calls in a SINGLE response.

IMPORTANT: You MUST call multiple tools at once to complete the task. Do NOT call just one tool.
Generate tool calls for ALL files that need to be created.
"""
        },
        {
            "role": "user",
            "content": """Create a simple Python project with 3 files:
1. hello.py - prints "Hello World"
2. goodbye.py - prints "Goodbye World"
3. README.md - describes the project

Generate tool calls to create ALL 3 files NOW. Do not generate just 1 tool call - generate ALL 3."""
        }
    ]

    tools = [WRITE_FILE_TOOL, READ_FILE_TOOL]

    try:
        print("Calling LLM with explicit instructions for MULTIPLE tool calls...")
        response = llm.generate_with_tools(
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        print(f"\n[OK] LLM Response:")
        print(f"  Content: {response.content}")
        print(f"  Finish reason: {response.finish_reason}")

        if response.tool_calls:
            print(f"\n[RESULT] Tool calls generated: {len(response.tool_calls)}")
            for i, call in enumerate(response.tool_calls, 1):
                print(f"\n  Tool Call #{i}:")
                print(f"    Name: {call.name}")
                print(f"    Arguments: {call.arguments}")
        else:
            print("\n[FAIL] No tool calls generated!")
            return False

        # Success criteria: Should generate 3 tool calls (one for each file)
        if len(response.tool_calls) >= 3:
            print(f"\n{'='*80}")
            print(f"[SUCCESS] Model supports parallel tool calling! ({len(response.tool_calls)} calls)")
            print(f"{'='*80}")
            return True
        elif len(response.tool_calls) == 1:
            print(f"\n{'='*80}")
            print(f"[FAIL] Model only generated 1 tool call (needs prompting fix)")
            print(f"{'='*80}")
            return False
        else:
            print(f"\n{'='*80}")
            print(f"[PARTIAL] Model generated {len(response.tool_calls)} tool calls (expected 3)")
            print(f"{'='*80}")
            return False

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_parallel_tool_calls()
    print(f"\nResult: {'PASS' if success else 'FAIL'}")
