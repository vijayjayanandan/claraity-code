"""
Store-driven message renderer.

Renders messages from MessageStore into conversation widgets. Handles user
messages, assistant messages (with segment-based rendering), tool results,
and system messages (clarify requests, plan approvals, compaction boundaries).
"""

from typing import TYPE_CHECKING, Any, Callable, Awaitable, Optional

from src.observability import get_logger
from src.core.tool_status import ToolStatus as CoreToolStatus

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ..session.store.memory_store import MessageStore
    from ..session.models.message import Message
    from .widgets.message import MessageWidget, UserMessage, AssistantMessage
    from .widgets.tool_card import ToolCard
    from .segment_renderer import SegmentRenderer
    from .events import ToolStatus


class StoreRenderer:
    """Renders messages from MessageStore into conversation widgets.

    Takes shared state dicts by reference (so mutations are visible to the app)
    and callbacks for operations that require Textual widget state.

    Args:
        segment_renderer: SegmentRenderer for rendering assistant message segments
        tool_cards: Shared dict mapping tool_call_id -> ToolCard
        message_store: MessageStore instance (may change on rebind)
        store_message_widgets: Shared dict mapping stream_id -> MessageWidget
        store_rendered_segment_idx: Shared dict mapping stream_id -> last rendered segment index
        silent_tools: Set of tool names that should not display ToolCards
        on_clarify_request: Callback for clarify_request system messages
        on_plan_approval: Callback for plan approval system messages
        on_tool_card_created: Callback when a ToolCard is created
        scroll_to_bottom: Callback to scroll conversation to bottom
    """

    def __init__(
        self,
        segment_renderer: "SegmentRenderer",
        tool_cards: dict,
        message_store: Any,
        store_message_widgets: dict,
        store_rendered_segment_idx: dict,
        silent_tools: set,
        on_clarify_request: Callable,
        on_plan_approval: Callable,
        on_tool_card_created: Callable,
        scroll_to_bottom: Callable,
    ):
        self._segment_renderer = segment_renderer
        self._tool_cards = tool_cards
        self._message_store = message_store
        self._store_message_widgets = store_message_widgets
        self._store_rendered_segment_idx = store_rendered_segment_idx
        self._silent_tools = silent_tools
        self._on_clarify_request = on_clarify_request
        self._on_plan_approval = on_plan_approval
        self._on_tool_card_created = on_tool_card_created
        self._scroll_to_bottom = scroll_to_bottom

    def set_message_store(self, store: Any) -> None:
        """Update the message store reference."""
        self._message_store = store

    async def render_store_message(
        self,
        message: "Message",
        conversation: Any,
        bulk_load: bool = False,
        current_message: Optional["MessageWidget"] = None,
        pre_mounted_user_widget: Optional["MessageWidget"] = None,
        is_replaying: bool = False,
        status_bar: Any = None,
    ) -> Optional["MessageWidget"]:
        """Render a single message from the store into the conversation.

        This is the SINGLE rendering path for all store-driven messages.
        Both live notifications and bulk load (session replay) use this method.

        Args:
            message: The message to render
            conversation: The conversation container to mount widgets into
            bulk_load: If True, applies bulk load optimizations
            current_message: The currently active streaming AssistantMessage (live path)
            pre_mounted_user_widget: Eagerly-mounted UserMessage widget (live path)
            is_replaying: True during session replay
            status_bar: StatusBar widget for director phase updates

        Returns:
            The pre_mounted_user_widget (may be consumed/cleared) or None
        """
        from .widgets.message import UserMessage, AssistantMessage
        from .events import ToolStatus

        if not message:
            return pre_mounted_user_widget

        # Track by stream_id for updates
        stream_id = message.meta.stream_id if message.meta else None

        # Create appropriate widget based on role
        if message.is_user:
            # Adopt pre-mounted widget (mounted immediately on submit)
            if not bulk_load and pre_mounted_user_widget is not None:
                widget = pre_mounted_user_widget
                pre_mounted_user_widget = None  # consumed
                if stream_id:
                    self._store_message_widgets[stream_id] = widget
                return pre_mounted_user_widget  # Return None (consumed)
            # Pass raw content and UUID for clickable image support
            message_uuid = message.meta.uuid if message.meta else ""
            widget = UserMessage(content=message.content or "", message_uuid=message_uuid)
        elif message.is_assistant:
            if not bulk_load:
                # Check if widget already exists for this stream_id
                if stream_id and stream_id in self._store_message_widgets:
                    return pre_mounted_user_widget

                # Live stream in progress - register widget, render tool cards only
                if current_message is not None:
                    if stream_id:
                        self._store_message_widgets[stream_id] = current_message
                    segments = message.meta.segments if message.meta and message.meta.segments else []
                    if segments:
                        await self._segment_renderer.render_tool_segments_only(
                            current_message, message, segments
                        )
                    return pre_mounted_user_widget

            # Skip assistant messages with no text and only silent tool calls
            if not message.content:
                tool_calls = message.tool_calls or []
                if tool_calls and all(tc.function.name in self._silent_tools for tc in tool_calls):
                    return pre_mounted_user_widget

            widget = AssistantMessage()
        elif message.is_tool:
            # Tool result message - update the corresponding ToolCard
            await self.apply_tool_result_to_card(message)
            return pre_mounted_user_widget
        elif message.is_system:
            await self._handle_system_message(
                message, conversation, status_bar
            )
            return pre_mounted_user_widget
        else:
            return pre_mounted_user_widget

        if stream_id:
            self._store_message_widgets[stream_id] = widget

        await conversation.mount(widget)

        # Render content for assistant messages using segments
        if message.is_assistant:
            segments = message.meta.segments if message.meta and message.meta.segments else []

            if segments:
                try:
                    rendered = await self._segment_renderer.render_segments(
                        widget, message, segments,
                        defer_tool_mount=bulk_load,
                        use_store_hydration=bulk_load,
                        hydrate_fn=self.hydrate_tool_card_from_store if bulk_load else None,
                    )
                except Exception as e:
                    logger.error(
                        f"_render_segments failed: {type(e).__name__}: {e}",
                        exc_info=True
                    )
                    rendered = 0
                # Track segment index for future updates (live path only)
                if not bulk_load and stream_id:
                    self._store_rendered_segment_idx[stream_id] = rendered
            else:
                # Fallback: no segments, render content if present
                if message.content:
                    await widget.add_text(message.content)
                # Bulk load: also render tool calls in fallback path
                if bulk_load and message.tool_calls:
                    import json
                    for tc in message.tool_calls:
                        if tc.function.name in self._silent_tools:
                            continue
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                        card.set_defer_diff_mount(True)
                        self._tool_cards[tc.id] = card
                        self._on_tool_card_created(tc.id, card)
                        self.hydrate_tool_card_from_store(card, tc.id)

            # Bulk load: finalize widget immediately
            if bulk_load:
                widget.finalize()

        # Auto-scroll only during live rendering (not replay)
        if not bulk_load and not is_replaying:
            self._scroll_to_bottom(conversation)

        return pre_mounted_user_widget

    async def _handle_system_message(
        self,
        message: "Message",
        conversation: Any,
        status_bar: Any = None,
    ) -> None:
        """Handle system message types (clarify, plan, director, compaction, etc.)."""
        from .events import ToolStatus

        event_type = message.meta.event_type if message.meta else None

        if event_type == "compact_boundary":
            for child in list(conversation.children):
                child.remove()
            self._store_message_widgets.clear()
            self._tool_cards.clear()
            logger.info("compact_boundary: cleared pre-compaction widgets")

        elif event_type == "clarify_request":
            await self._on_clarify_request(message, conversation)

        elif event_type == "plan_submitted":
            await self._handle_plan_submitted(message, "PLAN")

        elif event_type == "director_plan_submitted":
            await self._handle_plan_submitted(message, "DIRECTOR")

        elif event_type == "director_phase_changed":
            extra = message.meta.extra if message.meta else {}
            new_phase = extra.get("phase", "") if extra else ""
            if status_bar:
                try:
                    if new_phase:
                        status_bar.set_director_phase(new_phase)
                    else:
                        status_bar.clear_director_phase()
                except Exception:
                    pass

        elif event_type == "permission_mode_changed":
            if self._message_store:
                new_mode = self._message_store.current_mode
            else:
                extra = message.meta.extra if message.meta else {}
                new_mode = extra.get("new_mode", "normal") if extra else "normal"
            if status_bar:
                try:
                    status_bar.set_mode(new_mode)
                except Exception:
                    pass

    async def _handle_plan_submitted(self, message: "Message", label: str) -> None:
        """Handle plan_submitted / director_plan_submitted system messages."""
        extra = message.meta.extra if message.meta else {}
        plan_hash = extra.get("plan_hash") if extra else None
        call_id = extra.get("call_id") if extra else None

        if not plan_hash:
            return

        # Check if tool already has a result (already approved/rejected)
        if call_id and self._message_store:
            tool_result = self._message_store.get_tool_result(call_id)
            if tool_result:
                logger.info(f"[{label}] Skipping approval mount - tool result exists for call_id={call_id}")
                return

        await self._on_plan_approval(
            plan_hash=plan_hash,
            excerpt=extra.get("excerpt", ""),
            truncated=extra.get("truncated", False),
            plan_path=extra.get("plan_path") if label == "PLAN" else None,
        )

    async def apply_tool_result_to_card(self, message: "Message") -> None:
        """
        Apply a tool result message to its corresponding ToolCard.

        Args:
            message: Tool result message with tool_call_id and meta.status
        """
        if not message.tool_call_id:
            logger.warning("Tool result message missing tool_call_id, cannot update ToolCard")
            return

        tool_call_id = message.tool_call_id
        card = self._tool_cards.get(tool_call_id)
        if not card:
            logger.debug(f"No ToolCard found for tool_call_id={tool_call_id}, skipping result update")
            return

        status = message.meta.status if message.meta else None
        duration_ms = message.meta.duration_ms if message.meta else None
        content = message.content or ""

        if status == "success":
            card.set_result(content, duration_ms=duration_ms)
        elif status in ("error", "timeout", "cancelled"):
            error_msg = content if content else f"Tool execution {status}"
            card.set_error(error_msg)
        else:
            if content:
                card.set_result(content, duration_ms=duration_ms)
            else:
                logger.warning(f"Tool result for {tool_call_id} has no status and no content")

    def hydrate_tool_card_from_store(self, card: "ToolCard", tool_call_id: str) -> None:
        """
        Hydrate a ToolCard with result and approval data from the MessageStore.

        Handles (in order):
        1. Approval decisions
        2. Success: Sets result content and duration
        3. Error/Timeout: Sets error message
        4. Missing result: Shows "Interrupted" label

        Args:
            card: The ToolCard widget to hydrate
            tool_call_id: The tool_call_id to look up in the store
        """
        from .events import ToolStatus

        if not self._message_store:
            card.status = ToolStatus.PENDING
            return

        # Check for approval decision
        approval_msg = self._message_store.get_tool_approval(tool_call_id)
        has_approval = False
        approved = False
        if approval_msg and approval_msg.meta and approval_msg.meta.extra:
            extra = approval_msg.meta.extra
            approved = extra.get("approved", False)
            has_approval = True

        result_msg = self._message_store.get_tool_result(tool_call_id)

        if result_msg:
            result_content = result_msg.get_text_content() if hasattr(result_msg, 'get_text_content') else (result_msg.content or "")
            status = result_msg.meta.status if result_msg.meta else None
            duration = result_msg.meta.duration_ms if result_msg.meta else None

            if status in ("success", None):
                card.set_result(result_content, duration_ms=duration)
            elif status in ("error", "timeout", "cancelled"):
                card.set_error(result_content or f"Tool {status}")
            else:
                card.set_result(result_content, duration_ms=duration)
        elif has_approval:
            if approved:
                card.status = ToolStatus.APPROVED
                card.result_preview = "(Approved but not executed)"
            else:
                card.status = ToolStatus.REJECTED
                feedback = approval_msg.meta.extra.get("feedback") if approval_msg.meta.extra else None
                if feedback:
                    card.result_preview = f"(Rejected: {feedback[:50]})"
                else:
                    card.result_preview = "(Rejected by user)"
        else:
            card.status = ToolStatus.CANCELLED
            card.result_preview = "(Interrupted - no recorded result)"
