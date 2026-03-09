"""Cooperative cancellation token for subagent execution."""


class CancelledException(Exception):
    """Raised when a cancel token is triggered."""

    pass


class CancelToken:
    """Simple cooperative cancellation flag.

    Used by subagents to check for cancellation at safe checkpoints
    between operations (before LLM calls, before tool executions).
    """

    def __init__(self):
        self._cancelled = False

    def cancel(self) -> None:
        """Signal cancellation."""
        self._cancelled = True

    def check_cancelled(self) -> None:
        """Raise CancelledException if cancelled."""
        if self._cancelled:
            raise CancelledException("Operation cancelled")

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled
