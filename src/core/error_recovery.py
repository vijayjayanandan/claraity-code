"""
ErrorRecoveryTracker - Track retry attempts and ENFORCE loop prevention.

This module implements the controller component of the model+controller pattern
for intelligent error recovery. It programmatically blocks repeated failed calls
rather than relying solely on LLM prompt guidance.

Retry Policy:
- Same exact failed call: blocked immediately (1 failure = no retry)
- Same tool + SAME ERROR TYPE: max 2 failures, then blocked
- Near-identical calls (tool-specific normalization): also blocked
- Total tool failures per USER REQUEST: max 5
- Absolute iterations: 15 (enforced in agent loop)

Lifecycle: Reset ONCE at START of each user request (in on_user_submit, NOT in generator).
"""

import hashlib
import json
import logging
import re
from typing import Dict, Any, List, Tuple, Optional

from .error_context import ErrorContext

logger = logging.getLogger(__name__)


class ErrorRecoveryTracker:
    """
    Track retry attempts and ENFORCE loop prevention.

    This is the CONTROLLER in the model+controller pattern. It enforces
    constraints programmatically rather than trusting the LLM to follow
    prompt guidance.

    Key Features:
    - Stable hashing with json.dumps + sha256 (not Python hash())
    - Tool-specific argument normalization to catch "wiggling"
    - Per-error-type retry counting (different errors = different budgets)
    - Approach history for LLM context (capped to prevent DoS)

    Usage:
        tracker = ErrorRecoveryTracker()

        # At start of each user request (NOT in generator!)
        tracker.reset()

        # Before executing a tool call
        is_repeat, summary = tracker.is_repeated_failed_call(tool_name, tool_args)
        if is_repeat:
            blocked_calls.append(summary)
            continue  # Don't execute

        # After a tool fails
        error_context = tracker.record_failure(
            error_type=classify_error(result.error),
            tool_name=tool_name,
            tool_args=tool_args,
            error_message=result.error,
            exit_code=result.exit_code,
        )

        # Check if retry should be allowed
        allowed, reason = tracker.should_allow_retry(tool_name, error_type)
        if not allowed:
            # Stop with user explanation
            yield TextDelta(content=format_stop_explanation(reason, error_context))
            return
    """

    # Tool-specific field normalization to catch "wiggling" attacks
    # where the LLM makes trivial changes to bypass repeat detection
    NORMALIZE_FIELDS: Dict[str, Dict[str, str]] = {
        "run_command": {"command": "collapse_whitespace"},
        "read_file": {"file_path": "normalize_path"},
        "write_file": {"file_path": "normalize_path"},
        "edit_file": {"file_path": "normalize_path"},  # DON'T normalize patch content
        "list_directory": {"path": "normalize_path"},
        "search_code": {"pattern": "strip"},
    }

    def __init__(
        self,
        max_same_tool_error_failures: int = 4,
        max_total_failures: int = 10
    ):
        """
        Initialize ErrorRecoveryTracker.

        Args:
            max_same_tool_error_failures: Max failures for same tool+error_type combo
            max_total_failures: Max total failures per user request
        """
        self.max_same_tool_error_failures = max_same_tool_error_failures
        self.max_total_failures = max_total_failures

        # Set of signature hashes for calls that have failed
        self._failed_call_signatures: set[str] = set()

        # Count failures by (tool_name, error_type) - different errors get separate budgets
        self._failed_tool_error_counts: Dict[Tuple[str, str], int] = {}

        # History of approaches tried (for LLM context)
        self._approach_history: List[Dict[str, Any]] = []

        # Total failures in this request
        self._total_failures = 0

    def _normalize_args(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tool-specific argument normalization to catch "wiggling".

        Different tools have different fields that should be normalized:
        - Commands: collapse whitespace (` cmd  arg ` -> `cmd arg`)
        - File paths: normalize separators and strip
        - Patterns: strip whitespace

        Args:
            tool_name: Name of the tool
            tool_args: Original arguments

        Returns:
            Normalized arguments dict
        """
        normalized = {}
        field_rules = self.NORMALIZE_FIELDS.get(tool_name, {})

        for key, value in tool_args.items():
            if isinstance(value, str) and key in field_rules:
                rule = field_rules[key]
                if rule == "collapse_whitespace":
                    value = re.sub(r'\s+', ' ', value.strip())
                elif rule == "normalize_path":
                    value = value.strip()
                    # Normalize path separators (Windows/Unix)
                    value = re.sub(r'[\\/]+', '/', value)
                elif rule == "strip":
                    value = value.strip()
            # Don't normalize fields not in rules (e.g., patch content, file content)
            normalized[key] = value

        return normalized

    def _stable_signature(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """
        Generate stable hash for tool call.

        Uses json.dumps with sort_keys=True for deterministic ordering,
        then sha256 for a stable hash (Python's hash() is not stable across runs).

        Args:
            tool_name: Name of the tool
            tool_args: Arguments (will be normalized)

        Returns:
            32-character hex signature (128 bits for collision resistance)
        """
        normalized = self._normalize_args(tool_name, tool_args)
        canonical = json.dumps({"tool": tool_name, "args": normalized}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    def _get_key_args(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """
        Get a human-readable summary of key arguments for blocked call messages.

        This is shown to the LLM in controller constraints so it knows exactly
        what was blocked, not just the tool name.

        Args:
            tool_name: Name of the tool
            tool_args: Arguments dictionary

        Returns:
            Summary string like `run_command(cmd="ls -la...")` or just tool_name
        """
        if tool_name == "run_command" and "command" in tool_args:
            cmd = tool_args["command"]
            # Truncate long commands
            cmd_preview = cmd[:50] + "..." if len(cmd) > 50 else cmd
            return f'{tool_name}(cmd="{cmd_preview}")'
        if "file_path" in tool_args:
            return f'{tool_name}(path="{tool_args["file_path"]}")'
        if "path" in tool_args:
            return f'{tool_name}(path="{tool_args["path"]}")'
        return tool_name

    def is_repeated_failed_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Check if this exact call has FAILED before.

        This is the first line of defense - if we've seen this exact call
        (after normalization) fail before, we block it immediately without
        even executing.

        Args:
            tool_name: Name of the tool
            tool_args: Arguments dictionary

        Returns:
            Tuple of (is_repeat, summary_with_args)
            - is_repeat: True if this call failed before
            - summary_with_args: Human-readable summary (empty if not repeat)
        """
        sig = self._stable_signature(tool_name, tool_args)
        is_repeat = sig in self._failed_call_signatures
        summary = self._get_key_args(tool_name, tool_args) if is_repeat else ""

        logger.debug(
            f"Checking {tool_name}: sig={sig[:8]}..., "
            f"known_failures={len(self._failed_call_signatures)}, is_repeat={is_repeat}"
        )

        if is_repeat:
            logger.info(f"BLOCKED repeated failed call: {summary}")

        return is_repeat, summary

    def should_allow_retry(
        self,
        tool_name: str,
        error_type: str
    ) -> Tuple[bool, str]:
        """
        Check if retry should be allowed for this tool+error_type.

        Called AFTER recording a failure. Uses separate budgets per error type
        so "command not found" errors don't consume the budget for "test failed"
        errors.

        Args:
            tool_name: Name of the tool that failed
            error_type: Classification of the error

        Returns:
            Tuple of (allowed, reason)
            - allowed: True if retry should be allowed
            - reason: Human-readable explanation (for both allow and deny)
        """
        if self._total_failures >= self.max_total_failures:
            return False, f"Maximum total failures ({self.max_total_failures}) reached"

        # Key by (tool, error_type) - "command not found" != "test failed"
        key = (tool_name, error_type)
        count = self._failed_tool_error_counts.get(key, 0)
        if count >= self.max_same_tool_error_failures:
            return False, (
                f"Tool '{tool_name}' with error type '{error_type}' "
                f"failed {self.max_same_tool_error_failures} time(s)"
            )

        return True, "Retry allowed with different approach"

    def record_failure(
        self,
        error_type: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        error_message: str,
        exit_code: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        working_dir: Optional[str] = None
    ) -> ErrorContext:
        """
        Record a FAILURE and return structured context for LLM.

        This updates all tracking state and returns an ErrorContext that can
        be injected into the LLM prompt for informed decision-making.

        Args:
            error_type: Classification of the error
            tool_name: Name of the tool that failed
            tool_args: Arguments that were passed to the tool
            error_message: The error message
            exit_code: Exit code if applicable (commands)
            stdout: Standard output if applicable (last 500 chars used)
            stderr: Standard error if applicable (last 500 chars used)
            working_dir: Working directory when error occurred

        Returns:
            ErrorContext with all failure information
        """
        sig = self._stable_signature(tool_name, tool_args)

        # Record the signature so identical calls are blocked
        self._failed_call_signatures.add(sig)

        # Count by (tool, error_type) for per-type budget
        key = (tool_name, error_type)
        self._failed_tool_error_counts[key] = self._failed_tool_error_counts.get(key, 0) + 1
        self._total_failures += 1

        # Add to approach history (for LLM context)
        args_summary = self._get_key_args(tool_name, tool_args)
        self._approach_history.append({
            "tool": tool_name,
            "args_summary": args_summary,
            "error_type": error_type,
            "result_summary": error_message[:100]
        })

        # Cap history size to prevent unbounded memory growth
        if len(self._approach_history) > 10:
            self._approach_history = self._approach_history[-10:]

        return ErrorContext(
            error_type=error_type,
            tool_name=tool_name,
            tool_args=tool_args,
            error_message=error_message,
            exit_code=exit_code,
            stdout_tail=stdout[-500:] if stdout else None,
            stderr_tail=stderr[-500:] if stderr else None,
            working_dir=working_dir,
            attempt_number=self._failed_tool_error_counts[key],
            previous_attempts=self._approach_history[-3:]  # Cap at 3 for context
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get current tracking statistics.

        Returns:
            Dictionary with total failures, failed signatures count, etc.
        """
        return {
            "total_failures": self._total_failures,
            "unique_failed_calls": len(self._failed_call_signatures),
            "failed_tool_error_counts": dict(self._failed_tool_error_counts),
            "approach_history_length": len(self._approach_history),
        }

    @property
    def total_failures(self) -> int:
        """Get total failure count (public accessor)."""
        return self._total_failures

    def reset_tool_error_counts(self, tool_name: Optional[str] = None) -> None:
        """
        Reset per-tool-error counters (partial recovery).

        Called when user chooses 'Continue' after error budget pause.

        Args:
            tool_name: If provided, reset only counters for this tool.
                       If None, reset all tool counters.

        Preserves:
        - _total_failures (safety limit still applies)
        - _failed_call_signatures (exact same calls still blocked)
        """
        if tool_name is None:
            # Reset all tool counters
            self._failed_tool_error_counts.clear()
        else:
            # Reset only the failing tool (safer, more controlled)
            # Keys are (tool_name, error_type) tuples
            keys_to_remove = [k for k in self._failed_tool_error_counts if k[0] == tool_name]
            for key in keys_to_remove:
                del self._failed_tool_error_counts[key]

    def reset(self) -> None:
        """
        Reset for new USER REQUEST.

        IMPORTANT: Call this in on_user_submit() or at the START of stream_response(),
        NOT inside the tool execution loop - that would reset mid-request!
        """
        self._failed_call_signatures.clear()
        self._failed_tool_error_counts.clear()
        self._approach_history.clear()
        self._total_failures = 0


# Export
__all__ = ['ErrorRecoveryTracker']
