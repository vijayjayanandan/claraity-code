"""
Tests for LLM Failure Handler

Tests error classification, retry logic, exponential backoff,
rate limit handling, timeout handling, and response validation.
"""

import time
import pytest
from unittest.mock import Mock, patch
import logging

from src.llm.failure_handler import (
    LLMFailureHandler,
    LLMError,
    RateLimitError,
    TimeoutError,
    ValidationError,
    InvalidAPIKeyError,
    InvalidModelError,
    ContextLengthExceededError,
    ContentPolicyViolationError,
)


class TestErrorClassification:
    """Test error classification as retryable vs fatal."""

    def test_retryable_timeout_error(self):
        """Test timeout errors are classified as retryable."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Request timed out after 30s")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is True
        assert "timeout" in msg.lower() or "timed out" in msg.lower()

    def test_retryable_rate_limit_error(self):
        """Test rate limit errors are classified as retryable."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Rate limit exceeded, please retry after 60s")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is True
        assert "rate" in msg.lower() or "retryable" in msg.lower()

    def test_retryable_service_unavailable(self):
        """Test 503 service unavailable is retryable."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("503 Service Temporarily Unavailable")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is True

    def test_retryable_connection_error(self):
        """Test connection errors are retryable."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Connection failed: Network is unreachable")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is True

    def test_fatal_invalid_api_key(self):
        """Test invalid API key is fatal."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("401 Unauthorized: Invalid API key provided")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False
        assert "fatal" in msg.lower()

    def test_fatal_invalid_model(self):
        """Test invalid model is fatal."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("404 Model not found: gpt-99 does not exist")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False
        assert "fatal" in msg.lower()

    def test_fatal_context_length_exceeded(self):
        """Test context length exceeded is fatal."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Maximum context length exceeded (4096 tokens)")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False
        assert "fatal" in msg.lower()

    def test_fatal_authentication_error(self):
        """Test authentication errors are fatal."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Authentication failed: Check your API key")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False

    def test_unknown_error_defaults_retryable(self):
        """Test unknown errors default to retryable (conservative)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Unknown mysterious error XYZ123")

        is_retryable, msg = handler.handle_api_error(error)

        # Conservative approach: retry unknown errors
        assert is_retryable is True
        assert "unknown" in msg.lower()


class TestExponentialBackoff:
    """Test exponential backoff retry logic."""

    def test_successful_first_attempt(self):
        """Test successful execution on first attempt (no retry)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that succeeds immediately
        mock_func = Mock(return_value="success")

        result = handler.execute_with_retry(mock_func, max_attempts=3)

        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_on_transient_error(self):
        """Test retry on transient error (succeeds on 2nd attempt)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that fails once then succeeds
        mock_func = Mock(side_effect=[
            Exception("timeout error"),
            "success"
        ])

        start_time = time.time()
        result = handler.execute_with_retry(mock_func, max_attempts=3)
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 2
        # Should have 1s delay (2^0 = 1)
        assert elapsed >= 0.9  # Allow 100ms margin

    def test_exponential_backoff_timing(self):
        """Test exponential backoff delays: 1s, 2s, 4s progression."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that fails 3 times then succeeds
        mock_func = Mock(side_effect=[
            Exception("timeout"),
            Exception("timeout"),
            Exception("timeout"),
            "success"
        ])

        start_time = time.time()
        result = handler.execute_with_retry(mock_func, max_attempts=5, backoff_base=2.0)
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 4
        # Should have delays: 1s + 2s + 4s = 7s
        assert elapsed >= 6.9  # Allow 100ms margin
        assert elapsed < 8.0  # Should not take too long

    def test_max_attempts_exhausted(self):
        """Test failure after max attempts exhausted."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that always fails
        mock_func = Mock(side_effect=Exception("timeout"))

        with pytest.raises(LLMError) as exc_info:
            handler.execute_with_retry(mock_func, max_attempts=3)

        assert "Failed after 3 attempts" in str(exc_info.value)
        assert mock_func.call_count == 3

    def test_fatal_error_no_retry(self):
        """Test fatal error stops retry immediately."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that returns fatal error
        mock_func = Mock(side_effect=Exception("401 Invalid API key"))

        with pytest.raises(LLMError) as exc_info:
            handler.execute_with_retry(mock_func, max_attempts=5)

        # Should fail immediately, not retry
        assert mock_func.call_count == 1
        assert "fatal" in str(exc_info.value).lower()

    def test_custom_backoff_base(self):
        """Test custom backoff base (3.0 instead of 2.0)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that fails twice
        mock_func = Mock(side_effect=[
            Exception("timeout"),
            Exception("timeout"),
            "success"
        ])

        start_time = time.time()
        result = handler.execute_with_retry(mock_func, max_attempts=3, backoff_base=3.0)
        elapsed = time.time() - start_time

        assert result == "success"
        # Should have delays: 3^0=1s + 3^1=3s = 4s
        assert elapsed >= 3.9  # Allow 100ms margin


class TestRateLimitHandling:
    """Test rate limit specific handling."""

    def test_rate_limit_detection(self):
        """Test rate limit error is detected and retried."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that hits rate limit then succeeds
        mock_func = Mock(side_effect=[
            Exception("429 Rate limit exceeded"),
            "success"
        ])

        result = handler.handle_rate_limit(mock_func, max_retries=3)

        assert result == "success"
        assert mock_func.call_count == 2

    def test_rate_limit_longer_delays(self):
        """Test rate limit uses longer delays (10s base)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that hits rate limit twice
        mock_func = Mock(side_effect=[
            Exception("rate_limit_exceeded"),
            Exception("too many requests"),
            "success"
        ])

        start_time = time.time()
        result = handler.handle_rate_limit(mock_func, max_retries=3)
        elapsed = time.time() - start_time

        assert result == "success"
        # Should have delays: 10s + 20s = 30s
        assert elapsed >= 29.9  # Allow 100ms margin

    def test_rate_limit_max_retries(self):
        """Test rate limit respects max_retries."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that always rate limits
        mock_func = Mock(side_effect=Exception("Rate limit exceeded"))

        with pytest.raises(RateLimitError) as exc_info:
            handler.handle_rate_limit(mock_func, max_retries=2)

        assert mock_func.call_count == 2
        assert "after 2 attempts" in str(exc_info.value)

    def test_non_rate_limit_error_raises(self):
        """Test non-rate-limit errors are raised immediately."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function with fatal error
        mock_func = Mock(side_effect=Exception("Invalid API key"))

        with pytest.raises(LLMError):
            handler.handle_rate_limit(mock_func, max_retries=3)

        # Should not retry non-rate-limit errors
        assert mock_func.call_count == 1


class TestTimeoutHandling:
    """Test timeout specific handling."""

    def test_timeout_detection(self):
        """Test timeout error is detected and retried."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that times out then succeeds
        mock_func = Mock(side_effect=[
            Exception("Request timed out"),
            "success"
        ])

        result = handler.handle_timeout(mock_func, timeout_seconds=30.0, max_retries=3)

        assert result == "success"
        assert mock_func.call_count == 2

    def test_timeout_increasing_timeout(self):
        """Test timeout increases on each retry (30s, 45s, 67.5s)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Note: This test verifies retry logic, not actual timeout enforcement
        # (timeout enforcement is handled by the LLM backend's httpx.Timeout)

        # Mock function that times out twice then succeeds
        mock_func = Mock(side_effect=[
            Exception("timeout"),
            Exception("timed out"),
            "success"
        ])

        result = handler.handle_timeout(mock_func, timeout_seconds=30.0, max_retries=3)

        assert result == "success"
        assert mock_func.call_count == 3

    def test_timeout_max_retries(self):
        """Test timeout respects max_retries."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function that always times out
        mock_func = Mock(side_effect=Exception("timeout"))

        with pytest.raises(TimeoutError) as exc_info:
            handler.handle_timeout(mock_func, timeout_seconds=10.0, max_retries=2)

        assert mock_func.call_count == 2
        assert "after 2 attempts" in str(exc_info.value)

    def test_non_timeout_error_raises(self):
        """Test non-timeout errors are raised immediately."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Mock function with fatal error
        mock_func = Mock(side_effect=Exception("Invalid model"))

        with pytest.raises(LLMError):
            handler.handle_timeout(mock_func, timeout_seconds=30.0, max_retries=3)

        # Should not retry non-timeout errors
        assert mock_func.call_count == 1


class TestResponseValidation:
    """Test response validation."""

    def test_valid_response(self):
        """Test valid response passes validation."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        result = handler.validate_response("This is a valid response")

        assert result is True

    def test_none_response_fails(self):
        """Test None response fails validation."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        with pytest.raises(ValidationError) as exc_info:
            handler.validate_response(None)

        assert "None" in str(exc_info.value)

    def test_empty_string_fails(self):
        """Test empty string fails validation."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        with pytest.raises(ValidationError) as exc_info:
            handler.validate_response("")

        assert "empty" in str(exc_info.value).lower()

    def test_whitespace_only_fails(self):
        """Test whitespace-only response fails validation."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        with pytest.raises(ValidationError) as exc_info:
            handler.validate_response("   \n\t   ")

        assert "empty" in str(exc_info.value).lower() or "whitespace" in str(exc_info.value).lower()

    def test_non_string_fails(self):
        """Test non-string response fails validation."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        with pytest.raises(ValidationError) as exc_info:
            handler.validate_response(12345)

        assert "not a string" in str(exc_info.value)

    def test_valid_multiline_response(self):
        """Test valid multiline response passes."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        response = """Line 1
Line 2
Line 3"""

        result = handler.validate_response(response)

        assert result is True


class TestDecoratorInterface:
    """Test decorator interface for retry logic."""

    def test_decorator_success(self):
        """Test @with_retry decorator on successful function."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        @handler.with_retry(max_attempts=3)
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success"

    def test_decorator_retry(self):
        """Test @with_retry decorator retries on failure."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Create a stateful function that fails once then succeeds
        call_count = [0]

        @handler.with_retry(max_attempts=3)
        def flaky_func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("timeout")
            return "success"

        result = flaky_func()
        assert result == "success"
        assert call_count[0] == 2

    def test_decorator_with_args(self):
        """Test @with_retry decorator preserves function arguments."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        @handler.with_retry(max_attempts=3)
        def func_with_args(a, b, c=10):
            return a + b + c

        result = func_with_args(1, 2, c=3)
        assert result == 6


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""

    def test_transient_network_issue_recovers(self):
        """Test recovery from transient network issue."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Simulate network blip: fail twice, then succeed
        mock_llm = Mock(side_effect=[
            Exception("Connection reset by peer"),
            Exception("503 Service Unavailable"),
            "LLM response text"
        ])

        result = handler.execute_with_retry(mock_llm, max_attempts=5)

        assert result == "LLM response text"
        assert mock_llm.call_count == 3

    def test_permanent_auth_failure_fast(self):
        """Test fast failure on permanent auth error."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Simulate invalid API key
        mock_llm = Mock(side_effect=Exception("401 Unauthorized: Invalid API key"))

        start_time = time.time()
        with pytest.raises(LLMError):
            handler.execute_with_retry(mock_llm, max_attempts=5)
        elapsed = time.time() - start_time

        # Should fail immediately (< 0.1s), not retry
        assert elapsed < 0.1
        assert mock_llm.call_count == 1

    def test_rate_limit_then_timeout(self):
        """Test handling rate limit followed by timeout."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Simulate rate limit, then timeout, then success
        mock_llm = Mock(side_effect=[
            Exception("429 Too Many Requests"),
            Exception("Request timed out"),
            "success"
        ])

        # Use standard retry (not rate_limit specific) to handle both
        result = handler.execute_with_retry(mock_llm, max_attempts=5)

        assert result == "success"
        assert mock_llm.call_count == 3


class TestDelayCaps:
    """Test delay caps prevent DoS vulnerability."""

    def test_max_backoff_delay_cap(self):
        """Test delays are capped at max_backoff_delay."""
        handler = LLMFailureHandler(max_backoff_delay=10.0, enable_jitter=False)

        mock_func = Mock(side_effect=[
            Exception("timeout"),
            Exception("timeout"),
            Exception("timeout"),
            Exception("timeout"),
            Exception("timeout"),
            "success"
        ])

        start_time = time.time()
        result = handler.execute_with_retry(mock_func, max_attempts=6, backoff_base=2.0)
        elapsed = time.time() - start_time

        # Without cap: 1s + 2s + 4s + 8s + 16s = 31s
        # With 10s cap: 1s + 2s + 4s + 8s + 10s = 25s (cap kicks in at attempt 5)
        assert result == "success"
        assert elapsed >= 24.9 and elapsed < 27.0
        assert mock_func.call_count == 6

    def test_max_rate_limit_delay_cap(self):
        """Test rate limit delays are capped at max_rate_limit_delay."""
        handler = LLMFailureHandler(max_rate_limit_delay=20.0, enable_jitter=False)

        mock_func = Mock(side_effect=[
            Exception("429 Rate limit exceeded"),
            Exception("429 Rate limit exceeded"),
            Exception("429 Rate limit exceeded"),
            "success"
        ])

        start_time = time.time()
        result = handler.handle_rate_limit(mock_func, max_retries=4)
        elapsed = time.time() - start_time

        # Without cap: 10s + 20s + 40s = 70s
        # With 20s cap: 10s + 20s + 20s = 50s (cap kicks in at attempt 3)
        assert result == "success"
        assert elapsed >= 49.9 and elapsed < 52.0


class TestJitter:
    """Test jitter prevents thundering herd."""

    def test_full_jitter_randomizes_delay(self):
        """Test full jitter produces random delays."""
        handler = LLMFailureHandler(
            max_backoff_delay=15.0,
            enable_jitter=True,
            jitter_type="full"
        )

        # Collect jittered delays
        delays = []
        for _ in range(10):
            base_delay = 10.0
            max_delay = 15.0
            delay = handler._calculate_delay(base_delay, max_delay)
            delays.append(delay)

        # All delays should be different (very high probability)
        assert len(set(delays)) >= 8  # At least 8 out of 10 different

        # All delays should be between 0 and min(base, max)
        assert all(0 <= d <= 10.0 for d in delays)

    def test_equal_jitter_balances_delay(self):
        """Test equal jitter provides balanced randomization."""
        handler = LLMFailureHandler(
            enable_jitter=True,
            jitter_type="equal"
        )

        delays = []
        for _ in range(10):
            base_delay = 10.0
            max_delay = 15.0
            delay = handler._calculate_delay(base_delay, max_delay)
            delays.append(delay)

        # Equal jitter: delay/2 + random(0, delay/2)
        # So delays should be between 5 and 10
        assert all(4.0 <= d <= 10.5 for d in delays)

    def test_no_jitter_uses_exact_delay(self):
        """Test jitter can be disabled."""
        handler = LLMFailureHandler(enable_jitter=False)

        # All delays should be exactly the same
        delays = []
        for _ in range(5):
            base_delay = 10.0
            max_delay = 15.0
            delay = handler._calculate_delay(base_delay, max_delay)
            delays.append(delay)

        assert all(d == 10.0 for d in delays)


class TestThreadSafety:
    """Test handler is thread-safe under concurrent load."""

    def test_concurrent_retries_thread_safe(self):
        """Test handler is thread-safe with concurrent calls."""
        import threading

        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        results = []
        errors = []

        def worker(worker_id):
            try:
                # Each worker has different failure pattern
                mock_func = Mock(side_effect=[
                    Exception("timeout") if worker_id % 2 == 0 else Exception("rate_limit"),
                    f"success_{worker_id}"
                ])
                result = handler.execute_with_retry(mock_func, max_attempts=3)
                results.append(result)
            except Exception as e:
                errors.append((worker_id, str(e)))

        # Run 10 workers concurrently
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should succeed independently
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 10
        assert all("success_" in r for r in results)

    def test_concurrent_rate_limit_handlers(self):
        """Test multiple rate limit handlers run concurrently."""
        import threading

        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        results = []

        def worker(worker_id):
            mock_func = Mock(side_effect=[
                Exception("429 Rate limit"),
                f"success_{worker_id}"
            ])
            result = handler.handle_rate_limit(mock_func, max_retries=3)
            results.append(result)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert all("success_" in r for r in results)


class TestEnhancedValidation:
    """Test enhanced response validation features."""

    def test_truncation_detection(self):
        """Test truncation detection for responses ending mid-sentence."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Response ending with proper punctuation should pass
        valid_response = "This is a complete sentence."
        assert handler.validate_response(valid_response) is True

        # Response ending mid-word should trigger warning (but still pass)
        truncated_response = "This is a truncated resp"
        # Should not raise, but should log warning
        assert handler.validate_response(truncated_response) is True

    def test_repetition_loop_detection(self):
        """Test detection of repetition loops."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Normal response should pass
        normal_response = "The quick brown fox jumps over the lazy dog"
        assert handler.validate_response(normal_response) is True

        # Repetition loop should fail
        repetitive_response = "the the the the the the the the"
        with pytest.raises(ValidationError) as exc_info:
            handler.validate_response(repetitive_response)
        assert "repetition loop" in str(exc_info.value).lower()

    def test_json_format_validation(self):
        """Test JSON format validation."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Valid JSON should pass
        valid_json = '{"key": "value", "number": 42}'
        assert handler.validate_response(valid_json, expected_format="json") is True

        # Invalid JSON should fail
        invalid_json = '{"key": "value", "number": '  # Truncated
        with pytest.raises(ValidationError) as exc_info:
            handler.validate_response(invalid_json, expected_format="json")
        assert "invalid json" in str(exc_info.value).lower()

    def test_code_bracket_validation(self):
        """Test code validation detects unclosed brackets."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Well-formed code should pass
        valid_code = "def hello():\n    return {'key': 'value'}"
        assert handler.validate_response(valid_code, expected_format="code") is True

        # Code with many unclosed brackets should trigger warning
        unclosed_code = "def hello() {\n    if (true) {\n        return [1, 2, 3\n"
        # Should not raise, but should log warning
        assert handler.validate_response(unclosed_code, expected_format="code") is True


class TestErrorSanitization:
    """Test error message sanitization."""

    def test_ansi_escape_code_removal(self):
        """Test ANSI escape codes are removed from errors."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Error with ANSI codes
        error = Exception("\x1b[31mCritical Error\x1b[0m: Something failed")
        sanitized = handler._sanitize_error_message(error)

        # ANSI codes should be stripped
        assert "\x1b[" not in sanitized
        assert "Critical Error" in sanitized

    def test_long_message_truncation(self):
        """Test long error messages are truncated."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)

        # Very long error message
        long_message = "Error: " + ("x" * 300)
        error = Exception(long_message)
        sanitized = handler._sanitize_error_message(error, max_length=200)

        # Message should be truncated
        assert len(sanitized) <= 220  # 200 + "... (truncated)" + some margin
        assert "truncated" in sanitized
        assert len(sanitized) < len(long_message)  # Definitely shorter than original


class TestUserProgress:
    """Test user-facing progress notifications."""

    def test_progress_notifications_shown(self):
        """Test retry progress is shown to user."""
        handler = LLMFailureHandler(show_progress=True, enable_jitter=False)

        # Mock safe_print to capture output
        with patch('src.llm.failure_handler.safe_print') as mock_print:
            mock_func = Mock(side_effect=[
                Exception("timeout"),
                "success"
            ])

            result = handler.execute_with_retry(mock_func, max_attempts=3)

            # Should have called safe_print for retry and success
            assert mock_print.call_count >= 2
            calls = [str(call) for call in mock_print.call_args_list]
            assert any("[RETRY]" in str(call) for call in calls)
            assert any("[OK]" in str(call) for call in calls)

    def test_progress_can_be_disabled(self):
        """Test progress notifications can be disabled."""
        handler = LLMFailureHandler(show_progress=False, enable_jitter=False)

        with patch('src.llm.failure_handler.safe_print') as mock_print:
            mock_func = Mock(side_effect=[
                Exception("timeout"),
                "success"
            ])

            result = handler.execute_with_retry(mock_func, max_attempts=3)

            # Should not have called safe_print
            assert mock_print.call_count == 0

    def test_countdown_for_long_delays(self):
        """Test countdown is shown for delays > threshold."""
        handler = LLMFailureHandler(
            show_progress=True,
            enable_jitter=False,
            progress_countdown_threshold=5.0,
            max_backoff_delay=15.0
        )

        with patch('src.llm.failure_handler.safe_print') as mock_print:
            # Force a long delay (15s)
            mock_func = Mock(side_effect=[
                Exception("timeout"),
                Exception("timeout"),
                Exception("timeout"),
                Exception("timeout"),
                "success"
            ])

            start_time = time.time()
            result = handler.execute_with_retry(mock_func, max_attempts=5, backoff_base=2.0)
            elapsed = time.time() - start_time

            # Should show countdown (multiple safe_print calls)
            assert mock_print.call_count > 5  # Multiple countdown updates


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
