"""
Autocomplete dropdown widget for @ file references.

Features:
- Displays file suggestions with match highlighting
- Keyboard navigation (up/down/tab/enter/esc)
- Auto-hide when no suggestions
"""

from typing import Optional

from rich.console import RenderableType
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from ..autocomplete import FileSuggestion


class AutocompleteDropdown(Static):
    """
    Dropdown menu for file suggestions.

    Usage:
        dropdown = AutocompleteDropdown()
        await container.mount(dropdown)

        # Show with suggestions
        dropdown.show(suggestions)

        # Navigate
        dropdown.move_selection(1)   # Down
        dropdown.move_selection(-1)  # Up

        # Get selected
        selected = dropdown.get_selected()

        # Hide
        dropdown.hide()
    """

    selected_index = reactive(0)
    visible = reactive(False)

    DEFAULT_CSS = """
    AutocompleteDropdown {
        width: auto;
        min-width: 40;
        max-width: 80;
        height: auto;
        max-height: 12;
        background: $surface;
        border: solid $accent;
        padding: 0 1;
        layer: autocomplete;
    }

    AutocompleteDropdown.-hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._suggestions: list[FileSuggestion] = []
        self.add_class("-hidden")

    def show(self, suggestions: list[FileSuggestion]) -> None:
        """
        Show dropdown with suggestions.

        Args:
            suggestions: list of FileSuggestion objects
        """
        self._suggestions = suggestions
        self.selected_index = 0
        self.visible = True
        self.remove_class("-hidden")
        self.refresh()

    def hide(self) -> None:
        """Hide the dropdown."""
        self.visible = False
        self.add_class("-hidden")
        self._suggestions = []
        self.refresh()

    def move_selection(self, delta: int) -> None:
        """
        Move selection up/down.

        Args:
            delta: Direction (+1 = down, -1 = up)
        """
        if self._suggestions:
            new_index = (self.selected_index + delta) % len(self._suggestions)
            self.selected_index = new_index
            self.refresh()

    def get_selected(self) -> FileSuggestion | None:
        """
        Get currently selected suggestion.

        Returns:
            Selected FileSuggestion or None
        """
        if self._suggestions and 0 <= self.selected_index < len(self._suggestions):
            return self._suggestions[self.selected_index]
        return None

    def get_selected_path(self) -> str | None:
        """
        Get path of currently selected suggestion.

        Returns:
            Selected path string or None
        """
        selected = self.get_selected()
        return selected.path if selected else None

    @property
    def has_suggestions(self) -> bool:
        """Whether there are any suggestions."""
        return len(self._suggestions) > 0

    @property
    def suggestion_count(self) -> int:
        """Number of suggestions."""
        return len(self._suggestions)

    def render(self) -> RenderableType:
        """Render the dropdown with match highlighting."""
        if not self._suggestions:
            return Text("")

        result = Text()

        for i, suggestion in enumerate(self._suggestions):
            is_selected = i == self.selected_index

            # Build the display line with match highlighting
            line = self._render_suggestion(suggestion, is_selected)
            result.append(line)
            result.append("\n")

        return result

    def _render_suggestion(self, suggestion: FileSuggestion, is_selected: bool) -> Text:
        """
        Render a single suggestion with match highlighting.

        Args:
            suggestion: The suggestion to render
            is_selected: Whether this is the selected item

        Returns:
            Rich Text object
        """
        line = Text()

        # Selection indicator
        if is_selected:
            line.append(" > ", style="bold cyan")
        else:
            line.append("   ", style="")

        # Path with match highlighting
        path = suggestion.path
        match_positions = set(suggestion.match_positions)

        # Base style
        base_style = "reverse bold" if is_selected else "dim"
        highlight_style = "bold cyan" if is_selected else "bold yellow"

        # Render path with highlights
        for i, char in enumerate(path):
            if i in match_positions:
                line.append(char, style=highlight_style)
            else:
                line.append(char, style=base_style if is_selected else "")

        # Add score for debugging (can be removed in production)
        # line.append(f" ({suggestion.score:.2f})", style="dim")

        return line

    def watch_selected_index(self, old_index: int, new_index: int) -> None:
        """React to selection changes."""
        self.refresh()
