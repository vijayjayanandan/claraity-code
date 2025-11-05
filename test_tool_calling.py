"""Quick test for tool calling implementation."""

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

# Test tool calling with DashScope
def test_tool_calling():
    config = LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        temperature=0.2,
        max_tokens=1024
    )

    backend = OpenAIBackend(
        config=config,
        api_key_env="DASHSCOPE_API_KEY"
    )

    # Test message
    messages = [
        {
            "role": "user",
            "content": "Create a hello.py file that prints 'Hello World'"
        }
    ]

    # Call with tools
    tools = [WRITE_FILE_TOOL, READ_FILE_TOOL]

    try:
        response = backend.generate_with_tools(
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        print("Response received!")
        print(f"Content: {response.content}")
        print(f"Finish reason: {response.finish_reason}")

        if response.tool_calls:
            print(f"\nTool calls: {len(response.tool_calls)}")
            for call in response.tool_calls:
                print(f"\n  Tool: {call.name}")
                print(f"  ID: {call.id}")
                print(f"  Arguments: {call.arguments}")
        else:
            print("\nNo tool calls (LLM responded with text)")

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_tool_calling()
    print(f"\nTest {'PASSED' if success else 'FAILED'}")
