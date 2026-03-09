"""
CodeBlock - Syntax-highlighted code with live streaming updates.

Features:
- Live updates during streaming (code appears progressively)
- Syntax highlighting via Rich's Syntax
- Line numbers
- Language indicator in title
- Visual distinction between streaming and complete states
"""

from rich.console import RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class CodeBlock(Static):
    """
    Syntax-highlighted code block with streaming support.

    Usage:
        # Create and mount
        block = CodeBlock(language="python")
        await container.mount(block)

        # Stream content
        block.append("def hello():\\n")
        block.append("    print('world')\\n")

        # Finalize when complete
        block.finalize()

    Attributes:
        code: The accumulated code content
        language: Programming language for syntax highlighting
        is_streaming: Whether still receiving content
    """

    # Reactive attributes trigger re-render on change
    # Note: layout=True removed for performance - prevents forced layout recalc per append
    code = reactive("")
    language = reactive("text")
    is_streaming = reactive(True)

    DEFAULT_CSS = """
    CodeBlock {
        margin: 1 0;
        height: auto;
        min-height: 3;
    }

    CodeBlock.streaming {
        border: round $warning;
    }

    CodeBlock.complete {
        border: round $success;
    }
    """

    def __init__(self, code: str = "", language: str = "text", is_streaming: bool = True, **kwargs):
        """
        Initialize CodeBlock.

        Args:
            code: Initial code content
            language: Programming language for highlighting
            is_streaming: Whether still receiving content
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self.code = code
        self.language = language or "text"
        self.is_streaming = is_streaming
        self._update_classes()

    def _update_classes(self) -> None:
        """Update CSS classes based on streaming state."""
        self.remove_class("streaming", "complete")
        if self.is_streaming:
            self.add_class("streaming")
        else:
            self.add_class("complete")

    def watch_is_streaming(self, is_streaming: bool) -> None:
        """React to streaming state changes."""
        self._update_classes()

    def render(self) -> RenderableType:
        """Render the code block with syntax highlighting."""
        if not self.code:
            # Empty placeholder during streaming
            content = Text("...", style="dim italic")
        else:
            # Syntax highlighted code
            # Use a safe theme that works in most terminals
            content = Syntax(
                self.code,
                self.language,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                background_color="default",
            )

        # Build title with language and streaming indicator
        title_parts = [self.language]
        if self.is_streaming:
            title_parts.append("[dim]...[/dim]")

        title = " ".join(title_parts)

        # Border style indicates streaming state
        if self.is_streaming:
            border_style = "yellow"
        else:
            border_style = "green"

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
        )

    def append(self, content: str) -> None:
        """
        Append content during streaming.

        Args:
            content: Code content to append
        """
        self.code += content

    def set_code(self, code: str) -> None:
        """
        Replace all code content.

        Args:
            code: New code content
        """
        self.code = code

    def finalize(self) -> None:
        """Mark as complete (no longer streaming)."""
        self.is_streaming = False

    def clear(self) -> None:
        """Clear all code content."""
        self.code = ""

    @property
    def line_count(self) -> int:
        """Get number of lines in the code."""
        if not self.code:
            return 0
        return self.code.count("\n") + (1 if not self.code.endswith("\n") else 0)
