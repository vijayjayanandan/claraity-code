"""
Example Hook: Rate Limiting

This hook demonstrates how to implement rate limiting for tool calls.
Useful for preventing runaway operations or enforcing usage quotas.

Usage:
    Copy this file to .claude/hooks.py to enable rate limiting.
"""

from src.hooks import HookResult, HookDecision
from datetime import datetime, timedelta
from collections import deque


# Rate limiting state (per tool)
tool_call_history = {}


def rate_limit_tool_calls(context, max_calls=10, window_seconds=60):
    """
    Rate limit tool calls to prevent runaway operations.

    Args:
        context: Hook context
        max_calls: Maximum calls allowed in time window
        window_seconds: Time window in seconds

    Policy:
        - Allow up to max_calls in window_seconds
        - Deny additional calls with helpful error message
        - Reset after window expires
    """
    tool = context.tool

    # Initialize history for this tool
    if tool not in tool_call_history:
        tool_call_history[tool] = deque()

    history = tool_call_history[tool]
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)

    # Remove calls outside the window
    while history and history[0] < cutoff:
        history.popleft()

    # Check if we're over the limit
    if len(history) >= max_calls:
        oldest_call = history[0]
        wait_seconds = (oldest_call + timedelta(seconds=window_seconds) - now).total_seconds()

        return HookResult(
            decision=HookDecision.DENY,
            message=f"Rate limit exceeded for {tool}: {max_calls} calls per {window_seconds}s. "
                    f"Wait {wait_seconds:.0f}s or reduce usage.",
            metadata={
                'rate_limit': True,
                'tool': tool,
                'calls_in_window': len(history),
                'max_calls': max_calls,
                'window_seconds': window_seconds,
                'wait_seconds': wait_seconds
            }
        )

    # Record this call
    history.append(now)

    return HookResult(
        decision=HookDecision.PERMIT,
        metadata={
            'calls_in_window': len(history),
            'max_calls': max_calls,
            'remaining': max_calls - len(history)
        }
    )


# Specific rate limiters for different tools
def rate_limit_write_operations(context):
    """Rate limit write operations: 20 per minute."""
    return rate_limit_tool_calls(context, max_calls=20, window_seconds=60)


def rate_limit_command_execution(context):
    """Rate limit command execution: 5 per minute (stricter)."""
    return rate_limit_tool_calls(context, max_calls=5, window_seconds=60)


def rate_limit_git_operations(context):
    """Rate limit git operations: 10 per 5 minutes."""
    return rate_limit_tool_calls(context, max_calls=10, window_seconds=300)


# Advanced: Burst allowance with sustained rate
class TokenBucket:
    """Token bucket rate limiter for burst allowance."""

    def __init__(self, capacity, refill_rate):
        """
        Initialize token bucket.

        Args:
            capacity: Maximum tokens (burst allowance)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = datetime.now()

    def consume(self, tokens=1):
        """
        Try to consume tokens.

        Returns:
            (allowed, wait_time): Tuple of whether allowed and wait time if denied
        """
        now = datetime.now()
        elapsed = (now - self.last_refill).total_seconds()

        # Refill tokens
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        # Try to consume
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, 0

        # Calculate wait time
        needed_tokens = tokens - self.tokens
        wait_time = needed_tokens / self.refill_rate

        return False, wait_time


# Token buckets per tool
token_buckets = {}


def token_bucket_rate_limit(context, capacity=10, refill_rate=0.5):
    """
    Token bucket rate limiter with burst allowance.

    Args:
        capacity: Maximum burst (tokens)
        refill_rate: Tokens per second

    Example:
        capacity=10, refill_rate=0.5 means:
        - Can burst up to 10 calls
        - Sustained rate of 30 calls/minute (0.5/sec)
    """
    tool = context.tool

    # Initialize bucket for this tool
    if tool not in token_buckets:
        token_buckets[tool] = TokenBucket(capacity, refill_rate)

    bucket = token_buckets[tool]
    allowed, wait_time = bucket.consume()

    if not allowed:
        return HookResult(
            decision=HookDecision.DENY,
            message=f"Rate limit exceeded for {tool}. Wait {wait_time:.1f}s. "
                    f"(Burst: {capacity}, Sustained: {refill_rate * 60:.0f}/min)",
            metadata={
                'rate_limit': True,
                'wait_seconds': wait_time,
                'capacity': capacity,
                'refill_rate': refill_rate
            }
        )

    return HookResult(
        decision=HookDecision.PERMIT,
        metadata={
            'tokens_remaining': bucket.tokens,
            'capacity': capacity
        }
    )


# Hook registry
HOOKS = {
    # Simple rate limiting
    'PreToolUse:write_file': [rate_limit_write_operations],
    'PreToolUse:edit_file': [rate_limit_write_operations],
    'PreToolUse:run_command': [rate_limit_command_execution],
    'PreToolUse:git_commit': [rate_limit_git_operations],

    # Alternative: Token bucket rate limiting (comment out above, uncomment below)
    # 'PreToolUse:write_file': [lambda c: token_bucket_rate_limit(c, capacity=10, refill_rate=0.5)],
    # 'PreToolUse:edit_file': [lambda c: token_bucket_rate_limit(c, capacity=10, refill_rate=0.5)],
}
