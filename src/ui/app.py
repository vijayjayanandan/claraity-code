"""
CodingAgentApp - Main Textual application for the coding agent.

This is the top-level application that:
- Composes the UI layout (conversation, input, status bar)
- Handles UIEvents from StreamProcessor and dispatches to widgets
- Manages streaming state and auto-scroll
- Coordinates with UIProtocol for approvals
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.events import Paste
from textual.widgets import Footer, Header, Static, TextArea
from textual.widgets.text_area import Selection
from textual.worker import Worker

from src.observability import get_logger

# Module-level logger for debugging silent exceptions
logger = get_logger(__name__)

from src.core.attachment import Attachment
from src.core.render_meta import RenderMetaRegistry
from src.core.tool_status import ToolStatus as CoreToolStatus

from .autocomplete import FileAutocomplete
from .clipboard_handler import ClipboardHandler
from .events import (
    CodeBlockDelta,
    CodeBlockEnd,
    CodeBlockStart,
    ContextCompacted,
    ContextCompacting,
    ContextUpdated,
    ErrorEvent,
    FileReadEvent,
    PausePromptEnd,
    PausePromptStart,
    StreamEnd,
    StreamStart,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolStatus,
    UIEvent,
)
from .messages import (
    ApprovalResponseMessage,
    ClarifyResponseMessage,
    InputSubmittedMessage,
    PauseResponseMessage,
    PlanApprovalResponseMessage,
    RetryRequestMessage,
    StreamInterruptMessage,
)
from .protocol import (
    ApprovalResult,
    ClarifyResult,
    InterruptSignal,
    PauseResult,
    PlanApprovalResult,
    RetrySignal,
    UIProtocol,
)
from .segment_renderer import SegmentRenderer
from .store_renderer import StoreRenderer
from .subagent_coordinator import SubagentCoordinator
from .widgets.attachment_bar import AttachmentBar
from .widgets.autocomplete_dropdown import AutocompleteDropdown
from .widgets.clarify_widget import ClarifyWidget
from .widgets.code_block import CodeBlock
from .widgets.message import AssistantMessage, MessageWidget, UserMessage
from .widgets.pause_widget import PausePromptWidget
from .widgets.plan_approval_widget import PlanApprovalWidget
from .widgets.status_bar import StatusBar
from .widgets.subagent_card import SubAgentCard
from .widgets.thinking import ThinkingBlock
from .widgets.todo_bar import TodoBar
from .widgets.tool_card import ToolCard

if TYPE_CHECKING:
    from ..core.agent import CodingAgent  # For type hints
    from ..session.models.message import Message
    from ..session.store.memory_store import MessageStore, StoreNotification
    from .store_adapter import StoreAdapter
    from .subagent_registry import SubagentRegistry


# Tools that should NOT display a ToolCard in the UI (silent/internal tools)
SILENT_TOOLS = {
    'task_create', 'task_update', 'task_list', 'task_get', 'enter_plan_mode',
    'director_complete_understand', 'director_complete_plan',
    'director_complete_slice', 'director_complete_integration',
}

# =============================================================================
# FOCUSABLE CONVERSATION CONTAINER
# =============================================================================

class ConversationContainer(ScrollableContainer):
    """ScrollableContainer that can receive focus for keyboard scrolling.

    By setting can_focus=True, users can:
    - Click on the conversation area to focus it
    - Use mouse wheel to scroll (works even without focus in Textual)
    - Use keyboard bindings (PageUp/PageDown, Ctrl+Up/Down) when app has focus
    """
    can_focus = True


# =============================================================================
# USER-FRIENDLY ERROR HANDLING (extracted to error_helpers.py)
# =============================================================================
from .error_helpers import (
    _classify_error,
    _extract_user_content_text,
    _format_user_error,
    _generate_error_reference,
)


class ChatInput(TextArea):
    """
    Multi-line input with Ctrl+Enter for newline, Enter for submit.

    Features:
    - Ctrl+Enter = newline (like Claude Code)
    - Enter = submit
    - Ctrl+V = paste (text, images, or files)
    - Attachment indicator in border title
    """

    # Ensure this widget can receive focus
    can_focus = True

    DEFAULT_CSS = """
    ChatInput {
        height: auto;
        min-height: 5;
        max-height: 15;
        margin: 0 1 1 1;
        border: round #666666;
    }

    ChatInput:focus {
        border: round $accent;
    }
    """

    BINDINGS = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.show_line_numbers = False
        # Remove language to disable syntax highlighting
        self.language = None
        # Attachment manager for screenshots/files
        from .attachments import AttachmentManager
        self.attachments = AttachmentManager()
        # Autocomplete for @ file references
        from pathlib import Path
        self._autocomplete = FileAutocomplete(Path("."))
        self._autocomplete_active = False
        self._autocomplete_start = 0  # Position of @ in text
        self._index_task: asyncio.Task | None = None  # Track for cleanup
        # Guard to prevent on_paste() from double-inserting text
        self._suppress_paste_text_until = 0.0

    def action_undo(self) -> None:
        """Override to handle cursor position errors during undo.

        Textual bug: undo can leave cursor at invalid position when
        scrollbar visibility changes during the operation.
        """
        try:
            super().action_undo()
        except ValueError:
            # Cursor at invalid position after undo - reset to safe position
            try:
                self.cursor_location = (0, 0)
                self.selection = Selection(start=(0, 0), end=(0, 0))
            except Exception:
                pass

    def action_redo(self) -> None:
        """Override to handle cursor position errors during redo."""
        try:
            super().action_redo()
        except ValueError:
            # Cursor at invalid position after redo - reset to safe position
            try:
                self.cursor_location = (0, 0)
                self.selection = Selection(start=(0, 0), end=(0, 0))
            except Exception:
                pass

    def on_focus(self) -> None:
        """Handle focus event."""
        self.refresh()

    def on_mount(self) -> None:
        """Start autocomplete indexing in background (non-blocking)."""
        self._index_task = asyncio.create_task(self._autocomplete.index())

    def on_unmount(self) -> None:
        """Clean up background tasks."""
        if self._index_task and not self._index_task.done():
            self._index_task.cancel()

    def action_paste_image(self) -> None:
        """Handle Alt+V - paste image/files from system clipboard via PIL."""
        logger.info("ALT_V: Checking system clipboard for image/files")
        self._suppress_paste_text_until = time.time() + 0.3

        try:
            from PIL import ImageGrab
            result = ImageGrab.grabclipboard()

            if result is not None and not isinstance(result, list):
                logger.info("ALT_V: Clipboard has image, attaching")
                self.call_next(lambda r=result: asyncio.create_task(
                    self._attach_clipboard_image(r)
                ))
                return

            if isinstance(result, list):
                logger.info(f"ALT_V: Clipboard has {len(result)} file(s), attaching")
                self.call_next(lambda r=result: asyncio.create_task(
                    self._attach_clipboard_files(r)
                ))
                return
        except Exception as e:
            logger.debug(f"ALT_V: PIL ImageGrab failed: {e}")

        # No image/file found
        self.app.notify("No image in clipboard", severity="warning", timeout=2)

    def on_key(self, event) -> None:
        """Handle Enter to submit, Ctrl+Enter for newline, Alt+V paste, @ autocomplete."""
        logger.debug(f"ON_KEY: key={event.key!r}")

        # Alt+V: paste image/files from system clipboard
        if event.key == "alt+v":
            event.prevent_default()
            event.stop()
            self.action_paste_image()
            return

        # If autocomplete is active, handle navigation first
        if self._autocomplete_active:
            if event.key == "escape":
                self._hide_autocomplete()
                event.prevent_default()
                return

            if event.key == "up":
                self._move_autocomplete_selection(-1)
                event.prevent_default()
                return

            if event.key == "down":
                self._move_autocomplete_selection(1)
                event.prevent_default()
                return

            if event.key in ("tab", "enter"):
                self._accept_autocomplete()
                event.prevent_default()
                return

            # Backspace might delete @, check if we should hide
            if event.key == "backspace":
                # Let the backspace happen, then check position
                self.call_after_refresh(self._check_autocomplete_position)

        # Up arrow at first position -> navigate to attachment bar
        if event.key == "up" and not self._autocomplete_active:
            row, col = self.cursor_location
            if row == 0 and col == 0 and self.attachments.count > 0:
                self._focus_attachment_bar()
                event.prevent_default()
                return

        # Ctrl+Enter OR Ctrl+J = newline (Ctrl+J is universal fallback)
        if event.key in ("ctrl+enter", "ctrl+j"):
            event.prevent_default()
            self._insert_newline()
            return

        # Enter = submit (prevent default newline behavior)
        if event.key == "enter":
            event.prevent_default()
            self.action_submit()
            return

    def on_text_area_changed(self, event) -> None:
        """Handle text changes for @ autocomplete trigger."""
        text = self.text

        # Note: Height auto-resize is handled by CSS (height: auto, min-height, max-height)
        # Do NOT manually set height here - it causes crashes during Ctrl+Z undo

        try:
            cursor_pos = self.cursor_location[1]  # Column position
        except (ValueError, IndexError):
            # Cursor position invalid during undo - skip autocomplete check
            return

        # Check if we just typed @
        if text and cursor_pos > 0:
            # Find last @ before cursor
            text_before_cursor = text[:cursor_pos] if cursor_pos <= len(text) else text
            at_pos = text_before_cursor.rfind("@")

            if at_pos >= 0:
                # Check if @ is at word boundary (start of text or after space)
                if at_pos == 0 or text_before_cursor[at_pos - 1] in " \n\t":
                    # Get query (text after @)
                    query = text_before_cursor[at_pos + 1:]

                    # Don't activate if query contains any whitespace (completed)
                    if not any(c.isspace() for c in query):
                        self._autocomplete_active = True
                        self._autocomplete_start = at_pos
                        self._show_autocomplete_suggestions(query)
                        return

        # No valid @ context - hide autocomplete
        if self._autocomplete_active:
            self._hide_autocomplete()

    def _show_autocomplete_suggestions(self, query: str) -> None:
        """Show autocomplete dropdown with suggestions."""
        if not self._autocomplete._indexed:
            try:
                dropdown = self.app.query_one("#autocomplete", AutocompleteDropdown)
                dropdown.show_message("Indexing files...")
            except Exception:
                pass
            return

        suggestions = self._autocomplete.suggest(query)
        try:
            dropdown = self.app.query_one("#autocomplete", AutocompleteDropdown)
            if suggestions:
                dropdown.show(suggestions)
            else:
                dropdown.hide()
                self._autocomplete_active = False
        except Exception as e:
            logger.debug(f"Failed to show autocomplete suggestions: {e}")

    def _hide_autocomplete(self) -> None:
        """Hide the autocomplete dropdown."""
        self._autocomplete_active = False
        try:
            dropdown = self.app.query_one("#autocomplete", AutocompleteDropdown)
            dropdown.hide()
        except Exception as e:
            logger.debug(f"Failed to hide autocomplete dropdown: {e}")

    def _move_autocomplete_selection(self, delta: int) -> None:
        """Move autocomplete selection up/down."""
        try:
            dropdown = self.app.query_one("#autocomplete", AutocompleteDropdown)
            dropdown.move_selection(delta)
        except Exception as e:
            logger.debug(f"Failed to move autocomplete selection: {e}")

    def _accept_autocomplete(self) -> None:
        """Accept the selected autocomplete suggestion."""
        try:
            dropdown = self.app.query_one("#autocomplete", AutocompleteDropdown)
            selected = dropdown.get_selected()
            if selected:
                self._insert_autocomplete(selected.path)
            dropdown.hide()
        except Exception as e:
            logger.debug(f"Failed to accept autocomplete selection: {e}")
        self._autocomplete_active = False

    def _insert_autocomplete(self, path: str) -> None:
        """Insert the selected file path."""
        # Replace @query with @path
        text = self.text
        cursor_pos = self.cursor_location[1]

        # Find where the @ query ends (current cursor position)
        before_at = text[:self._autocomplete_start]
        after_cursor = text[cursor_pos:] if cursor_pos < len(text) else ""

        # Build new text: before @ + @path + space + after cursor
        new_text = before_at + "@" + path + " " + after_cursor
        self.text = new_text

        # Move cursor after the inserted path + space
        new_cursor_pos = len(before_at) + 1 + len(path) + 1
        self.move_cursor((0, new_cursor_pos))

    def _check_autocomplete_position(self) -> None:
        """Check if @ is still valid after backspace."""
        text = self.text
        if self._autocomplete_start >= len(text) or text[self._autocomplete_start] != "@":
            self._hide_autocomplete()

    def _insert_newline(self) -> None:
        """Insert newline at cursor position using Textual's insert() for proper undo support.

        Note: We use self.insert() exclusively because it properly integrates with
        Textual's undo/redo history. Manual text manipulation (self.text = ...)
        breaks Ctrl+Z because the cursor position becomes out of sync.
        """
        try:
            self.insert("\n")
        except Exception as e:
            # Log but don't fall back to manual manipulation - it breaks undo
            self.app.notify(f"Newline insert failed: {e}", severity="warning")

    def action_submit(self) -> None:
        """Submit the message with any attachments."""
        text = self.text.strip()
        attachments = self.attachments.attachments

        if text or attachments:
            self.post_message(InputSubmittedMessage(text, attachments=attachments))
            self.text = ""
            # Height auto-resets via CSS (height: auto)
            self.attachments.clear()
            self._update_attachment_indicator()

    async def _attach_image_bytes(self, image_bytes: bytes) -> None:
        """Attach image from clipboard bytes."""
        try:
            att = self.attachments.add_screenshot(image_bytes, "png")
            self.app.notify(f"Attached image ({att.size_kb:.1f} KB)")
            self._update_attachment_indicator()
        except Exception as e:
            logger.error(f"Failed to attach image: {e}", exc_info=True)
            self.app.notify(f"Failed to attach image: {e}", severity="error")

    async def _attach_clipboard_image(self, image) -> None:
        """Attach PIL Image from clipboard (called from on_key with PIL result)."""
        try:
            from io import BytesIO
            output = BytesIO()
            if hasattr(image, 'mode') and image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
            image.save(output, format='PNG')
            att = self.attachments.add_screenshot(output.getvalue(), "png")
            self.app.notify(f"Attached image ({att.size_kb:.1f} KB)")
            self._update_attachment_indicator()
        except Exception as e:
            logger.error(f"Failed to attach clipboard image: {e}", exc_info=True)
            self.app.notify(f"Failed to attach image: {e}", severity="error")

    async def on_paste(self, event: Paste) -> None:
        """Handle paste events from terminal emulator.

        On Windows Terminal, Ctrl+V is intercepted by the terminal and sent
        as a Paste event (text only). We must prevent TextArea's default
        _on_paste from also inserting text, and check PIL for images/files.
        """
        # CRITICAL: stop TextArea's _on_paste from also inserting the text
        event.prevent_default()
        event.stop()

        logger.info(f"ON_PASTE: Terminal paste event - text_len={len(event.text) if event.text else 0}")

        # Guard: prevent double-insert when a previous handler already inserted.
        if time.time() < self._suppress_paste_text_until:
            logger.info("ON_PASTE: Suppressed - paste already handled")
            return

        # In many terminals Ctrl+V maps to a Paste event; attempt image/file attach first.
        image_bytes, file_list, _text = ClipboardHandler.get_clipboard_content()
        logger.info(
            "ON_PASTE: ClipboardHandler returned - "
            f"image={bool(image_bytes)}, files={bool(file_list)}"
        )

        if image_bytes:
            # Suppress any immediately-following Paste event that contains text.
            self._suppress_paste_text_until = time.time() + 0.2
            self.call_next(lambda: asyncio.create_task(self._attach_image_bytes(image_bytes)))
            return

        if file_list:
            self._suppress_paste_text_until = time.time() + 0.2
            self.call_next(lambda: asyncio.create_task(self._attach_clipboard_files(file_list)))
            return

        # For terminal-initiated pastes, check if it looks like file paths
        if event.text:
            lines = event.text.strip().split('\n')
            # If all lines look like Windows file paths, try to attach them
            if all(line.strip() and (':' in line or line.startswith('\\\\')) for line in lines if line.strip()):
                logger.info("ON_PASTE: Text looks like file paths, attempting to attach")
                from pathlib import Path
                file_paths = [line.strip() for line in lines if line.strip()]
                valid_files = [f for f in file_paths if Path(f).exists() and Path(f).is_file()]

                if valid_files:
                    self._suppress_paste_text_until = time.time() + 0.2
                    self.call_next(lambda: asyncio.create_task(self._attach_clipboard_files(valid_files)))
                    return

            # Regular text - insert it
            logger.info(f"ON_PASTE: Inserting text ({len(event.text)} chars)")
            self._suppress_paste_text_until = time.time() + 0.2
            self.insert(event.text)

    async def _attach_clipboard_files(self, files: list) -> None:
        """Attach files from clipboard file list."""
        from pathlib import Path
        valid_count = 0

        for file_path in files[:5]:  # Limit to 5 files
            if isinstance(file_path, str) and Path(file_path).exists() and Path(file_path).is_file():
                try:
                    att = await self.attachments.add_file(file_path)
                    if att.kind == "image":
                        self.app.notify(f"Attached image ({att.size_kb:.1f} KB)")
                    else:
                        self.app.notify(f"Attached: {att.filename}")
                    valid_count += 1
                except (OSError, ValueError, FileNotFoundError) as e:
                    logger.error(f"Failed to attach {file_path}: {e}", exc_info=True)
                    self.app.notify(f"Failed: {e}", severity="error")

        if valid_count == 0 and files:
            self.app.notify("No valid files found in clipboard", severity="warning")

        self._update_attachment_indicator()

    def _update_attachment_indicator(self) -> None:
        """Update attachment bar and clear border title (bar handles display now)."""
        # Clear border title - AttachmentBar handles display
        self.border_title = ""
        # Update the AttachmentBar widget
        try:
            bar = self.app.query_one("#attachment-bar", AttachmentBar)
            bar.update_attachments(self.attachments.attachments)
        except Exception as e:
            logger.debug(f"Failed to update attachment bar: {e}")

    def _focus_attachment_bar(self) -> None:
        """Focus the attachment bar for navigation."""
        try:
            bar = self.app.query_one("#attachment-bar", AttachmentBar)
            bar.focus()
        except Exception as e:
            logger.debug(f"Failed to focus attachment bar: {e}")


class CodingAgentApp(App):
    """
    Main TUI application for the coding agent.

    Layout:
    ┌─────────────────────────────────────────┐
    │  Header (optional)                      │
    ├─────────────────────────────────────────┤
    │  ScrollableContainer (conversation)     │
    │   ├── MessageWidget (user)              │
    │   └── MessageWidget (assistant)         │
    │        ├── Markdown                     │
    │        ├── CodeBlock                    │
    │        └── ToolCard                     │
    ├─────────────────────────────────────────┤
    │  ChatInput (input area)                 │
    ├─────────────────────────────────────────┤
    │  StatusBar                              │
    └─────────────────────────────────────────┘

    Usage:
        # With a stream handler function
        async def stream_handler(user_input: str, ui: UIProtocol) -> AsyncIterator[UIEvent]:
            # Your agent logic here
            yield StreamStart()
            yield TextDelta(content="Hello!")
            yield StreamEnd()

        app = CodingAgentApp(stream_handler=stream_handler, model_name="claude-3-opus")
        app.run()
    """

    CSS_PATH = Path(__file__).parent / "styles.tcss"

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", show=True, priority=True),
        Binding("ctrl+d", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=False),
        Binding("f2", "toggle_mode", "Mode", show=True),
        Binding("ctrl+t", "toggle_todos", "Todos", show=False),
        Binding("ctrl+w", "debug_widgets", "Debug", show=False),  # Debug: count widgets
        # Scroll bindings for conversation area
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("ctrl+up", "scroll_up", "Scroll Up", show=False),
        Binding("ctrl+down", "scroll_down", "Scroll Down", show=False),
        Binding("ctrl+home", "scroll_home", "Top", show=False),
        Binding("ctrl+end", "scroll_end", "Bottom", show=False),
    ]

    TITLE = "AI Coding Agent"

    # Maximum retry attempts for recoverable errors
    MAX_RETRIES = 3

    def __init__(
        self,
        agent: "CodingAgent | None" = None,
        stream_handler: Callable[[str, UIProtocol], AsyncIterator[UIEvent]] | None = None,
        model_name: str = "claude-3-opus",
        show_header: bool = False,
        subagent_registry: Optional["SubagentRegistry"] = None,
        **kwargs
    ):
        """
        Initialize the application.

        Args:
            agent: CodingAgent instance (recommended). If provided, stream_handler
                  is created automatically using agent.stream_response().
            stream_handler: Async function that takes (user_input, ui_protocol)
                           and yields UIEvents. Alternative to providing agent directly.
            model_name: Name of the LLM model for status bar. If agent is provided,
                       this is extracted from the agent.
            show_header: Whether to show the header bar
            subagent_registry: Optional registry for subagent visibility.
                              When provided, subagent progress is displayed in TUI.
            **kwargs: Additional arguments for App

        Note:
            Either `agent` or `stream_handler` must be provided. If both are given,
            `agent` takes precedence.
        """
        super().__init__(**kwargs)
        self.agent = agent
        self.show_header = show_header
        self.ui_protocol = UIProtocol()

        # Determine model name
        if agent:
            self.model_name = agent.model_name
        else:
            self.model_name = model_name

        # Create stream_handler from agent if provided
        if agent:
            self.stream_handler = self._create_agent_stream_handler(agent)
        elif stream_handler:
            self.stream_handler = stream_handler
        else:
            # Setup mode: no agent yet, wizard will be shown on mount
            self.stream_handler = None

        # Streaming state
        self._is_streaming = False
        self._streaming_task: asyncio.Task | None = None
        self._stream_worker: Worker | None = None  # Textual worker for streaming
        self._stream_id: int = 0  # Monotonic counter to detect stale events after restart/interrupt
        self._user_interrupt_requested: bool = False  # True only when user explicitly interrupts (Ctrl+C)
        self._current_message: MessageWidget | None = None
        self._current_code: CodeBlock | None = None
        self._current_thinking: ThinkingBlock | None = None
        self._tool_cards: dict[str, ToolCard] = {}

        # Scroll state: _auto_scroll is True when user hasn't explicitly scrolled away.
        # Reset to True on new message submission and action_scroll_end.
        # Set to False by keyboard scroll-up actions.
        # Mouse wheel scrolls are handled by checking is_vertical_scroll_end at scroll time.
        self._auto_scroll = True

        # Retry state
        self._last_user_input: str = ""
        self._last_attachments: list[Attachment] = []
        self._retry_count: int = 0

        # Track pending approvals to manage focus
        self._pending_approval_ids: set[str] = set()

        # Track pause widget
        self._pause_widget: PausePromptWidget | None = None

        # Track clarify widget
        self._clarify_widget: ClarifyWidget | None = None

        # Track plan approval widget
        self._plan_approval_widget: PlanApprovalWidget | None = None

        # Cache conversation reference (avoid repeated query_one per flush)
        self._conversation: ConversationContainer | None = None

        # Cache status bar reference (Fix #3: avoid query_one in hot path)
        self._status_bar: StatusBar | None = None

        # Throttle status bar updates (Fix #3: time-based throttling)
        self._last_status_update_ts: float = 0.0
        self._status_update_interval_sec: float = 0.2  # Update at most every 200ms

        # Director mode: pending activation (user typed /director with no task)
        self._director_pending: bool = False

        # Phase 6: Store-driven rendering
        # TUI renders from MessageStore notifications. UIEvents are forwarded
        # to StoreAdapter for persistence; store notifications handle rendering.
        self._message_store: MessageStore | None = None
        self._store_adapter: StoreAdapter | None = None  # Bridges UIEvents to store
        self._store_unsubscribe: Callable[[], None] | None = None
        self._store_message_widgets: dict[str, MessageWidget] = {}  # stream_id -> widget
        self._store_rendered_segment_idx: dict[str, int] = {}  # stream_id -> last rendered segment index
        self._is_replaying: bool = False  # True during BULK_LOAD (replay mode)
        self._pre_mounted_user_widget: MessageWidget | None = None  # Eagerly-mounted UserMessage
        self._session_id: str | None = None  # Current session ID for persistence
        self._session_writer = None  # SessionWriter, opened in on_mount

        # PR4: Store update coalescing (prevents UI flicker during streaming)
        self._store_pending_updates: dict[str, Message] = {}  # stream_id -> latest message

        # Buffered file-read notes: FileReadEvents arrive before UserMessage widget
        # is mounted (store notification chain is async). We buffer them and flush
        # when StreamStart arrives, by which point UserMessage is guaranteed mounted.
        self._pending_file_read_events: list = []
        self._store_update_timer: asyncio.TimerHandle | None = None
        self._store_update_interval_sec: float = 0.15  # Coalesce updates within 150ms

        # Render metadata registry (ephemeral approval policy hints)
        # Injected via set_render_meta_registry(), queried when creating tool cards
        self._render_meta: RenderMetaRegistry | None = None

        # Segmented streaming: accumulate text until boundary (tool/code/thinking/end)
        self._segment_chunks: list[str] = []  # Current segment accumulator
        self._segment_chars: int = 0          # For status bar display
        self._segment_flush_handle: asyncio.TimerHandle | None = None  # Timer for delayed flush
        self._segment_flush_interval_sec: float = 0.5  # Flush after 0.5s (Fix #4: faster feedback)
        self._segment_flush_running: bool = False  # Prevent overlapping flushes (Fix #4)

        # Subagent visibility: registry + coordinator (extracted Phase 5)
        self._subagent_registry: SubagentRegistry | None = subagent_registry
        self._subagent_coordinator = SubagentCoordinator(
            tool_cards=self._tool_cards,
            mount_callback=self.call_later,
        )
        # Backward-compat aliases (used by on_unmount, action_interrupt, etc.)
        self._subagent_subscriptions = self._subagent_coordinator.subscriptions

        # Setup mode: when agent=None, TUI shows config wizard on mount
        self._pending_llm_config = None  # Set by cli.py before app.run()

        # Segment renderer (extracted from app.py - Phase 2)
        self._segment_renderer = SegmentRenderer(
            tool_cards=self._tool_cards,
            message_store=self._message_store,
            silent_tools=SILENT_TOOLS,
            is_replaying_fn=lambda: self._is_replaying,
            on_tool_card_created=self._on_tool_card_created,
        )

        # Store renderer (extracted from app.py - Phase 3)
        self._store_renderer = StoreRenderer(
            segment_renderer=self._segment_renderer,
            tool_cards=self._tool_cards,
            message_store=self._message_store,
            store_message_widgets=self._store_message_widgets,
            store_rendered_segment_idx=self._store_rendered_segment_idx,
            silent_tools=SILENT_TOOLS,
            on_clarify_request=self._on_clarify_request,
            on_plan_approval=self.mount_plan_approval,
            on_tool_card_created=self._on_tool_card_created,
            scroll_to_bottom=self._scroll_to_bottom,
        )

    def _create_agent_stream_handler(
        self,
        agent: "CodingAgent"
    ) -> Callable[[str, UIProtocol, list[Attachment] | None], AsyncIterator[UIEvent]]:
        """
        Create a stream_handler function that wraps agent.stream_response().

        This bridges the agent's stream_response() method to the stream_handler
        interface expected by the app.

        Args:
            agent: CodingAgent instance

        Returns:
            Async function that yields UIEvents
        """
        async def handler(
            user_input: str,
            ui: UIProtocol,
            attachments: list[Attachment] | None = None
        ) -> AsyncIterator[UIEvent]:
            async for event in agent.stream_response(user_input, ui, attachments):
                yield event

        return handler

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        if self.show_header:
            yield Header()

        yield ConversationContainer(id="conversation")
        yield AutocompleteDropdown(id="autocomplete")
        yield AttachmentBar(id="attachment-bar")
        yield TodoBar(id="todo-bar")  # Above status bar, hidden until todos exist
        yield StatusBar(model_name=self.model_name, id="status")
        yield ChatInput(id="input")
        yield Footer()

    def get_system_commands(self, screen):
        """Add custom commands to the command palette (Ctrl+P)."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Configure LLM",
            "Set up LLM backend, model, and subagent models",
            self.action_configure_llm,
        )
        yield SystemCommand(
            "Configure Jira",
            "Set up Jira connection profiles (URL, username, API token)",
            self.action_configure_jira,
        )

    def action_configure_llm(self) -> None:
        """Open the LLM configuration wizard."""
        from .llm_config_screen import ConfigLLMScreen

        # Get subagent names from the already-loaded agent config
        subagent_names = []
        if self.agent and hasattr(self.agent, 'subagent_manager'):
            try:
                subagent_names = list(
                    self.agent.subagent_manager.config_loader.loaded_configs.keys()
                )
            except Exception:
                pass

        self.push_screen(
            ConfigLLMScreen(subagent_names=subagent_names),
            callback=self._on_llm_configured,
        )

    def action_configure_jira(self) -> None:
        """Open the Jira configuration screen."""
        from .jira_config_screen import ConfigJiraScreen

        # Detect which Jira profile is currently connected (if any)
        connected_profile = None
        if self.agent:
            conn = self.agent._mcp_manager.get_connection("jira")
            if conn:
                # Extract profile from server name "mcp-atlassian-<profile>"
                connected_profile = conn.config.name.replace("mcp-atlassian-", "")

        self.push_screen(
            ConfigJiraScreen(connected_profile=connected_profile),
            callback=self._on_jira_configured,
        )

    def _on_jira_configured(self, result) -> None:
        """Handle result from the Jira config screen."""
        if result is None:
            return

        if result.disconnect:
            # "Disconnect" was pressed
            self.run_worker(
                self._disconnect_jira(),
                exclusive=False,
                group="jira",
            )
        else:
            # "Save & Connect" was pressed -- trigger connection
            self.run_worker(
                self._connect_jira(profile=result.profile),
                exclusive=False,
                group="jira",
            )

    def _show_setup_wizard(self) -> None:
        """Auto-present the LLM config wizard in setup mode."""
        from .llm_config_screen import ConfigLLMScreen

        self.push_screen(
            ConfigLLMScreen(),
            callback=self._on_llm_configured,
        )

    def _on_llm_configured(self, result) -> None:
        """Handle result from the LLM config wizard.

        When in setup mode (agent was None), initializes a real agent
        from the saved config and wires it into the app.
        """
        if result is None:
            if self.agent is None:
                # User cancelled the wizard in setup mode -- exit the app
                self.notify("LLM configuration required. Exiting.", severity="warning")
                self.set_timer(1.0, lambda: self.exit())
            return

        self.notify("LLM configuration saved to .clarity/config.yaml")

        # If agent already exists, config was just updated (not setup mode)
        if self.agent is not None:
            self.notify(
                "Config updated. Please restart the app for changes to take effect.",
                severity="information",
                timeout=8.0
            )
            return

        # Setup mode: create agent from saved config
        self._initialize_agent_from_config(result)

    def _initialize_agent_from_config(self, config) -> None:
        """Create a CodingAgent from saved LLMConfigData and wire it into the app.

        Args:
            config: LLMConfigData from the wizard
        """
        from src.core.agent import CodingAgent

        try:
            # Resolve API key
            api_key = (
                config.api_key
                or os.environ.get(config.api_key_env, "")
            )

            agent = CodingAgent.from_config(
                config,
                api_key=api_key,
                session_id=self._session_id,
                message_store=self._message_store,
            )

            # Wire agent into the app
            self.agent = agent
            self.model_name = agent.model_name
            self.stream_handler = self._create_agent_stream_handler(agent)

            # Wire render meta registry
            self.set_render_meta_registry(agent.memory.render_meta)

            # Update status bar
            if self._status_bar:
                self._status_bar.set_mode(agent.get_permission_mode())
                self._status_bar.set_model(self.model_name)

            # Set up subagent registry
            self._setup_subagent_registry()

            self.notify(
                f"Agent ready: {config.model} via {config.backend_type}",
                severity="information",
            )
            logger.info(f"Agent initialized from wizard: model={config.model}")

        except Exception as e:
            logger.error(f"Failed to initialize agent from config: {e}")
            self.notify(
                f"Failed to initialize agent: {e}",
                severity="error",
            )

    def on_mount(self) -> None:
        """Focus input on start and initialize mode display."""
        # Set terminal tab title safely through Textual's rendering pipeline
        self.console.set_window_title("ClarAIty")

        # Install asyncio exception handler to capture unhandled task exceptions
        try:
            import asyncio

            from src.observability.logging_config import install_asyncio_handler
            loop = asyncio.get_running_loop()
            install_asyncio_handler(loop)
        except Exception:
            pass  # Graceful degradation if observability not available

        # Phase 6: Open session writer within Textual's event loop
        if self._session_writer:
            asyncio.create_task(self._open_session_writer())

        # Cache status bar reference (Fix #3: avoid query_one in hot path)
        try:
            self._status_bar = self.query_one("#status", StatusBar)
        except NoMatches:
            self._status_bar = None

        # Use call_after_refresh to ensure focus happens after layout is complete
        self.call_after_refresh(self._focus_input)

        # Initialize mode display from agent
        if self.agent and self._status_bar:
            self._status_bar.set_mode(self.agent.get_permission_mode())

        # Register todos callback for TodoBar and StatusBar updates
        self.ui_protocol.set_todos_callback(self._on_todos_updated)

        # Register background task completion callback for StatusBar BG badge
        if self.agent:
            self.agent._bg_registry.set_completion_callback(self._on_bg_task_update)

        # Create and wire subagent registry for live visibility
        self._setup_subagent_registry()

        # Setup mode: auto-present config wizard when no agent is configured
        if self.agent is None:
            self.call_after_refresh(self._show_setup_wizard)

        # Note: Signal handlers for SIGINT on Windows with asyncio are problematic.
        # We rely on Textual's Ctrl+C binding (action_interrupt) and the outer
        # try/except KeyboardInterrupt wrapper instead.

    def on_unmount(self) -> None:
        """Cleanup on app exit."""
        # Phase 6: Close session writer
        if self._session_writer:
            import asyncio
            try:
                # Schedule async close - may not complete if app exits quickly
                asyncio.create_task(self._close_session_writer())
            except RuntimeError:
                pass  # No running loop

        # Cleanup subagent coordinator (registry + store subscriptions)
        self._subagent_coordinator.cleanup()

        # Log cache summary (avoid full agent.shutdown() during event loop teardown)
        if self.agent and hasattr(self.agent, 'llm') and hasattr(self.agent.llm, 'log_cache_summary'):
            self.agent.llm.log_cache_summary()

        # Synchronously kill MCP subprocesses (event loop may be closed)
        if self.agent and self.agent._mcp_manager.has_connections:
            self.agent._mcp_manager.shutdown_sync()

    # ---- Subagent lifecycle (delegated to SubagentCoordinator - Phase 5) ----

    def _setup_subagent_registry(self) -> None:
        """Set up subagent registry for live visibility."""
        if self._subagent_registry is None and self.agent:
            from .subagent_registry import SubagentRegistry
            self._subagent_registry = SubagentRegistry(app=self)
            logger.info("Created SubagentRegistry for TUI visibility")

        if self._subagent_registry:
            self._subagent_coordinator.setup_registry(
                registry=self._subagent_registry,
                agent=self.agent,
                ui_protocol=self.ui_protocol,
                pause_callback=self._on_subagent_pause_requested,
            )

    async def _on_subagent_pause_requested(
        self, reason: str, reason_code: str,
        pending_todos: list | None, stats: dict | None,
    ) -> None:
        """Mount PausePromptWidget when a subagent requests a pause."""
        try:
            conversation = self._conversation or self.query_one("#conversation", ConversationContainer)
        except NoMatches:
            logger.warning("No conversation container found for subagent pause widget")
            return

        if self._pause_widget:
            self._pause_widget.remove()
            self._pause_widget = None

        widget = PausePromptWidget(
            reason=reason, reason_code=reason_code,
            pending_todos=pending_todos or [], stats=stats or {},
        )
        self._pause_widget = widget
        await conversation.mount(widget)
        widget.scroll_visible()

    def _focus_input(self) -> None:
        """Set focus to input widget."""
        try:
            input_widget = self.query_one("#input", ChatInput)
            input_widget.focus()
        except Exception as e:
            self.log.error(f"Failed to focus input: {e}")

    def _on_tool_card_created(self, tool_call_id: str, tool_card: ToolCard) -> None:
        """Delegate to SubagentCoordinator.on_tool_card_created()."""
        self._subagent_coordinator.on_tool_card_created(tool_call_id, tool_card)

    # -------------------------------------------------------------------------
    # Input Handling
    # -------------------------------------------------------------------------

    async def on_input_submitted_message(self, message: InputSubmittedMessage) -> None:
        """Handle user input submission."""
        user_input = message.content.strip()
        attachments = message.attachments  # Extract attachments from message

        # Allow submission if there's text OR attachments
        if not user_input and not attachments:
            return

        # CRITICAL: Prevent concurrent streams
        if self._is_streaming:
            # Ignore input while streaming - input should be disabled anyway
            self.log.warning("Input submitted while streaming - ignoring")
            return

        # Guard: no agent configured yet
        if self.stream_handler is None:
            self.notify(
                "No LLM configured. Use Ctrl+P > 'Configure LLM' to set up.",
                severity="warning",
            )
            return

        # Handle /director command (activate director, strip prefix, send task as message)
        if user_input.lower().startswith("/director") and not user_input.lower().startswith("/director-"):
            task = user_input[len("/director"):].strip()
            if not task:
                # Bare /director -- activate pending mode, wait for next message as task
                self._director_pending = True
                self.notify("Director mode ready. Type your task to begin.")
                try:
                    status_bar = self.query_one("#status", StatusBar)
                    status_bar.set_director_phase("READY")
                except Exception:
                    pass
                return
            if self.agent:
                self.agent.director_adapter.start(task)
                self._director_pending = False
                self.notify("Director mode: UNDERSTAND phase")
                try:
                    status_bar = self.query_one("#status", StatusBar)
                    status_bar.set_director_phase("UNDERSTAND")
                except Exception:
                    pass
                user_input = task  # Strip prefix, fall through to send as message

        # Handle pending director activation -- next message becomes the task
        if self._director_pending and self.agent and not user_input.startswith("/"):
            self.agent.director_adapter.start(user_input)
            self._director_pending = False
            self.notify("Director mode: UNDERSTAND phase")
            try:
                status_bar = self.query_one("#status", StatusBar)
                status_bar.set_director_phase("UNDERSTAND")
            except Exception:
                pass
            # Fall through to send as message

        # Handle slash commands
        if user_input.startswith("/"):
            handled = await self._handle_slash_command(user_input)
            if handled:
                return

        # Store for potential retry
        self._last_user_input = user_input
        self._last_attachments = attachments  # Store attachments for retry

        # Re-enable auto-scroll on new message (user expects to follow the response)
        self._auto_scroll = True

        # Mount user message immediately (no store round-trip)
        attachment_summary = ""
        if attachments:
            parts = [f"[{a.kind.upper()}: {a.filename}]" for a in attachments]
            attachment_summary = " " + " ".join(parts)
        try:
            conversation = self.query_one("#conversation", ConversationContainer)
            user_widget = UserMessage(content=user_input + attachment_summary)
            await conversation.mount(user_widget)
            self._pre_mounted_user_widget = user_widget
            self._scroll_to_bottom(conversation)
        except NoMatches:
            pass

        # Start streaming response in a worker - DO NOT await here!
        # This allows Textual to keep processing key events and messages
        # while the stream runs (fixes approval widget keyboard issue)
        self._stream_worker = self.run_worker(
            self._stream_response(user_input, attachments),
            exclusive=True,
            group="stream",
            name="stream-response",
        )

    async def _add_user_message(self, content: str) -> None:
        """Add user message to conversation.

        Store-driven rendering: only adds to store and lets the store
        notification handle rendering.

        When agent is present, the agent adds user messages via
        MemoryManager.add_user_message() during stream_response().
        We skip adding here to avoid duplicate store notifications.
        """
        # Agent adds user message via MemoryManager -- store notification renders
        if self.agent:
            return

        # No agent case: add to store, store notification handles rendering
        if self._store_adapter:
            try:
                self._store_adapter.add_user_message(content)
            except Exception as e:
                logger.warning(f"Failed to add user message to store: {e}")

    # -------------------------------------------------------------------------
    # Attachment Bar Handlers
    # -------------------------------------------------------------------------

    def on_attachment_bar_attachment_removed(self, message: AttachmentBar.AttachmentRemoved) -> None:
        """Handle attachment removal from AttachmentBar."""
        try:
            input_widget = self.query_one("#input", ChatInput)
            input_widget.attachments.remove(message.index)
            input_widget._update_attachment_indicator()
            self.notify("Attachment removed")
        except Exception as e:
            self.log.error(f"Failed to remove attachment: {e}")

    def on_attachment_bar_exit_to_input(self, message: AttachmentBar.ExitToInput) -> None:
        """Handle request to return focus to input."""
        self._focus_input()

    # -------------------------------------------------------------------------
    # Slash Commands (routing extracted to SlashCommandDispatcher - Phase 4)
    # -------------------------------------------------------------------------

    def _build_slash_dispatcher(self):
        """Build the slash command dispatcher with current handler references."""
        from .slash_commands import SlashCommandDispatcher

        async def _do_configure_llm():
            self.action_configure_llm()

        async def _do_configure_jira():
            self.action_configure_jira()

        async def _do_disconnect_jira():
            self.run_worker(self._disconnect_jira(), exclusive=False, group="jira")

        async def _do_director_reset():
            if self.agent:
                self.agent.director_adapter.reset()
            self.notify("Director mode reset")
            try:
                status_bar = self.query_one("#status", StatusBar)
                status_bar.clear_director_phase()
            except Exception:
                pass

        async def _do_connect_jira(command: str):
            parts = command.strip().split(maxsplit=1)
            profile = parts[1].strip() if len(parts) > 1 else None
            self.run_worker(
                self._connect_jira(profile=profile), exclusive=False, group="jira"
            )

        return SlashCommandDispatcher(
            commands={
                "/new": self._reset_session,
                "/resume": self._show_session_picker,
                "/config-llm": _do_configure_llm,
                "/config-jira": _do_configure_jira,
                "/disconnect-jira": _do_disconnect_jira,
                "/director-reset": _do_director_reset,
            },
            prefix_commands={
                "/connect-jira": _do_connect_jira,
            },
        )

    async def _handle_slash_command(self, command: str) -> bool:
        """Route slash commands via the dispatcher."""
        if not hasattr(self, '_slash_dispatcher') or self._slash_dispatcher is None:
            self._slash_dispatcher = self._build_slash_dispatcher()
        return await self._slash_dispatcher.dispatch(command)

    async def _connect_jira(self, profile: str = None) -> None:
        """Connect to Jira via mcp-atlassian MCP server.

        Args:
            profile: Named profile to connect (e.g. "personal", "corporate").
                     If None, auto-selects when only one profile exists.
        """
        if not self.agent:
            self.notify("No agent available", severity="error")
            return

        try:
            from src.integrations.jira.connection import JiraConnection
            from src.integrations.jira.tools import create_jira_policy_gate
            from src.integrations.mcp.client import McpClient, StdioTransport
            from src.integrations.mcp.registry import McpToolRegistry

            # Resolve which profile to use
            if profile is None:
                profiles = JiraConnection.list_profiles()
                if len(profiles) == 0:
                    self.notify(
                        "No Jira profiles found. Opening configuration...",
                        severity="warning",
                    )
                    self.action_configure_jira()
                    return
                if len(profiles) == 1:
                    profile = profiles[0]
                else:
                    profiles_str = ", ".join(profiles)
                    self.notify(
                        f"Multiple profiles found: {profiles_str}. "
                        f"Use /connect-jira <profile> to specify one.",
                        severity="warning",
                    )
                    return

            conn = JiraConnection(profile=profile)
            if not conn.is_configured():
                self.notify(
                    f"Jira profile '{profile}' incomplete. Opening configuration...",
                    severity="warning",
                )
                from .jira_config_screen import ConfigJiraScreen
                self.push_screen(
                    ConfigJiraScreen(profile=profile),
                    callback=self._on_jira_configured,
                )
                return

            # Auto-disconnect existing Jira connection before connecting new profile
            existing = self.agent._mcp_manager.get_connection("jira")
            if existing:
                await self.agent.disable_mcp_integration("jira")

            self.notify(f"Connecting to Jira ({profile})...")

            config = conn.get_mcp_config()
            transport = StdioTransport()
            client = McpClient(config, transport)
            policy_gate = create_jira_policy_gate()
            registry = McpToolRegistry(config, policy_gate)

            import asyncio as _asyncio
            count = await _asyncio.wait_for(
                self.agent.enable_mcp_integration("jira", registry, client),
                timeout=120,
            )
            self.notify(
                f"Jira ({profile}) connected: {count} tools available",
                severity="information",
                timeout=10,
            )
        except TimeoutError:
            self.notify(
                "Jira connection timed out (120s). Is mcp-atlassian installed?",
                severity="error",
            )
        except Exception as e:
            self.notify(f"Jira connection failed: {e}", severity="error")

    async def _disconnect_jira(self) -> None:
        """Disconnect from Jira MCP server."""
        if not self.agent:
            self.notify("Jira is not connected", severity="warning")
            return

        try:
            await self.agent.disable_mcp_integration("jira")
            self.notify("Jira disconnected", severity="information")
        except KeyError:
            self.notify("Jira is not connected", severity="warning")
        except Exception as e:
            self.notify(f"Disconnect failed: {e}", severity="error")

    async def _show_session_picker(self) -> None:
        """Show the session picker modal and load selected session."""
        from .session_picker import SessionPickerScreen

        # Determine sessions directory
        sessions_dir = Path(".clarity/sessions")

        def on_session_selected(session_id: str | None) -> None:
            """Callback when session is selected or picker is cancelled."""
            if session_id:
                # Schedule the async load in the app's context
                self.call_later(lambda: self.run_worker(self._load_session(session_id)))

        # Push the session picker screen with callback
        self.push_screen(
            SessionPickerScreen(sessions_dir=sessions_dir),
            callback=on_session_selected
        )

    async def _load_session(self, session_id: str) -> None:
        """
        Load an existing session by ID using SessionHydrator.

        This will:
        1. Close current session writer
        2. Clear current conversation
        3. Hydrate session via agent.resume_session_from_jsonl()
           - Loads JSONL into MessageStore (conversation history)
           - Injects MessageStore into MemoryManager
        4. Enable todo persistence via set_session_id()
           - Loads tasks from todos.json (single source of truth)
        5. Rebind store and writer
        6. Render loaded messages

        Args:
            session_id: Session ID to load
        """
        from src.session.persistence.writer import SessionWriter

        sessions_dir = Path(".clarity/sessions")

        # Find session file
        session_path = sessions_dir / session_id / "session.jsonl"
        if not session_path.exists():
            # Try flat file structure
            session_path = sessions_dir / f"{session_id}.jsonl"

        if not session_path.exists():
            self.notify(f"Session not found: {session_id}", severity="error")
            return

        self.notify("Loading session...", severity="information")

        try:
            # Close current writer if active
            if self._session_writer:
                await self._close_session_writer()

            # Clear current conversation UI
            await self._clear_conversation()

            # Unbind current store
            self.unbind_store()

            # Use agent's hydration method if agent is available
            if self.agent:
                # Hydrate conversation history from JSONL
                result = self.agent.resume_session_from_jsonl(session_path)
                store = result.store

                # Enable todo persistence and load tasks from todos.json
                # (is_new_session=False preserves plan mode state)
                self.agent.set_session_id(session_id, is_new_session=False)

                # Refresh TodoBar and StatusBar with loaded tasks
                todos = self.agent.task_state.get_todos_list()
                if todos:
                    self._on_todos_updated(todos)

                # Log hydration report
                logger.info(f"Session hydrated: {result.report}")
            else:
                # Fallback: direct load without agent state restoration
                from src.session import load_session
                from src.session.store.memory_store import MessageStore
                store = MessageStore()
                load_session(session_path, store)
                logger.warning("No agent available - session loaded without state restoration")

            # Create new writer (appending to existing file)
            writer = SessionWriter(file_path=session_path)

            # Rebind store and writer
            self.bind_store(store, session_id=session_id)
            self._session_writer = writer
            await self._open_session_writer()

            # Render using unified bulk load path (same as replay_session)
            # This ensures consistent segment-based rendering with correct ordering
            self._is_replaying = True
            conversation = self.query_one("#conversation", ScrollableContainer)
            await self._on_store_bulk_load_complete(conversation)

            message_count = store.message_count
            self.notify(f"Loaded session with {message_count} messages", severity="information")

        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            self.notify(f"Failed to load session: {e}", severity="error")

    async def _clear_conversation(self) -> None:
        """Clear all messages from the conversation container."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            # Remove all children
            await conversation.remove_children()
        except NoMatches:
            pass

    async def _reset_session(self) -> None:
        """Start a fresh chat session (New Chat / /new command).

        Preserves agent configuration while clearing all conversation state.
        """
        import uuid as _uuid
        from datetime import datetime
        from pathlib import Path

        from src.session.persistence.writer import SessionWriter
        from src.session.store.memory_store import MessageStore

        if not self.agent:
            self.notify("No agent available", severity="error")
            return

        try:
            # 1. Close current writer
            if self._session_writer:
                await self._close_session_writer()

            # 2. Clear conversation UI
            await self._clear_conversation()

            # 3. Unbind current store
            self.unbind_store()

            # 4. Generate new session ID and path
            new_session_id = (
                f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                f"-{_uuid.uuid4().hex[:8]}"
            )
            session_dir = Path(".clarity/sessions") / new_session_id
            jsonl_path = session_dir / "session.jsonl"

            # 5. Reset core agent state
            self.agent.reset_session(new_session_id)

            # 6. Create new store + writer
            new_store = MessageStore()
            self.agent.memory.set_message_store(new_store, new_session_id)

            writer = SessionWriter(file_path=jsonl_path)

            # 7. Rebind store and writer
            self.bind_store(new_store, session_id=new_session_id)
            self._session_writer = writer
            await self._open_session_writer()

            # 8. Clear todo panel
            self._on_todos_updated([])

            self.notify("New session started", severity="information")
            logger.info(f"TUI session reset to {new_session_id}")

        except Exception as e:
            logger.error(f"Failed to reset session: {e}")
            self.notify(f"Failed to start new session: {e}", severity="error")

    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------

    async def _stream_response(
        self,
        user_input: str,
        attachments: list[Attachment] | None = None
    ) -> None:
        """
        Stream agent response and render events.

        This method runs in a Textual worker (via run_worker), which allows
        Textual's message loop to keep processing keyboard events and widget
        messages while streaming. This is critical for:
        - Tool approval widgets receiving keyboard input
        - Ctrl+C/Escape interrupt working during streaming

        Args:
            user_input: User's text message
            attachments: Optional list of Attachment objects (images, files)
        """
        self._is_streaming = True
        self.ui_protocol.reset()

        # Track current task for potential cancellation
        # (The worker itself is the primary cancellation mechanism now)
        self._streaming_task = asyncio.current_task()

        # Disable input while streaming
        try:
            input_widget = self.query_one("#input", ChatInput)
            input_widget.disabled = True
        except NoMatches:
            input_widget = None

        # Update status bar
        try:
            status_bar = self.query_one("#status", StatusBar)
            status_bar.set_streaming(True)
            status_bar.clear_error()
        except NoMatches:
            status_bar = None

        # Cache conversation reference ONCE (avoid repeated query_one per flush)
        self._conversation = self.query_one("#conversation", ConversationContainer)

        try:
            # Directly await _process_stream (no nested task needed)
            # The worker is the thing to cancel now
            await self._process_stream(user_input, self._conversation, attachments)

            # Success - reset retry count
            self._retry_count = 0

        except asyncio.CancelledError:
            # CancelledError can be caused by:
            # 1. User pressing Ctrl+C (action_interrupt) - should show [Interrupted]
            # 2. Exclusive worker replacement - silent cleanup
            # 3. Internal timeouts - silent cleanup
            if self._user_interrupt_requested:
                # True user interrupt - show [Interrupted]
                # Cancel pending timer before flush
                if self._segment_flush_handle:
                    self._segment_flush_handle.cancel()
                    self._segment_flush_handle = None
                await self._flush_segment()
                if self._current_message:
                    await self._current_message.add_text("\n\n[Interrupted]")
                self.notify("Stream interrupted", severity="information", timeout=2)
            else:
                # Non-user cancellation (exclusive worker replacement / lifecycle)
                # Silent cleanup - no [Interrupted] marker
                self.log("Stream worker cancelled (non-user). Silent cleanup.")
                # Cancel pending timer before flush
                if self._segment_flush_handle:
                    self._segment_flush_handle.cancel()
                    self._segment_flush_handle = None
                await self._flush_segment()

        except KeyboardInterrupt:
            # Ctrl+C raised as exception (common on Windows)
            # Cancel pending timer before flush
            if self._segment_flush_handle:
                self._segment_flush_handle.cancel()
                self._segment_flush_handle = None
            await self._flush_segment()
            if self._current_message:
                await self._current_message.add_text("\n\n[Interrupted by Ctrl+C]")
            self.notify("Stream interrupted by Ctrl+C", severity="information", timeout=2)

        finally:
            # Capture current message to finalize (prevents racing with new stream)
            msg_to_finalize = self._current_message

            # Notify store_adapter that stream ended (prevents "already streaming" warning)
            # This ensures _state is cleared even if StreamEnd event wasn't emitted
            if self._store_adapter:
                self._store_adapter.handle_event(StreamEnd(total_tokens=None, duration_ms=None))

            # Reset all streaming state (Fix #6: ensure clean state for next stream)
            self._is_streaming = False
            self._streaming_task = None
            self._user_interrupt_requested = False  # Reset for next stream
            self._segment_flush_running = False  # Fix #6: always reset flush guard

            # Drain any remaining buffered text before finalizing the widget.
            # Must happen here — live streaming owns the flush, not store notifications.
            if self._segment_flush_handle:
                self._segment_flush_handle.cancel()
                self._segment_flush_handle = None
            await self._flush_segment()

            # Finalize the specific message we captured (not whatever is current now)
            # This prevents clearing a new message if a new stream started during cleanup
            self._finalize_current_message(msg_to_finalize)

            self._conversation = None  # Clear cached reference
            # Clear segment buffers
            self._segment_chunks = []
            self._segment_chars = 0

            if status_bar:
                status_bar.set_streaming(False)

            # Re-enable and re-focus input
            try:
                input_widget = self.query_one("#input", ChatInput)
                input_widget.disabled = False
                input_widget.focus()
            except NoMatches:
                pass

    async def _process_stream(
        self,
        user_input: str,
        conversation: ScrollableContainer,
        attachments: list[Attachment] | None = None
    ) -> None:
        """Process the event stream from the agent."""
        # Increment stream ID to invalidate any stale event handlers from previous stream
        self._stream_id += 1

        try:
            # Call the stream handler with attachments
            event_stream = self.stream_handler(user_input, self.ui_protocol, attachments)

            event_count = 0
            async for event in event_stream:
                event_count += 1

                # CRITICAL: Yield control to event loop EVERY event
                # This allows Textual to process key events (Ctrl+C, Escape, approval keys)
                await asyncio.sleep(0)

                # Check for interrupt BEFORE processing (for faster response)
                if self.ui_protocol.check_interrupted():
                    self.log("Stream interrupted via protocol")
                    break

                self.log(f"Event {event_count}: {type(event).__name__}")
                await self._handle_event(event, conversation)

                # NOTE: scroll_end() removed here for performance
                # Scrolling is now handled by _flush_segment() at controlled intervals

            self.log(f"Stream completed with {event_count} events")

        except KeyboardInterrupt:
            # Ctrl+C during iteration - re-raise to be caught by caller
            self.log("KeyboardInterrupt in _process_stream")
            raise

        except asyncio.CancelledError:
            # Task was cancelled - re-raise to be caught by caller
            self.log("CancelledError in _process_stream")
            raise

        except Exception as e:
            # Log full technical details for debugging
            self.log.error(f"Stream error: {type(e).__name__}: {e}")

            # Generate user-friendly error message (no technical details)
            user_error = _format_user_error(e, include_reference=True)

            # Show error in status bar
            try:
                status_bar = self.query_one("#status", StatusBar)
                status_bar.show_error(user_error)
            except NoMatches:
                pass

            # Flush what we have and show friendly error in UI
            # Cancel pending timer before flush
            if self._segment_flush_handle:
                self._segment_flush_handle.cancel()
                self._segment_flush_handle = None
            await self._flush_segment()
            if self._current_message:
                await self._current_message.add_text(f"\n\n{user_error}")
            else:
                error_widget = AssistantMessage()
                await conversation.mount(error_widget)
                await error_widget.add_text(user_error)

            # Don't re-raise: error is already displayed in UI
            # Re-raising would leak raw traceback to Textual's worker error handler

    async def _handle_event(
        self,
        event: UIEvent,
        conversation: ScrollableContainer
    ) -> None:
        """Forward event to store adapter for persistence.

        All rendering is handled by store subscription notifications.
        ErrorEvents are handled directly since they need UI interaction
        (status bar, retry logic) that the store doesn't handle.
        """
        if self._store_adapter:
            try:
                self._store_adapter.handle_event(event)
            except Exception as e:
                logger.warning(f"Store adapter error: {e}")

        # ErrorEvents need direct UI handling (retry, status bar)
        if isinstance(event, ErrorEvent):
            current_msg = self._current_message
            if current_msg:
                try:
                    await current_msg.set_loading(False)
                except asyncio.CancelledError:
                    pass
            await self._handle_error(
                event.error_type, event.user_message,
                event.error_id, event.recoverable, event.retry_after
            )

        # FileReadEvent — buffer now, flush on StreamStart (when UserMessage is mounted).
        elif isinstance(event, FileReadEvent):
            self._pending_file_read_events.append(event)

        # StreamStart — flush buffered file-read notes after UserMessage is mounted.
        elif isinstance(event, StreamStart):
            await self._flush_file_read_notes(conversation)

        # ThinkingStart — create widget and start thinking block
        elif isinstance(event, ThinkingStart):
            if not self._current_message:
                self._current_message = AssistantMessage()
                await conversation.mount(self._current_message)
            try:
                await self._current_message.set_loading(False)
            except Exception:
                pass
            self._current_thinking = self._current_message.start_thinking()

        # ThinkingDelta — append to current thinking block
        elif isinstance(event, ThinkingDelta):
            if self._current_thinking:
                self._current_thinking.append(event.content)

        # ThinkingEnd — finalize thinking block
        elif isinstance(event, ThinkingEnd):
            if self._current_thinking:
                self._current_thinking.finalize(event.token_count)
                self._current_thinking = None

        # TextDelta — feed incremental text to segment buffer for live rendering
        elif isinstance(event, TextDelta):
            if not self._current_message:
                self._current_message = AssistantMessage()
                await conversation.mount(self._current_message)
            # Stop loading spinner on first text
            try:
                await self._current_message.set_loading(False)
            except Exception:
                pass
            # Buffer text for batched rendering
            self._segment_chunks.append(event.content)
            self._segment_chars += len(event.content)
            # Schedule flush (uses existing timer infrastructure)
            if not self._segment_flush_handle:
                try:
                    loop = asyncio.get_running_loop()
                    self._segment_flush_handle = loop.call_later(
                        self._segment_flush_interval_sec,
                        self._schedule_segment_flush,
                    )
                except RuntimeError:
                    pass

        # PausePromptStart — mount the pause widget
        elif isinstance(event, PausePromptStart):
            await self._flush_segment()
            widget = PausePromptWidget(
                reason=event.reason,
                reason_code=event.reason_code,
                pending_todos=event.pending_todos or [],
                stats=event.stats or {},
            )
            self._pause_widget = widget
            await conversation.mount(widget)
            widget.scroll_visible()

        # PausePromptEnd — remove widget if agent resolved it
        elif isinstance(event, PausePromptEnd):
            if self._pause_widget:
                self._pause_widget.remove()
                self._pause_widget = None

        # ContextUpdated — update status bar context pressure indicator
        elif isinstance(event, ContextUpdated):
            try:
                status_bar = self.query_one("#status", StatusBar)
                status_bar.update_context(event.used, event.limit, event.pressure_level)
            except NoMatches:
                pass

        # ContextCompacting — show info banner (higher render priority than task name,
        # and has minimum display duration so it's visible even if compaction is fast)
        elif isinstance(event, ContextCompacting):
            try:
                status_bar = self.query_one("#status", StatusBar)
                status_bar.show_info("Compacting conversation...", duration=30.0)
            except NoMatches:
                pass

        # ContextCompacted — replace compacting banner with result summary
        # (Old widgets are already cleared by the compact_boundary handler
        # in _render_store_message when the boundary MESSAGE_ADDED fires.)
        elif isinstance(event, ContextCompacted):
            try:
                status_bar = self.query_one("#status", StatusBar)
                status_bar.show_info(
                    f"Compacted: {event.messages_removed} messages summarized",
                    duration=5.0,
                )
            except NoMatches:
                pass

    def _finalize_current_message(self, msg: MessageWidget | None = None) -> None:
        """Finalize current message and reset state.

        Args:
            msg: Specific message to finalize. If provided, only clears
                 self._current_message if it matches. This prevents racing
                 with a new message that was created after cleanup started.
        """
        target = msg or self._current_message
        if target:
            target.finalize()

        # Only clear self._current_message if:
        # - No specific msg was provided (finalize whatever is current), OR
        # - The specific msg IS the current message (safe to clear)
        if msg is None or self._current_message is msg:
            self._current_message = None

        self._current_code = None
        self._current_thinking = None
        self._tool_cards.clear()
        self._pending_approval_ids.clear()

    # -------------------------------------------------------------------------
    # Loading State Helpers (Safe for sync interrupt handler)
    # -------------------------------------------------------------------------

    def _schedule_clear_loading(self) -> None:
        """
        Schedule loading clear safely - no lambdas, no create_task.

        Called from action_interrupt (sync context). Uses call_next to
        dispatch to async context safely.
        """
        msg = self._current_message
        if msg and hasattr(msg, 'set_loading'):
            self.call_next(self._clear_loading_async, msg)

    async def _clear_loading_async(self, msg: "AssistantMessage") -> None:
        """
        Actually clear loading (async-safe, exception-safe).

        Args:
            msg: The AssistantMessage to clear loading from
        """
        try:
            # Check if widget is still mounted before calling set_loading
            if hasattr(msg, '_is_mounted') and not msg._is_mounted:
                return  # Widget already removed from DOM
            await msg.set_loading(False)
        except Exception:
            pass  # Widget may have been removed

    # -------------------------------------------------------------------------
    # File-read notes (buffered flush)
    # -------------------------------------------------------------------------

    async def _flush_file_read_notes(self, conversation: ScrollableContainer) -> None:
        """Mount buffered file-read notes as children of the last UserMessage.

        Called on StreamStart, when UserMessage is guaranteed to be mounted.
        """
        if not self._pending_file_read_events:
            return

        events = self._pending_file_read_events
        self._pending_file_read_events = []

        # Find last UserMessage in conversation
        user_msgs = list(conversation.query("UserMessage"))
        if not user_msgs:
            return
        user_msg = user_msgs[-1]

        for evt in events:
            label = f" \u2514 Read {evt.path} ({evt.lines_read} lines)"
            if evt.truncated:
                label += " (truncated)"
            await user_msg.add_annotation(label)

    # -------------------------------------------------------------------------
    # Segmented Streaming (Default Mode)
    # -------------------------------------------------------------------------

    async def _flush_segment(self) -> None:
        """
        Render accumulated text as Markdown at a boundary.

        Called before tool cards, code blocks, thinking blocks, and at stream end.
        This is the core of segmented streaming - text only renders at boundaries,
        giving users stable, readable chunks instead of flickery incremental updates.
        """
        # RACE CONDITION FIX: Capture local reference
        msg = self._current_message
        if not msg or not self._segment_chunks:
            return

        # Snapshot scroll position BEFORE rendering
        was_at_bottom = self._is_at_bottom()

        # Join and render as Markdown (one-time parse at boundary)
        text = "".join(self._segment_chunks)
        self._segment_chunks.clear()
        self._segment_chars = 0

        # Reset buffered chars in status bar (use cached reference if available)
        if self._status_bar:
            self._status_bar.update_buffered_chars(0)

        # Use captured reference and check it's still mounted
        if msg.parent is not None:
            await msg.add_text(text)

        # Auto-scroll if was at bottom before append
        self._scroll_to_bottom(was_at_bottom=was_at_bottom)

    def _schedule_segment_flush(self) -> None:
        """
        Schedule segment flush without lambda closure (Fix #4).

        Called by loop.call_later() as a method reference.
        Guards against stale timers and prevents overlapping flushes.
        """
        # Timer has fired — clear handle so TextDelta can schedule the next one
        self._segment_flush_handle = None

        # Guard: Only flush if still streaming and not already flushing
        if not self._is_streaming or self._segment_flush_running:
            return

        # Schedule the async flush task
        asyncio.create_task(self._guarded_segment_flush())

    async def _guarded_segment_flush(self) -> None:
        """
        Guarded segment flush that prevents overlapping flushes (Fix #4).
        """
        if self._segment_flush_running:
            return

        self._segment_flush_running = True
        try:
            await self._flush_segment()
        finally:
            self._segment_flush_running = False

    async def _handle_error(
        self,
        error_type: str,
        user_message: str,
        error_id: str,
        recoverable: bool,
        retry_after: int | None
    ) -> None:
        """Handle error events with appropriate recovery.

        Note: Errors are NOT added to transcript. For provider_timeout, the pause
        widget owns the error display. For other errors, status bar shows briefly.
        Full debug info is in logs/SQLite keyed by error_id.
        """
        try:
            status_bar = self.query_one("#status", StatusBar)
        except NoMatches:
            status_bar = None

        # Check if we should retry (with limit to prevent infinite loops)
        can_retry = recoverable and self._retry_count < self.MAX_RETRIES

        # Optionally append error_id for debugging (CLARITY_SHOW_DEBUG_ERRORS=1)
        display_msg = user_message
        if os.getenv("CLARITY_SHOW_DEBUG_ERRORS") and error_id:
            display_msg = f"{user_message} [ref: {error_id[:8]}]"

        if error_type == "rate_limit" and retry_after and status_bar:
            # Show countdown and auto-retry
            status_bar.show_error(f"Rate limited: {display_msg}", countdown=retry_after)
            await asyncio.sleep(retry_after)
            status_bar.clear_error()

            if can_retry:
                self._retry_count += 1
                # Start retry in a worker - DO NOT await here!
                self._stream_worker = self.run_worker(
                    self._stream_response(self._last_user_input, self._last_attachments),
                    exclusive=True,
                    group="stream",
                    name="stream-retry",
                )
            else:
                self._retry_count = 0
                # Max retries exceeded - status bar will show error, pause widget will appear

        elif error_type == "network" and can_retry:
            # Show error and retry with backoff
            self._retry_count += 1
            backoff = 2 * self._retry_count  # Exponential backoff
            if status_bar:
                status_bar.show_error(f"Network error (retry {self._retry_count}/{self.MAX_RETRIES}): {display_msg}")
            await asyncio.sleep(backoff)
            if status_bar:
                status_bar.clear_error()
            # Start retry in a worker - DO NOT await here!
            self._stream_worker = self.run_worker(
                self._stream_response(self._last_user_input, self._last_attachments),
                exclusive=True,
                group="stream",
                name="stream-retry",
            )

        elif error_type == "provider_timeout":
            # Timeout errors go to pause flow - pause widget owns error display
            # Just briefly show in status bar, then clear when pause widget appears
            self._retry_count = 0
            if status_bar:
                status_bar.show_error(display_msg)
            # Pause widget will appear shortly via PausePromptStart event

        else:
            # Non-recoverable or max retries exceeded
            self._retry_count = 0
            if status_bar:
                status_bar.show_error(display_msg)
            # Don't add to transcript - status bar is sufficient for transient errors

    # -------------------------------------------------------------------------
    # Message Handlers (from widgets)
    # -------------------------------------------------------------------------

    def _find_subagent_tool_card(self, call_id: str):
        """Delegate to SubagentCoordinator.find_subagent_tool_card()."""
        return self._subagent_coordinator.find_subagent_tool_card(call_id)

    def on_approval_response_message(self, message: ApprovalResponseMessage) -> None:
        """Handle approval response from ToolApprovalOptions."""
        approved = message.action in ("yes", "yes_all")

        self.ui_protocol.submit_action(ApprovalResult(
            call_id=message.call_id,
            approved=approved,
            auto_approve_future=(message.action == "yes_all"),
            feedback=message.feedback,
        ))

        # Clear from pending approvals
        self._pending_approval_ids.discard(message.call_id)

        # Update tool card status (check parent cards, then subagent cards)
        tool_name = ""
        card = self._tool_cards.get(message.call_id)
        if not card:
            card = self._find_subagent_tool_card(message.call_id)
        if card:
            tool_name = card.tool_name
            if approved:
                card.status = ToolStatus.APPROVED
            else:
                card.status = ToolStatus.REJECTED

        # Persist approval decision to MessageStore (Fix 2: Approval persistence)
        self._persist_tool_approval(
            tool_call_id=message.call_id,
            tool_name=tool_name,
            approved=approved,
            action=message.action,
            feedback=message.feedback
        )

        # Re-focus input if no more pending approvals
        if not self._pending_approval_ids and not self._is_streaming:
            try:
                self.query_one("#input", ChatInput).focus()
            except NoMatches:
                pass

    def on_stream_interrupt_message(self, message: StreamInterruptMessage) -> None:
        """Handle stream interrupt request."""
        self.ui_protocol.submit_action(InterruptSignal())

        # Cancel the worker (primary cancellation mechanism)
        if self._stream_worker is not None:
            self._stream_worker.cancel()

        # Also cancel the task (belt and suspenders)
        if self._streaming_task:
            self._streaming_task.cancel()

    def on_retry_request_message(self, message: RetryRequestMessage) -> None:
        """Handle retry request."""
        self.ui_protocol.submit_action(RetrySignal())

    def on_pause_response_message(self, message: PauseResponseMessage) -> None:
        """Handle pause response from PausePromptWidget.

        Simple two-option handler:
        - Continue: Signal agent to resume (agent emits StreamStart, UI shows spinner)
        - Stop: Signal agent to stop, return focus to input
        """
        # Remove the pause widget
        if self._pause_widget:
            self._pause_widget.remove()
            self._pause_widget = None

        # Signal agent with user's decision
        # Note: Spinner for Continue is driven by agent's StreamStart event, not hardcoded here
        self.ui_protocol.submit_action(PauseResult(
            continue_work=message.continue_work,
            feedback=None,
        ))

        # Re-focus input if stopping
        if not message.continue_work and not self._is_streaming:
            try:
                self.query_one("#input", ChatInput).focus()
            except NoMatches:
                pass

    # -------------------------------------------------------------------------
    # Clarify Widget Handling
    # -------------------------------------------------------------------------

    async def _on_clarify_request(
        self,
        message: "Message",
        conversation: ScrollableContainer
    ) -> None:
        """Handle clarify_request system message - mount ClarifyWidget if needed.

        Called when a clarify_request message is added to the store.
        Mounts ClarifyWidget only if the tool is still pending (not yet answered).

        Widget visibility is driven by tool_state:
        - PENDING/AWAITING_APPROVAL: Mount widget (needs user input)
        - SUCCESS/ERROR/CANCELLED: Don't mount (already completed)
        """
        extra = message.meta.extra if message.meta else {}
        call_id = extra.get("call_id")
        questions = extra.get("questions", [])
        context = extra.get("context")

        if not call_id or not questions:
            return

        # Don't mount if we already have a clarify widget for this call_id
        if self._clarify_widget and self._clarify_widget.call_id == call_id:
            return

        # Check if tool already has a result: Only mount if tool is still pending
        # Use get_tool_result() which reads from persisted tool messages (role="tool")
        # This works for both live and replay sessions (tool_state is ephemeral)
        if self._message_store:
            tool_result = self._message_store.get_tool_result(call_id)
            if tool_result:
                # Tool result exists - tool was already executed, don't mount widget
                logger.info(f"[CLARIFY] Skipping mount - tool result exists for call_id={call_id}")
                return

        # Create and mount clarify widget
        self._clarify_widget = ClarifyWidget(
            call_id=call_id,
            questions=questions,
            context=context
        )

        # Mount in current assistant message or conversation
        if self._current_message:
            try:
                await self._current_message.mount(self._clarify_widget)
            except Exception:
                # Fallback to conversation
                await conversation.mount(self._clarify_widget)
        else:
            await conversation.mount(self._clarify_widget)

        # Scroll to make widget visible (only if user is at bottom)
        if self._auto_scroll:
            self._scroll_to_bottom(conversation)

    def on_clarify_response_message(self, message: ClarifyResponseMessage) -> None:
        """Handle ClarifyResponseMessage from ClarifyWidget.

        Single-writer architecture: We do NOT persist here. The agent persists
        clarify_response via MemoryManager after receiving the ClarifyResult.

        We only:
        1. Remove the widget
        2. Submit ClarifyResult to ui_protocol (unblocks agent)
        """
        # Remove the clarify widget
        if self._clarify_widget:
            self._clarify_widget.remove()
            self._clarify_widget = None

        # Signal agent with user's response (agent will persist)
        self.ui_protocol.submit_action(ClarifyResult(
            call_id=message.call_id,
            submitted=message.submitted,
            responses=message.responses,
            chat_instead=message.chat_instead,
            chat_message=message.chat_message,
        ))

        # Re-focus input if cancelled/completed
        if not self._is_streaming:
            try:
                self.query_one("#input", ChatInput).focus()
            except NoMatches:
                pass

    async def mount_plan_approval(
        self,
        plan_hash: str,
        excerpt: str,
        truncated: bool = False,
        plan_path: str | None = None
    ) -> None:
        """
        Mount PlanApprovalWidget when agent requests plan approval.

        Called when request_plan_approval tool returns with plan for approval.
        """
        # Avoid duplicates
        if self._plan_approval_widget and self._plan_approval_widget.plan_hash == plan_hash:
            return

        self._plan_approval_widget = PlanApprovalWidget(
            plan_hash=plan_hash,
            excerpt=excerpt,
            truncated=truncated,
            plan_path=plan_path,
        )

        # Mount in conversation area
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            if self._current_message:
                await self._current_message.mount(self._plan_approval_widget)
            else:
                await conversation.mount(self._plan_approval_widget)
        except NoMatches:
            conversation = self.query_one("#conversation", ConversationContainer)
            await conversation.mount(self._plan_approval_widget)

        # Scroll to make widget visible (only if user is at bottom)
        if self._auto_scroll:
            self._scroll_to_bottom(conversation)

    def on_plan_approval_response_message(self, message: PlanApprovalResponseMessage) -> None:
        """Handle PlanApprovalResponseMessage from PlanApprovalWidget.

        Single-writer architecture: We do NOT persist here. The agent persists
        plan_approved/plan_rejected via MemoryManager after receiving the PlanApprovalResult.

        We only:
        1. Remove the widget
        2. Submit PlanApprovalResult to ui_protocol (unblocks agent)
        """
        # Remove the plan approval widget
        if self._plan_approval_widget:
            self._plan_approval_widget.remove()
            self._plan_approval_widget = None

        # Signal agent with user's response (agent will persist)
        self.ui_protocol.submit_action(PlanApprovalResult(
            plan_hash=message.plan_hash,
            approved=message.approved,
            auto_accept_edits=message.auto_accept_edits,
            feedback=message.feedback,
        ))

        # Re-focus input if cancelled/completed
        if not self._is_streaming:
            try:
                self.query_one("#input", ChatInput).focus()
            except NoMatches:
                pass

    # -------------------------------------------------------------------------
    # Scroll Handling
    # -------------------------------------------------------------------------

    def _is_at_bottom(self, conversation: ScrollableContainer | None = None) -> bool:
        """Check if conversation is scrolled to the bottom.

        Call BEFORE appending content to snapshot the scroll position.
        """
        target = conversation or self._conversation
        if not target:
            return True
        return target.is_vertical_scroll_end

    def _scroll_to_bottom(
        self,
        conversation: ScrollableContainer | None = None,
        was_at_bottom: bool | None = None,
    ) -> None:
        """Scroll to bottom only if user hasn't scrolled away.

        Args:
            conversation: Target container (defaults to self._conversation)
            was_at_bottom: Pre-append scroll position snapshot from _is_at_bottom().
                          If None, checks _auto_scroll flag only (for cases where
                          snapshot wasn't taken, e.g. widget mounts).
        """
        target = conversation or self._conversation
        if not target:
            return
        if not self._auto_scroll:
            return
        if was_at_bottom is not None and not was_at_bottom:
            return
        target.scroll_end(animate=False)

    # -------------------------------------------------------------------------
    # Actions (keyboard bindings)
    # -------------------------------------------------------------------------

    def action_interrupt(self) -> None:
        """
        Handle Ctrl+C/Escape - cancel approval, interrupt stream, or exit.

        Behavior:
        - If pending approvals: Cancel the approval (reject it)
        - If streaming (no approvals): Interrupt the stream
        - If not streaming: First press shows hint, second quick press exits
        """
        try:
            import time

            now = time.time()

            # FIX: Safe loading clear (no lambdas, no create_task)
            self._schedule_clear_loading()

            # If there are pending approvals, cancel them instead of interrupting stream
            if self._pending_approval_ids:
                # Reject all pending approvals - notify agent for persistence
                for call_id in list(self._pending_approval_ids):
                    try:
                        self.ui_protocol.submit_action(ApprovalResult(
                            call_id=call_id,
                            approved=False,
                        ))
                    except Exception as e:
                        logger.error(f"Error submitting approval cancellation for {call_id}: {e}", exc_info=True)

                    # DIRECT UI CLEANUP: Update card status immediately
                    # Don't wait for async store notification - user expects immediate feedback
                    try:
                        if call_id in self._tool_cards:
                            self._tool_cards[call_id].status = ToolStatus.CANCELLED
                    except Exception as e:
                        logger.error(f"Error updating tool card status for {call_id}: {e}", exc_info=True)

                # Clear pending approvals
                self._pending_approval_ids.clear()
                self.notify("Approval cancelled", severity="information", timeout=2)
                return

            if self._is_streaming:
                # Interrupt the current stream
                self.log("Ctrl+C: Interrupting stream")
                self.notify("Interrupting stream...", severity="warning", timeout=2)

                # DIRECT UI CLEANUP: Cancel any approval widgets immediately
                # This handles cases where _pending_approval_ids might be out of sync
                for _call_id, card in self._tool_cards.items():
                    if card.status == ToolStatus.AWAITING_APPROVAL:
                        card.status = ToolStatus.CANCELLED  # triggers watch_status()
                self._pending_approval_ids.clear()

                # Set flag BEFORE cancelling so handler knows this is user-initiated
                self._user_interrupt_requested = True

                self.ui_protocol.submit_action(InterruptSignal())

                # Cancel the worker (primary cancellation mechanism)
                if self._stream_worker is not None:
                    self._stream_worker.cancel()

                # Cancel any running subagents (handles both in-process and subprocess)
                if self._subagent_registry:
                    for sid in list(self._subagent_subscriptions.keys()):
                        self._subagent_registry.cancel(sid)

                # Also cancel the task (belt and suspenders)
                if self._streaming_task and not self._streaming_task.done():
                    self._streaming_task.cancel()

                # Also show feedback in status bar
                try:
                    status_bar = self.query_one("#status", StatusBar)
                    status_bar.show_error("Interrupting...", countdown=2)
                except NoMatches:
                    pass
            else:
                # Double Ctrl+C to exit (within 1 second)
                if hasattr(self, '_last_ctrl_c_time') and (now - self._last_ctrl_c_time) < 1.0:
                    self.exit()
                else:
                    self._last_ctrl_c_time = now
                    # Show hint
                    self.notify("Press Ctrl+C again to quit, or Ctrl+D to exit", severity="warning", timeout=2)
                    try:
                        status_bar = self.query_one("#status", StatusBar)
                        status_bar.show_error("Ctrl+C again to quit | Ctrl+D to exit", countdown=2)
                    except NoMatches:
                        pass
        except Exception as e:
            logger.error(f"Critical error in action_interrupt: {e}", exc_info=True)
            # Try to recover gracefully
            try:
                self._pending_approval_ids.clear()
                self.notify("Error handling interrupt", severity="error", timeout=2)
            except Exception:
                pass  # Last resort - don't crash on error handling error

    def action_clear_screen(self) -> None:
        """Handle Ctrl+L - clear conversation."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.remove_children()
        except NoMatches:
            pass

    def action_toggle_mode(self) -> None:
        """Toggle permission mode: plan -> normal -> auto -> plan"""
        try:
            if not self.agent:
                return

            # Cycle through modes
            current = self.agent.get_permission_mode()
            cycle = {"plan": "normal", "normal": "auto", "auto": "plan"}
            next_mode = cycle.get(current, "normal")

            # Update agent (this also handles plan_mode_state activation/deactivation)
            self.agent.set_permission_mode(next_mode)

            # Update status bar
            try:
                status = self.query_one("#status", StatusBar)
                status.set_mode(next_mode)
            except NoMatches:
                pass

            # Notification with plan mode details
            if next_mode == "plan":
                plan_path = self.agent.plan_mode_state.plan_file_path
                self.notify(f"PLAN MODE - Write plan to: {plan_path}", timeout=3)
            else:
                mode_labels = {"normal": "NORMAL", "auto": "AUTO"}
                self.notify(f"Mode: {mode_labels.get(next_mode, next_mode.upper())}", timeout=1)
        except Exception as e:
            logger.error(f"Error toggling mode: {e}", exc_info=True)
            self.notify("Error toggling mode", severity="error", timeout=2)

    def action_toggle_todos(self) -> None:
        """Toggle todo bar expand/collapse."""
        try:
            todo_bar = self.query_one("#todo-bar", TodoBar)
            todo_bar.toggle()
        except NoMatches:
            pass

    def action_debug_widgets(self) -> None:
        """Debug action: count and log all widgets in the DOM."""
        from .widgets.code_block import CodeBlock
        from .widgets.message import MessageWidget, UserMessage
        from .widgets.tool_card import ToolCard

        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            all_widgets = list(conversation.walk_children())
            messages = list(conversation.query(MessageWidget)) + list(conversation.query(UserMessage))
            tool_cards = list(conversation.query(ToolCard))
            code_blocks = list(conversation.query(CodeBlock))

            debug_msg = (
                f"[DEBUG] Widget count: "
                f"Total={len(all_widgets)}, "
                f"Messages={len(messages)}, "
                f"ToolCards={len(tool_cards)}, "
                f"CodeBlocks={len(code_blocks)}"
            )
            self.notify(debug_msg, timeout=10)
            logger.info(debug_msg)
        except Exception as e:
            self.notify(f"[DEBUG ERROR] {e}", timeout=5)

    def _on_todos_updated(self, todos: list) -> None:
        """
        Handle todo list updates from agent.

        Updates both TodoBar (shows list) and StatusBar (shows current task name).
        """
        # Update TodoBar
        try:
            todo_bar = self.query_one("#todo-bar", TodoBar)
            todo_bar.update_todos(todos)
        except NoMatches:
            pass

        # Update StatusBar with current in_progress task
        try:
            status = self.query_one("#status", StatusBar)
            # Find the in_progress task
            in_progress = [t for t in todos if t.get('status') == 'in_progress']
            if in_progress:
                # Use activeForm for dynamic status display
                task_name = in_progress[0].get('activeForm', in_progress[0].get('content', ''))
                status.set_current_task(task_name)
            else:
                status.clear_current_task()
        except NoMatches:
            pass

    def _on_bg_task_update(self, active_count: int) -> None:
        """Handle background task completion callback.

        Updates the StatusBar BG badge count. Called from the asyncio
        event loop by BackgroundTaskRegistry on task completion.
        """
        try:
            status = self.query_one("#status", StatusBar)
            status.set_bg_task_count(active_count)
        except NoMatches:
            pass

    # -------------------------------------------------------------------------
    # Phase 6: Store-Driven Rendering
    # -------------------------------------------------------------------------

    def bind_store(self, store: "MessageStore", session_id: str | None = None) -> None:
        """
        Bind a MessageStore for session persistence and store-driven rendering.

        Creates a StoreAdapter for JSONL persistence and subscribes to store
        notifications for rendering. UIEvents are forwarded to the adapter;
        store notifications drive all TUI rendering.

        Args:
            store: MessageStore to bind
            session_id: Session ID for the current session
        """
        self._message_store = store
        self._session_id = session_id or f"session-{id(store)}"

        # Always create StoreAdapter for persistence (JSONL via SessionWriter)
        from .store_adapter import StoreAdapter
        self._store_adapter = StoreAdapter(
            store=store,
            session_id=self._session_id,
            flush_on_boundary=True  # Update store at each content boundary
        )

        # Keep extracted renderers' store references in sync
        self._segment_renderer.set_message_store(store)
        self._store_renderer.set_message_store(store)

        self._subscribe_to_store()
        logger.info(f"TUI bound to MessageStore with store-driven rendering (session={self._session_id})")

    def set_session_writer(self, writer) -> None:
        """
        Set the SessionWriter for JSONL persistence.

        The writer will be opened in on_mount() (within Textual's event loop)
        and closed in on_unmount().

        Args:
            writer: SessionWriter instance (not yet opened)
        """
        self._session_writer = writer

    def set_render_meta_registry(self, registry: RenderMetaRegistry) -> None:
        """
        Set the render metadata registry for tool approval hints.

        The registry is queried when creating tool cards to determine
        whether to show the approval widget. Agent writes approval policy
        to this registry when tool name becomes known during streaming.

        Args:
            registry: RenderMetaRegistry instance (from MemoryManager)
        """
        self._render_meta = registry

    async def _open_session_writer(self) -> None:
        """Open the session writer and bind to store (called from on_mount)."""
        if self._session_writer and self._message_store:
            try:
                await self._session_writer.open()
                self._session_writer.bind_to_store(self._message_store)
                logger.info("Session writer opened and bound to store")
            except Exception as e:
                logger.error(f"Failed to open session writer: {e}")

    async def _close_session_writer(self) -> None:
        """Close the session writer (called from on_unmount)."""
        if self._session_writer:
            try:
                await self._session_writer.close()
                logger.info("Session writer closed")
            except Exception as e:
                logger.error(f"Failed to close session writer: {e}")

    def _subscribe_to_store(self) -> None:
        """Subscribe to MessageStore events."""
        if not self._message_store:
            return

        def sync_handler(notification: "StoreNotification") -> None:
            """Sync callback that schedules async handling."""
            # Use call_soon_threadsafe for thread-safe async scheduling
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        self._handle_store_notification(notification)
                    )
                )
            except RuntimeError:
                # No running loop - we're in sync context, use call_next
                self.call_next(self._handle_store_notification, notification)

        self._store_unsubscribe = self._message_store.subscribe(sync_handler)

    async def _handle_store_notification(self, notification: "StoreNotification") -> None:
        """
        Handle store notification events.

        Maps store events to widget operations:
        - MESSAGE_ADDED: Mount new message widget
        - MESSAGE_UPDATED: Update existing widget
        - MESSAGE_FINALIZED: Finalize widget state
        - BULK_LOAD_COMPLETE: Replay finished, enable input
        """
        from ..session.store.memory_store import StoreEvent

        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
        except NoMatches:
            return

        event = notification.event
        message = notification.message

        match event:
            case StoreEvent.MESSAGE_ADDED:
                await self._on_store_message_added(message, conversation)

            case StoreEvent.MESSAGE_UPDATED:
                await self._on_store_message_updated(message, conversation)

            case StoreEvent.MESSAGE_FINALIZED:
                await self._on_store_message_finalized(message)

            case StoreEvent.BULK_LOAD_COMPLETE:
                await self._on_store_bulk_load_complete(conversation)

            case StoreEvent.TOOL_STATE_UPDATED:
                await self._on_store_tool_state_updated(notification)

    # ---- Store message rendering (delegated to StoreRenderer - Phase 3) ----

    async def _render_store_message(
        self,
        message: "Message",
        conversation: ScrollableContainer,
        bulk_load: bool = False
    ) -> None:
        """Delegate to StoreRenderer.render_store_message().

        Handles compact_boundary's live-streaming widget reset locally
        (since it writes to self._current_message etc.), then delegates
        all rendering to the extracted StoreRenderer.
        """
        # compact_boundary needs to reset live-streaming refs on self
        if (message and message.is_system and message.meta
                and message.meta.event_type == "compact_boundary"):
            self._current_message = None
            self._current_code = None
            self._current_thinking = None

        self._pre_mounted_user_widget = await self._store_renderer.render_store_message(
            message, conversation,
            bulk_load=bulk_load,
            current_message=self._current_message,
            pre_mounted_user_widget=self._pre_mounted_user_widget,
            is_replaying=self._is_replaying,
            status_bar=self._status_bar,
        )

    async def _on_store_message_added(
        self,
        message: "Message",
        conversation: ScrollableContainer
    ) -> None:
        """Handle MESSAGE_ADDED: mount new widget (live path)."""
        await self._render_store_message(message, conversation, bulk_load=False)

    async def _on_store_message_updated(
        self,
        message: "Message",
        conversation: ScrollableContainer
    ) -> None:
        """Handle MESSAGE_UPDATED: coalesce and update existing widget.

        PR4: Updates are coalesced within a time window to prevent UI flicker
        during rapid streaming updates. Only the latest state is rendered.
        """
        if not message or not message.meta:
            return

        stream_id = message.meta.stream_id
        if not stream_id:
            return

        if stream_id not in self._store_message_widgets:
            # No existing widget - treat as add
            await self._on_store_message_added(message, conversation)
            return

        # PR4: Coalesce updates - store latest and schedule flush
        self._store_pending_updates[stream_id] = message

        # Cancel existing timer and schedule new one
        if self._store_update_timer:
            self._store_update_timer.cancel()

        try:
            loop = asyncio.get_running_loop()
            self._store_update_timer = loop.call_later(
                self._store_update_interval_sec,
                lambda: asyncio.create_task(self._flush_store_updates(conversation))
            )
        except RuntimeError:
            # No running loop - flush immediately
            await self._flush_store_updates(conversation)

    async def _flush_store_updates(self, conversation: ScrollableContainer) -> None:
        """Flush all pending store updates to widgets.

        PR4: Called after coalescing interval to batch-render updates.
        Renders segments in order to maintain correct text/tool interleaving.
        """
        self._store_update_timer = None

        if not self._store_pending_updates:
            return

        # Snapshot scroll position BEFORE rendering batch
        was_at_bottom = self._is_at_bottom(conversation)

        # Process all pending updates
        for stream_id, message in self._store_pending_updates.items():
            if stream_id not in self._store_message_widgets:
                continue

            widget = self._store_message_widgets[stream_id]
            segments = message.meta.segments if message.meta and message.meta.segments else []
            last_idx = self._store_rendered_segment_idx.get(stream_id, 0)

            # Use unified helper to render only NEW segments (skip existing cards)
            rendered = await self._render_segments(
                widget, message, segments,
                start_idx=last_idx, skip_existing_cards=True
            )

            # Update last rendered segment index
            if segments:
                self._store_rendered_segment_idx[stream_id] = last_idx + rendered

        # Clear pending updates
        self._store_pending_updates.clear()

        # Auto-scroll if was at bottom before batch render
        if not self._is_replaying:
            self._scroll_to_bottom(conversation, was_at_bottom=was_at_bottom)

    async def _on_store_message_finalized(self, message: "Message") -> None:
        """Handle MESSAGE_FINALIZED: flush pending updates and finalize widget."""
        if not message or not message.meta:
            return

        stream_id = message.meta.stream_id
        if not stream_id:
            return

        # PR4: Flush any pending updates for this stream before finalizing
        if stream_id in self._store_pending_updates:
            try:
                final_msg = self._store_pending_updates.pop(stream_id)
                if stream_id in self._store_message_widgets:
                    widget = self._store_message_widgets[stream_id]
                    segments = final_msg.meta.segments if final_msg.meta and final_msg.meta.segments else []
                    last_idx = self._store_rendered_segment_idx.get(stream_id, 0)

                    # Use unified helper to render remaining segments (skip existing cards)
                    await self._render_segments(
                        widget, final_msg, segments,
                        start_idx=last_idx, skip_existing_cards=True
                    )
            except NoMatches:
                pass

        # Finalize the widget and cleanup tracking
        if stream_id in self._store_message_widgets:
            widget = self._store_message_widgets[stream_id]
            widget.finalize()
            # Cleanup segment index tracking for this stream
            self._store_rendered_segment_idx.pop(stream_id, None)

    # ---- Segment rendering (delegated to SegmentRenderer - Phase 2) ----

    async def _render_segments(
        self,
        widget: "AssistantMessage",
        message: "Message",
        segments: list,
        start_idx: int = 0,
        skip_existing_cards: bool = False,
        defer_tool_mount: bool = False,
        use_store_hydration: bool = False
    ) -> int:
        """Delegate to SegmentRenderer.render_segments()."""
        return await self._segment_renderer.render_segments(
            widget, message, segments,
            start_idx=start_idx,
            skip_existing_cards=skip_existing_cards,
            defer_tool_mount=defer_tool_mount,
            use_store_hydration=use_store_hydration,
            hydrate_fn=self._hydrate_tool_card_from_store if use_store_hydration else None,
        )

    async def _render_tool_segments_only(
        self,
        widget: "AssistantMessage",
        message: "Message",
        segments: list
    ) -> None:
        """Delegate to SegmentRenderer.render_tool_segments_only()."""
        await self._segment_renderer.render_tool_segments_only(widget, message, segments)

    def _get_tool_call_safe(self, message, tc_idx, context=""):
        """Delegate to SegmentRenderer.get_tool_call_safe()."""
        return self._segment_renderer.get_tool_call_safe(message, tc_idx, context)

    def _get_tool_call_by_id(self, message, tool_call_id, context=""):
        """Delegate to SegmentRenderer.get_tool_call_by_id()."""
        return self._segment_renderer.get_tool_call_by_id(message, tool_call_id, context)

    async def _apply_tool_result_to_card(self, message: "Message") -> None:
        """Delegate to StoreRenderer.apply_tool_result_to_card()."""
        await self._store_renderer.apply_tool_result_to_card(message)

    async def _on_store_bulk_load_complete(
        self,
        conversation: ScrollableContainer
    ) -> None:
        """Handle BULK_LOAD_COMPLETE: render all loaded messages.

        During bulk load, individual MESSAGE_ADDED events are suppressed.
        This handler iterates all messages and renders each through the
        shared _render_store_message() method with bulk_load=True for
        performance optimizations (deferred tool mounts, no per-message scroll).
        """
        if not self._message_store:
            self._is_replaying = False
            return

        # Render post-compaction messages only (get_transcript_view filters
        # out pre-compaction messages when a compact boundary exists).
        #
        # Hide conversation during bulk load to prevent "reel loading" effect.
        # Each await mount()/add_text() yields to the event loop, letting
        # Textual flush intermediate frames. By hiding the container, all
        # mounts happen invisibly — then a single paint on reveal.
        messages = []
        try:
            conversation.styles.visibility = "hidden"

            messages = self._message_store.get_transcript_view()

            for message in messages:
                await self._render_store_message(message, conversation, bulk_load=True)

        except Exception as e:
            # Log full stack trace for debuggability
            import traceback
            logger.error(f"Error rendering bulk-loaded messages: {e}\n{traceback.format_exc()}")
            # Show UI banner so user knows resume failed
            await self._show_resume_error_banner(str(e))
        finally:
            conversation.styles.visibility = "visible"

        # Clear replay mode
        self._is_replaying = False

        # Scroll to bottom after replay
        self._scroll_to_bottom(conversation)

        # Re-enable input
        try:
            input_widget = self.query_one("#input", ChatInput)
            input_widget.disabled = False
            input_widget.focus()
        except NoMatches:
            pass

        logger.info(f"Session replay complete: {len(messages)} messages rendered")

    async def _on_store_tool_state_updated(
        self,
        notification: "StoreNotification"
    ) -> None:
        """Handle TOOL_STATE_UPDATED: update tool card status and clarify widget.

        Called when Agent updates tool execution state in MessageStore.
        Updates card.status which triggers watch_status() for approval widget.
        Also removes clarify widget when clarify tool completes (status-driven).
        """
        tool_call_id = notification.tool_call_id
        tool_state = notification.tool_state

        if not tool_call_id or not tool_state:
            return

        # Remove clarify widget when clarify tool completes (status-driven)
        # This handles both live and replay sessions uniformly
        if self._clarify_widget and self._clarify_widget.call_id == tool_call_id:
            if tool_state.status in (
                CoreToolStatus.SUCCESS,
                CoreToolStatus.ERROR,
                CoreToolStatus.CANCELLED
            ):
                self._clarify_widget.remove()
                self._clarify_widget = None

        # Card may not exist yet (race condition) - that's OK, card creation queries store
        if tool_call_id not in self._tool_cards:
            return

        card = self._tool_cards[tool_call_id]

        # Map and set status - watch_status() handles approval widget
        status_map = {
            CoreToolStatus.PENDING: ToolStatus.PENDING,
            CoreToolStatus.AWAITING_APPROVAL: ToolStatus.AWAITING_APPROVAL,
            CoreToolStatus.APPROVED: ToolStatus.APPROVED,
            CoreToolStatus.REJECTED: ToolStatus.REJECTED,
            CoreToolStatus.RUNNING: ToolStatus.RUNNING,
            CoreToolStatus.SUCCESS: ToolStatus.SUCCESS,
            CoreToolStatus.ERROR: ToolStatus.ERROR,
            CoreToolStatus.TIMEOUT: ToolStatus.TIMEOUT,
            CoreToolStatus.CANCELLED: ToolStatus.CANCELLED,
            CoreToolStatus.SKIPPED: ToolStatus.SKIPPED,
        }
        card.status = status_map.get(tool_state.status, ToolStatus.PENDING)

        # Handle terminal states
        if tool_state.status == CoreToolStatus.SUCCESS:
            card.set_result(tool_state.result, tool_state.duration_ms)
        elif tool_state.status == CoreToolStatus.ERROR:
            card.set_error(tool_state.error)

    def _hydrate_tool_card_from_store(self, card: "ToolCard", tool_call_id: str) -> None:
        """Delegate to StoreRenderer.hydrate_tool_card_from_store()."""
        self._store_renderer.hydrate_tool_card_from_store(card, tool_call_id)

    def _persist_tool_approval(
        self,
        tool_call_id: str,
        tool_name: str,
        approved: bool,
        action: str,
        feedback: str | None = None
    ) -> None:
        """
        Persist a tool approval decision to the MessageStore.

        This creates a system event with event_type="tool_approval" that is
        NOT included in LLM context, but IS written to JSONL for session resume.

        On session resume, these events are read and applied to restore ToolCard states.

        Args:
            tool_call_id: The tool_call_id this approval responds to
            tool_name: Name of the tool
            approved: Whether the tool was approved
            action: The action taken ("yes", "yes_all", "no")
            feedback: Optional feedback text if rejected with feedback
        """
        if not self._message_store:
            return

        try:
            from src.session.models.message import Message as SessionMessage

            # Get session_id from store or use a default
            session_id = ""
            messages = self._message_store.get_ordered_messages()
            if messages:
                session_id = messages[0].session_id

            approval_msg = SessionMessage.create_tool_approval(
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                approved=approved,
                action=action,
                feedback=feedback,
                seq=self._message_store.next_seq(),
            )
            self._message_store.add_message(approval_msg)
        except Exception as e:
            logger.warning(f"Failed to persist tool approval: {e}")

    async def _show_resume_error_banner(self, error_message: str) -> None:
        """
        Show an error banner when session resume fails.

        Tweak 1: Make failures visible to users instead of silently degrading.

        Args:
            error_message: The error message to display
        """
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            # Create a simple error banner widget
            error_widget = Static(
                f"[bold red]Session Resume Error[/bold red]\n{error_message[:200]}",
                classes="resume-error-banner"
            )
            await conversation.mount(error_widget)
            logger.warning(f"Displayed resume error banner: {error_message[:100]}")
        except Exception as banner_error:
            # If we can't even show the banner, just log
            logger.error(f"Could not show resume error banner: {banner_error}")

    def unbind_store(self) -> None:
        """Unbind from MessageStore and cleanup adapter."""
        if self._store_unsubscribe:
            self._store_unsubscribe()
            self._store_unsubscribe = None
        self._message_store = None
        self._store_adapter = None
        self._store_message_widgets.clear()
        self._session_id = None

    def action_scroll_up(self) -> None:
        """Scroll conversation up."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.scroll_up(animate=False)
            self._auto_scroll = False
        except NoMatches:
            pass

    def action_scroll_down(self) -> None:
        """Scroll conversation down."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.scroll_down(animate=False)
            # Re-enable auto-scroll if at bottom
            if conversation.scroll_offset.y >= conversation.max_scroll_y - 10:
                self._auto_scroll = True
        except NoMatches:
            pass

    def action_page_up(self) -> None:
        """Page up in conversation."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.scroll_page_up(animate=False)
            self._auto_scroll = False
        except NoMatches:
            pass

    def action_page_down(self) -> None:
        """Page down in conversation."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.scroll_page_down(animate=False)
            # Re-enable auto-scroll if at bottom
            if conversation.scroll_offset.y >= conversation.max_scroll_y - 10:
                self._auto_scroll = True
        except NoMatches:
            pass

    def action_scroll_home(self) -> None:
        """Scroll to top of conversation."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.scroll_home(animate=False)
            self._auto_scroll = False
        except NoMatches:
            pass

    def action_scroll_end(self) -> None:
        """Scroll to bottom of conversation."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.scroll_end(animate=False)
            self._auto_scroll = True
        except NoMatches:
            pass


def run_app(
    agent: "CodingAgent | None" = None,
    stream_handler: Callable[[str, UIProtocol], AsyncIterator[UIEvent]] | None = None,
    model_name: str = "claude-3-opus",
    show_header: bool = False,
) -> None:
    """
    Run the Coding Agent TUI.

    This is the main entry point for launching the TUI.

    Args:
        agent: CodingAgent instance (recommended). If provided, stream_handler
              is created automatically using agent.stream_response().
        stream_handler: Async function that yields UIEvents for a given input.
                       Alternative to providing agent directly.
        model_name: Name of the LLM model for display (used if agent not provided)
        show_header: Whether to show the header bar

    Example with agent:
        from src.core.agent import CodingAgent

        agent = CodingAgent(...)
        run_app(agent=agent)

    Example with stream_handler:
        async def my_stream_handler(user_input: str, ui: UIProtocol):
            yield StreamStart()
            yield TextDelta(content=f"You said: {user_input}")
            yield StreamEnd()

        run_app(stream_handler=my_stream_handler, model_name="my-model")
    """
    app = CodingAgentApp(
        agent=agent,
        stream_handler=stream_handler,
        model_name=model_name,
        show_header=show_header,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        # Gracefully handle Ctrl+C that escapes signal handler
        pass
