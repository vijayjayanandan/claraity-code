# TUI Tool Approval Widget Issue - Technical Documentation

## Goal

Build a Textual-based TUI for an AI coding agent that:
1. Streams LLM responses in real-time
2. Shows tool calls with a keyboard-navigable approval widget
3. Allows user to approve/reject risky tool calls before execution
4. Supports Ctrl+C/Escape to interrupt streams

Similar to how Claude Code CLI works.

---

## Current Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        CodingAgentApp (Textual)                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  ScrollableContainer (conversation)                        │  │
│  │    ├── MessageWidget (user message)                        │  │
│  │    └── MessageWidget (assistant message)                   │  │
│  │         ├── Text content                                   │  │
│  │         └── ToolCard (with ToolApprovalOptions widget)     │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │  ChatInput (user input)                                    │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │  StatusBar                                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Input
    │
    ▼
CodingAgentApp._stream_response()
    │
    ▼
agent.stream_response(user_input, ui_protocol)  ◄── Async Generator
    │
    ▼
Yields UIEvent objects:
  - StreamStart
  - TextDelta (streamed text)
  - ToolCallStart (requires_approval=True/False)
  - ToolCallStatus (AWAITING_APPROVAL, APPROVED, RUNNING, etc.)
  - ToolCallResult
  - StreamEnd
    │
    ▼
CodingAgentApp._process_stream() consumes events
    │
    ▼
CodingAgentApp._handle_event() renders each event
```

### Key Files

1. **`src/ui/app.py`** - Main Textual application
2. **`src/ui/widgets/tool_card.py`** - ToolCard and ToolApprovalOptions widgets
3. **`src/ui/protocol.py`** - UIProtocol for bidirectional communication
4. **`src/core/agent.py`** - CodingAgent with stream_response() method

---

## The Problem

### Symptom

When a tool requires approval:
1. The ToolCard renders correctly with `[?]` status (AWAITING_APPROVAL)
2. The ToolApprovalOptions widget is created and mounted
3. **But keyboard events (arrow keys, Enter, y/n) don't reach the widget**
4. The UI appears frozen - user cannot interact with approval options

### Root Cause Analysis

The issue is an **async coordination deadlock** between the generator and consumer.

#### The Flow That Causes the Problem

```python
# In agent.py - stream_response() is an async generator
async def stream_response(self, user_input: str, ui: UIProtocol):
    # ... LLM streaming ...

    for tool_call in tool_calls:
        # 1. Yield event to show approval widget
        yield ToolCallStart(call_id=cid, requires_approval=True)
        yield ToolCallStatus(call_id=cid, status=AWAITING_APPROVAL)

        # 2. BLOCK here waiting for user approval
        result = await ui.wait_for_approval(call_id, tool_name)  # ◄── BLOCKS

        # 3. Continue after approval
        yield ToolCallStatus(call_id=cid, status=APPROVED)
        # ... execute tool ...
```

```python
# In app.py - consumes the generator
async def _process_stream(self, user_input: str, conversation):
    event_stream = self.stream_handler(user_input, self.ui_protocol)

    async for event in event_stream:  # ◄── Waits for next yield
        await asyncio.sleep(0)  # Yield to event loop
        await self._handle_event(event, conversation)
```

#### The Deadlock

1. Generator yields `ToolCallStatus(AWAITING_APPROVAL)`
2. Consumer receives it, renders the approval widget
3. Consumer loops back to `async for event in event_stream` - **waits for next yield**
4. Generator is blocked in `await ui.wait_for_approval()` - **waits for user input**
5. **Both are waiting** - but keyboard events need to be processed!

#### Why Keyboard Events Don't Work

The asyncio event loop IS running during the `await`, so in theory Textual should process key events. However:

1. The approval widget may not be fully mounted/focused when `wait_for_approval()` starts
2. There's a race condition between widget mounting and the blocking await
3. Textual's event processing may need explicit yield points at specific times

### What We Tried

1. **Added `await asyncio.sleep(0)` in `_process_stream()`** - Yields to event loop every iteration
2. **Added `await asyncio.sleep(0)` after mounting approval widgets** - Extra yield for focus
3. **Fixed widget lifecycle** - Use `requires_approval` in `compose()`, defer status to `on_mount()`
4. **Multiple focus attempts in ToolApprovalOptions** - `call_after_refresh`, timers at 0.1s, 0.3s

None of these fully solved the issue.

---

## Code Snippets

### UIProtocol.wait_for_approval() - src/ui/protocol.py

```python
async def wait_for_approval(
    self,
    call_id: str,
    tool_name: str,
    timeout: float | None = None
) -> ApprovalResult:
    """Wait for user to approve/reject a tool call."""
    # Check auto-approve first
    if tool_name in self._auto_approve:
        return ApprovalResult(call_id=call_id, approved=True)

    # Create future for this specific call
    future: asyncio.Future[ApprovalResult] = asyncio.Future()
    self._pending_approvals[call_id] = PendingApproval(future=future, tool_name=tool_name)

    try:
        if timeout:
            return await asyncio.wait_for(future, timeout)
        else:
            return await future  # ◄── Blocks until future is resolved
    finally:
        self._pending_approvals.pop(call_id, None)
```

### ToolApprovalOptions widget - src/ui/widgets/tool_card.py

```python
class ToolApprovalOptions(Static, can_focus=True):
    """Inline approval UI with keyboard navigation."""

    BINDINGS = [
        Binding("up", "move_up", priority=True),
        Binding("down", "move_down", priority=True),
        Binding("enter", "select", priority=True),
        Binding("y", "quick_yes", priority=True),
        Binding("n", "quick_no", priority=True),
        # ... more bindings
    ]

    def on_mount(self) -> None:
        """Focus on mount to capture key events."""
        self.call_after_refresh(self._ensure_focus)
        self.set_timer(0.1, self._ensure_focus)
        self.set_timer(0.3, self._ensure_focus)

    def _ensure_focus(self) -> None:
        if not self.has_focus:
            self.focus()
            self.scroll_visible()

    def _submit_selection(self) -> None:
        """Submit the current selection."""
        action, _ = self.OPTIONS[self.selected_index]
        self.post_message(ApprovalResponseMessage(self.call_id, action))
```

### How approval response flows back

```python
# In app.py
def on_approval_response_message(self, message: ApprovalResponseMessage) -> None:
    """Handle approval response from ToolApprovalOptions."""
    approved = message.action in ("yes", "yes_all")

    # This resolves the Future that wait_for_approval() is awaiting
    self.ui_protocol.submit_action(ApprovalResult(
        call_id=message.call_id,
        approved=approved,
    ))
```

```python
# In protocol.py
def submit_action(self, action: UserAction) -> None:
    """Submit a user action (non-blocking)."""
    if isinstance(action, ApprovalResult):
        pending = self._pending_approvals.get(action.call_id)
        if pending and not pending.future.done():
            pending.future.set_result(action)  # ◄── Resolves the future
```

---

## Constraints

1. **Must use Textual framework** - Already heavily invested in Textual-based TUI
2. **Must support streaming** - LLM output should stream in real-time
3. **Must support approval widgets** - User should be able to approve/reject tool calls
4. **Windows compatibility** - Primary development platform is Windows
5. **asyncio-based** - Agent uses asyncio for async operations

---

## Potential Solutions to Explore

### Option 1: Separate Tool Execution from Streaming

Don't block inside the generator. Instead:
1. Generator yields tool calls but doesn't wait for approval
2. After stream ends, process tool calls separately
3. For each tool: show approval → wait → execute
4. Call LLM again with results

```python
async def stream_response(...):
    # Phase 1: Stream LLM response, collect tool calls
    tool_calls = []
    async for chunk in llm_stream:
        yield TextDelta(chunk.content)
        if chunk.tool_calls:
            tool_calls.extend(chunk.tool_calls)

    # Phase 2: Process tool calls (after streaming is done)
    for tc in tool_calls:
        yield ToolCallStart(tc)
        # Don't block here - let consumer handle approval
```

Then in consumer:
```python
async for event in event_stream:
    if isinstance(event, ToolCallStart) and event.requires_approval:
        # Wait for approval HERE, not in generator
        result = await ui.wait_for_approval(event.call_id)
        # Signal back to agent somehow...
```

### Option 2: Use Textual Workers

Textual has a worker pattern for background tasks:
```python
@work(exclusive=True)
async def process_tool_call(self, tool_call):
    # This runs in background, UI stays responsive
    result = await self.wait_for_approval()
    await self.execute_tool()
```

### Option 3: Event-Driven Architecture

Instead of blocking on approval:
1. Generator yields events and continues (doesn't block)
2. UI shows approval widget
3. When user approves, UI posts message
4. Agent receives message via queue/callback
5. Agent continues execution

### Option 4: Use asyncio.Event or asyncio.Queue

Instead of Future, use an Event that the UI sets:
```python
approval_event = asyncio.Event()
# ... show widget ...
await approval_event.wait()  # Non-blocking wait?
```

---

## Questions for Consultation

1. What is the standard pattern for handling user approval in async TUI applications?
2. How do other TUI tools (like Claude Code) handle blocking for user input mid-stream?
3. Is there a way to make Textual's key handling work while an async generator is blocked?
4. Should we restructure to avoid blocking inside the generator entirely?
5. Is there a Textual-specific pattern (workers, screens, etc.) for this use case?

---

## Environment

- Python 3.11+
- Textual framework (latest)
- Windows 11 (primary), also needs to work on Linux/Mac
- asyncio with WindowsProactorEventLoopPolicy on Windows

---

## Files to Share

If needed, the key files are:
- `src/ui/app.py` (~700 lines)
- `src/ui/widgets/tool_card.py` (~550 lines)
- `src/ui/protocol.py` (~240 lines)
- `src/core/agent.py` (stream_response method, ~200 lines)
