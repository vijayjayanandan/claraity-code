"""JSON-RPC 2.0 envelope utilities for the stdio transport.

Provides thin wrap/unwrap functions that convert between the internal
message format (``{"type": "X", ...}``) and JSON-RPC 2.0 notifications
(``{"jsonrpc": "2.0", "method": "X", "params": {...}}``).

Only the transport layer (``stdio_server.py``) calls these functions.
Everything above (serializers, handlers, sidebar) continues to work
with the internal ``{"type": ...}`` dict format.
"""

JSONRPC_VERSION = "2.0"


def wrap_notification(data: dict) -> dict:
    """Wrap an internal message dict as a JSON-RPC 2.0 notification.

    Converts ``{"type": "text_delta", "content": "hi"}``
    to ``{"jsonrpc": "2.0", "method": "text_delta", "params": {"content": "hi"}}``.
    """
    data = dict(data)  # shallow copy to avoid mutating caller's dict
    method = data.pop("type", "unknown")
    msg: dict = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if data:
        msg["params"] = data
    return msg


def unwrap(raw: dict) -> dict:
    """Unwrap a JSON-RPC 2.0 message to the internal format.

    Converts ``{"jsonrpc": "2.0", "method": "chat_message", "params": {"content": "hi"}}``
    to ``{"type": "chat_message", "content": "hi"}``.
    """
    method = raw.get("method", "unknown")
    params = raw.get("params") or {}
    return {"type": method, **params}


def is_jsonrpc(raw: dict) -> bool:
    """Check whether a parsed dict is a JSON-RPC 2.0 envelope."""
    return raw.get("jsonrpc") == JSONRPC_VERSION
