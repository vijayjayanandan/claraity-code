"""
Tests for ErrorRecoveryTracker - partial reset and retry behavior.
"""

import pytest
from src.core.error_recovery import ErrorRecoveryTracker


class TestErrorRecoveryTracker:
    """Test suite for ErrorRecoveryTracker."""

    def test_basic_failure_tracking(self):
        """Test that failures are tracked correctly."""
        tracker = ErrorRecoveryTracker(max_same_tool_error_failures=2)

        # First failure should be allowed
        tracker.record_failure('command_failed', 'run_command', {'command': 'ls -la'}, 'error')
        allowed, _ = tracker.should_allow_retry('run_command', 'command_failed')
        assert allowed is True

        # Second failure should still be allowed (at limit)
        tracker.record_failure('command_failed', 'run_command', {'command': 'pwd'}, 'another error')
        allowed, _ = tracker.should_allow_retry('run_command', 'command_failed')
        assert allowed is False  # Now at limit, no more retries

    def test_partial_reset_allows_retry(self):
        """
        Test that partial reset clears tool counters but preserves safety limits.

        This is the key behavior for error budget pause/continue:
        - User hits Continue -> reset tool counters -> retry allowed
        - But total_failures still accumulates (safety limit)
        - And exact same call is still blocked (signature blocker)
        """
        tracker = ErrorRecoveryTracker(max_same_tool_error_failures=2)

        # Trigger 2 failures -> should_allow_retry returns False
        # Use REAL arg keys: {'command': ...} not {'cmd': ...}
        tracker.record_failure('command_failed', 'run_command', {'command': 'ls -la'}, 'error 1')
        tracker.record_failure('command_failed', 'run_command', {'command': 'ls -la'}, 'error 2')
        allowed, reason = tracker.should_allow_retry('run_command', 'command_failed')
        assert allowed is False
        assert 'command_failed' in reason

        # After partial reset -> should_allow_retry returns True
        tracker.reset_tool_error_counts()
        allowed, _ = tracker.should_allow_retry('run_command', 'command_failed')
        assert allowed is True  # Can retry now!

        # But total_failures still accumulates
        assert tracker.total_failures == 2

        # And signature blocker still active (exact same call blocked)
        is_repeat, summary = tracker.is_repeated_failed_call('run_command', {'command': 'ls -la'})
        assert is_repeat is True  # Exact same call still blocked!
        assert 'run_command' in summary

    def test_targeted_partial_reset(self):
        """
        Test that targeted reset only clears counters for specific tool.
        """
        tracker = ErrorRecoveryTracker(max_same_tool_error_failures=2)

        # Fail both run_command and read_file
        tracker.record_failure('command_failed', 'run_command', {'command': 'ls'}, 'error')
        tracker.record_failure('command_failed', 'run_command', {'command': 'pwd'}, 'error')
        tracker.record_failure('file_not_found', 'read_file', {'file_path': '/missing.txt'}, 'not found')
        tracker.record_failure('file_not_found', 'read_file', {'file_path': '/other.txt'}, 'not found')

        # Both should be at limit
        allowed_cmd, _ = tracker.should_allow_retry('run_command', 'command_failed')
        allowed_read, _ = tracker.should_allow_retry('read_file', 'file_not_found')
        assert allowed_cmd is False
        assert allowed_read is False

        # Reset only run_command
        tracker.reset_tool_error_counts(tool_name='run_command')

        # run_command should be allowed now, read_file still blocked
        allowed_cmd, _ = tracker.should_allow_retry('run_command', 'command_failed')
        allowed_read, _ = tracker.should_allow_retry('read_file', 'file_not_found')
        assert allowed_cmd is True  # Reset worked
        assert allowed_read is False  # Still blocked

    def test_total_failures_property(self):
        """Test that total_failures property works correctly."""
        tracker = ErrorRecoveryTracker()

        assert tracker.total_failures == 0

        tracker.record_failure('error1', 'tool1', {}, 'msg')
        assert tracker.total_failures == 1

        tracker.record_failure('error2', 'tool2', {}, 'msg')
        assert tracker.total_failures == 2

        # Partial reset doesn't affect total_failures
        tracker.reset_tool_error_counts()
        assert tracker.total_failures == 2

        # Full reset clears total_failures
        tracker.reset()
        assert tracker.total_failures == 0

    def test_signature_blocker_survives_partial_reset(self):
        """
        Test that exact same calls remain blocked after partial reset.

        The signature blocker (is_repeated_failed_call) should NOT be cleared
        by partial reset - only by full reset.
        """
        tracker = ErrorRecoveryTracker()

        # Record a specific failure
        tracker.record_failure('error', 'run_command', {'command': 'npm install'}, 'failed')

        # Should be blocked
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'npm install'})
        assert is_repeat is True

        # Partial reset
        tracker.reset_tool_error_counts()

        # Still blocked!
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'npm install'})
        assert is_repeat is True

        # Full reset clears it
        tracker.reset()
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'npm install'})
        assert is_repeat is False

    def test_different_error_types_have_separate_budgets(self):
        """
        Test that different error types for the same tool have separate budgets.
        """
        tracker = ErrorRecoveryTracker(max_same_tool_error_failures=2)

        # Two 'command_failed' errors
        tracker.record_failure('command_failed', 'run_command', {'command': 'ls'}, 'error')
        tracker.record_failure('command_failed', 'run_command', {'command': 'pwd'}, 'error')

        # 'command_failed' should be at limit
        allowed, _ = tracker.should_allow_retry('run_command', 'command_failed')
        assert allowed is False

        # But 'timeout' error type should have its own budget
        allowed, _ = tracker.should_allow_retry('run_command', 'timeout')
        assert allowed is True

        # And can fail separately
        tracker.record_failure('timeout', 'run_command', {'command': 'slow-cmd'}, 'timed out')
        allowed, _ = tracker.should_allow_retry('run_command', 'timeout')
        assert allowed is True  # Only 1 of 2 used

    def test_get_stats(self):
        """Test that get_stats returns correct statistics."""
        tracker = ErrorRecoveryTracker()

        tracker.record_failure('error1', 'tool1', {'arg': 'val1'}, 'msg')
        tracker.record_failure('error2', 'tool1', {'arg': 'val2'}, 'msg')
        tracker.record_failure('error1', 'tool2', {'arg': 'val3'}, 'msg')

        stats = tracker.get_stats()

        assert stats['total_failures'] == 3
        assert stats['unique_failed_calls'] == 3
        assert ('tool1', 'error1') in stats['failed_tool_error_counts']
        assert ('tool1', 'error2') in stats['failed_tool_error_counts']
        assert ('tool2', 'error1') in stats['failed_tool_error_counts']

    def test_normalization_catches_wiggling(self):
        """
        Test that argument normalization catches 'wiggling' attacks.

        The LLM might try to bypass the signature blocker by adding extra
        whitespace or changing path separators.
        """
        tracker = ErrorRecoveryTracker()

        # Original failure
        tracker.record_failure('error', 'run_command', {'command': 'ls -la'}, 'failed')

        # These should all be detected as the same call (normalized)
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'ls  -la'})  # Extra space
        assert is_repeat is True

        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': ' ls -la '})  # Leading/trailing
        assert is_repeat is True

        # Different command should not be blocked
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'ls -l'})
        assert is_repeat is False
