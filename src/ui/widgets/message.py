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

import os
import re
from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Markdown, Static

from .code_block import CodeBlock
from .thinking import ThinkingBlock
from .tool_card import ToolCard

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
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m|\x1b\[\?[0-9;]*[a-zA-Z]|\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


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

        # Content segments for accurate copying (stores text as blocks are added)
        self._segments: list[str] = []

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
            # Start new segment
            self._segments.append("")

        # Append content and update (update() already triggers refresh internally)
        self._markdown_text += content
        self._current_markdown.update(self._markdown_text)

        # Update the current segment
        if self._segments:
            self._segments[-1] = self._markdown_text

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
            # Start new segment
            self._segments.append(content)
        else:
            # Update existing segment
            if self._segments:
                self._segments[-1] = content

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

            # Store text segment for copying
            self._segments.append(final_text)

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

        # Start new segment for code block (will be updated in append_code/end_code_block)
        self._segments.append("")

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
            # Update segment with final code content
            if self._segments:
                lang = self._current_code.language or ""
                code = self._current_code.code or ""
                self._segments[-1] = f"```{lang}\n{code}\n```"
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
        suppress_approval_ui: bool = False,
    ) -> ToolCard:
        """
        Add a tool card.

        Args:
            call_id: Unique identifier for tracking
            tool_name: Tool function name
            args: Tool arguments dictionary
            requires_approval: Whether user must approve
            suppress_approval_ui: If True, don't mount approval widget inline

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
            suppress_approval_ui=suppress_approval_ui,
        )

        self._blocks.append(card)
        self._tool_cards[call_id] = card
        self.mount(card)

        # Add tool card segment (will be updated when result is set)
        # Store call_id as marker to update later
        self._segments.append(f"[Tool: {tool_name}]")

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

        # Start new segment for thinking block (will be updated in end_thinking)
        self._segments.append("")

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
            # Update segment with final thinking content
            if self._segments:
                content = self._current_thinking.content or ""
                self._segments[-1] = f"<thinking>\n{content}\n</thinking>"
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

        Uses pre-stored content segments for accurate copying.
        For tool cards, extracts current result/error from the widget.
        Handles streaming mode by including current streaming text.

        Returns:
            Plain text content suitable for clipboard
        """
        # Build final segments list with tool card results
        final_segments = []
        tool_card_index = 0

        for _i, segment in enumerate(self._segments):
            # Check if this segment is a tool card placeholder
            if segment.startswith("[Tool: "):
                # Find corresponding tool card and extract result
                if tool_card_index < len(self._tool_cards):
                    tool_card = list(self._tool_cards.values())[tool_card_index]
                    tool_card_index += 1

                    # Build tool card text with result/error
                    tool_text = f"[Tool: {tool_card.tool_name}]"
                    if tool_card.result_preview:
                        tool_text += f"\nResult: {tool_card.result_preview}"
                    elif tool_card.error_message:
                        tool_text += f"\nError: {tool_card.error_message}"

                    final_segments.append(tool_text)
                else:
                    # Fallback to placeholder if tool card not found
                    final_segments.append(segment)
            else:
                # Regular segment (text, code, thinking, attachment)
                final_segments.append(segment)

        # If in streaming mode, include current streaming text
        if self._is_streaming_mode and self._streaming_text:
            final_segments.append(self._streaming_text.plain)

        return "\n\n".join(final_segments) if final_segments else ""

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
        self._segments.clear()


class ClickableAttachmentPlaceholder(Static):
    """Clickable attachment placeholder that opens file in external viewer."""

    DEFAULT_CSS = """
    ClickableAttachmentPlaceholder {
        width: auto;
        height: 1;
        color: $accent;
        text-style: underline;
    }

    ClickableAttachmentPlaceholder:hover {
        color: $accent-lighten-2;
        text-style: bold underline;
    }
    """

    def __init__(
        self,
        attachment_type: str,
        attachment_num: int,
        attachment_data: str,
        filename: str = "",
        message_uuid: str = "",
    ):
        """
        Initialize clickable attachment placeholder.

        Args:
            attachment_type: Type of attachment ("image" or "file")
            attachment_num: Attachment sequence number (1-indexed)
            attachment_data: Data (base64 data URL for images, text content for files)
            filename: Original filename (for files)
            message_uuid: UUID of the message containing this attachment
        """
        if attachment_type == "image":
            label = f"[Image #{attachment_num}]"
        else:
            label = f"[File #{attachment_num}: {filename}]"

        super().__init__(label)
        self.attachment_type = attachment_type
        self.attachment_num = attachment_num
        self.attachment_data = attachment_data
        self.filename = filename
        self.message_uuid = message_uuid

    def on_click(self, event) -> None:
        """Handle click to open attachment in external viewer."""
        event.stop()
        self._open_attachment()

    def _open_attachment(self) -> None:
        """Open attachment in system viewer."""
        import base64
        import os
        import platform
        import subprocess
        import tempfile

        try:
            if self.attachment_type == "image":
                self._open_image()
            else:
                self._open_file()
        except Exception as e:
            self.app.notify(f"Failed to open attachment: {e}", severity="error", timeout=3)

    def _open_image(self) -> None:
        """Decode base64 image and open in system viewer."""
        import base64
        import os
        import platform
        import subprocess
        import tempfile

        # Extract base64 data from data URL
        if not self.attachment_data.startswith("data:image/"):
            self.app.notify("Invalid image data", severity="error", timeout=3)
            return

        # Parse data URL: data:image/png;base64,<data>
        parts = self.attachment_data.split(",", 1)
        if len(parts) != 2:
            self.app.notify("Invalid image format", severity="error", timeout=3)
            return

        # Extract MIME type and extension
        header = parts[0]  # data:image/png;base64
        data = parts[1]  # base64 data

        # Decode base64
        img_bytes = base64.b64decode(data)

        # Save to temporary file with original filename
        if self.filename:
            # Use original filename in temp directory
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, self.filename)

            with open(temp_path, "wb") as f:
                f.write(img_bytes)
        else:
            # Fallback: generate temp name with extension from MIME type
            ext = self._get_extension_from_mime(header)
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
                f.write(img_bytes)
                temp_path = f.name

        # Open in system viewer
        system = platform.system()
        if system == "Windows":
            os.startfile(temp_path)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", temp_path])
        else:  # Linux
            subprocess.run(["xdg-open", temp_path])

        # Show notification with actual filename
        actual_filename = os.path.basename(temp_path)
        self.app.notify(f"Opening: {actual_filename}", timeout=3)

    def _get_extension_from_mime(self, mime_header: str) -> str:
        """Extract file extension from MIME type header."""
        if "png" in mime_header:
            return ".png"
        elif "jpeg" in mime_header or "jpg" in mime_header:
            return ".jpg"
        elif "gif" in mime_header:
            return ".gif"
        elif "webp" in mime_header:
            return ".webp"
        else:
            return ".png"  # Default

    def _open_file(self) -> None:
        """Save text file and open in system viewer."""
        import os
        import platform
        import subprocess
        import tempfile

        # Save to temporary file with original filename
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, self.filename)

        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(self.attachment_data)

        # Open in system viewer
        system = platform.system()
        if system == "Windows":
            os.startfile(temp_path)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", temp_path])
        else:  # Linux
            subprocess.run(["xdg-open", temp_path])

        self.app.notify(f"Opening {self.filename}...", timeout=2)


class UserMessage(MessageWidget):
    """Convenience class for user messages."""

    def __init__(self, content: Any = "", message_uuid: str = "", **kwargs):
        """
        Initialize user message.

        Args:
            content: Message content (string or multimodal list)
            message_uuid: UUID of the message (for image retrieval)
            **kwargs: Additional arguments for MessageWidget
        """
        super().__init__(role="user", **kwargs)
        self._raw_content = content
        self._message_uuid = message_uuid
        self._has_attachments = isinstance(content, list) and any(
            isinstance(item, dict) and item.get("type") in ("image_url", "text") for item in content
        )
        self._pending_annotations: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose the header and content with clickable attachment placeholders."""
        # Yield header with copy button from parent
        yield from super().compose()

        # Handle multimodal content with clickable attachments
        if self._has_attachments:
            yield from self._compose_multimodal_content()
        else:
            # Simple text content
            text_content = self._extract_text_only(self._raw_content)
            if text_content:
                self._markdown_text = text_content
                self._current_markdown = Markdown(text_content)
                self._blocks.append(self._current_markdown)
                self._segments.append(text_content)
                yield self._current_markdown

    def _compose_multimodal_content(self) -> ComposeResult:
        """Compose multimodal content with clickable attachment placeholders."""
        if not isinstance(self._raw_content, list):
            return

        image_count = 0
        file_count = 0
        text_parts = []

        for item in self._raw_content:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type", "")

            if item_type == "text":
                text = item.get("text", "")
                if not text:
                    continue

                # Check if this is a file attachment (has file header)
                if text.startswith("--- BEGIN FILE:"):
                    # Flush accumulated text before file
                    if text_parts:
                        text_content = " ".join(text_parts)
                        markdown = Markdown(text_content)
                        self._blocks.append(markdown)
                        self._segments.append(text_content)
                        yield markdown
                        text_parts = []

                    # Extract filename from structured field (with backward compatibility)
                    filename = item.get("filename")

                    if not filename:
                        # Backward compatibility: parse from text header
                        # Format: --- BEGIN FILE: filename.txt ---
                        try:
                            header_line = text.split("\n")[0]
                            filename = (
                                header_line.split("--- BEGIN FILE:")[1].split("---")[0].strip()
                            )
                        except Exception:
                            filename = "attachment.txt"

                    # Create clickable file placeholder
                    file_count += 1
                    placeholder = ClickableAttachmentPlaceholder(
                        attachment_type="file",
                        attachment_num=file_count,
                        attachment_data=text,
                        filename=filename,
                        message_uuid=self._message_uuid,
                    )
                    self._blocks.append(placeholder)
                    # Add file content to segments (the actual file text)
                    self._segments.append(text)
                    yield placeholder
                else:
                    # Regular text - accumulate
                    text_parts.append(text)

            elif item_type == "image_url":
                # Flush accumulated text before image
                if text_parts:
                    text_content = " ".join(text_parts)
                    markdown = Markdown(text_content)
                    self._blocks.append(markdown)
                    self._segments.append(text_content)
                    yield markdown
                    text_parts = []

                # Create clickable image placeholder
                image_count += 1
                image_url = item.get("image_url", {})
                data_url = (
                    image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
                )

                # Extract filename from structured field (with fallback)
                filename = item.get("filename", f"image_{image_count}.png")

                # Debug: Log extracted filename
                from src.observability import get_logger

                logger = get_logger(__name__)
                logger.debug(
                    "image_filename_extracted",
                    filename=filename,
                    has_filename_field=("filename" in item),
                )

                placeholder = ClickableAttachmentPlaceholder(
                    attachment_type="image",
                    attachment_num=image_count,
                    attachment_data=data_url,
                    filename=filename,
                    message_uuid=self._message_uuid,
                )
                self._blocks.append(placeholder)
                # Add image placeholder to segments
                self._segments.append(f"[Image: {filename}]")
                yield placeholder

        # Flush remaining text
        if text_parts:
            text_content = " ".join(text_parts)
            markdown = Markdown(text_content)
            self._blocks.append(markdown)
            self._segments.append(text_content)
            yield markdown

    @staticmethod
    def _extract_text_only(content: Any) -> str:
        """
        Extract plain text from content (for simple text messages).

        Args:
            content: Message content (string or list)

        Returns:
            Plain text string
        """
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return str(content) if content is not None else ""

        # Extract text parts only (images handled separately)
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)

        return " ".join(parts) if parts else ""

    async def add_annotation(self, label: str) -> None:
        """Add a dim annotation line below the message content.

        Used for file-read confirmations (e.g., "Read demo.py (98 lines)")
        and interruption notices.

        Args:
            label: Annotation text (e.g., " L  Read file.py (42 lines)")
        """
        # Buffer annotations and defer mounting to after the next refresh
        # cycle.  This avoids a race where add_annotation runs before
        # compose() has finished yielding children (MessageHeader,
        # Markdown).  call_after_refresh guarantees compose is complete,
        # so mount() appends after all content widgets.
        self._pending_annotations.append(label)
        self.call_after_refresh(self._mount_pending_annotations)

    def _mount_pending_annotations(self) -> None:
        """Mount buffered annotations at the end of children."""
        if not self._pending_annotations:
            return
        labels = self._pending_annotations[:]
        self._pending_annotations.clear()
        for label in labels:
            annotation = Static(label, classes="user-annotation")
            annotation.styles.color = "#6e7681"
            annotation.styles.height = "auto"
            annotation.styles.margin = (0, 0, 0, 1)
            self.mount(annotation)
        self._blocks.append(annotation)


class AssistantMessage(MessageWidget):
    """Assistant message with loading state support."""

    def __init__(self, **kwargs):
        super().__init__(role="assistant", **kwargs)
        # Loading state
        self.is_loading: bool = False
        self._loading_widget: Widget | None = None
        self._loading_timer: Timer | None = None

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
            self._segments.append(self._initial_content)
            yield self._current_markdown
