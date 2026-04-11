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
    NetworkError,
    ValidationError,
    InvalidAPIKeyError,
    InvalidModelError,
    InvalidRequestError,
    ContextLengthExceededError,
    ContentPolicyViolationError,
    classify_provider_error,
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
        assert msg  # has a user-friendly message

    def test_fatal_invalid_model(self):
        """Test invalid model is fatal."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("404 Model not found: gpt-99 does not exist")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False
        assert msg

    def test_fatal_context_length_exceeded(self):
        """Test context length exceeded is fatal."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Maximum context length exceeded (4096 tokens)")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False
        assert msg

    def test_fatal_authentication_error(self):
        """Test authentication_error signal is fatal (specific signal, not bare word)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("authentication_error: Check your API key")

        is_retryable, msg = handler.handle_api_error(error)

        assert is_retryable is False

    def test_unknown_error_defaults_retryable(self):
        """Test unknown errors default to retryable (conservative)."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        error = Exception("Unknown mysterious error XYZ123")

        is_retryable, msg = handler.handle_api_error(error)

        # Conservative approach: retry unknown errors
        assert is_retryable is True
        assert msg  # has some user-facing message


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

        # Should fail immediately, not retry, and raise a typed non-retryable exception
        assert mock_func.call_count == 1
        assert exc_info.value.retryable is False

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


class TestClassifyProviderError:
    """Tests for the centralized classify_provider_error() classifier."""

    # -- Typed returns --

    def test_timeout_returns_timeout_error(self):
        result = classify_provider_error(Exception("Request timed out after 30s"))
        assert isinstance(result, TimeoutError)
        assert result.event_type == "provider_timeout"
        assert result.retryable is True

    def test_rate_limit_returns_rate_limit_error(self):
        result = classify_provider_error(Exception("429 Too Many Requests"))
        assert isinstance(result, RateLimitError)
        assert result.event_type == "rate_limit"
        assert result.retryable is True

    def test_network_returns_network_error(self):
        result = classify_provider_error(Exception("Connection reset by peer"))
        assert isinstance(result, NetworkError)
        assert result.event_type == "network"
        assert result.retryable is True

    def test_invalid_api_key_via_401(self):
        result = classify_provider_error(Exception("401 Unauthorized: bad credentials"))
        assert isinstance(result, InvalidAPIKeyError)
        assert result.event_type == "config_error"
        assert result.retryable is False

    def test_invalid_api_key_via_signal(self):
        result = classify_provider_error(Exception("invalid_api_key: The key is wrong"))
        assert isinstance(result, InvalidAPIKeyError)
        assert result.retryable is False

    def test_invalid_model_via_signal(self):
        result = classify_provider_error(Exception("invalid_model: gpt-99 does not exist"))
        assert isinstance(result, InvalidModelError)
        assert result.event_type == "config_error"
        assert result.retryable is False
        assert "API configuration error" in result.user_message

    def test_invalid_model_via_404(self):
        result = classify_provider_error(Exception("404 model not found"))
        assert isinstance(result, InvalidModelError)
        assert result.retryable is False

    def test_content_policy_is_distinct_from_config_error(self):
        result = classify_provider_error(Exception("content_policy_violation: request refused"))
        assert isinstance(result, ContentPolicyViolationError)
        assert result.event_type == "content_policy"  # NOT "config_error"
        assert result.retryable is False

    def test_content_policy_not_labeled_api_config_error(self):
        result = classify_provider_error(Exception("content policy violation detected"))
        assert result.event_type == "content_policy"
        assert "content policy" in result.user_message.lower()

    def test_invalid_request_bad_temperature(self):
        result = classify_provider_error(Exception("invalid value for 'temperature': must be between 0 and 2"))
        assert isinstance(result, InvalidRequestError)
        assert result.event_type == "config_error"
        assert result.retryable is False
        assert "API configuration error" in result.user_message

    def test_invalid_request_bad_max_tokens(self):
        result = classify_provider_error(Exception("max_tokens must be a positive integer"))
        assert isinstance(result, InvalidRequestError)
        assert result.retryable is False

    def test_invalid_request_error_string(self):
        result = classify_provider_error(Exception("invalid_request_error: bad parameter"))
        assert isinstance(result, InvalidRequestError)
        assert result.retryable is False

    def test_context_length_exceeded(self):
        result = classify_provider_error(Exception("maximum context length exceeded (128k tokens)"))
        assert isinstance(result, ContextLengthExceededError)
        assert result.retryable is False

    def test_unknown_error_is_retryable(self):
        result = classify_provider_error(Exception("Unknown mysterious provider error XYZ"))
        assert result.retryable is True

    # -- False positive prevention --

    def test_bare_authentication_word_not_classified_as_api_key_error(self):
        """Broad 'authentication' in user code errors should NOT trigger InvalidAPIKeyError."""
        result = classify_provider_error(Exception("authentication required for user login endpoint"))
        assert not isinstance(result, InvalidAPIKeyError)

    def test_bare_unauthorized_not_classified_as_api_key_error(self):
        """Broad 'unauthorized' should NOT trigger InvalidAPIKeyError."""
        result = classify_provider_error(Exception("user is unauthorized to access this resource"))
        assert not isinstance(result, InvalidAPIKeyError)

    def test_bare_invalid_request_not_classified_alone(self):
        """Bare 'invalid_request' (without _error suffix) should not classify as InvalidRequestError
        when accompanied by content policy signals -- content policy takes precedence."""
        result = classify_provider_error(Exception("content policy violation invalid_request"))
        assert isinstance(result, ContentPolicyViolationError)

    # -- Anthropic bytes payload extraction --

    def test_anthropic_bytes_payload_extraction(self):
        """Anthropic SDK wraps errors as bytes literal strings -- classifier extracts the message."""
        # Simulate what str(root_cause) looks like for an Anthropic error.
        # The SDK produces: b'{"type":"error","error":{"message":"..."}}'
        payload = '{"type":"error","error":{"message":"model not found: claude-99 does not exist"}}'
        exc = Exception(f'b"{payload}"')
        result = classify_provider_error(exc)
        # Should classify based on extracted content; model not found -> InvalidModelError
        assert isinstance(result, InvalidModelError)
        assert "API configuration error" in result.user_message

    # -- Already-classified passthrough --

    def test_already_classified_exception_passed_through(self):
        """If the exception is already an LLMError subclass, return it unchanged."""
        original = InvalidAPIKeyError("already classified", user_message="My custom message")
        result = classify_provider_error(original)
        assert result is original
        assert result.user_message == "My custom message"

    # -- Production log reproduction (real exception chains from logs) --

    def test_production_thinking_budget_too_low(self):
        """Exact exception chain from production log: thinking_budget below minimum.

        Chain: RuntimeError -> APIError
        root_cause_message contains litellm-wrapped Anthropic bytes payload.
        """
        inner = Exception(
            "litellm.BadRequestError: AnthropicException - "
            "b'{\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\","
            "\"message\":\"thinking.enabled.budget_tokens: Input should be greater than or equal to 1024\"}}'"
            " LiteLLM Retried: 1 times"
        )
        outer = RuntimeError("OpenAI async provider delta error: APIError: " + str(inner))
        outer.__cause__ = inner

        result = classify_provider_error(outer)

        assert isinstance(result, InvalidRequestError)
        assert result.event_type == "config_error"
        assert result.retryable is False
        # Provider message preserved (constraint value from API, not hardcoded)
        assert "greater than or equal to 1024" in result.user_message
        # Field path prefix stripped ("thinking.enabled.budget_tokens:" not shown)
        assert "thinking.enabled.budget_tokens" not in result.user_message
        # Actionable hint appended
        assert "Settings > Thinking Budget" in result.user_message

    def test_production_invalid_model_403(self):
        """Exact exception chain from production log: invalid model name returns 403.

        Chain: RuntimeError -> PermissionDeniedError
        Provider uses 403 with ModelAuthorizationError for unrecognised model names.
        Must NOT classify as NetworkError or InvalidAPIKeyError.
        """
        inner = Exception(
            "Error code: 403 - {'error': {'message': "
            "\"Authorization failed for model 'claude-sonnet-4-62'. "
            "The model may be unavailable, retired, or not enabled for your organization. "
            "If your API key is valid, verify the model name is correct and currently supported.\", "
            "'type': 'basicllm.schemas.errors.ModelAuthorizationError', "
            "'param': {'model': 'claude-sonnet-4-62'}, 'code': 403}}"
        )
        outer = RuntimeError("OpenAI async provider delta error: PermissionDeniedError: " + str(inner))
        outer.__cause__ = inner

        result = classify_provider_error(outer)

        assert isinstance(result, InvalidModelError), (
            f"Expected InvalidModelError, got {type(result).__name__}: {result.user_message}"
        )
        assert result.event_type == "config_error"
        assert result.retryable is False
        assert "API configuration error" in result.user_message

    # -- handle_api_error backward compat --

    def test_handle_api_error_still_returns_tuple(self):
        """handle_api_error() must still return (bool, str) for all existing callers."""
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        is_retryable, msg = handler.handle_api_error(Exception("timeout"))
        assert isinstance(is_retryable, bool)
        assert isinstance(msg, str)
        assert is_retryable is True

    def test_handle_api_error_fatal_returns_false(self):
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        is_retryable, msg = handler.handle_api_error(Exception("401 invalid_api_key"))
        assert is_retryable is False
        assert msg

    def test_handle_api_error_content_policy_is_fatal(self):
        handler = LLMFailureHandler(enable_jitter=False, show_progress=False)
        is_retryable, msg = handler.handle_api_error(Exception("content_policy_violation"))
        assert is_retryable is False


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])


class TestHumanizeConfigError:
    """Tests for _humanize_config_error() and the full classify -> user_message pipeline."""

    def test_field_path_prefix_stripped(self):
        """Dotted field path prefix is removed; constraint value is preserved."""
        exc = Exception("thinking.enabled.budget_tokens: Input should be greater than or equal to 1024")
        result = classify_provider_error(exc)
        assert "thinking.enabled.budget_tokens" not in result.user_message
        assert "greater than or equal to 1024" in result.user_message
        assert "Settings > Thinking Budget" in result.user_message

    def test_no_field_path_prefix_unchanged(self):
        """Messages without a dotted prefix are passed through as-is."""
        exc = Exception("temperature must be between 0 and 2")
        result = classify_provider_error(exc)
        assert "temperature must be between 0 and 2" in result.user_message.lower()
        assert "Settings > Temperature" in result.user_message

    def test_max_tokens_hint(self):
        """max_tokens validation error maps to Settings > Max Tokens."""
        exc = Exception("max_tokens must not exceed 4096 for this model")
        result = classify_provider_error(exc)
        assert "Settings > Max Tokens" in result.user_message

    def test_ansi_codes_stripped_once_in_extract(self):
        """ANSI escape codes in the root message are stripped before humanization."""
        exc = Exception("\x1b[31mbudget_tokens: Input should be greater than or equal to 1024\x1b[0m")
        result = classify_provider_error(exc)
        assert "\x1b[" not in result.user_message
        assert "greater than or equal to 1024" in result.user_message

    def test_false_positive_generic_phrase_without_config_field(self):
        """'greater than or equal to' alone does NOT trigger InvalidRequestError."""
        exc = Exception("Value must be greater than or equal to the threshold")
        result = classify_provider_error(exc)
        assert not isinstance(result, InvalidRequestError)

    def test_sentence_boundary_truncation(self):
        """Long messages are truncated at a sentence boundary, not mid-word."""
        long_msg = ("budget_tokens: " + "This is sentence one. " * 10 +
                    "This is sentence two. " * 10)
        exc = Exception(long_msg)
        result = classify_provider_error(exc)
        # Must not cut mid-sentence (no trailing partial word before hint)
        msg = result.user_message
        hint_pos = msg.find(" Go to ")
        if hint_pos > 0:
            before_hint = msg[:hint_pos]
            assert before_hint.endswith("."), f"Expected sentence boundary before hint, got: {before_hint[-20:]!r}"

    def test_period_added_before_hint(self):
        """A period is inserted between the provider message and the hint if missing."""
        exc = Exception("budget_tokens: Input should be greater than or equal to 1024")
        result = classify_provider_error(exc)
        # hint must be preceded by ". Go to"
        assert ". Go to" in result.user_message

    def test_no_hint_for_unknown_field(self):
        """Errors with no matching field produce a clean message without a hint."""
        exc = Exception("invalid_request_error: some unknown parameter is wrong")
        result = classify_provider_error(exc)
        assert "Go to" not in result.user_message
