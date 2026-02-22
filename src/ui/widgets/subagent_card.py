"""SubAgentCard - displays subagent execution as a collapsible mini-session.

Renders subagent output identically to the main session using the same
AssistantMessage and ToolCard widgets.  The card takes full width (same as
main agent) and is collapsible via a clickable header.

Widget tree:
    SubAgentCard (Container)
    +-- _SubagentHeader (Static, clickable)   -- status badge + collapse toggle
    +-- _SubagentBody (Vertical)              -- display:none when collapsed
        +-- Static (dim task input)           -- first user message
        +-- AssistantMessage                  -- reused from main session
        |   +-- text blocks, code blocks
        |   +-- ToolCard (per tool call)      -- with diffs, results
        +-- AssistantMessage                  -- next assistant turn
        ...

Mounted inside the parent ToolCard (delegation tool call).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from textual.containers import Container, ScrollableContainer, Vertical
from textual.widgets import Static
from rich.text import Text
from rich.console import RenderableType

from src.core.events import ToolStatus
from src.observability import get_logger

if TYPE_CHECKING:
    from src.session.store.memory_store import (
        MessageStore, StoreNotification, StoreEvent, ToolExecutionState,
    )
    from src.session.models.message import Message
    from src.ui.widgets.tool_card import ToolCard

logger = get_logger("ui.widgets.subagent_card")


# Tools that should not be rendered (same as app.py SILENT_TOOLS)
SILENT_TOOLS = {'task_create', 'task_update', 'task_list', 'task_get', 'enter_plan_mode'}

# Status badge config for the header
HEADER_ICONS: Dict[str, tuple[str, str, str]] = {
    "running": ("*", "#1e1e1e", "#cca700"),
    "done":    ("+", "#1e1e1e", "#73c991"),
    "failed":  ("!", "#ffffff", "#f14c4c"),
}


# =============================================================================
# Helper widgets
# =============================================================================

class _SubagentHeader(Static):
    """Clickable header: status badge + subagent name + tool count + duration.

    Click to toggle collapse/expand of the body.
    """

    DEFAULT_CSS = """
    _SubagentHeader {
        width: 100%;
        height: 1;
        color: #9cdcfe;
        background: #1a1a2e;
        padding: 0 1;
    }
    _SubagentHeader:hover {
        background: #252545;
        text-style: bold;
    }
    """

    def __init__(self, subagent_id: str, model_name: str = "", **kwargs):
        super().__init__(**kwargs)
        self._subagent_id = subagent_id
        self._model_name = model_name
        self._status = "running"
        self._tool_count = 0
        self._duration_ms: Optional[int] = None
        self._collapsed = False

    def update_status(
        self,
        status: str,
        tool_count: int,
        duration_ms: Optional[int] = None,
    ) -> None:
        self._status = status
        self._tool_count = tool_count
        self._duration_ms = duration_ms
        self.refresh()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.refresh()

    def render(self) -> RenderableType:
        icon, fg, bg = HEADER_ICONS.get(
            self._status, ("*", "#1e1e1e", "#cca700")
        )

        collapse_indicator = "[+]" if self._collapsed else "[-]"

        t = Text()
        t.append(collapse_indicator, style="bold #73c991" if not self._collapsed else "bold #cca700")
        t.append(" ", style="")
        t.append(f" {icon} ", style=f"bold {fg} on {bg}")
        t.append(" ", style="")
        t.append("Subagent ", style="#9cdcfe")
        t.append(self._subagent_id[:12], style="bold #e0e0e0")

        if self._model_name:
            t.append(f" ({self._model_name})", style="#b5cea8")

        t.append(f" | {self._tool_count} tools", style="#6e7681")

        if self._duration_ms:
            secs = self._duration_ms / 1000
            t.append(f" | {secs:.1f}s", style="#6e7681")
        elif self._status == "running":
            t.append(" | running", style="#cca700")

        return t

    def on_click(self, event) -> None:
        event.stop()
        card = self.parent
        if isinstance(card, SubAgentCard):
            card.toggle_collapsed()


class _SubagentBody(ScrollableContainer):
    """Scrollable container for the mini-session content.

    Toggled via -collapsed class. Max height prevents subagent output
    from taking over the entire screen.
    """

    DEFAULT_CSS = """
    _SubagentBody {
        height: auto;
        max-height: 40;
        padding: 0;
        margin: 0;
        border-left: tall #333355;
    }
    _SubagentBody.-collapsed {
        display: none;
    }
    """


# =============================================================================
# Main SubAgentCard
# =============================================================================

class SubAgentCard(Container):
    """Displays subagent execution as a collapsible mini-session.

    Architecture:
        SubAgentCard (Container)
        +-- _SubagentHeader (clickable collapse toggle + status badge)
        +-- _SubagentBody (Vertical, toggles display:none)
            +-- Static (dim task input text)
            +-- AssistantMessage (with ToolCards, code blocks, etc.)
            +-- AssistantMessage (next turn, if any)
            ...

    Reuses the same AssistantMessage and ToolCard widgets as the main session
    for identical rendering of text, code, tool results, and file diffs.
    """

    DEFAULT_CSS = """
    SubAgentCard {
        height: auto;
        padding: 0;
        margin: 0;
    }
    /* Subagent user messages: orange (distinct from main agent blue) */
    SubAgentCard MessageWidget.subagent-user {
        border-left: thick #cc7832;
    }
    /* Subagent assistant messages: purple (distinct from main agent green) */
    SubAgentCard MessageWidget.subagent-message {
        border-left: thick #6a5acd;
    }
    """

    def __init__(
        self,
        subagent_id: str,
        transcript_path: Optional[Path] = None,
        store: Optional["MessageStore"] = None,
        buffered_notifications: Optional[list] = None,
        model_name: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.subagent_id = subagent_id
        self.transcript_path = transcript_path
        self.model_name = model_name
        self._status = "running"
        self._collapsed = False
        self._duration_ms: Optional[int] = None

        # Own tool card tracking (separate from app._tool_cards)
        self._tool_cards: Dict[str, "ToolCard"] = {}
        self._tool_count = 0

        # Buffer for tool state updates that arrive before the card is mounted.
        # call_later creates concurrent async tasks, so TOOL_STATE_UPDATED can
        # race ahead of the MESSAGE_ADDED handler that creates the ToolCard.
        self._pending_tool_states: Dict[str, "StoreNotification"] = {}

        # Current assistant message widget (for appending tool cards)
        self._current_assistant: Optional[Any] = None

        # Track which stream_ids we've already rendered
        self._rendered_stream_ids: set = set()

        # Deferred hydration: processed in on_mount after compose builds DOM
        self._pending_store = store
        self._pending_notifications = buffered_notifications or []

        # Direct widget references (set after compose)
        self._header: Optional[_SubagentHeader] = None
        self._body: Optional[_SubagentBody] = None

    def compose(self):
        yield _SubagentHeader(self.subagent_id, model_name=self.model_name, id="sa-header")
        yield _SubagentBody(id="sa-body")

    async def on_mount(self) -> None:
        """Hydrate from store after compose builds the DOM."""
        try:
            self._header = self.query_one("#sa-header", _SubagentHeader)
        except Exception:
            pass
        try:
            self._body = self.query_one("#sa-body", _SubagentBody)
        except Exception:
            pass

        # Deferred hydration
        if self._pending_store is not None:
            await self._hydrate_from_store(self._pending_store)
            self._pending_store = None

        # Flush buffered notifications
        if self._pending_notifications:
            for notif in self._pending_notifications:
                await self._apply_notification(notif)
            self._pending_notifications.clear()

    # -------------------------------------------------------------------------
    # Public API (called by app.py)
    # -------------------------------------------------------------------------

    def toggle_collapsed(self) -> None:
        """Toggle collapse state of the body."""
        self._collapsed = not self._collapsed
        if self._header:
            self._header.set_collapsed(self._collapsed)
        if self._body:
            if self._collapsed:
                self._body.add_class("-collapsed")
            else:
                self._body.remove_class("-collapsed")

    async def update_from_notification(self, notification: "StoreNotification") -> None:
        """Update display from a live store notification."""
        await self._apply_notification(notification)

    def hydrate_from_store(self, store: "MessageStore") -> None:
        """Sync entry point for hydration (for backward compat).

        Prefer the async path via on_mount deferred hydration.
        """
        # Schedule async hydration
        self.call_later(self._hydrate_from_store, store)

    def mark_completed(self, success: bool = True) -> None:
        """Mark the subagent as completed."""
        self._status = "done" if success else "failed"
        self._refresh_header()

        # Auto-collapse on completion
        if not self._collapsed:
            self.toggle_collapsed()

    def remove(self) -> None:
        """Clean up references before removal."""
        self._tool_cards.clear()
        self._pending_tool_states.clear()
        self._current_assistant = None
        super().remove()

    # -------------------------------------------------------------------------
    # Internal: hydration from store (session resume)
    # -------------------------------------------------------------------------

    async def _hydrate_from_store(self, store: "MessageStore") -> None:
        """Load and render all messages from the store."""
        try:
            messages = store.get_ordered_messages()

            for msg in messages:
                await self._render_message(msg, store=store)

            self._refresh_header()

        except Exception as e:
            logger.error(f"SubAgentCard hydrate error: {e}")

    # -------------------------------------------------------------------------
    # Internal: notification handling
    # -------------------------------------------------------------------------

    async def _apply_notification(self, notification: "StoreNotification") -> None:
        """Process a single store notification."""
        try:
            from src.session.store.memory_store import StoreEvent

            if notification.event == StoreEvent.TOOL_STATE_UPDATED:
                self._apply_tool_state_update(notification)

            elif notification.event == StoreEvent.MESSAGE_ADDED:
                if notification.message:
                    await self._render_message(notification.message)
                    self._refresh_header()

            elif notification.event == StoreEvent.MESSAGE_UPDATED:
                if notification.message and notification.message.role == "assistant":
                    await self._update_assistant_message(notification.message)

            elif notification.event == StoreEvent.MESSAGE_FINALIZED:
                if notification.message and notification.message.role == "assistant":
                    # Finalize the current assistant widget
                    if self._current_assistant:
                        self._current_assistant.finalize()

        except Exception as e:
            logger.error(f"SubAgentCard notification error: {e}")

    def _apply_tool_state_update(self, notification: "StoreNotification") -> None:
        """Update an existing ToolCard from a tool state notification.

        call_later processes notifications sequentially, so the MESSAGE_ADDED
        that creates the ToolCard always completes before TOOL_STATE_UPDATED
        is processed. No buffering needed.
        """
        if not notification.tool_call_id or not notification.tool_state:
            return

        card = self._tool_cards.get(notification.tool_call_id)
        if not card:
            # Card not created yet (async race). Buffer for flush on card creation.
            self._pending_tool_states[notification.tool_call_id] = notification
            return

        state = notification.tool_state
        status = state.status

        if status == ToolStatus.AWAITING_APPROVAL:
            card.status = ToolStatus.AWAITING_APPROVAL
        elif status == ToolStatus.APPROVED:
            card.status = ToolStatus.APPROVED
        elif status == ToolStatus.REJECTED:
            card.status = ToolStatus.REJECTED
        elif status == ToolStatus.RUNNING:
            card.start_running()
        elif status == ToolStatus.SUCCESS:
            # Result content comes from tool MESSAGE_ADDED, not state update.
            # Use state.result if available, otherwise just update duration/status.
            result_content = str(state.result) if state.result else ""
            if result_content:
                card.set_result(result_content, duration_ms=state.duration_ms)
            elif card.status != ToolStatus.SUCCESS:
                # Only upgrade status if card hasn't already been set by tool message
                card.set_result("", duration_ms=state.duration_ms)
        elif status in (ToolStatus.FAILED, ToolStatus.ERROR):
            card.set_error(state.error or "Unknown error")
        elif status == ToolStatus.CANCELLED:
            card.cancel()

        self._refresh_header()

    # -------------------------------------------------------------------------
    # Internal: message rendering
    # -------------------------------------------------------------------------

    async def _render_message(
        self,
        msg: "Message",
        store: Optional["MessageStore"] = None,
    ) -> None:
        """Render a single store message into the body."""
        if not self._body:
            return

        if msg.role == "user":
            await self._render_user_message(msg)
        elif msg.role == "assistant":
            await self._render_assistant_message(msg, store=store)
        elif msg.role == "tool":
            self._apply_tool_result_message(msg)

    async def _render_user_message(self, msg: "Message") -> None:
        """Show user message as a proper MessageWidget with subagent-specific color."""
        from src.ui.widgets.message import MessageWidget

        if not self._body or not msg.content:
            return
        content = msg.content if isinstance(msg.content, str) else str(msg.content)

        widget = MessageWidget(role="user")
        widget.add_class("subagent-user")
        await self._body.mount(widget)
        await widget.add_text(content)
        widget.finalize()

    async def _render_assistant_message(
        self,
        msg: "Message",
        store: Optional["MessageStore"] = None,
    ) -> None:
        """Render an assistant message using AssistantMessage widget."""
        from src.ui.widgets.message import AssistantMessage

        if not self._body:
            return

        # Avoid rendering the same message twice
        stream_id = msg.meta.stream_id if msg.meta else None
        if stream_id and stream_id in self._rendered_stream_ids:
            return
        if stream_id:
            self._rendered_stream_ids.add(stream_id)

        widget = AssistantMessage()
        widget.add_class("subagent-message")
        self._current_assistant = widget
        await self._body.mount(widget)

        # Render segments if available
        segments = msg.meta.segments if msg.meta and msg.meta.segments else []
        if segments:
            await self._render_segments(widget, msg, segments, store=store)
        else:
            # Fallback: render plain content + tool calls
            if msg.content:
                await widget.add_text(msg.content)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.function.name in SILENT_TOOLS:
                        continue
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                    self._register_tool_card(tc.id, card)
                    if store:
                        self._hydrate_tool_card(card, tc.id, store)

        # Finalize immediately (messages arrive complete, no streaming)
        widget.finalize()

    async def _update_assistant_message(self, msg: "Message") -> None:
        """Handle incremental updates to the current assistant message.

        For live notifications where the assistant message gets updated
        with new segments (e.g., new tool calls added to an existing message).
        """
        if not self._current_assistant:
            return

        segments = msg.meta.segments if msg.meta and msg.meta.segments else []
        if segments:
            # Re-render only new segments we haven't seen
            await self._render_segments(self._current_assistant, msg, segments)

    async def _render_segments(
        self,
        widget: "Any",  # AssistantMessage
        message: "Message",
        segments: list,
        store: Optional["MessageStore"] = None,
    ) -> None:
        """Render message segments into an AssistantMessage widget.

        Simplified version of app.py's _render_segments(). Handles:
        - TextSegment: markdown text
        - CodeBlockSegment: syntax-highlighted code
        - ThinkingSegment: collapsible thinking block
        - ToolCallRefSegment: ToolCard with diffs and results
        """
        from src.session.models.message import (
            TextSegment, CodeBlockSegment,
            ToolCallRefSegment, ThinkingSegment
        )

        for segment in segments:
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
                tc = self._find_tool_call(message, segment.tool_call_id)
                if tc:
                    if tc.function.name in SILENT_TOOLS:
                        continue
                    # Skip if we already created this card
                    if tc.id in self._tool_cards:
                        continue
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    card = widget.add_tool_card(tc.id, tc.function.name, args, requires_approval=False)
                    self._register_tool_card(tc.id, card)
                    # Hydrate from store if available (session resume)
                    if store:
                        self._hydrate_tool_card(card, tc.id, store)

    # -------------------------------------------------------------------------
    # Internal: tool card hydration
    # -------------------------------------------------------------------------

    def _hydrate_tool_card(
        self,
        card: "ToolCard",
        tool_call_id: str,
        store: "MessageStore",
    ) -> None:
        """Load tool result from store into a ToolCard (session resume)."""
        result_msg = store.get_tool_result(tool_call_id)

        if result_msg:
            result_content = (
                result_msg.get_text_content()
                if hasattr(result_msg, 'get_text_content')
                else (result_msg.content or "")
            )
            status = result_msg.meta.status if result_msg.meta else None
            duration = result_msg.meta.duration_ms if result_msg.meta else None

            if status in ("success", None):
                card.set_result(result_content, duration_ms=duration)
            elif status in ("error", "timeout", "cancelled"):
                card.set_error(result_content or f"Tool {status}")
            else:
                card.set_result(result_content, duration_ms=duration)
        else:
            # No result found -- interrupted
            card.status = ToolStatus.CANCELLED
            card.result_preview = "(Interrupted - no recorded result)"

    def _apply_tool_result_message(self, msg: "Message") -> None:
        """Apply a tool result message to the corresponding ToolCard."""
        if not msg.meta:
            return
        tool_call_id = msg.meta.tool_call_id if hasattr(msg.meta, 'tool_call_id') else None
        if not tool_call_id:
            return

        card = self._tool_cards.get(tool_call_id)
        if not card:
            return

        content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        status = msg.meta.status if msg.meta else None
        duration = msg.meta.duration_ms if msg.meta else None

        if status in ("error", "timeout", "cancelled"):
            card.set_error(content or f"Tool {status}")
        else:
            card.set_result(content, duration_ms=duration)

    # -------------------------------------------------------------------------
    # Internal: helpers
    # -------------------------------------------------------------------------

    def _register_tool_card(self, tool_call_id: str, card: "ToolCard") -> None:
        """Register a tool card and flush any pending state updates.

        call_later creates concurrent async tasks, so TOOL_STATE_UPDATED
        notifications can arrive before MESSAGE_ADDED finishes creating
        the ToolCard. This method applies any buffered states.
        """
        self._tool_cards[tool_call_id] = card
        self._tool_count += 1

        # Flush pending tool state update (if TOOL_STATE_UPDATED raced ahead)
        pending = self._pending_tool_states.pop(tool_call_id, None)
        if pending:
            self._apply_tool_state_update(pending)

    @staticmethod
    def _find_tool_call(message: "Message", tool_call_id: str):
        """Find a tool call by ID in a message."""
        if not message.tool_calls:
            return None
        for tc in message.tool_calls:
            if tc.id == tool_call_id:
                return tc
        return None

    def _refresh_header(self) -> None:
        """Update the header with current status and tool count."""
        if self._header:
            self._header.update_status(
                self._status, self._tool_count, self._duration_ms
            )
