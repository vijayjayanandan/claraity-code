"""
Agent Events - Shared contract between Agent and all UI handlers.

These events are emitted by the Agent and consumed by:
- CLI Handler (prints formatted output)
- TUI Handler (via StreamProcessor → UIEvents → widgets)

Design Principles:
- Frozen dataclasses for immutability
- Agent emits these, never prints directly
- UI handlers subscribe and render however they want

Event Flow:
                        AgentEvent
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
    CLI Handler (direct)         StreamProcessor
              │                           │
              │                           ▼
              │                       UIEvent
              │                           │
              ▼                           ▼
        Rich console              Textual widgets
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Union


class ToolStatus(Enum):
    """Tool execution lifecycle."""
    STARTED = auto()       # Tool call parsed, about to execute
    RUNNING = auto()       # Execution in progress
    SUCCESS = auto()       # Completed successfully
    FAILED = auto()        # Completed with error
    CANCELLED = auto()     # User cancelled


# =============================================================================
# Content Events
# =============================================================================

@dataclass(frozen=True)
class ContentDelta:
    """
    Incremental LLM content.

    This is raw LLM output - no formatting, no tool announcements.
    May contain markdown, code fences, thinking tags, etc.
    StreamProcessor will parse these for TUI rendering.
    """
    content: str


@dataclass(frozen=True)
class ContentComplete:
    """LLM finished generating content (before tool calls)."""
    pass


# =============================================================================
# Tool Events
# =============================================================================

@dataclass(frozen=True)
class ToolCallParsed:
    """
    Tool call fully parsed and ready to execute.

    Emitted when we have complete tool name + valid JSON arguments.
    Never emit partial tool calls or raw JSON.
    """
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolExecutionStarted:
    """Tool execution has begun."""
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolExecutionResult:
    """
    Tool execution completed.

    For CLI: format and print the result
    For TUI: update the ToolCard widget
    """
    call_id: str
    name: str
    status: ToolStatus
    result: Any = None
    error: str | None = None
    duration_ms: int | None = None


# =============================================================================
# Stream Lifecycle
# =============================================================================

@dataclass(frozen=True)
class StreamStarted:
    """New response stream started."""
    pass


@dataclass(frozen=True)
class StreamEnded:
    """Response stream completed."""
    total_tokens: int | None = None


@dataclass(frozen=True)
class StreamError:
    """Error during streaming."""
    error_type: str  # "network", "rate_limit", "api_error"
    message: str
    recoverable: bool = True
    retry_after: int | None = None  # For rate limits


# =============================================================================
# Type Union
# =============================================================================

AgentEvent = Union[
    ContentDelta,
    ContentComplete,
    ToolCallParsed,
    ToolExecutionStarted,
    ToolExecutionResult,
    StreamStarted,
    StreamEnded,
    StreamError,
]


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    'ToolStatus',
    # Content Events
    'ContentDelta',
    'ContentComplete',
    # Tool Events
    'ToolCallParsed',
    'ToolExecutionStarted',
    'ToolExecutionResult',
    # Stream Lifecycle
    'StreamStarted',
    'StreamEnded',
    'StreamError',
    # Type Union
    'AgentEvent',
]
