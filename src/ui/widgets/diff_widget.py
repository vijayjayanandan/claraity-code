"""
DiffWidget - Claude Code-style diff display with professional formatting.

Features:
- Line numbers for both old and new versions
- Background colors (green for additions, red for deletions)
- Summary statistics ("Added X lines, removed Y lines")
- Context lines around changes
- Truncation for large diffs
- Windows ANSI compatibility
"""

import difflib
import re
from dataclasses import dataclass
from typing import Optional

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static


@dataclass
class DiffLine:
    """Single diff line with metadata."""

    line_num_old: int | None  # Line number in old file (None for additions)
    line_num_new: int | None  # Line number in new file (None for deletions)
    marker: str  # '+' for addition, '-' for deletion, ' ' for context
    content: str  # Line content (without the marker prefix)


class DiffWidget(Static):
    """
    Professional diff display widget matching VS Code/GitHub style.

    Displays file changes with:
    - Line numbers in the gutter
    - Subtle background colors (muted green for additions, muted red for deletions)
    - Summary statistics header
    - Context lines around changes
    - Truncation for large files

    Usage:
        # For new file (write_file)
        diff = DiffWidget(
            file_path="hello.py",
            new_content="print('Hello')",
            old_content=None
        )

        # For edit (edit_file)
        diff = DiffWidget(
            file_path="hello.py",
            new_content="print('Hello World')",
            old_content="print('Hello')"
        )
    """

    DEFAULT_CSS = """
    DiffWidget {
        height: auto;
        margin: 0;
        padding: 0;
        background: #000000;
    }
    """

    def __init__(
        self,
        file_path: str,
        new_content: str,
        old_content: str | None = None,
        max_lines: int = 30,
        context_lines: int = 3,
        start_line: int = 1,
        **kwargs,
    ):
        """
        Initialize DiffWidget.

        Args:
            file_path: Path to the file being changed
            new_content: New file content
            old_content: Original content (None for new files)
            max_lines: Maximum lines to display before truncation
            context_lines: Number of context lines around changes
            start_line: Line offset for snippet diffs (1-based)
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self.file_path = file_path
        self.new_content = new_content or ""
        self.old_content = old_content
        self.max_lines = max_lines
        self.context_lines = context_lines
        self.start_line = start_line

        # Pre-compute diff lines for rendering
        self._diff_lines: list[DiffLine] = []
        self._additions = 0
        self._deletions = 0
        self._truncated = False
        self._compute_diff()

    def _compute_diff(self) -> None:
        """Compute diff lines and statistics."""
        if self.old_content is None:
            # New file - all lines are additions
            lines = self.new_content.split("\n")
            total_lines = len(lines)

            if total_lines > self.max_lines:
                lines = lines[: self.max_lines]
                self._truncated = True

            self._diff_lines = [DiffLine(None, i + 1, "+", line) for i, line in enumerate(lines)]
            self._additions = total_lines
            self._deletions = 0
        else:
            # Edit - compute unified diff
            self._compute_unified_diff()

    def _compute_unified_diff(self) -> None:
        """Compute unified diff with line numbers."""
        old_lines = self.old_content.split("\n") if self.old_content else []
        new_lines = self.new_content.split("\n")

        # Generate unified diff
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=self.context_lines))

        if not diff:
            # No differences
            return

        result = []
        old_num = 0
        new_num = 0

        # Parse hunk headers to get starting line numbers
        # Apply start_line offset for snippet diffs (e.g. edit_file)
        offset = self.start_line - 1
        for line in diff:
            if line.startswith("@@"):
                # Parse @@ -start,count +start,count @@
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if match:
                    old_num = int(match.group(1)) - 1 + offset
                    new_num = int(match.group(2)) - 1 + offset
                continue
            elif line.startswith("---") or line.startswith("+++"):
                continue
            elif line.startswith("+"):
                new_num += 1
                self._additions += 1
                result.append(DiffLine(None, new_num, "+", line[1:]))
            elif line.startswith("-"):
                old_num += 1
                self._deletions += 1
                result.append(DiffLine(old_num, None, "-", line[1:]))
            else:
                # Context line
                old_num += 1
                new_num += 1
                content = line[1:] if len(line) > 0 else ""
                result.append(DiffLine(old_num, new_num, " ", content))

            if len(result) >= self.max_lines:
                self._truncated = True
                break

        self._diff_lines = result

    def _get_stats_text(self) -> str:
        """Generate statistics header text."""
        parts = []

        if self._additions > 0:
            word = "line" if self._additions == 1 else "lines"
            parts.append(f"{self._additions} {word} added")

        if self._deletions > 0:
            word = "line" if self._deletions == 1 else "lines"
            parts.append(f"{self._deletions} {word} removed")

        if not parts:
            return "No changes"

        return ", ".join(parts)

    def render(self) -> RenderableType:
        """Render the diff with professional formatting."""
        result = Text()

        # File header with operation type - VS Code style
        from pathlib import Path

        filename = Path(self.file_path).name if self.file_path else "unknown"

        if self.old_content is None:
            # New file - green accent
            result.append("  ", style="")
            result.append(f"{filename} ", style="bold #73c991")
            result.append("(new file)\n", style="dim #6e7681")
        else:
            # Edit file - yellow/orange accent
            result.append("  ", style="")
            result.append(f"{filename} ", style="bold #cca700")
            result.append("(modified)\n", style="dim #6e7681")

        # Statistics header - subtle styling
        stats = self._get_stats_text()
        result.append(f"    {stats}\n", style="#6e7681")
        result.append("\n")

        # Render each diff line
        for diff_line in self._diff_lines:
            self._render_line(result, diff_line)

        # Truncation notice
        if self._truncated:
            remaining = (self._additions + self._deletions) - len(self._diff_lines)
            if remaining > 0:
                result.append(f"\n    ... ({remaining} more lines)\n", style="dim")

        return result

    def _render_line(self, text: Text, line: DiffLine) -> None:
        """
        Render a single diff line with proper styling.

        Uses VS Code/GitHub-inspired colors:
        - Additions: Muted green background (#2d4a2d) with green text
        - Deletions: Muted red background (#4a2d2d) with red text
        - Context: Subtle gray background for visual continuity

        Args:
            text: Rich Text object to append to
            line: DiffLine to render
        """
        # Determine which line number to show (prefer new, fallback to old)
        line_num = line.line_num_new or line.line_num_old or 0

        if line.marker == "+":
            # Addition - muted green background with green-tinted text
            # Line number in green
            text.append(f" {line_num:4} ", style="#6a9955 on #1e2d1e")
            text.append("+", style="bold #73c991 on #2d4a2d")
            text.append(f"{line.content}\n", style="#c5e1c5 on #2d4a2d")
        elif line.marker == "-":
            # Deletion - muted red background with red-tinted text
            # Line number in red
            text.append(f" {line_num:4} ", style="#ce9178 on #2d1e1e")
            text.append("-", style="bold #f14c4c on #4a2d2d")
            text.append(f"{line.content}\n", style="#e1c5c5 on #4a2d2d")
        else:
            # Context line - subtle dark background
            text.append(f" {line_num:4} ", style="dim #6e7681 on #161616")
            text.append(f" {line.content}\n", style="#a0a0a0 on #1e1e1e")


class InlineDiffWidget(Static):
    """
    Compact inline diff for smaller displays.

    Shows a condensed view suitable for tool card headers:
    - Single line summary
    - Key changes highlighted
    """

    def __init__(self, old_text: str, new_text: str, max_preview_chars: int = 60, **kwargs):
        """
        Initialize inline diff widget.

        Args:
            old_text: Original text
            new_text: New text
            max_preview_chars: Maximum characters to show in preview
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self.old_text = old_text
        self.new_text = new_text
        self.max_preview_chars = max_preview_chars

    def render(self) -> RenderableType:
        """Render compact inline diff."""
        result = Text()

        # Truncate for preview
        old_preview = self.old_text[: self.max_preview_chars]
        new_preview = self.new_text[: self.max_preview_chars]

        if len(self.old_text) > self.max_preview_chars:
            old_preview += "..."
        if len(self.new_text) > self.max_preview_chars:
            new_preview += "..."

        # Show old -> new
        result.append("    ", style="")
        result.append(old_preview, style="red strike")
        result.append(" -> ", style="dim")
        result.append(new_preview, style="green")
        result.append("\n")

        return result
