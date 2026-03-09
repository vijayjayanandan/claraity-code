"""ClarAIty Session Persistence Module.

JSONL-based session persistence for the ClarAIty CLI coding agent.

Architecture:
- Ledger = JSONL file (full fidelity, append-only)
- Projection = Memory Store (collapsed, indexed, filtered)
- Ordering = by seq (line number on replay, monotonic counter at runtime)

Schema v2.1: OpenAI-anchored with ClarAIty extensions.
- Single unified Message class
- OpenAI core: role, content, tool_calls, tool_call_id
- ClarAIty extensions: meta (stripped for LLM)
- Collapse by stream_id (not provider_message_id)

Modules:
- models/: Unified Message class and related types
- store/: In-memory message store with indexes and projections
- persistence/: Parser and writer for JSONL files
- providers/: API response translators (OpenAI, Anthropic)
- manager/: Session lifecycle management

For more details, see:
- docs/CLARAITY_SESSION_SCHEMA_v2.1.md
- docs/CLAUDE_CODE_REFACTOR_INSTRUCTIONS.md
"""

from .manager import (
    SessionInfo,
    SessionManager,
)
from .manager.hydrator import (
    AgentState,
    HydrationReport,
    HydrationResult,
    SessionHydrator,
)
from .models import (
    # Constants
    SCHEMA_VERSION,
    FileBackup,
    FileHistorySnapshot,
    # Unified message
    Message,
    # Message meta
    MessageMeta,
    Segment,
    SessionContext,
    # File snapshots
    Snapshot,
    # Segment types
    TextSegment,
    ThinkingSegment,
    # Token usage
    TokenUsage,
    ToolCall,
    # Tool calls
    ToolCallFunction,
    ToolCallSegment,
    generate_stream_id,
    # Utilities
    generate_uuid,
    now_iso,
    parse_segment,
)
from .persistence import (
    ParseError,
    SessionWriter,
    WriteResult,
    append_to_session,
    create_session_file,
    get_session_info,
    load_session,
    parse_file_iter,
    parse_line,
    validate_session_file,
)
from .providers import (
    from_anthropic,
    from_openai,
    to_anthropic,
    to_openai,
)
from .store import (
    MessageStore,
    SeqCollisionError,
    StoreEvent,
    StoreNotification,
    Subscriber,
)

__all__ = [
    # Constants
    "SCHEMA_VERSION",
    # Utilities
    "generate_uuid",
    "now_iso",
    "generate_stream_id",
    "SessionContext",
    # Segment types
    "TextSegment",
    "ToolCallSegment",
    "ThinkingSegment",
    "Segment",
    "parse_segment",
    # Tool calls
    "ToolCallFunction",
    "ToolCall",
    # Token usage
    "TokenUsage",
    # Message meta
    "MessageMeta",
    # Unified message
    "Message",
    # File snapshots
    "Snapshot",
    "FileBackup",
    "FileHistorySnapshot",
    # Store
    "MessageStore",
    "StoreEvent",
    "StoreNotification",
    "SeqCollisionError",
    "Subscriber",
    # Persistence
    "ParseError",
    "parse_line",
    "parse_file_iter",
    "load_session",
    "validate_session_file",
    "get_session_info",
    "WriteResult",
    "SessionWriter",
    "create_session_file",
    "append_to_session",
    # Manager
    "SessionManager",
    "SessionInfo",
    # Hydrator
    "SessionHydrator",
    "HydrationResult",
    "AgentState",
    "HydrationReport",
    # Providers
    "from_openai",
    "to_openai",
    "from_anthropic",
    "to_anthropic",
]
