"""Lightweight subagent bridge for server transports (stdio+TCP).

Duck-typed to match what delegation.py expects from ``self._registry``
(register / push_notification / unregister). Instead of mounting TUI
widgets it serializes events to JSON and sends them to the VS Code client
so subagent tool cards, approval buttons, and progress updates appear in
the sidebar.

Uses ``asyncio.ensure_future()`` for fire-and-forget sends (same pattern
as ``stdio_server.py`` -- ``notify_todos_updated``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.observability import get_logger
from src.server.serializers import serialize_store_notification

if TYPE_CHECKING:
    from src.session.store.memory_store import StoreNotification

logger = get_logger("server.subagent_bridge")


class ServerSubagentBridge:
    """Forwards subagent lifecycle events over a server protocol.

    The delegation tool calls ``register``, ``push_notification``, and
    ``unregister`` -- exactly the same methods it calls on the TUI's
    ``SubagentRegistry``. This class translates those calls into JSON
    messages the VS Code client already understands.

    Works with any protocol that exposes an async ``_send_json(dict)``
    method (StdioProtocol, etc.).
    """

    def __init__(self, protocol: Any) -> None:
        self._protocol = protocol
        self._active: dict[str, dict[str, Any]] = {}

    def register(
        self,
        subagent_id: str,
        store: Any,
        transcript_path: Any,
        parent_tool_call_id: str,
        instance: Any = None,
        model_name: str = "",
        subagent_name: str = "",
        context_window: int = 0,
    ) -> None:
        """Track a newly launched subagent and notify the client."""
        self._active[subagent_id] = {
            "parent_tool_call_id": parent_tool_call_id,
            "model_name": model_name,
            "subagent_name": subagent_name,
        }
        asyncio.ensure_future(
            self._protocol._send_json(
                {
                    "type": "subagent",
                    "event": "registered",
                    "data": {
                        "subagent_id": subagent_id,
                        "parent_tool_call_id": parent_tool_call_id,
                        "model_name": model_name,
                        "subagent_name": subagent_name,
                        "transcript_path": str(transcript_path),
                        "context_window": context_window,
                    },
                }
            )
        )
        logger.info(
            f"[BRIDGE] Registered subagent {subagent_id} (name={subagent_name}, model={model_name})"
        )

    def push_notification(
        self,
        subagent_id: str,
        notification: StoreNotification,
    ) -> None:
        """Serialize a store notification and forward to the client."""
        data = serialize_store_notification(notification)
        if data is not None:
            data["subagent_id"] = subagent_id
            asyncio.ensure_future(self._protocol._send_json(data))

    def unregister(self, subagent_id: str) -> None:
        """Remove tracking and notify the client."""
        self._active.pop(subagent_id, None)
        asyncio.ensure_future(
            self._protocol._send_json(
                {
                    "type": "subagent",
                    "event": "unregistered",
                    "data": {"subagent_id": subagent_id},
                }
            )
        )
        logger.info(f"[BRIDGE] Unregistered subagent {subagent_id}")
