"""
UI Event Types - The contract between StreamProcessor and Textual UI.

Design Principles:
- Frozen dataclasses for immutability
- Discriminated union via structural pattern matching
- No optional fields that change semantics (use separate event types)
- Events are facts about what happened, not commands
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Union


class ToolStatus(Enum):
    """Tool execution lifecycle states."""

    PENDING = auto()            # Queued, not yet started
    AWAITING_APPROVAL = auto()  # Waiting for user confirmation
    APPROVED = auto()           # User approved, about to execute
    REJECTED = auto()           # User rejected
    RUNNING = auto()            # Currently executing
    SUCCESS = auto()            # Completed successfully
    FAILED = auto()             # Completed with error
    CANCELLED = auto()          # User cancelled mid-execution
    SKIPPED = auto()            # Blocked (e.g., repeated failed call)


# =============================================================================
# Stream Lifecycle Events
# =============================================================================

@dataclass(frozen=True)
class StreamStart:
    """
    New assistant response starting.

    UI should create a new MessageWidget for the assistant.
    """
    pass


@dataclass(frozen=True)
class StreamEnd:
    """
    Stream complete (normal termination).

    UI should finalize the current message and re-focus input.
    """
    total_tokens: int | None = None
    duration_ms: int | None = None


# =============================================================================
# Text Content Events
# =============================================================================

@dataclass(frozen=True)
class TextDelta:
    """
    Incremental text content to append to the current markdown block.

    These arrive debounced (not per-token) for smooth rendering.
    The UI should accumulate and render as Markdown.
    """
    content: str


# =============================================================================
# Code Block Events
# =============================================================================

@dataclass(frozen=True)
class CodeBlockStart:
    """
    Start a new syntax-highlighted code block.

    The UI should create a new CodeBlock widget.
    Subsequent CodeBlockDelta events append to this block.
    """
    language: str

    def __post_init__(self):
        # Normalize empty/None language to "text"
        if not self.language:
            object.__setattr__(self, 'language', 'text')


@dataclass(frozen=True)
class CodeBlockDelta:
    """
    Incremental code content to append to the current code block.
    """
    content: str


@dataclass(frozen=True)
class CodeBlockEnd:
    """
    Current code block is complete.

    UI should finalize the block (update border, stop streaming indicator).
    """
    pass


# =============================================================================
# Tool Call Events
# =============================================================================

@dataclass(frozen=True)
class ToolCallStart:
    """
    A complete, parsed tool call ready for execution.

    IMPORTANT: This is only emitted when the full tool call has been
    accumulated (name + valid JSON arguments). The UI never sees raw JSON.

    Attributes:
        call_id: Unique identifier for tracking this tool call
        name: Tool function name (e.g., "read_file", "write_file", "bash")
        arguments: Fully parsed, validated arguments dict
        requires_approval: Whether user must approve before execution
    """
    call_id: str
    name: str
    arguments: dict[str, Any]
    requires_approval: bool


@dataclass(frozen=True)
class ToolCallStatus:
    """
    Tool execution status update.

    Emitted when tool transitions between states (pending -> running -> complete).
    """
    call_id: str
    status: ToolStatus
    message: str | None = None  # Optional status message (e.g., "Reading file...")


@dataclass(frozen=True)
class ToolCallResult:
    """
    Tool execution completed with result.

    This is the terminal event for a tool call.
    """
    call_id: str
    status: ToolStatus  # SUCCESS or FAILED
    result: Any = None
    error: str | None = None
    duration_ms: int | None = None


# =============================================================================
# Thinking/Reasoning Events (for models with extended thinking)
# =============================================================================

@dataclass(frozen=True)
class ThinkingStart:
    """
    Model started extended thinking/reasoning.

    UI should create a collapsible ThinkingBlock.
    """
    pass


@dataclass(frozen=True)
class ThinkingDelta:
    """
    Incremental thinking content.
    """
    content: str


@dataclass(frozen=True)
class ThinkingEnd:
    """
    Thinking phase complete.

    UI should finalize the thinking block and show token count.
    """
    token_count: int | None = None


# =============================================================================
# Pause/Continue Events
# =============================================================================

@dataclass(frozen=True)
class PausePromptStart:
    """
    Agent paused and awaiting user decision to continue or stop.

    Emitted when agent hits a budget limit (tool calls, wall time, iterations).
    UI should display a pause widget with Continue/Stop options.

    Attributes:
        reason: Human-readable reason for pause (e.g., "Tool limit reached")
        reason_code: Machine-readable code (e.g., "max_tool_calls")
        pending_todos: List of incomplete task descriptions
        stats: Execution stats (tool_calls, elapsed_s, iterations)
    """
    reason: str
    reason_code: str
    pending_todos: list[str]
    stats: dict[str, Any]


@dataclass(frozen=True)
class PausePromptEnd:
    """
    User responded to pause prompt.

    Emitted after user makes a decision.
    """
    continue_work: bool
    feedback: str | None = None


# =============================================================================
# Context Window Events
# =============================================================================

@dataclass(frozen=True)
class ContextUpdated:
    """
    Context window usage updated.

    Emitted after each context build so UI can display usage progress bar.

    Attributes:
        used: Tokens currently used in assembled context
        limit: Maximum context window size
        pressure_level: Current pressure (green/yellow/orange/red)
    """
    used: int
    limit: int
    pressure_level: str = "green"


@dataclass(frozen=True)
class ContextCompacted:
    """
    Context was compacted to free up space.

    Emitted when orchestrator triggers compaction due to threshold breach.
    UI should display a notification like "Compacting conversation history..."

    Attributes:
        messages_removed: Number of messages removed from working memory
        tokens_before: Token count before compaction
        tokens_after: Token count after compaction
    """
    messages_removed: int
    tokens_before: int
    tokens_after: int


# =============================================================================
# Error Events
# =============================================================================

@dataclass(frozen=True)
class ErrorEvent:
    """
    Error during streaming.

    Attributes:
        error_type: Category for determining recovery behavior
            - "provider_timeout": LLM request timed out (show pause prompt)
            - "network": Connection error (auto-retry)
            - "rate_limit": Rate limited (auto-retry with countdown)
            - "api_error": Provider API error
            - "auth": Authentication error (fatal)
        user_message: Safe, user-friendly message (NO stack traces)
        error_id: Reference ID for looking up full details in logs/SQLite
        recoverable: Whether automatic retry is possible
        retry_after: Seconds to wait before retry (for rate limits)

    Note: Technical debug info (stack traces, exception chains) is stored
    in JSONL/SQLite keyed by error_id, NOT exposed to users by default.
    Set CLARITY_SHOW_DEBUG_ERRORS=1 to show debug info in TUI.
    """
    error_type: str
    user_message: str  # Safe message for display (no stack traces)
    error_id: str = ""  # Reference to look up full details in logs
    recoverable: bool = True
    retry_after: int | None = None


# =============================================================================
# Type Union for Pattern Matching
# =============================================================================

UIEvent = Union[
    StreamStart, StreamEnd,
    TextDelta,
    CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    PausePromptStart, PausePromptEnd,
    ContextUpdated, ContextCompacted,
    ErrorEvent
]

# Export all event types for convenient imports
__all__ = [
    'ToolStatus',
    'StreamStart', 'StreamEnd',
    'TextDelta',
    'CodeBlockStart', 'CodeBlockDelta', 'CodeBlockEnd',
    'ToolCallStart', 'ToolCallStatus', 'ToolCallResult',
    'ThinkingStart', 'ThinkingDelta', 'ThinkingEnd',
    'PausePromptStart', 'PausePromptEnd',
    'ContextUpdated', 'ContextCompacted',
    'ErrorEvent',
    'UIEvent',
]
