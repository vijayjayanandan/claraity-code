"""Ephemeral approval policy hints (frozen at tool-call creation).

Agent writes approval policy when tool name becomes known during streaming.
TUI queries when rendering tool cards from store.

Freeze semantics: approval requirement is sampled at tool-call creation time.
If user changes permission mode later, existing tool cards are unaffected;
only future tool calls sample the new mode.

NOT persisted to JSONL - ephemeral, session-scoped only.
NO pub/sub - just a lookup table. MessageStore is the single notification system.
"""

import threading
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ToolApprovalMeta:
    """Frozen approval policy at tool-call creation time.

    Attributes:
        requires_approval: Whether this tool call needs user approval
        permission_mode: Mode at creation time (plan/normal/auto)
    """

    requires_approval: bool = False
    permission_mode: str = "normal"


class RenderMetaRegistry:
    """Session-scoped approval policy hints (no pub/sub).

    Agent writes metadata when tool call is streamed (name becomes known).
    TUI reads metadata when rendering tool cards from store.

    Thread-safe for concurrent access.

    Usage:
        # Agent (during streaming):
        registry.set_approval_meta(tool_call_id, ToolApprovalMeta(
            requires_approval=True,
            permission_mode="normal"
        ))

        # TUI (when creating tool card):
        meta = registry.get_approval_meta(tool_call_id)
        requires_approval = meta.requires_approval if meta else False
    """

    def __init__(self):
        self._approval_meta: dict[str, ToolApprovalMeta] = {}
        self._lock = threading.Lock()

    def set_approval_meta(self, tool_call_id: str, meta: ToolApprovalMeta) -> None:
        """Freeze approval policy for a tool call.

        Called by Agent when tool name becomes known during streaming.
        """
        with self._lock:
            self._approval_meta[tool_call_id] = meta

    def get_approval_meta(self, tool_call_id: str) -> ToolApprovalMeta | None:
        """Query frozen approval policy.

        Called by TUI when rendering tool cards.
        Returns None if not found (e.g., during replay).
        """
        with self._lock:
            return self._approval_meta.get(tool_call_id)

    def clear(self) -> None:
        """Clear all hints (session reset)."""
        with self._lock:
            self._approval_meta.clear()
