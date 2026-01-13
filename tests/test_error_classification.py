"""
Tests for error classification - ensuring wrapped exceptions are correctly identified.

Key scenario: RuntimeError wrapping ReadTimeout should be classified as "provider_timeout",
not "network". This regression test ensures the fix at agent.py:2053 works correctly.
"""

import pytest


class TestGetRootCauseInfo:
    """Test suite for get_root_cause_info helper function."""

    def test_unwrapped_exception(self):
        """Test that an unwrapped exception returns its own type."""
        from src.core.error_context import get_root_cause_info

        exc = ValueError("simple error")
        root_type, root_msg = get_root_cause_info(exc)

        assert root_type == "ValueError"
        assert root_msg == "simple error"

    def test_explicit_cause_chain(self):
        """Test that __cause__ chain is followed (raise X from Y)."""
        from src.core.error_context import get_root_cause_info

        # Simulate: raise RuntimeError("wrapper") from OriginalError("root")
        original = ValueError("root cause")
        wrapper = RuntimeError("wrapper")
        wrapper.__cause__ = original

        root_type, root_msg = get_root_cause_info(wrapper)

        assert root_type == "ValueError"
        assert root_msg == "root cause"

    def test_implicit_context_chain(self):
        """Test that __context__ chain is followed when __cause__ is None."""
        from src.core.error_context import get_root_cause_info

        # Simulate: try: raise X except: raise Y (implicit chaining)
        original = TypeError("implicit root")
        wrapper = RuntimeError("wrapper")
        wrapper.__context__ = original
        # No __cause__ set

        root_type, root_msg = get_root_cause_info(wrapper)

        assert root_type == "TypeError"
        assert root_msg == "implicit root"

    def test_cause_preferred_over_context(self):
        """Test that __cause__ is preferred over __context__ when both exist."""
        from src.core.error_context import get_root_cause_info

        context_exc = TypeError("context exception")
        cause_exc = ValueError("cause exception")
        wrapper = RuntimeError("wrapper")
        wrapper.__context__ = context_exc
        wrapper.__cause__ = cause_exc

        root_type, root_msg = get_root_cause_info(wrapper)

        # __cause__ should be preferred
        assert root_type == "ValueError"
        assert root_msg == "cause exception"

    def test_deep_chain(self):
        """Test that deeply nested exception chains are followed."""
        from src.core.error_context import get_root_cause_info

        # Create chain: wrapper -> middle -> root
        root = KeyError("deepest root")
        middle = ValueError("middle")
        middle.__cause__ = root
        wrapper = RuntimeError("wrapper")
        wrapper.__cause__ = middle

        root_type, root_msg = get_root_cause_info(wrapper)

        assert root_type == "KeyError"
        assert "deepest root" in root_msg

    def test_cycle_detection(self):
        """Test that cycles in exception chains don't cause infinite loops."""
        from src.core.error_context import get_root_cause_info

        # Create a cycle: A -> B -> A
        exc_a = ValueError("A")
        exc_b = RuntimeError("B")
        exc_a.__cause__ = exc_b
        exc_b.__cause__ = exc_a  # Cycle!

        # Should not hang, should return something reasonable
        root_type, root_msg = get_root_cause_info(exc_a)

        # Should stop at some point in the cycle
        assert root_type in ("ValueError", "RuntimeError")

    def test_message_truncation(self):
        """Test that long messages are truncated."""
        from src.core.error_context import get_root_cause_info

        long_message = "x" * 1000
        exc = ValueError(long_message)

        root_type, root_msg = get_root_cause_info(exc, max_message_len=100)

        assert len(root_msg) <= 103  # 100 + "..."
        assert root_msg.endswith("...")

    def test_none_exception(self):
        """Test handling of None input."""
        from src.core.error_context import get_root_cause_info

        root_type, root_msg = get_root_cause_info(None)

        assert root_type == "NoneType"
        assert root_msg == ""


class TestIsTimeoutError:
    """Test suite for is_timeout_error helper function."""

    def test_direct_timeout(self):
        """Test that direct timeout exceptions are detected."""
        from src.core.error_context import is_timeout_error

        # Create a mock timeout exception (simulating httpx.ReadTimeout)
        class ReadTimeout(Exception):
            pass

        exc = ReadTimeout("Read timed out")
        assert is_timeout_error(exc) is True

    def test_wrapped_timeout(self):
        """Test that wrapped timeout exceptions are detected."""
        from src.core.error_context import is_timeout_error

        # Simulate what openai_backend.py does
        class ReadTimeout(Exception):
            pass

        original = ReadTimeout("Read timed out")
        wrapper = RuntimeError(f"OpenAI streaming error: {original}")
        wrapper.__cause__ = original

        assert is_timeout_error(wrapper) is True

    def test_non_timeout(self):
        """Test that non-timeout exceptions return False."""
        from src.core.error_context import is_timeout_error

        exc = ValueError("not a timeout")
        assert is_timeout_error(exc) is False

        exc2 = RuntimeError("connection refused")
        assert is_timeout_error(exc2) is False


class TestRuntimeErrorWrappingReadTimeout:
    """
    Regression test for the specific bug:
    RuntimeError wrapping ReadTimeout was being classified as "network" instead of "provider_timeout".
    """

    def test_classification_uses_root_cause(self):
        """
        Verify that the classification logic uses root cause type, not wrapper type.

        This is the exact scenario that was broken:
        1. httpx.ReadTimeout raised
        2. openai_backend.py catches and wraps in RuntimeError
        3. agent.py receives RuntimeError
        4. Classification should be "provider_timeout" (from ReadTimeout), not "network" (from RuntimeError)
        """
        from src.core.error_context import get_root_cause_info

        # Simulate httpx.ReadTimeout (we don't need actual httpx for the test)
        class ReadTimeout(Exception):
            """Mock of httpx.ReadTimeout"""
            pass

        # Simulate what openai_backend.py does
        original = ReadTimeout("Read timed out after 60.0 seconds")
        wrapped = RuntimeError(f"OpenAI streaming error: {original}")
        wrapped.__cause__ = original

        # Get root cause info
        root_type, root_msg = get_root_cause_info(wrapped)

        # Verify root cause is correctly extracted
        assert root_type == "ReadTimeout", f"Expected ReadTimeout, got {root_type}"
        assert "timeout" in root_type.lower()

        # Verify classification logic (same as agent.py:2053)
        error_type_for_event = "provider_timeout" if "timeout" in root_type.lower() else "network"
        assert error_type_for_event == "provider_timeout", (
            f"Expected provider_timeout, got {error_type_for_event}. "
            "This would cause TUI to auto-retry instead of showing pause prompt!"
        )

    def test_wrapper_type_would_fail(self):
        """
        Demonstrate that using wrapper type (the old bug) would produce wrong result.
        """
        # Simulate httpx.ReadTimeout
        class ReadTimeout(Exception):
            pass

        original = ReadTimeout("Read timed out")
        wrapped = RuntimeError(f"OpenAI streaming error: {original}")
        wrapped.__cause__ = original

        # OLD (buggy) approach: use type(wrapped).__name__
        wrapper_type = type(wrapped).__name__
        old_classification = "provider_timeout" if "timeout" in wrapper_type.lower() else "network"

        # This is the bug! RuntimeError doesn't contain "timeout"
        assert old_classification == "network", "Old approach should produce 'network' (the bug)"

        # NEW (fixed) approach: use root cause type
        from src.core.error_context import get_root_cause_info
        root_type, _ = get_root_cause_info(wrapped)
        new_classification = "provider_timeout" if "timeout" in root_type.lower() else "network"

        # Fixed approach produces correct result
        assert new_classification == "provider_timeout", "New approach should produce 'provider_timeout'"
