"""Session models - OpenAI-anchored with ClarAIty extensions.

v2.1: Single unified Message class with OpenAI core + meta extensions.

Base utilities:
- generate_uuid(): UUID generation
- now_iso(): ISO timestamp
- generate_stream_id(): Stream ID for message collapse
- SessionContext: Session metadata

Message types:
- Message: Unified message (user, assistant, tool, system)
- MessageMeta: ClarAIty extensions (stripped for LLM)
- ToolCall: OpenAI-compatible tool call
- TokenUsage: Token usage statistics

Segment types (for content ordering):
- TextSegment: Text content
- ToolCallSegment: Tool call reference
- ThinkingSegment: Extended thinking content

File snapshots:
- FileHistorySnapshot: Session file history
- Snapshot: Single file snapshot
- FileBackup: File backup for restoration
"""

from .base import (
    SCHEMA_VERSION,
    SessionContext,
    generate_stream_id,
    generate_tool_call_id,
    generate_uuid,
    now_iso,
)
from .message import (
    FileBackup,
    FileHistorySnapshot,
    # Unified message
    Message,
    # Message meta
    MessageMeta,
    Segment,
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
    parse_segment,
)

__all__ = [
    # Constants
    "SCHEMA_VERSION",
    # Utilities
    "generate_uuid",
    "now_iso",
    "generate_stream_id",
    "generate_tool_call_id",
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
]
