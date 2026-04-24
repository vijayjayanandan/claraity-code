"""
ErrorContext - Structured error context for LLM decision-making.

This module provides a dataclass that captures comprehensive error information
from tool failures, formatted for injection into LLM prompts. The structured
format helps the LLM make informed decisions about error recovery strategies.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ErrorContext:
    """
    Structured error context for LLM decision-making.

    Captures comprehensive information about a tool failure to help the LLM
    decide whether to retry with a different approach, ask the user for help,
    or stop with a clear explanation.

    Attributes:
        error_type: Classification of the error (e.g., "file_not_found", "permission")
        tool_name: Name of the tool that failed
        tool_args: Arguments that were passed to the tool
        error_message: The error message returned by the tool
        exit_code: Exit code if the tool was a command execution
        stdout_tail: Last 500 chars of stdout (for command failures)
        stderr_tail: Last 500 chars of stderr (for command failures)
        working_dir: Working directory when the error occurred
        attempt_number: How many times this tool+error_type combination has failed
        previous_attempts: list of previous distinct attempts (capped to last 3)
    """

    error_type: str
    tool_name: str
    tool_args: dict[str, Any]
    error_message: str
    exit_code: int | None
    stdout_tail: str | None  # Last 500 chars
    stderr_tail: str | None  # Last 500 chars
    working_dir: str | None
    attempt_number: int
    previous_attempts: list[dict[str, Any]]  # Capped to last 3

    def to_prompt_block(self) -> str:
        """
        Format as structured prompt for LLM (kept concise).

        Returns a string in a structured format that the LLM can parse and use
        to make informed decisions about error recovery.

        Returns:
            Formatted string suitable for injection into LLM prompt
        """
        attempts_summary = "\n".join(
            f"- {a['tool']}({a['args_summary']}): {a['result_summary']}"
            for a in self.previous_attempts[-3:]  # Cap at 3
        )

        # Build optional fields
        optional_lines = []
        if self.exit_code is not None:
            optional_lines.append(f"exit_code: {self.exit_code}")
        if self.stdout_tail:
            optional_lines.append(f"stdout_tail: {self.stdout_tail[:200]}")
        if self.stderr_tail:
            optional_lines.append(f"stderr_tail: {self.stderr_tail[:200]}")
        if self.working_dir:
            optional_lines.append(f"working_dir: {self.working_dir}")

        optional_section = "\n".join(optional_lines)

        return f"""<tool_failure>
tool: {self.tool_name}
attempt: {self.attempt_number}
error_type: {self.error_type}
error: {self.error_message}
{optional_section}

previous_distinct_attempts:
{attempts_summary if attempts_summary else "(none)"}

rules:
- Do NOT repeat an identical call
- If retrying, fix the args (wrong path, invalid pattern, etc.) and retry the SAME tool
- Do NOT switch to run_command as a fallback for grep/glob/read_file -- fix the args instead
- Only switch tools if the tool itself cannot do what is needed (not just because args were wrong)
- If blocked after 3 attempts, ask user for clarification or explain stop
</tool_failure>"""

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the error context
        """
        return {
            "error_type": self.error_type,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "error_message": self.error_message,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "working_dir": self.working_dir,
            "attempt_number": self.attempt_number,
            "previous_attempts": self.previous_attempts,
        }


# =============================================================================
# ROOT CAUSE EXTRACTION
# =============================================================================


def get_root_cause_info(exc: BaseException, max_message_len: int = 500) -> tuple[str, str]:
    """
    Walk exception chain to find the deepest root cause.

    Handles both explicit chaining (__cause__ from 'raise X from Y')
    and implicit chaining (__context__ from 'raise X' inside except block).
    Guards against cycles to prevent infinite loops.

    Args:
        exc: The exception to analyze
        max_message_len: Maximum length for root cause message (default 500)

    Returns:
        Tuple of (root_cause_type, root_cause_message)
        - root_cause_type: Class name of the deepest exception (e.g., "ReadTimeout")
        - root_cause_message: String representation, truncated to max_message_len

    Example:
        >>> try:
        ...     raise RuntimeError("Wrapper") from httpx.ReadTimeout("timeout")
        ... except Exception as e:
        ...     root_type, root_msg = get_root_cause_info(e)
        ...     # root_type == "ReadTimeout"
        ...     # root_msg == "timeout"
    """
    if exc is None:
        return ("NoneType", "")

    # Track seen exceptions to guard against cycles
    seen: set[int] = set()
    root = exc

    while True:
        exc_id = id(root)
        if exc_id in seen:
            # Cycle detected, stop here
            break
        seen.add(exc_id)

        # Prefer explicit cause (__cause__), fall back to implicit (__context__)
        next_exc = root.__cause__ if root.__cause__ is not None else root.__context__

        if next_exc is None:
            # No more causes, root is the deepest
            break

        root = next_exc

    root_type = type(root).__name__
    root_message = str(root).strip()

    # Truncate message to prevent memory issues
    if len(root_message) > max_message_len:
        root_message = root_message[:max_message_len] + "..."

    return (root_type, root_message)


def is_timeout_error(exc: BaseException) -> bool:
    """
    Check if exception (or its root cause) is a timeout error.

    Args:
        exc: Exception to check

    Returns:
        True if "timeout" is in the root cause type name (case-insensitive)
    """
    root_type, _ = get_root_cause_info(exc)
    return "timeout" in root_type.lower()


# Export
__all__ = ["ErrorContext", "get_root_cause_info", "is_timeout_error"]
