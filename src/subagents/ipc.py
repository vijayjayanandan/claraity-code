"""IPC protocol for subprocess subagents.

Wire protocol: JSON lines over stdin/stdout.

Parent -> Child (stdin, kept open for bidirectional communication):
    Line 1: SubprocessInput with config, LLM settings, task, working directory.
    Line 2+: ApprovalResponse JSON lines (sent in reply to APPROVAL_REQUEST events).

Child -> Parent (stdout, one JSON line per event):
    IPCEventType.REGISTERED        - subagent bootstrapped
    IPCEventType.NOTIFICATION      - serialized StoreNotification
    IPCEventType.APPROVAL_REQUEST  - subagent needs user approval for a tool
    IPCEventType.DONE              - SubAgentResult
    IPCEventType.ERROR             - fatal error string
"""

import json
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.session.store.memory_store import StoreNotification, ToolExecutionState
    from src.subagents.subagent import SubAgentResult


# ============================================================================
# Parent -> Child: Input
# ============================================================================

@dataclass
class SubprocessInput:
    """Configuration sent from parent to child on stdin (single JSON line).

    Attributes:
        config: SubAgentConfig fields as dict (via dataclasses.asdict)
        llm_config: LLMConfig fields as dict (via .model_dump())
        api_key: API key for LLM backend
        task_description: The task the subagent should execute
        working_directory: Absolute path to project root
        max_iterations: Maximum tool-calling iterations
        transcript_path: Path for JSONL transcript file
    """
    config: dict[str, Any]
    llm_config: dict[str, Any]
    api_key: str
    task_description: str
    working_directory: str
    max_iterations: int = 50
    max_wall_time: float | None = 300.0
    transcript_path: str = ""
    permission_mode: str = "normal"
    auto_approve_tools: list[str] = field(default_factory=list)
    delegation_depth: int = 0

    def __repr__(self) -> str:
        """Redact api_key from repr to prevent leakage in tracebacks/logs."""
        key_display = f"{self.api_key[:4]}...{self.api_key[-4:]}" if len(self.api_key) > 8 else "***"
        return (
            f"SubprocessInput(config={self.config.get('name', '?')!r}, "
            f"api_key={key_display!r}, task={self.task_description[:50]!r}...)"
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), default=str, ensure_ascii=True)

    @classmethod
    def from_json(cls, json_str: str) -> "SubprocessInput":
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls(**data)


# ============================================================================
# Child -> Parent: Event Types
# ============================================================================

class IPCEventType(str, Enum):
    """Event types emitted by the subprocess child."""
    REGISTERED = "registered"              # Subagent bootstrapped, sends id + model
    NOTIFICATION = "notification"          # Serialized StoreNotification
    APPROVAL_REQUEST = "approval_request"  # Child needs user approval for a tool
    DONE = "done"                          # SubAgentResult
    ERROR = "error"                        # Fatal error string


# ============================================================================
# Serialization Helpers
# ============================================================================

def serialize_notification(notification: "StoreNotification") -> dict[str, Any]:
    """Serialize a StoreNotification for IPC transport.

    Converts Message objects via to_dict(), enums via .value,
    and ToolExecutionState to a plain dict.

    Args:
        notification: StoreNotification from MessageStore

    Returns:
        JSON-serializable dict
    """
    result: dict[str, Any] = {
        "event": notification.event.value,
    }

    if notification.message is not None:
        result["message"] = notification.message.to_dict()

    if notification.tool_call_id is not None:
        result["tool_call_id"] = notification.tool_call_id

    if notification.tool_state is not None:
        result["tool_state"] = {
            "status": notification.tool_state.status.name
                if hasattr(notification.tool_state.status, 'name')
                else str(notification.tool_state.status),
            "result": notification.tool_state.result,
            "error": notification.tool_state.error,
            "duration_ms": notification.tool_state.duration_ms,
        }

    if notification.metadata:
        result["metadata"] = notification.metadata

    return result


def deserialize_notification(data: dict[str, Any]) -> "StoreNotification":
    """Deserialize a StoreNotification from IPC transport.

    Reconstructs Message via from_dict(), StoreEvent from string,
    and ToolExecutionState from dict.

    Args:
        data: dict from JSON-parsed IPC event

    Returns:
        StoreNotification instance
    """
    from src.core.events import ToolStatus
    from src.session.models.message import Message
    from src.session.store.memory_store import (
        StoreEvent,
        StoreNotification,
        ToolExecutionState,
    )

    # Reconstruct event enum
    event = StoreEvent(data["event"])

    # Reconstruct message if present
    message = None
    if "message" in data and data["message"] is not None:
        message = Message.from_dict(data["message"])

    # Reconstruct tool state if present
    tool_state = None
    if "tool_state" in data and data["tool_state"] is not None:
        ts_data = data["tool_state"]
        # Resolve ToolStatus from name string (serialized via .name)
        status_str = ts_data.get("status", "")
        try:
            status = _resolve_tool_status(status_str)
        except (ValueError, KeyError):
            status = ToolStatus.PENDING
        tool_state = ToolExecutionState(
            status=status,
            result=ts_data.get("result"),
            error=ts_data.get("error"),
            duration_ms=ts_data.get("duration_ms"),
        )

    return StoreNotification(
        event=event,
        message=message,
        tool_call_id=data.get("tool_call_id"),
        tool_state=tool_state,
        metadata=data.get("metadata", {}),
    )


def _resolve_tool_status(status_str: str):
    """Resolve ToolStatus from its name or value string.

    ToolStatus uses auto() so values are ints, but we serialize the name.
    """
    from src.core.events import ToolStatus
    # Try by name first (e.g., "RUNNING", "SUCCESS")
    name_upper = status_str.upper()
    for member in ToolStatus:
        if member.name == name_upper:
            return member
    # Try by value (int as string)
    try:
        return ToolStatus(int(status_str))
    except (ValueError, KeyError):
        return ToolStatus.PENDING


def serialize_result(result: "SubAgentResult") -> dict[str, Any]:
    """Serialize SubAgentResult for IPC transport.

    Args:
        result: SubAgentResult from subagent execution

    Returns:
        JSON-serializable dict
    """
    return asdict(result)


def deserialize_result(data: dict[str, Any]) -> "SubAgentResult":
    """Deserialize SubAgentResult from IPC transport.

    Args:
        data: dict from JSON-parsed IPC event

    Returns:
        SubAgentResult instance
    """
    from src.subagents.subagent import SubAgentResult
    return SubAgentResult(
        success=data.get("success", False),
        subagent_name=data.get("subagent_name", ""),
        output=data.get("output", ""),
        metadata=data.get("metadata", {}),
        error=data.get("error"),
        tool_calls=data.get("tool_calls", []),
        execution_time=data.get("execution_time", 0.0),
    )


# ============================================================================
# Tool Approval IPC (bidirectional)
# ============================================================================

@dataclass
class ApprovalRequest:
    """Request from child to parent for user interaction (emitted on stdout).

    Used for both tool approval and clarify requests via request_type:
    - "tool_approval": risky tool needs permission before executing
    - "clarify": subagent needs structured answers from user
    """
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]
    subagent_name: str
    args_summary: str
    request_type: str = "tool_approval"
    # Clarify-specific fields (only when request_type="clarify")
    questions: list[dict[str, Any]] | None = None
    context: str | None = None
    # Pause-specific fields (only when request_type="pause")
    pause_reason: str | None = None
    pause_reason_code: str | None = None
    pause_stats: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ApprovalRequest':
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ApprovalResponse:
    """Response from parent to child for user interaction (sent on stdin).

    Used for both tool approval and clarify responses:
    - Tool approval: uses approved/feedback fields
    - Clarify: uses clarify_result dict
    """
    tool_call_id: str
    approved: bool
    auto_approve_future: bool = False
    feedback: str | None = None
    # Clarify-specific: structured response from ClarifyWidget
    clarify_result: dict[str, Any] | None = None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True)

    @classmethod
    def from_json_line(cls, line: str) -> 'ApprovalResponse':
        data = json.loads(line.strip())
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


def read_approval_response_from_stdin() -> ApprovalResponse:
    """Block until the parent writes an ApprovalResponse on stdin.

    Called by the subprocess approval callback. The subprocess is
    single-threaded and synchronous, so blocking here is fine -- the
    parent's async event loop stays alive handling the TUI.

    Raises:
        EOFError: Parent closed stdin (crash/cancel) -- treat as rejection.
    """
    line = sys.stdin.readline()
    if not line:
        raise EOFError("Parent closed stdin - treating as rejection")
    return ApprovalResponse.from_json_line(line)


# ============================================================================
# Event Emission (child process)
# ============================================================================

def emit_event(event_type: IPCEventType, **fields) -> None:
    """Emit a JSON-line event to stdout (used by subprocess runner).

    Writes a single JSON line to stdout and flushes immediately.
    Stdout is exclusively for IPC events in the subprocess.

    Args:
        event_type: The event type to emit
        **fields: Additional fields to include in the event
    """
    event = {"type": event_type.value, **fields}
    line = json.dumps(event, default=str, ensure_ascii=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def read_input_from_stdin() -> SubprocessInput:
    """Read SubprocessInput from stdin (used by subprocess runner).

    Reads a single JSON line from stdin.

    Returns:
        SubprocessInput instance

    Raises:
        ValueError: If stdin is empty or contains invalid JSON
    """
    line = sys.stdin.readline()
    if not line:
        raise ValueError("No input received on stdin")
    return SubprocessInput.from_json(line.strip())
