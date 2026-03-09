"""
Agent Events - Shared contract between Agent and all UI handlers.

These events are emitted by the Agent and consumed by:
- CLI Handler (prints formatted output)
- TUI Handler (store notifications + these events for ephemeral signals)

Design Principles:
- Frozen dataclasses for immutability
- Agent emits these, never prints directly
- UI handlers subscribe and render however they want
- This module lives in core/ so agent has no UI dependency
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class ToolStatus(Enum):
    """Tool execution lifecycle states."""

    PENDING = auto()  # Queued, not yet started
    AWAITING_APPROVAL = auto()  # Waiting for user confirmation
    APPROVED = auto()  # User approved, about to execute
    REJECTED = auto()  # User rejected
    RUNNING = auto()  # Currently executing
    SUCCESS = auto()  # Completed successfully
    FAILED = auto()  # Completed with error
    ERROR = auto()  # Tool execution error (alias for FAILED)
    TIMEOUT = auto()  # Tool execution timed out
    CANCELLED = auto()  # User cancelled mid-execution
    SKIPPED = auto()  # Blocked (e.g., repeated failed call)


# =============================================================================
# Stream Lifecycle Events
# =============================================================================


@dataclass(frozen=True)
class StreamStart:
    """New assistant response starting.

    UI should create a new MessageWidget for the assistant.
    """

    pass


@dataclass(frozen=True)
class StreamEnd:
    """Stream complete (normal termination).

    UI should finalize the current message and re-focus input.
    """

    total_tokens: int | None = None
    duration_ms: int | None = None


# =============================================================================
# Text Content Events
# =============================================================================


@dataclass(frozen=True)
class TextDelta:
    """Incremental text content to append to the current markdown block.

    These arrive debounced (not per-token) for smooth rendering.
    The UI should accumulate and render as Markdown.
    """

    content: str


# =============================================================================
# Code Block Events
# =============================================================================


@dataclass(frozen=True)
class CodeBlockStart:
    """Start a new syntax-highlighted code block.

    The UI should create a new CodeBlock widget.
    Subsequent CodeBlockDelta events append to this block.
    """

    language: str

    def __post_init__(self):
        # Normalize empty/None language to "text"
        if not self.language:
            object.__setattr__(self, "language", "text")


@dataclass(frozen=True)
class CodeBlockDelta:
    """Incremental code content to append to the current code block."""

    content: str


@dataclass(frozen=True)
class CodeBlockEnd:
    """Current code block is complete.

    UI should finalize the block (update border, stop streaming indicator).
    """

    pass


# =============================================================================
# Tool Call Events (legacy - kept for backward compatibility)
# =============================================================================


@dataclass(frozen=True)
class ToolCallStart:
    """A complete, parsed tool call ready for execution.

    Note: No longer yielded by the agent. Kept for backward compatibility.
    Tool cards are now created from store notifications.
    """

    call_id: str
    name: str
    arguments: dict[str, Any]
    requires_approval: bool


@dataclass(frozen=True)
class ToolCallStatus:
    """Tool execution status update.

    Note: No longer yielded by the agent. Kept for backward compatibility.
    Tool status is now driven by store notifications.
    """

    call_id: str
    status: ToolStatus
    message: str | None = None


@dataclass(frozen=True)
class ToolCallResult:
    """Tool execution completed with result.

    Note: No longer yielded by the agent. Kept for backward compatibility.
    Tool results are now persisted to the store directly.
    """

    call_id: str
    status: ToolStatus
    result: Any = None
    error: str | None = None
    duration_ms: int | None = None


# =============================================================================
# Thinking/Reasoning Events (for models with extended thinking)
# =============================================================================


@dataclass(frozen=True)
class ThinkingStart:
    """Model started extended thinking/reasoning.

    UI should create a collapsible ThinkingBlock.
    """

    pass


@dataclass(frozen=True)
class ThinkingDelta:
    """Incremental thinking content."""

    content: str


@dataclass(frozen=True)
class ThinkingEnd:
    """Thinking phase complete.

    UI should finalize the thinking block and show token count.
    """

    token_count: int | None = None


# =============================================================================
# Pause/Continue Events
# =============================================================================


@dataclass(frozen=True)
class PausePromptStart:
    """Agent paused and awaiting user decision to continue or stop.

    Emitted when agent hits a budget limit (tool calls, wall time, iterations).
    UI should display a pause widget with Continue/Stop options.
    """

    reason: str
    reason_code: str
    pending_todos: list[str]
    stats: dict[str, Any]


@dataclass(frozen=True)
class PausePromptEnd:
    """User responded to pause prompt."""

    continue_work: bool
    feedback: str | None = None


# =============================================================================
# Context Window Events
# =============================================================================


@dataclass(frozen=True)
class ContextUpdated:
    """Context window usage updated.

    Emitted after each context build so UI can display usage progress bar.
    """

    used: int
    limit: int
    pressure_level: str = "green"


@dataclass(frozen=True)
class ContextCompacting:
    """Compaction is about to start.

    Emitted just before the LLM summarization call so the UI can show
    a 'Compacting Conversation' indicator in the status bar.
    """

    tokens_before: int


@dataclass(frozen=True)
class ContextCompacted:
    """Context was compacted to free up space.

    Emitted when orchestrator triggers compaction due to threshold breach.
    """

    messages_removed: int
    tokens_before: int
    tokens_after: int


# =============================================================================
# Error Events
# =============================================================================


@dataclass(frozen=True)
class ErrorEvent:
    """Error during streaming.

    Attributes:
        error_type: Category for determining recovery behavior
            - "provider_timeout": LLM request timed out
            - "network": Connection error (auto-retry)
            - "rate_limit": Rate limited (auto-retry with countdown)
            - "api_error": Provider API error
            - "auth": Authentication error (fatal)
        user_message: Safe, user-friendly message (NO stack traces)
        error_id: Reference ID for looking up full details in logs
        recoverable: Whether automatic retry is possible
        retry_after: Seconds to wait before retry (for rate limits)
    """

    error_type: str
    user_message: str
    error_id: str = ""
    recoverable: bool = True
    retry_after: int | None = None


# =============================================================================
# File Operations Events
# =============================================================================


@dataclass(frozen=True)
class FileReadEvent:
    """Emitted when the agent reads a file (for TUI annotations).

    Attributes:
        path: File path that was read
        lines_read: Number of lines read
        truncated: Whether the content was truncated
    """

    path: str
    lines_read: int = 0
    truncated: bool = False


# =============================================================================
# Type Union for Pattern Matching
# =============================================================================

UIEvent = (
    StreamStart
    | StreamEnd
    | TextDelta
    | CodeBlockStart
    | CodeBlockDelta
    | CodeBlockEnd
    | ToolCallStart
    | ToolCallStatus
    | ToolCallResult
    | ThinkingStart
    | ThinkingDelta
    | ThinkingEnd
    | PausePromptStart
    | PausePromptEnd
    | ContextUpdated
    | ContextCompacting
    | ContextCompacted
    | FileReadEvent
    | ErrorEvent
)

# Export all event types
__all__ = [
    "ToolStatus",
    "StreamStart",
    "StreamEnd",
    "TextDelta",
    "CodeBlockStart",
    "CodeBlockDelta",
    "CodeBlockEnd",
    "ToolCallStart",
    "ToolCallStatus",
    "ToolCallResult",
    "ThinkingStart",
    "ThinkingDelta",
    "ThinkingEnd",
    "PausePromptStart",
    "PausePromptEnd",
    "ContextUpdated",
    "ContextCompacting",
    "ContextCompacted",
    "FileReadEvent",
    "ErrorEvent",
    "UIEvent",
]
