"""
MessageWidget - Container for a conversation message.

Features:
- Holds multiple content blocks (text, code, tools, thinking)
- Dynamically adds blocks as stream events arrive
- Visual distinction by role (user, assistant, system)
- Tracks current block for streaming updates
- Copy button to copy message content to clipboard

Performance Optimizations:
- Streaming text uses cheap Static + Rich Text (O(1) append)
- Markdown parsing happens ONCE per text block at finalization
- Debug counters available via TUI_PERF_DEBUG=1
"""

from textual.app import ComposeResult
from textual.widgets import Static, Markdown, Button
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from rich.text import Text
from typing import Any, Optional
import os
import re

from .code_block import CodeBlock

from .tool_card import ToolCard
from .thinking import ThinkingBlock

# Performance debug flag - set TUI_PERF_DEBUG=1 to enable
TUI_PERF_DEBUG = os.getenv("TUI_PERF_DEBUG", "").lower() in ("1", "true", "yes")

# Performance counters (global, reset per session if needed)
_perf_counters = {
    "markdown_parses": 0,
    "streaming_appends": 0,
    "widgets_mounted": 0,
}

def get_perf_counters() -> dict:
    """Get current performance counters (for debugging)."""
    return _perf_counters.copy()

def reset_perf_counters() -> None:
    """Reset performance counters."""
    global _perf_counters
    _perf_counters = {
        "markdown_parses": 0,
        "streaming_appends": 0,
        "widgets_mounted": 0,
    }

# Try to import pyperclip for clipboard support
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

# ANSI escape code pattern for stripping
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*m|\x1b\[\?[0-9;]*[a-zA-Z]|\x1b\[[0-9;]*[a-zA-Z]')


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE_PATTERN.sub('', text)


class CopyButton(Static):
    """Small clickable copy button for messages."""

    DEFAULT_CSS = """
    CopyButton {
        width: 6;
        height: 1;
        margin: 0;
        background: #555555;
    }

    CopyButton:hover {
        background: #0077cc;
    }
    """

    def __init__(self, message_widget: "MessageWidget"):
        # Use Rich Text object to force text rendering (no background - CSS handles it)
        label = Text("[Copy]", style="bold white")
        super().__init__(label)
        self.message_widget = message_widget

    def on_click(self, event) -> None:
        """Handle click to copy."""
        event.stop()
        self._do_copy()

    def _do_copy(self) -> None:
        """Copy message content to clipboard."""
        text = self.message_widget.get_plain_text()
        # FIX 3: Handle empty content gracefully (e.g., during loading state)
        if not text or not text.strip():
            self.app.notify("Nothing to copy yet", severity="warning", timeout=1)
            return
        if not HAS_PYPERCLIP:
            self.app.notify("pyperclip not installed", severity="warning", timeout=3)
            return
        try:
            pyperclip.copy(text)
            self.app.notify("Copied to clipboard", timeout=2)
        except Exception as e:
            self.app.notify(f"Copy failed: {e}", severity="error", timeout=3)


class MessageHeader(Horizontal):
    """Compact header row with copy button only (role indicated by border color)."""

    DEFAULT_CSS = """
    MessageHeader {
        height: 1;
        width: 100%;
        layout: horizontal;
        padding: 0;
        margin: 0;
        align: right middle;
    }

    MessageHeader > CopyButton {
        width: 6;
        height: 1;
        margin: 0;
    }
    """

    def __init__(self, role: str, message_widget: "MessageWidget"):
        super().__init__()
        self.role = role
        self.message_widget = message_widget

    def compose(self) -> ComposeResult:
        # Role label removed - border color indicates speaker
        yield CopyButton(self.message_widget)


class MessageWidget(Vertical):
    """
    Container for a single conversation message.

    Holds multiple blocks that are added dynamically as stream events arrive:
    - Markdown (text content)
    - CodeBlock (syntax-highlighted code)
    - ToolCard (tool execution)
    - ThinkingBlock (collapsible reasoning)

    Usage:
        # Create message
        msg = MessageWidget(role="assistant")
        await container.mount(msg)

        # Add content blocks
        msg.add_text("Here's what I found:\\n")

        # Add code block
        code = msg.start_code_block("python")
        msg.append_code("print('hello')\\n")
        msg.end_code_block()

        # Add tool card
        card = msg.add_tool_card("c1", "read_file", {"path": "x.py"}, True)
        card.set_result("contents", 50)

    Attributes:
        role: Message role ("user", "assistant", "system")
    """

    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    MessageWidget.user {
        border-left: thick $primary;
    }

    MessageWidget.assistant {
        border-left: thick $secondary;
    }

    MessageWidget.system {
        border-left: thick $warning;
        opacity: 0.8;
    }

    MessageWidget > Markdown {
        margin: 0;
        padding: 0;
    }

    MessageWidget > .streaming-text {
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, role: str, **kwargs):
        """
        Initialize MessageWidget.

        Args:
            role: Message role ("user", "assistant", "system")
            **kwargs: Additional arguments for Vertical
        """
        super().__init__(**kwargs)
        self.role = role
        self.add_class(role)

        # Track widgets for updates
        self._blocks: list[Static] = []
        self._current_markdown: Markdown | None = None
        self._current_code: CodeBlock | None = None
        self._current_thinking: ThinkingBlock | None = None
        self._tool_cards: dict[str, ToolCard] = {}

        # Track accumulated markdown text
        self._markdown_text: str = ""

        # Initial content for subclasses (set in compose)
        self._initial_content: str = ""

        # Streaming optimization: use Static + Rich Text during stream,
        # convert to Markdown only once at end (avoids O(n^2) Markdown reparses)
        self._streaming_widget: Static | None = None
        self._streaming_text: Text | None = None  # Rich Text object for O(1) appends
        self._is_streaming_mode: bool = False

    def compose(self) -> ComposeResult:
        """Compose the message with header containing copy button."""
        yield MessageHeader(self.role, self)

    # -------------------------------------------------------------------------
    # Text Content
    # -------------------------------------------------------------------------

    async def add_text(self, content: str) -> None:
        """
        Append text to current markdown block, or create a new one.

        Text content is accumulated and rendered as Markdown.

        Args:
            content: Text content to append (markdown supported)
        """
        # Strip ANSI escape codes - Markdown widget expects plain text
        content = strip_ansi_codes(content)

        # If we were in code mode, end it
        self._current_code = None

        if self._current_markdown is None:
            # Create new markdown widget
            self._markdown_text = ""
            self._current_markdown = Markdown("")
            self._blocks.append(self._current_markdown)
            await self.mount(self._current_markdown)

        # Append content and update (update() already triggers refresh internally)
        self._markdown_text += content
        self._current_markdown.update(self._markdown_text)

    async def set_text(self, content: str) -> None:
        """
        Replace all text in current markdown block.

        Args:
            content: New text content
        """
        # Strip ANSI escape codes - Markdown widget expects plain text
        content = strip_ansi_codes(content)

        if self._current_markdown is None:
            self._current_markdown = Markdown("")
            self._blocks.append(self._current_markdown)
            await self.mount(self._current_markdown)

        self._markdown_text = content
        self._current_markdown.update(self._markdown_text)

    # -------------------------------------------------------------------------
    # Streaming Text (Performance Optimized)
    # -------------------------------------------------------------------------

    def start_streaming_text(self) -> None:
        """
        Start streaming mode - uses Static + Rich Text for O(1) appends.

        During streaming, text is rendered as plain text (no Markdown parsing).
        Call finalize_streaming_text() at stream end to convert to Markdown.

        This is the CHEAP path - use append_streaming_text() to add content,
        then finalize_streaming_text() for ONE Markdown parse at the end.
        """
        # End any current text/code block
        self._current_code = None
        self._current_markdown = None

        self._is_streaming_mode = True
        self._markdown_text = ""  # Reset accumulator for this text block
        self._streaming_text = Text()  # Rich Text object - O(1) append
        self._streaming_widget = Static(self._streaming_text, classes="streaming-text")
        self._blocks.append(self._streaming_widget)
        self.mount(self._streaming_widget)

        _perf_counters["widgets_mounted"] += 1

    def append_streaming_text(self, content: str) -> None:
        """
        Append text during streaming - O(1) via Rich Text.append().

        Auto-starts streaming mode if not active (e.g., after tool card).
        This is the CHEAP path - no Markdown parsing happens here.

        Args:
            content: Text content to append (already coalesced by caller)
        """
        content = strip_ansi_codes(content)

        # Auto-start streaming mode if not active (e.g., text after tool card)
        if not self._is_streaming_mode:
            self.start_streaming_text()

        if self._streaming_text is not None:
            # O(1) amortized append to Rich Text object
            self._streaming_text.append(content)

            # Track for accumulated text (used by finalize)
            self._markdown_text += content

            if self._streaming_widget is not None:
                # Update Static widget with the same Text object
                self._streaming_widget.update(self._streaming_text)

            # Performance counter
            _perf_counters["streaming_appends"] += 1

    def finalize_streaming_text(self, override_text: str | None = None) -> None:
        """
        Convert streaming text to Markdown - called once at stream end.

        This is the ONLY Markdown parse for the entire text block.
        Performance: O(n) once, instead of O(n^2) from repeated parses.

        Args:
            override_text: If provided, use this text instead of the streaming
                          widget content. Used by smart streaming mode to render
                          the full response (not just the streamed preview).
        """
        if not self._is_streaming_mode:
            return

        # Get final text: override (smart mode) or accumulated markdown_text
        if override_text is not None:
            final_text = override_text
        elif self._markdown_text:
            # Use accumulated text (tracked in append_streaming_text)
            final_text = self._markdown_text
        elif self._streaming_text is not None:
            # Fallback to streaming widget content
            final_text = self._streaming_text.plain
        else:
            final_text = ""

        # Remove the streaming widget (preview in smart mode)
        if self._streaming_widget is not None:
            self._streaming_widget.remove()
            if self._streaming_widget in self._blocks:
                self._blocks.remove(self._streaming_widget)

        # Create final Markdown widget (ONE-TIME parse - this is the key optimization)
        if final_text:
            self._markdown_text = final_text
            self._current_markdown = Markdown(final_text)
            self._blocks.append(self._current_markdown)
            self.mount(self._current_markdown)

            # Performance counter - this should be ~1 per text block
            _perf_counters["markdown_parses"] += 1
            _perf_counters["widgets_mounted"] += 1

            if TUI_PERF_DEBUG:
                # Lazy import to avoid circular imports
                try:
                    from src.observability import get_logger
                    logger = get_logger("tui.perf")
                    logger.debug(
                        "markdown_finalized",
                        text_len=len(final_text),
                        total_parses=_perf_counters["markdown_parses"],
                        streaming_appends=_perf_counters["streaming_appends"],
                    )
                except ImportError:
                    pass

        # Reset streaming state
        self._streaming_widget = None
        self._streaming_text = None
        self._is_streaming_mode = False

    # -------------------------------------------------------------------------
    # Code Blocks
    # -------------------------------------------------------------------------

    def start_code_block(self, language: str) -> CodeBlock:
        """
        Start a new code block.

        Args:
            language: Programming language for syntax highlighting

        Returns:
            The CodeBlock widget for direct updates
        """
        # Finalize streaming text if active (convert to Markdown)
        if self._is_streaming_mode:
            self.finalize_streaming_text()

        # End any current text or code block
        self._current_markdown = None
        if self._current_code:
            self._current_code.finalize()

        block = CodeBlock(language=language, is_streaming=True)

        self._blocks.append(block)
        self._current_code = block
        self.mount(block)

        return block

    def append_code(self, content: str) -> None:
        """
        Append to current code block.

        Args:
            content: Code content to append
        """
        if self._current_code:
            self._current_code.append(content)

    def end_code_block(self) -> None:
        """Finalize current code block."""
        if self._current_code:
            self._current_code.finalize()
            self._current_code = None

    def get_current_code_block(self) -> CodeBlock | None:
        """Get the current code block if one is active."""
        return self._current_code

    # -------------------------------------------------------------------------
    # Tool Cards
    # -------------------------------------------------------------------------

    def add_tool_card(
        self,
        call_id: str,
        tool_name: str,
        args: dict[str, Any],
        requires_approval: bool,
    ) -> ToolCard:
        """
        Add a tool card.

        Args:
            call_id: Unique identifier for tracking
            tool_name: Tool function name
            args: Tool arguments dictionary
            requires_approval: Whether user must approve

        Returns:
            The ToolCard widget for status updates
        """
        # Finalize streaming text if active (convert to Markdown before tool card)
        if self._is_streaming_mode:
            self.finalize_streaming_text()

        # End text/code mode
        self._current_markdown = None
        if self._current_code:
            self._current_code.finalize()
            self._current_code = None

        card = ToolCard(
            call_id=call_id,
            tool_name=tool_name,
            args=args,
            requires_approval=requires_approval,
        )

        self._blocks.append(card)
        self._tool_cards[call_id] = card
        self.mount(card)

        return card

    def get_tool_card(self, call_id: str) -> ToolCard | None:
        """
        Get a tool card by call ID.

        Args:
            call_id: Tool call identifier

        Returns:
            The ToolCard widget or None if not found
        """
        return self._tool_cards.get(call_id)

    def get_all_tool_cards(self) -> dict[str, ToolCard]:
        """Get all tool cards in this message."""
        return self._tool_cards.copy()

    # -------------------------------------------------------------------------
    # Thinking Blocks
    # -------------------------------------------------------------------------

    def start_thinking(self) -> ThinkingBlock:
        """
        Start a thinking block.

        Returns:
            The ThinkingBlock widget for live updates
        """
        # Finalize streaming text if active (convert to Markdown before thinking block)
        if self._is_streaming_mode:
            self.finalize_streaming_text()

        # End text/code mode
        self._current_markdown = None
        if self._current_code:
            self._current_code.finalize()
            self._current_code = None

        block = ThinkingBlock()
        self._blocks.append(block)
        self._current_thinking = block
        self.mount(block)

        return block

    def append_thinking(self, content: str) -> None:
        """
        Append to current thinking block.

        Args:
            content: Thinking content to append
        """
        if self._current_thinking:
            self._current_thinking.append(content)

    def end_thinking(self, token_count: int | None = None) -> None:
        """
        Finalize current thinking block.

        Args:
            token_count: Number of tokens used in thinking
        """
        if self._current_thinking:
            self._current_thinking.finalize(token_count)
            self._current_thinking = None

    def get_current_thinking_block(self) -> ThinkingBlock | None:
        """Get the current thinking block if one is active."""
        return self._current_thinking

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def finalize(self) -> None:
        """
        Finalize all blocks in the message.

        Call this when the message is complete.
        """
        # Finalize streaming text first (converts to Markdown)
        if self._is_streaming_mode:
            self.finalize_streaming_text()

        if self._current_code:
            self._current_code.finalize()
            self._current_code = None

        if self._current_thinking:
            self._current_thinking.finalize()
            self._current_thinking = None

        self._current_markdown = None

    def get_block_count(self) -> int:
        """Get number of content blocks."""
        return len(self._blocks)

    def get_tool_card_count(self) -> int:
        """Get number of tool cards."""
        return len(self._tool_cards)

    def get_plain_text(self) -> str:
        """
        Get all text content from the message as plain text.

        Collects text from:
        - Markdown blocks
        - Code blocks
        - Tool cards (name and result summary)
        - Thinking blocks

        Returns:
            Plain text content suitable for clipboard
        """
        parts = []

        # Get streaming text if still in streaming mode
        if self._is_streaming_mode and self._streaming_text:
            parts.append(self._streaming_text.plain)
        # Otherwise use markdown text (accumulated during message building)
        elif self._markdown_text:
            parts.append(self._markdown_text)

        # Get text from code blocks, tool cards, and thinking blocks
        for block in self._blocks:
            if isinstance(block, CodeBlock):
                # Get code content from reactive attribute
                if block.code:
                    lang = block.language or ""
                    parts.append(f"```{lang}\n{block.code}\n```")
            elif isinstance(block, ToolCard):
                # Get tool info
                tool_text = f"[Tool: {block.tool_name}]"
                parts.append(tool_text)
            elif isinstance(block, ThinkingBlock):
                # Get thinking content from reactive attribute
                if block.content:
                    parts.append(f"<thinking>\n{block.content}\n</thinking>")

        return "\n\n".join(parts) if parts else ""

    def clear(self) -> None:
        """
        Clear all content from the message.

        Removes all blocks and resets state.
        """
        for block in self._blocks:
            block.remove()

        self._blocks.clear()
        self._tool_cards.clear()
        self._current_markdown = None
        self._current_code = None
        self._current_thinking = None
        self._markdown_text = ""


class UserMessage(MessageWidget):
    """Convenience class for user messages."""

    def __init__(self, content: str = "", **kwargs):
        super().__init__(role="user", **kwargs)
        self._initial_content = content

    def compose(self) -> ComposeResult:
        """Compose the header and initial content."""
        # Yield header with copy button from parent
        yield from super().compose()
        # Add initial content
        if self._initial_content:
            self._markdown_text = self._initial_content
            self._current_markdown = Markdown(self._initial_content)
            self._blocks.append(self._current_markdown)
            yield self._current_markdown


class AssistantMessage(MessageWidget):
    """Assistant message with loading state support."""

    def __init__(self, **kwargs):
        super().__init__(role="assistant", **kwargs)
        # Loading state
        self.is_loading: bool = False
        self._loading_widget: Optional[Widget] = None
        self._loading_timer: Optional[Timer] = None

    async def set_loading(self, on: bool) -> None:
        """
        Toggle loading indicator (async-safe).

        Args:
            on: True to show loading, False to hide
        """
        if on and not self.is_loading:
            self.is_loading = True
            # FIX 1: Timer callback must be SYNC, use call_next for async mount
            # 200ms delay prevents flicker for fast responses
            self._loading_timer = self.set_timer(0.2, self._schedule_show_loading)
        elif not on and self.is_loading:
            self.is_loading = False
            if self._loading_timer:
                self._loading_timer.stop()
                self._loading_timer = None
            if self._loading_widget:
                await self._loading_widget.remove()
                self._loading_widget = None

    def _schedule_show_loading(self) -> None:
        """SYNC timer callback - schedules async mount via call_next."""
        if self.is_loading and not self._loading_widget:
            self.app.call_next(self._mount_loading_widget)

    async def _mount_loading_widget(self) -> None:
        """Actually mount the loading widget (async).

        Re-checks state after being scheduled via call_next - state may have
        been cleared by set_loading(False) in the meantime (race condition fix).
        """
        # Double-check both conditions to prevent race condition:
        # 1. is_loading could be False if set_loading(False) was called
        # 2. _loading_widget could be set if mounted twice somehow
        if self.is_loading and self._loading_widget is None:
            self._loading_widget = Static("Thinking...", classes="loading-indicator")
            await self.mount(self._loading_widget)

    async def add_text(self, content: str) -> None:
        """Add text content, clearing loading state first."""
        if self.is_loading:
            await self.set_loading(False)
        await super().add_text(content)

    def on_unmount(self) -> None:
        """Clean up timer when widget is removed from DOM."""
        if self._loading_timer:
            self._loading_timer.stop()
            self._loading_timer = None


class SystemMessage(MessageWidget):
    """Convenience class for system messages."""

    def __init__(self, content: str = "", **kwargs):
        super().__init__(role="system", **kwargs)
        self._initial_content = content

    def compose(self) -> ComposeResult:
        """Compose the header and initial content."""
        # Yield header with copy button from parent
        yield from super().compose()
        # Add initial content
        if self._initial_content:
            self._markdown_text = self._initial_content
            self._current_markdown = Markdown(self._initial_content)
            self._blocks.append(self._current_markdown)
            yield self._current_markdown
