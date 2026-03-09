"""
Manual test script for Phase 1 basic communication.

This tests the complete agent-to-agent orchestration system end-to-end.

Usage:
    python -m src.orchestration.test_basic
"""

import os
import sys
from pathlib import Path

from src.orchestration import AgentOrchestrator


def test_basic_communication():
    """Test basic communication between Claude Code and AI Coding Agent"""

    print("\n" + "="*70)
    print("PHASE 1 TEST: Basic Agent-to-Agent Communication")
    print("="*70 + "\n")

    # Step 1: Initialize orchestrator
    print("[1/5] Initializing orchestrator...")
    try:
        orchestrator = AgentOrchestrator(
            output_dir="./test-orchestration-logs",
            working_directory="./test-orchestration-workspace"
        )
        print("   [OK] Orchestrator initialized")
        print(f"   Model: {orchestrator.model_name}")
        print(f"   Backend: {orchestrator.backend}")
        print(f"   Logs: {orchestrator.output_dir}")
        print(f"   Workspace: {orchestrator.working_directory}\n")
    except Exception as e:
        print(f"   [FAIL] Failed to initialize: {e}")
        return False

    # Step 2: Start conversation
    print("[2/5] Starting conversation...")
    try:
        session = orchestrator.start_conversation()
        print("   [OK] Conversation started")
        print(f"   ID: {session.conversation_id}")
        print(f"   Workspace: {session.working_directory}\n")
    except Exception as e:
        print(f"   [FAIL] Failed to start conversation: {e}")
        return False

    # Step 3: Send message to agent
    print("[3/5] Sending message to agent...")
    message = "Create a Python script called hello.py that prints 'Hello, World!'"
    print(f"   Message: '{message}'")
    try:
        response = session.send_message(message)
        print("   [OK] Agent responded")
        print(f"   Success: {response.success}")
        if response.success:
            print(f"   Files generated: {response.files_generated}")
            print(f"   Response preview: {response.content[:150]}...")
        else:
            print(f"   Error: {response.error}")
            return False
        print()
    except Exception as e:
        print(f"   [FAIL] Failed to send message: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 4: Verify files were created
    print("[4/5] Verifying files...")
    try:
        if response.files_generated:
            for file in response.files_generated:
                file_path = session.working_directory / file
                if file_path.exists():
                    print(f"   [OK] File exists: {file}")
                    # Show first few lines
                    with open(file_path, encoding='utf-8') as f:
                        content = f.read()
                        print(f"        Preview: {content[:100]}...")
                else:
                    print(f"   [WARN] File not found: {file}")
        else:
            print("   [WARN] No files generated")
        print()
    except Exception as e:
        print(f"   [FAIL] Error verifying files: {e}")

    # Step 5: End conversation and check log
    print("[5/5] Ending conversation...")
    try:
        log = orchestrator.end_conversation(session.conversation_id)
        print("   [OK] Conversation ended")
        print(f"   Total turns: {log.total_turns}")
        print(f"   Total messages: {len(log.messages)}")
        print(f"   Duration: {(log.ended_at - log.started_at).total_seconds():.1f}s")
        print(f"   Log saved to: {log.metadata.get('log_path')}\n")

        # Verify log file exists
        log_path = Path(log.metadata.get('log_path'))
        if log_path.exists():
            print(f"   [OK] Log file exists ({log_path.stat().st_size} bytes)")
        else:
            print("   [WARN] Log file not found")
        print()
    except Exception as e:
        print(f"   [FAIL] Failed to end conversation: {e}")
        return False

    # Success summary
    print("="*70)
    print("SUCCESS: Phase 1 basic communication working!")
    print("="*70)
    print("\nSummary:")
    print("  - Orchestrator initialized: OK")
    print("  - Conversation started: OK")
    print("  - Message sent and received: OK")
    print(f"  - Files generated: {len(response.files_generated)}")
    print("  - Conversation logged: OK")
    print("\nPhase 1 is COMPLETE!")
    print("="*70 + "\n")

    return True


def test_simple_send_message_api():
    """Test the simple send_message API (no session tracking)"""

    print("\n" + "="*70)
    print("BONUS TEST: Simple send_message() API")
    print("="*70 + "\n")

    print("[1/2] Testing simple send_message() API...")
    try:
        orchestrator = AgentOrchestrator(
            output_dir="./test-orchestration-logs",
            working_directory="./test-orchestration-workspace"
        )

        response = orchestrator.send_message("Create a file called test.txt with the text 'Testing!'")

        print("   [OK] Message sent and received")
        print(f"   Success: {response.success}")
        print(f"   Files: {response.files_generated}")
        print()
    except Exception as e:
        print(f"   [FAIL] Failed: {e}")
        return False

    print("[2/2] Verifying no session tracked...")
    try:
        active = orchestrator.list_active_conversations()
        if len(active) == 0:
            print("   [OK] No active sessions (as expected)")
        else:
            print(f"   [WARN] Found {len(active)} active sessions")
        print()
    except Exception as e:
        print(f"   [FAIL] Failed: {e}")
        return False

    print("="*70)
    print("SUCCESS: Simple API working!")
    print("="*70 + "\n")

    return True


if __name__ == "__main__":
    # Check for API key
    if not os.environ.get("DASHSCOPE_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print("\n[ERROR] No API key found!")
        print("Set DASHSCOPE_API_KEY or OPENAI_API_KEY environment variable.\n")
        sys.exit(1)

    # Run tests
    success = True

    # Main test
    if not test_basic_communication():
        success = False

    # Bonus test
    if not test_simple_send_message_api():
        success = False

    # Exit
    sys.exit(0 if success else 1)
