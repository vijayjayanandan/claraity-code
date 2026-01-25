"""Anthropic API response translator.

Converts Anthropic API responses to unified Message format.
Flattens content blocks, preserves order in segments, puts thinking in meta.
"""

from typing import Dict, Any, List, Optional
import json

from ..models.base import generate_uuid, now_iso, generate_stream_id
from ..models.message import (
    Message,
    MessageMeta,
    ToolCall,
    ToolCallFunction,
    TokenUsage,
    TextSegment,
    ToolCallSegment,
    ThinkingSegment,
    Segment,
)


def map_stop_reason(stop_reason: Optional[str]) -> str:
    """Map Anthropic stop_reason to our format."""
    mapping = {
        "end_turn": "complete",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "stop_sequence": "stop_sequence",
        None: "streaming",
    }
    return mapping.get(stop_reason, "complete")


def from_anthropic(
    response: Dict[str, Any],
    session_id: str,
    parent_uuid: Optional[str],
    seq: int,
    stream_id: Optional[str] = None,
) -> Message:
    """
    Convert Anthropic API response to Message.

    Flattens content blocks:
    - text blocks → concatenated content
    - tool_use blocks → tool_calls array
    - thinking blocks → meta.thinking

    Preserves order in meta.segments.

    Args:
        response: Anthropic API response dict
        session_id: Current session ID
        parent_uuid: Parent message UUID
        seq: Sequence number from store
        stream_id: Optional stream ID (generated if not provided)

    Returns:
        Message with OpenAI core fields and ClarAIty meta
    """
    content_blocks = response.get("content", [])

    # Process content blocks
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []
    segments: List[Segment] = []
    thinking: Optional[str] = None
    thinking_signature: Optional[str] = None

    for block in content_blocks:
        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "")
            text_parts.append(text)
            segments.append(TextSegment(content=text))

        elif block_type == "thinking":
            thinking = block.get("thinking", "")
            thinking_signature = block.get("signature")
            segments.append(ThinkingSegment(content=thinking))

        elif block_type == "tool_use":
            tool_call = ToolCall(
                id=block.get("id", ""),
                function=ToolCallFunction(
                    name=block.get("name", ""),
                    arguments=json.dumps(block.get("input", {}))
                ),
                type="function"
            )
            tool_calls.append(tool_call)
            segments.append(ToolCallSegment(tool_call_index=len(tool_calls) - 1))

    # Concatenate text for OpenAI-compatible content field
    content = "\n".join(text_parts) if text_parts else None

    # Parse usage
    usage = None
    if "usage" in response:
        usage_data = response["usage"]
        usage = TokenUsage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            cache_read_tokens=usage_data.get("cache_read_input_tokens"),
            cache_write_tokens=usage_data.get("cache_creation_input_tokens"),
        )

    # Only include segments if there's interleaving (more than one segment type)
    segment_types = set(type(s).__name__ for s in segments)
    include_segments = len(segment_types) > 1 or len(segments) > 1

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
            provider="anthropic",
            model=response.get("model"),
            stop_reason=map_stop_reason(response.get("stop_reason")),
            usage=usage,
            segments=segments if include_segments else None,
            thinking=thinking,
            thinking_signature=thinking_signature,
            provider_message_id=response.get("id"),
        )
    )

    # Store raw response for runtime debugging (NOT persisted)
    message._raw_response = response

    return message


def from_anthropic_stream_event(
    event: Dict[str, Any],
    session_id: str,
    parent_uuid: Optional[str],
    seq: int,
    stream_id: str,
    accumulated_text: str = "",
    accumulated_tool_calls: Optional[List[ToolCall]] = None,
    accumulated_thinking: str = "",
    current_block_type: Optional[str] = None,
    current_block_index: int = 0,
) -> Message:
    """
    Convert Anthropic streaming event to Message.

    Anthropic streams with events like:
    - message_start
    - content_block_start
    - content_block_delta
    - content_block_stop
    - message_delta
    - message_stop

    Args:
        event: Anthropic streaming event
        session_id: Current session ID
        parent_uuid: Parent message UUID
        seq: Sequence number from store
        stream_id: Stream ID (must be consistent across events)
        accumulated_text: Text accumulated so far
        accumulated_tool_calls: Tool calls accumulated so far
        accumulated_thinking: Thinking accumulated so far
        current_block_type: Type of current content block being streamed
        current_block_index: Index of current content block

    Returns:
        Message representing current stream state
    """
    if accumulated_tool_calls is None:
        accumulated_tool_calls = []

    event_type = event.get("type", "")

    # Handle different event types
    if event_type == "content_block_start":
        block = event.get("content_block", {})
        current_block_type = block.get("type")

        if current_block_type == "tool_use":
            accumulated_tool_calls.append(
                ToolCall(
                    id=block.get("id", ""),
                    function=ToolCallFunction(
                        name=block.get("name", ""),
                        arguments=""
                    ),
                    type="function"
                )
            )

    elif event_type == "content_block_delta":
        delta = event.get("delta", {})
        delta_type = delta.get("type", "")

        if delta_type == "text_delta":
            accumulated_text += delta.get("text", "")

        elif delta_type == "thinking_delta":
            accumulated_thinking += delta.get("thinking", "")

        elif delta_type == "input_json_delta":
            # Tool call arguments being streamed
            if accumulated_tool_calls:
                tc = accumulated_tool_calls[-1]
                accumulated_tool_calls[-1] = ToolCall(
                    id=tc.id,
                    function=ToolCallFunction(
                        name=tc.function.name,
                        arguments=tc.function.arguments + delta.get("partial_json", "")
                    ),
                    type=tc.type
                )

    # Build segments
    segments: List[Segment] = []
    if accumulated_thinking:
        segments.append(ThinkingSegment(content=accumulated_thinking))
    if accumulated_text:
        segments.append(TextSegment(content=accumulated_text))
    for i in range(len(accumulated_tool_calls)):
        segments.append(ToolCallSegment(tool_call_index=i))

    # Determine stop reason
    stop_reason = "streaming"
    if event_type == "message_stop":
        stop_reason = "complete"
    elif event_type == "message_delta":
        delta = event.get("delta", {})
        if delta.get("stop_reason"):
            stop_reason = map_stop_reason(delta["stop_reason"])

    return Message(
        role="assistant",
        content=accumulated_text if accumulated_text else None,
        tool_calls=accumulated_tool_calls,
        meta=MessageMeta(
            uuid=generate_uuid(),
            seq=seq,
            timestamp=now_iso(),
            session_id=session_id,
            parent_uuid=parent_uuid,
            is_sidechain=False,
            stream_id=stream_id,
            provider="anthropic",
            stop_reason=stop_reason,
            segments=segments if len(segments) > 1 else None,
            thinking=accumulated_thinking if accumulated_thinking else None,
        )
    )


def to_anthropic(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Convert Messages to Anthropic API request format.

    Expands tool_calls back to content blocks.

    Args:
        messages: List of Message objects

    Returns:
        List of dicts ready for Anthropic API
    """
    result = []

    for msg in messages:
        if msg.role == "system":
            # Anthropic handles system separately, skip in messages array
            continue

        if msg.role == "assistant" and (msg.tool_calls or msg.meta.thinking):
            # Expand to content blocks (has tool_calls or thinking)
            content_blocks = []

            # Add thinking if present
            if msg.meta.thinking:
                content_blocks.append({
                    "type": "thinking",
                    "thinking": msg.meta.thinking
                })

            # Add text if present
            if msg.content:
                content_blocks.append({
                    "type": "text",
                    "text": msg.content
                })

            # Add tool_use blocks
            for tc in msg.tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": tc.function.get_parsed_arguments()
                })

            result.append({
                "role": "assistant",
                "content": content_blocks
            })

        elif msg.role == "tool":
            # Tool result
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content or ""
                }]
            })

        else:
            # User or simple assistant message
            result.append({
                "role": msg.role,
                "content": msg.content or ""
            })

    return result


def get_system_prompt(messages: List[Message]) -> Optional[str]:
    """
    Extract system prompt for Anthropic API.

    Anthropic takes system as a separate parameter, not in messages array.

    Args:
        messages: List of Message objects

    Returns:
        System prompt string or None
    """
    for msg in messages:
        if msg.role == "system":
            return msg.content
    return None
