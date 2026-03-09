"""Core agent orchestration and logic."""

# NOTE: CodingAgent is loaded lazily via __getattr__ below to break a circular
# import chain: src.core.__init__ -> src.core.agent -> src.llm -> src.session
# -> src.core.events -> src.core.__init__ (cycle). All other imports here are
# safe because they don't pull in src.llm at module level.

from .agent_helpers import AgentContextProvider, AgentLLMProxy, AgentToolProxy
from .agent_interface import AgentInterface, MockAgent
from .events import (
    CodeBlockDelta,
    CodeBlockEnd,
    CodeBlockStart,
    ContextCompacted,
    ContextUpdated,
    ErrorEvent,
    PausePromptEnd,
    PausePromptStart,
    StreamEnd,
    StreamStart,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolCallResult,
    ToolCallStart,
    ToolCallStatus,
    ToolStatus,
    UIEvent,
)

# NOTE: ContextBuilder is loaded lazily via __getattr__ below to break a
# circular import chain: src.memory.__init__ -> memory_manager -> src.core.render_meta
# -> src.core.__init__ -> context_builder -> src.memory (cycle).
from .file_reference_parser import FileReference, FileReferenceParser
from .session_manager import SessionManager, SessionMetadata

# Lazy-loaded names (not imported at module level to avoid circular imports)
_LAZY_IMPORTS = {
    "CodingAgent": ".agent",
    "ContextBuilder": ".context_builder",
    "ContextAssemblyReport": ".context_builder",
}


def __getattr__(name):
    if name in _LAZY_IMPORTS:
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        value = getattr(module, name)
        # Cache on the module so __getattr__ is only called once per name
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CodingAgent",
    "AgentInterface",
    "MockAgent",
    "AgentContextProvider",
    "AgentLLMProxy",
    "AgentToolProxy",
    "ContextBuilder",
    "ContextAssemblyReport",
    "FileReferenceParser",
    "FileReference",
    "SessionManager",
    "SessionMetadata",
    # Events
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
    "ContextCompacted",
    "ErrorEvent",
    "UIEvent",
]
