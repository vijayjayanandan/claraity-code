"""UI components for AI Coding Agent."""

# Existing prompt_toolkit-based UI (to be replaced)
# App
from .app import ChatInput, CodingAgentApp, run_app

# New Textual-based UI (Session 1: Foundation)
from .events import (
    CodeBlockDelta,
    CodeBlockEnd,
    CodeBlockStart,
    ErrorEvent,
    StreamEnd,
    StreamStart,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolStatus,
    UIEvent,
)
from .formatters import ToolOutputFormatter, format_tool_call
from .messages import (
    ApprovalResponseMessage,
    InputSubmittedMessage,
    RetryRequestMessage,
    ScrollStateChangedMessage,
    StreamInterruptMessage,
)
from .protocol import (
    ApprovalResult,
    InterruptSignal,
    RetrySignal,
    UIProtocol,
    UserAction,
)

# Widgets
from .widgets import (
    CodeBlock,
    MessageWidget,
    StatusBar,
    ThinkingBlock,
    ToolApprovalOptions,
    ToolCard,
)

__all__ = [
    # Existing (prompt_toolkit)
    "ToolOutputFormatter",
    "format_tool_call",
    # Events
    "ToolStatus",
    "StreamStart",
    "StreamEnd",
    "TextDelta",
    "CodeBlockStart",
    "CodeBlockDelta",
    "CodeBlockEnd",
    "ThinkingStart",
    "ThinkingDelta",
    "ThinkingEnd",
    "ErrorEvent",
    "UIEvent",
    # Messages
    "ApprovalResponseMessage",
    "StreamInterruptMessage",
    "RetryRequestMessage",
    "ScrollStateChangedMessage",
    "InputSubmittedMessage",
    # Protocol
    "ApprovalResult",
    "InterruptSignal",
    "RetrySignal",
    "UserAction",
    "UIProtocol",
    # Widgets
    "CodeBlock",
    "ThinkingBlock",
    "ToolCard",
    "ToolApprovalOptions",
    "MessageWidget",
    "StatusBar",
    # App
    "CodingAgentApp",
    "ChatInput",
    "run_app",
]
