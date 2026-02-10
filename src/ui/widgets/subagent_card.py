"""SubAgentCard - displays subagent execution in the TUI.

Three vertically stacked collapsible sections, each with a scrollable body:

1. Input:  Task sent to the subagent (collapsed by default) + Copy
2. Tools:  Tool calls with live status badges (expanded by default)
3. Output: Final subagent response (collapsed until done) + Copy

Uses a custom _CollapsibleSection widget (not Textual's Collapsible) for
reliable expand/collapse behavior with explicit display toggle.

Tools are rendered as Rich Text inside a SINGLE Static widget — no dynamic
widget mounting.  When any tool changes, the entire tools display is
re-rendered.  This avoids Textual mount-timing issues that caused only
1-of-N tools to appear.

Mounted inside the parent ToolCard (delegation tool call).
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from textual.containers import Container, ScrollableContainer, Vertical
from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from src.core.events import ToolStatus
from src.observability import get_logger

if TYPE_CHECKING:
    from src.session.store.memory_store import (
        MessageStore, StoreNotification, StoreEvent, ToolExecutionState,
    )

logger = get_logger("ui.widgets.subagent_card")


# Status badge config -- matches ToolCard for visual consistency
STATUS_ICONS: Dict[ToolStatus, tuple[str, str, str]] = {
    ToolStatus.PENDING:           ("~", "#888888", "#2a2a2a"),
    ToolStatus.AWAITING_APPROVAL: ("?", "#1e1e1e", "#cca700"),
    ToolStatus.APPROVED:          ("+", "#1e1e1e", "#73c991"),
    ToolStatus.REJECTED:          ("x", "#ffffff", "#f14c4c"),
    ToolStatus.RUNNING:           ("*", "#1e1e1e", "#cca700"),
    ToolStatus.SUCCESS:           ("+", "#1e1e1e", "#73c991"),
    ToolStatus.FAILED:            ("!", "#ffffff", "#f14c4c"),
    ToolStatus.ERROR:             ("!", "#ffffff", "#f14c4c"),
    ToolStatus.CANCELLED:         ("-", "#666666", "#2a2a2a"),
    ToolStatus.TIMEOUT:           ("!", "#ffffff", "#f14c4c"),
    ToolStatus.SKIPPED:           ("-", "#666666", "#2a2a2a"),
}

HEADER_ICONS: Dict[str, tuple[str, str, str]] = {
    "running": ("*", "#1e1e1e", "#cca700"),
    "done":    ("+", "#1e1e1e", "#73c991"),
    "failed":  ("!", "#ffffff", "#f14c4c"),
}


@dataclass
class _ToolEntry:
    """Plain data for a single tool call (NOT a widget)."""
    tool_call_id: str
    name: str
    args_summary: str = ""
    status: ToolStatus = ToolStatus.PENDING
    duration_ms: Optional[int] = None
    error: Optional[str] = None


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    # Windows ctypes fallback
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        user32.OpenClipboard(0)
        try:
            user32.EmptyClipboard()
            data = text.encode("utf-16le") + b"\x00\x00"
            h = kernel32.GlobalAlloc(0x0042, len(data))
            ptr = kernel32.GlobalLock(h)
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(13, h)  # CF_UNICODETEXT
        finally:
            user32.CloseClipboard()
        return True
    except Exception:
        return False


# =============================================================================
# Custom collapsible section (replaces Textual Collapsible)
# =============================================================================

class _SectionTitle(Static):
    """Clickable title bar for a collapsible section."""

    DEFAULT_CSS = """
    _SectionTitle {
        width: 100%;
        height: 1;
        color: #9cdcfe;
        background: #1a1a2e;
        padding: 0 1;
    }
    _SectionTitle:hover {
        background: #252545;
        text-style: bold;
    }
    """

    def __init__(self, label: str, expanded: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self._expanded = expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.refresh()

    def set_label(self, label: str) -> None:
        self._label = label
        self.refresh()

    def render(self) -> RenderableType:
        indicator = "[-]" if self._expanded else "[+]"
        t = Text()
        t.append(indicator, style="bold #73c991" if self._expanded else "bold #cca700")
        t.append(f" {self._label}", style="#9cdcfe")
        return t

    def on_click(self, event) -> None:
        event.stop()
        section = self.parent
        if isinstance(section, _CollapsibleSection):
            section.toggle()


class _SectionBody(ScrollableContainer):
    """Scrollable body of a collapsible section."""

    DEFAULT_CSS = """
    _SectionBody {
        height: auto;
        max-height: 15;
        margin: 0 0 0 1;
        background: #0d1117;
        border-left: tall #333333;
    }
    _SectionBody.-hidden {
        display: none;
    }
    """


class _CollapsibleSection(Vertical):
    """A single collapsible section: clickable title + scrollable body.

    Click the title bar to toggle expand/collapse.  The body uses
    display:none when collapsed so Textual skips layout entirely.
    """

    DEFAULT_CSS = """
    _CollapsibleSection {
        height: auto;
        margin: 0;
        padding: 0;
    }
    """

    expanded = reactive(False)

    def __init__(
        self,
        label: str,
        expanded: bool = False,
        body_max_height: int = 15,
        section_id: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._label = label
        self._initial_expanded = expanded
        self._body_max_height = body_max_height
        self._section_id = section_id

    def compose(self):
        yield _SectionTitle(
            self._label,
            expanded=self._initial_expanded,
            id=f"{self._section_id}-title" if self._section_id else None,
        )
        body = _SectionBody(id=f"{self._section_id}-body" if self._section_id else None)
        body.styles.max_height = self._body_max_height
        if not self._initial_expanded:
            body.add_class("-hidden")
        yield body

    def on_mount(self) -> None:
        self.expanded = self._initial_expanded

    def toggle(self) -> None:
        self.expanded = not self.expanded

    def watch_expanded(self, value: bool) -> None:
        try:
            title = self.query_one(_SectionTitle)
            title.set_expanded(value)
        except Exception:
            pass
        try:
            body = self.query_one(_SectionBody)
            if value:
                body.remove_class("-hidden")
            else:
                body.add_class("-hidden")
        except Exception:
            pass

    def set_label(self, label: str) -> None:
        self._label = label
        try:
            title = self.query_one(_SectionTitle)
            title.set_label(label)
        except Exception:
            pass

    @property
    def body(self) -> _SectionBody:
        """Direct access to the scrollable body container."""
        return self.query_one(_SectionBody)


# =============================================================================
# Small helper widgets
# =============================================================================

class _CopyButton(Static):
    """Small clickable copy button placed inside a section body."""

    DEFAULT_CSS = """
    _CopyButton {
        height: 1;
        width: auto;
        min-width: 8;
        margin: 0 0 0 1;
        color: #555555;
    }
    _CopyButton:hover {
        color: #4a9eff;
        text-style: underline;
    }
    """

    def __init__(self, label: str = "Copy", **kwargs):
        super().__init__(**kwargs)
        self._base_label = label
        self._label = label
        self._text_to_copy: str = ""

    def set_text(self, text: str) -> None:
        self._text_to_copy = text

    def render(self) -> RenderableType:
        return Text(f"[{self._label}]", style="")

    def on_click(self, event) -> None:
        event.stop()
        if not self._text_to_copy:
            self._label = "Empty"
        elif _copy_to_clipboard(self._text_to_copy):
            self._label = "Copied!"
        else:
            self._label = "Failed"
        self.refresh()
        self.set_timer(1.5, self._reset_label)

    def _reset_label(self) -> None:
        self._label = self._base_label
        self.refresh()


class _StatusHeader(Static):
    """Top status line: badge + subagent name + tool count + duration."""

    DEFAULT_CSS = """
    _StatusHeader {
        height: 1;
        margin: 0 0 0 1;
    }
    """

    def __init__(self, subagent_id: str, **kwargs):
        super().__init__(**kwargs)
        self._subagent_id = subagent_id
        self._status = "running"
        self._tool_count = 0
        self._duration_ms: Optional[int] = None

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

    def render(self) -> RenderableType:
        icon, fg, bg = HEADER_ICONS.get(
            self._status, ("*", "#1e1e1e", "#cca700")
        )

        t = Text()
        t.append(f" {icon} ", style=f"bold {fg} on {bg}")
        t.append(" ", style="")
        t.append("Subagent ", style="#9cdcfe")
        t.append(self._subagent_id[:12], style="bold #e0e0e0")
        t.append(f" | {self._tool_count} tools", style="#6e7681")

        if self._duration_ms:
            secs = self._duration_ms / 1000
            t.append(f" | {secs:.1f}s", style="#6e7681")
        elif self._status == "running":
            t.append(" | running", style="#cca700")

        return t


# =============================================================================
# Main SubAgentCard
# =============================================================================

class SubAgentCard(Container):
    """Displays subagent execution status inside a parent ToolCard.

    Architecture:
        SubAgentCard (Container)
        +-- _StatusHeader
        +-- _CollapsibleSection "Input"  (collapsed by default)
        |   +-- _SectionTitle  "[+] Input"
        |   +-- _SectionBody   (max-height: 10)
        |       +-- Static#sa-input-text       (mounted in on_mount)
        |       +-- _CopyButton#sa-copy-input  (mounted in on_mount)
        +-- _CollapsibleSection "Tools"  (expanded by default)
        |   +-- _SectionTitle  "[-] Tools (N)"
        |   +-- _SectionBody   (max-height: 15)
        |       +-- Static#sa-tools-display    (mounted in on_mount)
        +-- _CollapsibleSection "Output" (collapsed until done)
            +-- _SectionTitle  "[+] Output"
            +-- _SectionBody   (max-height: 20)
                +-- Static#sa-output-text       (mounted in on_mount)
                +-- _CopyButton#sa-copy-output  (mounted in on_mount)

    IMPORTANT: Tools are rendered as Rich Text in a SINGLE Static widget.
    No dynamic widget mounting.  _tool_data is a plain dict, not widgets.
    Every tool add/update re-renders the entire tools Static via .update().
    """

    DEFAULT_CSS = """
    SubAgentCard {
        height: auto;
        padding: 0;
        margin: 0 0 0 2;
    }
    """

    def __init__(
        self,
        subagent_id: str,
        transcript_path: Optional[Path] = None,
        store: Optional["MessageStore"] = None,
        buffered_notifications: Optional[list] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.subagent_id = subagent_id
        self.transcript_path = transcript_path
        self._status = "running"
        self._input_text = ""
        self._output_text = ""
        self._duration_ms: Optional[int] = None

        # Tool data (plain dicts, NOT widgets): tool_call_id -> _ToolEntry
        self._tool_data: Dict[str, _ToolEntry] = {}
        # Insertion-ordered list for stable display order
        self._tool_order: List[str] = []

        # Deferred hydration: store and buffered notifications are processed
        # in on_mount() AFTER compose() has built the DOM tree.
        self._pending_store = store
        self._pending_notifications = buffered_notifications or []

        # Direct widget references (set in on_mount, avoids query_one)
        self._header_widget: Optional[_StatusHeader] = None
        self._input_text_widget: Optional[Static] = None
        self._input_copy_widget: Optional[_CopyButton] = None
        self._tools_display_widget: Optional[Static] = None
        self._output_text_widget: Optional[Static] = None
        self._output_copy_widget: Optional[_CopyButton] = None

    def compose(self):
        yield _StatusHeader(self.subagent_id, id="sa-header")

        # --- Input section (collapsed by default) ---
        yield _CollapsibleSection(
            label="Input",
            expanded=False,
            body_max_height=10,
            section_id="sa-input",
            id="sa-input-section",
        )

        # --- Tools section (expanded by default) ---
        yield _CollapsibleSection(
            label="Tools (0)",
            expanded=True,
            body_max_height=15,
            section_id="sa-tools",
            id="sa-tools-section",
        )

        # --- Output section (collapsed until done) ---
        yield _CollapsibleSection(
            label="Output",
            expanded=False,
            body_max_height=20,
            section_id="sa-output",
            id="sa-output-section",
        )

    def on_mount(self) -> None:
        """Populate section bodies, then hydrate from store.

        Compose has already created the _CollapsibleSection widgets and
        their _SectionBody children.  We mount content widgets into the
        bodies, then hydrate (pure data operations + .update() calls).
        """
        # Grab header reference
        try:
            self._header_widget = self.query_one("#sa-header", _StatusHeader)
        except Exception:
            pass

        # Input body: text + copy button
        try:
            input_body = self.query_one("#sa-input-section", _CollapsibleSection).body
            self._input_text_widget = Static("(waiting for input...)", id="sa-input-text")
            self._input_copy_widget = _CopyButton("Copy Input", id="sa-copy-input")
            input_body.mount(self._input_text_widget, self._input_copy_widget)
        except Exception as e:
            logger.error(f"Failed to mount input body: {e}")

        # Tools body: single Static for ALL tools (no dynamic mounting)
        try:
            tools_body = self.query_one("#sa-tools-section", _CollapsibleSection).body
            self._tools_display_widget = Static("(no tools yet)", id="sa-tools-display")
            tools_body.mount(self._tools_display_widget)
        except Exception as e:
            logger.error(f"Failed to mount tools body: {e}")

        # Output body: text + copy button
        try:
            output_body = self.query_one("#sa-output-section", _CollapsibleSection).body
            self._output_text_widget = Static("(waiting for output...)", id="sa-output-text")
            self._output_copy_widget = _CopyButton("Copy Output", id="sa-copy-output")
            output_body.mount(self._output_text_widget, self._output_copy_widget)
        except Exception as e:
            logger.error(f"Failed to mount output body: {e}")

        # --- Deferred hydration: populate data, then update displays ---
        if self._pending_store is not None:
            self._hydrate_from_store(self._pending_store)
            self._pending_store = None

        # Flush any buffered notifications that arrived before mount
        if self._pending_notifications:
            for notif in self._pending_notifications:
                self.update_from_notification(notif)
            self._pending_notifications.clear()

    # -------------------------------------------------------------------------
    # Public API (called by app.py)
    # -------------------------------------------------------------------------

    def hydrate_from_store(self, store: "MessageStore") -> None:
        """Public entry point for hydration (delegates to internal)."""
        self._hydrate_from_store(store)

    def update_from_notification(self, notification: "StoreNotification") -> None:
        """Update display from a live store notification."""
        try:
            from src.session.store.memory_store import StoreEvent

            if notification.event == StoreEvent.TOOL_STATE_UPDATED:
                if notification.tool_call_id and notification.tool_state:
                    meta = notification.metadata or {}
                    tool_name = meta.get("tool_name") or "unknown"
                    args_summary = meta.get("args_summary") or ""
                    self._register_tool(
                        notification.tool_call_id,
                        tool_name,
                        args_summary,
                        notification.tool_state.status,
                        notification.tool_state.duration_ms,
                        notification.tool_state.error,
                    )

            elif notification.message:
                msg = notification.message
                if msg.role == "user" and msg.content and not self._input_text:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    self._input_text = content
                    self._refresh_input()

                elif msg.role == "assistant" and msg.content:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    self._output_text = content
                    self._refresh_output()

                elif msg.role == "assistant" and msg.tool_calls:
                    for tc in msg.tool_calls:
                        name = tc.function.name if tc.function else "unknown"
                        args = tc.function.get_parsed_arguments() if tc.function else {}
                        args_summary = _summarize_args(name, args)
                        self._register_tool(tc.id, name, args_summary, ToolStatus.PENDING)

        except Exception as e:
            logger.error(f"SubAgentCard update error: {e}")

    def mark_completed(self, success: bool = True) -> None:
        """Mark the subagent as completed."""
        self._status = "done" if success else "failed"
        self._refresh_header()

        # Expand output section on completion (success or failure)
        try:
            output_section = self.query_one("#sa-output-section", _CollapsibleSection)
            output_section.expanded = True
        except Exception as e:
            logger.warning(f"Failed to expand output section: {e}")

    def remove(self) -> None:
        """Clean up references before removal."""
        self._tool_data.clear()
        self._tool_order.clear()
        super().remove()

    # -------------------------------------------------------------------------
    # Internal: hydration
    # -------------------------------------------------------------------------

    def _hydrate_from_store(self, store: "MessageStore") -> None:
        """Load initial state from a MessageStore snapshot.

        Pure data operation: populates _tool_data, _input_text, _output_text,
        then refreshes display widgets via .update() calls.
        No dynamic widget mounting.
        """
        try:
            messages = store.get_ordered_messages()

            for msg in messages:
                if msg.role == "user" and msg.content and not self._input_text:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    self._input_text = content

                elif msg.role == "assistant":
                    if msg.content:
                        content = msg.content if isinstance(msg.content, str) else str(msg.content)
                        self._output_text = content

                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            name = tc.function.name if tc.function else "unknown"
                            args = tc.function.get_parsed_arguments() if tc.function else {}
                            args_summary = _summarize_args(name, args)
                            state = store.get_tool_state(tc.id)
                            status = state.status if state else ToolStatus.PENDING
                            duration = state.duration_ms if state else None
                            error = state.error if state else None
                            self._register_tool(
                                tc.id, name, args_summary, status, duration, error,
                                skip_refresh=True,  # batch: refresh once at end
                            )

            # Single refresh for all data
            self._refresh_all()

        except Exception as e:
            logger.error(f"SubAgentCard hydrate error: {e}")

    # -------------------------------------------------------------------------
    # Internal: tool data management
    # -------------------------------------------------------------------------

    def _register_tool(
        self,
        tool_call_id: str,
        name: str,
        args_summary: str = "",
        status: ToolStatus = ToolStatus.PENDING,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        skip_refresh: bool = False,
    ) -> None:
        """Add or update a tool entry (pure data, no widget mounting)."""
        existing = self._tool_data.get(tool_call_id)
        if existing:
            existing.status = status
            if duration_ms is not None:
                existing.duration_ms = duration_ms
            if error is not None:
                existing.error = error
        else:
            entry = _ToolEntry(
                tool_call_id=tool_call_id,
                name=name or "unknown",
                args_summary=args_summary,
                status=status,
                duration_ms=duration_ms,
                error=error,
            )
            self._tool_data[tool_call_id] = entry
            self._tool_order.append(tool_call_id)

        if not skip_refresh:
            self._refresh_tools_display()
            self._refresh_header()

    # -------------------------------------------------------------------------
    # Internal: display refresh (all use .update(), no mounting)
    # -------------------------------------------------------------------------

    def _refresh_all(self) -> None:
        """Refresh all display widgets after hydration."""
        self._refresh_header()
        self._refresh_input()
        self._refresh_output()
        self._refresh_tools_display()

    def _refresh_header(self) -> None:
        if self._header_widget:
            self._header_widget.update_status(
                self._status, len(self._tool_data), self._duration_ms
            )

    def _refresh_input(self) -> None:
        if self._input_text_widget:
            self._input_text_widget.update(self._input_text or "(empty)")
        if self._input_copy_widget:
            self._input_copy_widget.set_text(self._input_text)

    def _refresh_output(self) -> None:
        if self._output_text_widget:
            self._output_text_widget.update(self._output_text or "(empty)")
        if self._output_copy_widget:
            self._output_copy_widget.set_text(self._output_text)

    def _refresh_tools_display(self) -> None:
        """Re-render ALL tools as Rich Text into a single Static widget."""
        if not self._tools_display_widget:
            return

        if not self._tool_data:
            self._tools_display_widget.update("(no tools yet)")
            self._update_tools_title(0)
            return

        # Build Rich Text with all tool lines
        text = Text()
        for i, tool_call_id in enumerate(self._tool_order):
            entry = self._tool_data.get(tool_call_id)
            if not entry:
                continue

            if i > 0:
                text.append("\n")

            # Status badge
            icon, fg, bg = STATUS_ICONS.get(
                entry.status, ("?", "#888888", "#2a2a2a")
            )
            text.append(f" {icon} ", style=f"bold {fg} on {bg}")
            text.append(" ", style="")

            # Tool name
            text.append(entry.name, style="bold #e0e0e0")

            # Args summary
            if entry.args_summary:
                text.append("(", style="#6e7681")
                text.append(entry.args_summary, style="#9cdcfe")
                text.append(")", style="#6e7681")

            # Duration
            if entry.duration_ms:
                text.append(f"  {entry.duration_ms}ms", style="#6e7681")

            # Error
            if entry.error:
                err = entry.error[:57] + "..." if len(entry.error) > 60 else entry.error
                text.append(f"  {err}", style="#f14c4c")

        self._tools_display_widget.update(text)
        self._update_tools_title(len(self._tool_data))

    def _update_tools_title(self, count: int) -> None:
        try:
            tools_section = self.query_one("#sa-tools-section", _CollapsibleSection)
            tools_section.set_label(f"Tools ({count})")
        except Exception:
            pass


def _summarize_args(tool_name: str, args: Dict[str, Any]) -> str:
    """Create a short summary of tool arguments."""
    if not args:
        return ""

    main_keys = [
        "file_path", "path", "filename", "command", "query",
        "pattern", "url", "name",
    ]
    for key in main_keys:
        if key in args:
            val = str(args[key])
            if len(val) > 60:
                val = val[:57] + "..."
            return val

    for val in args.values():
        if isinstance(val, str) and val:
            if len(val) > 60:
                return val[:57] + "..."
            return val
    return ""
