"""Hook events and decision types for in-process Python hooks.

This module defines the event types that can trigger hooks and the
decision types that hooks can return.
"""

from enum import Enum


class HookEvent(Enum):
    """All supported hook events.

    Hook events represent points in the agent's execution where
    user-defined hooks can be triggered to customize behavior.
    """

    PRE_TOOL_USE = "PreToolUse"
    """Triggered before a tool is executed.

    Allows hooks to:
    - Validate tool arguments
    - Modify arguments
    - Block execution
    """

    POST_TOOL_USE = "PostToolUse"
    """Triggered after a tool completes execution.

    Allows hooks to:
    - Inspect results
    - Modify results
    - Log execution
    - Verify outputs
    """

    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    """Triggered when user submits a prompt.

    Allows hooks to:
    - Validate user input
    - Modify prompt
    - Block inappropriate requests
    """

    NOTIFICATION = "Notification"
    """Triggered when agent requests user approval.

    Allows hooks to:
    - Auto-approve safe operations
    - Block dangerous operations
    - Custom approval logic
    """

    SESSION_START = "SessionStart"
    """Triggered when agent session starts.

    Allows hooks to:
    - Initialize resources
    - Load configuration
    - Set up logging
    """

    SESSION_END = "SessionEnd"
    """Triggered when agent session ends.

    Allows hooks to:
    - Cleanup resources
    - Save state
    - Generate reports
    """

    PRE_COMPACT = "PreCompact"
    """Triggered before context compaction.

    Allows hooks to:
    - Preserve important messages
    - Customize compaction strategy
    """

    STOP = "Stop"
    """Triggered after agent generates response.

    Allows hooks to:
    - Review agent output
    - Log responses
    - Modify formatting
    """

    SUBAGENT_STOP = "SubagentStop"
    """Triggered when subagent completes.

    Allows hooks to:
    - Inspect subagent results
    - Log subagent execution
    """


class HookDecision(Enum):
    """Decisions that hooks can make for PreToolUse events.

    These decisions control whether a tool operation proceeds or is blocked.
    """

    PERMIT = "permit"
    """Allow the operation to proceed.

    The tool will be executed with the (potentially modified) arguments.
    """

    DENY = "deny"
    """Reject the operation gracefully.

    The tool will not be executed, and an error result will be returned.
    This is a soft failure - the agent continues execution.
    """

    BLOCK = "block"
    """Block the operation with hard failure.

    The tool will not be executed, and an exception will be raised.
    This terminates the current workflow step.
    """


class HookContinue(Enum):
    """Decisions for UserPromptSubmit events."""

    CONTINUE = "continue"
    """Allow the prompt to be processed normally."""

    BLOCK = "block"
    """Block the prompt from being processed."""


class HookApproval(Enum):
    """Decisions for Notification events."""

    APPROVE = "approve"
    """Approve the requested operation."""

    DENY = "deny"
    """Deny the requested operation."""
