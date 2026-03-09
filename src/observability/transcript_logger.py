"""
JSONL Transcript Logger for Conversation History

Provides append-only logging of conversation events for:
- Ground truth recovery after compaction
- Replay/debug capabilities
- Audit trail

Event Schema (v1):
{
    "v": 1,                          # Schema version
    "session_id": "uuid",            # Session identifier
    "seq": 42,                       # Monotonic sequence number
    "ts": "2026-01-16T16:12:34.123Z", # ISO timestamp
    "event": "tool_result",          # Event type
    "turn_id": "t-0007",             # Optional turn identifier
    "level": "info",                 # Log level
    "data": { ... }                  # Event-specific payload
}
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Optional

# Patterns for secret detection
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?[\w-]{20,}'),
    re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?[^\s"\']+'),
    re.compile(r'(?i)(secret|token)\s*[:=]\s*["\']?[\w-]{20,}'),
    re.compile(r'(?i)(bearer)\s+[\w-]{20,}'),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),  # OpenAI API keys
    re.compile(r'(?i)(aws[_-]?secret|aws[_-]?access)\s*[:=]\s*["\']?[\w/+=]{20,}'),
]

# Keys that should always be redacted
SENSITIVE_KEYS = {
    'password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apikey',
    'api-key', 'auth', 'authorization', 'credential', 'credentials',
    'private_key', 'privatekey', 'access_token', 'refresh_token',
}


@dataclass
class TranscriptEvent:
    """
    Single event in the conversation transcript.

    Attributes:
        v: Schema version (always 1 for now)
        session_id: UUID of the session
        seq: Monotonic sequence number within session
        ts: ISO timestamp
        event: Event type (user_message, assistant_message, tool_result, etc.)
        turn_id: Optional turn identifier for grouping
        level: Log level (info, warn, error)
        data: Event-specific payload
    """
    v: int
    session_id: str
    seq: int
    ts: str
    event: str
    level: str = "info"
    turn_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        d = asdict(self)
        # Remove None values for cleaner output
        d = {k: v for k, v in d.items() if v is not None}
        return json.dumps(d, ensure_ascii=False)


class TranscriptLogger:
    """
    Append-only JSONL transcript logger for conversation history.

    Thread-safe, handles truncation and redaction automatically.

    Usage:
        logger = TranscriptLogger(session_id="abc123", base_dir=Path(".clarity"))

        # Log events
        logger.log_user_message("Hello, help me fix this bug")
        logger.log_assistant_message("I'll help you fix that", tool_calls=[...])
        logger.log_tool_result(tool_call_id="call_123", name="read_file", content="...")
        logger.log_compaction(tokens_before=90000, tokens_after=60000, ...)
    """

    # Configuration
    SCHEMA_VERSION = 1
    MAX_CONTENT_CHARS = 20000  # Truncate content longer than this
    HEAD_CHARS = 10000         # Keep first N chars when truncating
    TAIL_CHARS = 5000          # Keep last N chars when truncating

    def __init__(
        self,
        session_id: str,
        base_dir: Path,
        max_content_chars: int = 20000,
        redact_secrets: bool = True
    ):
        """
        Initialize transcript logger.

        Args:
            session_id: Unique session identifier
            base_dir: Base directory for transcript storage
            max_content_chars: Max chars before truncation (default 20000)
            redact_secrets: Whether to redact detected secrets (default True)
        """
        import re as _re

        # Validate session_id to prevent path traversal
        if not _re.match(r'^[0-9a-f\-]{1,36}$', session_id):
            raise ValueError(f"Invalid session ID format: {session_id!r}")

        self.session_id = session_id
        self.base_dir = Path(base_dir)
        self.max_content_chars = max_content_chars
        self.redact_secrets = redact_secrets

        # Create transcript directory
        self.transcript_dir = self.base_dir / "transcripts"
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

        # Transcript file path (session_id validated above)
        self.transcript_path = self.transcript_dir / f"{session_id}.jsonl"

        # Sequence counter and lock for thread safety
        self._seq = 0
        self._lock = Lock()

        # Initialize sequence from existing file if resuming
        self._init_sequence()

    def _init_sequence(self) -> None:
        """Initialize sequence number from existing transcript file."""
        if self.transcript_path.exists():
            try:
                with open(self.transcript_path, encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                event = json.loads(line)
                                self._seq = max(self._seq, event.get('seq', 0))
                            except json.JSONDecodeError:
                                continue
            except Exception:
                pass  # Start fresh if file is corrupted

    def _next_seq(self) -> int:
        """Get next sequence number (thread-safe)."""
        with self._lock:
            self._seq += 1
            return self._seq

    def _now(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'

    def _truncate(self, content: str) -> tuple[str, bool, int]:
        """
        Truncate content if too long.

        Returns:
            Tuple of (truncated_content, was_truncated, original_length)
        """
        original_len = len(content)

        if original_len <= self.max_content_chars:
            return content, False, original_len

        # Keep head and tail
        head = content[:self.HEAD_CHARS]
        tail = content[-self.TAIL_CHARS:]
        truncated_chars = original_len - self.HEAD_CHARS - self.TAIL_CHARS

        truncated = (
            f"{head}\n\n"
            f"[... {truncated_chars:,} characters truncated ...]\n\n"
            f"{tail}"
        )

        return truncated, True, original_len

    def _redact(self, content: str) -> str:
        """Redact detected secrets from content."""
        if not self.redact_secrets:
            return content

        redacted = content
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub('[REDACTED]', redacted)

        return redacted

    def _sanitize_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Sanitize event data: truncate large content, redact secrets.

        Args:
            data: Raw event data

        Returns:
            Sanitized data dict
        """
        sanitized = {}

        for key, value in data.items():
            # Check for sensitive keys
            if key.lower() in SENSITIVE_KEYS:
                sanitized[key] = '[REDACTED]'
                continue

            # Handle string content
            if isinstance(value, str):
                # Redact secrets
                value = self._redact(value)

                # Truncate if too long
                truncated, was_truncated, original_len = self._truncate(value)
                sanitized[key] = truncated

                if was_truncated:
                    sanitized[f'{key}_truncated'] = True
                    sanitized[f'{key}_original_len'] = original_len

            # Handle nested dicts
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_data(value)

            # Handle lists
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_data(item) if isinstance(item, dict)
                    else self._redact(item) if isinstance(item, str)
                    else item
                    for item in value
                ]

            else:
                sanitized[key] = value

        return sanitized

    def log(
        self,
        event: str,
        data: dict[str, Any],
        level: str = "info",
        turn_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None
    ) -> TranscriptEvent:
        """
        Log an event to the transcript.

        Args:
            event: Event type
            data: Event payload
            level: Log level (info, warn, error)
            turn_id: Optional turn identifier
            span_id: Optional span ID for tracing
            parent_span_id: Optional parent span ID

        Returns:
            The logged TranscriptEvent
        """
        sanitized_data = self._sanitize_data(data)

        transcript_event = TranscriptEvent(
            v=self.SCHEMA_VERSION,
            session_id=self.session_id,
            seq=self._next_seq(),
            ts=self._now(),
            event=event,
            level=level,
            turn_id=turn_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            data=sanitized_data
        )

        # Append to file
        with self._lock:
            with open(self.transcript_path, 'a', encoding='utf-8') as f:
                f.write(transcript_event.to_json() + '\n')

        return transcript_event

    # ==================== Convenience Methods ====================

    def log_user_message(
        self,
        content: str,
        turn_id: str | None = None,
        token_count: int | None = None
    ) -> TranscriptEvent:
        """Log a user message."""
        data = {
            "content": content,
        }
        if token_count is not None:
            data["token_count"] = token_count

        return self.log("user_message", data, turn_id=turn_id)

    def log_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        turn_id: str | None = None,
        token_count: int | None = None
    ) -> TranscriptEvent:
        """Log an assistant message."""
        data = {
            "content": content,
        }
        if tool_calls:
            data["tool_calls"] = tool_calls
        if token_count is not None:
            data["token_count"] = token_count

        return self.log("assistant_message", data, turn_id=turn_id)

    def log_tool_call(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict[str, Any],
        turn_id: str | None = None
    ) -> TranscriptEvent:
        """Log a tool call (before execution)."""
        return self.log("tool_call", {
            "tool_call_id": tool_call_id,
            "name": name,
            "arguments": arguments
        }, turn_id=turn_id)

    def log_tool_result(
        self,
        tool_call_id: str,
        name: str,
        content: str,
        status: str = "ok",
        duration_ms: float | None = None,
        error: str | None = None,
        turn_id: str | None = None
    ) -> TranscriptEvent:
        """Log a tool result (after execution)."""
        data = {
            "tool_call_id": tool_call_id,
            "name": name,
            "status": status,
            "content": content,
        }
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        if error:
            data["error"] = error

        return self.log(
            "tool_result",
            data,
            level="error" if error else "info",
            turn_id=turn_id
        )

    def log_compaction(
        self,
        tokens_before: int,
        tokens_after: int,
        evicted_count: int,
        summary_tokens: int,
        summary_preview: str,
        component: str = "working_memory",
        reason: str = "token_budget"
    ) -> TranscriptEvent:
        """Log a compaction event."""
        return self.log("compaction", {
            "component": component,
            "reason": reason,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "evicted_message_count": evicted_count,
            "summary_tokens": summary_tokens,
            "summary_preview": summary_preview[:500]  # Always truncate preview
        })

    def log_continuation_injected(
        self,
        injected_chars: int,
        sections_included: list[str]
    ) -> TranscriptEvent:
        """Log when continuation summary is injected."""
        return self.log("continuation_injected", {
            "injected_chars": injected_chars,
            "sections_included": sections_included
        })

    def log_error(
        self,
        error_type: str,
        message: str,
        traceback: str | None = None,
        turn_id: str | None = None
    ) -> TranscriptEvent:
        """Log an error event."""
        data = {
            "error_type": error_type,
            "message": message,
        }
        if traceback:
            data["traceback"] = traceback

        return self.log("error", data, level="error", turn_id=turn_id)

    def log_file_write(
        self,
        file_path: str,
        bytes_written: int,
        turn_id: str | None = None
    ) -> TranscriptEvent:
        """Log a file write operation."""
        return self.log("file_write", {
            "file_path": file_path,
            "bytes_written": bytes_written
        }, turn_id=turn_id)

    def log_file_edit(
        self,
        file_path: str,
        edit_summary: str,
        turn_id: str | None = None
    ) -> TranscriptEvent:
        """Log a file edit operation."""
        return self.log("file_edit", {
            "file_path": file_path,
            "edit_summary": edit_summary
        }, turn_id=turn_id)

    # ==================== Query Methods ====================

    def get_events(
        self,
        event_types: list[str] | None = None,
        since_seq: int = 0,
        limit: int = 1000
    ) -> list[TranscriptEvent]:
        """
        Query events from transcript.

        Args:
            event_types: Filter by event types (None = all)
            since_seq: Only return events after this sequence number
            limit: Maximum events to return

        Returns:
            list of TranscriptEvent objects
        """
        events = []

        if not self.transcript_path.exists():
            return events

        with open(self.transcript_path, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)

                    # Apply filters
                    if data.get('seq', 0) <= since_seq:
                        continue
                    if event_types and data.get('event') not in event_types:
                        continue

                    events.append(TranscriptEvent(**data))

                    if len(events) >= limit:
                        break

                except (json.JSONDecodeError, TypeError):
                    continue

        return events

    def get_user_messages(self) -> list[str]:
        """Get all user messages from transcript."""
        events = self.get_events(event_types=["user_message"])
        return [e.data.get("content", "") for e in events]

    def get_transcript_path(self) -> Path:
        """Get path to transcript file."""
        return self.transcript_path

    def get_stats(self) -> dict[str, Any]:
        """Get transcript statistics."""
        if not self.transcript_path.exists():
            return {
                "event_count": 0,
                "file_size_bytes": 0,
                "session_id": self.session_id
            }

        event_counts: dict[str, int] = {}
        total_events = 0

        with open(self.transcript_path, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    event_type = data.get('event', 'unknown')
                    event_counts[event_type] = event_counts.get(event_type, 0) + 1
                    total_events += 1
                except json.JSONDecodeError:
                    continue

        return {
            "session_id": self.session_id,
            "event_count": total_events,
            "events_by_type": event_counts,
            "file_size_bytes": self.transcript_path.stat().st_size,
            "transcript_path": str(self.transcript_path)
        }
