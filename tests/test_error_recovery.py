"""
Tests for ErrorRecoveryTracker - failure tracking and repeat detection.

Note: should_allow_retry() always returns True (error budget pause disabled).
The iteration limit is now the sole mechanism for pausing on repeated failures.
"""

import pytest
from src.core.error_recovery import ErrorRecoveryTracker


class TestErrorRecoveryTracker:
    """Test suite for ErrorRecoveryTracker."""

    def test_should_allow_retry_always_true(self):
        """should_allow_retry always returns True (error budget disabled)."""
        tracker = ErrorRecoveryTracker(max_same_tool_error_failures=2)

        # Record failures past the old threshold
        tracker.record_failure('command_failed', 'run_command', {'command': 'ls -la'}, 'error')
        tracker.record_failure('command_failed', 'run_command', {'command': 'pwd'}, 'error')
        tracker.record_failure('command_failed', 'run_command', {'command': 'echo'}, 'error')

        # Always allowed now
        allowed, _ = tracker.should_allow_retry('run_command', 'command_failed')
        assert allowed is True

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

        # Should be blocked (exact same args)
        is_repeat, summary = tracker.is_repeated_failed_call('run_command', {'command': 'npm install'})
        assert is_repeat is True
        assert 'run_command' in summary

        # Different args should NOT be blocked
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'npm test'})
        assert is_repeat is False

        # Partial reset should NOT clear signature blocker
        tracker.reset_tool_error_counts()
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'npm install'})
        assert is_repeat is True  # Still blocked!

        # Full reset SHOULD clear signature blocker
        tracker.reset()
        is_repeat, _ = tracker.is_repeated_failed_call('run_command', {'command': 'npm install'})
        assert is_repeat is False  # Now allowed

    def test_record_failure_returns_error_context(self):
        """Test that record_failure returns structured ErrorContext."""
        tracker = ErrorRecoveryTracker()

        ctx = tracker.record_failure(
            'command_failed', 'run_command',
            {'command': 'ls -la'}, 'Permission denied',
            exit_code=1,
            stdout='', stderr='Permission denied',
        )

        assert ctx.error_type == 'command_failed'
        assert ctx.tool_name == 'run_command'
        assert ctx.error_message == 'Permission denied'
        assert ctx.exit_code == 1

    def test_get_stats(self):
        """Test that get_stats returns correct summary."""
        tracker = ErrorRecoveryTracker()

        tracker.record_failure('err1', 'tool1', {}, 'msg1')
        tracker.record_failure('err1', 'tool1', {}, 'msg2')
        tracker.record_failure('err2', 'tool2', {}, 'msg3')

        stats = tracker.get_stats()
        assert stats['total_failures'] == 3
