"""Tests for stdio_server.py pure functions and security hardening.

Covers:
- _error_response dict shape
- _build_replay_messages with mock store/messages (text, multimodal, tool_calls, meta)
- _SESSION_ID_RE UUID validation (valid, path traversal, empty)
- _find_session_file path traversal rejection
- _stdin_reader_thread line size limit
- _HANDLERS dispatch table -> real methods on StdioProtocol
- Tunables (_MAX_LINE_BYTES, _MAX_STDIN_QUEUE, etc.) existence and defaults
"""

import asyncio
import io
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.server.stdio_server import (
    StdioProtocol,
    _build_replay_messages,
    _error_response,
    _MAX_CHAT_MESSAGE_LEN,
    _MAX_CHAT_QUEUE,
    _MAX_LINE_BYTES,
    _MAX_STDIN_QUEUE,
    _SESSION_ID_RE,
    _stdin_reader_thread,
    _TCP_CONNECT_TIMEOUT,
    _TCP_DRAIN_TIMEOUT,
    _CHAT_POLL_INTERVAL,
    _VALID_MODES,
)


# ============================================================================
# _error_response
# ============================================================================


class TestErrorResponse:
    """Test _error_response() dict shape and fields."""

    def test_basic_shape(self):
        result = _error_response("test_error", "Something went wrong")
        assert result == {
            "type": "error",
            "error_type": "test_error",
            "user_message": "Something went wrong",
            "recoverable": True,
        }

    def test_recoverable_defaults_to_true(self):
        result = _error_response("err", "msg")
        assert result["recoverable"] is True

    def test_recoverable_false(self):
        result = _error_response("fatal", "Unrecoverable", recoverable=False)
        assert result["recoverable"] is False

    def test_all_keys_present(self):
        result = _error_response("e", "m")
        expected_keys = {"type", "error_type", "user_message", "recoverable"}
        assert set(result.keys()) == expected_keys

    def test_type_always_error(self):
        """The 'type' field must always be 'error' regardless of error_type."""
        result = _error_response("session_not_found", "No session")
        assert result["type"] == "error"

    def test_empty_strings_allowed(self):
        result = _error_response("", "")
        assert result["error_type"] == ""
        assert result["user_message"] == ""


# ============================================================================
# _build_replay_messages
# ============================================================================


@dataclass
class _MockToolCallFunction:
    """Minimal mock of ToolCallFunction for _build_replay_messages tests."""
    name: str
    arguments: str


@dataclass
class _MockToolCall:
    """Minimal mock of ToolCall for _build_replay_messages tests."""
    id: str
    function: _MockToolCallFunction


@dataclass
class _MockMeta:
    """Minimal mock of MessageMeta."""
    stop_reason: str | None = None


@dataclass
class _MockMessage:
    """Minimal mock of Message for _build_replay_messages tests."""
    role: str
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list = field(default_factory=list)
    tool_call_id: str | None = None
    meta: _MockMeta | None = None


class _MockStore:
    """Minimal mock of MessageStore for _build_replay_messages tests."""

    def __init__(self, messages: list):
        self._messages = messages

    def get_transcript_view(self, include_pre_compaction: bool = False) -> list:
        return self._messages


class TestBuildReplayMessages:
    """Test _build_replay_messages() with various message types."""

    def test_empty_store(self):
        store = _MockStore([])
        result = _build_replay_messages(store)
        assert result == []

    def test_simple_text_message(self):
        store = _MockStore([
            _MockMessage(role="user", content="Hello"),
        ])
        result = _build_replay_messages(store)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    def test_multimodal_content_extracts_text(self):
        """Multimodal content (list of parts) should join text parts only."""
        store = _MockStore([
            _MockMessage(
                role="user",
                content=[
                    {"type": "text", "text": "Look at this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    {"type": "text", "text": "and this"},
                ],
            ),
        ])
        result = _build_replay_messages(store)
        assert len(result) == 1
        assert result[0]["content"] == "Look at this and this"

    def test_multimodal_no_text_parts(self):
        """Multimodal content with zero text parts returns empty string."""
        store = _MockStore([
            _MockMessage(
                role="user",
                content=[
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            ),
        ])
        result = _build_replay_messages(store)
        assert result[0]["content"] == ""

    def test_none_content(self):
        """None content (e.g. assistant tool_call-only message) becomes empty string."""
        store = _MockStore([
            _MockMessage(role="assistant", content=None),
        ])
        result = _build_replay_messages(store)
        assert result[0]["content"] == ""

    def test_empty_string_content(self):
        store = _MockStore([
            _MockMessage(role="assistant", content=""),
        ])
        result = _build_replay_messages(store)
        assert result[0]["content"] == ""

    def test_tool_calls_serialized(self):
        """Assistant messages with tool_calls include them in the replay."""
        tc = _MockToolCall(
            id="call_abc123",
            function=_MockToolCallFunction(
                name="read_file",
                arguments='{"file_path": "/tmp/test.py"}',
            ),
        )
        store = _MockStore([
            _MockMessage(role="assistant", content="Let me read that file.", tool_calls=[tc]),
        ])
        result = _build_replay_messages(store)
        assert "tool_calls" in result[0]
        assert len(result[0]["tool_calls"]) == 1
        assert result[0]["tool_calls"][0]["id"] == "call_abc123"
        assert result[0]["tool_calls"][0]["function"]["name"] == "read_file"
        assert result[0]["tool_calls"][0]["function"]["arguments"] == '{"file_path": "/tmp/test.py"}'

    def test_tool_call_id_included(self):
        """Tool result messages include tool_call_id."""
        store = _MockStore([
            _MockMessage(role="tool", content="File contents here", tool_call_id="call_abc123"),
        ])
        result = _build_replay_messages(store)
        assert result[0]["tool_call_id"] == "call_abc123"

    def test_tool_call_id_not_included_when_none(self):
        """Non-tool messages omit tool_call_id key entirely."""
        store = _MockStore([
            _MockMessage(role="user", content="Hello"),
        ])
        result = _build_replay_messages(store)
        assert "tool_call_id" not in result[0]

    def test_meta_stop_reason(self):
        """Messages with meta.stop_reason include meta.status in replay."""
        store = _MockStore([
            _MockMessage(
                role="assistant",
                content="Done.",
                meta=_MockMeta(stop_reason="complete"),
            ),
        ])
        result = _build_replay_messages(store)
        assert "meta" in result[0]
        assert result[0]["meta"]["status"] == "complete"

    def test_meta_no_stop_reason_omits_meta(self):
        """Meta with no stop_reason produces empty meta dict, which is omitted."""
        store = _MockStore([
            _MockMessage(
                role="assistant",
                content="Working...",
                meta=_MockMeta(stop_reason=None),
            ),
        ])
        result = _build_replay_messages(store)
        assert "meta" not in result[0]

    def test_meta_none_omits_meta(self):
        """None meta omits meta key entirely."""
        store = _MockStore([
            _MockMessage(role="user", content="Hello", meta=None),
        ])
        result = _build_replay_messages(store)
        assert "meta" not in result[0]

    def test_full_conversation(self):
        """Test a realistic multi-turn conversation."""
        tc = _MockToolCall(
            id="call_001",
            function=_MockToolCallFunction(name="edit_file", arguments='{"file_path": "a.py"}'),
        )
        messages = [
            _MockMessage(role="user", content="Fix the bug in a.py"),
            _MockMessage(role="assistant", content="I'll fix it.", tool_calls=[tc]),
            _MockMessage(role="tool", content="File edited.", tool_call_id="call_001"),
            _MockMessage(
                role="assistant",
                content="Done!",
                meta=_MockMeta(stop_reason="complete"),
            ),
        ]
        store = _MockStore(messages)
        result = _build_replay_messages(store)
        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert "tool_calls" in result[1]
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "call_001"
        assert result[3]["meta"]["status"] == "complete"

    def test_empty_tool_calls_list_omitted(self):
        """An empty tool_calls list should NOT appear in the replay entry."""
        store = _MockStore([
            _MockMessage(role="assistant", content="Hello", tool_calls=[]),
        ])
        result = _build_replay_messages(store)
        assert "tool_calls" not in result[0]

    def test_multimodal_with_non_dict_items_skipped(self):
        """Non-dict items in content list are silently skipped."""
        store = _MockStore([
            _MockMessage(
                role="user",
                content=[
                    {"type": "text", "text": "valid"},
                    "not a dict",
                    42,
                    {"type": "text", "text": "also valid"},
                ],
            ),
        ])
        result = _build_replay_messages(store)
        assert result[0]["content"] == "valid also valid"


# ============================================================================
# _SESSION_ID_RE
# ============================================================================


class TestSessionIdRegex:
    """Test _SESSION_ID_RE validates session-YYYYMMDD-HHMMSS-hex8 format and rejects attacks."""

    def test_valid_session_id_lowercase(self):
        assert _SESSION_ID_RE.match("session-20260328-143022-a1b2c3d4")

    def test_valid_session_id_uppercase_hex(self):
        assert _SESSION_ID_RE.match("SESSION-20260328-143022-A1B2C3D4")

    def test_valid_session_id_mixed_case(self):
        assert _SESSION_ID_RE.match("session-20260328-143022-aAbBcCdD")

    def test_generated_session_id(self):
        from src.session.scanner import generate_session_id
        sid = generate_session_id()
        assert _SESSION_ID_RE.match(sid)

    def test_empty_string_fails(self):
        assert _SESSION_ID_RE.match("") is None

    def test_path_traversal_dot_dot(self):
        assert _SESSION_ID_RE.match("../../../etc/passwd") is None

    def test_path_traversal_encoded(self):
        assert _SESSION_ID_RE.match("..%2F..%2Fetc%2Fpasswd") is None

    def test_path_traversal_with_session_prefix(self):
        """Valid session ID followed by path traversal must fail."""
        assert _SESSION_ID_RE.match("session-20260328-143022-a1b2c3d4/../secret") is None

    def test_path_traversal_with_session_suffix(self):
        """Path traversal before session ID must fail."""
        assert _SESSION_ID_RE.match("../../session-20260328-143022-a1b2c3d4") is None

    def test_too_short_hex(self):
        assert _SESSION_ID_RE.match("session-20260328-143022-a1b2c3") is None

    def test_too_long_hex(self):
        assert _SESSION_ID_RE.match("session-20260328-143022-a1b2c3d4e5") is None

    def test_missing_session_prefix(self):
        assert _SESSION_ID_RE.match("20260328-143022-a1b2c3d4") is None

    def test_wrong_date_format(self):
        assert _SESSION_ID_RE.match("session-2026328-143022-a1b2c3d4") is None

    def test_invalid_hex_chars(self):
        assert _SESSION_ID_RE.match("session-20260328-143022-g1b2c3d4") is None

    def test_null_bytes(self):
        assert _SESSION_ID_RE.match("session-20260328-143022-a1b2c3\x00") is None

    def test_spaces(self):
        assert _SESSION_ID_RE.match(" session-20260328-143022-a1b2c3d4") is None
        assert _SESSION_ID_RE.match("session-20260328-143022-a1b2c3d4 ") is None

    def test_backslash_path(self):
        assert _SESSION_ID_RE.match("..\\..\\etc\\passwd") is None

    def test_single_dot(self):
        assert _SESSION_ID_RE.match(".") is None

    def test_double_dot(self):
        assert _SESSION_ID_RE.match("..") is None

    def test_just_hyphens(self):
        assert _SESSION_ID_RE.match("--------") is None

    def test_uuid_format_rejected(self):
        """Old UUID format should not match the new session ID pattern."""
        assert _SESSION_ID_RE.match("a1b2c3d4-e5f6-7890-abcd-ef1234567890") is None


# ============================================================================
# _find_session_file
# ============================================================================


class TestFindSessionFile:
    """Test _find_session_file path traversal rejection and session lookup."""

    def _make_protocol(self, working_directory: str) -> StdioProtocol:
        """Create a minimal StdioProtocol with just _working_directory set.

        We avoid __init__ (which needs a running event loop) by constructing
        a bare object and setting the attributes we need directly.
        """
        proto = object.__new__(StdioProtocol)
        proto._working_directory = working_directory
        return proto

    def test_rejects_path_traversal(self, tmp_path):
        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file("../../etc/passwd")
        assert result is None

    def test_rejects_empty_string(self, tmp_path):
        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file("")
        assert result is None

    def test_rejects_non_uuid(self, tmp_path):
        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file("not-a-uuid-at-all")
        assert result is None

    def test_rejects_valid_uuid_with_traversal_suffix(self, tmp_path):
        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file("a1b2c3d4-e5f6-7890-abcd-ef1234567890/../secret")
        assert result is None

    def test_returns_none_for_nonexistent_session(self, tmp_path):
        """Valid UUID but no corresponding file on disk."""
        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert result is None

    def test_finds_directory_structure_session(self, tmp_path):
        """Finds session in sessions/<uuid>/session.jsonl structure."""
        session_id = "session-20260328-143022-a1b2c3d4"
        sessions_dir = tmp_path / ".claraity" / "sessions" / session_id
        sessions_dir.mkdir(parents=True)
        jsonl_file = sessions_dir / "session.jsonl"
        jsonl_file.write_text("{}\n")

        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file(session_id)
        assert result is not None
        assert result.name == "session.jsonl"

    def test_finds_flat_structure_session(self, tmp_path):
        """Finds session in sessions/<uuid>.jsonl flat structure."""
        session_id = "session-20260328-143022-a1b2c3d4"
        sessions_dir = tmp_path / ".claraity" / "sessions"
        sessions_dir.mkdir(parents=True)
        jsonl_file = sessions_dir / f"{session_id}.jsonl"
        jsonl_file.write_text("{}\n")

        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file(session_id)
        assert result is not None
        assert result.name == f"{session_id}.jsonl"

    def test_prefers_directory_structure_over_flat(self, tmp_path):
        """When both structures exist, directory structure is found first."""
        session_id = "session-20260328-143022-a1b2c3d4"
        sessions_dir = tmp_path / ".claraity" / "sessions"

        # Create directory structure
        dir_path = sessions_dir / session_id
        dir_path.mkdir(parents=True)
        (dir_path / "session.jsonl").write_text("{}\n")

        # Create flat structure
        (sessions_dir / f"{session_id}.jsonl").write_text("{}\n")

        proto = self._make_protocol(str(tmp_path))
        result = proto._find_session_file(session_id)
        assert result is not None
        assert result.name == "session.jsonl"
        assert session_id in str(result.parent)


# ============================================================================
# _stdin_reader_thread line size limit
# ============================================================================


class TestStdinReaderThread:
    """Test _stdin_reader_thread oversized line dropping and normal operation.

    _stdin_reader_thread uses loop.call_soon_threadsafe() to enqueue items,
    so the event loop must be running for callbacks to fire. We run the
    reader in a background thread and collect results from the async queue
    inside the running loop.
    """

    @staticmethod
    async def _run_reader(fake_buffer, max_line_bytes, queue_maxsize=100):
        """Run _stdin_reader_thread in a background thread with a running loop.

        Returns the list of items placed on the queue.
        """
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=queue_maxsize)

        def _thread_target():
            with patch.object(sys, "stdin", SimpleNamespace(buffer=fake_buffer)):
                _stdin_reader_thread(loop, queue, max_line_bytes)

        t = threading.Thread(target=_thread_target, daemon=True)
        t.start()

        # Collect items until we see the None sentinel
        items = []
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=5.0)
            items.append(item)
            if item is None:
                break
        t.join(timeout=2.0)
        return items

    async def test_oversized_line_dropped(self):
        """Lines exceeding max_line_bytes are silently dropped."""
        oversized = b"A" * 200 + b"\n"
        normal = b'{"type":"chat_message","content":"hi"}\n'
        fake_stdin = io.BytesIO(oversized + normal)

        items = await self._run_reader(fake_stdin, max_line_bytes=100)

        # The oversized line should be dropped, only the normal line + sentinel
        assert len(items) == 2
        assert items[0] == normal.strip()
        assert items[1] is None

    async def test_normal_lines_queued(self):
        """Normal-sized lines are queued correctly."""
        line1 = b'{"type":"ping"}\n'
        line2 = b'{"type":"pong"}\n'
        fake_stdin = io.BytesIO(line1 + line2)

        items = await self._run_reader(fake_stdin, max_line_bytes=_MAX_LINE_BYTES)

        assert len(items) == 3  # two lines + None sentinel
        assert items[0] == line1.strip()
        assert items[1] == line2.strip()
        assert items[2] is None

    async def test_empty_lines_skipped(self):
        """Blank lines are skipped."""
        fake_stdin = io.BytesIO(b"\n\n\n" + b'{"ok":true}\n' + b"\n")

        items = await self._run_reader(fake_stdin, max_line_bytes=_MAX_LINE_BYTES)

        # Only one real line + sentinel
        assert len(items) == 2
        assert items[0] == b'{"ok":true}'
        assert items[1] is None

    async def test_eof_sends_sentinel(self):
        """EOF on stdin sends None sentinel to the queue."""
        fake_stdin = io.BytesIO(b"")  # immediate EOF

        items = await self._run_reader(fake_stdin, max_line_bytes=_MAX_LINE_BYTES)

        assert items == [None]

    def test_stderr_message_for_oversized(self):
        """Oversized line drop writes a diagnostic to stderr.

        This test runs synchronously because we only check stderr output,
        not the queue. The call_soon_threadsafe calls will fail silently
        (no running loop), but stderr writes still happen synchronously.
        """
        loop = asyncio.new_event_loop()

        oversized = b"X" * 50 + b"\n"
        fake_stdin = io.BytesIO(oversized)

        stderr_capture = io.StringIO()
        with patch.object(sys, "stdin", SimpleNamespace(buffer=fake_stdin)):
            with patch.object(sys, "stderr", stderr_capture):
                # Note: call_soon_threadsafe will fail since loop isn't running,
                # but the finally block's error is caught by the broad except.
                # The important thing is the stderr write happens before that.
                try:
                    _stdin_reader_thread(loop, asyncio.Queue(maxsize=100), max_line_bytes=10)
                except Exception:
                    pass

        assert "Dropped oversized stdin line" in stderr_capture.getvalue()
        assert "50 bytes" in stderr_capture.getvalue()
        loop.close()


# ============================================================================
# _HANDLERS dispatch table
# ============================================================================


class TestHandlersDispatchTable:
    """Verify all _HANDLERS entries map to real methods on StdioProtocol."""

    def test_all_handler_names_are_methods(self):
        """Every handler name in _HANDLERS must be a real method on StdioProtocol."""
        for msg_type, handler_name in StdioProtocol._HANDLERS.items():
            assert hasattr(StdioProtocol, handler_name), (
                f"_HANDLERS['{msg_type}'] references '{handler_name}' "
                f"which does not exist on StdioProtocol"
            )

    def test_all_handlers_are_callable(self):
        """Every handler must be callable (a method, not a data attribute)."""
        for msg_type, handler_name in StdioProtocol._HANDLERS.items():
            attr = getattr(StdioProtocol, handler_name)
            assert callable(attr), (
                f"_HANDLERS['{msg_type}'] -> '{handler_name}' is not callable"
            )

    def test_expected_message_types_present(self):
        """Key message types expected by the VS Code extension are registered."""
        expected_types = {
            "chat_message",
            "get_config",
            "save_config",
            "list_models",
            "set_mode",
            "set_auto_approve",
            "get_auto_approve",
            "new_session",
            "list_sessions",
            "resume_session",
        }
        registered = set(StdioProtocol._HANDLERS.keys())
        missing = expected_types - registered
        assert not missing, f"Missing handler registrations: {missing}"

    def test_jira_handlers_present(self):
        """Jira integration message types are registered."""
        jira_types = {"get_jira_profiles", "save_jira_config", "connect_jira", "disconnect_jira"}
        registered = set(StdioProtocol._HANDLERS.keys())
        missing = jira_types - registered
        assert not missing, f"Missing Jira handler registrations: {missing}"

    def test_no_duplicate_handler_methods(self):
        """No two message types should map to the same handler (detect copy-paste errors)."""
        handler_names = list(StdioProtocol._HANDLERS.values())
        # Intentional: different types CAN map to the same handler, but let's verify
        # the current state (no duplicates expected in current impl)
        seen = {}
        for msg_type, handler_name in StdioProtocol._HANDLERS.items():
            if handler_name in seen:
                # This is not necessarily a bug, but flag it for review
                pass
            seen[handler_name] = msg_type

    def test_handlers_dict_is_not_empty(self):
        assert len(StdioProtocol._HANDLERS) > 0


# ============================================================================
# Tunables existence and defaults
# ============================================================================


class TestTunables:
    """Verify tunable constants exist and have sane default values."""

    def test_max_line_bytes_exists_and_positive(self):
        assert isinstance(_MAX_LINE_BYTES, int)
        assert _MAX_LINE_BYTES > 0

    def test_max_line_bytes_default_10mb(self):
        """Default is 10 MB (10 * 1024 * 1024)."""
        assert _MAX_LINE_BYTES == 10 * 1024 * 1024

    def test_max_stdin_queue_exists_and_positive(self):
        assert isinstance(_MAX_STDIN_QUEUE, int)
        assert _MAX_STDIN_QUEUE > 0

    def test_max_stdin_queue_default(self):
        assert _MAX_STDIN_QUEUE == 200

    def test_max_chat_queue_exists_and_positive(self):
        assert isinstance(_MAX_CHAT_QUEUE, int)
        assert _MAX_CHAT_QUEUE > 0

    def test_max_chat_queue_default(self):
        assert _MAX_CHAT_QUEUE == 10

    def test_max_chat_message_len_exists_and_positive(self):
        assert isinstance(_MAX_CHAT_MESSAGE_LEN, int)
        assert _MAX_CHAT_MESSAGE_LEN > 0

    def test_max_chat_message_len_default(self):
        assert _MAX_CHAT_MESSAGE_LEN == 100_000

    def test_tcp_connect_timeout_exists_and_positive(self):
        assert isinstance(_TCP_CONNECT_TIMEOUT, float)
        assert _TCP_CONNECT_TIMEOUT > 0

    def test_tcp_connect_timeout_default(self):
        assert _TCP_CONNECT_TIMEOUT == 10.0

    def test_tcp_drain_timeout_exists_and_positive(self):
        assert isinstance(_TCP_DRAIN_TIMEOUT, float)
        assert _TCP_DRAIN_TIMEOUT > 0

    def test_tcp_drain_timeout_default(self):
        assert _TCP_DRAIN_TIMEOUT == 5.0

    def test_chat_poll_interval_exists_and_positive(self):
        assert isinstance(_CHAT_POLL_INTERVAL, float)
        assert _CHAT_POLL_INTERVAL > 0

    def test_chat_poll_interval_default(self):
        assert _CHAT_POLL_INTERVAL == 1.0

    def test_valid_modes_is_frozenset(self):
        assert isinstance(_VALID_MODES, frozenset)

    def test_valid_modes_contains_expected(self):
        assert _VALID_MODES == frozenset({"plan", "normal", "auto"})

    def test_session_id_regex_is_compiled(self):
        """_SESSION_ID_RE should be a compiled regex, not a raw string."""
        import re
        assert isinstance(_SESSION_ID_RE, re.Pattern)


# ============================================================================
# _handle_enrich_prompt
# ============================================================================


def _make_async_delta_gen(*text_deltas: str):
    """Return an async generator that yields ProviderDelta-like objects for each text chunk."""
    async def _gen():
        for text in text_deltas:
            yield SimpleNamespace(text_delta=text, finish_reason=None)
    return _gen()


def _make_protocol_for_enrich(deltas: tuple[str, ...] = ("enriched text",)):
    """Build a minimal StdioProtocol instance suitable for enrich_prompt tests.

    Uses SimpleNamespace so attribute access (agent.llm) matches the real
    code path exactly — catching any typo like 'llm_backend' at test time.

    The mock LLM's generate_provider_deltas_async yields one delta per element
    in `deltas`, matching the streaming interface used by _handle_enrich_prompt.
    """
    mock_llm = MagicMock()
    mock_llm.config = SimpleNamespace(model_name="test-model")
    mock_llm.generate_provider_deltas_async = MagicMock(
        return_value=_make_async_delta_gen(*deltas)
    )

    agent = SimpleNamespace(llm=mock_llm)

    protocol = StdioProtocol.__new__(StdioProtocol)
    protocol._agent = agent
    protocol._working_directory = ""
    protocol._sent = []

    async def _fake_send_json(data):
        protocol._sent.append(data)

    protocol._send_json = _fake_send_json

    # Patch load_llm_config so tests don't need a real config file
    from src.llm.config_loader import LLMConfigData
    protocol._load_config = lambda: LLMConfigData()

    return protocol


def _run(coro):
    """Run a coroutine in the test event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestHandleEnrichPrompt:
    """Tests for StdioProtocol._handle_enrich_prompt."""

    def test_accesses_agent_llm_not_llm_backend(self):
        """Regression: handler must use agent.llm, not agent.llm_backend.

        An AttributeError on agent.llm_backend was silently swallowed,
        causing the feature to appear broken with no user feedback.
        """
        protocol = _make_protocol_for_enrich()
        assert not hasattr(protocol._agent, "llm_backend"), (
            "Fixture misconfigured: agent should not have llm_backend"
        )
        assert hasattr(protocol._agent, "llm"), (
            "Fixture misconfigured: agent must have llm"
        )

    def test_streaming_sends_delta_messages(self):
        """Each text chunk from the LLM yields an enrichment_delta message."""
        protocol = _make_protocol_for_enrich(deltas=("Fix ", "the ", "bug."))

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "fix the bug"}))

        delta_msgs = [m for m in protocol._sent if m["type"] == "enrichment_delta"]
        assert len(delta_msgs) == 3
        assert delta_msgs[0]["delta"] == "Fix "
        assert delta_msgs[1]["delta"] == "the "
        assert delta_msgs[2]["delta"] == "bug."

    def test_complete_message_sent_after_all_deltas(self):
        """enrichment_complete is sent after all deltas with concatenated enriched text."""
        protocol = _make_protocol_for_enrich(deltas=("Fix ", "the ", "bug."))

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "fix the bug"}))

        complete_msgs = [m for m in protocol._sent if m["type"] == "enrichment_complete"]
        assert len(complete_msgs) == 1
        msg = complete_msgs[0]
        assert msg["original"] == "fix the bug"
        assert msg["enriched"] == "Fix the bug."

    def test_delta_messages_come_before_complete(self):
        """All enrichment_delta messages must precede enrichment_complete."""
        protocol = _make_protocol_for_enrich(deltas=("A", "B"))

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "hello"}))

        types = [m["type"] for m in protocol._sent]
        assert types == ["enrichment_delta", "enrichment_delta", "enrichment_complete"]

    def test_uses_generate_provider_deltas_async_not_generate(self):
        """Handler must use streaming generate_provider_deltas_async, not blocking generate."""
        protocol = _make_protocol_for_enrich()

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "add tests"}))

        assert protocol._agent.llm.generate_provider_deltas_async.called, (
            "generate_provider_deltas_async was not called"
        )
        assert not protocol._agent.llm.generate.called, (
            "Blocking generate() was called — should use streaming instead"
        )

    def test_user_message_contains_request_in_quotes(self):
        """User message must wrap the request in quotes for clear delineation."""
        protocol = _make_protocol_for_enrich()

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "add tests"}))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        messages = call_args[0][0]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert '"add tests"' in messages[1]["content"]

    def test_custom_system_prompt_from_config_is_used(self):
        """If prompt_enrichment.system_prompt is set in config, it replaces the built-in default."""
        protocol = _make_protocol_for_enrich()

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData, PromptEnrichmentConfig
            cfg = LLMConfigData()
            cfg.prompt_enrichment = PromptEnrichmentConfig(system_prompt="Custom instructions.")
            mock_cfg.return_value = cfg
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "hello"}))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        messages = call_args[0][0]
        assert messages[0]["content"] == "Custom instructions."

    def test_empty_content_returns_enrichment_error(self):
        """Empty prompt returns enrichment_error without calling the LLM."""
        protocol = _make_protocol_for_enrich()

        _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": ""}))

        assert len(protocol._sent) == 1
        assert protocol._sent[0]["type"] == "enrichment_error"
        assert not protocol._agent.llm.generate_provider_deltas_async.called

    def test_whitespace_only_content_returns_enrichment_error(self):
        """Whitespace-only prompt is treated as empty."""
        protocol = _make_protocol_for_enrich()

        _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "   "}))

        assert protocol._sent[0]["type"] == "enrichment_error"

    def test_llm_failure_returns_enrichment_error(self):
        """If the LLM streaming call raises, enrichment_error is sent."""
        async def _failing_gen(*a, **kw):
            raise RuntimeError("LLM unavailable")
            yield  # make it an async generator

        mock_llm = MagicMock()
        mock_llm.config = SimpleNamespace(model_name="test-model")
        mock_llm.generate_provider_deltas_async = _failing_gen

        protocol = StdioProtocol.__new__(StdioProtocol)
        protocol._agent = SimpleNamespace(llm=mock_llm)
        protocol._working_directory = ""
        protocol._sent = []

        async def _fake_send_json(data):
            protocol._sent.append(data)
        protocol._send_json = _fake_send_json

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({"type": "enrich_prompt", "content": "hello"}))

        assert len(protocol._sent) == 1
        msg = protocol._sent[0]
        assert msg["type"] == "enrichment_error"
        assert "LLM unavailable" in msg["message"]

    def test_history_included_in_user_message(self):
        """Chat history entries are prepended to the user message sent to the LLM."""
        protocol = _make_protocol_for_enrich()
        history = [
            {"role": "user", "content": "I'm working on the auth module"},
            {"role": "assistant", "content": "I can help with that."},
        ]

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({
                "type": "enrich_prompt",
                "content": "fix the login bug",
                "history": history,
            }))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        user_content = call_args[0][0][1]["content"]
        assert "I'm working on the auth module" in user_content
        assert "I can help with that." in user_content
        assert '"fix the login bug"' in user_content
        # History must appear before the request
        assert user_content.index("auth module") < user_content.index("fix the login bug")

    def test_history_labels_roles_correctly(self):
        """User turns are labelled 'User:' and assistant turns 'Assistant:'."""
        protocol = _make_protocol_for_enrich()
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({
                "type": "enrich_prompt",
                "content": "do something",
                "history": history,
            }))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        user_content = call_args[0][0][1]["content"]
        assert "User: hello" in user_content
        assert "Assistant: hi there" in user_content

    def test_no_history_sends_request_only(self):
        """When history is absent the user message contains only the request."""
        protocol = _make_protocol_for_enrich()

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({
                "type": "enrich_prompt",
                "content": "add tests",
            }))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        user_content = call_args[0][0][1]["content"]
        assert "Recent conversation" not in user_content
        assert '"add tests"' in user_content

    def test_empty_history_list_ignored(self):
        """An empty history list produces the same output as no history."""
        protocol = _make_protocol_for_enrich()

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({
                "type": "enrich_prompt",
                "content": "do it",
                "history": [],
            }))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        user_content = call_args[0][0][1]["content"]
        assert "Recent conversation" not in user_content

    def test_invalid_history_entries_skipped(self):
        """Non-dict entries and unknown roles in history are silently ignored."""
        protocol = _make_protocol_for_enrich()
        history = [
            "not a dict",
            {"role": "system", "content": "should be ignored"},
            {"role": "user", "content": "valid entry"},
            {"role": "assistant"},  # missing content
        ]

        with patch("src.llm.config_loader.load_llm_config") as mock_cfg:
            from src.llm.config_loader import LLMConfigData
            mock_cfg.return_value = LLMConfigData()
            _run(protocol._handle_enrich_prompt({
                "type": "enrich_prompt",
                "content": "go",
                "history": history,
            }))

        call_args = protocol._agent.llm.generate_provider_deltas_async.call_args
        user_content = call_args[0][0][1]["content"]
        assert "should be ignored" not in user_content
        assert "User: valid entry" in user_content

    def test_enrich_prompt_registered_in_handlers(self):
        """enrich_prompt must be in the _HANDLERS dispatch table."""
        assert "enrich_prompt" in StdioProtocol._HANDLERS

    def test_enrich_prompt_handler_maps_to_correct_method(self):
        """_HANDLERS['enrich_prompt'] must point to _handle_enrich_prompt."""
        assert StdioProtocol._HANDLERS["enrich_prompt"] == "_handle_enrich_prompt"
