"""
End-to-End Test for ClarAIty Integration

This test demonstrates the complete ClarAIty flow:
1. Initialize agent with ClarAIty enabled
2. Submit a complex task
3. ClarAIty intercepts and generates blueprint
4. User reviews and approves blueprint
5. Agent proceeds with code generation

Note: This is a semi-automated test that requires user interaction
for blueprint approval.
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Ensure API key is set
if not os.getenv("DASHSCOPE_API_KEY"):
    print("⚠️  DASHSCOPE_API_KEY environment variable not set")
    sys.exit(1)


def main():
    """Run end-to-end test."""
    print("="*80)
    print("🧪 ClarAIty End-to-End Integration Test")
    print("="*80)
    print()

    # Step 1: Initialize agent with ClarAIty enabled
    print("Step 1: Initializing agent with ClarAIty enabled...")
    print()

    from src.core import CodingAgent

    agent = CodingAgent(
        model_name="qwen-plus",
        backend="openai",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=131072,
        working_directory=".",
        api_key_env="DASHSCOPE_API_KEY",
        enable_clarity=True  # Enable ClarAIty
    )

    # Verify ClarAIty is enabled
    if agent.clarity_hook:
        print("✅ ClarAIty enabled successfully")
        print(f"   Mode: {agent.clarity_hook.config.mode}")
        print(f"   Database: {agent.clarity_hook.config.db_path}")
    else:
        print("❌ ClarAIty not enabled!")
        sys.exit(1)

    print()

    # Step 2: Submit a complex task that should trigger ClarAIty
    print("Step 2: Submitting complex task...")
    print()

    task_description = """
Build a new feature for user authentication that includes:
1. User registration with email validation
2. Login with JWT tokens
3. Password reset functionality
4. Session management
5. Rate limiting for security

The system should use:
- FastAPI for the REST API
- SQLAlchemy for database
- Redis for session storage
- Email service for notifications

Please create a complete implementation with proper error handling,
validation, and security best practices.
"""

    print(f"Task: {task_description[:100]}...")
    print()

    # Step 3: Execute task (ClarAIty will intercept)
    print("Step 3: Executing task (ClarAIty will intercept)...")
    print()
    print("⏳ This will open a browser window for blueprint approval")
    print("   Please review the architecture and approve or reject")
    print()

    try:
        response = agent.execute_task(
            task_description=task_description,
            task_type="implement",
            use_rag=False,
            stream=False
        )

        print()
        print("="*80)
        print("✅ Test Complete!")
        print("="*80)
        print()

        # Check if blueprint was used
        metadata = response.metadata
        if "clarity_status" in metadata:
            print(f"ClarAIty Status: {metadata['clarity_status']}")

            if metadata.get('clarity_status') == 'rejected':
                print(f"Feedback: {metadata.get('clarity_feedback', 'None')}")
                print()
                print("ℹ️  Blueprint was rejected by user")
            else:
                print()
                print("ℹ️  Blueprint was approved, code generation would proceed")

        # Show response summary
        print()
        print("Agent Response Summary:")
        print(f"  Length: {len(response.content)} characters")
        print(f"  Execution Mode: {metadata.get('execution_mode', 'unknown')}")

        # In a real implementation, the agent would have generated code
        # For this test, we're just verifying the integration works
        print()
        print("Note: In a production implementation, the approved blueprint")
        print("      would be used to guide code generation with detailed")
        print("      architecture context and design decisions.")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
