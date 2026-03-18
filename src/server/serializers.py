"""Pure functions for UIEvent/StoreNotification <-> JSON conversion.

Separated from protocol code for unit testing without transport dependencies.

Serialization strategy:
- Use dataclasses.asdict() as the default serializer for UIEvent dataclasses
- Apply special-case overrides for types that need transformation:
  - Enum values -> .name.lower()
  - StreamStart -> empty dict (no fields)
  - FAILED status -> normalized to "error" (see tool_status.py)
- StoreNotification serialization extracts relevant fields from the
  notification + embedded ToolExecutionState objects
"""

from dataclasses import asdict
from enum import Enum
from typing import Optional

from src.core.events import (
    CodeBlockDelta,
    CodeBlockEnd,
    CodeBlockStart,
    ContextCompacted,
    ContextCompacting,
    ContextUpdated,
    ErrorEvent,
    FileReadEvent,
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
    UIEvent,
)
from src.core.protocol import (
    ApprovalResult,
    ClarifyResult,
    InterruptSignal,
    PauseResult,
    PlanApprovalResult,
    RetrySignal,
    UserAction,
)
from src.session.store.memory_store import (
    StoreEvent,
    StoreNotification,
    ToolExecutionState,
)
from src.observability import get_logger

logger = get_logger(__name__)


def _content_to_str(content) -> str:
    """Safely convert message content to a string for the wire protocol.

    Content is normally a str, but multimodal messages (with images) store it
    as a list of content blocks. The webview expects a string, so we extract
    the text parts — same logic as _build_replay_messages in stdio_server.py.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content) if content else ""


# ============================================================================
# UIEvent type name mapping
# ============================================================================

_EVENT_TYPE_MAP = {
    StreamStart: "stream_start",
    StreamEnd: "stream_end",
    TextDelta: "text_delta",
    CodeBlockStart: "code_block_start",
    CodeBlockDelta: "code_block_delta",
    CodeBlockEnd: "code_block_end",
    ThinkingStart: "thinking_start",
    ThinkingDelta: "thinking_delta",
    ThinkingEnd: "thinking_end",
    PausePromptStart: "pause_prompt_start",
    PausePromptEnd: "pause_prompt_end",
    ContextUpdated: "context_updated",
    ContextCompacting: "context_compacting",
    ContextCompacted: "context_compacted",
    FileReadEvent: "file_read",
    ErrorEvent: "error",
    # Legacy types (should not be serialized, but map them for safety)
    ToolCallStart: "tool_call_start",
    ToolCallStatus: "tool_call_status",
    ToolCallResult: "tool_call_result",
}


def _event_type_name(event: UIEvent) -> str:
    """Get the wire protocol type name for a UIEvent."""
    return _EVENT_TYPE_MAP.get(type(event), type(event).__name__.lower())


def _normalize_value(value):
    """Recursively normalize values for JSON serialization."""
    if isinstance(value, Enum):
        return value.name.lower()
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize_value(item) for item in value]
    return value


# ============================================================================
# UIEvent -> JSON
# ============================================================================


def serialize_event(event: UIEvent) -> dict | None:
    """Convert UIEvent to JSON-serializable dict.

    Uses dataclasses.asdict() with special-case overrides.
    Returns None for legacy event types (ToolCallStart/Status/Result).
    """
    # Skip legacy tool events (handled via StoreNotification)
    if isinstance(event, ToolCallStart | ToolCallStatus | ToolCallResult):
        return None

    data = asdict(event)
    data["type"] = _event_type_name(event)

    # Normalize enum values recursively
    for key in list(data.keys()):
        if key == "type":
            continue
        data[key] = _normalize_value(data[key])

    return data


# ============================================================================
# StoreNotification -> JSON
# ============================================================================


def serialize_tool_status(status) -> str:
    """Convert ToolStatus enum to wire string.

    Normalizes FAILED -> "error" to match the canonical ToolStatus
    enum in src/core/tool_status.py.
    """
    name = status.name.lower()
    if name == "failed":
        return "error"
    return name


def serialize_store_notification(notification: StoreNotification) -> dict | None:
    """Convert StoreNotification to JSON-serializable dict.

    Returns None for events not relevant to the wire protocol
    (e.g., BULK_LOAD_COMPLETE, STORE_CLEARED, SNAPSHOT_ADDED).
    """
    event = notification.event

    if event == StoreEvent.TOOL_STATE_UPDATED:
        tool_state = notification.tool_state
        if tool_state is None:
            return None

        data = {
            "call_id": notification.tool_call_id,
            "status": serialize_tool_status(tool_state.status),
        }

        # Include optional fields only when present
        if tool_state.result is not None:
            data["result"] = str(tool_state.result)
        if tool_state.error is not None:
            data["error"] = tool_state.error
        if tool_state.duration_ms is not None:
            data["duration_ms"] = tool_state.duration_ms

        # Include metadata (tool_name, args, requires_approval, etc.)
        metadata = notification.metadata or {}
        if "tool_name" in metadata:
            data["tool_name"] = metadata["tool_name"]
        if "arguments" in metadata:
            data["arguments"] = metadata["arguments"]
        if "requires_approval" in metadata:
            data["requires_approval"] = metadata["requires_approval"]
        if "message" in metadata:
            data["message"] = metadata["message"]

        return {
            "type": "store",
            "event": "tool_state_updated",
            "data": data,
        }

    elif event == StoreEvent.MESSAGE_ADDED:
        msg = notification.message
        if msg is None:
            return None

        # Detect interactive system events (clarify, plan approval)
        if msg.is_system and msg.meta and msg.meta.event_type:
            event_type = msg.meta.event_type
            extra = msg.meta.extra or {}

            if event_type == "clarify_request":
                return {
                    "type": "interactive",
                    "event": "clarify_request",
                    "data": {
                        "uuid": msg.uuid,
                        "call_id": extra.get("call_id", ""),
                        "questions": extra.get("questions", []),
                        "context": extra.get("context"),
                    },
                }

            elif event_type in ("plan_submitted", "director_plan_submitted"):
                return {
                    "type": "interactive",
                    "event": event_type,
                    "data": {
                        "uuid": msg.uuid,
                        "call_id": extra.get("call_id", ""),
                        "plan_hash": extra.get("plan_hash", ""),
                        "excerpt": extra.get("excerpt", ""),
                        "truncated": extra.get("truncated", False),
                        "plan_path": extra.get("plan_path"),
                    },
                }

            elif event_type == "permission_mode_changed":
                return {
                    "type": "interactive",
                    "event": "permission_mode_changed",
                    "data": {
                        "uuid": msg.uuid,
                        "old_mode": extra.get("old_mode", ""),
                        "new_mode": extra.get("new_mode", ""),
                    },
                }

        content_type = type(msg.content).__name__
        logger.debug(
            "serialize_message_added",
            uuid=msg.uuid,
            role=msg.role,
            content_type=content_type,
        )
        if not isinstance(msg.content, str):
            logger.warning(
                "serialize_message_added_non_string_content",
                uuid=msg.uuid,
                role=msg.role,
                content_type=content_type,
            )

        return {
            "type": "store",
            "event": "message_added",
            "data": {
                "uuid": msg.uuid,
                "role": msg.role,
                "content": _content_to_str(msg.content),
                "stream_id": getattr(msg.meta, "stream_id", None),
            },
        }

    elif event == StoreEvent.MESSAGE_UPDATED:
        msg = notification.message
        if msg is None:
            return None
        if not isinstance(msg.content, str):
            logger.warning(
                "serialize_message_updated_non_string_content",
                uuid=msg.uuid,
                role=msg.role,
                content_type=type(msg.content).__name__,
            )
        return {
            "type": "store",
            "event": "message_updated",
            "data": {
                "uuid": msg.uuid,
                "role": msg.role,
                "content": _content_to_str(msg.content),
            },
        }

    elif event == StoreEvent.MESSAGE_FINALIZED:
        metadata = notification.metadata or {}
        return {
            "type": "store",
            "event": "message_finalized",
            "data": {
                "stream_id": metadata.get("stream_id", ""),
            },
        }

    # Events not relevant to the wire protocol
    return None


# ============================================================================
# JSON -> UserAction
# ============================================================================


def deserialize_action(data: dict) -> UserAction | None:
    """Convert JSON dict to UserAction. Returns None for unknown types."""
    msg_type = data.get("type")

    if msg_type == "approval_result":
        return ApprovalResult(
            call_id=data["call_id"],
            approved=data["approved"],
            auto_approve_future=data.get("auto_approve_future", False),
            feedback=data.get("feedback"),
        )

    elif msg_type == "interrupt":
        return InterruptSignal()

    elif msg_type == "retry":
        return RetrySignal()

    elif msg_type == "pause_result":
        return PauseResult(
            continue_work=data["continue_work"],
            feedback=data.get("feedback"),
        )

    elif msg_type == "clarify_result":
        return ClarifyResult(
            call_id=data["call_id"],
            submitted=data.get("submitted", False),
            responses=data.get("responses"),
            chat_instead=data.get("chat_instead", False),
            chat_message=data.get("chat_message"),
        )

    elif msg_type == "plan_approval_result":
        return PlanApprovalResult(
            plan_hash=data["plan_hash"],
            approved=data["approved"],
            auto_accept_edits=data.get("auto_accept_edits", False),
            feedback=data.get("feedback"),
        )

    return None
