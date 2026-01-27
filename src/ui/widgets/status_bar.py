"""
StatusBar - Bottom status bar with model info, errors, and shortcuts.

Features:
- Current model name
- Token count during streaming
- Elapsed time during streaming
- Error messages with countdown
- Keyboard shortcuts hint

Performance Optimizations:
- Uses layout=False in refresh() to skip expensive layout recalculation
- Timer runs at 150ms for smooth spinner, stopped when not streaming
- Debug counters available via TUI_PERF_DEBUG=1
"""

from textual.widgets import Static
from textual.reactive import reactive
from textual.timer import Timer
from rich.text import Text
from rich.console import RenderableType
import os
import time

# Performance debug flag - set TUI_PERF_DEBUG=1 to enable
TUI_PERF_DEBUG = os.getenv("TUI_PERF_DEBUG", "").lower() in ("1", "true", "yes")

# Performance counters (global)
_status_bar_counters = {
    "refresh_ticks": 0,
}

def get_status_bar_counters() -> dict:
    """Get current status bar performance counters (for debugging)."""
    return _status_bar_counters.copy()

def reset_status_bar_counters() -> None:
    """Reset status bar performance counters."""
    global _status_bar_counters
    _status_bar_counters = {
        "refresh_ticks": 0,
    }


class StatusBar(Static):
    """
    Bottom status bar.

    Shows:
    - Current model name (left)
    - Token count and elapsed time (left, when streaming)
    - Error messages with countdown (center)
    - Keyboard shortcuts (right)

    Usage:
        status = StatusBar(model_name="claude-3-opus")
        await container.mount(status)

        # During streaming
        status.set_streaming(True)
        status.update_tokens(150)

        # On error
        status.show_error("Rate limited", countdown=60)

    Attributes:
        model_name: Name of the current LLM
        token_count: Number of tokens (during streaming)
        is_streaming: Whether currently streaming
        error_message: Current error message
        countdown: Countdown seconds for rate limits
    """

    # Reactive attributes
    model_name = reactive("claude-3-opus")
    token_count = reactive(0)
    buffered_chars = reactive(0)  # Characters buffered in segmented mode
    is_streaming = reactive(False)
    elapsed_seconds = reactive(0)
    error_message = reactive("")
    info_message = reactive("")  # Temporary info message (auto-clears)
    countdown = reactive(0)
    spinner_frame = reactive(0)
    current_tool = reactive("")  # Name of currently executing tool
    current_mode = reactive("normal")  # Permission mode: plan, normal, auto
    current_task_name = reactive("")  # activeForm of in_progress todo task

    # Context window tracking (values set by agent, not hardcoded)
    context_used = reactive(0)  # Tokens currently used in context
    context_limit = reactive(0)  # Max context window (0 = not set, hide bar)
    context_pressure = reactive("green")  # Pressure level from agent (green/yellow/orange/red)

    # Spinner animation frames (ASCII-safe for Windows compatibility)
    SPINNER_FRAMES = ["|", "/", "-", "\\"]

    DEFAULT_CSS = """
    StatusBar {
        height: 2;
        min-height: 1;
        background: #1a1a1a;
        color: #6e7681;
        padding: 0 2;
        border-top: solid #2a2a2a;
    }
    """

    def __init__(
        self,
        model_name: str = "claude-3-opus",
        **kwargs
    ):
        """
        Initialize StatusBar.

        Args:
            model_name: Name of the LLM model
            **kwargs: Additional arguments for Static
        """
        super().__init__(**kwargs)
        self.model_name = model_name
        self._stream_start_time: float = 0
        self._refresh_timer: Timer | None = None  # Single timer for all updates
        self._countdown_timer: Timer | None = None
        self._info_timer: Timer | None = None  # Timer for auto-clearing info messages

    def render(self) -> RenderableType:
        """Render the status bar with premium formatting.

        Format: * State | mm:ss (no model name)
        Empty when idle.
        """
        # PERFORMANCE TEST: Return minimal content when idle
        # This tests if complex status bar rendering is causing performance issues
        if not self.is_streaming and not self.current_tool and not self.error_message and not self.info_message:
            # Minimal idle state - just show mode if not normal
            if self.current_mode == "plan":
                return Text(" PLAN ", style="bold #1e1e1e on #cca700")
            elif self.current_mode == "auto":
                return Text(" AUTO ", style="bold #1e1e1e on #73c991")
            return Text("")  # Empty when truly idle

        result = Text()

        # Calculate elapsed time locally (don't mutate reactives in render)
        elapsed_str = ""
        if self._stream_start_time:
            elapsed = int(time.monotonic() - self._stream_start_time)
            minutes, seconds = divmod(elapsed, 60)
            elapsed_str = f"{minutes:02d}:{seconds:02d}"

        # Compute spinner frame from time (self-correcting, no counter needed)
        spinner = ""
        if self.is_streaming or self.current_tool:
            frame = int(time.monotonic() * 10) % len(self.SPINNER_FRAMES)
            spinner = self.SPINNER_FRAMES[frame]

        # State indicator
        if self.error_message:
            # Error state - badge style
            result.append(" ERROR ", style="bold #ffffff on #f14c4c")
            result.append(" ", style="")
            if self.countdown > 0:
                result.append(f"{self.error_message} ({self.countdown}s)", style="#cca700")
            else:
                result.append(f"{self.error_message}", style="#f14c4c")
        elif self.info_message:
            # Info state - badge style (blue/cyan for informational)
            result.append(" INFO ", style="bold #1e1e1e on #3794ff")
            result.append(" ", style="")
            result.append(f"{self.info_message}", style="#3794ff")
        elif self.current_tool:
            # Tool executing state - animated spinner with refined colors
            result.append(f"{spinner} ", style="#3794ff")
            result.append(f"{self.current_tool}", style="#9cdcfe")
            if elapsed_str:
                result.append(f" | {elapsed_str}", style="#6e7681")
        elif self.is_streaming:
            # Streaming state - animated spinner with refined colors
            result.append(f"{spinner} ", style="#3794ff")
            # Show current task name if available, otherwise "Streaming"
            if self.current_task_name:
                result.append(self.current_task_name, style="#3794ff")
            else:
                result.append("Streaming", style="#3794ff")
            if elapsed_str:
                result.append(f" | {elapsed_str}", style="#6e7681")
        else:
            # Idle state - show ready indicator
            result.append("| Ready", style="#6e7681")

        # Mode indicator (badge style, show only if not normal)
        if self.current_mode == "plan":
            result.append(" ", style="")
            result.append(" PLAN ", style="bold #1e1e1e on #cca700")
        elif self.current_mode == "auto":
            result.append(" ", style="")
            result.append(" AUTO ", style="bold #1e1e1e on #73c991")

        # Context window progress bar (right-aligned)
        if self.context_limit > 0:
            context_bar = self._render_context_bar()
            # Pad to push context bar to the right
            # Get terminal width, subtract context bar length
            try:
                width = self.app.size.width if self.app else 80
            except (AttributeError, RuntimeError):
                width = 80
            current_len = len(result.plain)
            context_len = len(context_bar.plain)
            min_width_needed = current_len + context_len + 6  # +6 for margins and spacing

            # Skip context bar on narrow terminals to avoid layout issues
            if width >= min_width_needed:
                padding = width - current_len - context_len - 4  # -4 for margins
                result.append(" " * padding)
                result.append_text(context_bar)

        return result

    def _render_context_bar(self) -> Text:
        """Render the context window progress bar."""
        result = Text()

        # Format: 44.9k ████░░░░ 200.0k
        used_k = self.context_used / 1000
        limit_k = self.context_limit / 1000

        # Calculate percentage for bar fill
        if self.context_limit > 0:
            percent = min(100, (self.context_used / self.context_limit) * 100)
        else:
            percent = 0

        # Use pressure level from agent (consistent thresholds: 70/85/95)
        # Map pressure levels to Rich styles (orange -> bright_yellow)
        pressure_styles = {
            "green": "green",
            "yellow": "yellow",
            "orange": "bright_yellow",  # Rich doesn't have orange
            "red": "red",
        }
        bar_style = pressure_styles.get(self.context_pressure, "green")

        # Build progress bar (10 chars wide)
        bar_width = 10
        filled = int(bar_width * percent / 100)
        empty = bar_width - filled

        # Format numbers with appropriate precision
        # >= 100k: "150k" (no decimal)
        # >= 10k:  "44.9k" (1 decimal)
        # < 10k:   "5.23k" (2 decimals for small values)
        if used_k >= 100:
            used_str = f"{used_k:.0f}k"
        elif used_k >= 10:
            used_str = f"{used_k:.1f}k"
        else:
            used_str = f"{used_k:.2f}k"

        if limit_k >= 100:
            limit_str = f"{limit_k:.0f}k"
        else:
            limit_str = f"{limit_k:.1f}k"

        result.append(f"{used_str} ", style="#6e7681")
        result.append("█" * filled, style=bar_style)
        result.append("░" * empty, style="#3a3a3a")
        result.append(f" {limit_str}", style="#6e7681")

        return result

    def set_streaming(self, is_streaming: bool) -> None:
        """
        Update streaming state.

        Args:
            is_streaming: Whether currently streaming
        """
        if is_streaming and not self.is_streaming:
            # Starting to stream
            self._stream_start_time = time.monotonic()
            self.elapsed_seconds = 0
            self.spinner_frame = 0
            self._start_refresh_timer()

        elif not is_streaming and self.is_streaming:
            # Stopped streaming
            self._stop_refresh_timer()

        self.is_streaming = is_streaming

        if not is_streaming:
            self.token_count = 0
            self.buffered_chars = 0

    def _start_refresh_timer(self) -> None:
        """Start periodic refresh timer for animation updates.

        Performance (Fix #1):
        - Timer runs at 150ms (smooth spinner, ~7 ticks/sec)
        - Uses layout=False to skip expensive layout recalculation
        - Timer only runs during streaming, stopped otherwise
        """
        if self._refresh_timer:
            self._refresh_timer.stop()
        # Refresh every 150ms for smooth spinner (between 100-200ms as specified)
        # render() calculates current time/spinner frame dynamically
        self._refresh_timer = self.set_interval(0.15, self._trigger_refresh)

    def _stop_refresh_timer(self) -> None:
        """Stop refresh timer."""
        if self._refresh_timer:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def _trigger_refresh(self) -> None:
        """Force a cheap refresh without layout recalculation (Fix #1).

        Uses layout=False to skip expensive layout pass - status bar has
        fixed height so layout never needs to change during refresh.
        """
        # Performance counter
        _status_bar_counters["refresh_ticks"] += 1

        # Performance: layout=False skips layout recalculation
        # Status bar has fixed height (2 lines) so layout never changes
        self.refresh(layout=False)

    def update_tokens(self, count: int) -> None:
        """
        Update token count.

        Args:
            count: New token count
        """
        self.token_count = count

    def increment_tokens(self, delta: int = 1) -> None:
        """
        Increment token count.

        Args:
            delta: Amount to add to token count
        """
        self.token_count += delta

    def update_buffered_chars(self, count: int) -> None:
        """
        Update buffered character count (for segmented streaming feedback).

        Args:
            count: Current buffered character count
        """
        self.buffered_chars = count

    def show_error(self, message: str, countdown: int = 0) -> None:
        """
        Show error message, optionally with countdown.

        Args:
            message: Error message to display
            countdown: Countdown seconds (for rate limits)
        """
        self.error_message = message
        self.countdown = countdown

        if countdown > 0:
            self._start_countdown()

    def clear_error(self) -> None:
        """Clear error message."""
        self.error_message = ""
        self.countdown = 0
        self._stop_countdown()

    def show_info(self, message: str, duration: float = 3.0) -> None:
        """
        Show temporary info message (auto-clears after duration).

        Args:
            message: Info message to display
            duration: Seconds before auto-clear (default 3s)
        """
        # Cancel any existing info timer to prevent premature clearing
        if self._info_timer:
            self._info_timer.stop()

        self.info_message = message
        # Auto-clear after duration
        self._info_timer = self.set_timer(duration, self._clear_info)

    def _clear_info(self) -> None:
        """Clear info message."""
        self.info_message = ""
        self._info_timer = None

    def _start_countdown(self) -> None:
        """Start countdown timer."""
        if self._countdown_timer:
            self._countdown_timer.stop()

        self._countdown_timer = self.set_interval(1.0, self._update_countdown)

    def _stop_countdown(self) -> None:
        """Stop countdown timer."""
        if self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def _update_countdown(self) -> None:
        """Update countdown."""
        if self.countdown > 0:
            self.countdown -= 1
        else:
            self.error_message = ""
            self._stop_countdown()

    def set_model(self, model_name: str) -> None:
        """
        Update model name.

        Args:
            model_name: New model name
        """
        self.model_name = model_name

    def update_context(self, used: int, limit: int, pressure: str = "green") -> None:
        """
        Update context window usage display.

        Args:
            used: Tokens currently used in context
            limit: Maximum context window size
            pressure: Pressure level from agent (green/yellow/orange/red)
        """
        # Validate inputs (ignore invalid values)
        if used < 0 or limit < 0:
            return
        # Clamp used to limit (LLM might report slightly over)
        self.context_used = min(used, limit) if limit > 0 else used
        self.context_limit = limit
        self.context_pressure = pressure if pressure in ("green", "yellow", "orange", "red") else "green"

    def set_context_limit(self, limit: int) -> None:
        """
        Set context window limit (call once at startup).

        Args:
            limit: Maximum context window size from config
        """
        self.context_limit = limit

    def update_context_used(self, used: int) -> None:
        """
        Update tokens used in context window.

        Args:
            used: Tokens currently used
        """
        self.context_used = used

    def set_mode(self, mode: str) -> None:
        """
        Update permission mode display.

        Args:
            mode: Permission mode ("plan", "normal", "auto")
        """
        self.current_mode = mode

    def set_tool(self, tool_name: str) -> None:
        """
        Set currently executing tool name.

        Args:
            tool_name: Tool name (empty string to clear)
        """
        self.current_tool = tool_name

    def clear_tool(self) -> None:
        """Clear current tool indicator."""
        self.current_tool = ""

    def set_current_task(self, task_name: str) -> None:
        """
        Set current task name (from in_progress todo).

        This is shown instead of "Streaming" in the status bar.

        Args:
            task_name: The activeForm of the in_progress todo (e.g., "Fixing bug")
        """
        self.current_task_name = task_name

    def clear_current_task(self) -> None:
        """Clear current task name."""
        self.current_task_name = ""

    def reset(self) -> None:
        """Reset all state (except context limit which persists)."""
        self.token_count = 0
        self.buffered_chars = 0
        self.elapsed_seconds = 0
        self.is_streaming = False
        self.error_message = ""
        self.countdown = 0
        self.spinner_frame = 0
        self.current_tool = ""
        self.current_task_name = ""
        self._stream_start_time = 0
        # Note: context_limit is NOT reset (set once at startup)
        # context_used will be updated when context is built
        self._stop_refresh_timer()
        self._stop_countdown()

    def on_unmount(self) -> None:
        """Clean up timers when widget is removed from DOM."""
        self._stop_refresh_timer()
        self._stop_countdown()
        if self._info_timer:
            self._info_timer.stop()
            self._info_timer = None


class StreamingIndicator(Static):
    """
    Simple streaming indicator showing animated dots.

    Can be used alongside or instead of StatusBar for
    a more prominent streaming indication.
    """

    is_active = reactive(False)

    DEFAULT_CSS = """
    StreamingIndicator {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dot_count = 0
        self._timer: Timer | None = None

    def render(self) -> RenderableType:
        if not self.is_active:
            return Text("")

        dots = "." * (self._dot_count % 4)
        return Text(f"Generating{dots}", style="yellow")

    def watch_is_active(self, is_active: bool) -> None:
        """React to active state changes."""
        if is_active:
            self._timer = self.set_interval(0.3, self._update_dots)
        elif self._timer:
            self._timer.stop()
            self._timer = None
            self._dot_count = 0

    def _update_dots(self) -> None:
        """Update dot animation."""
        self._dot_count += 1
        self.refresh()

    def start(self) -> None:
        """Start the indicator."""
        self.is_active = True

    def stop(self) -> None:
        """Stop the indicator."""
        self.is_active = False

    def on_unmount(self) -> None:
        """Clean up timer when widget is removed from DOM."""
        if self._timer:
            self._timer.stop()
            self._timer = None
