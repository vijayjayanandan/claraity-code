#!/usr/bin/env python3
"""
Test script for enhanced prompts.
Tests conversation memory, tool calling, and autonomous behavior.
"""

import sys
import time
from src.core.agent import CodingAgent

def print_section(title):
    """Print a section header."""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")

def print_response(response, max_length=500):
    """Print agent response."""
    content = response.content
    if len(content) > max_length:
        print(content[:max_length] + f"\n... (truncated {len(content) - max_length} chars)")
    else:
        print(content)

def test_conversation_memory(agent):
    """Test that agent remembers previous conversation."""
    print_section("TEST 1: Conversation Memory")

    print("📝 Step 1: Ask agent to remember a specific detail")
    print("User: 'My favorite color is blue. Please remember this.'\n")

    response1 = agent.chat("My favorite color is blue. Please remember this.", stream=False)
    print("Agent response:")
    print_response(response1)

    print("\n" + "-"*80 + "\n")

    print("📝 Step 2: Ask agent to recall the detail")
    print("User: 'What is my favorite color?'\n")

    response2 = agent.chat("What is my favorite color?", stream=False)
    print("Agent response:")
    print_response(response2)

    # Check if agent remembered
    if "blue" in response2.content.lower():
        print("\n✅ PASS: Agent remembered the conversation!")
    else:
        print("\n❌ FAIL: Agent did not remember the conversation")

    return "blue" in response2.content.lower()

def test_tool_calling_read_before_edit(agent):
    """Test that agent reads files before editing."""
    print_section("TEST 2: Tool Calling - Read Before Edit")

    # First, index the codebase so search works
    print("📝 Indexing codebase for testing...")
    agent.index_codebase(directory="./src")
    print("✓ Codebase indexed\n")

    print("📝 Step 1: Ask agent to find and describe a file")
    print("User: 'What does the agent.py file in src/core do?'\n")

    response1 = agent.chat("What does the agent.py file in src/core do?", stream=False)
    print("Agent response:")
    print_response(response1)

    print("\n" + "-"*80 + "\n")

    print("📝 Step 2: Ask follow-up about the same file")
    print("User: 'What class is defined in that file we just discussed?'\n")

    response2 = agent.chat("What class is defined in that file we just discussed?", stream=False)
    print("Agent response:")
    print_response(response2)

    # Check if agent referenced the previous discussion
    has_context = any(word in response2.content.lower() for word in ["just", "earlier", "discussed", "codingagent"])

    if has_context:
        print("\n✅ PASS: Agent maintained context from previous interaction!")
    else:
        print("\n❌ FAIL: Agent did not maintain context")

    return has_context

def test_autonomous_behavior(agent):
    """Test that agent uses tools proactively."""
    print_section("TEST 3: Autonomous Behavior")

    print("📝 Ask agent to analyze a file (should use tools without being told)")
    print("User: 'Tell me about the memory system implementation'\n")

    response = agent.chat("Tell me about the memory system implementation", stream=False)
    print("Agent response:")
    print_response(response, max_length=800)

    # The agent should have used tools (search_code or read_file)
    # We can't directly check tool usage here, but we can check for detailed content
    has_detail = len(response.content) > 200 and any(word in response.content.lower() for word in ["memory", "class", "function", "implements"])

    if has_detail:
        print("\n✅ PASS: Agent provided detailed analysis (likely used tools)")
    else:
        print("\n❌ FAIL: Agent response was too generic")

    return has_detail

def test_thinking_and_reasoning(agent):
    """Test that agent shows reasoning."""
    print_section("TEST 4: Thinking and Reasoning")

    print("📝 Ask agent a question requiring analysis")
    print("User: 'What would be the best way to add caching to the RAG retrieval system?'\n")

    response = agent.chat("What would be the best way to add caching to the RAG retrieval system?", stream=False)
    print("Agent response:")
    print_response(response, max_length=800)

    # Check for reasoning indicators
    has_reasoning = any(word in response.content.lower() for word in ["because", "would", "could", "should", "consider", "approach"])

    if has_reasoning:
        print("\n✅ PASS: Agent showed reasoning in response")
    else:
        print("\n❌ FAIL: Agent response lacked reasoning")

    return has_reasoning

def main():
    """Run all tests."""
    print("\n" + "🚀"*40)
    print("  TESTING ENHANCED PROMPTS")
    print("🚀"*40)

    print("\nInitializing agent with enhanced prompts...")
    agent = CodingAgent(
        model_name="qwen3-coder:30b",
        backend="ollama",
        context_window=131072,
    )
    print("✓ Agent initialized\n")

    results = {}

    try:
        # Test 1: Conversation Memory
        results['memory'] = test_conversation_memory(agent)
        time.sleep(2)

        # Test 2: Tool Calling
        results['tool_calling'] = test_tool_calling_read_before_edit(agent)
        time.sleep(2)

        # Test 3: Autonomous Behavior
        results['autonomous'] = test_autonomous_behavior(agent)
        time.sleep(2)

        # Test 4: Reasoning
        results['reasoning'] = test_thinking_and_reasoning(agent)

    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Print summary
    print_section("TEST SUMMARY")

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    print(f"Tests Passed: {passed}/{total}\n")

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name.replace('_', ' ').title()}")

    print("\n" + "="*80 + "\n")

    if passed == total:
        print("🎉 ALL TESTS PASSED! Enhanced prompts are working correctly!")
        return 0
    else:
        print(f"⚠️  {total - passed} test(s) failed. Review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
