"""Core agent orchestration and logic."""

from .agent import CodingAgent
from .agent_interface import AgentInterface, MockAgent
from .agent_helpers import AgentContextProvider, AgentLLMProxy, AgentToolProxy
from .context_builder import ContextBuilder, ContextAssemblyReport, ContextBudgetExceededError
from .file_reference_parser import FileReferenceParser, FileReference
from .session_manager import SessionManager, SessionMetadata
from .events import (
    ToolStatus,
    ContentDelta,
    ContentComplete,
    ToolCallParsed,
    ToolExecutionStarted,
    ToolExecutionResult,
    StreamStarted,
    StreamEnded,
    StreamError,
    AgentEvent,
)

__all__ = [
    "CodingAgent",
    "AgentInterface",
    "MockAgent",
    "AgentContextProvider",
    "AgentLLMProxy",
    "AgentToolProxy",
    "ContextBuilder",
    "ContextAssemblyReport",
    "ContextBudgetExceededError",
    "FileReferenceParser",
    "FileReference",
    "SessionManager",
    "SessionMetadata",
    # Agent Events
    "ToolStatus",
    "ContentDelta",
    "ContentComplete",
    "ToolCallParsed",
    "ToolExecutionStarted",
    "ToolExecutionResult",
    "StreamStarted",
    "StreamEnded",
    "StreamError",
    "AgentEvent",
]
