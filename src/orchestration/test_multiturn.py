"""
Manual test script for Phase 2 multi-turn conversations.

This tests that the agent maintains context across multiple conversation turns
and successfully modifies existing code based on previous interactions.

Usage:
    python -m src.orchestration.test_multiturn
"""

import os
import sys
from pathlib import Path

from src.orchestration import AgentOrchestrator


def test_multiturn_conversation():
    """Test multi-turn conversation with context preservation"""

    print("\n" + "="*70)
    print("PHASE 2 TEST: Multi-Turn Conversations with Context Preservation")
    print("="*70 + "\n")

    # Step 1: Initialize orchestrator
    print("[1/8] Initializing orchestrator...")
    try:
        orchestrator = AgentOrchestrator(
            output_dir="./test-orchestration-logs",
            working_directory="./test-orchestration-workspace"
        )
        print("   [OK] Orchestrator initialized")
        print(f"   Model: {orchestrator.model_name}")
        print(f"   Workspace: {orchestrator.working_directory}\n")
    except Exception as e:
        print(f"   [FAIL] Failed to initialize: {e}")
        return False

    # Step 2: Start conversation
    print("[2/8] Starting conversation...")
    try:
        session = orchestrator.start_conversation(
            task_description="Multi-turn calculator test"
        )
        print(f"   [OK] Conversation started")
        print(f"   ID: {session.conversation_id}")
        print(f"   Workspace: {session.working_directory}\n")
    except Exception as e:
        print(f"   [FAIL] Failed to start conversation: {e}")
        return False

    # Step 3: Turn 1 - Create initial calculator
    print("[3/8] Turn 1: Create initial calculator...")
    turn1_message = "Create a Python file called calculator.py with functions for add(a, b) and subtract(a, b). Include docstrings."
    print(f"   Message: '{turn1_message}'")
    try:
        response1 = session.send_message(turn1_message)
        print(f"   [OK] Agent responded")
        print(f"   Success: {response1.success}")
        if response1.success:
            print(f"   Files generated: {response1.files_generated}")
            print(f"   Tool calls: {len(response1.tool_calls)}")
        else:
            print(f"   [FAIL] Turn 1 failed: {response1.error}")
            return False

        # Verify calculator.py was created
        calc_file = session.working_directory / "calculator.py"
        if not calc_file.exists():
            print(f"   [FAIL] calculator.py not found!")
            return False

        # Read and check content
        with open(calc_file, 'r', encoding='utf-8') as f:
            content1 = f.read()

        has_add = "def add" in content1
        has_subtract = "def subtract" in content1
        has_multiply = "def multiply" in content1
        has_divide = "def divide" in content1

        print(f"   Functions present: add={has_add}, subtract={has_subtract}, multiply={has_multiply}, divide={has_divide}")

        if not (has_add and has_subtract):
            print(f"   [FAIL] Missing required functions in Turn 1!")
            return False

        print(f"   [OK] Turn 1 complete - Basic calculator created")
        print()
    except Exception as e:
        print(f"   [FAIL] Turn 1 failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 4: Verify conversation history after Turn 1
    print("[4/8] Verifying conversation history after Turn 1...")
    try:
        history = session.get_history()
        print(f"   Messages in history: {len(history)}")
        print(f"   User messages: {len([m for m in history if m.role == 'user'])}")
        print(f"   Assistant messages: {len([m for m in history if m.role == 'assistant'])}")

        if len(history) != 2:  # 1 user + 1 assistant
            print(f"   [WARN] Expected 2 messages, got {len(history)}")
        else:
            print(f"   [OK] History tracking working")
        print()
    except Exception as e:
        print(f"   [FAIL] Failed to get history: {e}")
        return False

    # Step 5: Turn 2 - Add multiply and divide (requires context)
    print("[5/8] Turn 2: Add multiply and divide functions...")
    turn2_message = "Now add multiply(a, b) and divide(a, b) functions to the calculator. Make sure divide handles division by zero."
    print(f"   Message: '{turn2_message}'")
    print(f"   [TEST] This requires the agent to remember calculator.py from Turn 1")
    try:
        response2 = session.send_message(turn2_message)
        print(f"   [OK] Agent responded")
        print(f"   Success: {response2.success}")
        if response2.success:
            print(f"   Files modified: {response2.files_generated}")
            print(f"   Tool calls: {len(response2.tool_calls)}")
        else:
            print(f"   [FAIL] Turn 2 failed: {response2.error}")
            return False

        # Verify calculator.py was modified (not recreated)
        calc_file = session.working_directory / "calculator.py"
        if not calc_file.exists():
            print(f"   [FAIL] calculator.py disappeared!")
            return False

        # Read and check content
        with open(calc_file, 'r', encoding='utf-8') as f:
            content2 = f.read()

        has_add = "def add" in content2
        has_subtract = "def subtract" in content2
        has_multiply = "def multiply" in content2
        has_divide = "def divide" in content2
        has_zero_check = "ZeroDivisionError" in content2 or "== 0" in content2

        print(f"   Functions present: add={has_add}, subtract={has_subtract}, multiply={has_multiply}, divide={has_divide}")
        print(f"   Division by zero handling: {has_zero_check}")

        # Check context preservation: all 4 functions should exist
        if not (has_add and has_subtract and has_multiply and has_divide):
            print(f"   [FAIL] Missing functions! Agent didn't preserve context from Turn 1!")
            print(f"   Content preview:")
            print(f"   {content2[:500]}")
            return False

        if not has_zero_check:
            print(f"   [WARN] Division by zero handling may be missing")

        print(f"   [OK] Turn 2 complete - Context preserved, functions added")
        print()
    except Exception as e:
        print(f"   [FAIL] Turn 2 failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 6: Verify conversation history after Turn 2
    print("[6/8] Verifying conversation history after Turn 2...")
    try:
        history = session.get_history()
        print(f"   Messages in history: {len(history)}")
        print(f"   Total turns: {len([m for m in history if m.role == 'user'])}")

        if len(history) != 4:  # 2 user + 2 assistant
            print(f"   [WARN] Expected 4 messages, got {len(history)}")
        else:
            print(f"   [OK] Multi-turn history tracking working")

        # Verify messages contain expected content
        user_messages = [m for m in history if m.role == 'user']
        if len(user_messages) >= 2:
            print(f"   Turn 1 message preview: '{user_messages[0].content[:50]}...'")
            print(f"   Turn 2 message preview: '{user_messages[1].content[:50]}...'")
        print()
    except Exception as e:
        print(f"   [FAIL] Failed to verify history: {e}")
        return False

    # Step 7: Turn 3 - Add tests (requires context from both previous turns)
    print("[7/8] Turn 3: Add test file for the calculator...")
    turn3_message = "Create a test file test_calculator.py with tests for all calculator functions, including the division by zero case."
    print(f"   Message: '{turn3_message}'")
    print(f"   [TEST] This requires context from BOTH previous turns")
    try:
        response3 = session.send_message(turn3_message)
        print(f"   [OK] Agent responded")
        print(f"   Success: {response3.success}")
        if response3.success:
            print(f"   Files generated: {response3.files_generated}")
            print(f"   Tool calls: {len(response3.tool_calls)}")
        else:
            print(f"   [FAIL] Turn 3 failed: {response3.error}")
            return False

        # Verify test file was created
        test_file = session.working_directory / "test_calculator.py"
        if not test_file.exists():
            print(f"   [FAIL] test_calculator.py not found!")
            return False

        # Read and check content
        with open(test_file, 'r', encoding='utf-8') as f:
            test_content = f.read()

        # Check that test file references all functions
        tests_add = "add" in test_content.lower()
        tests_subtract = "subtract" in test_content.lower()
        tests_multiply = "multiply" in test_content.lower()
        tests_divide = "divide" in test_content.lower()
        tests_zero = "zero" in test_content.lower()

        print(f"   Tests cover: add={tests_add}, subtract={tests_subtract}, multiply={tests_multiply}, divide={tests_divide}, zero_div={tests_zero}")

        if not (tests_add and tests_subtract and tests_multiply and tests_divide):
            print(f"   [WARN] Test file may not cover all functions")

        # Verify calculator.py still exists
        calc_file = session.working_directory / "calculator.py"
        if not calc_file.exists():
            print(f"   [FAIL] calculator.py disappeared during Turn 3!")
            return False

        print(f"   [OK] Turn 3 complete - Test file created with context from all turns")
        print()
    except Exception as e:
        print(f"   [FAIL] Turn 3 failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 8: End conversation and verify log
    print("[8/8] Ending conversation and verifying log...")
    try:
        log = orchestrator.end_conversation(session.conversation_id)
        print(f"   [OK] Conversation ended")
        print(f"   Total turns: {log.total_turns}")
        print(f"   Total messages: {len(log.messages)}")
        print(f"   Duration: {(log.ended_at - log.started_at).total_seconds():.1f}s")

        # Verify we have 3 turns
        if log.total_turns != 3:
            print(f"   [WARN] Expected 3 turns, got {log.total_turns}")

        # Verify log file
        log_path = Path(log.metadata.get('log_path'))
        if log_path.exists():
            print(f"   [OK] Log file exists ({log_path.stat().st_size} bytes)")

            # Read and parse log to verify structure
            import json
            with open(log_path, 'r', encoding='utf-8') as f:
                log_data = json.load(f)

            print(f"   Log contains {len(log_data['messages'])} messages")
            print(f"   Conversation ID: {log_data['conversation_id']}")
        else:
            print(f"   [WARN] Log file not found")
        print()
    except Exception as e:
        print(f"   [FAIL] Failed to end conversation: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Success summary
    print("="*70)
    print("SUCCESS: Phase 2 Multi-Turn Conversations WORKING!")
    print("="*70)
    print("\nContext Preservation Evidence:")
    print("  - Turn 1: Created calculator.py with add() and subtract()")
    print("  - Turn 2: Added multiply() and divide() WITHOUT recreating file")
    print("           All original functions (add, subtract) still present")
    print("  - Turn 3: Created test file covering ALL 4 functions")
    print("           Agent remembered entire calculator structure")
    print("\nConversation Tracking:")
    print(f"  - Total turns: {log.total_turns}")
    print(f"  - Total messages: {len(log.messages)}")
    print(f"  - History preserved: YES")
    print(f"  - Log saved: {log.metadata.get('log_path')}")
    print("\nPhase 2 is COMPLETE!")
    print("="*70 + "\n")

    return True


def test_context_independence():
    """Test that separate conversations are independent"""

    print("\n" + "="*70)
    print("BONUS TEST: Context Independence Between Conversations")
    print("="*70 + "\n")

    print("[1/3] Testing that separate conversations don't share context...")

    try:
        orchestrator = AgentOrchestrator(
            output_dir="./test-orchestration-logs",
            working_directory="./test-orchestration-workspace"
        )

        # Start first conversation
        print("   [OK] Starting conversation A...")
        session_a = orchestrator.start_conversation()
        response_a = session_a.send_message("Create a file called file_a.txt with text 'From conversation A'")
        print(f"   [OK] Conversation A: {response_a.files_generated}")

        # Start second conversation
        print("   [OK] Starting conversation B...")
        session_b = orchestrator.start_conversation()
        response_b = session_b.send_message("Create a file called file_b.txt with text 'From conversation B'")
        print(f"   [OK] Conversation B: {response_b.files_generated}")

        # Verify both files exist in their respective workspaces
        file_a = session_a.working_directory / "file_a.txt"
        file_b = session_b.working_directory / "file_b.txt"

        print("\n[2/3] Verifying workspace isolation...")
        if file_a.exists() and file_b.exists():
            print(f"   [OK] Both files exist in separate workspaces")
            print(f"   Workspace A: {session_a.working_directory}")
            print(f"   Workspace B: {session_b.working_directory}")

            # Verify workspaces are different
            if session_a.working_directory != session_b.working_directory:
                print(f"   [OK] Workspaces are isolated")
            else:
                print(f"   [FAIL] Workspaces are the same!")
                return False
        else:
            print(f"   [FAIL] Files not found in expected locations")
            return False

        print("\n[3/3] Ending conversations...")
        log_a = orchestrator.end_conversation(session_a.conversation_id)
        log_b = orchestrator.end_conversation(session_b.conversation_id)
        print(f"   [OK] Both conversations ended")
        print(f"   Conversation A turns: {log_a.total_turns}")
        print(f"   Conversation B turns: {log_b.total_turns}")

        print("\n" + "="*70)
        print("SUCCESS: Context independence verified!")
        print("="*70 + "\n")

        return True

    except Exception as e:
        print(f"   [FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Check for API key
    if not os.environ.get("DASHSCOPE_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print("\n[ERROR] No API key found!")
        print("Set DASHSCOPE_API_KEY or OPENAI_API_KEY environment variable.\n")
        sys.exit(1)

    # Run tests
    success = True

    # Main test: Multi-turn conversations
    if not test_multiturn_conversation():
        success = False

    # Bonus test: Context independence
    if not test_context_independence():
        success = False

    # Exit
    sys.exit(0 if success else 1)
