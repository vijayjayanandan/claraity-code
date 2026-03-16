"""Tests for JSON-RPC 2.0 envelope utilities."""

import pytest

from src.server.jsonrpc import JSONRPC_VERSION, is_jsonrpc, unwrap, wrap_notification


# ---------------------------------------------------------------------------
# wrap_notification
# ---------------------------------------------------------------------------


class TestWrapNotification:
    def test_simple_message(self):
        result = wrap_notification({"type": "text_delta", "content": "hi"})
        assert result == {
            "jsonrpc": "2.0",
            "method": "text_delta",
            "params": {"content": "hi"},
        }

    def test_message_with_no_extra_fields(self):
        result = wrap_notification({"type": "stream_start"})
        assert result == {"jsonrpc": "2.0", "method": "stream_start"}
        assert "params" not in result

    def test_nested_data(self):
        result = wrap_notification(
            {
                "type": "store",
                "event": "tool_state_updated",
                "data": {"call_id": "abc", "status": "running"},
            }
        )
        assert result["method"] == "store"
        assert result["params"]["event"] == "tool_state_updated"
        assert result["params"]["data"]["call_id"] == "abc"

    def test_does_not_mutate_input(self):
        original = {"type": "text_delta", "content": "hi"}
        original_copy = dict(original)
        wrap_notification(original)
        assert original == original_copy

    def test_missing_type_defaults_to_unknown(self):
        result = wrap_notification({"content": "orphan"})
        assert result["method"] == "unknown"
        assert result["params"] == {"content": "orphan"}


# ---------------------------------------------------------------------------
# unwrap
# ---------------------------------------------------------------------------


class TestUnwrap:
    def test_simple_message(self):
        result = unwrap(
            {
                "jsonrpc": "2.0",
                "method": "chat_message",
                "params": {"content": "hello"},
            }
        )
        assert result == {"type": "chat_message", "content": "hello"}

    def test_no_params(self):
        result = unwrap({"jsonrpc": "2.0", "method": "interrupt"})
        assert result == {"type": "interrupt"}

    def test_nested_params(self):
        result = unwrap(
            {
                "jsonrpc": "2.0",
                "method": "store",
                "params": {
                    "event": "tool_state_updated",
                    "data": {"call_id": "xyz"},
                },
            }
        )
        assert result["type"] == "store"
        assert result["event"] == "tool_state_updated"
        assert result["data"]["call_id"] == "xyz"

    def test_missing_method_defaults_to_unknown(self):
        result = unwrap({"jsonrpc": "2.0", "params": {"x": 1}})
        assert result["type"] == "unknown"

    def test_null_params_treated_as_empty(self):
        result = unwrap({"jsonrpc": "2.0", "method": "ping", "params": None})
        assert result == {"type": "ping"}


# ---------------------------------------------------------------------------
# is_jsonrpc
# ---------------------------------------------------------------------------


class TestIsJsonRpc:
    def test_valid_envelope(self):
        assert is_jsonrpc({"jsonrpc": "2.0", "method": "x"}) is True

    def test_plain_json(self):
        assert is_jsonrpc({"type": "text_delta", "content": "hi"}) is False

    def test_wrong_version(self):
        assert is_jsonrpc({"jsonrpc": "1.0", "method": "x"}) is False

    def test_empty_dict(self):
        assert is_jsonrpc({}) is False


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize(
        "original",
        [
            {"type": "chat_message", "content": "hello"},
            {"type": "stream_start"},
            {"type": "stream_end", "tool_calls": 3, "elapsed_s": 1.5},
            {"type": "store", "event": "tool_state_updated", "data": {"call_id": "a"}},
            {"type": "error", "error_type": "api_error", "user_message": "fail", "recoverable": True},
            {"type": "approval_result", "call_id": "c1", "approved": True},
            {"type": "session_info", "session_id": "s1", "model_name": "gpt-4"},
        ],
    )
    def test_wrap_then_unwrap_is_identity(self, original):
        wrapped = wrap_notification(original)
        assert is_jsonrpc(wrapped)
        unwrapped = unwrap(wrapped)
        assert unwrapped == original
