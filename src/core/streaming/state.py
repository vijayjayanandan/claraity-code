"""Streaming state for tracking in-flight message assembly.

This module contains the StreamingState dataclass that tracks the current
state of a streaming message being assembled from provider deltas.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from src.session.models.base import generate_stream_id
from src.session.models.message import Segment, TokenUsage, ToolCall, ToolCallFunction


@dataclass
class ToolCallAccumulator:
    """Accumulates incremental tool call data during streaming."""
    id: str = ""
    name: str = ""
    arguments_buffer: str = ""  # Accumulated JSON string

    def is_complete(self) -> bool:
        """Check if tool call has all required fields."""
        return bool(self.id and self.name)

    def to_tool_call(self) -> ToolCall:
        """Convert accumulated data to ToolCall object.

        The ID is already canonical (generated at ProviderDelta emission
        in the backend), so we use the direct constructor to avoid
        double-generating a new canonical ID.
        """
        return ToolCall(
            id=self.id,
            function=ToolCallFunction(
                name=self.name,
                arguments=self.arguments_buffer or "{}"
            ),
        )


@dataclass
class StreamingState:
    """
    Tracks state of the current streaming message.

    This state is maintained by StreamingPipeline during delta processing
    and is used to build the final Message with segments.
    """
    # Identity
    stream_id: str = field(default_factory=generate_stream_id)
    session_id: str = ""
    parent_uuid: str | None = None

    # Text accumulation
    text_buffer: str = ""           # Current text being accumulated
    full_text_content: str = ""     # Complete text content for message.content

    # Code block state
    in_code_block: bool = False
    code_block_language: str = ""
    code_block_content: str = ""
    code_fence_buffer: str = ""     # Buffer for detecting fence patterns

    # Thinking state
    in_thinking: bool = False
    thinking_content: str = ""
    thinking_buffer: str = ""       # Buffer for detecting thinking tags
    thinking_signature: str = ""    # Anthropic thinking block signature

    # Reasoning content (Kimi K2.5 etc.) - must be echoed back on iteration 2+
    reasoning_content: str = ""

    # Tool call state
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_accumulators: dict[int, ToolCallAccumulator] = field(default_factory=dict)

    # Segments (ordered)
    segments: list[Segment] = field(default_factory=list)

    # Metrics
    usage: TokenUsage | None = None

    # Provider info
    provider: str | None = None
    model: str | None = None

    def reset(self) -> None:
        """Reset state for new stream."""
        self.stream_id = generate_stream_id()
        self.text_buffer = ""
        self.full_text_content = ""
        self.in_code_block = False
        self.code_block_language = ""
        self.code_block_content = ""
        self.code_fence_buffer = ""
        self.in_thinking = False
        self.thinking_content = ""
        self.thinking_buffer = ""
        self.thinking_signature = ""
        self.reasoning_content = ""
        self.tool_calls = []
        self.tool_call_accumulators = {}
        self.segments = []
        self.usage = None
