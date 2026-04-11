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
import json
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
    """Base exception for LLM errors.

    All subclasses carry UI metadata so the agent's except block
    can emit an ErrorEvent without doing its own phrase matching.
    """

    def __init__(
        self,
        message: str = "",
        *,
        user_message: str = "",
        event_type: str = "provider_error",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.user_message = user_message or message or "An unexpected provider error occurred."
        self.event_type = event_type
        self.retryable = retryable


class RateLimitError(LLMError):
    """Rate limit exceeded -- retryable."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Rate limit reached. Retrying automatically.")
        kwargs.setdefault("event_type", "rate_limit")
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class TimeoutError(LLMError):
    """Request timed out -- retryable."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Request timed out. The server took too long to respond.")
        kwargs.setdefault("event_type", "provider_timeout")
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class NetworkError(LLMError):
    """Connection / network error -- retryable."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Connection error. Please check your network.")
        kwargs.setdefault("event_type", "network")
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class ValidationError(LLMError):
    """Response validation error."""

    pass


class InvalidAPIKeyError(LLMError):
    """Invalid API key -- fatal config error."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "API key is invalid or missing. Check the API Key in Settings.")
        kwargs.setdefault("event_type", "config_error")
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)


class InvalidModelError(LLMError):
    """Invalid or unknown model -- fatal config error."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Model not found. Check the model name in Settings.")
        kwargs.setdefault("event_type", "config_error")
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)


class InvalidRequestError(LLMError):
    """Invalid request parameters (temperature, max_tokens, etc.) -- fatal config error."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Invalid request parameters. Check your model settings.")
        kwargs.setdefault("event_type", "config_error")
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)


class ContextLengthExceededError(LLMError):
    """Context length exceeded -- fatal."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Context length exceeded. The conversation is too long.")
        kwargs.setdefault("event_type", "config_error")
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)


class ContentPolicyViolationError(LLMError):
    """Content policy violation -- fatal (distinct from config errors)."""

    def __init__(self, message: str = "", **kwargs: Any) -> None:
        kwargs.setdefault("user_message", "Request blocked by provider content policy.")
        kwargs.setdefault("event_type", "content_policy")
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)


# ---------------------------------------------------------------------------
# Signal sets used by classify_provider_error()
# Single source of truth -- agent.py no longer duplicates these.
# ---------------------------------------------------------------------------

_TIMEOUT_SIGNALS: frozenset[str] = frozenset({
    "timeout", "timed out",
})

_RATE_LIMIT_SIGNALS: frozenset[str] = frozenset({
    "rate_limit", "rate limit", "too many requests", "429",
})

_NETWORK_SIGNALS: frozenset[str] = frozenset({
    "connection", "network", "service unavailable", "temporarily unavailable",
    "overloaded", "502", "503", "504",
})

# Specific auth signals only -- bare "authentication" / "unauthorized" removed
# to prevent false positives on user code that mentions those words.
_AUTH_SIGNALS: frozenset[str] = frozenset({
    "invalid_api_key", "invalid api key", "incorrect api key",
    "authentication_error", "401",
})

_CONTENT_POLICY_SIGNALS: frozenset[str] = frozenset({
    "content_policy_violation", "content policy",
})

_MODEL_SIGNALS: frozenset[str] = frozenset({
    "invalid_model", "invalid model", "model not found", "404",
})

# Full phrases only -- no bare "invalid_request" (too broad, catches content policy)
_INVALID_REQUEST_SIGNALS: frozenset[str] = frozenset({
    "invalid_request_error",
    "invalid value for", "must be between", "must be a",
    "max_tokens must", "temperature must", "top_p must",
    "top_p not supported",
})

_CONTEXT_LENGTH_SIGNALS: frozenset[str] = frozenset({
    "context_length_exceeded", "maximum context length",
})

# Backward-compat aliases (kept in case external code imports them)
RETRYABLE_ERROR_KEYWORDS: dict[str, bool] = {s: True for s in _TIMEOUT_SIGNALS | _RATE_LIMIT_SIGNALS | _NETWORK_SIGNALS}
FATAL_ERROR_KEYWORDS: dict[str, bool] = {
    s: True for s in _AUTH_SIGNALS | _CONTENT_POLICY_SIGNALS | _MODEL_SIGNALS
    | _INVALID_REQUEST_SIGNALS | _CONTEXT_LENGTH_SIGNALS
}


# ---------------------------------------------------------------------------
# Private helpers for root-cause extraction
# ---------------------------------------------------------------------------

def _extract_root_cause_message(exc: Exception) -> str:
    """Walk the __cause__ chain and return the cleanest error message.

    Handles the Anthropic SDK quirk where the response body is stored as a
    bytes literal string: b'{"type":"error","error":{"message":"..."}}'.
    Falls back to str(root) if JSON parsing fails -- always returns a string.
    """
    root = exc
    while root.__cause__ is not None:
        root = root.__cause__

    raw = str(root).strip()[:500]

    # Anthropic SDK may produce: b'{"type":"error","error":{"message":"..."}}'
    # Strip the leading b" or b' and trailing quote, then try JSON parse.
    bytes_match = re.match(r'^b([\'"])(.*)\1$', raw, re.DOTALL)
    if bytes_match:
        try:
            payload = json.loads(bytes_match.group(2))
            msg = payload.get("error", {}).get("message") or payload.get("message")
            if msg:
                return str(msg)
        except (json.JSONDecodeError, AttributeError):
            pass

    # Also try extracting "message" field from any embedded JSON in the string
    msg_match = re.search(r'"message"\s*:\s*"([^"]+)"', raw)
    if msg_match:
        return msg_match.group(1)

    return raw


def _build_combined_text(exc: Exception) -> str:
    """Return a single lowercased string combining top-level and root-cause messages.

    Used for signal matching in classify_provider_error().
    """
    top = str(exc).strip()
    root_msg = _extract_root_cause_message(exc)
    return (top + " " + root_msg).lower()


def classify_provider_error(exc: Exception) -> LLMError:
    """Classify any provider exception into a typed LLMError subclass.

    Returns a typed LLMError carrying user_message, event_type, and retryable.
    Never raises -- always returns an LLMError even for completely unknown exceptions.

    Classification precedence (first match wins):
      1. Timeout
      2. Rate limit
      3. Network / transient
      4. Invalid API key / auth
      5. Content policy (must be before invalid_request to prevent misclassification)
      6. Invalid model
      7. Invalid request / bad params
      8. Context length exceeded
      9. Unknown -> NetworkError (retryable, conservative)
    """
    combined = _build_combined_text(exc)
    type_name = type(exc).__name__.lower()

    # Already classified upstream -- preserve the type
    if isinstance(exc, LLMError):
        return exc

    # 1. Timeout
    if any(s in combined or s in type_name for s in _TIMEOUT_SIGNALS):
        return TimeoutError(str(exc))

    # 2. Rate limit
    if any(s in combined or s in type_name for s in _RATE_LIMIT_SIGNALS):
        return RateLimitError(str(exc))

    # 3. Network / transient
    if any(s in combined or s in type_name for s in _NETWORK_SIGNALS):
        return NetworkError(str(exc))

    # 4. Invalid API key / auth (specific signals only)
    if any(s in combined or s in type_name for s in _AUTH_SIGNALS):
        root_msg = _extract_root_cause_message(exc)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", root_msg)
        clean = " ".join(clean.split())[:200]
        return InvalidAPIKeyError(
            str(exc),
            user_message=f"API configuration error: {clean}",
        )

    # 5. Content policy (before invalid_request -- some providers send both signals)
    if any(s in combined for s in _CONTENT_POLICY_SIGNALS):
        return ContentPolicyViolationError(str(exc))

    # 6. Invalid model
    if any(s in combined or s in type_name for s in _MODEL_SIGNALS):
        root_msg = _extract_root_cause_message(exc)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", root_msg)
        clean = " ".join(clean.split())[:200]
        return InvalidModelError(
            str(exc),
            user_message=f"API configuration error: {clean}",
        )

    # 7. Invalid request / bad params (full phrases only)
    if any(s in combined for s in _INVALID_REQUEST_SIGNALS):
        root_msg = _extract_root_cause_message(exc)
        clean = re.sub(r"\x1b\[[0-9;]*m", "", root_msg)
        clean = " ".join(clean.split())[:200]
        return InvalidRequestError(
            str(exc),
            user_message=f"API configuration error: {clean}",
        )

    # 8. Context length
    if any(s in combined for s in _CONTEXT_LENGTH_SIGNALS):
        return ContextLengthExceededError(str(exc))

    # 9. Unknown -- conservative: keep agent alive, let user retry
    return NetworkError(
        str(exc),
        user_message="Connection error. Please check your network and provider status.",
    )


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
        progress_countdown_threshold: float = 10.0,
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
        message = re.sub(r"\x1b\[[0-9;]*m", "", message)

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
                flush=True,
            )

            # Show countdown for long delays
            if delay >= self.progress_countdown_threshold:
                for remaining in range(int(delay), 0, -1):
                    safe_print(f"  Retrying in {remaining}s...    ", end="\r", flush=True)
                    time.sleep(1)
                safe_print("  Retrying now...                ", flush=True)
                return  # Already slept during countdown

        # Sleep for the delay (either no progress shown, or short delay without countdown)
        time.sleep(delay)

    @observe(name="llm_retry_handler", as_type="span")
    def execute_with_retry(
        self, func: Callable, max_attempts: int = 3, backoff_base: float = 2.0
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
                    self.logger.info(f"[OK] Retry successful after {attempt + 1} attempts")

                return result

            except Exception as e:
                last_error = e

                # Classify error -- preserves typed metadata for callers
                classified = classify_provider_error(e)
                is_retryable = classified.retryable
                error_message = classified.user_message

                # If fatal error, fail immediately -- re-raise typed exception
                if not is_retryable:
                    if self.show_progress:
                        safe_print(f"[FAIL] {error_message}")
                    self.logger.error(f"[FAIL] Fatal error (not retrying): {error_message}")
                    raise classified from e

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
                base_delay = backoff_base**attempt  # 1s, 2s, 4s, 8s...
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
        self, func: Callable, max_attempts: int = 3, backoff_base: float = 2.0
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
                    self.logger.info(f"[OK] Async retry successful after {attempt + 1} attempts")

                return result

            except Exception as e:
                last_error = e

                classified = classify_provider_error(e)
                is_retryable = classified.retryable
                error_message = classified.user_message

                if not is_retryable:
                    self.logger.error(f"[FAIL] Fatal error (not retrying): {error_message}")
                    raise classified from e

                if attempt == max_attempts - 1:
                    self.logger.error(
                        f"[FAIL] All {max_attempts} async retry attempts exhausted: {error_message}"
                    )
                    raise LLMError(f"Failed after {max_attempts} attempts: {error_message}") from e

                base_delay = backoff_base**attempt
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
        classified = classify_provider_error(error)
        if not classified.retryable:
            self.logger.warning(
                f"[WARN] Fatal provider error ({type(error).__name__}): {classified.user_message}"
            )
        return classified.retryable, classified.user_message

    @observe(name="rate_limit_handler", as_type="span")
    def handle_rate_limit(self, func: Callable, max_retries: int = 5) -> Any:
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
                    classified = classify_provider_error(e)
                    if not classified.retryable:
                        raise classified from e
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
                    raise RateLimitError(f"Rate limit persists after {max_retries} attempts") from e

                # Exponential backoff with base=10s for rate limits, with cap and jitter
                base_delay = self.rate_limit_base_delay * (2**attempt)  # 10s, 20s, 40s...
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
        self, func: Callable, timeout_seconds: float = 30.0, max_retries: int = 3
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
                current_timeout = timeout_seconds * (self.timeout_multiplier**attempt)

                # Note: Timeout enforcement must be done in LLM backend
                # This method only handles retry logic for timeout errors

                result = func()

                # Notify user of success if this was a retry
                if attempt > 0:
                    if self.show_progress:
                        safe_print(f"[OK] Request succeeded after {attempt + 1} timeout retries")
                    self.logger.info(f"[OK] Timeout retry successful after {attempt + 1} attempts")

                return result

            except Exception as e:
                error_str = str(e).lower()
                is_timeout = any(keyword in error_str for keyword in ["timeout", "timed out"])

                # If not a timeout error, re-raise
                if not is_timeout:
                    # Check if it's a fatal error
                    classified = classify_provider_error(e)
                    if not classified.retryable:
                        raise classified from e
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
                    self.logger.error(f"[FAIL] Timeout: All {max_retries} retry attempts exhausted")
                    raise TimeoutError(f"Timeout persists after {max_retries} attempts") from e

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
        check_repetition: bool = True,
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
            if last_char not in [".", "!", "?", '"', "'", "`", "}", "]", ")"]:
                self.logger.warning(f"[WARN] Response may be truncated (ends with '{last_char}')")

        if check_repetition:
            # Check for repetition loops (5+ consecutive repeated tokens)
            words = response.split()
            if len(words) >= 5:
                for i in range(len(words) - 4):
                    if len(set(words[i : i + 5])) == 1:  # All 5 words identical
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
                "{": response.count("{") - response.count("}"),
                "[": response.count("[") - response.count("]"),
                "(": response.count("(") - response.count(")"),
            }
            if any(count > 2 for count in unclosed.values()):  # Allow small imbalance
                self.logger.warning(f"[WARN] Code response has unclosed brackets: {unclosed}")

        # Response is valid
        return True

    def with_retry(self, max_attempts: int = 3, backoff_base: float = 2.0):
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
                    backoff_base=backoff_base,
                )

            return wrapper

        return decorator
