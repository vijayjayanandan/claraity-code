"""
Professional TUI chat interface with fixed input box.

Matches Claude Code's UX:
- Fixed input box at bottom
- Scrollable chat history above
- Colored status indicator
- Alt+M mode toggle
- Real-time streaming with asyncio
- TUI-native approval dialogs (selection list)
"""

import sys
import os
import asyncio
from dataclasses import dataclass
from pathlib import Path

# CRITICAL: Remove TERM variable on Windows BEFORE importing prompt_toolkit
# This prevents prompt_toolkit from thinking we're in a Unix terminal
if sys.platform == 'win32' and 'TERM' in os.environ:
    del os.environ['TERM']

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import Layout, HSplit, Window, VSplit
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
from typing import Callable, Optional, List, Tuple, Awaitable, Union, Dict, Any


# Approval options for selection list
class ApprovalOption:
    """Indices for approval options."""
    YES = 0           # "Yes, execute"
    YES_AUTO = 1      # "Yes, and auto-approve all"
    NO = 2            # "No, skip this action"


APPROVAL_OPTIONS = [
    "Yes, execute",
    "Yes, and auto-approve all",
    "No, skip this action",
]


@dataclass
class ApprovalRequest:
    """Pending approval request data."""
    tool_name: str
    tool_args: Dict[str, Any]
    description: str  # Human-readable (e.g., "Write file: hello.py")
    future: asyncio.Future  # Will be set with True/False


def get_output():
    """Get the appropriate output for the current platform."""
    # TERM is already removed at module import time for Windows
    # Let prompt_toolkit auto-detect the output
    return None


class ChatTUI:
    """Professional chat interface with fixed input box and async streaming."""

    def __init__(
        self,
        agent,
        on_message: Optional[Callable[[str], str]] = None,
        on_message_async: Optional[Callable[[str, Callable[[str], Awaitable[None]]], Awaitable[str]]] = None,
    ):
        """
        Initialize chat interface.

        Args:
            agent: CodingAgent instance
            on_message: Sync callback (legacy, blocks UI)
            on_message_async: Async callback with streaming support (preferred)
                Signature: async def callback(user_input, on_chunk) -> str
                where on_chunk: async def(chunk: str) -> None
        """
        self.agent = agent
        self.on_message = on_message
        self.on_message_async = on_message_async
        self.chat_history: List[str] = []
        self.running = True
        self._processing = False  # Track if we're processing a message

        # Approval state for TUI-native approval dialogs
        self._pending_approval: Optional[ApprovalRequest] = None
        self._approval_selection: int = 0  # Currently highlighted option

        # Thinking indicator state
        self._thinking = False  # True when waiting for LLM response

        # Create buffers
        # Keep writable for updates, focusable=False on control prevents keyboard input
        self.output_buffer = Buffer(read_only=False)
        self.input_buffer = Buffer(
            multiline=False,
            accept_handler=self._handle_accept
        )

        # Create key bindings
        self.kb = self._create_key_bindings()

        # Create style
        self.style = self._create_style()

        # Create layout
        self.layout = self._create_layout()

        # Create application with platform-specific output
        # mouse_support=False allows native terminal text selection (like Claude Code)
        output = get_output()
        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=self.style,
            full_screen=True,
            mouse_support=False,  # Allow native terminal selection
            output=output,
        )

    def _create_key_bindings(self) -> KeyBindings:
        """Create key bindings."""
        kb = KeyBindings()

        # Filter: only active when approval is pending
        approval_pending = Condition(lambda: self._pending_approval is not None)
        approval_not_pending = Condition(lambda: self._pending_approval is None)

        # ===== APPROVAL KEY BINDINGS =====

        @kb.add('up', filter=approval_pending)
        @kb.add('k', filter=approval_pending)  # vim-style
        def move_up(event):
            """Move selection up."""
            if self._approval_selection > 0:
                self._approval_selection -= 1
                self.app.invalidate()

        @kb.add('down', filter=approval_pending)
        @kb.add('j', filter=approval_pending)  # vim-style
        def move_down(event):
            """Move selection down."""
            if self._approval_selection < len(APPROVAL_OPTIONS) - 1:
                self._approval_selection += 1
                self.app.invalidate()

        @kb.add('enter', filter=approval_pending)
        def confirm_selection(event):
            """Confirm the current selection."""
            if self._pending_approval:
                selection = self._approval_selection

                if selection == ApprovalOption.YES:
                    self._pending_approval.future.set_result(True)
                elif selection == ApprovalOption.YES_AUTO:
                    self.agent.set_permission_mode("auto")
                    self._pending_approval.future.set_result(True)
                    self._add_to_history("\n[Switched to AUTO mode]\n")
                else:  # NO
                    self._pending_approval.future.set_result(False)

                self._clear_approval()

        @kb.add('escape', filter=approval_pending)
        def cancel_approval(event):
            """Cancel/reject via Escape."""
            if self._pending_approval:
                self._pending_approval.future.set_result(False)
                self._clear_approval()

        # ===== NORMAL KEY BINDINGS =====

        @kb.add('escape', 'm')
        def toggle_mode(event):
            """Toggle mode with Alt+M."""
            current = self.agent.get_permission_mode()
            cycle = {"plan": "normal", "normal": "auto", "auto": "plan"}
            self.agent.set_permission_mode(cycle.get(current, "normal"))
            event.app.invalidate()

        @kb.add('c-c')
        def exit_ctrl_c(event):
            """Exit on Ctrl+C."""
            # If approval pending, reject it first
            if self._pending_approval:
                self._pending_approval.future.set_result(False)
                self._clear_approval()
            self.running = False
            event.app.exit()

        @kb.add('c-d')
        def exit_ctrl_d(event):
            """Exit on Ctrl+D."""
            if self._pending_approval:
                self._pending_approval.future.set_result(False)
                self._clear_approval()
            self.running = False
            event.app.exit()

        # ===== FOCUS SWITCHING KEY BINDINGS =====

        @kb.add('tab', filter=approval_not_pending)
        def switch_focus(event):
            """Switch focus between output (for scrolling) and input."""
            app = event.app
            # Check current focus and switch
            if hasattr(self, 'output_window') and hasattr(self, 'input_window'):
                current = app.layout.current_window
                if current == self.output_window:
                    app.layout.focus(self.input_window)
                else:
                    app.layout.focus(self.output_window)

        @kb.add('escape', filter=approval_not_pending)
        def return_to_input(event):
            """Return focus to input on Escape."""
            if hasattr(self, 'input_window'):
                event.app.layout.focus(self.input_window)

        return kb

    def _clear_approval(self):
        """Clear approval state and refresh UI."""
        self._pending_approval = None
        self._approval_selection = 0  # Reset to first option
        self.app.invalidate()

    def _create_style(self) -> Style:
        """Create color style."""
        return Style.from_dict({
            'output': '#cccccc',
            'separator': '#444444',
            'input': '#ffffff',
            'status': '#888888',
            'status-dot-plan': '#ffaa00',
            'status-dot-auto': '#00ff88',
            # Approval selection list styles
            'approval': 'bg:#1a1a2e',             # Dark background
            'approval-header': '#ff9900 bold',     # Orange header
            'approval-selected': '#00ff88 bold',   # Green selected option
            'approval-option': '#888888',          # Gray unselected options
            'approval-hint': '#666666 italic',     # Dim hint text
            # Thinking indicator
            'thinking': '#00aaff',                 # Blue thinking indicator
        })

    def _get_status_text(self) -> List[Tuple[str, str]]:
        """Generate status bar content."""
        result = []

        # Show thinking indicator (takes priority)
        if self._thinking:
            result.append(('class:thinking', '● Thinking...'))

        # Show mode indicator
        mode = self.agent.get_permission_mode().lower()
        if mode == "plan":
            if result:
                result.append(('class:status', ' | '))
            result.append(('class:status-dot-plan', '● '))
            result.append(('class:status', 'plan mode'))
        elif mode == "auto":
            if result:
                result.append(('class:status', ' | '))
            result.append(('class:status-dot-auto', '● '))
            result.append(('class:status', 'auto mode'))

        return result

    def _get_approval_text(self) -> List[Tuple[str, str]]:
        """Generate approval selection list content."""
        if not self._pending_approval:
            return []

        result = []

        # Header with action description
        result.append(('class:approval-header', f'Approve: {self._pending_approval.description}?\n\n'))

        # Options with selection indicator
        for i, option in enumerate(APPROVAL_OPTIONS):
            if i == self._approval_selection:
                # Selected option (highlighted)
                result.append(('class:approval-selected', f'> {i+1}. {option}\n'))
            else:
                # Unselected option
                result.append(('class:approval-option', f'  {i+1}. {option}\n'))

        # Footer with key hints
        result.append(('class:approval-hint', '\nEnter to select | Arrow keys to navigate | Esc to cancel'))

        return result

    def _create_layout(self) -> Layout:
        """Create the UI layout with conditional approval overlay."""
        # Filters for conditional containers
        approval_pending = Condition(lambda: self._pending_approval is not None)
        approval_not_pending = Condition(lambda: self._pending_approval is None)

        # Create windows
        # Output window: focusable=True for keyboard scrolling (Tab to focus)
        # Native terminal selection works via mouse (mouse_support=False on app)
        self.output_control = BufferControl(buffer=self.output_buffer, focusable=True)
        self.output_window = Window(
            content=self.output_control,
            wrap_lines=True,
            style='class:output',
        )

        self.input_control = BufferControl(
            buffer=self.input_buffer,
            input_processors=[BeforeInput('> ')],
            focusable=True,
        )
        self.input_window = Window(
            content=self.input_control,
            height=1,
            style='class:input',
        )

        # Approval selection window (replaces input when pending)
        self.approval_window = Window(
            content=FormattedTextControl(self._get_approval_text),
            height=7,  # Fixed height for 3 options + header + hints
            style='class:approval',
        )

        return Layout(
            HSplit([
                # Chat history (scrollable, not focusable)
                self.output_window,
                # Separator
                Window(height=1, char='─', style='class:separator'),
                # Input area OR Approval selection (conditional)
                ConditionalContainer(self.input_window, filter=approval_not_pending),
                ConditionalContainer(self.approval_window, filter=approval_pending),
                # Status bar
                Window(
                    content=FormattedTextControl(self._get_status_text),
                    height=1,
                    style='class:status',
                ),
            ]),
            focused_element=self.input_window,  # Start with focus on input
        )

    def _handle_accept(self, buffer: Buffer) -> bool:
        """Handle input submission."""
        user_input = buffer.text.strip()

        if not user_input:
            return False

        # Prevent multiple concurrent requests
        if self._processing:
            return False

        # Clear input IMMEDIATELY before any processing
        buffer.reset()

        # Handle exit commands
        if user_input.lower() in ['exit', 'quit', 'q']:
            self.running = False
            self.app.exit()
            return False

        # Handle ? for help
        if user_input == '?':
            self._add_to_history(self._get_help_text())
            return True

        # Handle /mode commands
        if user_input.lower().startswith('/mode'):
            self._handle_mode_command(user_input)
            return True

        # Add user message to history
        self._add_to_history(f"You: {user_input}\n")

        # Use async processing if available (non-blocking, streaming)
        if self.on_message_async:
            # Add placeholder for streaming response
            self._add_to_history("Agent: ")
            self.app.invalidate()

            # Spawn background task - returns immediately, UI stays responsive
            asyncio.get_event_loop().create_task(
                self._process_message_async(user_input)
            )
            return True

        # Fallback to sync processing (legacy, blocks UI)
        self._add_to_history("Agent: ...\n")
        self.app.invalidate()

        try:
            response = self.on_message(user_input)
            self.chat_history.pop()  # Remove "..."
            self._add_to_history(f"Agent:\n{response}\n")
        except Exception as e:
            self.chat_history.pop()  # Remove "..."
            self._add_to_history(f"Error: {e}\n")

        return True

    async def _process_message_async(self, user_input: str) -> None:
        """Process message asynchronously with streaming updates."""
        self._processing = True
        self._thinking = True  # Show thinking indicator
        self.app.invalidate()  # Refresh to show indicator

        try:
            # Define the on_chunk callback that updates the UI
            async def on_chunk(chunk: str) -> None:
                # Clear thinking indicator on first chunk
                if self._thinking:
                    self._thinking = False

                # Append chunk to the last history entry (the "Agent: " line)
                if self.chat_history:
                    self.chat_history[-1] += chunk
                    # Update the buffer
                    content = '\n'.join(self.chat_history)
                    self.output_buffer.text = content
                    self.output_buffer.cursor_position = len(content)
                    # Refresh UI immediately
                    self.app.invalidate()

            # Call the async message handler with streaming and approval callbacks
            await self.on_message_async(user_input, on_chunk, self.request_approval)

            # After response completes, add newline for spacing
            if self.chat_history:
                self.chat_history[-1] += "\n"
                content = '\n'.join(self.chat_history)
                self.output_buffer.text = content
                self.output_buffer.cursor_position = len(content)
                self.app.invalidate()

        except Exception as e:
            # Handle errors
            self._add_to_history(f"\nError: {e}\n")

        finally:
            self._processing = False
            self._thinking = False  # Ensure indicator is cleared
            self.app.invalidate()

    def _handle_mode_command(self, cmd: str):
        """Handle /mode commands."""
        parts = cmd.lower().split()
        if len(parts) == 1:
            # Toggle
            current = self.agent.get_permission_mode()
            cycle = {"plan": "normal", "normal": "auto", "auto": "plan"}
            new_mode = cycle.get(current, "normal")
            self.agent.set_permission_mode(new_mode)
            self._add_to_history(f"Mode changed to {new_mode.upper()}\n")
        elif len(parts) == 2:
            mode_map = {'p': 'plan', 'n': 'normal', 'a': 'auto'}
            if parts[1] in mode_map:
                self.agent.set_permission_mode(mode_map[parts[1]])
                self._add_to_history(f"Mode changed to {mode_map[parts[1]].upper()}\n")

    def _get_help_text(self) -> str:
        """Get help text."""
        mode = self.agent.get_permission_mode().upper()
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Quick Reference | Current Mode: {mode}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Commands:
    /mode     Toggle mode (plan -> normal -> auto)
    /mode p   Set PLAN mode
    /mode n   Set NORMAL mode
    /mode a   Set AUTO mode
    exit      Quit

  Shortcuts:
    Tab       Switch focus (scroll/select in chat history)
    Esc       Return to input
    Alt+M     Toggle mode
    Ctrl+C    Exit

  When focused on chat history:
    Arrow keys, PgUp/PgDn to scroll
    Shift+Arrow to select text

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    def _add_to_history(self, text: str):
        """Add text to chat history."""
        self.chat_history.append(text)
        content = '\n'.join(self.chat_history)
        self.output_buffer.text = content
        # Scroll to bottom
        self.output_buffer.cursor_position = len(content)

    def add_message(self, text: str):
        """Add a message to the chat history (public method)."""
        self._add_to_history(text)

    async def request_approval(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """
        Request user approval for a tool operation.

        This method is called by the agent when it needs approval.
        It shows the approval selection list and waits for the user
        to select an option using arrow keys + Enter.

        Args:
            tool_name: Name of the tool (e.g., 'write_file')
            tool_args: Tool arguments

        Returns:
            True if approved, False if rejected
        """
        # Create human-readable description
        description = self._format_approval_description(tool_name, tool_args)

        # Create future for async coordination
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        # Set pending approval (triggers UI update via ConditionalContainer)
        self._pending_approval = ApprovalRequest(
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
            future=future,
        )

        # Refresh UI to show approval selection list
        self.app.invalidate()

        # Wait for user response (non-blocking - UI stays responsive)
        result = await future

        return result

    def _format_approval_description(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """Format approval description for the selection list header."""
        if tool_name == 'write_file':
            path = tool_args.get('file_path', 'unknown')
            return f"Write file: {Path(path).name}"
        elif tool_name == 'edit_file':
            path = tool_args.get('file_path', 'unknown')
            return f"Edit file: {Path(path).name}"
        elif tool_name == 'append_to_file':
            path = tool_args.get('file_path', 'unknown')
            return f"Append to: {Path(path).name}"
        elif tool_name == 'run_command':
            cmd = tool_args.get('command', 'unknown')[:50]
            return f"Run: {cmd}"
        elif tool_name == 'git_commit':
            msg = tool_args.get('message', '')[:40]
            return f"Commit: {msg}"
        else:
            return f"{tool_name}"

    async def run_async(self):
        """Run the chat interface asynchronously (preferred for streaming)."""
        # Add welcome message
        welcome = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AI Coding Agent
  Model: {self.agent.model_name}
  Context: {self.agent.context_window} tokens
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Type ? for help | Tab to scroll | Alt+M to toggle mode | exit to quit

"""
        self._add_to_history(welcome)

        try:
            # Run prompt_toolkit in async mode - enables background tasks
            await self.app.run_async()
        except Exception as e:
            raise RuntimeError(f"TUI failed: {e}")

    def run(self):
        """Run the chat interface.

        If on_message_async is provided, runs in async mode for streaming.
        Otherwise falls back to sync mode (legacy).
        """
        # Add welcome message
        welcome = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AI Coding Agent
  Model: {self.agent.model_name}
  Context: {self.agent.context_window} tokens
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Type ? for help | Tab to scroll | Alt+M to toggle mode | exit to quit

"""
        self._add_to_history(welcome)

        try:
            if self.on_message_async:
                # Use async mode for streaming support
                asyncio.run(self.app.run_async())
            else:
                # Legacy sync mode
                self.app.run()
        except Exception as e:
            raise RuntimeError(f"TUI failed: {e}")


def run_tui_chat(agent, controller=None, on_message=None, use_async: bool = True):
    """Run the TUI chat interface.

    Args:
        agent: CodingAgent instance
        controller: Optional LongRunningController
        on_message: Sync callback for processing messages (legacy)
        use_async: Whether to use async mode with streaming (default: True)
    """
    if use_async:
        # Async mode with streaming and TUI-native approval (preferred)
        async def on_message_async(user_input: str, on_chunk, request_approval) -> str:
            response = await agent.chat_async(
                user_input,
                on_chunk=on_chunk,
                request_approval=request_approval  # TUI-native approval dialog
            )
            return response.content

        tui = ChatTUI(agent, on_message_async=on_message_async)
    else:
        # Legacy sync mode
        if on_message is None:
            def on_message(user_input):
                return agent.chat(user_input, stream=False).content

        tui = ChatTUI(agent, on_message=on_message)

    tui.run()
