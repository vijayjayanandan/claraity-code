"""Unified Message class - OpenAI-anchored with ClarAIty extensions.

Design principle: OpenAI messages are the canonical shape. Everything else is `meta`.

Schema: v2.1
- OpenAI Core: role, content, tool_calls, tool_call_id
- ClarAIty Extensions: meta (MessageMeta)
- Runtime Only: _raw_response (NOT persisted)
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .base import SCHEMA_VERSION, generate_stream_id, generate_uuid, now_iso

# =============================================================================
# Segment Types (for content ordering)
# =============================================================================

@dataclass
class TextSegment:
    """Text segment in ordered content."""
    content: str
    type: str = field(default="text", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextSegment":
        return cls(content=data.get("content", ""))


@dataclass
class CodeBlockSegment:
    """Code block segment with language."""
    language: str
    content: str
    type: str = field(default="code_block", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "language": self.language,
            "content": self.content
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeBlockSegment":
        return cls(
            language=data.get("language", ""),
            content=data.get("content", "")
        )


@dataclass
class ToolCallSegment:
    """Tool call segment referencing tool_calls array index (DEPRECATED - use ToolCallRefSegment)."""
    tool_call_index: int
    type: str = field(default="tool_call", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "tool_call_index": self.tool_call_index}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallSegment":
        return cls(tool_call_index=data.get("tool_call_index", 0))


@dataclass
class ToolCallRefSegment:
    """Tool call segment referencing tool_calls by ID (stable reference)."""
    tool_call_id: str
    type: str = field(default="tool_call_ref", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "tool_call_id": self.tool_call_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallRefSegment":
        return cls(tool_call_id=data.get("tool_call_id", ""))


@dataclass
class ThinkingSegment:
    """Thinking segment for extended thinking content."""
    content: str
    type: str = field(default="thinking", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThinkingSegment":
        return cls(content=data.get("content", ""))


Segment = TextSegment | CodeBlockSegment | ToolCallSegment | ToolCallRefSegment | ThinkingSegment


def parse_segment(data: dict[str, Any]) -> Segment:
    """Parse segment from dict."""
    seg_type = data.get("type", "text")
    if seg_type == "text":
        return TextSegment.from_dict(data)
    elif seg_type == "code_block":
        return CodeBlockSegment.from_dict(data)
    elif seg_type == "tool_call":
        return ToolCallSegment.from_dict(data)
    elif seg_type == "tool_call_ref":
        return ToolCallRefSegment.from_dict(data)
    elif seg_type == "thinking":
        return ThinkingSegment.from_dict(data)
    else:
        # Unknown segment type - treat as text
        return TextSegment(content=str(data.get("content", "")))


# =============================================================================
# ToolCall (OpenAI-compatible)
# =============================================================================

@dataclass
class ToolCallFunction:
    """Function details in a tool call."""
    name: str
    arguments: str  # JSON string

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallFunction":
        return cls(
            name=data.get("name", ""),
            arguments=data.get("arguments", "{}")
        )

    def get_parsed_arguments(self) -> dict[str, Any]:
        """Parse arguments JSON string to dict."""
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            return {}


@dataclass
class ToolCall:
    """OpenAI-compatible tool call with optional ClarAIty meta."""
    id: str
    function: ToolCallFunction
    type: str = "function"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "type": self.type,
            "function": self.function.to_dict()
        }
        if self.meta:
            result["meta"] = self.meta
        return result

    def to_llm_dict(self) -> dict[str, Any]:
        """Export for LLM API (strip meta)."""
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(
            id=data.get("id", ""),
            function=ToolCallFunction.from_dict(data.get("function", {})),
            type=data.get("type", "function"),
            meta=data.get("meta", {})
        )

    @classmethod
    def from_provider(
        cls,
        provider_id: str,
        function: "ToolCallFunction",
        type: str = "function",
    ) -> "ToolCall":
        """Create ToolCall with canonical ID, preserving provider's native ID in meta.

        Use this when creating ToolCalls from LLM provider responses.
        The provider-generated ID (e.g. toolu_xxx, call_xxx) is stored in
        meta['provider_tool_id'] for debugging. The canonical ID (tc_<hex32>)
        is safe for all providers, enabling model switching mid-session.
        """
        from src.session.models.base import generate_tool_call_id
        return cls(
            id=generate_tool_call_id(),
            function=function,
            type=type,
            meta={"provider_tool_id": provider_id},
        )


# =============================================================================
# TokenUsage
# =============================================================================

@dataclass
class TokenUsage:
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens
        }
        if self.cache_read_tokens is not None:
            result["cache_read_tokens"] = self.cache_read_tokens
        if self.cache_write_tokens is not None:
            result["cache_write_tokens"] = self.cache_write_tokens
        if self.reasoning_tokens is not None:
            result["reasoning_tokens"] = self.reasoning_tokens
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenUsage":
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens"),
            cache_write_tokens=data.get("cache_write_tokens"),
            reasoning_tokens=data.get("reasoning_tokens")
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# =============================================================================
# MessageMeta (ClarAIty Extensions)
# =============================================================================

@dataclass
class MessageMeta:
    """ClarAIty extensions - stripped for LLM context."""
    # Required
    schema_version: int = SCHEMA_VERSION
    uuid: str = ""
    seq: int = 0
    timestamp: str = ""
    session_id: str = ""
    parent_uuid: str | None = None
    is_sidechain: bool = False

    # Streaming
    stream_id: str | None = None
    provider_message_id: str | None = None

    # Provider
    provider: str | None = None  # "anthropic" | "openai" | "ollama" | "local"
    model: str | None = None

    # Completion
    stop_reason: str | None = None  # "complete" | "tool_use" | "max_tokens" | "stop_sequence" | "streaming" | "error"
    usage: TokenUsage | None = None

    # Content Ordering (v2.1)
    segments: list[Segment] | None = None

    # Thinking
    thinking: str | None = None
    thinking_signature: str | None = None

    # Reasoning (Kimi K2.5 etc.) - echoed back in to_llm_dict() for iteration 2+
    reasoning_content: str | None = None

    # Tool Execution
    status: str | None = None  # "success" | "error" | "timeout" | "cancelled"
    duration_ms: int | None = None
    exit_code: int | None = None
    truncated: bool | None = None

    # System Events
    event_type: str | None = None  # "compact_boundary" | "turn_duration" | "session_start"
    include_in_llm_context: bool | None = None

    # Compaction
    pre_tokens: int | None = None
    logical_parent_uuid: str | None = None

    # UI Hints
    is_compact_summary: bool | None = None
    is_visible_in_transcript_only: bool | None = None

    # Extensible
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize meta to dict."""
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "uuid": self.uuid,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "parent_uuid": self.parent_uuid,
            "is_sidechain": self.is_sidechain,
        }

        # Optional fields - only include if set
        if self.stream_id is not None:
            result["stream_id"] = self.stream_id
        if self.provider_message_id is not None:
            result["provider_message_id"] = self.provider_message_id
        if self.provider is not None:
            result["provider"] = self.provider
        if self.model is not None:
            result["model"] = self.model
        if self.stop_reason is not None:
            result["stop_reason"] = self.stop_reason
        if self.usage is not None:
            result["usage"] = self.usage.to_dict()
        if self.segments is not None:
            result["segments"] = [s.to_dict() for s in self.segments]
        if self.thinking is not None:
            result["thinking"] = self.thinking
        if self.thinking_signature is not None:
            result["thinking_signature"] = self.thinking_signature
        if self.reasoning_content is not None:
            result["reasoning_content"] = self.reasoning_content
        if self.status is not None:
            result["status"] = self.status
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        if self.truncated is not None:
            result["truncated"] = self.truncated
        if self.event_type is not None:
            result["event_type"] = self.event_type
        if self.include_in_llm_context is not None:
            result["include_in_llm_context"] = self.include_in_llm_context
        if self.pre_tokens is not None:
            result["pre_tokens"] = self.pre_tokens
        if self.logical_parent_uuid is not None:
            result["logical_parent_uuid"] = self.logical_parent_uuid
        if self.is_compact_summary is not None:
            result["is_compact_summary"] = self.is_compact_summary
        if self.is_visible_in_transcript_only is not None:
            result["is_visible_in_transcript_only"] = self.is_visible_in_transcript_only
        if self.extra is not None:
            result["extra"] = self.extra

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessageMeta":
        """Deserialize from dict."""
        usage = None
        if "usage" in data:
            usage = TokenUsage.from_dict(data["usage"])

        segments = None
        if "segments" in data:
            segments = [parse_segment(s) for s in data["segments"]]

        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            uuid=data.get("uuid", ""),
            seq=data.get("seq", 0),
            timestamp=data.get("timestamp", ""),
            session_id=data.get("session_id", ""),
            parent_uuid=data.get("parent_uuid"),
            is_sidechain=data.get("is_sidechain", False),
            stream_id=data.get("stream_id"),
            provider_message_id=data.get("provider_message_id"),
            provider=data.get("provider"),
            model=data.get("model"),
            stop_reason=data.get("stop_reason"),
            usage=usage,
            segments=segments,
            thinking=data.get("thinking"),
            thinking_signature=data.get("thinking_signature"),
            reasoning_content=data.get("reasoning_content"),
            status=data.get("status"),
            duration_ms=data.get("duration_ms"),
            exit_code=data.get("exit_code"),
            truncated=data.get("truncated"),
            event_type=data.get("event_type"),
            include_in_llm_context=data.get("include_in_llm_context"),
            pre_tokens=data.get("pre_tokens"),
            logical_parent_uuid=data.get("logical_parent_uuid"),
            is_compact_summary=data.get("is_compact_summary"),
            is_visible_in_transcript_only=data.get("is_visible_in_transcript_only"),
            extra=data.get("extra")
        )


# =============================================================================
# Message (Unified)
# =============================================================================

@dataclass
class Message:
    """
    Unified message class - OpenAI-anchored with ClarAIty extensions.

    OpenAI Core (sent to LLM):
    - role: "system" | "user" | "assistant" | "tool"
    - content: string | null
    - tool_calls: ToolCall[] (assistant only)
    - tool_call_id: string (tool only)

    ClarAIty Extensions:
    - meta: MessageMeta (stripped for LLM)

    Runtime Only:
    - _raw_response: original provider response (NOT persisted)
    """
    # OpenAI Core
    role: str
    content: str | list[dict[str, Any]] | None = None  # str for text, list for multimodal
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    # ClarAIty Extensions
    meta: MessageMeta = field(default_factory=MessageMeta)

    # Runtime only - NOT persisted
    _raw_response: dict[str, Any] | None = field(
        default=None, repr=False, compare=False
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSONL. Excludes _raw_response."""
        result: dict[str, Any] = {
            "role": self.role,
            "meta": self.meta.to_dict()
        }

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]

        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id

        return result

    def to_llm_dict(self) -> dict[str, Any]:
        """Export for LLM API (strip meta)."""
        result: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = [tc.to_llm_dict() for tc in self.tool_calls]

        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id

        if self.role == "assistant" and self.meta and self.meta.reasoning_content:
            result["reasoning_content"] = self.meta.reasoning_content

        if (self.role == "assistant" and self.meta
                and self.meta.thinking and self.meta.thinking_signature):
            result["thinking"] = self.meta.thinking
            result["thinking_signature"] = self.meta.thinking_signature

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], seq: int = 0) -> "Message":
        """
        Deserialize from JSONL dict.

        Args:
            data: The parsed JSON dict
            seq: Sequence number (from line number during replay)
        """
        meta_data = data.get("meta", {})
        if seq > 0 and meta_data.get("seq", 0) == 0:
            meta_data["seq"] = seq

        tool_calls = [ToolCall.from_dict(tc) for tc in data.get("tool_calls", [])]

        return cls(
            role=data.get("role", "user"),
            content=data.get("content"),
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
            meta=MessageMeta.from_dict(meta_data)
        )

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def create_user(
        cls,
        content: str,
        session_id: str,
        parent_uuid: str | None,
        seq: int,
        **meta_kwargs
    ) -> "Message":
        """Create a user message."""
        # Remove parent_uuid from meta_kwargs to avoid duplicate parameter error
        meta_kwargs.pop('parent_uuid', None)

        return cls(
            role="user",
            content=content,
            meta=MessageMeta(
                uuid=generate_uuid(),
                seq=seq,
                timestamp=now_iso(),
                session_id=session_id,
                parent_uuid=parent_uuid,
                is_sidechain=False,
                **meta_kwargs
            )
        )

    @classmethod
    def create_assistant(
        cls,
        content: str | None,
        session_id: str,
        parent_uuid: str | None,
        seq: int,
        tool_calls: list[ToolCall] | None = None,
        stream_id: str | None = None,
        **meta_kwargs
    ) -> "Message":
        """Create an assistant message."""
        # Remove parent_uuid from meta_kwargs to avoid duplicate parameter error
        meta_kwargs.pop('parent_uuid', None)

        return cls(
            role="assistant",
            content=content,
            tool_calls=tool_calls or [],
            meta=MessageMeta(
                uuid=generate_uuid(),
                seq=seq,
                timestamp=now_iso(),
                session_id=session_id,
                parent_uuid=parent_uuid,
                is_sidechain=False,
                stream_id=stream_id or generate_stream_id(),
                **meta_kwargs
            )
        )

    @classmethod
    def create_tool(
        cls,
        tool_call_id: str,
        content: str,
        session_id: str,
        parent_uuid: str | None,
        seq: int,
        status: str = "success",
        duration_ms: int | None = None,
        exit_code: int | None = None,
        **meta_kwargs
    ) -> "Message":
        """Create a tool result message."""
        # Remove parent_uuid from meta_kwargs to avoid duplicate parameter error
        meta_kwargs.pop('parent_uuid', None)

        return cls(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            meta=MessageMeta(
                uuid=generate_uuid(),
                seq=seq,
                timestamp=now_iso(),
                session_id=session_id,
                parent_uuid=parent_uuid,
                is_sidechain=False,
                status=status,
                duration_ms=duration_ms,
                exit_code=exit_code,
                **meta_kwargs
            )
        )

    @classmethod
    def create_system(
        cls,
        content: str,
        session_id: str,
        seq: int,
        event_type: str | None = None,
        include_in_llm_context: bool | None = None,
        **meta_kwargs
    ) -> "Message":
        """Create a system message.

        Args:
            content: System message content
            session_id: Session ID
            seq: Sequence number
            event_type: Optional event type (e.g., "compact_boundary", "turn_duration")
            include_in_llm_context: Whether to include in LLM context.
                If None, determined by event_type (compact_boundary/turn_duration = False)
        """
        # Remove parent_uuid from meta_kwargs to avoid duplicate parameter error
        # (system messages always have parent_uuid=None)
        meta_kwargs.pop('parent_uuid', None)

        return cls(
            role="system",
            content=content,
            meta=MessageMeta(
                uuid=generate_uuid(),
                seq=seq,
                timestamp=now_iso(),
                session_id=session_id,
                parent_uuid=None,
                is_sidechain=False,
                event_type=event_type,
                include_in_llm_context=include_in_llm_context,
                **meta_kwargs
            )
        )

    @classmethod
    def create_agent_state(
        cls,
        session_id: str,
        todos: list[dict[str, Any]],
        current_todo_id: str | None = None,
        last_stop_reason: str | None = None,
        seq: int = 0,
    ) -> "Message":
        """Create an agent_state system event for session persistence.

        This event type stores agent runtime state (todos, current task, etc.)
        and is NOT included in LLM context. Used for session resume.

        Args:
            session_id: Session ID
            todos: List of todo dicts
            current_todo_id: ID of currently active todo
            last_stop_reason: Last stop reason for context
            seq: Sequence number
        """
        extra = {
            "todos": todos,
        }
        if current_todo_id is not None:
            extra["current_todo_id"] = current_todo_id
        if last_stop_reason is not None:
            extra["last_stop_reason"] = last_stop_reason

        return cls.create_system(
            content="[Agent State Snapshot]",
            session_id=session_id,
            seq=seq,
            event_type="agent_state",
            include_in_llm_context=False,
            extra=extra
        )

    @classmethod
    def create_tool_approval(
        cls,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        approved: bool,
        action: str,
        feedback: str | None = None,
        seq: int = 0,
    ) -> "Message":
        """Create a tool_approval system event for session persistence.

        This event type stores the user's approval/rejection decision for a tool call.
        NOT included in LLM context. Used for session resume to restore ToolCard states.

        Args:
            session_id: Session ID
            tool_call_id: The tool_call_id this approval responds to
            tool_name: Name of the tool
            approved: Whether the tool was approved
            action: The action taken ("yes", "yes_all", "no")
            feedback: Optional feedback text if rejected with feedback
            seq: Sequence number
        """
        extra = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "approved": approved,
            "action": action,
        }
        if feedback is not None:
            extra["feedback"] = feedback

        status_text = "approved" if approved else "rejected"
        return cls.create_system(
            content=f"[Tool {status_text}: {tool_name}]",
            session_id=session_id,
            seq=seq,
            event_type="tool_approval",
            include_in_llm_context=False,
            extra=extra
        )

    @classmethod
    def create_clarify_request(
        cls,
        session_id: str,
        call_id: str,
        questions: list[dict[str, Any]],
        context: str | None = None,
        seq: int = 0,
    ) -> "Message":
        """Create a clarify_request system event.

        Persists the questions asked. NOT in LLM context.
        Used for TUI rendering and session resume.

        Args:
            session_id: Session ID
            call_id: Tool call ID for correlation
            questions: List of question dicts with id, label, question, options
            context: Optional context explaining why clarification is needed
            seq: Sequence number
        """
        extra = {
            "call_id": call_id,
            "questions": questions,
            "context": context,
        }
        return cls.create_system(
            content="[Clarification requested]",
            session_id=session_id,
            seq=seq,
            event_type="clarify_request",
            include_in_llm_context=False,
            extra=extra
        )

    @classmethod
    def create_clarify_response(
        cls,
        session_id: str,
        call_id: str,
        submitted: bool,
        responses: dict[str, Any] | None = None,
        chat_instead: bool = False,
        chat_message: str | None = None,
        seq: int = 0,
    ) -> "Message":
        """Create a clarify_response system event.

        Persists the user's answers. NOT in LLM context.
        Used for session resume.

        Args:
            session_id: Session ID
            call_id: Tool call ID for correlation
            submitted: Whether user submitted answers (vs cancelled)
            responses: Dict of question_id -> selected_option_id(s)
            chat_instead: True if user chose to chat instead of answering
            chat_message: User's chat message if chat_instead=True
            seq: Sequence number
        """
        extra = {
            "call_id": call_id,
            "submitted": submitted,
            "responses": responses,
            "chat_instead": chat_instead,
            "chat_message": chat_message,
        }
        status = "submitted" if submitted else ("chat" if chat_instead else "cancelled")
        return cls.create_system(
            content=f"[Clarification {status}]",
            session_id=session_id,
            seq=seq,
            event_type="clarify_response",
            include_in_llm_context=False,
            extra=extra
        )

    # =========================================================================
    # Role Checks
    # =========================================================================

    @property
    def is_user(self) -> bool:
        return self.role == "user"

    @property
    def is_assistant(self) -> bool:
        return self.role == "assistant"

    @property
    def is_tool(self) -> bool:
        return self.role == "tool"

    @property
    def is_system(self) -> bool:
        return self.role == "system"

    # =========================================================================
    # Accessors
    # =========================================================================

    @property
    def uuid(self) -> str:
        return self.meta.uuid

    @property
    def seq(self) -> int:
        return self.meta.seq

    @property
    def session_id(self) -> str:
        return self.meta.session_id

    @property
    def parent_uuid(self) -> str | None:
        return self.meta.parent_uuid

    @property
    def is_sidechain(self) -> bool:
        return self.meta.is_sidechain

    @property
    def stream_id(self) -> str | None:
        return self.meta.stream_id

    @property
    def segments(self) -> list[Segment]:
        """Convenience accessor for meta.segments."""
        return self.meta.segments if self.meta.segments else []

    @segments.setter
    def segments(self, value: list[Segment]) -> None:
        """Convenience setter for meta.segments."""
        self.meta.segments = value

    def get_collapse_key(self) -> str | None:
        """Get key for streaming collapse (stream_id for assistant messages)."""
        if self.is_assistant:
            return self.meta.stream_id
        return None

    def get_tool_call_ids(self) -> list[str]:
        """Get IDs of tool calls in this message."""
        return [tc.id for tc in self.tool_calls]

    @property
    def should_include_in_context(self) -> bool:
        """Check if this message should be included in LLM context."""
        # Explicit setting takes precedence
        if self.meta.include_in_llm_context is not None:
            return self.meta.include_in_llm_context

        # System events with event_type are usually excluded
        if self.meta.event_type and self.meta.event_type in ("compact_boundary", "turn_duration"):
            return False

        # Visible in transcript only = excluded from LLM
        if self.meta.is_visible_in_transcript_only:
            return False

        return True

    # =========================================================================
    # Content Helpers
    # =========================================================================

    def get_text_content(self) -> str:
        """Get text content (handles None)."""
        return self.content or ""

    def has_tool_calls(self) -> bool:
        """Check if message has tool calls."""
        return bool(self.tool_calls)

    def get_ordered_content(self) -> list[Segment]:
        """
        Get content in display order.

        Returns segments if present, otherwise synthesizes from content/tool_calls.
        """
        if self.meta.segments:
            return self.meta.segments

        # Synthesize from flat fields
        segments: list[Segment] = []

        if self.content:
            segments.append(TextSegment(content=self.content))

        for i in range(len(self.tool_calls)):
            segments.append(ToolCallSegment(tool_call_index=i))

        return segments


# =============================================================================
# File Snapshot (for file history tracking)
# =============================================================================

@dataclass
class Snapshot:
    """Single file snapshot."""
    file_path: str
    content: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "content": self.content,
            "hash": self.hash
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        return cls(
            file_path=data.get("file_path", ""),
            content=data.get("content", ""),
            hash=data.get("hash", "")
        )


@dataclass
class FileBackup:
    """File backup for restoration."""
    file_path: str
    existed: bool
    content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "file_path": self.file_path,
            "existed": self.existed
        }
        if self.content is not None:
            result["content"] = self.content
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileBackup":
        return cls(
            file_path=data.get("file_path", ""),
            existed=data.get("existed", True),
            content=data.get("content")
        )


@dataclass
class FileHistorySnapshot:
    """Full file history snapshot for session."""
    uuid: str
    timestamp: str
    session_id: str
    snapshots: list[Snapshot] = field(default_factory=list)
    backups: list[FileBackup] = field(default_factory=list)
    type: str = field(default="file_snapshot", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "uuid": self.uuid,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "backups": [b.to_dict() for b in self.backups]
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileHistorySnapshot":
        return cls(
            uuid=data.get("uuid", ""),
            timestamp=data.get("timestamp", ""),
            session_id=data.get("session_id", ""),
            snapshots=[Snapshot.from_dict(s) for s in data.get("snapshots", [])],
            backups=[FileBackup.from_dict(b) for b in data.get("backups", [])]
        )

    @classmethod
    def create(cls, session_id: str) -> "FileHistorySnapshot":
        """Create a new empty snapshot."""
        return cls(
            uuid=generate_uuid(),
            timestamp=now_iso(),
            session_id=session_id
        )
