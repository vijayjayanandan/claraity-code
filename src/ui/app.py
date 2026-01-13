"""
CodingAgentApp - Main Textual application for the coding agent.

This is the top-level application that:
- Composes the UI layout (conversation, input, status bar)
- Handles UIEvents from StreamProcessor and dispatches to widgets
- Manages streaming state and auto-scroll
- Coordinates with UIProtocol for approvals
"""

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Input, Footer, Header, TextArea
from textual.widgets.text_area import Selection
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.worker import Worker
from textual.events import Paste
from typing import TYPE_CHECKING, AsyncIterator, Callable, Any, Optional, Literal, List
from pathlib import Path
import asyncio
import logging
import time

# Module-level logger for debugging silent exceptions
logger = logging.getLogger(__name__)

from src.core.attachment import Attachment
from .events import (
    UIEvent, StreamStart, StreamEnd,
    TextDelta, CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    PausePromptStart, PausePromptEnd,
    ContextUpdated, ContextCompacted,
    ErrorEvent, ToolStatus,
)
from .messages import (
    ApprovalResponseMessage, StreamInterruptMessage,
    RetryRequestMessage, InputSubmittedMessage,
    PauseResponseMessage,
)
from .protocol import UIProtocol, ApprovalResult, InterruptSignal, RetrySignal, PauseResult
from .widgets.message import MessageWidget, UserMessage, AssistantMessage
from .widgets.code_block import CodeBlock
from .widgets.tool_card import ToolCard
from .widgets.thinking import ThinkingBlock
from .widgets.status_bar import StatusBar
from .widgets.autocomplete_dropdown import AutocompleteDropdown
from .widgets.attachment_bar import AttachmentBar
from .widgets.todo_bar import TodoBar
from .widgets.pause_widget import PausePromptWidget
from .autocomplete import FileAutocomplete

if TYPE_CHECKING:
    from ..core.agent import CodingAgent  # For type hints


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

    # Note: Ctrl+V handled in on_key() to prevent race condition with TextArea's native paste
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
        # Track task for cleanup on unmount
        self._index_task = asyncio.create_task(self._autocomplete.index())

    def on_unmount(self) -> None:
        """Clean up background tasks."""
        if self._index_task and not self._index_task.done():
            self._index_task.cancel()

    def on_key(self, event) -> None:
        """Handle Enter to submit, Ctrl+Enter for newline, Ctrl+V for paste, @ autocomplete."""
        # Handle Ctrl+V - check for image/file first, then text
        if event.key == "ctrl+v":
            try:
                from PIL import ImageGrab
                result = ImageGrab.grabclipboard()

                if result is not None and not isinstance(result, list):
                    # It's an image - handle it and STOP event
                    event.prevent_default()
                    event.stop()
                    import asyncio
                    asyncio.create_task(self._attach_clipboard_image(result))
                    return

                if isinstance(result, list):
                    # It's files - handle them and STOP event
                    event.prevent_default()
                    event.stop()
                    import asyncio
                    asyncio.create_task(self._attach_clipboard_files(result))
                    return
            except Exception as e:
                logger.debug(f"PIL ImageGrab failed (falling back to text): {e}")

            # No image/file - get text from clipboard using our fixed handler
            event.prevent_default()
            event.stop()
            try:
                from .clipboard_handler import ClipboardHandler
                _, _, text = ClipboardHandler.get_clipboard_content()
                if text:
                    # Normalize newlines for cross-platform compatibility
                    text = text.replace("\r\n", self.document.newline)
                    text = text.replace("\r", self.document.newline)
                    # Checkpoint for clean undo history
                    self.history.checkpoint()
                    self.insert(text)
            except Exception as e:
                self.app.notify(f"Paste failed: {e}", severity="error")
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
        # Skip if still indexing (background task not complete yet)
        if not self._autocomplete._indexed:
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

    async def on_paste(self, event: Paste) -> None:
        """Handle paste events - intercept before TextArea's default handler.

        The Paste event contains text in event.text. For images/files,
        we need to check the clipboard separately via on_key().
        """
        event.prevent_default()
        event.stop()

        # Paste event only fires for text - use event.text directly
        if event.text:
            self.insert(event.text)

    async def _attach_clipboard_image(self, image) -> None:
        """Attach image from clipboard (called from on_key with PIL image)."""
        try:
            from io import BytesIO
            output = BytesIO()
            # Convert to RGB if necessary (handles RGBA, P mode images)
            if hasattr(image, 'mode') and image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
            image.save(output, format='PNG')
            att = self.attachments.add_screenshot(output.getvalue(), "png")
            self.app.notify(f"Attached image ({att.size_kb:.1f} KB)")
            self._update_attachment_indicator()
        except Exception as e:
            self.app.notify(f"Failed to attach image: {e}", severity="error")

    async def _attach_clipboard_files(self, files: list) -> None:
        """Attach files from clipboard (called from on_key with file list)."""
        from pathlib import Path
        valid_count = 0
        for file_path in files[:5]:
            if isinstance(file_path, str) and Path(file_path).exists() and Path(file_path).is_file():
                try:
                    att = await self.attachments.add_file(file_path)
                    if att.kind == "image":
                        self.app.notify(f"Attached image ({att.size_kb:.1f} KB)")
                    else:
                        self.app.notify(f"Attached: {att.filename}")
                    valid_count += 1
                except (ValueError, FileNotFoundError, IOError) as e:
                    self.app.notify(f"Failed: {e}", severity="error")

        # Fix #7: Notify if no valid files found in clipboard
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
            raise ValueError("Either 'agent' or 'stream_handler' must be provided")

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

        # Scroll state
        self._auto_scroll = True

        # Retry state
        self._last_user_input: str = ""
        self._last_attachments: List[Attachment] = []
        self._retry_count: int = 0

        # Track pending approvals to manage focus
        self._pending_approval_ids: set[str] = set()

        # Track pause widget
        self._pause_widget: PausePromptWidget | None = None

        # Cache conversation reference (avoid repeated query_one per flush)
        self._conversation: ScrollableContainer | None = None

        # Cache status bar reference (Fix #3: avoid query_one in hot path)
        self._status_bar: StatusBar | None = None

        # Throttle status bar updates (Fix #3: time-based throttling)
        self._last_status_update_ts: float = 0.0
        self._status_update_interval_sec: float = 0.2  # Update at most every 200ms

        # Segmented Streaming mode (default)
        # - segmented: Accumulate text, render as Markdown only at boundaries
        # - full: Stream text incrementally (for debugging)
        self._streaming_mode: Literal["segmented", "full"] = "segmented"

        # Segmented streaming: accumulate text until boundary (tool/code/thinking/end)
        self._segment_chunks: list[str] = []  # Current segment accumulator
        self._segment_chars: int = 0          # For status bar display
        self._segment_flush_handle: asyncio.TimerHandle | None = None  # Timer for delayed flush
        self._segment_flush_interval_sec: float = 0.5  # Flush after 0.5s (Fix #4: faster feedback)
        self._segment_flush_running: bool = False  # Prevent overlapping flushes (Fix #4)

        # Full streaming mode buffers (kept for debug mode)
        self._delta_buffer: list[str] = []
        self._flush_task: asyncio.Task | None = None
        self._flush_interval_sec: float = 0.050  # 50ms
        self._flush_chars_threshold: int = 512
        self._delta_chars: int = 0

    def _create_agent_stream_handler(
        self,
        agent: "CodingAgent"
    ) -> Callable[[str, UIProtocol, Optional[List[Attachment]]], AsyncIterator[UIEvent]]:
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
            attachments: Optional[List[Attachment]] = None
        ) -> AsyncIterator[UIEvent]:
            async for event in agent.stream_response(user_input, ui, attachments):
                yield event

        return handler

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        if self.show_header:
            yield Header()

        yield ScrollableContainer(id="conversation")
        yield AutocompleteDropdown(id="autocomplete")
        yield AttachmentBar(id="attachment-bar")
        yield TodoBar(id="todo-bar")  # Above status bar, hidden until todos exist
        yield StatusBar(model_name=self.model_name, id="status")
        yield ChatInput(id="input")
        yield Footer()

    def on_mount(self) -> None:
        """Focus input on start and initialize mode display."""
        # Install asyncio exception handler to capture unhandled task exceptions
        try:
            from src.observability.logging_config import install_asyncio_handler
            import asyncio
            loop = asyncio.get_running_loop()
            install_asyncio_handler(loop)
        except Exception:
            pass  # Graceful degradation if observability not available

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

        # Note: Signal handlers for SIGINT on Windows with asyncio are problematic.
        # We rely on Textual's Ctrl+C binding (action_interrupt) and the outer
        # try/except KeyboardInterrupt wrapper instead.

    def _focus_input(self) -> None:
        """Set focus to input widget."""
        try:
            input_widget = self.query_one("#input", ChatInput)
            input_widget.focus()
        except Exception as e:
            self.log.error(f"Failed to focus input: {e}")

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

        # Store for potential retry
        self._last_user_input = user_input
        self._last_attachments = attachments  # Store attachments for retry

        # Add user message to conversation (with attachment indicator)
        attachment_summary = ""
        if attachments:
            parts = [f"[{a.kind.upper()}: {a.filename}]" for a in attachments]
            attachment_summary = " " + " ".join(parts)
        await self._add_user_message(user_input + attachment_summary)

        # Start streaming response in a worker - DO NOT await here!
        # This allows Textual to keep processing key events and messages
        # while the stream runs (fixes approval widget keyboard issue)
        self._stream_worker = self.run_worker(
            self._stream_response(user_input, attachments),
            exclusive=True,
            group="stream",
            name="stream-response",
        )

    # Message limit disabled - show all messages
    # Root cause of performance issue was CSS :hover effects, not widget count
    MAX_MOUNTED_MESSAGES = None  # None = no limit

    async def _prune_old_messages(self, conversation: ScrollableContainer) -> None:
        """Remove oldest messages from DOM if over limit.

        Currently disabled (MAX_MOUNTED_MESSAGES = None) since the root cause
        of performance issues was CSS :hover effects, not widget count.
        """
        # No limit - show all messages
        if self.MAX_MOUNTED_MESSAGES is None:
            return

        from .widgets.message import MessageWidget, UserMessage

        # Get all message widgets (both user and assistant)
        messages = list(conversation.query(MessageWidget)) + list(conversation.query(UserMessage))

        if len(messages) > self.MAX_MOUNTED_MESSAGES:
            # Remove oldest messages (they're at the start of the list)
            num_to_remove = len(messages) - self.MAX_MOUNTED_MESSAGES
            for i in range(num_to_remove):
                try:
                    messages[i].remove()
                except Exception:
                    pass  # Widget may already be removed

    async def _add_user_message(self, content: str) -> None:
        """Add user message to conversation."""
        conversation = self.query_one("#conversation", ScrollableContainer)
        user_msg = UserMessage(content=content)
        await conversation.mount(user_msg)
        # Prune old messages to keep DOM small
        await self._prune_old_messages(conversation)
        conversation.scroll_end()

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
    # Streaming
    # -------------------------------------------------------------------------

    async def _stream_response(
        self,
        user_input: str,
        attachments: Optional[List[Attachment]] = None
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
        self._conversation = self.query_one("#conversation", ScrollableContainer)

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
                if self._streaming_mode == "segmented":
                    # Cancel pending timer before flush
                    if self._segment_flush_handle:
                        self._segment_flush_handle.cancel()
                        self._segment_flush_handle = None
                    await self._flush_segment()
                    if self._current_message:
                        await self._current_message.add_text("\n\n[Interrupted]")
                else:
                    await self._cleanup_flush()
                    if self._current_message:
                        self._current_message.append_streaming_text("\n\n[Interrupted]")
                self.notify("Stream interrupted", severity="information", timeout=2)
            else:
                # Non-user cancellation (exclusive worker replacement / lifecycle)
                # Silent cleanup - no [Interrupted] marker
                self.log("Stream worker cancelled (non-user). Silent cleanup.")
                if self._streaming_mode == "segmented":
                    # Cancel pending timer before flush
                    if self._segment_flush_handle:
                        self._segment_flush_handle.cancel()
                        self._segment_flush_handle = None
                    await self._flush_segment()
                else:
                    await self._cleanup_flush()

        except KeyboardInterrupt:
            # Ctrl+C raised as exception (common on Windows)
            if self._streaming_mode == "segmented":
                # Cancel pending timer before flush
                if self._segment_flush_handle:
                    self._segment_flush_handle.cancel()
                    self._segment_flush_handle = None
                await self._flush_segment()
                if self._current_message:
                    await self._current_message.add_text("\n\n[Interrupted by Ctrl+C]")
            else:
                await self._cleanup_flush()
                if self._current_message:
                    self._current_message.append_streaming_text("\n\n[Interrupted by Ctrl+C]")
            self.notify("Stream interrupted by Ctrl+C", severity="information", timeout=2)

        finally:
            # Capture current message to finalize (prevents racing with new stream)
            msg_to_finalize = self._current_message

            # Cleanup based on mode
            if self._streaming_mode == "full":
                await self._cleanup_flush()

            # Reset all streaming state (Fix #6: ensure clean state for next stream)
            self._is_streaming = False
            self._streaming_task = None
            self._user_interrupt_requested = False  # Reset for next stream
            self._segment_flush_running = False  # Fix #6: always reset flush guard

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
        attachments: Optional[List[Attachment]] = None
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
                # Scrolling is now handled by _flush_deltas() at controlled intervals

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
            self.log.error(f"Stream error: {type(e).__name__}: {e}")
            # Flush what we have and show error
            if self._streaming_mode == "segmented":
                # Cancel pending timer before flush
                if self._segment_flush_handle:
                    self._segment_flush_handle.cancel()
                    self._segment_flush_handle = None
                await self._flush_segment()
                if self._current_message:
                    await self._current_message.add_text(f"\n\n[Error: {e}]")
                else:
                    error_msg = AssistantMessage()
                    await conversation.mount(error_msg)
                    await error_msg.add_text(f"[Error: {e}]")
            else:
                await self._cleanup_flush()
                if self._current_message:
                    self._current_message.append_streaming_text(f"\n\n[Error: {e}]")
                else:
                    error_msg = AssistantMessage()
                    await conversation.mount(error_msg)
                    error_msg.start_streaming_text()
                    error_msg.append_streaming_text(f"[Error: {e}]")
            raise

    async def _handle_event(
        self,
        event: UIEvent,
        conversation: ScrollableContainer
    ) -> None:
        """Dispatch event to appropriate handler."""
        match event:
            # Stream lifecycle
            case StreamStart():
                # Capture stream_id to detect stale events after restart/interrupt
                sid = self._stream_id

                # Use local variable to survive race condition where
                # _finalize_current_message() runs during await and sets
                # self._current_message = None
                msg = AssistantMessage()
                self._current_message = msg

                await conversation.mount(msg)

                # Prune old messages to keep DOM small (performance)
                await self._prune_old_messages(conversation)

                # Guard: If interrupted during mount, cleanup may have run
                if msg.parent is None:
                    return  # Widget was removed, stale event
                if self._current_message is not msg:
                    return  # A newer message replaced this one
                if sid != self._stream_id:
                    return  # A new stream started, this event is stale

                # Show loading indicator (with CancelledError protection)
                try:
                    await msg.set_loading(True)
                except asyncio.CancelledError:
                    return  # Cancellation during shutdown/interrupt: safe to ignore

                # Reset segment buffer for new response
                self._segment_chunks = []
                self._segment_chars = 0

                # Full mode: start streaming widget
                if self._streaming_mode == "full" and msg.parent is not None and self._current_message is msg:
                    msg.start_streaming_text()
                    self._delta_buffer = []
                    self._delta_chars = 0

            case StreamEnd(total_tokens=tokens, duration_ms=duration):
                # RACE CONDITION FIX: Capture local reference BEFORE any await
                msg = self._current_message

                # Clear loading on stream end (all end states)
                if msg:
                    try:
                        await msg.set_loading(False)
                    except asyncio.CancelledError:
                        pass  # Safe to ignore during shutdown

                if self._streaming_mode == "segmented":
                    # Cancel pending timer before final flush
                    if self._segment_flush_handle:
                        self._segment_flush_handle.cancel()
                        self._segment_flush_handle = None
                    # Render final segment as Markdown
                    await self._flush_segment()
                else:
                    # Full mode: cleanup and finalize streaming
                    await self._cleanup_flush()
                    # Use captured reference - check parent to ensure still mounted
                    if msg and msg.parent is not None:
                        msg.finalize_streaming_text()

                # Pass captured msg to only clear if it's still current
                self._finalize_current_message(msg)

                # Clear buffers
                self._segment_chunks = []
                self._segment_chars = 0

                if tokens:
                    try:
                        status = self.query_one("#status", StatusBar)
                        status.update_tokens(tokens)
                    except NoMatches:
                        pass

            # Text content
            case TextDelta(content=text):
                if not self._current_message:
                    return

                if self._streaming_mode == "segmented":
                    # Segmented mode: accumulate text, flush after delay if no boundary
                    self._segment_chunks.append(text)
                    self._segment_chars += len(text)

                    # Cancel existing timer, schedule new one (resets countdown on each chunk)
                    # Fix #4: Use method reference instead of lambda to avoid closure issues
                    if self._segment_flush_handle:
                        self._segment_flush_handle.cancel()
                    loop = asyncio.get_running_loop()
                    self._segment_flush_handle = loop.call_later(
                        self._segment_flush_interval_sec,
                        self._schedule_segment_flush  # Method reference, not lambda
                    )

                    # Fix #3: Time-based throttling for buffered char updates (200ms)
                    # Reduces reactive attribute spam from 100+ to ~5 per response
                    now = time.monotonic()
                    if self._status_bar and (now - self._last_status_update_ts) >= self._status_update_interval_sec:
                        self._status_bar.update_buffered_chars(self._segment_chars)
                        self._last_status_update_ts = now
                else:
                    # Full mode: coalesced streaming (for debugging)
                    self._delta_buffer.append(text)
                    self._delta_chars += len(text)
                    if self._buffer_len() >= self._flush_chars_threshold:
                        await self._flush_deltas()
                    else:
                        self._schedule_flush()

            # Code blocks
            case CodeBlockStart(language=lang):
                if self._current_message:
                    # Flush accumulated text before code block
                    if self._streaming_mode == "segmented":
                        # Cancel pending timer before boundary flush
                        if self._segment_flush_handle:
                            self._segment_flush_handle.cancel()
                            self._segment_flush_handle = None
                        await self._flush_segment()
                    else:
                        await self._flush_deltas()
                    self._current_code = self._current_message.start_code_block(lang)

            case CodeBlockDelta(content=code):
                if self._current_message:
                    self._current_message.append_code(code)

            case CodeBlockEnd():
                if self._current_message:
                    self._current_message.end_code_block()
                self._current_code = None

            # Tool calls
            case ToolCallStart(call_id=cid, name=name, arguments=args, requires_approval=req):
                if self._current_message:
                    # Flush accumulated text before tool card
                    if self._streaming_mode == "segmented":
                        # Cancel pending timer before boundary flush
                        if self._segment_flush_handle:
                            self._segment_flush_handle.cancel()
                            self._segment_flush_handle = None
                        await self._flush_segment()
                    else:
                        await self._flush_deltas()
                    card = self._current_message.add_tool_card(cid, name, args, req)
                    self._tool_cards[cid] = card
                    # Track pending approval
                    if req:
                        self._pending_approval_ids.add(cid)
                        # Extra yield to ensure approval widget mounts and can receive focus
                        await asyncio.sleep(0)
                    # Scroll to make approval UI visible
                    card.scroll_visible()

            case ToolCallStatus(call_id=cid, status=status, message=msg):
                if cid in self._tool_cards:
                    self._tool_cards[cid].status = status
                    # Clear pending approval when no longer awaiting
                    if status != ToolStatus.AWAITING_APPROVAL:
                        self._pending_approval_ids.discard(cid)

            case ToolCallResult(call_id=cid, status=status, result=result, error=err, duration_ms=dur):
                if cid in self._tool_cards:
                    card = self._tool_cards[cid]
                    if status == ToolStatus.SUCCESS:
                        card.set_result(result, dur)
                    elif err:
                        card.set_error(err)
                    else:
                        card.status = status
                    # Clear pending approval on result
                    self._pending_approval_ids.discard(cid)

            # Thinking
            case ThinkingStart():
                if self._current_message:
                    # Flush accumulated text before thinking block
                    if self._streaming_mode == "segmented":
                        # Cancel pending timer before boundary flush
                        if self._segment_flush_handle:
                            self._segment_flush_handle.cancel()
                            self._segment_flush_handle = None
                        await self._flush_segment()
                    else:
                        await self._flush_deltas()
                    self._current_thinking = self._current_message.start_thinking()

            case ThinkingDelta(content=text):
                if self._current_message:
                    self._current_message.append_thinking(text)

            case ThinkingEnd(token_count=count):
                if self._current_message:
                    self._current_message.end_thinking(count)
                self._current_thinking = None

            # Errors
            case ErrorEvent(error_type=etype, user_message=err_msg, error_id=eid, recoverable=rec, retry_after=retry):
                # RACE CONDITION FIX: Capture local reference BEFORE await
                current_msg = self._current_message
                if current_msg:
                    try:
                        await current_msg.set_loading(False)
                    except asyncio.CancelledError:
                        pass  # Safe to ignore during shutdown
                await self._handle_error(etype, err_msg, eid, rec, retry)

            # Pause prompt
            case PausePromptStart(reason=reason, reason_code=code, pending_todos=todos, stats=stats):
                # DEBUG: Log pause event receipt
                self.log(f"[PAUSE] PausePromptStart received: reason_code={code}, reason={reason[:50]}...")

                # RACE CONDITION FIX: Capture local references BEFORE any await
                # During _flush_segment(), interrupt/cleanup can set _current_message = None
                msg = self._current_message
                sid = self._stream_id

                self.log(f"[PAUSE] Pre-flush state: msg={msg is not None}, sid={sid}")

                # Cancel pending timer before flush
                if self._segment_flush_handle:
                    self._segment_flush_handle.cancel()
                    self._segment_flush_handle = None

                # Flush any pending text first
                await self._flush_segment()

                # Guard: Check for stale/interrupted state after await
                if msg is None:
                    # No message was active - can't mount pause widget
                    self.log("[PAUSE] GUARD: msg is None - skipping widget mount!")
                    return
                if msg.parent is None:
                    # Message was removed from DOM (interrupted/cleaned up)
                    self.log("[PAUSE] GUARD: msg.parent is None - skipping widget mount!")
                    return
                if sid != self._stream_id:
                    # A new stream started - this event is stale
                    self.log(f"[PAUSE] GUARD: stream_id mismatch ({sid} vs {self._stream_id}) - skipping!")
                    return

                self.log("[PAUSE] Guards passed, mounting widget...")

                # Create and mount pause widget using captured reference
                self._pause_widget = PausePromptWidget(
                    reason=reason,
                    reason_code=code,
                    pending_todos=todos,
                    stats=stats,
                )
                try:
                    await msg.mount(self._pause_widget)
                except asyncio.CancelledError:
                    # Shutdown during mount - cleanup
                    self._pause_widget = None
                    raise

                # Give time for mount before focusing
                await asyncio.sleep(0)

            case PausePromptEnd(continue_work=cont, feedback=fb):
                # Remove pause widget if still present
                if self._pause_widget:
                    self._pause_widget.remove()
                    self._pause_widget = None

                # If continuing, clear error and show spinner (same as normal streaming)
                if cont:
                    try:
                        status_bar = self.query_one("#status", StatusBar)
                        status_bar.clear_error()  # Clear "Request timed out" message
                        status_bar.set_streaming(True)
                    except NoMatches:
                        pass

            # Context window updates
            case ContextUpdated(used=used, limit=limit, pressure_level=pressure):
                try:
                    status_bar = self.query_one("#status", StatusBar)
                    status_bar.update_context(used, limit, pressure)
                except NoMatches:
                    pass

            # Context compaction notification
            case ContextCompacted(messages_removed=removed, tokens_before=before, tokens_after=after):
                try:
                    status_bar = self.query_one("#status", StatusBar)
                    status_bar.show_info(f"Compacting conversation history... ({removed} messages removed)", duration=4.0)
                except NoMatches:
                    pass

    def _finalize_current_message(self, msg: Optional[MessageWidget] = None) -> None:
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
        was_at_bottom = (
            self._conversation.is_vertical_scroll_end
            if self._conversation else True
        )

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

        # Auto-scroll if was at bottom
        if self._auto_scroll and was_at_bottom and self._conversation:
            self._conversation.scroll_end(animate=False)

    def _schedule_segment_flush(self) -> None:
        """
        Schedule segment flush without lambda closure (Fix #4).

        Called by loop.call_later() as a method reference.
        Guards against stale timers and prevents overlapping flushes.
        """
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

    # -------------------------------------------------------------------------
    # Delta Coalescing (Full Streaming Mode - for debugging)
    # -------------------------------------------------------------------------

    def _buffer_len(self) -> int:
        """Get total characters in delta buffer (O(1) via counter)."""
        return self._delta_chars

    def _schedule_flush(self) -> None:
        """Schedule a flush if not already scheduled."""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        """Wait then flush buffered deltas."""
        await asyncio.sleep(self._flush_interval_sec)
        await self._flush_deltas()

    async def _flush_deltas(self) -> None:
        """Flush all buffered deltas to the message widget."""
        if not self._delta_buffer or not self._current_message:
            return

        # CRITICAL: Snapshot scroll position BEFORE appending
        # (appending moves "bottom", so checking after would be wrong)
        was_at_bottom = (
            self._conversation.is_vertical_scroll_end
            if self._conversation else True
        )

        # Join all buffered text - O(n) once per flush, not O(n^2)
        chunk = "".join(self._delta_buffer)
        self._delta_buffer.clear()
        self._delta_chars = 0  # Reset O(1) counter

        # Use streaming-optimized append (Static + Rich Text)
        self._current_message.append_streaming_text(chunk)

        # Scroll only if user WAS at bottom before append
        if self._auto_scroll and was_at_bottom and self._conversation:
            self._conversation.scroll_end(animate=False)

    async def _cleanup_flush(self) -> None:
        """
        Cleanup flush task and flush remaining buffer.

        CRITICAL: Call this before finalize to prevent late appends!
        """
        # RACE CONDITION FIX: Capture local reference BEFORE any await
        msg = self._current_message

        # Cancel pending delayed flush FIRST to prevent race
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        self._flush_task = None

        # Now flush any remaining content (using captured reference)
        if self._delta_buffer and msg and msg.parent is not None:
            chunk = "".join(self._delta_buffer)
            self._delta_buffer.clear()
            self._delta_chars = 0  # Reset O(1) counter
            msg.append_streaming_text(chunk)

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
        import os
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

        # Update tool card status
        if message.call_id in self._tool_cards:
            card = self._tool_cards[message.call_id]
            if approved:
                card.status = ToolStatus.APPROVED
            else:
                card.status = ToolStatus.REJECTED

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
    # Scroll Handling
    # -------------------------------------------------------------------------

    def on_scroll(self) -> None:
        """Detect user scrolling to manage auto-scroll."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            # Disable auto-scroll if user scrolled up
            at_bottom = conversation.scroll_offset.y >= conversation.max_scroll_y - 10
            self._auto_scroll = at_bottom
        except NoMatches:
            pass

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
        import time

        now = time.time()

        # FIX: Safe loading clear (no lambdas, no create_task)
        self._schedule_clear_loading()

        # If there are pending approvals, cancel them instead of interrupting stream
        if self._pending_approval_ids:
            # Reject all pending approvals
            for call_id in list(self._pending_approval_ids):
                self.ui_protocol.submit_action(ApprovalResult(
                    call_id=call_id,
                    approved=False,
                ))
            self.notify("Approval cancelled", severity="information", timeout=2)
            return

        if self._is_streaming:
            # Interrupt the current stream
            self.log("Ctrl+C: Interrupting stream")
            self.notify("Interrupting stream...", severity="warning", timeout=2)

            # Set flag BEFORE cancelling so handler knows this is user-initiated
            self._user_interrupt_requested = True

            self.ui_protocol.submit_action(InterruptSignal())

            # Cancel the worker (primary cancellation mechanism)
            if self._stream_worker is not None:
                self._stream_worker.cancel()

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

    def action_clear_screen(self) -> None:
        """Handle Ctrl+L - clear conversation."""
        try:
            conversation = self.query_one("#conversation", ScrollableContainer)
            conversation.remove_children()
        except NoMatches:
            pass

    def action_toggle_mode(self) -> None:
        """Toggle permission mode: plan -> normal -> auto -> plan"""
        if not self.agent:
            return

        # Cycle through modes
        current = self.agent.get_permission_mode()
        cycle = {"plan": "normal", "normal": "auto", "auto": "plan"}
        next_mode = cycle.get(current, "normal")

        # Update agent
        self.agent.set_permission_mode(next_mode)

        # Update status bar
        try:
            status = self.query_one("#status", StatusBar)
            status.set_mode(next_mode)
        except NoMatches:
            pass

        # Brief notification
        mode_labels = {"plan": "PLAN", "normal": "NORMAL", "auto": "AUTO"}
        self.notify(f"Mode: {mode_labels.get(next_mode, next_mode.upper())}", timeout=1)

    def action_toggle_todos(self) -> None:
        """Toggle todo bar expand/collapse."""
        try:
            todo_bar = self.query_one("#todo-bar", TodoBar)
            todo_bar.toggle()
        except NoMatches:
            pass

    def action_debug_widgets(self) -> None:
        """Debug action: count and log all widgets in the DOM."""
        from .widgets.message import MessageWidget, UserMessage
        from .widgets.tool_card import ToolCard
        from .widgets.code_block import CodeBlock

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
