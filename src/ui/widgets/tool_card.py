"""
ToolCard - Tool execution status with inline approval UI.

Features:
- Status indicator with colored icons
- Arguments preview (compact format)
- Inline approval options (Claude Code style)
- Result preview or error display
- Duration tracking
- Content preview for write_file
- Diff preview for edit_file
- Collapsible command preview for run_command
"""

import difflib
import os
from typing import Any

from rich.console import RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

from ..events import ToolStatus
from ..messages import ApprovalResponseMessage
from .diff_widget import DiffWidget


class ScrollableDiffContainer(VerticalScroll):
    """Scrollable container for diff widgets with bounded height."""

    DEFAULT_CSS = """
    ScrollableDiffContainer {
        max-height: 20;
        height: auto;
        margin: 0 0 0 2;
        padding: 0 1;
        background: #000000;
        border: round #222222;
        scrollbar-size: 1 1;
        scrollbar-color: #333333;
        scrollbar-background: #000000;
    }

    ScrollableDiffContainer:focus {
        border: round #3794ff;
    }
    """


class CommandPreviewBlock(Static):
    """Collapsible command preview for run_command tool calls.

    Expanded by default so users see the exact command before approving.
    Click to collapse/expand. Follows SubAgentCard's [+]/[-] pattern.
    """

    DEFAULT_CSS = """
    CommandPreviewBlock {
        height: auto;
        padding: 0;
    }
    """

    PREVIEW_LENGTH = 80

    MAX_OUTPUT_LINES = 50

    def __init__(self, command: str, **kwargs):
        super().__init__(**kwargs)
        self.command = command
        self._collapsed = False
        self._output: str | None = None

    def set_output(self, output: str) -> None:
        """Set the command output to display below the command."""
        self._output = output
        self._collapsed = True  # Collapse by default once output arrives
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        t = Text()
        if self._collapsed:
            t.append("[+]", style="bold #cca700")
        else:
            t.append("[-]", style="bold #73c991")
        t.append(" ", style="")
        t.append("$ ", style="bold #73c991")

        if self._collapsed:
            preview = self.command.replace("\n", " ")[: self.PREVIEW_LENGTH]
            if len(self.command) > self.PREVIEW_LENGTH:
                preview += "..."
            t.append(preview, style="#d4d4d4")
            # Show output summary when collapsed
            if self._output:
                line_count = self._output.count("\n") + 1
                t.append(f"  ({line_count} lines)", style="#6e7681")
        else:
            t.append(self.command, style="#d4d4d4")
            # Show full output when expanded
            if self._output:
                t.append("\n", style="")
                lines = self._output.split("\n")
                truncated = len(lines) > self.MAX_OUTPUT_LINES
                for line in lines[: self.MAX_OUTPUT_LINES]:
                    t.append(f"  {line}\n", style="#a0a0a0")
                if truncated:
                    t.append(
                        f"  ... ({len(lines) - self.MAX_OUTPUT_LINES} more lines)\n",
                        style="#6e7681",
                    )
        return t

    def on_click(self) -> None:
        self._collapsed = not self._collapsed
        self.refresh(layout=True)


class ToolCard(Static):
    """
    Tool execution card with status indicator and approval UI.

    Displays:
    - Tool name and status icon
    - Arguments preview
    - Inline approval options (when awaiting approval)
    - Result preview or error (when complete)

    Usage:
        card = ToolCard(
            call_id="call_1",
            tool_name="read_file",
            args={"path": "config.py"},
            requires_approval=True
        )
        await container.mount(card)

        # Update status
        card.status = ToolStatus.RUNNING

        # Set result
        card.set_result("file contents here", duration_ms=50)

        # Or set error
        card.set_error("File not found")

    Attributes:
        call_id: Unique identifier for this tool call
        tool_name: Tool function name
        args: Tool arguments dictionary
        status: Current execution status
        result_preview: Preview of successful result
        error_message: Error message if failed
    """

    # Reactive attributes
    status = reactive(ToolStatus.PENDING)
    result_preview = reactive("")
    error_message = reactive("")
    duration_ms = reactive(0)

    # Status display configuration: color for the dot indicator
    # Subtle colored dot instead of badge - status is conveyed by color alone
    STATUS_COLORS = {
        ToolStatus.PENDING: "#888888",
        ToolStatus.AWAITING_APPROVAL: "#cca700",
        ToolStatus.APPROVED: "#3794ff",
        ToolStatus.REJECTED: "#3a3a3a",
        ToolStatus.RUNNING: "#cca700",
        ToolStatus.SUCCESS: "#73c991",
        ToolStatus.FAILED: "#f14c4c",
        ToolStatus.CANCELLED: "#666666",
    }

    DEFAULT_CSS = """
    ToolCard {
        height: auto;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(
        self,
        call_id: str,
        tool_name: str,
        args: dict[str, Any],
        requires_approval: bool = False,
        suppress_approval_ui: bool = False,
        **kwargs,
    ):
        """
        Initialize ToolCard.

        Args:
            call_id: Unique identifier for tracking
            tool_name: Tool function name
            args: Tool arguments dictionary
            requires_approval: Whether user must approve
            suppress_approval_ui: If True, don't mount ToolApprovalOptions/ClarifyWidget
                on AWAITING_APPROVAL (used for subagent cards where approval is promoted)
            **kwargs: Additional arguments for Static
        """
        # Initialize instance attributes BEFORE super().__init__
        # because reactive watchers may fire during initialization
        self._approval_widget: ToolApprovalOptions | None = None
        self._defer_diff_mount: bool = False  # Set True during bulk load for performance
        self._diff_mounted: bool = False  # Track if diff already mounted
        self._header_widget: Static | None = None  # Mounted header for tools with children
        self._suppress_approval_ui = suppress_approval_ui

        super().__init__(**kwargs)
        self.call_id = call_id
        self.tool_name = tool_name
        self.args = args
        self.requires_approval = requires_approval

        # NOTE: Do NOT set initial status here - defer to on_mount()
        # Setting status in __init__ triggers watch_status() before compose() runs,
        # which can cause lifecycle issues with the approval widget.

        self._update_classes()

    def _update_classes(self) -> None:
        """Update CSS classes based on status (minimal for compact design)."""
        # Compact design doesn't need status classes for borders
        pass

    def watch_status(self, new_status: ToolStatus) -> None:
        """React to status changes.

        Handles approval widget lifecycle based on status:
        - AWAITING_APPROVAL: Show approval widget (create if needed)
        - Any other status: Hide/remove approval widget

        This makes store state the single source of truth for approval UI,
        independent of the initial requires_approval value at card creation.
        """
        from src.observability import get_logger

        logger = get_logger("tool_card")

        self._update_classes()

        # Refresh mounted header widget if present (children hide render())
        if self._header_widget and self._header_widget.is_attached:
            self._header_widget.update(self._render_header_line())

        # Mount diff when status advances past PENDING (deferred until active)
        # This prevents batch tool calls from showing diffs for tools not yet
        # processed, which caused visual confusion (diff from tool #3 appearing
        # below the approval dialog for tool #1).
        if new_status != ToolStatus.PENDING and not self._diff_mounted and self.is_attached:
            self._mount_diff_widget_if_applicable()

        if new_status == ToolStatus.AWAITING_APPROVAL:
            # Show interaction widget - clarify or approval depending on tool
            # (skip for subagent cards where approval is promoted to conversation level)
            if not self._suppress_approval_ui and not self._approval_widget and self.is_attached:
                if self.tool_name == "clarify":
                    logger.info(f"[WATCH_STATUS] {self.call_id}: Creating clarify widget")
                    from .clarify_widget import ClarifyWidget

                    questions = self.args.get("questions", [])
                    context = self.args.get("context")
                    self._approval_widget = ClarifyWidget(
                        call_id=self.call_id,
                        questions=questions,
                        context=context,
                    )
                else:
                    logger.info(f"[WATCH_STATUS] {self.call_id}: Creating approval widget")
                    self._approval_widget = ToolApprovalOptions(
                        call_id=self.call_id, tool_name=self.tool_name, args=self.args
                    )
                # Diff already mounted above; mount approval widget after it
                self.mount(self._approval_widget)
                self.call_after_refresh(self._focus_approval)
            elif not self.is_attached:
                logger.warning(
                    f"[WATCH_STATUS] {self.call_id}: NOT ATTACHED - cannot create approval widget!"
                )
            elif self._approval_widget:
                logger.info(f"[WATCH_STATUS] {self.call_id}: Approval widget already exists")
        else:
            # Remove approval UI when no longer awaiting
            if self._approval_widget:
                try:
                    self._approval_widget.remove()
                except Exception:
                    # Widget may not be mounted yet, ignore
                    pass
                self._approval_widget = None

    def on_mount(self) -> None:
        """Mount child widgets after widget is in DOM.

        For file operations (write_file, edit_file), mounts a DiffWidget to show
        the changes with professional formatting (line numbers, background colors).

        Diffs are only mounted for cards that have advanced past PENDING status.
        This prevents batch tool calls from showing diffs prematurely (e.g., the
        agent returns 3 write_file calls but only processes them sequentially —
        only the active one should show its diff).

        For session replay, cards are hydrated with their final status (SUCCESS,
        ERROR, etc.) so diffs mount immediately on_mount.

        NOTE: Status is NOT reset here. The reactive default is PENDING, and the
        store-driven flow may have already set status to AWAITING_APPROVAL before
        mount. We check current status and create approval widget if needed, since
        watch_status() may have fired before is_attached was True.
        """
        # Only mount diff for cards past PENDING (active or completed).
        # PENDING cards defer diff mounting until watch_status() advances them.
        if self.status != ToolStatus.PENDING:
            self._mount_diff_widget_if_applicable()

        # Check if we need to create approval widget
        # (watch_status may have been called before mount when is_attached=False)
        if self.status == ToolStatus.AWAITING_APPROVAL and not self._approval_widget:
            from src.observability import get_logger

            logger = get_logger("tool_card")
            logger.info(f"[ON_MOUNT] {self.call_id}: Creating widget (status was set before mount)")
            if self.tool_name == "clarify":
                from .clarify_widget import ClarifyWidget

                self._approval_widget = ClarifyWidget(
                    call_id=self.call_id,
                    questions=self.args.get("questions", []),
                    context=self.args.get("context"),
                )
            else:
                self._approval_widget = ToolApprovalOptions(
                    call_id=self.call_id, tool_name=self.tool_name, args=self.args
                )
            # Approval should appear AFTER diff - defer if diff mount was deferred
            if self._defer_diff_mount and not self._diff_mounted:
                # Diff will be mounted later, schedule approval after it
                self.call_after_refresh(self._mount_approval_after_diff)
            else:
                self.mount(self._approval_widget)
                self.call_after_refresh(self._focus_approval)

    def set_defer_diff_mount(self, defer: bool) -> None:
        """Set whether to defer diff widget mounting.

        Use during bulk load (session resume) to avoid blocking the render loop
        while processing many tool cards. The diff widget will be mounted
        asynchronously after the main render cycle completes.

        Args:
            defer: True to defer mounting, False for immediate mounting
        """
        self._defer_diff_mount = defer

    def _mount_diff_widget_if_applicable(self) -> None:
        """Mount DiffWidget for file operations (write_file, edit_file).

        Shows diff preview regardless of approval mode so users can see
        what file operations are doing even in AUTO mode.

        Uses ScrollableDiffContainer to handle large files - users can scroll
        to see the full diff within a bounded height area.

        If deferred mounting is enabled (bulk load), schedules the mount
        for after the current refresh cycle to avoid blocking.
        """
        # Check if already mounted to prevent double-mounting
        if self._diff_mounted:
            return

        # Deferred mounting during bulk load
        if self._defer_diff_mount:
            self.call_after_refresh(self._do_mount_diff_widget)
            return

        self._do_mount_diff_widget()

    def _do_mount_diff_widget(self) -> None:
        """Actually mount the diff widget (internal helper).

        Separated from _mount_diff_widget_if_applicable to support deferred mounting.
        """
        # Safety check: prevent double mounting and ensure widget is still attached
        if self._diff_mounted or not self.is_attached:
            return

        if self.tool_name == "write_file":
            content = self.args.get("content", "")
            if content:
                self._mount_header()
                diff_widget = DiffWidget(
                    file_path=self.args.get("file_path", ""),
                    new_content=content,
                    old_content=None,
                    max_lines=500,  # Large value - scrolling handles overflow
                )
                scroll_container = ScrollableDiffContainer()
                self.mount(scroll_container)
                scroll_container.mount(diff_widget)
                self._diff_mounted = True
            else:
                # Empty file creation — show minimal info so approval dialog
                # has context about what's being approved
                self._mount_header()
                file_name = os.path.basename(self.args.get("file_path", ""))
                label = Static(f"  [dim]{file_name} (empty file)[/dim]")
                self.mount(label)
                self._diff_mounted = True

        elif self.tool_name == "edit_file":
            old_text = self.args.get("old_text", "")
            new_text = self.args.get("new_text", "")
            if old_text or new_text:
                self._mount_header()
                file_path = self.args.get("file_path", "")
                start_line = self._find_line_offset(file_path, old_text)
                diff_widget = DiffWidget(
                    file_path=file_path,
                    new_content=new_text,
                    old_content=old_text,
                    max_lines=500,
                    start_line=start_line,
                )
                scroll_container = ScrollableDiffContainer()
                self.mount(scroll_container)
                scroll_container.mount(diff_widget)
                self._diff_mounted = True

        elif self.tool_name == "run_command":
            command = self.args.get("command", "")
            if command:
                self._mount_header()
                scroll_container = ScrollableDiffContainer()
                self.mount(scroll_container)
                scroll_container.mount(CommandPreviewBlock(command))
                self._diff_mounted = True

    def _mount_header(self) -> None:
        """Mount a header widget that can be updated on status change.

        Mounting children hides render(), so tools with children need an
        explicit header widget. Stored as _header_widget so watch_status
        can refresh it when status changes.
        """
        self._header_widget = Static(self._render_header_line())
        self.mount(self._header_widget)

    @staticmethod
    def _find_line_offset(file_path: str, old_text: str) -> int:
        """Read file and find the line number where old_text starts.

        Returns 1 if the file can't be read or old_text isn't found (safe fallback).
        """
        if not file_path or not old_text:
            return 1
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            pos = content.find(old_text)
            if pos == -1:
                return 1
            return content[:pos].count("\n") + 1
        except Exception:
            return 1

    def _mount_approval_after_diff(self) -> None:
        """Mount approval widget after deferred diff mount completes."""
        if self._approval_widget and not self._approval_widget.is_attached:
            self.mount(self._approval_widget)
            self.call_after_refresh(self._focus_approval)

    def _focus_approval(self) -> None:
        """Focus the approval widget after it's rendered."""
        if self._approval_widget and hasattr(self._approval_widget, "focus"):
            self._approval_widget.focus()
            self._approval_widget.scroll_visible()

    def compose(self) -> ComposeResult:
        """Compose child widgets.

        NOTE: Approval widget is mounted in on_mount() instead of here because
        Static widgets don't reliably render children from compose().
        """
        # Empty generator - approval widget is mounted explicitly in on_mount()
        if False:
            yield

    def _get_content_preview(self) -> Text | None:
        """Get content preview for write_file tool."""
        if self.tool_name != "write_file":
            return None

        content = self.args.get("content", "")
        if not content:
            return None

        # Limit preview to 15 lines for compact display
        lines = content.split("\n")
        max_lines = 15
        if len(lines) > max_lines:
            preview_lines = lines[:max_lines]
            truncated = True
        else:
            preview_lines = lines
            truncated = False

        result = Text()
        result.append("    Content:\n", style="cyan bold")

        for i, line in enumerate(preview_lines, 1):
            # Line number (right-aligned, 4 chars) + green line
            result.append(f"    {i:3d} ", style="dim")
            result.append(f"{line}\n", style="green")

        if truncated:
            result.append(f"        ... ({len(lines) - max_lines} more lines)\n", style="dim")

        return result

    def _get_diff_preview(self) -> Text | None:
        """Get diff preview for edit_file tool."""
        if self.tool_name != "edit_file":
            return None

        old_text = self.args.get("old_text", "")
        new_text = self.args.get("new_text", "")

        if not old_text and not new_text:
            return None

        # Generate unified diff
        old_lines = old_text.split("\n")
        new_lines = new_text.split("\n")

        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                lineterm="",
                n=1,  # Minimal context for compact display
            )
        )

        if not diff:
            # If no diff generated but texts differ, show simple before/after
            if old_text != new_text:
                result = Text()
                result.append("    Changes:\n", style="cyan bold")
                # Show truncated old/new
                old_preview = old_text[:60] + "..." if len(old_text) > 60 else old_text
                new_preview = new_text[:60] + "..." if len(new_text) > 60 else new_text
                result.append(f"    - {old_preview}\n", style="red")
                result.append(f"    + {new_preview}\n", style="green")
                return result
            return None

        result = Text()
        result.append("    Changes:\n", style="cyan bold")

        # Skip the first 2 lines (--- and +++ headers)
        for line in diff[2:]:
            if line.startswith("@@"):
                # Hunk header - skip for cleaner display
                continue
            elif line.startswith("-"):
                # Deleted line - red
                result.append(f"    {line}\n", style="red")
            elif line.startswith("+"):
                # Added line - green
                result.append(f"    {line}\n", style="green")
            else:
                # Context line
                result.append(f"     {line}\n", style="dim")

        return result

    def _render_header_line(self) -> Text:
        """Build the header line (status badge + tool name + args).

        Used both by render() and as a mounted child widget when preview
        children are present (Textual hides render() when children exist).
        """
        color = self.STATUS_COLORS.get(self.status, "#888888")

        result = Text()
        result.append(" ", style="")
        result.append("\u25cf", style=f"bold {color}")
        result.append("  ", style="")
        result.append(self.tool_name, style="bold #e0e0e0")

        main_arg = self._get_main_arg()
        if main_arg:
            result.append("(", style="#6e7681")
            result.append(main_arg, style="#9cdcfe")
            result.append(")", style="#6e7681")

        secondary_args = self._format_secondary_args()
        if secondary_args:
            result.append(f"  {secondary_args}", style="#6e7681")

        return result

    def render(self) -> RenderableType:
        """Render the tool card in polished VS Code style."""
        result = self._render_header_line()

        # NOTE: Content/Diff preview is now handled by DiffWidget (mounted as child)
        # run_command preview is handled by CommandPreviewBlock (mounted as child)
        # The DiffWidget provides professional formatting with:
        # - Line numbers
        # - Background colors (green for additions, red for deletions)
        # - Summary statistics ("Added X lines, removed Y lines")

        # Result or error (indented, polished styling)
        if self.error_message:
            result.append("\n")
            result.append("      ", style="")
            result.append(self.error_message, style="dim #d48a8a")
        elif self.result_preview:
            result.append("\n")
            result.append("      ", style="")
            result.append(self.result_preview, style="#6a9955")  # Muted green
            if self.duration_ms:
                result.append(f" [{self.duration_ms}ms]", style="#6e7681")

        return result

    def _get_main_arg(self) -> str:
        """Get the main argument value for inline display."""
        if not self.args:
            return ""

        # run_command: full command shown on dedicated line in render(), skip inline
        if self.tool_name == "run_command":
            return ""

        # delegate_to_subagent: show subagent type prominently
        if self.tool_name == "delegate_to_subagent" and "subagent" in self.args:
            return self.args["subagent"]

        # Common main argument names by priority
        main_keys = [
            "subagent",
            "file_path",
            "path",
            "filename",
            "command",
            "query",
            "pattern",
            "url",
            "name",
            "content",
            "message",
            "text",
        ]

        for key in main_keys:
            if key in self.args:
                value = self.args[key]
                if isinstance(value, str):
                    # Truncate long values
                    if len(value) > 50:
                        return value[:47] + "..."
                    return value
                return str(value)[:50]

        # Fallback: use first string argument
        for _key, value in self.args.items():
            if isinstance(value, str) and value:
                if len(value) > 50:
                    return value[:47] + "..."
                return value

        return ""

    def _format_secondary_args(self) -> str:
        """Format secondary arguments (excluding main arg and preview content)."""
        if not self.args:
            return ""

        # Keys to exclude from secondary args display
        # - main_keys: shown as the main argument in parentheses
        # - preview_keys: shown in content/diff preview section
        main_keys = [
            "subagent",
            "file_path",
            "path",
            "filename",
            "command",
            "query",
            "pattern",
            "url",
            "name",
            "content",
            "message",
            "text",
        ]
        preview_keys = ["old_text", "new_text"]  # Shown in diff preview

        parts = []
        for key, value in self.args.items():
            # Skip main argument and preview content
            if key in main_keys or key in preview_keys:
                continue

            if isinstance(value, str):
                if len(value) > 20:
                    value = value[:17] + "..."
                parts.append(f'{key}="{value}"')
            elif isinstance(value, bool):
                parts.append(f"{key}={str(value).lower()}")
            elif isinstance(value, int | float):
                parts.append(f"{key}={value}")
            elif isinstance(value, list):
                parts.append(f"{key}=[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}={{..}}")

        result = "  ".join(parts[:2])  # Max 2 secondary args
        if len(result) > 40:
            result = result[:37] + "..."
        return result

    def _format_args_preview(self) -> str:
        """Format arguments as compact preview (legacy method)."""
        if not self.args:
            return ""

        parts = []
        for key, value in list(self.args.items())[:3]:
            if isinstance(value, str):
                if len(value) > 40:
                    value = value[:37] + "..."
                # Escape quotes for display
                value = value.replace('"', '\\"')
                parts.append(f'{key}="{value}"')
            elif isinstance(value, bool):
                parts.append(f"{key}={str(value).lower()}")
            elif isinstance(value, int | float):
                parts.append(f"{key}={value}")
            elif isinstance(value, list):
                parts.append(f"{key}=[{len(value)} items]")
            elif isinstance(value, dict):
                parts.append(f"{key}={{...}}")
            else:
                parts.append(f"{key}=...")

        result = "  ".join(parts)

        # Truncate if too long
        if len(result) > 80:
            result = result[:77] + "..."

        return result

    def set_result(self, result: Any, duration_ms: int | None = None) -> None:
        """
        Set successful result.

        Args:
            result: The tool execution result
            duration_ms: Execution duration in milliseconds
        """
        self.status = ToolStatus.SUCCESS
        self.result_preview = self._format_result(result)
        if duration_ms:
            self.duration_ms = duration_ms

        # For run_command, pass output to the CommandPreviewBlock
        if self.tool_name == "run_command" and isinstance(result, str) and result:
            for child in self.query(CommandPreviewBlock):
                child.set_output(result)
                break

    def set_error(self, error: str) -> None:
        """
        Set error state.

        Extracts human-readable message from structured <tool_failure> blocks
        that are designed for the LLM, not the user.

        Args:
            error: Error message (may be a structured tool_failure prompt)
        """
        self.status = ToolStatus.FAILED

        # For run_command, extract command output and show in the preview block.
        # The error content format is: "Command output:\n<output>\n\n<tool_failure>..."
        if self.tool_name == "run_command" and error:
            output_text = error
            # Strip the <tool_failure> metadata block (designed for LLM, not user)
            if "<tool_failure>" in error:
                output_text = error.split("<tool_failure>")[0].strip()
            # Strip the "Command output:" prefix
            if output_text.startswith("Command output:\n"):
                output_text = output_text[len("Command output:\n") :]
            if output_text:
                for child in self.query(CommandPreviewBlock):
                    child.set_output(output_text)
                    break

        # Extract "error: ..." line from structured <tool_failure> blocks
        if error and "<tool_failure>" in error:
            for line in error.split("\n"):
                stripped = line.strip()
                if stripped.startswith("error:"):
                    self.error_message = stripped[6:].strip()[:100]
                    return
        self.error_message = error.split("\n")[0].strip()[:100] if error else "(unknown error)"

    def _format_result(self, result: Any) -> str:
        """Format result for preview."""
        if result is None:
            return "(no output)"

        if isinstance(result, str):
            lines = result.count("\n") + 1
            if lines > 1:
                return f"({lines} lines)"
            elif len(result) > 60:
                return result[:57] + "..."
            else:
                return result or "(empty)"

        elif isinstance(result, dict):
            return f"({len(result)} keys)"

        elif isinstance(result, list):
            return f"({len(result)} items)"

        elif isinstance(result, bool):
            return str(result).lower()

        elif isinstance(result, int | float):
            return str(result)

        else:
            preview = str(result)[:60]
            if len(str(result)) > 60:
                preview += "..."
            return preview

    def approve(self) -> None:
        """Programmatically approve this tool call."""
        self.status = ToolStatus.APPROVED

    def reject(self) -> None:
        """Programmatically reject this tool call."""
        self.status = ToolStatus.REJECTED

    def start_running(self) -> None:
        """Mark as running."""
        self.status = ToolStatus.RUNNING

    def cancel(self) -> None:
        """Mark as cancelled."""
        self.status = ToolStatus.CANCELLED


class ToolApprovalOptions(Static, can_focus=True):
    """
    Inline approval UI matching Claude Code style.

    Shows:
        Do you want to allow this action?
          1. Yes
          2. Yes, allow all [tool] during this session
        > 3. [Provide alternative instructions]

        Esc to cancel

    Features:
    - Options 1-2 are quick approve actions
    - Option 3 is an inline text input for feedback
    - Typing automatically selects option 3 and captures text
    - Esc cancels/rejects the tool call

    Posts ApprovalResponseMessage when user makes selection.
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("enter", "select", "Select", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding("backspace", "backspace", show=False, priority=True),
        # Note: 1, 2, y, j, k are handled in on_key() to allow typing in feedback mode
    ]

    # Only 2 fixed options - option 3 is the feedback input
    OPTIONS = [
        ("yes", "Yes"),
        ("yes_all", "Yes, allow all {tool} during this session"),
    ]

    FEEDBACK_PLACEHOLDER = "Provide alternative instructions"

    selected_index = reactive(0)
    feedback_text = reactive("")

    DEFAULT_CSS = """
    ToolApprovalOptions {
        height: auto;
        padding: 1 2;
        margin: 1 2;
        background: #1e2433;
        border: round #3794ff;
    }

    ToolApprovalOptions:focus {
        border: round #3794ff;
        background: #1e2838;
    }
    """

    def __init__(self, call_id: str, tool_name: str = "", args: dict | None = None, **kwargs):
        """
        Initialize approval options.

        Args:
            call_id: Tool call ID to include in response
            tool_name: Name of the tool being approved
            args: Tool arguments dictionary
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self.call_id = call_id
        self.tool_name = tool_name
        self.args = args or {}

    def on_mount(self) -> None:
        """Focus on mount to capture key events."""
        self.call_after_refresh(self._ensure_focus)

    def _ensure_focus(self) -> None:
        """Ensure this widget has focus for key events."""
        if not self.has_focus:
            self.focus()
            self.scroll_visible()

    def on_key(self, event) -> None:
        """Handle key presses for text input and shortcuts."""
        # Check if we're in feedback mode (typing text)
        in_feedback_mode = self.selected_index == 2 or self.feedback_text

        if event.is_printable and event.character:
            if not in_feedback_mode:
                # Handle shortcut keys when NOT in feedback mode
                if event.character == "1":
                    self.selected_index = 0
                    self._submit_selection()
                    event.prevent_default()
                    event.stop()
                    return
                elif event.character == "2":
                    self.selected_index = 1
                    self._submit_selection()
                    event.prevent_default()
                    event.stop()
                    return
                elif event.character == "y":
                    self.selected_index = 0
                    self._submit_selection()
                    event.prevent_default()
                    event.stop()
                    return
                elif event.character == "k":
                    self.selected_index = max(0, self.selected_index - 1)
                    event.prevent_default()
                    event.stop()
                    return
                elif event.character == "j":
                    self.selected_index = min(2, self.selected_index + 1)
                    event.prevent_default()
                    event.stop()
                    return

            # Any other printable character (or any char in feedback mode) -> type it
            self.selected_index = 2
            self.feedback_text += event.character
            event.prevent_default()
            event.stop()

    def action_backspace(self) -> None:
        """Handle backspace in feedback mode."""
        if self.selected_index == 2 and self.feedback_text:
            self.feedback_text = self.feedback_text[:-1]

    def render(self) -> RenderableType:
        """Render the approval options with polished styling."""
        lines = []

        # Question header - badge style
        lines.append(Text(" ? ", style="bold #1e1e1e on #3794ff"))
        lines.append(Text(" Allow this action?\n\n", style="bold #e0e0e0"))

        # Option 1: Yes
        if self.selected_index == 0:
            lines.append(Text("  ", style=""))
            lines.append(Text(" 1 ", style="bold #1e1e1e on #73c991"))
            lines.append(Text(" Yes\n", style="bold #73c991"))
        else:
            lines.append(Text("   1  ", style="#6e7681"))
            lines.append(Text("Yes\n", style="#a0a0a0"))

        # Option 2: Yes, allow all [tool] during this session
        tool_display = self.tool_name or "this tool"
        if self.selected_index == 1:
            lines.append(Text("  ", style=""))
            lines.append(Text(" 2 ", style="bold #1e1e1e on #3794ff"))
            lines.append(Text(" Yes, allow all ", style="bold #3794ff"))
            lines.append(Text(tool_display, style="bold #9cdcfe"))
            lines.append(Text(" this session\n", style="bold #3794ff"))
        else:
            lines.append(Text("   2  ", style="#6e7681"))
            lines.append(Text(f"Yes, allow all {tool_display} this session\n", style="#a0a0a0"))

        # Option 3: Feedback input
        if self.feedback_text or self.selected_index == 2:
            if self.selected_index == 2:
                lines.append(Text("  ", style=""))
                lines.append(Text(" 3 ", style="bold #1e1e1e on #cca700"))
                lines.append(Text(" ", style=""))
                if self.feedback_text:
                    lines.append(Text(self.feedback_text, style="bold #cca700"))
                    lines.append(Text("_", style="blink #cca700"))
                else:
                    lines.append(Text(self.FEEDBACK_PLACEHOLDER, style="italic #6e7681"))
                    lines.append(Text("_", style="blink #cca700"))
                lines.append(Text("\n"))
            else:
                lines.append(Text("   3  ", style="#6e7681"))
                lines.append(
                    Text(self.feedback_text or self.FEEDBACK_PLACEHOLDER, style="italic #6e7681")
                )
                lines.append(Text("\n"))
        else:
            lines.append(Text("   3  ", style="#6e7681"))
            lines.append(Text(self.FEEDBACK_PLACEHOLDER + "\n", style="italic #505050"))

        # Footer with keyboard hints
        lines.append(Text("\n"))
        lines.append(Text(" Esc ", style="#6e7681 on #2a2a2a"))
        lines.append(Text(" cancel  ", style="#6e7681"))
        lines.append(Text(" Enter ", style="#6e7681 on #2a2a2a"))
        lines.append(Text(" confirm", style="#6e7681"))

        return Text("").join(lines)

    def action_move_up(self) -> None:
        """Move selection up."""
        self.selected_index = max(0, self.selected_index - 1)

    def action_move_down(self) -> None:
        """Move selection down."""
        self.selected_index = min(2, self.selected_index + 1)  # 3 options (0, 1, 2)

    def action_select(self) -> None:
        """Confirm current selection."""
        self._submit_selection()

    def action_cancel(self) -> None:
        """Cancel (reject) the tool call."""
        self.post_message(ApprovalResponseMessage(self.call_id, "no"))

    def _submit_selection(self) -> None:
        """Submit the current selection."""
        if self.selected_index == 2:
            # Feedback mode - reject with feedback text
            feedback = self.feedback_text.strip() if self.feedback_text else None
            self.post_message(ApprovalResponseMessage(self.call_id, "no", feedback=feedback))
        else:
            # Regular option
            action, _ = self.OPTIONS[self.selected_index]
            self.post_message(ApprovalResponseMessage(self.call_id, action))
