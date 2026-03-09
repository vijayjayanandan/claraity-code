"""OpenAI API response translator.

Converts OpenAI API responses to unified Message format.
OpenAI is the primary/canonical format - responses are already correct shape.
Just add meta and detect segments if needed.
"""

from typing import Any, Optional

from ..models.base import generate_stream_id, generate_uuid, now_iso
from ..models.message import (
    Message,
    MessageMeta,
    Segment,
    TextSegment,
    TokenUsage,
    ToolCall,
    ToolCallFunction,
    ToolCallSegment,
)


def map_stop_reason(finish_reason: str | None) -> str:
    """Map OpenAI finish_reason to our stop_reason."""
    mapping = {
        "stop": "complete",
        "tool_calls": "tool_use",
        "length": "max_tokens",
        "content_filter": "stop_sequence",
        None: "streaming",
    }
    return mapping.get(finish_reason, "complete")


def from_openai(
    response: dict[str, Any],
    session_id: str,
    parent_uuid: str | None,
    seq: int,
    stream_id: str | None = None,
) -> Message:
    """
    Convert OpenAI API response to Message.

    Response is already correct shape - just add meta and detect segments.

    Args:
        response: OpenAI API response dict
        session_id: Current session ID
        parent_uuid: Parent message UUID
        seq: Sequence number from store
        stream_id: Optional stream ID (generated if not provided)

    Returns:
        Message with OpenAI core fields and ClarAIty meta
    """
    choice = response.get("choices", [{}])[0]
    msg = choice.get("message", {})

    # Extract content and tool_calls
    content = msg.get("content")
    raw_tool_calls = msg.get("tool_calls") or []  # Handle None explicitly

    # Convert tool calls
    tool_calls = [
        ToolCall(
            id=tc.get("id", ""),
            function=ToolCallFunction(
                name=tc.get("function", {}).get("name", ""),
                arguments=tc.get("function", {}).get("arguments", "{}"),
            ),
            type=tc.get("type", "function"),
        )
        for tc in raw_tool_calls
    ]

    # Build segments only if both content and tool_calls present (interleaving)
    segments: list[Segment] | None = None
    if content and tool_calls:
        segments = [
            TextSegment(content=content),
            *[ToolCallSegment(tool_call_index=i) for i in range(len(tool_calls))],
        ]

    # Parse usage
    usage = None
    if "usage" in response:
        usage_data = response["usage"]
        usage = TokenUsage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
            reasoning_tokens=usage_data.get("reasoning_tokens"),
        )

    # Build message
    message = Message(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
        meta=MessageMeta(
            uuid=generate_uuid(),
            seq=seq,
            timestamp=now_iso(),
            session_id=session_id,
            parent_uuid=parent_uuid,
            is_sidechain=False,
            stream_id=stream_id or generate_stream_id(),
            provider="openai",
            model=response.get("model"),
            stop_reason=map_stop_reason(choice.get("finish_reason")),
            usage=usage,
            segments=segments,
            provider_message_id=response.get("id"),
        ),
    )

    # Store raw response for runtime debugging (NOT persisted)
    message._raw_response = response

    return message


def from_openai_stream_chunk(
    chunk: dict[str, Any],
    session_id: str,
    parent_uuid: str | None,
    seq: int,
    stream_id: str,
    accumulated_content: str = "",
    accumulated_tool_calls: list[ToolCall] | None = None,
) -> Message:
    """
    Convert OpenAI streaming chunk to Message.

    For streaming, we accumulate content and tool_calls across chunks.
    The stream_id stays constant so later chunks collapse earlier ones.

    Args:
        chunk: OpenAI streaming chunk
        session_id: Current session ID
        parent_uuid: Parent message UUID
        seq: Sequence number from store
        stream_id: Stream ID (must be consistent across chunks)
        accumulated_content: Content accumulated so far
        accumulated_tool_calls: Tool calls accumulated so far

    Returns:
        Message representing current stream state
    """
    choice = chunk.get("choices", [{}])[0]
    delta = choice.get("delta", {})
    finish_reason = choice.get("finish_reason")

    # Accumulate content
    if delta.get("content"):
        accumulated_content += delta["content"]

    # Accumulate tool calls (OpenAI sends them incrementally)
    if accumulated_tool_calls is None:
        accumulated_tool_calls = []

    if delta.get("tool_calls"):
        for tc_delta in delta["tool_calls"]:
            index = tc_delta.get("index", 0)

            # Extend list if needed
            while len(accumulated_tool_calls) <= index:
                accumulated_tool_calls.append(
                    ToolCall(id="", function=ToolCallFunction(name="", arguments=""))
                )

            tc = accumulated_tool_calls[index]

            # Update fields
            if tc_delta.get("id"):
                accumulated_tool_calls[index] = ToolCall(
                    id=tc_delta["id"], function=tc.function, type=tc_delta.get("type", tc.type)
                )
                tc = accumulated_tool_calls[index]

            if tc_delta.get("function"):
                func = tc_delta["function"]
                accumulated_tool_calls[index] = ToolCall(
                    id=tc.id,
                    function=ToolCallFunction(
                        name=tc.function.name + func.get("name", ""),
                        arguments=tc.function.arguments + func.get("arguments", ""),
                    ),
                    type=tc.type,
                )

    # Build segments if both present
    segments: list[Segment] | None = None
    if accumulated_content and accumulated_tool_calls:
        segments = [
            TextSegment(content=accumulated_content),
            *[ToolCallSegment(tool_call_index=i) for i in range(len(accumulated_tool_calls))],
        ]

    # Determine stop reason
    stop_reason = "streaming"
    if finish_reason:
        stop_reason = map_stop_reason(finish_reason)

    return Message(
        role="assistant",
        content=accumulated_content if accumulated_content else None,
        tool_calls=accumulated_tool_calls,
        meta=MessageMeta(
            uuid=generate_uuid(),
            seq=seq,
            timestamp=now_iso(),
            session_id=session_id,
            parent_uuid=parent_uuid,
            is_sidechain=False,
            stream_id=stream_id,
            provider="openai",
            model=chunk.get("model"),
            stop_reason=stop_reason,
            segments=segments,
            provider_message_id=chunk.get("id"),
        ),
    )


def to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """
    Convert Messages to OpenAI API request format.

    Strips meta - only includes OpenAI core fields.

    Args:
        messages: list of Message objects

    Returns:
        list of dicts ready for OpenAI API
    """
    return [msg.to_llm_dict() for msg in messages]
