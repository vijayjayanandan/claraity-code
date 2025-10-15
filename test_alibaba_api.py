"""Test script for Alibaba Cloud API integration."""

import os
from src.core.agent import CodingAgent


def test_alibaba_connection():
    """Test basic connection to Alibaba Cloud Model Studio."""
    print("=" * 60)
    print("Testing Alibaba Cloud Model Studio Integration")
    print("=" * 60)

    # Initialize agent with Alibaba Cloud backend
    agent = CodingAgent(
        backend="openai",
        model_name="qwen3-coder-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=32768,  # Reasonable context window
        api_key="sk-6ca5ca68942447c7a4c18d0ea63f75e7",
        api_key_env="DASHSCOPE_API_KEY"
    )

    print("\n✓ Agent initialized successfully!")
    print(f"  Model: {agent.model_name}")
    print(f"  Backend: openai (Alibaba Cloud)")
    print(f"  Context Window: {agent.context_window}")

    # Test simple query
    print("\n" + "-" * 60)
    print("Test 1: Simple Python function")
    print("-" * 60)

    response = agent.chat(
        "Write a simple Python function that adds two numbers",
        stream=True
    )

    print("\nResponse:")
    print(response.content)

    print("\n" + "-" * 60)
    print("Test 2: Code explanation")
    print("-" * 60)

    response2 = agent.chat(
        "Explain what a list comprehension is in Python with a simple example",
        stream=True
    )

    print("\nResponse:")
    print(response2.content)

    print("\n" + "=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    test_alibaba_connection()
