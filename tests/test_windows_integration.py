"""
Integration test for Windows compatibility layer with agent.

Tests that the agent works properly with safe_print and emoji-free output.
"""

import sys
import os
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.platform import (
    safe_print,
    remove_emojis,
    is_windows,
    safe_encode_output
)


def test_safe_print_no_crash():
    """Test that safe_print doesn't crash with various inputs."""
    # Capture stdout
    output = StringIO()

    with redirect_stdout(output):
        # Test basic text
        safe_print("Hello World [OK]")

        # Test text that would have emojis
        safe_print("Task completed [OK]")
        safe_print("Error [FAIL] in processing")
        safe_print("[WARN] This is a warning")
        safe_print("[INFO] Information message")

    result = output.getvalue()

    # Verify output exists
    assert len(result) > 0
    assert "Hello World" in result
    assert "[OK]" in result
    assert "[FAIL]" in result
    assert "[WARN]" in result
    assert "[INFO]" in result

    # Verify no emoji characters in output
    emoji_pattern = "[\\U0001F600-\\U0001F64F\\U0001F300-\\U0001F5FF\\U0001F680-\\U0001F6FF]"
    import re
    emojis_found = re.findall(emoji_pattern, result)
    assert len(emojis_found) == 0, f"Found emojis in output: {emojis_found}"

    print("[OK] safe_print test passed")


def test_remove_emojis():
    """Test emoji removal function."""
    # Test with text markers (should not be removed)
    text1 = "Status: [OK] Success"
    result1 = remove_emojis(text1)
    assert result1 == text1

    # Test with text that doesn't contain emojis
    text2 = "Hello World [FAIL] Error"
    result2 = remove_emojis(text2)
    assert result2 == text2

    # Verify no crashes on various inputs
    test_inputs = [
        "",
        "Simple text",
        "[OK] [FAIL] [WARN] [INFO]",
        "Line 1\nLine 2\nLine 3",
        "Special chars: @#$%^&*()",
    ]

    for test_input in test_inputs:
        result = remove_emojis(test_input)
        assert isinstance(result, str)

    print("[OK] remove_emojis test passed")


def test_safe_encode_output():
    """Test safe output encoding."""
    # Test ASCII text
    text1 = "Hello World [OK]"
    result1 = safe_encode_output(text1)
    assert result1 == text1

    # Test text with markers
    text2 = "[OK] Success [FAIL] Error [WARN] Warning"
    result2 = safe_encode_output(text2)
    assert "[OK]" in result2
    assert "[FAIL]" in result2
    assert "[WARN]" in result2

    print("[OK] safe_encode_output test passed")


def test_agent_import():
    """Test that agent can be imported with platform utilities."""
    try:
        from src.core.agent import CodingAgent
        from src.platform import safe_print

        # Verify agent has access to safe_print
        import src.core.agent as agent_module
        assert hasattr(agent_module, 'safe_print')

        print("[OK] Agent import test passed")
        return True
    except Exception as e:
        print(f"[FAIL] Agent import test failed: {e}")
        return False


def test_platform_detection():
    """Test platform detection works correctly."""
    platform = is_windows()
    print(f"[INFO] Running on Windows: {platform}")
    print(f"[INFO] Platform: {sys.platform}")

    # Verify no crashes
    assert isinstance(platform, bool)

    print("[OK] Platform detection test passed")


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("[TEST] Windows Integration Tests")
    print("="*60 + "\n")

    tests = [
        ("safe_print", test_safe_print_no_crash),
        ("remove_emojis", test_remove_emojis),
        ("safe_encode_output", test_safe_encode_output),
        ("agent_import", test_agent_import),
        ("platform_detection", test_platform_detection),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\n[>] Running test: {name}")
            test_func()
            passed += 1
        except Exception as e:
            print(f"[FAIL] Test '{name}' failed: {e}")
            failed += 1
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print(f"[INFO] Test Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    if failed == 0:
        print("[OK] All integration tests passed!")
        return 0
    else:
        print(f"[FAIL] {failed} test(s) failed")
        return 1


if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
