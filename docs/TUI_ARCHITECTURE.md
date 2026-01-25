# TUI IMPLEMENTATION - COMPREHENSIVE RESEARCH & DOCUMENTATION

## Executive Summary

The AI Coding Agent's TUI is built with **Textual framework** (async-native TUI library) and features real-time LLM response streaming with inline tool approval UI. The implementation uses a sophisticated event-driven architecture with careful async/await coordination to prevent the deadlock issues that plagued earlier iterations.

**Key Achievement:** Streaming and approval widgets can now operate simultaneously without blocking the Textual message loop, enabling responsive UX even during heavy LLM processing.

---

## 1. ARCHITECTURE OVERVIEW

### 1.1 Layered Architecture Diagram

```
+-------------------------------------------------------------+
|                      CodingAgentApp                         |
|                   (Textual Application)                     |
|  - Manages widget hierarchy and layout                      |
|  - Handles Textual message dispatch                         |
|  - Coordinates streaming via Worker threads                 |
|  - Manages approval flow via UIProtocol                     |
+---------------------------+---------------------------------+
                            |
                 +----------+----------+
                 |                     |
       +---------v--------+  +---------v---------+
       |  Chat Widgets    |  |  UIProtocol       |
       +------------------+  +-------------------+
       | - MessageWidget  |  | - Approval Queue  |
       | - CodeBlock      |  | - Auto-approve    |
       | - ToolCard       |  | - Interrupt       |
       | - ThinkingBlock  |  | - Tool futures    |
       | - StatusBar      |  +-------------------+
       +------------------+
                 |
                 | Events
                 |
       +---------v-----------------------------------------+
       |      StreamProcessor (State Machine)              |
       |  - Code fence detection (```...```)               |
       |  - Tool call accumulation (JSON validation)       |
       |  - Thinking block markers                         |
       |  - Debounce + coalesce text deltas                |
       +-------------------------+-------------------------+
                                 | Raw chunks
                                 |
       +-------------------------v-------------------------+
       |  Agent / LLM Stream                               |
       |  - OpenAI API format                              |
       |  - Tool calls (partial JSON)                      |
       |  - Content chunks                                 |
       +---------------------------------------------------+
```

### 1.2 Core Responsibility Map

| Component | Responsibility | Key Files |
|-----------|---|---|
| **CodingAgentApp** | Main app orchestration, widget composition, streaming lifecycle | `src/ui/app.py` |
| **MessageWidget** | Container for conversation blocks (text, code, tools, thinking) | `src/ui/widgets/message.py` |
| **CodeBlock** | Syntax-highlighted code with streaming indicator | `src/ui/widgets/code_block.py` |
| **ToolCard** | Tool execution status with inline approval options | `src/ui/widgets/tool_card.py` |
| **ToolApprovalOptions** | Claude Code-style approval UI with 3 options | `src/ui/widgets/tool_card.py` |
| **ThinkingBlock** | Collapsible thinking/reasoning display | `src/ui/widgets/thinking.py` |
| **StatusBar** | Model name, elapsed time, token count, errors | `src/ui/widgets/status_bar.py` |
| **UIProtocol** | Bidirectional coordination (approvals, interrupts, auto-approve) | `src/ui/protocol.py` |
| **UIEvents** | Typed event contract between stream and UI | `src/ui/events.py` |
| **StreamProcessor** | State machine: raw chunks -> typed UIEvents | `src/ui/stream_processor.py` |
| **AgentStreamAdapter** | Bridges existing CodingAgent to TUI | `src/ui/agent_adapter.py` |

---

## 2. STREAMING IMPLEMENTATION DEEP DIVE

### 2.1 Two Streaming Modes

The app supports two modes selectable at runtime:

#### Mode 1: Segmented Streaming (Default)
- **When to use:** Production, user-facing (better UX)
- **How it works:**
  1. Text accumulates in `_segment_chunks[]` buffer
  2. NO UI updates until a **boundary** occurs:
     - Tool card
     - Code block
     - Thinking block
     - Stream end
  3. At boundary: all accumulated text rendered as Markdown (one parse)
  4. Gives stable, readable chunks instead of flickering

```python
# TextDelta events just accumulate
case TextDelta(content=text):
    self._segment_chunks.append(text)
    self._segment_chars += len(text)

# At boundary: flush and render
def _flush_segment(self) -> None:
    text = "".join(self._segment_chunks)
    self._current_message.add_text(text)  # One Markdown parse
    self._segment_chunks.clear()
```

**Pros:** Fast Markdown parsing (O(1) per response), stable UX
**Cons:** Slight latency before first visible output

#### Mode 2: Full Streaming (Debug)
- **When to use:** Development, testing, debugging
- **How it works:**
  1. Text accumulates in `_delta_buffer[]` (up to 512 chars or 50ms)
  2. Flushed incrementally via `append_streaming_text()`
  3. Uses Rich `Text` object (O(1) amortized append)
  4. Converted to Markdown at stream end (finalize_streaming_text)

```python
if self._buffer_len() >= self._flush_chars_threshold:
    await self._flush_deltas()  # Append to Static widget
else:
    self._schedule_flush()      # Timer-based flush
```

**Pros:** Live feedback on every chunk, real-time feel
**Cons:** Multiple Markdown parses = slower for long responses

### 2.2 Event Flow from Agent to Screen

```
+-------------------------------------------------------------+
| 1. User Input                                               |
| Text input submitted -> InputSubmittedMessage posted        |
+---------------------------+---------------------------------+
                            |
+---------------------------v---------------------------------+
| 2. Message Handler (on_input_submitted_message)             |
| - Add user message to conversation                          |
| - Start streaming in Worker (run_worker, exclusive=True)    |
| - Return immediately (don't await!) -> Textual keeps running|
+---------------------------+---------------------------------+
                            |
+---------------------------v---------------------------------+
| 3. Worker (Background) -> _stream_response()                |
| - Disable input widget                                      |
| - Update status bar to streaming                            |
| - Call _process_stream(user_input, ui_protocol)             |
| - Yield control every event (await asyncio.sleep(0))        |
+---------------------------+---------------------------------+
                            |
+---------------------------v---------------------------------+
| 4. Process Stream -> _process_stream()                      |
| - Call stream_handler(user_input, ui_protocol)              |
| - Iterate through UIEvent stream                            |
| - Dispatch each event to _handle_event()                    |
| - Check interrupt flag before processing each event         |
+---------------------------+---------------------------------+
                            |
+---------------------------v---------------------------------+
| 5. Handle Events (match statement)                          |
|                                                             |
| StreamStart -> Create MessageWidget, reset buffers          |
| TextDelta -> Accumulate in segment/delta buffer             |
| CodeBlockStart -> Flush segment, create CodeBlock           |
| CodeBlockDelta -> Append to current code                    |
| CodeBlockEnd -> Finalize code block                         |
| ToolCallStart -> Flush segment, add ToolCard+Approval       |
| ToolCallStatus -> Update card status                        |
| ToolCallResult -> Set result/error, display duration        |
| ThinkingStart -> Flush segment, create ThinkingBlock        |
| ThinkingDelta -> Append to thinking                         |
| ThinkingEnd -> Finalize thinking with token count           |
| ErrorEvent -> Show error in status bar, optionally retry    |
| StreamEnd -> Flush remaining, finalize message, refocus     |
+---------------------------+---------------------------------+
                            |
+---------------------------v---------------------------------+
| 6. Widget Rendering                                         |
| - MessageWidget mounts blocks incrementally                 |
| - Markdown renders formatted text                           |
| - CodeBlock renders syntax-highlighted code                 |
| - ToolCard shows compact tool status                        |
| - ToolApprovalOptions shows approval UI (mounted on_mount)  |
| - Auto-scroll to keep new content visible                   |
+-------------------------------------------------------------+
```

### 2.3 Approval Flow (UIProtocol)

```
+--------------------------------------------------+
| StreamProcessor detects tool call with JSON args |
| Emits ToolCallStart(call_id, name, args, req...) |
+-----------------------+--------------------------+
                        |
+-----------------------v--------------------------+
| App._handle_event(ToolCallStart)                 |
| - Create ToolCard(call_id, ...)                  |
| - Add to conversation                            |
| - Track in _pending_approval_ids                 |
+-----------------------+--------------------------+
                        |
+-----------------------v--------------------------+
| ToolCard.on_mount()                              |
| - If requires_approval: set status = AWAITING   |
| - Explicitly mount ToolApprovalOptions widget    |
| - Give approval widget focus                     |
+-----------------------+--------------------------+
                        |
                        | User presses key (e.g., "1" for Yes)
                        |
+-----------------------v--------------------------+
| ToolApprovalOptions.on_key() or action_select()  |
| - Post ApprovalResponseMessage                   |
+-----------------------+--------------------------+
                        |
+-----------------------v--------------------------+
| App.on_approval_response_message()               |
| - Submit ApprovalResult to ui_protocol           |
| - Update tool card status (APPROVED/REJECTED)    |
| - Clear from _pending_approval_ids               |
+-----------------------+--------------------------+
                        |
+-----------------------v--------------------------+
| Agent awaits ui.wait_for_approval(call_id, tool) |
| - Future in _pending_approvals[call_id] resolves |
| - Agent gets ApprovalResult(approved=True/False) |
| - Proceeds to execute tool or skip               |
+--------------------------------------------------+
```

---

## 3. WIDGET INVENTORY

### 3.1 MessageWidget (Container)

**Location:** `src/ui/widgets/message.py`

**Purpose:** Holds multiple content blocks for a single message

**Key Methods:**
- `add_text(content)` - Add markdown text (renders immediately via Markdown widget)
- `start_streaming_text() / append_streaming_text(content) / finalize_streaming_text()` - Live text rendering using Rich Text (O(1) append)
- `start_code_block(lang) / append_code(content) / end_code_block()` - Code streaming
- `add_tool_card(call_id, tool_name, args, requires_approval)` - Mount ToolCard
- `start_thinking() / append_thinking(content) / end_thinking(token_count)` - Thinking blocks
- `finalize()` - Finalize all blocks (convert streaming text to Markdown)

**State Tracking:**
```python
self._current_markdown: Markdown | None          # Current text block
self._current_code: CodeBlock | None             # Current code block
self._current_thinking: ThinkingBlock | None     # Current thinking
self._tool_cards: dict[str, ToolCard]            # All tool cards by ID
self._blocks: list[Static]                       # All blocks in order
self._streaming_widget: Static | None            # Temporary streaming preview
self._streaming_text: Text | None                # Rich Text for O(1) appends
```

**Three Roles:**
1. **UserMessage** - Role="user", border-left color primary
2. **AssistantMessage** - Role="assistant", border-left color secondary
3. **SystemMessage** - Role="system", border-left color warning, opacity 0.8

---

### 3.2 CodeBlock (Syntax-Highlighted Code)

**Location:** `src/ui/widgets/code_block.py`

**Purpose:** Display code with syntax highlighting and streaming indicator

**Key Attributes:**
- `code` (reactive) - Accumulated code content
- `language` (reactive) - Language for syntax highlighting
- `is_streaming` (reactive) - True during streaming, False when complete

**Rendering:**
- **Empty/Streaming:** Placeholder `"..."` in dim italic
- **With Content:** Rich `Syntax` widget with monokai theme, line numbers, word wrap
- **Border:** Yellow while streaming, green when complete
- **Title:** Language name + `[dim]...[/dim]` indicator while streaming

**Methods:**
- `append(content)` - Add code incrementally
- `finalize()` - Mark complete, change border to green
- `line_count` property - Count lines in code

---

### 3.3 ToolCard (Tool Execution Status)

**Location:** `src/ui/widgets/tool_card.py`

**Purpose:** Display tool call status, arguments, results, and approval UI

**Compact Format:**
```
[+] read_file(example.py)  mode="text"
    (5 lines) [42ms]
```

**Status Icons (Text, Windows-safe):**
```python
STATUS_CONFIG = {
    PENDING:           ("o", "yellow"),
    AWAITING_APPROVAL: ("?", "cyan"),
    APPROVED:          (">", "blue"),
    REJECTED:          ("x", "dim"),
    RUNNING:           ("*", "yellow"),
    SUCCESS:           ("+", "green"),
    FAILED:            ("!", "red"),
    CANCELLED:         ("-", "dim"),
}
```

**Key Methods:**
- `set_result(result, duration_ms)` - Set success status
- `set_error(error)` - Set failed status
- `approve() / reject() / start_running() / cancel()` - Programmatic status changes

**Approval Widget:**
- **Mounted on demand** in `on_mount()` (not in `compose()` - Static doesn't render children reliably)
- **Three options:**
  1. "Yes" (approve once)
  2. "Yes, allow all {tool}" (auto-approve for session)
  3. "[Type feedback]" (provide guidance)
- **Key handling:** Shortcut keys (1, 2, y) disabled in feedback mode to allow typing

---

### 3.4 ToolApprovalOptions (Approval UI)

**Location:** `src/ui/widgets/tool_card.py` (nested class)

**Purpose:** Inline approval interface matching Claude Code's style

**State:**
- `selected_index` (reactive) - 0, 1, or 2 (feedback mode)
- `feedback_text` (reactive) - User's typed guidance

**Rendering:**
```
Do you want to allow this action?
  1. Yes
  2. Yes, allow all read_file during this session
> 3. [feedback text or placeholder]

Esc to cancel
```

**Key Bindings (Priority-ordered):**
1. Up/K/Down/J - Navigate options
2. Enter - Confirm selection
3. Escape - Cancel/reject
4. 1/2/Y - Quick approve (only when NOT in feedback mode)
5. Backspace - Delete char in feedback
6. Any printable - Type in feedback (selects option 3)

**Critical Design Decision:**
- On `on_mount()`, explicitly call `self.mount(approval_widget)` instead of yielding from `compose()`
- Reason: Static widgets don't reliably render children from compose()
- Result: Approval UI is now guaranteed to be visible and keyboard-accessible

---

### 3.5 ThinkingBlock (Collapsible Reasoning)

**Location:** `src/ui/widgets/thinking.py`

**Purpose:** Display model's internal reasoning (Claude's extended thinking)

**State:**
- `content` (reactive) - Thinking text
- `is_complete` (reactive) - True when finished
- `token_count` (reactive) - Tokens used (shown when complete)
- `expanded` (reactive) - Collapsed (preview) or expanded (full)

**Rendering:**
- **Collapsed:** First 100 chars with `"..."` suffix, dim italic
- **Expanded:** Full content as Markdown, can click/toggle
- **Title:**
  - `"Thinking..."` while streaming
  - `"Thinking (150 tokens)"` when complete
  - Click hint: `[dim]click to expand/collapse[/dim]`
- **Border:** Blue when complete, cyan while streaming

**Methods:**
- `append(content)` - Add text incrementally
- `finalize(token_count)` - Mark complete, record token count
- `expand() / collapse() / toggle()` - Control visibility
- `on_click()` - Toggle on user click
- `word_count` property - Approximate word count

---

### 3.6 StatusBar (Bottom Status)

**Location:** `src/ui/widgets/status_bar.py`

**Purpose:** Show model, elapsed time, token count, errors, keyboard shortcuts

**Left Section (Model + Streaming):**
```
[claude-3-opus] | Processing 25s
```

**Center Section (Error with Countdown):**
```
[!] Rate limited (60s countdown)
```

**Right Section (Keyboard Hints):**
```
Esc/Ctrl+C stop | Ctrl+D quit
```

**Reactive State:**
- `model_name` - Name of LLM
- `is_streaming` - Streaming status
- `elapsed_seconds` - Elapsed time (1s granularity)
- `token_count` - Tokens generated
- `error_message` - Error text (if any)
- `countdown` - Countdown seconds (for rate limits)
- `spinner_frame` - Animation frame

**Spinner:**
- Frames: `|`, `/`, `-`, `\` (ASCII-safe for Windows)
- Updates every 100ms, shows "cyan" color

**Methods:**
- `set_streaming(is_streaming)` - Start/stop timers
- `update_tokens(count)` - Set token count
- `show_error(message, countdown)` - Show error with optional countdown
- `clear_error()` - Hide error

**Timers:**
- Elapsed: 1s update interval
- Spinner: 100ms animation
- Countdown: 1s decrement (for rate limits)

---

## 4. EVENT SYSTEM

### 4.1 Event Types (Typed Union)

**Location:** `src/ui/events.py`

All events are frozen dataclasses (immutable).

#### Stream Lifecycle
```python
@dataclass(frozen=True)
class StreamStart:
    """New assistant response starting"""
    pass

@dataclass(frozen=True)
class StreamEnd:
    """Stream complete (normal termination)"""
    total_tokens: int | None = None
    duration_ms: int | None = None
```

#### Text Content
```python
@dataclass(frozen=True)
class TextDelta:
    """Incremental text (debounced, not per-token)"""
    content: str
```

#### Code Blocks
```python
@dataclass(frozen=True)
class CodeBlockStart:
    """Start new syntax-highlighted code"""
    language: str  # e.g., "python", "bash"

@dataclass(frozen=True)
class CodeBlockDelta:
    """Incremental code content"""
    content: str

@dataclass(frozen=True)
class CodeBlockEnd:
    """Code block complete"""
    pass
```

#### Tool Calls
```python
@dataclass(frozen=True)
class ToolCallStart:
    """Complete, parsed tool call ready for execution"""
    call_id: str
    name: str  # e.g., "read_file"
    arguments: dict[str, Any]  # Fully parsed JSON
    requires_approval: bool

@dataclass(frozen=True)
class ToolCallStatus:
    """Tool execution status update"""
    call_id: str
    status: ToolStatus  # PENDING, AWAITING_APPROVAL, APPROVED, etc.
    message: str | None = None  # e.g., "Reading file..."

@dataclass(frozen=True)
class ToolCallResult:
    """Tool execution completed"""
    call_id: str
    status: ToolStatus  # SUCCESS or FAILED
    result: Any = None
    error: str | None = None
    duration_ms: int | None = None
```

#### Thinking
```python
@dataclass(frozen=True)
class ThinkingStart:
    """Model started extended thinking"""
    pass

@dataclass(frozen=True)
class ThinkingDelta:
    """Incremental thinking content"""
    content: str

@dataclass(frozen=True)
class ThinkingEnd:
    """Thinking phase complete"""
    token_count: int | None = None
```

#### Errors
```python
@dataclass(frozen=True)
class ErrorEvent:
    """Error during streaming"""
    error_type: str  # "rate_limit", "network", "api_error", "auth", "invalid_request"
    message: str
    recoverable: bool = True
    retry_after: int | None = None  # Seconds (for rate limits)
```

#### ToolStatus Enum
```python
class ToolStatus(Enum):
    PENDING = auto()
    AWAITING_APPROVAL = auto()
    APPROVED = auto()
    REJECTED = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    CANCELLED = auto()
```

---

### 4.2 UIProtocol (Bidirectional Communication)

**Location:** `src/ui/protocol.py`

#### User Actions (UI -> Agent)
```python
@dataclass(frozen=True)
class ApprovalResult:
    call_id: str
    approved: bool
    auto_approve_future: bool = False  # "Don't ask again for this tool"
    feedback: str | None = None  # Modified instructions

@dataclass(frozen=True)
class InterruptSignal:
    """User interrupted (Ctrl+C)"""
    pass

@dataclass(frozen=True)
class RetrySignal:
    """User requested retry"""
    pass
```

#### UIProtocol Class
```python
class UIProtocol:
    # Agent-side methods
    async def wait_for_approval(call_id, tool_name, timeout=None) -> ApprovalResult
    def check_interrupted() -> bool
    async def wait_for_interrupt() -> None
    def get_action_queue() -> asyncio.Queue[UserAction]

    # UI-side methods
    def submit_action(action: UserAction) -> None
    def reset() -> None  # Clear state for new turn
    def clear_auto_approve() -> None
    def is_auto_approved(tool_name) -> bool
    def add_auto_approve(tool_name) -> None
    def remove_auto_approve(tool_name) -> None
```

**Design Principles:**
- Agent doesn't know about Textual internals
- UI doesn't touch Agent's private state
- All coordination via async queues (testable, decoupled)
- Auto-approve rules persist within session (not cleared on reset)

---

### 4.3 Textual Messages (Widget <-> App)

**Location:** `src/ui/messages.py`

```python
class ApprovalResponseMessage(Message):
    """User responded to tool approval"""
    call_id: str
    action: str  # "yes", "yes_all", "no"
    feedback: str | None = None

class StreamInterruptMessage(Message):
    """User requested stream interrupt"""
    pass

class RetryRequestMessage(Message):
    """User requested retry"""
    pass

class ScrollStateChangedMessage(Message):
    """Scroll position changed"""
    at_bottom: bool

class InputSubmittedMessage(Message):
    """User submitted input"""
    content: str
```

---

## 5. STREAMING STATE MACHINE (StreamProcessor)

### 5.1 State Transitions

**Location:** `src/ui/stream_processor.py`

```
      StreamStart
         |
         v
    +---------+
    |  IDLE   | (emit StreamStart, transition to TEXT)
    +----+----+
         |
         v
    +-------------------------------------+
    |           TEXT STATE                |
    | Buffer text until boundary          |
    | Check for transitions:              |
    |  - ```language -> CODE_BLOCK        |
    |  - <thinking> -> THINKING           |
    |  - TextDelta emit (debounced)       |
    +--+------------------------------+---+
       |                              |
       | (code fence found)           | (thinking found)
       |                              |
       v                              v
    +--------------+              +--------------+
    | CODE_BLOCK   |              |  THINKING    |
    | Buffer code  |              | Buffer text  |
    | Check for    |              | Emit         |
    | ``` close    |              | ThinkingDelta|
    +------+-------+              +------+-------+
           |                             |
    (``` found / EOS)         (</thinking> found / EOS)
           |                             |
           v                             v
        TEXT <----------------------> TEXT
        (back)                       (back)
           |                            |
           v                            v
         StreamEnd (emit)         StreamEnd (emit)
```

### 5.2 Content Buffering Strategy

**Text (in TEXT state):**
1. Accumulate chunks in `_text_buffer`
2. Emit TextDelta when:
   - Buffer ends with `\n` (natural break)
   - Buffer ends with `.`, `!`, `?`, `:` + space (sentence boundary)
   - Max latency exceeded (150ms, prevent UI starvation)
   - Buffer > 500 chars (prevent memory issues)

**Code (in CODE_BLOCK state):**
1. Accumulate in `_code_buffer`
2. Emit CodeBlockDelta for safe content (except potential fence markers)
3. Keep 1-3 backticks at end of buffer (might be start of closing fence)
4. On fence close, emit remaining code + CodeBlockEnd

**Edge Cases Handled:**
```python
# Fence split across chunks
if safe_to_emit.endswith('\n`'):           # \n` -> wait
    safe_to_emit = safe_to_emit[:-2]
elif safe_to_emit.endswith('\n``'):        # \n`` -> wait
    safe_to_emit = safe_to_emit[:-3]
elif safe_to_emit.endswith('\n```'):       # \n``` -> wait (might close)
    return  # Don't emit, might be fence
elif safe_to_emit.endswith('`'):           # Single ` -> wait
    safe_to_emit = safe_to_emit[:-1]
elif safe_to_emit.endswith('``'):          # Double `` -> wait
    safe_to_emit = safe_to_emit[:-2]
```

### 5.3 Tool Call Accumulation

**Problem Solved:** Prevent raw JSON from leaking to UI

**Strategy:**
```python
class ToolCallAccumulator:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""

    def is_complete(self) -> bool:
        # Only complete when:
        # 1. name is non-empty
        # 2. arguments is non-empty
        # 3. arguments is valid JSON
        ...

# Accumulate incrementally from stream
for tc_delta in chunk.choices[0].delta.tool_calls:
    acc = _tool_calls[tc_delta.index]
    acc.name += tc_delta.function.name  # Partial name
    acc.arguments += tc_delta.function.arguments  # Partial JSON

    if acc.is_complete():
        # Only now, emit ToolCallStart with parsed args
        yield ToolCallStart(..., arguments=json.loads(acc.arguments))
```

---

## 6. IDENTIFIED ISSUES & TECHNICAL DEBT

### P0 - CRITICAL (Production Breaking)

#### Issue 6.0: add_text() Does Not Await mount()

**Status:** RED - ROOT CAUSE OF TEXT NOT APPEARING
**Location:** `src/ui/widgets/message.py`, `add_text()` method
**Description:**
The `add_text()` method is synchronous but calls `mount()` which is async:

```python
def add_text(self, content: str) -> None:  # NOT async!
    if self._current_markdown is None:
        self._current_markdown = Markdown("")
        self._blocks.append(self._current_markdown)
        self.mount(self._current_markdown)  # NOT awaited!

    self._markdown_text += content
    self._current_markdown.update(self._markdown_text)  # Widget not in DOM yet!
```

**Impact:** Widget is queued for mounting but `update()` is called before it's in the DOM. Text never appears.

**Fix Required:**
```python
async def add_text(self, content: str) -> None:  # Make async
    if self._current_markdown is None:
        self._current_markdown = Markdown("")
        self._blocks.append(self._current_markdown)
        await self.mount(self._current_markdown)  # AWAIT the mount

    self._markdown_text += content
    self._current_markdown.update(self._markdown_text)
```

**Callers to Update:**
- `app.py`: `_flush_segment()` must await `add_text()`
- `app.py`: Error/interrupt handlers must await `add_text()`

---

#### Issue 6.1: No Other Critical Async/Await Bugs Currently

**Status:** Green (after fixing 6.0)
**Analysis:** The worker pattern introduced in latest iteration successfully solved the deadlock issue from earlier attempts. Every place that might block Textual is now properly offloaded.

**Validation:**
- `on_input_submitted_message()` uses `run_worker()` - doesn't await
- `_stream_response()` yields control with `await asyncio.sleep(0)` every event
- Approval widget can receive focus while streaming (tested via demo mode)
- Ctrl+C/Escape work during streaming (interrupts worker + cancels task)

---

### P1 - HIGH (Should fix before production)

#### Issue 6.2: Missing Error Recovery for Incomplete Tool Calls

**Severity:** HIGH
**Location:** `src/ui/stream_processor.py`, `_flush_all()`
**Description:**
If stream ends while tool call is incomplete (partial JSON), error event is emitted but not propagated to UI error handler:

```python
# In _flush_all()
for idx, acc in self._tool_calls.items():
    yield ErrorEvent(
        error_type="incomplete_tool_call",
        message=f"Tool call '{acc.name}' incomplete",
        recoverable=False,
    )
```

The UI handler (`_handle_error`) doesn't have a case for `"incomplete_tool_call"` and just shows a generic error with no retry option. Should add specific handling:

```python
# Suggested fix in app._handle_error()
elif error_type == "incomplete_tool_call":
    # Show error, don't retry (API bug)
    status_bar.show_error(f"Tool call parsing failed: {message}")
    # Add to message for visibility
    if self._current_message:
        self._current_message.add_text(f"\n\n[!] {message}")
```

**Recommendation:** Add case for incomplete tool calls in error handler

---

#### Issue 6.3: Race Condition in Auto-Scroll During Flush

**Severity:** HIGH
**Location:** `src/ui/app.py`, `_flush_segment()` and `_flush_deltas()`
**Description:**
Current code checks `is_vertical_scroll_end` BEFORE appending content:

```python
was_at_bottom = (
    self._conversation.is_vertical_scroll_end
    if self._conversation else True
)
# ... append content (moves bottom) ...
if was_at_bottom:
    self._conversation.scroll_end(animate=False)
```

This works BUT is fragile if parent layout changes during the append. More robust pattern:

```python
# Use Textual's scroll_visible() instead
content_widget.scroll_visible(animate=False)
```

**Recommendation:** Test with large messages (100+ KB). If scrolling jumps, switch to `scroll_visible()` approach.

---

#### Issue 6.4: StatusBar Timers Not Always Cleaned Up

**Severity:** HIGH
**Location:** `src/ui/widgets/status_bar.py`
**Description:**
If app is interrupted during streaming, timers may continue running:

```python
def on_unmount(self) -> None:
    """Clean up timers"""
    self._stop_elapsed_timer()
    self._stop_countdown()
    self._stop_spinner_timer()
```

This assumes `on_unmount()` is called. If app crashes or exits via Ctrl+C without proper cleanup, timers persist in Textual's background.

**Recommendation:** Add try/finally in all timer methods:

```python
def _start_elapsed_timer(self) -> None:
    if self._elapsed_timer:
        self._elapsed_timer.stop()
    try:
        self._elapsed_timer = self.set_interval(1.0, self._update_elapsed)
    except Exception as e:
        self.log.error(f"Failed to start elapsed timer: {e}")
```

---

#### Issue 6.5: ToolApprovalOptions Keyboard Focus Not Guaranteed

**Severity:** HIGH
**Location:** `src/ui/widgets/tool_card.py`, `ToolApprovalOptions.on_mount()`
**Description:**
Focus is set with:

```python
def on_mount(self) -> None:
    self.call_after_refresh(self._ensure_focus)
    self.set_timer(0.1, self._ensure_focus)
```

This uses both `call_after_refresh()` AND a timer, which is redundant and may cause race conditions. The `set_timer()` will fire even if the first focus succeeded, potentially refocusing the widget unnecessarily.

**Recommendation:** Use call_after_refresh only:

```python
def on_mount(self) -> None:
    self.call_after_refresh(self._ensure_focus)
    # Remove: self.set_timer(0.1, self._ensure_focus)
```

---

#### Issue 6.6: Large Message Performance Degradation

**Severity:** HIGH
**Location:** `src/ui/widgets/message.py`, streaming text mode
**Description:**
Segmented streaming mode is fast (one Markdown parse), but for very large responses (100KB+), the Markdown widget can become slow to render.

Rich Markdown rendering is O(n) with content size. For responses like:
- 500+ lines of code (inline markdown comment display)
- 1000+ lines of thinking text
- Multiple large code blocks

Markdown rendering may freeze UI for 100-500ms.

**Recommendation:**
1. Consider lazy rendering for code blocks (syntax highlight on-demand, not full content)
2. For thinking blocks: keep collapsed by default (already done, but consider lazy expand)
3. Profile with large responses - if > 200ms render time, add progress indicator

---

### P2 - MEDIUM (Nice to have, can defer)

#### Issue 6.7: No Input Validation on Feedback Text

**Severity:** MEDIUM
**Location:** `src/ui/widgets/tool_card.py`, `ToolApprovalOptions.on_key()`
**Description:**
User can type any character including control chars, ANSI sequences, etc. in feedback:

```python
self.feedback_text += event.character  # No sanitization
```

If feedback is sent back to agent, could cause issues:
- Newlines: break formatting
- Control chars: could confuse agent parsing
- ANSI sequences: rendered literally

**Recommendation:**
```python
if event.character in '\n\r\t':  # Strip control chars
    event.prevent_default()
    return
if event.is_printable:
    self.feedback_text += event.character
```

---

#### Issue 6.8: No Maximum Feedback Length

**Severity:** MEDIUM
**Location:** `src/ui/widgets/tool_card.py`
**Description:**
User can type unlimited feedback text. For a 1-line UI widget, this could:
- Overflow display
- Cause performance issues if very long
- Send huge feedback to agent

**Recommendation:** Add length limit:

```python
MAX_FEEDBACK = 500  # characters

if len(self.feedback_text) < self.MAX_FEEDBACK:
    self.feedback_text += event.character
else:
    # Optional: show warning beep
    event.prevent_default()
```

---

#### Issue 6.9: Auto-Approve List Not Persisted

**Severity:** MEDIUM
**Location:** `src/ui/protocol.py`, `UIProtocol._auto_approve`
**Description:**
Auto-approve rules are stored in memory only:

```python
self._auto_approve: set[str] = set()  # Lost on restart
```

User must re-approve same tools each session. Not critical (security advantage - reapprove each session), but UX improvement would be:

```python
# Load from ~/.config/ai-agent/auto-approve.json on __init__
# Save whenever add_auto_approve() called
```

**Recommendation:** Defer for now. Add if users request it. Security-first approach is fine.

---

#### Issue 6.10: No User Input History / Line Editing

**Severity:** MEDIUM
**Location:** `src/ui/app.py`, `ChatInput` widget
**Description:**
`ChatInput` is a basic Textual Input widget. No:
- Up/Down arrow history navigation
- Ctrl+R reverse search
- Emacs/Vi key bindings
- Copy-paste history

Comparison: Claude Code has full line editing with history.

**Recommendation:** Defer for Phase 2 TUI Polish. Current input is functional for MVP.

---

#### Issue 6.11: Code Block Copy-to-Clipboard Not Implemented

**Severity:** MEDIUM
**Location:** `src/ui/widgets/code_block.py`
**Description:**
Code blocks are displayed but can't be easily copied. User must:
1. Manual selection + copy (works but tedious)
2. No "Copy code" button

Claude Code has visible copy button on hover.

**Recommendation:** Add copy button or keybinding:

```python
class CodeBlock(Static):
    def on_click(self) -> None:
        import pyperclip
        pyperclip.copy(self.code)
        # Show toast: "Copied to clipboard"
```

---

#### Issue 6.12: No Visual Distinction Between Tool Approval States

**Severity:** MEDIUM
**Location:** `src/ui/widgets/tool_card.py`
**Description:**
ToolCard visually looks the same whether:
- AWAITING_APPROVAL (user action needed)
- APPROVED (auto-proceeding)
- REJECTED (user declined)

Colors/icons are updated but subtle. In a chat with many tools, easy to miss which need attention.

**Recommendation:**
- Add indicator to AWAITING_APPROVAL (or use red box border)
- Make approval widget more prominent (flash/animate until focused)
- Play subtle sound on approval prompt (if audio enabled)

---

#### Issue 6.13: Tool Result Preview Truncation Could Lose Critical Info

**Severity:** MEDIUM
**Location:** `src/ui/widgets/tool_card.py`, `_format_result()`
**Description:**
Result preview is truncated to 60 chars for single-line strings:

```python
elif len(result) > 60:
    return result[:57] + "..."  # Info loss!
```

For critical errors or JSON results, truncation could hide important details.

**Recommendation:**
1. Show full result in collapsible/expandable section
2. Or hover tooltip with full text
3. Or "View full result" button

Current level is fine for MVP, but should improve before production.

---

### P3 - LOW (Polish, can defer indefinitely)

#### Issue 6.14: No Dark/Light Theme Toggle

**Severity:** LOW
**Location:** `src/ui/styles.tcss`
**Description:**
Textual app uses default theme. No user preference for dark/light mode.

**Recommendation:** Defer. Textual theme switching is possible but not critical for MVP.

---

#### Issue 6.15: No Keyboard Shortcut Reference Widget

**Severity:** LOW
**Location:** `src/ui/app.py`
**Description:**
Footer shows bindings, but full help/cheatsheet not easily accessible.

**Recommendation:** Add `/help` command that shows:
```
Keyboard Shortcuts
=================
Ctrl+C    Interrupt/Exit
Escape    Cancel approval
Tab       Switch focus
Ctrl+L    Clear screen
Ctrl+D    Quit
```

---

## 7. TESTING STRATEGY

### 7.1 Existing Tests

**Location:** `tests/ui/test_stream_processor.py`

Covers:
- ToolCallAccumulator logic
- Code fence detection (edge cases)
- Thinking block markers
- Debounce timing
- Error classification

**Run:**
```bash
pytest tests/ui/test_stream_processor.py -v
```

### 7.2 Recommended Additional Tests

**Widget Tests:**
```python
# test_message_widget.py
def test_add_text_creates_markdown()
def test_start_streaming_text_creates_static()
def test_finalize_converts_streaming_to_markdown()
def test_add_tool_card_mounts_approval_widget()

# test_tool_approval_options.py
def test_keyboard_shortcut_1_selects_yes()
def test_feedback_mode_prevents_shortcuts()
def test_escape_rejects_approval()

# test_code_block.py
def test_append_updates_code()
def test_finalize_changes_border_to_green()
```

**Integration Tests:**
```python
# test_app_streaming.py
async def test_stream_response_with_tool_approval()
async def test_ctrl_c_cancels_stream()
async def test_auto_scroll_during_streaming()

# test_ui_protocol.py
async def test_wait_for_approval_resolves()
async def test_auto_approve_skips_approval()
async def test_interrupt_cancels_pending_approvals()
```

**End-to-End Tests:**
```bash
# Demo mode test (no real LLM)
python -m src.ui.run_tui --demo

# Manual testing checklist:
# [ ] Type message -> gets sent
# [ ] LLM response streams in real-time
# [ ] Code blocks render with syntax highlighting
# [ ] Tool approval widget appears
# [ ] Press 1/2/y to approve
# [ ] Escape cancels approval
# [ ] Type custom feedback
# [ ] Ctrl+C interrupts stream
# [ ] Status bar shows elapsed time
# [ ] Auto-scroll keeps new content visible
# [ ] User can scroll up to read history
```

---

## 8. KEY ARCHITECTURAL DECISIONS & RATIONALE

### Decision 1: Worker Pattern for Streaming

**Choice:** Use Textual's `run_worker()` instead of direct task spawning

**Rationale:**
- Textual Workers provide exclusive, ordered execution
- Built-in cancellation support
- Prevents concurrent stream race conditions
- Cleaner than manual asyncio task management

**Alternative Considered:** Direct asyncio task - REJECTED (harder to coordinate with Textual message loop)

---

### Decision 2: Segmented Streaming as Default

**Choice:** Accumulate text until boundaries, render once as Markdown

**Rationale:**
- Better UX (stable, readable chunks)
- Faster rendering (O(1) Markdown parse per response, not per event)
- Prevents flickering from partial word streams

**Alternative Considered:** Full streaming (render every delta) - works but slower for large responses

---

### Decision 3: Explicit Mount of Approval Widget

**Choice:** Mount ToolApprovalOptions in `on_mount()`, not `compose()`

**Rationale:**
- Static widgets don't reliably render children from `compose()`
- Explicit mount in `on_mount()` guarantees widget is in DOM before receiving focus
- Fixed the keyboard input issue where approval widget was invisible

**Alternative Considered:** Use Dynamic container instead of Static - REJECTED (added complexity)

---

### Decision 4: No Timeout on Approvals

**Choice:** Wait indefinitely for user approval (no timeout)

**Rationale:**
- User may be multitasking, reading code, considering implications
- Timeout could interrupt important decision-making
- Better UX than "Timeout, try again"

**Alternative Considered:** 30s timeout - REJECTED (too aggressive)

---

### Decision 5: Text Markers Instead of Emojis

**Choice:** Use `[o]`, `[+]`, `[!]` instead of emojis

**Rationale:**
- Windows console uses cp1252 encoding (not UTF-8)
- Emojis cause rendering crashes/corruption on Windows
- Text markers are clear and reliable across all terminals

**Impact:** Zero emoji in Python code, logging, subprocess output

---

## 9. DEPLOYMENT & LAUNCHING

### 9.1 Entry Points

**Textual App:**
```bash
# Demo mode (no real agent)
python -m src.ui.run_tui --demo

# With real agent (requires agent initialization)
python -m src.ui.run_tui

# Run from CLI module
python -m src.cli  # Routes to TUI or other interfaces
```

**Prompt Toolkit Chat:**
```bash
# Old TUI (maintained for compatibility)
python src/ui/chat_interface.py
```

### 9.2 Configuration

**Model Name:** Pass via CLI or read from agent:
```python
app = CodingAgentApp(
    stream_handler=stream_handler,
    model_name=agent.model_name,  # Preferred
    show_header=False,
)
```

**Streaming Mode:** Set at runtime (default: "segmented"):
```python
app._streaming_mode = "full"  # For debugging
```

**Auto-Approve Rules:** Persistent within session (demo):
```python
ui_protocol.add_auto_approve("read_file")  # Skip approval for this tool
```

---

## 10. NEXT STEPS & RECOMMENDATIONS

### Immediate (Before Production)

1. **Fix Issue 6.0** (add_text not awaiting mount) - ROOT CAUSE of text not appearing
2. **Fix Issue 6.2** (Incomplete tool calls) - Add error handler case
3. **Fix Issue 6.5** (ToolApprovalOptions focus) - Remove redundant timer
4. **Fix Issue 6.4** (StatusBar timer cleanup) - Add try/finally guards

### Phase 2 (TUI Polish)

1. **Issue 6.10** - Add input history (Up/Down arrows)
2. **Issue 6.11** - Add copy-to-clipboard for code blocks
3. **Issue 6.14** - Theme toggle (dark/light)
4. **Issue 6.12** - Visual prominence for pending approvals

### Performance Testing

1. Test with large responses (100KB+)
2. Profile Markdown rendering time
3. Monitor memory usage during long sessions
4. Load test with rapid tool approvals

### Documentation

1. Add TUI architecture diagram to docs/
2. Document streaming modes (segmented vs full)
3. Create troubleshooting guide for common issues
4. Add keyboard shortcut reference card

---

## Appendix A: File Manifest

```
src/ui/
|-- app.py                      # Main Textual app (1000 LOC)
|-- events.py                   # Typed event contract (233 LOC)
|-- protocol.py                 # Bidirectional coordination (248 LOC)
|-- messages.py                 # Textual message types (78 LOC)
|-- stream_processor.py         # State machine (700 LOC)
|-- agent_adapter.py            # Bridge to existing agent (378 LOC)
|-- chat_interface.py           # Legacy prompt_toolkit TUI (651 LOC)
|-- run_tui.py                  # Entry point (126 LOC)
|-- formatters.py               # Text formatting utilities
|-- styles.tcss                 # Textual CSS (225 LOC)
+-- widgets/
    |-- message.py              # Message container (514 LOC)
    |-- code_block.py           # Syntax-highlighted code (168 LOC)
    |-- tool_card.py            # Tool card + approval UI (579 LOC)
    |-- thinking.py             # Collapsible thinking (238 LOC)
    |-- status_bar.py           # Bottom status bar (335 LOC)
    +-- __init__.py

tests/ui/
|-- test_stream_processor.py    # Comprehensive stream tests
+-- __init__.py
```

**Total:** ~5500 LOC of TUI code

---

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **Streaming** | Real-time delivery of LLM response chunks to UI |
| **Segmented** | Streaming mode that buffers text until boundaries (default) |
| **Delta** | Incremental chunk of content (text, code, etc.) |
| **UIEvent** | Typed event contract (StreamStart, TextDelta, ToolCallStart, etc.) |
| **UIProtocol** | Async coordination layer between agent and UI |
| **Worker** | Textual background worker for non-blocking tasks |
| **MessageWidget** | Container for all blocks in a single message |
| **Block** | Content element (Markdown, CodeBlock, ToolCard, ThinkingBlock) |
| **ToolCard** | Visual representation of tool call status |
| **Approval** | User permission to execute a tool |
| **Auto-Approve** | Session-scoped rule to skip approval for specific tools |
| **Fence** | Code block delimiters (``` ... ```) |
| **Thinking** | Extended reasoning/thinking block (Claude models) |
| **Debounce** | Delay rendering until natural boundary (prevents flickering) |
| **Coalesce** | Combine multiple small updates into one larger update |

---

## 11. SESSION PERSISTENCE INTEGRATION POINTS

This section documents the integration points for adding session persistence to the TUI, enabling conversation resume across restarts.

### 11.1 Current State Tracking Summary

The TUI currently tracks state at multiple levels without persistence:

| Component | State | Current Storage | Persistence Target |
|-----------|-------|-----------------|-------------------|
| `CodingAgentApp` | `_current_message`, `_tool_cards` | In-memory | Session JSONL |
| `MessageWidget` | `_blocks`, role, content | Widget tree | Session JSONL |
| `UIProtocol` | `_auto_approve`, `_pending_approvals` | In-memory | Session metadata |
| `CodingAgent.memory` | Conversation history | `MemoryManager` | Session JSONL |
| `CodingAgent.todo_state` | Task list | Dict | Session JSONL |

### 11.2 Integration Architecture

```
+-------------------------------------------------------------------+
|                       Session Persistence                         |
+-------------------------------------------------------------------+
|                                                                   |
|  +---------------------+                                          |
|  |  SessionManager     |  - Lifecycle: create/resume/close        |
|  |  (session/manager/) |  - Owns store + writer                   |
|  +----------+----------+                                          |
|             |                                                     |
|  +----------v----------+      +-------------------+               |
|  |   MessageStore      |<---->|  SessionWriter    |               |
|  |   (In-Memory)       |      |  (JSONL Output)   |               |
|  +----------+----------+      +-------------------+               |
|             |                                                     |
|             | Events trigger writes                               |
|             |                                                     |
+-------------------------------------------------------------------+
                              ^
                              | Hook into
+-----------------------------+-----------------------------+
|                    CodingAgentApp                         |
|  - _handle_event() processes UIEvents                     |
|  - Mount MessageWidget, CodeBlock, ToolCard               |
|  - Receive StreamEnd with complete message content        |
+-----------------------------------------------------------+
```

### 11.3 Where Messages Are Created (Hook Points)

#### User Messages

**Location:** `CodingAgentApp.on_input_submitted_message()`

```python
# Current code (app.py, ~line 400)
async def on_input_submitted_message(self, message: InputSubmittedMessage):
    user_input = message.content.strip()
    attachments = message.attachments

    # UI: Mount user message widget
    await self._add_user_message(user_input + attachment_summary)

    # HOOK POINT: Persist user message here
    # if self.session_manager and self.session_manager.is_active:
    #     self.session_manager.store.add_message(
    #         role="user",
    #         content=user_input,
    #         attachments=[att.to_dict() for att in attachments],
    #     )

    # Start streaming
    self._stream_worker = self.run_worker(...)
```

#### Assistant Messages

**Location:** `CodingAgentApp._handle_event()` (StreamStart/StreamEnd)

```python
# Current code (app.py, ~line 600)
case StreamStart():
    msg = AssistantMessage()
    self._current_message = msg
    await conversation.mount(msg)
    # HOOK POINT: Generate message ID for tracking
    # self._current_message_id = generate_uuid()

case StreamEnd(total_tokens=tokens, duration_ms=duration):
    await self._flush_segment()
    self._finalize_current_message(msg)
    # HOOK POINT: Persist complete assistant message
    # content = self._current_message.get_plain_text()
    # if self.session_manager:
    #     self.session_manager.store.add_message(
    #         id=self._current_message_id,
    #         role="assistant",
    #         content=content,
    #         token_count=tokens,
    #         duration_ms=duration,
    #     )
```

#### Tool Calls

**Location:** `CodingAgentApp._handle_event()` (ToolCallStart/ToolCallResult)

```python
# Current code (app.py, ~line 650)
case ToolCallStart(call_id, name, arguments, requires_approval):
    card = self._current_message.add_tool_card(...)
    self._tool_cards[call_id] = card
    # HOOK POINT: Persist tool call
    # if self.session_manager:
    #     self.session_manager.store.add_tool_call(
    #         message_id=self._current_message_id,
    #         call_id=call_id,
    #         name=name,
    #         arguments=arguments,
    #     )

case ToolCallResult(call_id, status, result, error, duration_ms):
    card.set_result(result, duration_ms)
    # HOOK POINT: Persist tool result
    # if self.session_manager:
    #     self.session_manager.store.update_tool_result(
    #         call_id=call_id,
    #         status=status.value,
    #         result=result,
    #         error=error,
    #         duration_ms=duration_ms,
    #     )
```

### 11.4 Session Resume Flow

To restore a conversation from a persisted session:

```python
# In CodingAgentApp
async def _restore_conversation(self) -> None:
    """Restore conversation from session store."""
    if not self.session_manager or not self.session_manager.store:
        return

    messages = self.session_manager.store.get_ordered_messages()
    conversation = self.query_one("#conversation")

    for msg in messages:
        if msg.role == "user":
            # Restore user message
            widget = UserMessage()
            await conversation.mount(widget)
            await widget.add_text(msg.content)

        elif msg.role == "assistant":
            # Restore assistant message
            widget = AssistantMessage()
            await conversation.mount(widget)

            # Restore content blocks in order
            for block in msg.blocks:
                if block.type == "text":
                    await widget.add_text(block.content)
                elif block.type == "code":
                    code_block = widget.start_code_block(block.language)
                    code_block.set_code(block.content)
                    widget.end_code_block()
                elif block.type == "tool":
                    card = widget.add_tool_card(
                        call_id=block.call_id,
                        tool_name=block.name,
                        args=block.arguments,
                        requires_approval=False,  # Don't re-approve
                    )
                    if block.result:
                        card.set_result(block.result, block.duration_ms)
                    elif block.error:
                        card.set_error(block.error)

    # Scroll to end
    conversation.scroll_end(animate=False)
```

### 11.5 Recommended Integration Strategy

#### Option A: TUI-Level Persistence (Recommended)

Hook into `_handle_event()` to persist as events are processed:

**Pros:**
- Complete control over what gets persisted
- Can capture UI-specific state (collapsed thinking, etc.)
- Natural fit with event-driven architecture

**Cons:**
- Requires passing SessionManager to TUI
- Duplicates some logic from agent

```python
class CodingAgentApp(App):
    def __init__(self, session_manager: SessionManager = None, ...):
        self.session_manager = session_manager
        ...

    async def on_mount(self) -> None:
        if self.session_manager:
            await self.session_manager.start_writer()
            if not self.session_manager.info.is_new:
                await self._restore_conversation()
```

#### Option B: Agent-Level Persistence

Let the agent handle all persistence in `stream_response()`:

**Pros:**
- Single source of truth (agent)
- Cleaner separation

**Cons:**
- TUI doesn't know about message IDs
- Harder to correlate UI widgets with persisted messages

#### Option C: Dual Persistence (Most Robust)

Persist at both levels with reconciliation:

```python
# Agent persists messages as they're generated
# TUI persists UI state (collapsed blocks, scroll position)
# On resume: agent provides messages, TUI applies UI state
```

### 11.6 Session File Format (JSONL)

The existing session infrastructure uses JSONL format:

```jsonl
{"type": "session_start", "session_id": "abc-123", "version": "1.0.0", "ts": "..."}
{"type": "message", "id": "msg-1", "role": "user", "content": "Hello", "ts": "..."}
{"type": "message", "id": "msg-2", "role": "assistant", "content": "Hi!", "ts": "..."}
{"type": "tool_call", "message_id": "msg-2", "call_id": "tc-1", "name": "read_file", "args": {...}}
{"type": "tool_result", "call_id": "tc-1", "status": "success", "result": "...", "duration_ms": 42}
```

### 11.7 Implementation Checklist

```
[ ] 1. Add SessionManager parameter to CodingAgentApp.__init__()
[ ] 2. Call session_manager.start_writer() in on_mount() (async context)
[ ] 3. Generate message IDs on StreamStart
[ ] 4. Persist user messages in on_input_submitted_message()
[ ] 5. Persist assistant messages on StreamEnd
[ ] 6. Persist tool calls on ToolCallStart
[ ] 7. Persist tool results on ToolCallResult
[ ] 8. Implement _restore_conversation() for session resume
[ ] 9. Add session resume CLI flag (--session <id>)
[ ] 10. Handle graceful shutdown (close writer on exit)
[ ] 11. Add tests for session persistence roundtrip
[ ] 12. Update CLAUDE.md with session commands
```

### 11.8 Current Gaps (What Session Persistence Fills)

| Gap | Current Behavior | With Persistence |
|-----|-----------------|------------------|
| Session resume | Conversation lost on exit | Resume from last state |
| Message IDs | No tracking | Unique IDs per message |
| Tool call history | In-memory only | Persisted to JSONL |
| Conversation compaction | Memory only | Persist before/after |
| Crash recovery | Total loss | Resume from checkpoint |
| Session listing | N/A | `--list-sessions` command |
| Session deletion | N/A | `--delete-session <id>` |

### 11.9 Existing Session Infrastructure

The session persistence infrastructure already exists in `src/session/`:

```
src/session/
├── manager/
│   └── session_manager.py   # SessionManager class
├── store/
│   └── memory_store.py      # MessageStore (in-memory)
├── persistence/
│   ├── parser.py            # JSONL parser (load_session)
│   └── writer.py            # JSONL writer (SessionWriter)
└── models/
    ├── base.py              # SessionContext, generate_uuid
    └── message.py           # Message models
```

Key classes:

```python
# SessionManager - Lifecycle management
session_manager = SessionManager(sessions_dir=".claraity/sessions")
info = session_manager.create_session(cwd=os.getcwd())
# or
info = session_manager.resume_session(session_id="abc-123")
await session_manager.start_writer()
await session_manager.close()

# MessageStore - In-memory storage
store = session_manager.store
store.add_message(role="user", content="Hello")
messages = store.get_ordered_messages()

# SessionWriter - JSONL output
# Automatically writes when bound to store via start_writer()
```

---

**End of Documentation**
