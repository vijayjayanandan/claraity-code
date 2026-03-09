"""
Segment renderer for message widgets.

Renders message segments (text, code blocks, tool cards, thinking blocks) into
AssistantMessage widgets. Used by both live streaming and session replay paths.
"""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from src.core.tool_status import ToolStatus as CoreToolStatus
from src.observability import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ..session.models.message import Message
    from .events import ToolStatus
    from .widgets.message import AssistantMessage
    from .widgets.tool_card import ToolCard


class SegmentRenderer:
    """Renders message segments (text, code, tool cards, thinking) into widgets.

    Takes explicit dependencies via constructor to avoid coupling to the App class.
    Shared dicts (tool_cards) are passed by reference so updates are visible to the app.

    Args:
        tool_cards: Shared dict mapping tool_call_id -> ToolCard (app owns this)
        message_store: MessageStore for querying tool state (may be None)
        silent_tools: Set of tool names that should not render ToolCards
        is_replaying_fn: Callable returning True during session replay
        on_tool_card_created: Callback when a new ToolCard is created (for pending subagent mounts)
    """

    def __init__(
        self,
        tool_cards: dict,
        message_store: Any,
        silent_tools: set,
        is_replaying_fn: Callable[[], bool],
        on_tool_card_created: Callable[[str, "ToolCard"], None],
    ):
        self._tool_cards = tool_cards
        self._message_store = message_store
        self._silent_tools = silent_tools
        self._is_replaying = is_replaying_fn
        self._on_tool_card_created = on_tool_card_created

    def set_message_store(self, store: Any) -> None:
        """Update the message store reference (e.g. after store rebind)."""
        self._message_store = store

    async def render_segments(
        self,
        widget: "AssistantMessage",
        message: "Message",
        segments: list,
        start_idx: int = 0,
        skip_existing_cards: bool = False,
        defer_tool_mount: bool = False,
        use_store_hydration: bool = False,
        hydrate_fn: Callable | None = None,
    ) -> int:
        """
        Render segments to a message widget.

        This is the unified segment rendering helper that consolidates duplicate
        logic from _on_store_message_added, _flush_store_updates,
        _on_store_message_finalized, and _on_store_bulk_load_complete.

        Args:
            widget: Target AssistantMessage widget
            message: Message containing tool_calls for reference
            segments: List of segments to render
            start_idx: Start rendering from this index (for incremental updates)
            skip_existing_cards: Skip tool cards that already exist in _tool_cards
            defer_tool_mount: Defer DiffWidget mounting (for bulk load)
            use_store_hydration: Use hydrate_fn for results
            hydrate_fn: Function to hydrate tool card from store (card, tool_call_id) -> None

        Returns:
            Number of segments rendered
        """
        from src.session.models.message import (
            CodeBlockSegment,
            TextSegment,
            ThinkingSegment,
            ToolCallRefSegment,
            ToolCallSegment,
        )

        rendered = 0
        for segment in segments[start_idx:]:
            if isinstance(segment, TextSegment):
                if segment.content and segment.content.strip():
                    await widget.add_text(segment.content)
            elif isinstance(segment, CodeBlockSegment):
                widget.start_code_block(segment.language)
                widget.append_code(segment.content)
                widget.end_code_block()
            elif isinstance(segment, ThinkingSegment):
                if segment.content and segment.content.strip():
                    widget.start_thinking()
                    widget.append_thinking(segment.content)
                    widget.end_thinking()
            elif isinstance(segment, ToolCallRefSegment):
                # Reference by ID (stable)
                tc = self.get_tool_call_by_id(message, segment.tool_call_id)
                if tc:
                    if tc.function.name in self._silent_tools:
                        rendered += 1
                        continue
                    if skip_existing_cards and tc.id in self._tool_cards:
                        rendered += 1
                        continue
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                    if defer_tool_mount:
                        card.set_defer_diff_mount(True)
                    self._tool_cards[tc.id] = card
                    self._on_tool_card_created(tc.id, card)
                    if use_store_hydration and hydrate_fn:
                        hydrate_fn(card, tc.id)
                    elif not self._is_replaying() and self._message_store:
                        # Query store for current status (handles race condition)
                        tool_state = self._message_store.get_tool_state(tc.id)
                        if tool_state and tool_state.status == CoreToolStatus.AWAITING_APPROVAL:
                            from .events import ToolStatus
                            card.status = ToolStatus.AWAITING_APPROVAL
            elif isinstance(segment, ToolCallSegment):
                # Legacy: reference by index (deprecated)
                tc = self.get_tool_call_safe(message, segment.tool_call_index, "render_segments")
                if tc:
                    if tc.function.name in self._silent_tools:
                        rendered += 1
                        continue
                    if skip_existing_cards and tc.id in self._tool_cards:
                        rendered += 1
                        continue
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                    if defer_tool_mount:
                        card.set_defer_diff_mount(True)
                    self._tool_cards[tc.id] = card
                    self._on_tool_card_created(tc.id, card)
                    if use_store_hydration and hydrate_fn:
                        hydrate_fn(card, tc.id)
                    elif not self._is_replaying() and self._message_store:
                        # Query store for current status (handles race condition)
                        tool_state = self._message_store.get_tool_state(tc.id)
                        if tool_state and tool_state.status == CoreToolStatus.AWAITING_APPROVAL:
                            from .events import ToolStatus
                            card.status = ToolStatus.AWAITING_APPROVAL
            rendered += 1
        return rendered

    async def render_tool_segments_only(
        self,
        widget: "AssistantMessage",
        message: "Message",
        segments: list,
    ) -> None:
        """Render only tool call segments from a finalized message.

        Called when text was already streamed incrementally via TextDelta.
        Skips TextSegment and CodeBlockSegment (already rendered).
        """
        from src.session.models.message import ToolCallRefSegment, ToolCallSegment

        for segment in segments:
            if isinstance(segment, ToolCallRefSegment):
                tc = self.get_tool_call_by_id(message, segment.tool_call_id)
                if tc and tc.function.name not in self._silent_tools:
                    if tc.id not in self._tool_cards:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                        self._tool_cards[tc.id] = card
                        self._on_tool_card_created(tc.id, card)
                        if self._message_store:
                            tool_state = self._message_store.get_tool_state(tc.id)
                            if tool_state and tool_state.status == CoreToolStatus.AWAITING_APPROVAL:
                                from .events import ToolStatus
                                card.status = ToolStatus.AWAITING_APPROVAL
            elif isinstance(segment, ToolCallSegment):
                tc = self.get_tool_call_safe(message, segment.tool_call_index, "streaming_dedup")
                if tc and tc.function.name not in self._silent_tools:
                    if tc.id not in self._tool_cards:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                        self._tool_cards[tc.id] = card
                        self._on_tool_card_created(tc.id, card)
                        if self._message_store:
                            tool_state = self._message_store.get_tool_state(tc.id)
                            if tool_state and tool_state.status == CoreToolStatus.AWAITING_APPROVAL:
                                from .events import ToolStatus
                                card.status = ToolStatus.AWAITING_APPROVAL

    def get_tool_call_safe(
        self,
        message: "Message",
        tc_idx: int,
        context: str = ""
    ) -> Any | None:
        """
        Safely get a tool call by index with bounds checking and logging.

        Args:
            message: Message containing tool_calls
            tc_idx: The tool_call_index from the segment
            context: Context string for logging

        Returns:
            ToolCall if valid, None if out of bounds or missing
        """
        if not message.tool_calls:
            logger.warning(
                f"Segment references tool_call_index={tc_idx} but message has no tool_calls. "
                f"Context: {context}, message_uuid={message.uuid if hasattr(message, 'uuid') else 'unknown'}"
            )
            return None

        if tc_idx >= len(message.tool_calls):
            logger.warning(
                f"Segment tool_call_index={tc_idx} out of bounds (message has {len(message.tool_calls)} tool_calls). "
                f"Context: {context}, message_uuid={message.uuid if hasattr(message, 'uuid') else 'unknown'}"
            )
            return None

        return message.tool_calls[tc_idx]

    def get_tool_call_by_id(
        self,
        message: "Message",
        tool_call_id: str,
        context: str = ""
    ) -> Any | None:
        """
        Get a tool call by ID (stable reference).

        Args:
            message: Message containing tool_calls
            tool_call_id: The tool_call_id from the segment
            context: Context string for logging

        Returns:
            ToolCall if found, None if not found
        """
        if not message.tool_calls:
            logger.warning(
                f"Segment references tool_call_id={tool_call_id} but message has no tool_calls. "
                f"Context: {context}, message_uuid={message.uuid if hasattr(message, 'uuid') else 'unknown'}"
            )
            return None

        for tc in message.tool_calls:
            if tc.id == tool_call_id:
                return tc

        logger.warning(
            f"No tool call found with id={tool_call_id}. "
            f"Context: {context}, message_uuid={message.uuid if hasattr(message, 'uuid') else 'unknown'}"
        )
        return None
