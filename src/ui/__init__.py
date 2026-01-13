"""UI components for AI Coding Agent."""

# Existing prompt_toolkit-based UI (to be replaced)
from .formatters import ToolOutputFormatter, format_tool_call
from .chat_interface import ChatTUI, run_tui_chat

# New Textual-based UI (Session 1: Foundation)
from .events import (
    ToolStatus,
    StreamStart, StreamEnd,
    TextDelta,
    CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    ErrorEvent,
    UIEvent,
)
from .messages import (
    ApprovalResponseMessage,
    StreamInterruptMessage,
    RetryRequestMessage,
    ScrollStateChangedMessage,
    InputSubmittedMessage,
)
from .protocol import (
    ApprovalResult,
    InterruptSignal,
    RetrySignal,
    UserAction,
    UIProtocol,
)

# Session 2: Stream Processor
from .stream_processor import (
    StreamState,
    ToolCallAccumulator,
    StreamProcessor,
)

# Session 3: Widgets
from .widgets import (
    CodeBlock,
    ThinkingBlock,
    ToolCard,
    ToolApprovalOptions,
    MessageWidget,
    StatusBar,
)

# Session 4: App and Integration
from .app import CodingAgentApp, ChatInput, run_app
from .agent_adapter import (
    AgentStreamAdapter,
    create_stream_handler,
    demo_stream_handler,
)

__all__ = [
    # Existing (prompt_toolkit)
    "ToolOutputFormatter", "format_tool_call", "ChatTUI", "run_tui_chat",
    # Events
    "ToolStatus",
    "StreamStart", "StreamEnd",
    "TextDelta",
    "CodeBlockStart", "CodeBlockDelta", "CodeBlockEnd",
    "ToolCallStart", "ToolCallStatus", "ToolCallResult",
    "ThinkingStart", "ThinkingDelta", "ThinkingEnd",
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
    # Stream Processor
    "StreamState",
    "ToolCallAccumulator",
    "StreamProcessor",
    # Widgets
    "CodeBlock",
    "ThinkingBlock",
    "ToolCard",
    "ToolApprovalOptions",
    "MessageWidget",
    "StatusBar",
    # App and Integration
    "CodingAgentApp",
    "ChatInput",
    "run_app",
    "AgentStreamAdapter",
    "create_stream_handler",
    "demo_stream_handler",
]
