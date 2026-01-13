# Claude Code Prompt: Textual TUI for Coding Agent

## Context

I'm migrating my CLI coding agent's TUI from prompt_toolkit to Textual. The current implementation has issues with streaming output formatting, raw JSON tool calls leaking to the UI, and inability to render rich content.

## Current State

- **Framework**: prompt_toolkit with plain Buffer (can't render ANSI/Rich)
- **Pain Points**:
  - Tool call JSON appears before execution completes
  - Code fences break mid-stream
  - No syntax highlighting or markdown rendering
  - Duplicate tool announcements
- **Codebase**: ~650 lines in `src/ui/chat_interface.py` to replace
- **Integration**: Agent uses callbacks (`on_chunk`, `request_approval`, `on_tool_status`)

## Target Architecture

```
LLM Stream (raw chunks) 
    → StreamProcessor (state machine, buffers, emits typed events)
    → Textual App (renders events to widgets)
```

### Key Principle: Typed Events, Not Strings

The UI never parses raw text. StreamProcessor emits typed events like `TextDelta`, `CodeBlockStart`, `ToolCallStart`. The UI just maps event types to widget operations.

---

## Task 1: Create Event Types

Create `src/ui/events.py` with these frozen dataclasses:

```python
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

class ToolStatus(Enum):
    PENDING = auto()           # Spinner shown
    AWAITING_APPROVAL = auto() # Needs user confirmation
    APPROVED = auto()          # User approved
    REJECTED = auto()          # User rejected  
    RUNNING = auto()           # Executing
    SUCCESS = auto()           # ✓ Complete
    FAILED = auto()            # ✗ Error
    CANCELLED = auto()         # User cancelled

@dataclass(frozen=True)
class TextDelta:
    """Append text to current markdown block."""
    content: str

@dataclass(frozen=True)
class CodeBlockStart:
    """Start new code block. Language may be empty string."""
    language: str

@dataclass(frozen=True)
class CodeBlockDelta:
    """Append to current code block."""
    content: str

@dataclass(frozen=True)
class CodeBlockEnd:
    """Close current code block."""
    pass

@dataclass(frozen=True)
class ToolCallStart:
    """
    Complete, parsed tool call ready to execute.
    Only emitted when full JSON arguments are valid.
    """
    call_id: str
    name: str
    arguments: dict[str, Any]
    requires_approval: bool

@dataclass(frozen=True)
class ToolCallStatus:
    """Tool status update (pending → running → success/failed)."""
    call_id: str
    status: ToolStatus
    message: str | None = None

@dataclass(frozen=True)
class ToolCallResult:
    """Tool completed with result."""
    call_id: str
    status: ToolStatus  # SUCCESS or FAILED
    result: Any
    error: str | None = None
    duration_ms: int | None = None

@dataclass(frozen=True)
class ThinkingStart:
    """Model started extended thinking."""
    pass

@dataclass(frozen=True)
class ThinkingDelta:
    """Thinking content (for collapsible display)."""
    content: str

@dataclass(frozen=True)
class ThinkingEnd:
    """Thinking complete."""
    token_count: int | None = None

@dataclass(frozen=True)
class StreamStart:
    """New assistant response starting."""
    pass

@dataclass(frozen=True)
class StreamEnd:
    """Stream complete."""
    pass

@dataclass(frozen=True)
class ErrorEvent:
    """Error during streaming (network, rate limit, etc.)."""
    error_type: str  # "network", "rate_limit", "api_error"
    message: str
    recoverable: bool = True

# Type alias for matching
UIEvent = (
    TextDelta | CodeBlockStart | CodeBlockDelta | CodeBlockEnd |
    ToolCallStart | ToolCallStatus | ToolCallResult |
    ThinkingStart | ThinkingDelta | ThinkingEnd |
    StreamStart | StreamEnd | ErrorEvent
)
```

---

## Task 2: Create StreamProcessor

Create `src/ui/stream_processor.py` - a state machine that:

1. **Accumulates tool calls** until complete (never leaks raw JSON)
2. **Detects code fence boundaries** (``` start/end)
3. **Batches text deltas** for debouncing

### State Machine

```
States: TEXT | CODE_BLOCK | TOOL_ACCUMULATING

Transitions:
- TEXT + "```lang" → emit CodeBlockStart → CODE_BLOCK
- CODE_BLOCK + "```" → emit CodeBlockEnd → TEXT  
- TEXT + tool_call delta → TOOL_ACCUMULATING (no emit yet)
- TOOL_ACCUMULATING + valid JSON → emit ToolCallStart → TEXT
```

### Implementation Requirements

```python
class StreamProcessor:
    """
    Transforms raw LLM chunks into typed UI events.
    
    Usage:
        processor = StreamProcessor()
        async for event in processor.process(raw_stream):
            # event is a typed UIEvent
    """
    
    def __init__(self, debounce_ms: int = 50):
        self.state = StreamState.TEXT
        self.debounce_ms = debounce_ms
        
        # Buffers
        self._text_buffer = ""
        self._code_buffer = ""
        self._code_language = ""
        self._tool_calls: dict[int, ToolCallAccumulator] = {}
    
    async def process(
        self, 
        raw_stream: AsyncIterator[StreamChunk]
    ) -> AsyncIterator[UIEvent]:
        """Main processing loop."""
        ...
    
    def _accumulate_tool_call(self, delta) -> Iterator[UIEvent]:
        """
        Accumulate tool_call deltas until we have valid JSON.
        Only emit ToolCallStart when complete.
        """
        ...
    
    def _process_content(self, content: str) -> Iterator[UIEvent]:
        """
        Process text, detecting code fence transitions.
        """
        ...
```

### Code Fence Detection Logic

```python
# Pattern for opening fence: ```language or just ```
FENCE_OPEN = re.compile(r'^```(\w*)\s*$', re.MULTILINE)

# Pattern for closing fence: ``` on its own line
FENCE_CLOSE = re.compile(r'^```\s*$', re.MULTILINE)

# Edge case: fence might arrive split across chunks
# e.g., chunk1="``", chunk2="`python\n"
# Solution: buffer partial fences, only emit when confirmed
```

### Tool Call Accumulation Logic

```python
def _accumulate_tool_call(self, delta) -> Iterator[UIEvent]:
    """
    OpenAI streams tool calls as deltas:
    - delta.index: tool call index (0, 1, 2...)
    - delta.function.name: streamed incrementally
    - delta.function.arguments: streamed as partial JSON
    
    We accumulate until json.loads(arguments) succeeds.
    """
    idx = delta.index
    
    if idx not in self._tool_calls:
        self._tool_calls[idx] = ToolCallAccumulator()
    
    acc = self._tool_calls[idx]
    
    if delta.function.name:
        acc.name += delta.function.name
    if delta.function.arguments:
        acc.arguments += delta.function.arguments
    
    # Try parsing - only emit when valid
    if acc.name and acc.arguments:
        try:
            args = json.loads(acc.arguments)
            yield ToolCallStart(
                call_id=str(idx),
                name=acc.name,
                arguments=args,
                requires_approval=self._needs_approval(acc.name)
            )
            del self._tool_calls[idx]
        except json.JSONDecodeError:
            pass  # Keep accumulating
```

---

## Task 3: Create Textual Widgets

### File Structure

```
src/ui/
├── __init__.py
├── app.py              # Main CodingAgentApp
├── events.py           # UIEvent types
├── stream_processor.py # State machine
├── styles.tcss         # Textual CSS
└── widgets/
    ├── __init__.py
    ├── message.py      # MessageWidget (container for blocks)
    ├── code_block.py   # Syntax-highlighted code
    ├── tool_card.py    # Tool status with approval
    ├── thinking.py     # Collapsible thinking block
    └── status_bar.py   # Bottom status bar
```

### CodeBlock Widget

```python
# src/ui/widgets/code_block.py
from textual.widgets import Static
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.panel import Panel

class CodeBlock(Static):
    """
    Syntax-highlighted code block with live streaming updates.
    """
    
    code = reactive("")
    language = reactive("text")
    is_streaming = reactive(True)
    
    def render(self) -> Panel:
        syntax = Syntax(
            self.code,
            self.language,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        
        title = self.language
        if self.is_streaming:
            title += " ⋯"  # Indicate still streaming
        
        return Panel(
            syntax,
            title=title,
            border_style="dim" if self.is_streaming else "green",
        )
```

### ToolCard Widget

```python
# src/ui/widgets/tool_card.py
from textual.widgets import Static, Button, OptionList
from textual.reactive import reactive
from textual.containers import Horizontal
from rich.panel import Panel

class ToolCard(Static):
    """
    Tool execution card with status indicator and optional approval UI.
    
    States:
    - AWAITING_APPROVAL: Shows inline selection list
    - RUNNING: Shows spinner
    - SUCCESS: Shows ✓ with result preview
    - FAILED: Shows ✗ with error
    """
    
    status = reactive(ToolStatus.PENDING)
    result_preview = reactive("")
    error_message = reactive("")
    
    def __init__(
        self, 
        call_id: str, 
        name: str, 
        args: dict[str, Any],
        requires_approval: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.call_id = call_id
        self.name = name
        self.args = args
        self.requires_approval = requires_approval
        
        if requires_approval:
            self.status = ToolStatus.AWAITING_APPROVAL
    
    def compose(self) -> ComposeResult:
        """Compose child widgets."""
        yield Static(id="tool-header")
        yield Static(id="tool-args")
        
        if self.requires_approval:
            yield ToolApprovalOptions(id="approval-options")
        
        yield Static(id="tool-result")
    
    def render_header(self) -> str:
        """Render the tool name with status icon."""
        icons = {
            ToolStatus.PENDING: "⠋",
            ToolStatus.AWAITING_APPROVAL: "?",
            ToolStatus.APPROVED: "▶",
            ToolStatus.RUNNING: "⠙",
            ToolStatus.SUCCESS: "✓",
            ToolStatus.FAILED: "✗",
            ToolStatus.REJECTED: "⊘",
            ToolStatus.CANCELLED: "○",
        }
        colors = {
            ToolStatus.PENDING: "yellow",
            ToolStatus.AWAITING_APPROVAL: "cyan",
            ToolStatus.APPROVED: "green",
            ToolStatus.RUNNING: "yellow",
            ToolStatus.SUCCESS: "green",
            ToolStatus.FAILED: "red",
            ToolStatus.REJECTED: "dim",
            ToolStatus.CANCELLED: "dim",
        }
        
        icon = icons.get(self.status, "?")
        color = colors.get(self.status, "white")
        
        return f"[{color}]{icon}[/{color}] [bold]{self.name}[/bold]"
    
    def format_args_preview(self) -> str:
        """Format arguments as compact preview."""
        # Show key args inline: file_path="config.py"
        parts = []
        for key, value in self.args.items():
            if isinstance(value, str) and len(value) < 50:
                parts.append(f'{key}="{value}"')
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}={value}")
        return " ".join(parts[:3])  # Max 3 args


class ToolApprovalOptions(Static):
    """
    Inline approval UI matching Claude Code style:
    
    Do you want to proceed?
    > 1. Yes
      2. Yes, and don't ask again for this tool
      3. No, skip this action  
      4. Provide feedback...
    
    Esc to cancel
    """
    
    OPTIONS = [
        ("yes", "Yes, execute"),
        ("yes_all", "Yes, and don't ask again for this tool"),
        ("no", "No, skip this action"),
        ("feedback", "Provide feedback..."),
    ]
    
    selected_index = reactive(0)
    
    def on_key(self, event) -> None:
        if event.key == "up":
            self.selected_index = max(0, self.selected_index - 1)
        elif event.key == "down":
            self.selected_index = min(len(self.OPTIONS) - 1, self.selected_index + 1)
        elif event.key == "enter":
            self._handle_selection()
        elif event.key == "escape":
            self.post_message(ApprovalResponse(self.call_id, "cancelled"))
    
    def _handle_selection(self) -> None:
        action, _ = self.OPTIONS[self.selected_index]
        self.post_message(ApprovalResponse(self.call_id, action))
```

### ThinkingBlock Widget

```python
# src/ui/widgets/thinking.py
from textual.widgets import Static, Collapsible
from textual.reactive import reactive

class ThinkingBlock(Static):
    """
    Collapsible thinking/reasoning section.
    
    - Collapsed by default
    - Shows preview when collapsed
    - Click to expand/collapse
    - Displays token count when complete
    """
    
    content = reactive("")
    is_complete = reactive(False)
    token_count = reactive(0)
    expanded = reactive(False)
    
    def render(self) -> Panel:
        if self.expanded:
            body = Markdown(self.content)
        else:
            # Collapsed preview
            preview = self.content[:80].replace("\n", " ")
            if len(self.content) > 80:
                preview += "..."
            body = f"[dim]{preview}[/dim]"
        
        # Title with token count if complete
        title = "💭 Thinking"
        if self.is_complete and self.token_count:
            title += f" ({self.token_count:,} tokens)"
        if not self.expanded:
            title += " [dim](click to expand)[/dim]"
        
        return Panel(
            body,
            title=title,
            border_style="dim blue",
        )
    
    def on_click(self) -> None:
        self.expanded = not self.expanded
```

### MessageWidget (Container)

```python
# src/ui/widgets/message.py
from textual.widgets import Static, Markdown
from textual.containers import Vertical

class MessageWidget(Vertical):
    """
    Container for a single conversation message.
    
    Holds multiple blocks:
    - MarkdownBlock (text)
    - CodeBlock
    - ToolCard
    - ThinkingBlock
    
    Blocks are added dynamically as stream events arrive.
    """
    
    def __init__(self, role: str, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self._blocks: list[Static] = []
        self._current_markdown: Markdown | None = None
        self._current_code: CodeBlock | None = None
    
    def add_text(self, content: str) -> None:
        """Append text to current markdown block, or create new one."""
        if self._current_markdown is None:
            self._current_markdown = Markdown("")
            self._blocks.append(self._current_markdown)
            self.mount(self._current_markdown)
        
        # Append to existing
        current = self._current_markdown.markup or ""
        self._current_markdown.update(current + content)
    
    def start_code_block(self, language: str) -> CodeBlock:
        """Start a new code block, return for live updates."""
        self._current_markdown = None  # End text mode
        
        block = CodeBlock()
        block.language = language
        block.is_streaming = True
        
        self._blocks.append(block)
        self._current_code = block
        self.mount(block)
        
        return block
    
    def end_code_block(self) -> None:
        """Finalize current code block."""
        if self._current_code:
            self._current_code.is_streaming = False
            self._current_code = None
    
    def add_tool_card(
        self, 
        call_id: str, 
        name: str, 
        args: dict,
        requires_approval: bool
    ) -> ToolCard:
        """Add a tool card, return for status updates."""
        self._current_markdown = None
        
        card = ToolCard(
            call_id=call_id,
            name=name,
            args=args,
            requires_approval=requires_approval,
        )
        self._blocks.append(card)
        self.mount(card)
        
        return card
    
    def add_thinking_block(self) -> ThinkingBlock:
        """Add a collapsible thinking block."""
        block = ThinkingBlock()
        self._blocks.append(block)
        self.mount(block)
        return block
```

---

## Task 4: Create Main App

```python
# src/ui/app.py
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import TextArea, Static
from textual.binding import Binding

class CodingAgentApp(App):
    """
    Main TUI application for the coding agent.
    
    Layout:
    ┌─────────────────────────────────────────┐
    │  ScrollableContainer (conversation)     │
    │   ├── MessageWidget (user)              │
    │   └── MessageWidget (assistant)         │
    │        ├── Markdown                     │
    │        ├── CodeBlock                    │
    │        └── ToolCard                     │
    ├─────────────────────────────────────────┤
    │  TextArea (input, docked bottom)        │
    ├─────────────────────────────────────────┤
    │  StatusBar (model, tokens, shortcuts)   │
    └─────────────────────────────────────────┘
    """
    
    CSS_PATH = "styles.tcss"
    
    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
        Binding("ctrl+d", "quit", "Quit", show=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+l", "clear", "Clear"),
    ]
    
    def __init__(self, agent: "Agent", **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self._is_streaming = False
        self._current_message: MessageWidget | None = None
        self._tool_cards: dict[str, ToolCard] = {}
        self._thinking_block: ThinkingBlock | None = None
        self._auto_scroll = True
    
    def compose(self) -> ComposeResult:
        yield ScrollableContainer(id="conversation")
        yield TextArea(id="input", placeholder="Type a message...")
        yield StatusBar(id="status")
    
    async def on_mount(self) -> None:
        """Focus input on start."""
        self.query_one("#input").focus()
    
    async def on_text_area_submitted(self, event) -> None:
        """Handle user input submission."""
        input_widget = self.query_one("#input", TextArea)
        user_input = input_widget.text.strip()
        
        if not user_input:
            return
        
        # Clear input
        input_widget.clear()
        
        # Add user message
        conversation = self.query_one("#conversation")
        user_msg = MessageWidget(role="user")
        user_msg.add_text(user_input)
        await conversation.mount(user_msg)
        
        # Start streaming response
        await self._stream_response(user_input)
    
    async def _stream_response(self, user_input: str) -> None:
        """Stream agent response and render events."""
        self._is_streaming = True
        conversation = self.query_one("#conversation")
        
        # Create assistant message container
        self._current_message = MessageWidget(role="assistant")
        await conversation.mount(self._current_message)
        
        try:
            # Get processed event stream from agent
            event_stream = self.agent.stream_response(user_input)
            
            async for event in event_stream:
                await self._handle_event(event)
                
                # Auto-scroll if enabled
                if self._auto_scroll:
                    conversation.scroll_end()
        
        except asyncio.CancelledError:
            # User interrupted
            pass
        finally:
            self._is_streaming = False
            self._current_message = None
            self.query_one("#input").focus()
    
    async def _handle_event(self, event: UIEvent) -> None:
        """Dispatch event to appropriate handler."""
        match event:
            case TextDelta(content=text):
                self._current_message.add_text(text)
            
            case CodeBlockStart(language=lang):
                self._current_code = self._current_message.start_code_block(lang)
            
            case CodeBlockDelta(content=code):
                if self._current_code:
                    self._current_code.code += code
            
            case CodeBlockEnd():
                self._current_message.end_code_block()
                self._current_code = None
            
            case ToolCallStart(call_id=cid, name=name, arguments=args, requires_approval=req):
                card = self._current_message.add_tool_card(cid, name, args, req)
                self._tool_cards[cid] = card
                card.scroll_visible()
            
            case ToolCallStatus(call_id=cid, status=status, message=msg):
                if cid in self._tool_cards:
                    self._tool_cards[cid].status = status
                    if msg:
                        self._tool_cards[cid].result_preview = msg
            
            case ToolCallResult(call_id=cid, status=status, result=result, error=err):
                if cid in self._tool_cards:
                    card = self._tool_cards[cid]
                    card.status = status
                    if status == ToolStatus.SUCCESS:
                        card.result_preview = self._format_result(result)
                    elif err:
                        card.error_message = err
            
            case ThinkingStart():
                self._thinking_block = self._current_message.add_thinking_block()
            
            case ThinkingDelta(content=text):
                if self._thinking_block:
                    self._thinking_block.content += text
            
            case ThinkingEnd(token_count=count):
                if self._thinking_block:
                    self._thinking_block.is_complete = True
                    if count:
                        self._thinking_block.token_count = count
                    self._thinking_block = None
            
            case ErrorEvent(error_type=etype, message=msg):
                self._show_error(etype, msg)
            
            case StreamEnd():
                pass
    
    def _format_result(self, result: Any) -> str:
        """Format tool result for preview."""
        if isinstance(result, str):
            lines = result.count('\n') + 1
            if lines > 1:
                return f"({lines} lines)"
            return result[:100]
        elif isinstance(result, dict):
            return f"({len(result)} keys)"
        elif isinstance(result, list):
            return f"({len(result)} items)"
        return str(result)[:100]
    
    def _show_error(self, error_type: str, message: str) -> None:
        """Show error in status bar or inline."""
        status = self.query_one("#status", StatusBar)
        status.show_error(error_type, message)
    
    def action_interrupt(self) -> None:
        """Handle Ctrl+C - interrupt current stream."""
        if self._is_streaming:
            # Cancel the streaming task
            self._streaming_task.cancel()
    
    def on_scroll(self) -> None:
        """Detect user scrolling to disable auto-scroll."""
        conversation = self.query_one("#conversation")
        # If user scrolled up, disable auto-scroll
        if conversation.scroll_offset.y < conversation.max_scroll_y:
            self._auto_scroll = False
```

---

## Task 5: Create Styles

```css
/* src/ui/styles.tcss */

Screen {
    layout: grid;
    grid-size: 1;
    grid-rows: 1fr auto auto;
}

#conversation {
    height: 100%;
    overflow-y: auto;
    padding: 1 2;
}

#input {
    height: auto;
    max-height: 10;
    margin: 0 1;
    border: tall $accent;
}

#input:focus {
    border: tall $accent-lighten-2;
}

#status {
    height: 1;
    dock: bottom;
    background: $surface;
    color: $text-muted;
}

/* Message styling */
MessageWidget {
    margin: 1 0;
    padding: 0 1;
}

MessageWidget.user {
    border-left: thick $primary;
}

MessageWidget.assistant {
    border-left: thick $secondary;
}

/* Code blocks */
CodeBlock {
    margin: 1 0;
}

/* Tool cards */
ToolCard {
    margin: 1 0;
    padding: 1;
}

ToolCard.success {
    border: round green;
}

ToolCard.failed {
    border: round red;
}

ToolCard.pending {
    border: round yellow;
}

/* Thinking blocks */
ThinkingBlock {
    margin: 1 0;
    opacity: 0.8;
}

ThinkingBlock:hover {
    opacity: 1.0;
}

/* Approval options */
ToolApprovalOptions {
    padding: 1;
    background: $surface;
}

ToolApprovalOptions > .option {
    padding: 0 1;
}

ToolApprovalOptions > .option.selected {
    background: $accent;
    color: $text;
}
```

---

## Task 6: Integration with Agent

Update your agent to use the new UI protocol:

```python
# src/core/agent.py

from src.ui.stream_processor import StreamProcessor
from src.ui.events import UIEvent, ToolCallStart, ToolCallResult

class Agent:
    """
    Minimal changes needed:
    - Wrap LLM stream with StreamProcessor
    - Emit ToolCallResult after tool execution
    """
    
    async def stream_response(self, user_input: str) -> AsyncIterator[UIEvent]:
        """
        Main entry point for UI.
        Returns processed event stream.
        """
        # Build messages
        messages = self._build_messages(user_input)
        
        # Get raw LLM stream
        raw_stream = self.llm.stream(messages, tools=self.tools)
        
        # Process through state machine
        processor = StreamProcessor(debounce_ms=50)
        
        async for event in processor.process(raw_stream):
            yield event
            
            # Handle tool execution
            if isinstance(event, ToolCallStart):
                # Execute tool and yield result
                result_event = await self._execute_tool(event)
                yield result_event
    
    async def _execute_tool(self, tool_call: ToolCallStart) -> ToolCallResult:
        """Execute tool and return result event."""
        import time
        start = time.monotonic()
        
        try:
            result = await self.tools.execute(
                tool_call.name, 
                tool_call.arguments
            )
            duration = int((time.monotonic() - start) * 1000)
            
            return ToolCallResult(
                call_id=tool_call.call_id,
                status=ToolStatus.SUCCESS,
                result=result,
                duration_ms=duration,
            )
        except Exception as e:
            return ToolCallResult(
                call_id=tool_call.call_id,
                status=ToolStatus.FAILED,
                result=None,
                error=str(e),
            )
```

---

## Task 7: Entry Point

```python
# src/cli.py

import asyncio
from src.ui.app import CodingAgentApp
from src.core.agent import Agent

def main():
    agent = Agent()
    app = CodingAgentApp(agent=agent)
    app.run()

if __name__ == "__main__":
    main()
```

---

## Implementation Order

1. **Events** (`events.py`) - Define the contract first
2. **StreamProcessor** (`stream_processor.py`) - Core state machine
3. **Widgets** - Start with CodeBlock, then ToolCard, then MessageWidget
4. **App** (`app.py`) - Wire everything together
5. **Styles** (`styles.tcss`) - Polish the look
6. **Integration** - Update agent to use new protocol

## Testing Strategy

```python
# Test StreamProcessor in isolation
async def test_tool_call_accumulation():
    """Tool calls should not emit until JSON is complete."""
    processor = StreamProcessor()
    
    # Simulate partial tool call chunks
    chunks = [
        StreamChunk(tool_calls=[ToolCallDelta(index=0, function=Function(name="read", arguments='{"path":'))]),
        StreamChunk(tool_calls=[ToolCallDelta(index=0, function=Function(name="", arguments='"config.py"}'))]),
    ]
    
    events = []
    async for event in processor.process(async_iter(chunks)):
        events.append(event)
    
    # Should get exactly one ToolCallStart, not partial JSON
    assert len([e for e in events if isinstance(e, ToolCallStart)]) == 1
    assert events[0].arguments == {"path": "config.py"}
```

---

## Key Design Decisions Recap

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tool approval | Inline selection list | Matches Claude Code, keeps context visible |
| Thinking blocks | Collapsible, collapsed by default | Don't overwhelm user |
| Error display | Inline for tool/LLM, status bar for network | Contextual visibility |
| Debounce | 50ms text, 100ms code, immediate tool | Smooth UX |
| Auto-scroll | Disable on user scroll up | Respect user intent |
| Code fence detection | Buffer until confirmed | Prevent partial fence rendering |

---

## Dependencies

```toml
# pyproject.toml
[project]
dependencies = [
    "textual>=0.50.0",
    "rich>=13.0.0",
    "openai>=1.0.0",  # or your LLM client
]
```

---

Start with Task 1 (events.py) and work through sequentially. Each component is testable in isolation before integration.
