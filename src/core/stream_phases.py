"""
Stream Phases - Helper functions used by stream_response().

These are self-contained functions that compute and return values
without yielding or awaiting. Used by the async tool loop.

Functions:
- build_assistant_context_message: Format assistant msg with tool_calls for LLM context
- inject_controller_constraint: Add blocked-call constraint to context
- fill_skipped_tool_results: Add tool_result for rejected/skipped tool calls
- build_pause_stats: Compute stats dict for pause prompts
"""

import json
from typing import Any, Dict, List, Optional

from src.observability import get_logger

logger = get_logger(__name__)


def build_assistant_context_message(
    response_content: str,
    tool_calls: Optional[List] = None,
    reasoning_content: Optional[str] = None,
    thinking: Optional[str] = None,
    thinking_signature: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the assistant message dict to append to LLM context.

    This is the message that tells the LLM what it said and which tools
    it called, so it can see the tool results in the next turn.

    Used by stream_response().

    Args:
        response_content: Text content from the LLM response.
        tool_calls: List of ToolCall objects (or None if no tool calls).
        reasoning_content: Optional reasoning/thinking content to echo back
            (required by Kimi K2.5 and other reasoning models).
        thinking: Optional thinking block content (Anthropic extended thinking).
        thinking_signature: Optional thinking block signature for round-tripping.

    Returns:
        Dict in OpenAI message format with role="assistant".
    """
    msg: Dict[str, Any] = {
        "role": "assistant",
        "content": response_content or "",
    }

    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]

    # Echo back reasoning_content for models that require it (Kimi K2.5 etc.)
    if reasoning_content:
        msg["reasoning_content"] = reasoning_content

    # Round-trip thinking blocks for Anthropic extended thinking
    if thinking and thinking_signature:
        msg["thinking"] = thinking
        msg["thinking_signature"] = thinking_signature

    return msg


def inject_controller_constraint(
    context: List[Dict[str, Any]],
    blocked_calls: List[str],
) -> None:
    """Inject a controller constraint message when calls were blocked.

    Appends a user-role message to the context telling the LLM that
    specific calls were blocked and it must try a different approach.

    Mutates context in-place.

    Args:
        context: The LLM conversation context (mutated).
        blocked_calls: List of human-readable blocked call summaries.
    """
    if not blocked_calls:
        return

    constraint = (
        "[CONTROLLER] The following tool calls were BLOCKED because "
        "they previously failed:\n"
        + "\n".join(f"- {call}" for call in blocked_calls)
        + "\n\nREQUIRED: Choose a DIFFERENT approach:\n"
        "- Use a different tool, OR\n"
        "- Change arguments meaningfully (path, command), OR\n"
        "- Add a diagnostic step first (read_file, list_directory)\n"
        "- If impossible, explain to user why task cannot be completed"
    )

    context.append({
        "role": "user",
        "content": constraint,
    })


def fill_skipped_tool_results(
    tool_calls: List,
    processed_call_ids: set,
    reason: str = "Tool execution was skipped.",
) -> List[Dict[str, Any]]:
    """Generate tool_result messages for tool calls that were not executed.

    When the user rejects a tool or the loop breaks mid-iteration, some
    tool_calls may not have corresponding tool_result messages. The LLM
    API requires every tool_call to have a matching tool_result, so we
    fill in skipped ones.

    Args:
        tool_calls: All tool calls from the LLM response.
        processed_call_ids: Set of call IDs that were already processed.
        reason: The reason text to include in skipped results.

    Returns:
        List of tool_result message dicts for unprocessed calls.
    """
    skipped = []
    for tc in tool_calls:
        call_id = tc.id or ""
        if call_id not in processed_call_ids:
            skipped.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": tc.function.name,
                "content": reason,
            })
    return skipped


def build_pause_stats(
    tool_call_count: int,
    elapsed_seconds: float,
    iteration: int,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the stats dict for PausePromptStart events.

    Args:
        tool_call_count: Number of tool calls executed.
        elapsed_seconds: Wall time since loop started.
        iteration: Current iteration number.
        error: Optional provider error message.

    Returns:
        Stats dict for the pause widget.
    """
    stats: Dict[str, Any] = {
        "tool_calls": tool_call_count,
        "elapsed_s": elapsed_seconds,
        "iterations": iteration,
    }
    if error:
        stats["error"] = error
    return stats
