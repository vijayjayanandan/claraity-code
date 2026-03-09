"""LLM Failure Handler - Handle API failures gracefully with retry logic.

This module provides robust error handling for LLM API calls including:
- Exponential backoff retry with configurable caps (prevents DoS)
- Jitter support to prevent thundering herd
- Rate limit detection and handling
- Timeout management
- Error classification (retryable vs fatal)
- Enhanced response validation (truncation, repetition detection)
- User-facing progress notifications
- Thread-safe implementation

Prevents crashes from transient API issues (timeouts, rate limits, network errors)
while failing fast on permanent failures (invalid API key, invalid model, etc.).

Thread Safety:
    This handler is thread-safe and can be safely shared across multiple threads.
    All retry methods use only local variables and do not modify shared state.

    Example:
        handler = LLMFailureHandler()

        def worker():
            result = handler.execute_with_retry(lambda: llm.chat(messages))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads: t.start()
"""

import asyncio
import logging
import random
import re
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Windows compatibility: Use text markers instead of emojis
from src.platform import safe_print

# Langfuse observability (optional, graceful degradation)
try:
    from langfuse import observe
    LANGFUSE_AVAILABLE = True
except ImportError:
    # Create a no-op decorator if Langfuse not available
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    LANGFUSE_AVAILABLE = False


class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class RateLimitError(LLMError):
    """Rate limit exceeded error."""
    pass


class TimeoutError(LLMError):
    """Timeout error."""
    pass


class ValidationError(LLMError):
    """Response validation error."""
    pass


class InvalidAPIKeyError(LLMError):
    """Invalid API key error (fatal)."""
    pass


class InvalidModelError(LLMError):
    """Invalid model error (fatal)."""
    pass


class ContextLengthExceededError(LLMError):
    """Context length exceeded error (fatal)."""
    pass


class ContentPolicyViolationError(LLMError):
    """Content policy violation error (fatal)."""
    pass


# Error classification maps
RETRYABLE_ERROR_KEYWORDS = {
    "timeout": True,
    "timed out": True,
    "rate_limit": True,
    "rate limit": True,
    "too many requests": True,
    "service unavailable": True,
    "503": True,
    "connection": True,
    "network": True,
    "temporarily unavailable": True,
    "overloaded": True,
    "502": True,
    "504": True,
}

FATAL_ERROR_KEYWORDS = {
    "invalid_api_key": True,
    "invalid api key": True,
    "authentication": True,
    "unauthorized": True,
    "401": True,
    "invalid_model": True,
    "invalid model": True,
    "model not found": True,
    "404": True,
    "context_length_exceeded": True,
    "maximum context length": True,
    "content_policy_violation": True,
    "content policy": True,
    "invalid_request": True,
}


class LLMFailureHandler:
    """
    Handle LLM API failures gracefully with retry logic.

    Provides methods for:
    - Exponential backoff retry with delay caps (prevents DoS)
    - Error classification (retryable vs fatal)
    - Rate limit handling
    - Timeout management
    - Enhanced response validation
    - User-facing progress notifications

    Thread Safety:
        This handler is thread-safe. All methods use local variables only
        and do not modify shared state, making it safe to use across multiple
        threads concurrently.

    Example:
        handler = LLMFailureHandler(
            max_backoff_delay=15.0,      # Cap standard retries at 15s
            max_rate_limit_delay=30.0,   # Cap rate limit retries at 30s
            enable_jitter=True,          # Prevent thundering herd
            show_progress=True           # Show retry notifications to user
        )

        # Wrap LLM call with retry
        result = handler.execute_with_retry(
            lambda: llm.chat(messages),
            max_attempts=5
        )

        # Handle rate limits specifically
        result = handler.handle_rate_limit(
            lambda: llm.chat(messages)
        )
    """

    def __init__(
        self,
        logger_instance: logging.Logger | None = None,
        max_backoff_delay: float = 15.0,
        max_rate_limit_delay: float = 30.0,
        rate_limit_base_delay: float = 10.0,
        timeout_multiplier: float = 1.5,
        enable_jitter: bool = True,
        jitter_type: str = "full",
        show_progress: bool = True,
        progress_countdown_threshold: float = 10.0
    ):
        """
        Initialize failure handler with configurable retry behavior.

        Args:
            logger_instance: Optional logger instance (uses module logger if not provided)
            max_backoff_delay: Maximum delay for standard retries (default: 15s)
                              Prevents unbounded exponential growth (DoS prevention)
            max_rate_limit_delay: Maximum delay for rate limit retries (default: 30s)
            rate_limit_base_delay: Base delay for rate limits (default: 10s)
            timeout_multiplier: Timeout multiplier for each retry (default: 1.5)
            enable_jitter: Add randomization to delays (prevents thundering herd)
            jitter_type: Jitter strategy - "full", "equal", or "none"
            show_progress: Show retry notifications to user via safe_print
            progress_countdown_threshold: Show countdown for delays > this value (default: 10s)
        """
        self.logger = logger_instance or logger
        self.max_backoff_delay = max_backoff_delay
        self.max_rate_limit_delay = max_rate_limit_delay
        self.rate_limit_base_delay = rate_limit_base_delay
        self.timeout_multiplier = timeout_multiplier
        self.enable_jitter = enable_jitter
        self.jitter_type = jitter_type
        self.show_progress = show_progress
        self.progress_countdown_threshold = progress_countdown_threshold

    def _calculate_delay(self, base_delay: float, max_delay: float) -> float:
        """
        Calculate delay with optional jitter and cap enforcement.

        Args:
            base_delay: Base delay before jitter/cap
            max_delay: Maximum allowed delay (cap)

        Returns:
            Final delay in seconds
        """
        # Apply maximum cap first
        delay = min(base_delay, max_delay)

        # Apply jitter if enabled
        if self.enable_jitter and delay > 0:
            if self.jitter_type == "full":
                # Full jitter: random value between 0 and delay
                delay = random.uniform(0, delay)
            elif self.jitter_type == "equal":
                # Equal jitter: delay/2 + random(0, delay/2)
                delay = delay / 2 + random.uniform(0, delay / 2)
            # else: no jitter (use delay as-is)

        return delay

    def _sanitize_error_message(self, error: Exception, max_length: int = 200) -> str:
        """
        Sanitize error message for safe logging and display.

        Removes ANSI escape codes and truncates long messages to prevent:
        - Terminal injection attacks
        - Information leakage
        - Log injection

        Args:
            error: Exception to sanitize
            max_length: Maximum message length (default: 200)

        Returns:
            Sanitized error message
        """
        message = str(error)

        # Remove ANSI escape codes
        message = re.sub(r'\x1b\[[0-9;]*m', '', message)

        # Truncate long messages
        if len(message) > max_length:
            message = message[:max_length] + "... (truncated)"

        return message

    def _show_progress(self, message: str, delay: float, attempt: int, max_attempts: int):
        """
        Show retry progress to user with optional countdown.

        Always sleeps for the specified delay. If show_progress is True,
        displays retry information and countdown to the user.

        Args:
            message: Error message to show
            delay: Delay in seconds
            attempt: Current attempt number (0-indexed)
            max_attempts: Maximum attempts
        """
        if self.show_progress:
            # Show retry message
            safe_print(
                f"[RETRY] {message}. "
                f"Retrying in {delay:.0f}s... (attempt {attempt + 1}/{max_attempts})",
                flush=True
            )

            # Show countdown for long delays
            if delay >= self.progress_countdown_threshold:
                for remaining in range(int(delay), 0, -1):
                    safe_print(f"  Retrying in {remaining}s...    ", end='\r', flush=True)
                    time.sleep(1)
                safe_print("  Retrying now...                ", flush=True)
                return  # Already slept during countdown

        # Sleep for the delay (either no progress shown, or short delay without countdown)
        time.sleep(delay)

    @observe(name="llm_retry_handler", as_type="span")
    def execute_with_retry(
        self,
        func: Callable,
        max_attempts: int = 3,
        backoff_base: float = 2.0
    ) -> Any:
        """
        Execute function with exponential backoff retry on failure.

        Retry delays: 1s, 2s, 4s, 8s... (capped at max_backoff_delay)
        Only retries on retryable errors (timeouts, rate limits, network issues).
        Fails fast on fatal errors (invalid API key, invalid model).

        Thread Safety: Uses only local variables, safe for concurrent calls.

        Args:
            func: Function to execute (typically an LLM API call)
            max_attempts: Maximum execution attempts (default: 3)
            backoff_base: Base for exponential backoff (default: 2.0)
                         delay = backoff_base ** attempt

        Returns:
            Result of function execution

        Raises:
            LLMError: If all retry attempts fail or error is fatal

        Example:
            result = handler.execute_with_retry(
                lambda: llm.chat(messages),
                max_attempts=5,
                backoff_base=2.0
            )
        """
        last_error = None

        for attempt in range(max_attempts):
            try:
                # Execute function
                result = func()

                # Notify user of success if this was a retry
                if attempt > 0:
                    if self.show_progress:
                        safe_print(f"[OK] Request succeeded after {attempt + 1} attempts")
                    self.logger.info(
                        f"[OK] Retry successful after {attempt + 1} attempts"
                    )

                return result

            except Exception as e:
                last_error = e

                # Classify error
                is_retryable, error_message = self.handle_api_error(e)

                # If fatal error, fail immediately
                if not is_retryable:
                    if self.show_progress:
                        safe_print(f"[FAIL] {error_message}")
                    self.logger.error(
                        f"[FAIL] Fatal error (not retrying): {error_message}"
                    )
                    raise LLMError(error_message) from e

                # If last attempt, raise error
                if attempt == max_attempts - 1:
                    if self.show_progress:
                        safe_print(
                            f"[FAIL] Request failed after {max_attempts} attempts: {error_message}"
                        )
                    self.logger.error(
                        f"[FAIL] All {max_attempts} retry attempts exhausted: {error_message}"
                    )
                    raise LLMError(f"Failed after {max_attempts} attempts: {error_message}") from e

                # Calculate exponential backoff delay with cap and jitter
                base_delay = backoff_base ** attempt  # 1s, 2s, 4s, 8s...
                delay = self._calculate_delay(base_delay, self.max_backoff_delay)

                # Log for debugging
                self.logger.warning(
                    f"[RETRY] Attempt {attempt + 1}/{max_attempts} failed: {error_message}. "
                    f"Retrying in {delay:.1f}s (base: {base_delay:.1f}s, cap: {self.max_backoff_delay}s)..."
                )

                # Show progress to user
                self._show_progress(error_message, delay, attempt, max_attempts)

        # Should never reach here, but just in case
        raise LLMError(f"Failed after {max_attempts} attempts") from last_error

    async def execute_with_retry_async(
        self,
        func: Callable,
        max_attempts: int = 3,
        backoff_base: float = 2.0
    ) -> Any:
        """Async version of execute_with_retry using asyncio.sleep instead of time.sleep.

        Prevents blocking the event loop during retries. Use this when the callable
        is an async function or when retries happen on the asyncio event loop
        (e.g., during compaction).

        Thread Safety: Uses only local variables, safe for concurrent calls.

        Args:
            func: Async function to execute (must be awaitable)
            max_attempts: Maximum execution attempts (default: 3)
            backoff_base: Base for exponential backoff (default: 2.0)
                         delay = backoff_base ** attempt

        Returns:
            Result of function execution

        Raises:
            LLMError: If all retry attempts fail or error is fatal
        """
        last_error = None

        for attempt in range(max_attempts):
            try:
                result = await func()

                if attempt > 0:
                    self.logger.info(
                        f"[OK] Async retry successful after {attempt + 1} attempts"
                    )

                return result

            except Exception as e:
                last_error = e

                is_retryable, error_message = self.handle_api_error(e)

                if not is_retryable:
                    self.logger.error(
                        f"[FAIL] Fatal error (not retrying): {error_message}"
                    )
                    raise LLMError(error_message) from e

                if attempt == max_attempts - 1:
                    self.logger.error(
                        f"[FAIL] All {max_attempts} async retry attempts exhausted: {error_message}"
                    )
                    raise LLMError(f"Failed after {max_attempts} attempts: {error_message}") from e

                base_delay = backoff_base ** attempt
                delay = self._calculate_delay(base_delay, self.max_backoff_delay)

                self.logger.warning(
                    f"[RETRY] Async attempt {attempt + 1}/{max_attempts} failed: {error_message}. "
                    f"Retrying in {delay:.1f}s (base: {base_delay:.1f}s, cap: {self.max_backoff_delay}s)..."
                )

                await asyncio.sleep(delay)

        raise LLMError(f"Failed after {max_attempts} attempts") from last_error

    def handle_api_error(self, error: Exception) -> tuple[bool, str]:
        """
        Classify API error as retryable or fatal.

        Retryable errors (transient):
        - Timeout errors
        - Rate limit errors
        - Service unavailable (503)
        - Connection/network errors

        Fatal errors (permanent):
        - Invalid API key (401)
        - Invalid model (404)
        - Context length exceeded
        - Content policy violation

        Args:
            error: API error to classify

        Returns:
            tuple of (is_retryable, error_message)
            - is_retryable: True if error can be retried, False if fatal
            - error_message: Human-readable error description (sanitized)

        Example:
            is_retryable, msg = handler.handle_api_error(error)
            if is_retryable:
                # Retry with backoff
                time.sleep(delay)
            else:
                # Fail fast
                raise FatalError(msg)
        """
        error_type = type(error).__name__
        error_str = str(error).lower()

        # Sanitize error message for safe display
        sanitized_error = self._sanitize_error_message(error)

        # Check for retryable errors
        for keyword in RETRYABLE_ERROR_KEYWORDS:
            if keyword in error_str or keyword in error_type.lower():
                return True, f"Retryable error ({error_type}): {sanitized_error}"

        # Check for fatal errors
        for keyword in FATAL_ERROR_KEYWORDS:
            if keyword in error_str or keyword in error_type.lower():
                return False, f"Fatal error ({error_type}): {sanitized_error}"

        # Default: treat unknown errors as retryable (conservative approach)
        # This prevents giving up too early on transient issues
        self.logger.warning(
            f"[WARN] Unknown error type ({error_type}), treating as retryable: {error}"
        )
        return True, f"Unknown error ({error_type}): {sanitized_error}"

    @observe(name="rate_limit_handler", as_type="span")
    def handle_rate_limit(
        self,
        func: Callable,
        max_retries: int = 5
    ) -> Any:
        """
        Execute function with automatic retry on rate limit errors.

        Uses exponential backoff with longer delays than standard retry
        because rate limits typically require 10s+ wait times.

        Backoff delays: 10s, 20s, 40s... (capped at max_rate_limit_delay)

        Thread Safety: Uses only local variables, safe for concurrent calls.

        Args:
            func: Function to execute (typically an LLM API call)
            max_retries: Maximum retry attempts (default: 5, rate limits need more)

        Returns:
            Result of function execution

        Raises:
            RateLimitError: If all retry attempts fail
            LLMError: If error is not a rate limit (e.g., invalid API key)

        Example:
            result = handler.handle_rate_limit(
                lambda: llm.chat(messages),
                max_retries=5
            )
        """
        for attempt in range(max_retries):
            try:
                result = func()

                # Notify user of success if this was a retry
                if attempt > 0:
                    if self.show_progress:
                        safe_print(f"[OK] Rate limit cleared after {attempt + 1} attempts")
                    self.logger.info(
                        f"[OK] Rate limit retry successful after {attempt + 1} attempts"
                    )

                return result

            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = any(
                    keyword in error_str
                    for keyword in ["rate_limit", "rate limit", "too many requests"]
                )

                # If not a rate limit error, re-raise
                if not is_rate_limit:
                    # Check if it's a fatal error
                    is_retryable, error_message = self.handle_api_error(e)
                    if not is_retryable:
                        raise LLMError(error_message) from e
                    else:
                        # Use standard retry for non-rate-limit retryable errors
                        raise LLMError(f"Not a rate limit error: {str(e)}") from e

                # If last attempt, raise error
                if attempt == max_retries - 1:
                    sanitized_error = self._sanitize_error_message(e)
                    if self.show_progress:
                        safe_print(
                            f"[FAIL] Rate limit persists after {max_retries} attempts: {sanitized_error}"
                        )
                    self.logger.error(
                        f"[FAIL] Rate limit: All {max_retries} retry attempts exhausted"
                    )
                    raise RateLimitError(
                        f"Rate limit persists after {max_retries} attempts"
                    ) from e

                # Exponential backoff with base=10s for rate limits, with cap and jitter
                base_delay = self.rate_limit_base_delay * (2 ** attempt)  # 10s, 20s, 40s...
                delay = self._calculate_delay(base_delay, self.max_rate_limit_delay)

                # Log for debugging
                self.logger.warning(
                    f"[RETRY] Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                    f"Waiting {delay:.1f}s (base: {base_delay:.1f}s, cap: {self.max_rate_limit_delay}s)..."
                )

                # Show progress to user
                sanitized_error = self._sanitize_error_message(e)
                self._show_progress(f"Rate limit: {sanitized_error}", delay, attempt, max_retries)

        # Should never reach here
        raise RateLimitError(f"Rate limit persists after {max_retries} attempts")

    @observe(name="timeout_handler", as_type="span")
    def handle_timeout(
        self,
        func: Callable,
        timeout_seconds: float = 30.0,
        max_retries: int = 3
    ) -> Any:
        """
        Execute function with timeout and automatic retry on TimeoutError.

        Increases timeout on each retry (30s -> 45s -> 67.5s) to handle
        slow network or LLM processing.

        Note: This method provides retry logic for timeout errors.
        The actual timeout enforcement must be implemented in the LLM backend
        (e.g., using httpx.Timeout in OpenAI client).

        Thread Safety: Uses only local variables, safe for concurrent calls.

        Args:
            func: Function to execute (typically an LLM API call)
            timeout_seconds: Initial timeout in seconds (default: 30.0)
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            Result of function execution

        Raises:
            TimeoutError: If all retry attempts timeout
            LLMError: If error is not a timeout (e.g., invalid API key)

        Example:
            result = handler.handle_timeout(
                lambda: llm.chat(messages),
                timeout_seconds=60.0,
                max_retries=3
            )
        """
        for attempt in range(max_retries):
            try:
                # Increase timeout on each retry (1x, 1.5x, 2.25x, 3.375x)
                current_timeout = timeout_seconds * (self.timeout_multiplier ** attempt)

                # Note: Timeout enforcement must be done in LLM backend
                # This method only handles retry logic for timeout errors

                result = func()

                # Notify user of success if this was a retry
                if attempt > 0:
                    if self.show_progress:
                        safe_print(f"[OK] Request succeeded after {attempt + 1} timeout retries")
                    self.logger.info(
                        f"[OK] Timeout retry successful after {attempt + 1} attempts"
                    )

                return result

            except Exception as e:
                error_str = str(e).lower()
                is_timeout = any(
                    keyword in error_str
                    for keyword in ["timeout", "timed out"]
                )

                # If not a timeout error, re-raise
                if not is_timeout:
                    # Check if it's a fatal error
                    is_retryable, error_message = self.handle_api_error(e)
                    if not is_retryable:
                        raise LLMError(error_message) from e
                    else:
                        # Use standard retry for non-timeout retryable errors
                        raise LLMError(f"Not a timeout error: {str(e)}") from e

                # If last attempt, raise error
                if attempt == max_retries - 1:
                    sanitized_error = self._sanitize_error_message(e)
                    if self.show_progress:
                        safe_print(
                            f"[FAIL] Timeout persists after {max_retries} attempts: {sanitized_error}"
                        )
                    self.logger.error(
                        f"[FAIL] Timeout: All {max_retries} retry attempts exhausted"
                    )
                    raise TimeoutError(
                        f"Timeout persists after {max_retries} attempts"
                    ) from e

                # Calculate next timeout (no sleep, retry immediately with longer timeout)
                next_timeout = timeout_seconds * (self.timeout_multiplier ** (attempt + 1))

                sanitized_error = self._sanitize_error_message(e)
                if self.show_progress:
                    safe_print(
                        f"[RETRY] Timeout after {current_timeout:.1f}s. "
                        f"Retrying immediately with {next_timeout:.1f}s timeout... "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )

                self.logger.warning(
                    f"[RETRY] Timeout after {current_timeout:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries}). "
                    f"Retrying with {next_timeout:.1f}s timeout..."
                )

                # No sleep needed - retry immediately with longer timeout

        # Should never reach here
        raise TimeoutError(f"Timeout persists after {max_retries} attempts")

    @observe(name="validate_llm_response", as_type="span")
    def validate_response(
        self,
        response: str,
        expected_format: str | None = None,
        check_truncation: bool = True,
        check_repetition: bool = True
    ) -> bool:
        """
        Validate LLM response is well-formed with enhanced checks.

        Basic checks:
        - Response is not None
        - Response is not empty string
        - Response is not just whitespace

        Enhanced checks (optional):
        - Truncation detection (ends mid-sentence, unclosed brackets)
        - Repetition loop detection (5+ consecutive repeated tokens)
        - Format-specific validation (JSON, code)

        Args:
            response: LLM response to validate
            expected_format: Expected format - "json", "code", or None
            check_truncation: Check for truncation indicators (default: True)
            check_repetition: Check for repetition loops (default: True)

        Returns:
            True if response is valid

        Raises:
            ValidationError: If response is invalid

        Example:
            response = llm.chat(messages)
            handler.validate_response(response, expected_format="json")
        """
        # Basic checks
        if response is None:
            raise ValidationError("Response is None")

        if not isinstance(response, str):
            raise ValidationError(f"Response is not a string: {type(response)}")

        if not response.strip():
            raise ValidationError("Response is empty or whitespace-only")

        # Enhanced checks (optional)
        if check_truncation and len(response) > 100:
            # Check if response ends mid-sentence (common truncation indicator)
            last_char = response.strip()[-1]
            if last_char not in ['.', '!', '?', '"', "'", '`', '}', ']', ')']:
                self.logger.warning(
                    f"[WARN] Response may be truncated (ends with '{last_char}')"
                )

        if check_repetition:
            # Check for repetition loops (5+ consecutive repeated tokens)
            words = response.split()
            if len(words) >= 5:
                for i in range(len(words) - 4):
                    if len(set(words[i:i+5])) == 1:  # All 5 words identical
                        raise ValidationError(
                            f"Response contains repetition loop: '{words[i]}' repeated 5+ times"
                        )

        # Format-specific validation
        if expected_format == "json":
            import json
            try:
                json.loads(response)
            except json.JSONDecodeError as e:
                raise ValidationError(f"Invalid JSON response: {e}")

        elif expected_format == "code":
            # Check for unclosed brackets (common truncation pattern in code)
            unclosed = {
                '{': response.count('{') - response.count('}'),
                '[': response.count('[') - response.count(']'),
                '(': response.count('(') - response.count(')')
            }
            if any(count > 2 for count in unclosed.values()):  # Allow small imbalance
                self.logger.warning(
                    f"[WARN] Code response has unclosed brackets: {unclosed}"
                )

        # Response is valid
        return True

    def with_retry(
        self,
        max_attempts: int = 3,
        backoff_base: float = 2.0
    ):
        """
        Decorator to add retry logic to any function.

        Args:
            max_attempts: Maximum execution attempts
            backoff_base: Base for exponential backoff

        Returns:
            Decorated function with retry logic

        Example:
            handler = LLMFailureHandler()

            @handler.with_retry(max_attempts=5)
            def call_llm():
                return llm.chat(messages)

            result = call_llm()
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                return self.execute_with_retry(
                    lambda: func(*args, **kwargs),
                    max_attempts=max_attempts,
                    backoff_base=backoff_base
                )
            return wrapper
        return decorator
