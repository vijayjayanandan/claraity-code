"""UI-agnostic tool execution status types.

This module defines tool status enums that can be imported by:
- MessageStore (for ephemeral tool_state)
- Agent (for updating tool lifecycle)
- UI (for rendering tool cards)

IMPORTANT: Store MUST NOT import status types from src/ui/*.
All components import from this module instead.
"""

from enum import Enum, auto


class ToolStatus(Enum):
    """Tool execution lifecycle states."""
    PENDING = auto()           # Tool call received, not yet started
    AWAITING_APPROVAL = auto() # Waiting for user approval
    APPROVED = auto()          # User approved, about to execute
    REJECTED = auto()          # User rejected
    RUNNING = auto()           # Currently executing
    SUCCESS = auto()           # Completed successfully
    ERROR = auto()             # Completed with error
    TIMEOUT = auto()           # Execution timed out
    CANCELLED = auto()         # User cancelled mid-execution
    SKIPPED = auto()           # Blocked (e.g., repeated failed call)
