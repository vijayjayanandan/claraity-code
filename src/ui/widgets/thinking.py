"""
ThinkingBlock - Collapsible thinking/reasoning section.

Features:
- Collapsed by default (don't overwhelm user with internal reasoning)
- Click to expand/collapse
- Shows preview when collapsed
- Displays token count when complete
- Streams content progressively
"""

from rich.console import RenderableType
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class ThinkingBlock(Static):
    """
    Collapsible thinking/reasoning block.

    Used to display the model's internal reasoning process (Claude's
    extended thinking, chain-of-thought, etc.).

    Usage:
        # Create and mount
        block = ThinkingBlock()
        await container.mount(block)

        # Stream content
        block.append("Analyzing the problem...\\n")
        block.append("Step 1: Consider the constraints...\\n")

        # Finalize with token count
        block.finalize(token_count=150)

        # User can click to expand/collapse

    Attributes:
        content: The thinking content (markdown)
        is_complete: Whether thinking is finished
        token_count: Number of tokens used (shown when complete)
        expanded: Whether content is expanded or collapsed
    """

    # Reactive attributes
    content = reactive("")
    is_complete = reactive(False)
    token_count = reactive(0)
    expanded = reactive(False)  # Collapsed by default

    DEFAULT_CSS = """
    ThinkingBlock {
        margin: 1 0;
        height: auto;
        min-height: 3;
    }

    ThinkingBlock:hover {
        background: $surface-lighten-1;
    }

    ThinkingBlock.streaming {
        border: round $primary-darken-2;
    }

    ThinkingBlock.complete {
        border: round $primary-darken-3;
    }

    ThinkingBlock.expanded {
        max-height: 100%;
    }

    ThinkingBlock.collapsed {
        max-height: 5;
    }
    """

    # Preview length when collapsed
    PREVIEW_LENGTH = 100

    def __init__(self, content: str = "", expanded: bool = False, **kwargs):
        """
        Initialize ThinkingBlock.

        Args:
            content: Initial thinking content
            expanded: Whether to start expanded
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self.content = content
        self.expanded = expanded
        self._update_classes()

    def _update_classes(self) -> None:
        """Update CSS classes based on state."""
        self.remove_class("streaming", "complete", "expanded", "collapsed")

        if self.is_complete:
            self.add_class("complete")
        else:
            self.add_class("streaming")

        if self.expanded:
            self.add_class("expanded")
        else:
            self.add_class("collapsed")

    def watch_is_complete(self, is_complete: bool) -> None:
        """React to completion state changes."""
        self._update_classes()

    def watch_expanded(self, expanded: bool) -> None:
        """React to expansion state changes."""
        self._update_classes()

    def render(self) -> RenderableType:
        """Render the thinking block."""
        if self.expanded:
            # Full content as markdown
            if self.content:
                body = RichMarkdown(self.content)
            else:
                body = Text("...", style="dim italic")
        else:
            # Collapsed preview
            preview = self._get_preview()
            body = Text(preview, style="dim italic")

        # Build title
        title_parts = ["Thinking"]

        if self.is_complete and self.token_count:
            title_parts.append(f"({self.token_count:,} tokens)")
        elif not self.is_complete:
            title_parts.append("...")

        # Add expand/collapse hint
        if self.expanded:
            title_parts.append("[dim]click to collapse[/dim]")
        else:
            title_parts.append("[dim]click to expand[/dim]")

        title = " ".join(title_parts)

        # Border style
        border_style = "blue" if self.is_complete else "cyan"

        return Panel(
            body,
            title=title,
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
        )

    def _get_preview(self) -> str:
        """Get preview text for collapsed state."""
        if not self.content:
            return "..."

        # Take first N characters, clean up
        preview = self.content[: self.PREVIEW_LENGTH]
        preview = preview.replace("\n", " ").strip()

        if len(self.content) > self.PREVIEW_LENGTH:
            preview += "..."

        return preview

    def on_click(self) -> None:
        """Toggle expansion on click."""
        self.expanded = not self.expanded

    def append(self, content: str) -> None:
        """
        Append content during streaming.

        Args:
            content: Thinking content to append
        """
        self.content += content

    def set_content(self, content: str) -> None:
        """
        Replace all content.

        Args:
            content: New thinking content
        """
        self.content = content

    def finalize(self, token_count: int | None = None) -> None:
        """
        Mark as complete.

        Args:
            token_count: Number of tokens used in thinking
        """
        self.is_complete = True
        if token_count:
            self.token_count = token_count

    def expand(self) -> None:
        """Expand the block to show full content."""
        self.expanded = True

    def collapse(self) -> None:
        """Collapse the block to show preview only."""
        self.expanded = False

    def toggle(self) -> None:
        """Toggle between expanded and collapsed states."""
        self.expanded = not self.expanded

    def clear(self) -> None:
        """Clear all content and reset state."""
        self.content = ""
        self.is_complete = False
        self.token_count = 0
        self.expanded = False

    @property
    def word_count(self) -> int:
        """Get approximate word count."""
        if not self.content:
            return 0
        return len(self.content.split())
