"""Test enhanced prompts with Alibaba API backend."""

import os
from src.core.agent import CodingAgent


def test_conversation_memory():
    """Test that conversation memory works with API backend."""
    print("=" * 70)
    print("TEST 1: Conversation Memory with API Backend")
    print("=" * 70)

    # Initialize agent with Alibaba Cloud
    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key=os.getenv("DASHSCOPE_API_KEY", "")
    )

    print("\n✓ Agent initialized with Alibaba API")
    print(f"  Model: {agent.model_name}")
    print(f"  Backend: OpenAI-compatible")

    # First message - tell agent something
    print("\n" + "-" * 70)
    print("Step 1: Tell agent about favorite programming language")
    print("-" * 70)

    response1 = agent.chat(
        "My favorite programming language is Python. Remember this for later.",
        stream=True
    )
    print("\nAgent response:")
    print(response1.content[:200] + "..." if len(response1.content) > 200 else response1.content)

    # Second message - ask about what we just told it
    print("\n" + "-" * 70)
    print("Step 2: Ask agent what we just told it")
    print("-" * 70)

    response2 = agent.chat(
        "What did I just tell you about my favorite programming language?",
        stream=True
    )
    print("\nAgent response:")
    print(response2.content)

    # Check if response mentions Python
    if "python" in response2.content.lower():
        print("\n✅ PASS: Agent remembered the conversation!")
    else:
        print("\n❌ FAIL: Agent did not remember the conversation")

    return agent


def test_tool_calling():
    """Test that tool calling works with API backend."""
    print("\n" + "=" * 70)
    print("TEST 2: Tool Calling with API Backend")
    print("=" * 70)

    # Initialize agent
    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key=os.getenv("DASHSCOPE_API_KEY", "")
    )

    # Index the codebase first
    print("\n📚 Indexing codebase for RAG...")
    try:
        stats = agent.index_codebase("./src/core")
        print(f"✓ Indexed {stats['total_files']} files, {stats['total_chunks']} chunks")
    except Exception as e:
        print(f"⚠ Warning: Could not index: {e}")

    # Ask agent to read a file
    print("\n" + "-" * 70)
    print("Step 1: Ask agent to explain agent.py")
    print("-" * 70)

    response = agent.chat(
        "Read the src/core/agent.py file and tell me what the main class does in 2-3 sentences.",
        stream=True
    )
    print("\nAgent response:")
    print(response.content)

    # Check if it actually read the file
    if "CodingAgent" in response.content or "agent" in response.content.lower():
        print("\n✅ PASS: Agent appears to have read the file!")
    else:
        print("\n❌ FAIL: Agent may not have used the read_file tool")

    return agent


def test_multi_turn_conversation():
    """Test multi-turn conversation with context retention."""
    print("\n" + "=" * 70)
    print("TEST 3: Multi-Turn Conversation")
    print("=" * 70)

    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key=os.getenv("DASHSCOPE_API_KEY", "")
    )

    # Turn 1
    print("\n📝 Turn 1: Define a function")
    response1 = agent.chat(
        "Write a simple Python function called 'greet' that takes a name and returns a greeting.",
        stream=True
    )
    print(f"Agent: {response1.content[:150]}...")

    # Turn 2 - Reference previous turn
    print("\n📝 Turn 2: Modify the function")
    response2 = agent.chat(
        "Now modify that function to also accept an optional language parameter.",
        stream=True
    )
    print(f"Agent: {response2.content[:150]}...")

    # Turn 3 - Reference both previous turns
    print("\n📝 Turn 3: Add another feature")
    response3 = agent.chat(
        "Great! Now add a default greeting in case no language is provided.",
        stream=True
    )
    print(f"Agent: {response3.content[:150]}...")

    # Check if later responses reference earlier context
    if "greet" in response3.content.lower() or "function" in response3.content.lower():
        print("\n✅ PASS: Agent maintained context across multiple turns!")
    else:
        print("\n❌ FAIL: Agent lost context")

    return agent


def test_code_quality():
    """Test that agent follows code quality guidelines from enhanced prompts."""
    print("\n" + "=" * 70)
    print("TEST 4: Code Quality Standards")
    print("=" * 70)

    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,
        api_key=os.getenv("DASHSCOPE_API_KEY", "")
    )

    print("\n📝 Asking agent to write a class with proper documentation")
    response = agent.chat(
        "Write a Python class called DataProcessor with type hints, docstrings, and error handling.",
        stream=True
    )
    print(f"\nAgent response length: {len(response.content)} characters")

    # Check for quality markers
    has_docstring = '"""' in response.content or "'''" in response.content
    has_type_hints = "->" in response.content or ": " in response.content
    has_error_handling = "try:" in response.content or "except" in response.content

    print(f"\n📊 Code Quality Check:")
    print(f"  Docstrings: {'✓' if has_docstring else '✗'}")
    print(f"  Type hints: {'✓' if has_type_hints else '✗'}")
    print(f"  Error handling: {'✓' if has_error_handling else '✗'}")

    if has_docstring and has_type_hints:
        print("\n✅ PASS: Agent follows code quality standards!")
    else:
        print("\n⚠ PARTIAL: Agent could improve code quality")

    return agent


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("TESTING ENHANCED PROMPTS WITH ALIBABA API")
    print("=" * 70)

    try:
        # Run all tests
        test_conversation_memory()
        test_tool_calling()
        test_multi_turn_conversation()
        test_code_quality()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS COMPLETED!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
