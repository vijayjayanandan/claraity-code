# Claude Code Prompt: Production-Grade Textual TUI for Coding Agent

## Overview

Build a production-grade TUI for a CLI coding agent using Textual. This replaces an existing prompt_toolkit implementation that has issues with streaming output, raw JSON tool calls leaking, and inability to render rich content.

**Quality Standards:**
- Production-ready, not MVP
- Comprehensive error handling
- Full test coverage for critical paths
- Clean separation of concerns
- No technical debt in core systems

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LLM Backend                                    │
│                    (OpenAI-compatible streaming API)                        │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ raw chunks + tool_call deltas
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           StreamProcessor                                   │
│                                                                             │
│  State Machine + Buffers → Emits typed UIEvent objects                      │
│  - Accumulates tool_calls until JSON is complete                            │
│  - Detects code fence boundaries (handles edge cases)                       │
│  - Hybrid debouncing (idle-based + max latency cap)                         │
│  - Error capture and classification                                         │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ UIEvent (typed, immutable)
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            UIProtocol                                       │
│                                                                             │
│  Bidirectional communication layer:                                         │
│  - UIEvent: LLM → UI (downstream)                                           │
│  - UserAction: UI → Agent (upstream via async queue)                        │
└──────────────────────┬────────────────────────┬─────────────────────────────┘
                       │                        │
                       ▼                        ▼
┌──────────────────────────────────┐  ┌────────────────────────────────────────┐
│         Textual App              │  │              Agent                     │
│                                  │  │                                        │
│  - Renders UIEvents to widgets   │  │  - Consumes UserActions from queue     │
│  - Posts Textual Messages        │  │  - Awaits approval via protocol        │
│  - Puts UserActions in queue     │  │  - Handles tool execution              │
└──────────────────────────────────┘  └────────────────────────────────────────┘
```

---

## File Structure

```
src/ui/
├── __init__.py
├── events.py           # UIEvent types (LLM → UI contract)
├── messages.py         # Textual Messages (Widget ↔ App, internal)
├── protocol.py         # UserAction types + UIProtocol (UI ↔ Agent contract)
├── stream_processor.py # State machine with hybrid debouncing
├── app.py              # Main CodingAgentApp
├── styles.tcss         # Textual CSS
└── widgets/
    ├── __init__.py
    ├── code_block.py   # Syntax-highlighted code
    ├── tool_card.py    # Tool status + approval UI
    ├── thinking.py     # Collapsible thinking block
    ├── message.py      # Message container
    └── status_bar.py   # Status, errors, countdowns
```

---

## Task 1: Event Types (`events.py`)

The contract between StreamProcessor and UI. These are **immutable, typed events** that flow downstream. The UI never parses raw text.

```python
"""
UI Event Types - The contract between StreamProcessor and Textual UI.

Design Principles:
- Frozen dataclasses for immutability
- Discriminated union via structural pattern matching
- No optional fields that change semantics (use separate event types)
- Events are facts about what happened, not commands
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Union


class ToolStatus(Enum):
    """Tool execution lifecycle states."""
    
    PENDING = auto()            # Queued, not yet started
    AWAITING_APPROVAL = auto()  # Waiting for user confirmation
    APPROVED = auto()           # User approved, about to execute
    REJECTED = auto()           # User rejected
    RUNNING = auto()            # Currently executing
    SUCCESS = auto()            # Completed successfully
    FAILED = auto()             # Completed with error
    CANCELLED = auto()          # User cancelled mid-execution


# =============================================================================
# Stream Lifecycle Events
# =============================================================================

@dataclass(frozen=True)
class StreamStart:
    """
    New assistant response starting.
    
    UI should create a new MessageWidget for the assistant.
    """
    pass


@dataclass(frozen=True)
class StreamEnd:
    """
    Stream complete (normal termination).
    
    UI should finalize the current message and re-focus input.
    """
    total_tokens: int | None = None
    duration_ms: int | None = None


# =============================================================================
# Text Content Events
# =============================================================================

@dataclass(frozen=True)
class TextDelta:
    """
    Incremental text content to append to the current markdown block.
    
    These arrive debounced (not per-token) for smooth rendering.
    The UI should accumulate and render as Markdown.
    """
    content: str


# =============================================================================
# Code Block Events
# =============================================================================

@dataclass(frozen=True)
class CodeBlockStart:
    """
    Start a new syntax-highlighted code block.
    
    The UI should create a new CodeBlock widget.
    Subsequent CodeBlockDelta events append to this block.
    """
    language: str
    
    def __post_init__(self):
        # Normalize empty/None language to "text"
        if not self.language:
            object.__setattr__(self, 'language', 'text')


@dataclass(frozen=True)
class CodeBlockDelta:
    """
    Incremental code content to append to the current code block.
    """
    content: str


@dataclass(frozen=True)
class CodeBlockEnd:
    """
    Current code block is complete.
    
    UI should finalize the block (update border, stop streaming indicator).
    """
    pass


# =============================================================================
# Tool Call Events
# =============================================================================

@dataclass(frozen=True)
class ToolCallStart:
    """
    A complete, parsed tool call ready for execution.
    
    IMPORTANT: This is only emitted when the full tool call has been
    accumulated (name + valid JSON arguments). The UI never sees raw JSON.
    
    Attributes:
        call_id: Unique identifier for tracking this tool call
        name: Tool function name (e.g., "read_file", "write_file", "bash")
        arguments: Fully parsed, validated arguments dict
        requires_approval: Whether user must approve before execution
    """
    call_id: str
    name: str
    arguments: dict[str, Any]
    requires_approval: bool


@dataclass(frozen=True)
class ToolCallStatus:
    """
    Tool execution status update.
    
    Emitted when tool transitions between states (pending → running → complete).
    """
    call_id: str
    status: ToolStatus
    message: str | None = None  # Optional status message (e.g., "Reading file...")


@dataclass(frozen=True)
class ToolCallResult:
    """
    Tool execution completed with result.
    
    This is the terminal event for a tool call.
    """
    call_id: str
    status: ToolStatus  # SUCCESS or FAILED
    result: Any = None
    error: str | None = None
    duration_ms: int | None = None


# =============================================================================
# Thinking/Reasoning Events (for models with extended thinking)
# =============================================================================

@dataclass(frozen=True)
class ThinkingStart:
    """
    Model started extended thinking/reasoning.
    
    UI should create a collapsible ThinkingBlock.
    """
    pass


@dataclass(frozen=True)
class ThinkingDelta:
    """
    Incremental thinking content.
    """
    content: str


@dataclass(frozen=True)
class ThinkingEnd:
    """
    Thinking phase complete.
    
    UI should finalize the thinking block and show token count.
    """
    token_count: int | None = None


# =============================================================================
# Error Events
# =============================================================================

@dataclass(frozen=True)
class ErrorEvent:
    """
    Error during streaming.
    
    Attributes:
        error_type: Category for determining recovery behavior
        message: Human-readable error message
        recoverable: Whether automatic retry is possible
        retry_after: Seconds to wait before retry (for rate limits)
    """
    error_type: str  # "rate_limit", "network", "api_error", "auth", "invalid_request"
    message: str
    recoverable: bool = True
    retry_after: int | None = None  # Seconds until retry (for rate limits)


# =============================================================================
# Type Union for Pattern Matching
# =============================================================================

UIEvent = (
    StreamStart | StreamEnd |
    TextDelta |
    CodeBlockStart | CodeBlockDelta | CodeBlockEnd |
    ToolCallStart | ToolCallStatus | ToolCallResult |
    ThinkingStart | ThinkingDelta | ThinkingEnd |
    ErrorEvent
)
```

---

## Task 2: Internal Textual Messages (`messages.py`)

These are **internal to the UI layer** — communication between widgets and the App. Not part of the public contract.

```python
"""
Internal Textual Messages - Widget ↔ App communication.

These are NOT part of the public contract. They're internal to the UI layer.
Use these for Textual's message-passing system between widgets and the App.
"""

from textual.message import Message


class ApprovalResponseMessage(Message):
    """
    User responded to a tool approval prompt.
    
    Posted by ToolApprovalOptions, handled by CodingAgentApp.
    """
    
    def __init__(
        self, 
        call_id: str, 
        action: str,
        feedback: str | None = None
    ):
        super().__init__()
        self.call_id = call_id
        self.action = action  # "yes", "yes_all", "no", "feedback"
        self.feedback = feedback  # User's modified instructions (if action == "feedback")


class StreamInterruptMessage(Message):
    """
    User requested stream interruption (Ctrl+C).
    
    Posted by keybinding handler, triggers cancellation.
    """
    pass


class RetryRequestMessage(Message):
    """
    User clicked retry after a recoverable error.
    """
    pass


class ScrollStateChangedMessage(Message):
    """
    User scroll position changed.
    
    Used to track whether auto-scroll should be enabled.
    """
    
    def __init__(self, at_bottom: bool):
        super().__init__()
        self.at_bottom = at_bottom


class InputSubmittedMessage(Message):
    """
    User submitted input.
    
    Decouples TextArea from submission logic.
    """
    
    def __init__(self, content: str):
        super().__init__()
        self.content = content
```

---

## Task 3: UI Protocol (`protocol.py`)

The **bidirectional contract** between UI and Agent. This enables clean async coordination without tight coupling.

```python
"""
UI Protocol - Bidirectional communication between UI and Agent.

This module defines:
- UserAction: Events from UI to Agent (approval responses, interrupts)
- UIProtocol: Async coordination layer with queues

Design Principles:
- Agent doesn't know about Textual internals
- UI doesn't touch Agent's private state
- All coordination via async queues (testable, decoupled)
"""

from dataclasses import dataclass
from typing import AsyncIterator
import asyncio

from .events import UIEvent


# =============================================================================
# User Actions (UI → Agent)
# =============================================================================

@dataclass(frozen=True)
class ApprovalResult:
    """
    User's response to a tool approval request.
    """
    call_id: str
    approved: bool
    auto_approve_future: bool = False  # "Don't ask again for this tool"
    feedback: str | None = None        # Modified instructions (if provided)


@dataclass(frozen=True)
class InterruptSignal:
    """
    User interrupted the stream (Ctrl+C).
    """
    pass


@dataclass(frozen=True)
class RetrySignal:
    """
    User requested retry after error.
    """
    pass


# Union type
UserAction = ApprovalResult | InterruptSignal | RetrySignal


# =============================================================================
# UI Protocol (Coordination Layer)
# =============================================================================

class UIProtocol:
    """
    Bidirectional communication layer between UI and Agent.
    
    Usage in Agent:
        async def stream_response(self, user_input: str, ui: UIProtocol):
            async for event in processor.process(raw_stream):
                yield event
                
                if isinstance(event, ToolCallStart) and event.requires_approval:
                    result = await ui.wait_for_approval(event.call_id)
                    if not result.approved:
                        yield ToolCallStatus(event.call_id, ToolStatus.REJECTED)
                        continue
    
    Usage in Textual App:
        def on_approval_response_message(self, message: ApprovalResponseMessage):
            self.ui_protocol.submit_action(
                ApprovalResult(
                    call_id=message.call_id,
                    approved=message.action in ("yes", "yes_all"),
                    auto_approve_future=message.action == "yes_all",
                    feedback=message.feedback,
                )
            )
    """
    
    def __init__(self):
        # Queue for UI → Agent actions
        self._action_queue: asyncio.Queue[UserAction] = asyncio.Queue()
        
        # Track pending approvals for targeted delivery
        self._pending_approvals: dict[str, asyncio.Future[ApprovalResult]] = {}
        
        # Auto-approve rules (tool_name → True)
        self._auto_approve: set[str] = set()
        
        # Interrupt flag
        self._interrupted = asyncio.Event()
    
    # -------------------------------------------------------------------------
    # Agent-side methods
    # -------------------------------------------------------------------------
    
    async def wait_for_approval(
        self, 
        call_id: str, 
        tool_name: str,
        timeout: float | None = None
    ) -> ApprovalResult:
        """
        Wait for user to approve/reject a tool call.
        
        Args:
            call_id: The tool call ID to wait for
            tool_name: Tool name (for auto-approve lookup)
            timeout: Optional timeout in seconds
        
        Returns:
            ApprovalResult with user's decision
        
        Raises:
            asyncio.CancelledError: If stream was interrupted
            asyncio.TimeoutError: If timeout exceeded
        """
        # Check auto-approve first
        if tool_name in self._auto_approve:
            return ApprovalResult(
                call_id=call_id,
                approved=True,
                auto_approve_future=True,
            )
        
        # Create future for this specific call
        future: asyncio.Future[ApprovalResult] = asyncio.Future()
        self._pending_approvals[call_id] = future
        
        try:
            if timeout:
                return await asyncio.wait_for(future, timeout)
            else:
                return await future
        finally:
            self._pending_approvals.pop(call_id, None)
    
    def check_interrupted(self) -> bool:
        """Check if user has requested interruption."""
        return self._interrupted.is_set()
    
    async def wait_for_interrupt(self) -> None:
        """Wait until interrupted. Use with asyncio.wait() for cancellation."""
        await self._interrupted.wait()
    
    # -------------------------------------------------------------------------
    # UI-side methods
    # -------------------------------------------------------------------------
    
    def submit_action(self, action: UserAction) -> None:
        """
        Submit a user action (non-blocking).
        
        Called by Textual message handlers.
        """
        if isinstance(action, ApprovalResult):
            # Deliver to specific waiting future
            future = self._pending_approvals.get(action.call_id)
            if future and not future.done():
                future.set_result(action)
                
                # Handle auto-approve
                if action.auto_approve_future and action.approved:
                    # Need to look up tool name - store it when creating approval
                    pass  # TODO: track tool_name in _pending_approvals
        
        elif isinstance(action, InterruptSignal):
            self._interrupted.set()
            # Cancel all pending approvals
            for future in self._pending_approvals.values():
                if not future.done():
                    future.cancel()
        
        # Also put in general queue for other consumers
        self._action_queue.put_nowait(action)
    
    def reset(self) -> None:
        """Reset state for new conversation turn."""
        self._interrupted.clear()
        self._pending_approvals.clear()
        # Don't clear auto_approve - persists within session
```

---

## Task 4: Stream Processor (`stream_processor.py`)

The **core state machine** that transforms raw LLM chunks into typed events. This is the most complex component.

```python
"""
Stream Processor - State machine for LLM stream → UIEvent transformation.

This is the critical path for streaming UX. It must:
1. Never leak raw JSON to the UI
2. Handle code fence edge cases
3. Debounce text for smooth rendering
4. Emit proper error events

Complexity: HIGH - extensive unit tests required.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import AsyncIterator, Iterator
import asyncio
import json
import re
import time

from .events import (
    UIEvent, StreamStart, StreamEnd,
    TextDelta, CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    ErrorEvent, ToolStatus,
)


class StreamState(Enum):
    """Parser state machine states."""
    
    IDLE = auto()           # Before stream starts
    TEXT = auto()           # Normal text content
    CODE_BLOCK = auto()     # Inside code fence
    THINKING = auto()       # Inside thinking block


@dataclass
class ToolCallAccumulator:
    """Accumulates partial tool call data until complete."""
    
    index: int
    name: str = ""
    arguments: str = ""
    
    def is_complete(self) -> bool:
        """Check if we have valid, complete JSON arguments."""
        if not self.name or not self.arguments:
            return False
        try:
            json.loads(self.arguments)
            return True
        except json.JSONDecodeError:
            return False
    
    def parse_arguments(self) -> dict:
        """Parse arguments JSON. Call only when is_complete() is True."""
        return json.loads(self.arguments)


class StreamProcessor:
    """
    Transforms raw LLM stream chunks into typed UI events.
    
    Features:
    - Hybrid debouncing (idle-based + max latency cap)
    - Code fence detection with edge case handling
    - Tool call accumulation (no raw JSON leaks)
    - Error capture and classification
    
    Usage:
        processor = StreamProcessor()
        async for event in processor.process(raw_stream):
            # event is a typed UIEvent
            pass
    """
    
    # Code fence patterns
    # Opening: ```language or just ```
    FENCE_OPEN_PATTERN = re.compile(r'```(\w*)\s*\n?')
    # Closing: ``` on its own line (with optional whitespace)
    FENCE_CLOSE_PATTERN = re.compile(r'\n```\s*(?:\n|$)')
    
    # Thinking block patterns (adjust based on your LLM's format)
    THINKING_START_PATTERN = re.compile(r'<thinking>\s*')
    THINKING_END_PATTERN = re.compile(r'\s*</thinking>')
    
    def __init__(
        self,
        idle_timeout_ms: int = 50,
        max_latency_ms: int = 150,
        approval_checker: callable = None,  # (tool_name) -> bool
    ):
        """
        Args:
            idle_timeout_ms: Flush text buffer after this much idle time
            max_latency_ms: Force flush after this much time (prevents UI starvation)
            approval_checker: Function to check if tool requires approval
        """
        self.idle_timeout = idle_timeout_ms / 1000
        self.max_latency = max_latency_ms / 1000
        self.approval_checker = approval_checker or (lambda name: True)
        
        # State
        self._state = StreamState.IDLE
        self._text_buffer = ""
        self._code_buffer = ""
        self._code_language = ""
        self._thinking_buffer = ""
        self._thinking_token_count = 0
        
        # Tool call accumulation
        self._tool_calls: dict[int, ToolCallAccumulator] = {}
        
        # Timing for debounce
        self._first_chunk_time: float = 0
        self._last_chunk_time: float = 0
        
        # Partial fence detection
        self._potential_fence = ""
    
    async def process(
        self,
        raw_stream: AsyncIterator,  # Yields OpenAI-style chunks
    ) -> AsyncIterator[UIEvent]:
        """
        Main processing loop.
        
        Consumes raw LLM chunks, yields typed UIEvents.
        """
        yield StreamStart()
        self._state = StreamState.TEXT
        
        start_time = time.monotonic()
        
        try:
            async for chunk in raw_stream:
                # Process tool call deltas (OpenAI format)
                if hasattr(chunk, 'choices') and chunk.choices:
                    delta = chunk.choices[0].delta
                    
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            async for event in self._accumulate_tool_call(tc_delta):
                                yield event
                    
                    if hasattr(delta, 'content') and delta.content:
                        async for event in self._process_content(delta.content):
                            yield event
            
            # Flush remaining buffers
            async for event in self._flush_all():
                yield event
            
            duration_ms = int((time.monotonic() - start_time) * 1000)
            yield StreamEnd(duration_ms=duration_ms)
        
        except Exception as e:
            yield from self._handle_error(e)
    
    async def _accumulate_tool_call(self, delta) -> AsyncIterator[UIEvent]:
        """
        Accumulate tool call deltas until we have complete, valid JSON.
        
        OpenAI streams tool calls as:
        - delta.index: which tool call (0, 1, 2...)
        - delta.function.name: streamed incrementally
        - delta.function.arguments: streamed as partial JSON
        """
        idx = delta.index
        
        if idx not in self._tool_calls:
            self._tool_calls[idx] = ToolCallAccumulator(index=idx)
        
        acc = self._tool_calls[idx]
        
        # Accumulate name
        if hasattr(delta, 'function') and delta.function:
            if delta.function.name:
                acc.name += delta.function.name
            if delta.function.arguments:
                acc.arguments += delta.function.arguments
        
        # Check if complete
        if acc.is_complete():
            args = acc.parse_arguments()
            requires_approval = self.approval_checker(acc.name)
            
            yield ToolCallStart(
                call_id=str(idx),
                name=acc.name,
                arguments=args,
                requires_approval=requires_approval,
            )
            
            del self._tool_calls[idx]
    
    async def _process_content(self, content: str) -> AsyncIterator[UIEvent]:
        """
        Process text content with state machine transitions.
        
        Handles:
        - Normal text → accumulate in buffer
        - Code fence start → transition to CODE_BLOCK
        - Code fence end → transition back to TEXT
        - Thinking markers → transition to/from THINKING
        """
        self._update_timing()
        
        # Add to appropriate buffer based on state
        if self._state == StreamState.TEXT:
            self._text_buffer += content
            async for event in self._check_transitions_from_text():
                yield event
        
        elif self._state == StreamState.CODE_BLOCK:
            self._code_buffer += content
            async for event in self._check_code_fence_close():
                yield event
        
        elif self._state == StreamState.THINKING:
            self._thinking_buffer += content
            self._thinking_token_count += len(content.split())  # Rough estimate
            async for event in self._check_thinking_end():
                yield event
        
        # Check if we should flush text buffer (debounce)
        if self._state == StreamState.TEXT and self._should_flush_text():
            async for event in self._flush_text():
                yield event
    
    def _update_timing(self) -> None:
        """Update timing for debounce logic."""
        now = time.monotonic()
        if not self._first_chunk_time:
            self._first_chunk_time = now
        self._last_chunk_time = now
    
    def _should_flush_text(self) -> bool:
        """
        Determine if text buffer should be flushed.
        
        Hybrid strategy:
        1. Flush on natural breaks (newline at end)
        2. Flush if max latency exceeded (don't starve UI)
        """
        if not self._text_buffer:
            return False
        
        now = time.monotonic()
        
        # Natural break: ends with newline
        if self._text_buffer.endswith('\n'):
            return True
        
        # Max latency exceeded
        if (now - self._first_chunk_time) >= self.max_latency:
            return True
        
        return False
    
    async def _check_transitions_from_text(self) -> AsyncIterator[UIEvent]:
        """
        Check for state transitions while in TEXT state.
        
        Handles:
        - ```language → CODE_BLOCK
        - <thinking> → THINKING
        """
        # Check for code fence opening
        match = self.FENCE_OPEN_PATTERN.search(self._text_buffer)
        if match:
            # Flush text before the fence
            before = self._text_buffer[:match.start()]
            if before:
                yield TextDelta(content=before)
            
            # Transition to code block
            self._code_language = match.group(1) or "text"
            self._state = StreamState.CODE_BLOCK
            yield CodeBlockStart(language=self._code_language)
            
            # Remaining content goes to code buffer
            self._code_buffer = self._text_buffer[match.end():]
            self._text_buffer = ""
            self._reset_timing()
            
            # Check if code buffer already has closing fence
            async for event in self._check_code_fence_close():
                yield event
            return
        
        # Check for thinking start
        match = self.THINKING_START_PATTERN.search(self._text_buffer)
        if match:
            # Flush text before thinking
            before = self._text_buffer[:match.start()]
            if before:
                yield TextDelta(content=before)
            
            self._state = StreamState.THINKING
            yield ThinkingStart()
            
            self._thinking_buffer = self._text_buffer[match.end():]
            self._text_buffer = ""
            self._reset_timing()
            return
    
    async def _check_code_fence_close(self) -> AsyncIterator[UIEvent]:
        """Check for closing code fence."""
        match = self.FENCE_CLOSE_PATTERN.search(self._code_buffer)
        if match:
            # Code before the closing fence
            code = self._code_buffer[:match.start()]
            if code:
                yield CodeBlockDelta(content=code)
            
            yield CodeBlockEnd()
            
            # Transition back to text
            self._state = StreamState.TEXT
            self._text_buffer = self._code_buffer[match.end():]
            self._code_buffer = ""
            self._code_language = ""
            self._reset_timing()
            
            # Check for new transitions in remaining text
            async for event in self._check_transitions_from_text():
                yield event
        else:
            # No closing fence yet, emit buffered code
            # But keep potential partial fence at end
            safe_to_emit = self._code_buffer
            
            # Don't emit if buffer ends with potential fence start
            if safe_to_emit.endswith('\n`'):
                safe_to_emit = safe_to_emit[:-2]
                self._code_buffer = '\n`'
            elif safe_to_emit.endswith('\n``'):
                safe_to_emit = safe_to_emit[:-3]
                self._code_buffer = '\n``'
            elif safe_to_emit.endswith('\n```'):
                # This might be the closing fence, wait for more
                return
            else:
                self._code_buffer = ""
            
            if safe_to_emit:
                yield CodeBlockDelta(content=safe_to_emit)
    
    async def _check_thinking_end(self) -> AsyncIterator[UIEvent]:
        """Check for thinking block end."""
        match = self.THINKING_END_PATTERN.search(self._thinking_buffer)
        if match:
            # Emit thinking content
            content = self._thinking_buffer[:match.start()]
            if content:
                yield ThinkingDelta(content=content)
            
            yield ThinkingEnd(token_count=self._thinking_token_count)
            
            # Transition back to text
            self._state = StreamState.TEXT
            self._text_buffer = self._thinking_buffer[match.end():]
            self._thinking_buffer = ""
            self._thinking_token_count = 0
            self._reset_timing()
        else:
            # Emit accumulated thinking content periodically
            if len(self._thinking_buffer) > 100:
                yield ThinkingDelta(content=self._thinking_buffer)
                self._thinking_buffer = ""
    
    async def _flush_text(self) -> AsyncIterator[UIEvent]:
        """Flush text buffer as TextDelta."""
        if self._text_buffer:
            # Don't flush if buffer might contain partial fence
            if self._text_buffer.rstrip().endswith('`'):
                # Wait for more content to determine if it's a fence
                return
            
            yield TextDelta(content=self._text_buffer)
            self._text_buffer = ""
            self._reset_timing()
    
    async def _flush_all(self) -> AsyncIterator[UIEvent]:
        """Flush all remaining buffers at stream end."""
        if self._state == StreamState.TEXT and self._text_buffer:
            yield TextDelta(content=self._text_buffer)
            self._text_buffer = ""
        
        elif self._state == StreamState.CODE_BLOCK:
            if self._code_buffer:
                yield CodeBlockDelta(content=self._code_buffer)
            yield CodeBlockEnd()
            self._code_buffer = ""
        
        elif self._state == StreamState.THINKING:
            if self._thinking_buffer:
                yield ThinkingDelta(content=self._thinking_buffer)
            yield ThinkingEnd(token_count=self._thinking_token_count)
            self._thinking_buffer = ""
        
        # Warn about incomplete tool calls (shouldn't happen normally)
        for idx, acc in self._tool_calls.items():
            yield ErrorEvent(
                error_type="incomplete_tool_call",
                message=f"Tool call {acc.name} was incomplete at stream end",
                recoverable=False,
            )
        self._tool_calls.clear()
    
    def _reset_timing(self) -> None:
        """Reset timing for debounce."""
        self._first_chunk_time = 0
        self._last_chunk_time = 0
    
    def _handle_error(self, error: Exception) -> Iterator[UIEvent]:
        """Convert exception to ErrorEvent."""
        error_type = "unknown"
        message = str(error)
        recoverable = False
        retry_after = None
        
        # Classify error
        error_class = type(error).__name__
        
        if "RateLimit" in error_class or "429" in message:
            error_type = "rate_limit"
            recoverable = True
            # Try to extract retry-after
            import re
            match = re.search(r'retry.after[:\s]+(\d+)', message, re.IGNORECASE)
            if match:
                retry_after = int(match.group(1))
            else:
                retry_after = 60  # Default
        
        elif "Timeout" in error_class or "Connection" in error_class:
            error_type = "network"
            recoverable = True
        
        elif "401" in message or "Unauthorized" in message:
            error_type = "auth"
            recoverable = False
        
        elif "400" in message or "Invalid" in error_class:
            error_type = "invalid_request"
            recoverable = False
        
        yield ErrorEvent(
            error_type=error_type,
            message=message,
            recoverable=recoverable,
            retry_after=retry_after,
        )
```

---

## Task 5: Widgets

### `widgets/code_block.py`

```python
"""
CodeBlock - Syntax-highlighted code with live streaming updates.
"""

from textual.widgets import Static
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text


class CodeBlock(Static):
    """
    Syntax-highlighted code block with streaming support.
    
    Features:
    - Live updates during streaming
    - Line numbers
    - Language indicator
    - Visual distinction between streaming and complete states
    """
    
    code = reactive("", layout=True)
    language = reactive("text")
    is_streaming = reactive(True)
    
    DEFAULT_CSS = """
    CodeBlock {
        margin: 1 0;
        height: auto;
    }
    """
    
    def render(self) -> Panel:
        if not self.code:
            # Empty placeholder during streaming
            content = Text("...", style="dim italic")
        else:
            content = Syntax(
                self.code,
                self.language,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
        
        # Title with language and streaming indicator
        title = self.language
        if self.is_streaming:
            title += " [dim]⋯[/dim]"
        
        # Border style indicates state
        border_style = "dim yellow" if self.is_streaming else "dim green"
        
        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
        )
    
    def append(self, content: str) -> None:
        """Append content during streaming."""
        self.code += content
    
    def finalize(self) -> None:
        """Mark as complete (no longer streaming)."""
        self.is_streaming = False
```

### `widgets/tool_card.py`

```python
"""
ToolCard - Tool execution status with inline approval UI.
"""

from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Vertical
from textual.reactive import reactive
from textual.binding import Binding
from rich.panel import Panel
from rich.text import Text
from typing import Any

from ..events import ToolStatus
from ..messages import ApprovalResponseMessage


class ToolCard(Static):
    """
    Tool execution card with status indicator and approval UI.
    
    Displays:
    - Tool name and status icon
    - Arguments preview
    - Inline approval options (when awaiting approval)
    - Result preview or error (when complete)
    """
    
    status = reactive(ToolStatus.PENDING)
    result_preview = reactive("")
    error_message = reactive("")
    
    # Status display configuration
    STATUS_CONFIG = {
        ToolStatus.PENDING:           ("⏳", "yellow", "Pending"),
        ToolStatus.AWAITING_APPROVAL: ("❓", "cyan",   "Awaiting approval"),
        ToolStatus.APPROVED:          ("▶️",  "blue",   "Approved"),
        ToolStatus.RUNNING:           ("⚙️",  "yellow", "Running"),
        ToolStatus.SUCCESS:           ("✓",  "green",  "Success"),
        ToolStatus.FAILED:            ("✗",  "red",    "Failed"),
        ToolStatus.REJECTED:          ("⊘",  "dim",    "Rejected"),
        ToolStatus.CANCELLED:         ("○",  "dim",    "Cancelled"),
    }
    
    DEFAULT_CSS = """
    ToolCard {
        margin: 1 0;
        height: auto;
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
    
    ToolCard.awaiting {
        border: round cyan;
    }
    """
    
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
        if self.status == ToolStatus.AWAITING_APPROVAL:
            yield ToolApprovalOptions(call_id=self.call_id)
    
    def watch_status(self, new_status: ToolStatus) -> None:
        """Update CSS class when status changes."""
        # Remove old status classes
        self.remove_class("success", "failed", "pending", "awaiting")
        
        # Add new status class
        if new_status == ToolStatus.SUCCESS:
            self.add_class("success")
        elif new_status == ToolStatus.FAILED:
            self.add_class("failed")
        elif new_status == ToolStatus.AWAITING_APPROVAL:
            self.add_class("awaiting")
        elif new_status in (ToolStatus.PENDING, ToolStatus.RUNNING):
            self.add_class("pending")
        
        # Remove approval UI when no longer awaiting
        if new_status != ToolStatus.AWAITING_APPROVAL:
            approval_ui = self.query("ToolApprovalOptions")
            for widget in approval_ui:
                widget.remove()
    
    def render(self) -> Panel:
        icon, color, status_text = self.STATUS_CONFIG.get(
            self.status, 
            ("?", "white", "Unknown")
        )
        
        # Header: icon + tool name
        header = Text()
        header.append(f"{icon} ", style=color)
        header.append(self.name, style="bold")
        
        # Arguments preview
        args_preview = self._format_args_preview()
        
        # Build content
        lines = [header]
        if args_preview:
            lines.append(Text(f"  {args_preview}", style="dim"))
        
        if self.error_message:
            lines.append(Text(f"  Error: {self.error_message}", style="red"))
        elif self.result_preview:
            lines.append(Text(f"  {self.result_preview}", style="dim green"))
        
        content = Text("\n").join(lines)
        
        return Panel(
            content,
            title=status_text,
            title_align="right",
            border_style=color,
            padding=(0, 1),
        )
    
    def _format_args_preview(self) -> str:
        """Format arguments as compact preview."""
        parts = []
        for key, value in list(self.args.items())[:3]:
            if isinstance(value, str):
                if len(value) > 40:
                    value = value[:37] + "..."
                parts.append(f'{key}="{value}"')
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}={value}")
            elif isinstance(value, list):
                parts.append(f"{key}=[{len(value)} items]")
            elif isinstance(value, dict):
                parts.append(f"{key}={{...}}")
        return "  ".join(parts)
    
    def set_result(self, result: Any, duration_ms: int | None = None) -> None:
        """Set successful result."""
        self.status = ToolStatus.SUCCESS
        self.result_preview = self._format_result(result, duration_ms)
    
    def set_error(self, error: str) -> None:
        """Set error state."""
        self.status = ToolStatus.FAILED
        self.error_message = error
    
    def _format_result(self, result: Any, duration_ms: int | None) -> str:
        """Format result for preview."""
        preview = ""
        
        if isinstance(result, str):
            lines = result.count('\n') + 1
            if lines > 1:
                preview = f"({lines} lines)"
            elif len(result) > 60:
                preview = result[:57] + "..."
            else:
                preview = result
        elif isinstance(result, dict):
            preview = f"({len(result)} keys)"
        elif isinstance(result, list):
            preview = f"({len(result)} items)"
        else:
            preview = str(result)[:60]
        
        if duration_ms:
            preview += f" [{duration_ms}ms]"
        
        return preview


class ToolApprovalOptions(Static, can_focus=True):
    """
    Inline approval UI matching Claude Code style.
    
    Shows:
        Do you want to proceed?
        > 1. Yes, execute
          2. Yes, and don't ask again for this tool
          3. No, skip this action
          4. Provide feedback...
        
        ↑↓ to select, Enter to confirm, Esc to cancel
    """
    
    BINDINGS = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("1", "quick_select_1", show=False),
        Binding("2", "quick_select_2", show=False),
        Binding("3", "quick_select_3", show=False),
        Binding("4", "quick_select_4", show=False),
    ]
    
    OPTIONS = [
        ("yes", "Yes, execute"),
        ("yes_all", "Yes, and don't ask again for this tool"),
        ("no", "No, skip this action"),
        ("feedback", "Provide feedback..."),
    ]
    
    selected_index = reactive(0)
    
    DEFAULT_CSS = """
    ToolApprovalOptions {
        height: auto;
        padding: 1;
        background: $surface;
        margin: 1 0;
    }
    
    ToolApprovalOptions:focus {
        border: tall $accent;
    }
    """
    
    def __init__(self, call_id: str, **kwargs):
        super().__init__(**kwargs)
        self.call_id = call_id
    
    def on_mount(self) -> None:
        """Focus on mount."""
        self.focus()
    
    def render(self) -> Text:
        lines = [Text("Do you want to proceed?\n", style="bold")]
        
        for i, (action, label) in enumerate(self.OPTIONS):
            prefix = "> " if i == self.selected_index else "  "
            style = "reverse" if i == self.selected_index else ""
            lines.append(Text(f"{prefix}{i + 1}. {label}\n", style=style))
        
        lines.append(Text("\n↑↓ select  Enter confirm  Esc cancel", style="dim"))
        
        return Text("").join(lines)
    
    def action_move_up(self) -> None:
        self.selected_index = max(0, self.selected_index - 1)
    
    def action_move_down(self) -> None:
        self.selected_index = min(len(self.OPTIONS) - 1, self.selected_index + 1)
    
    def action_select(self) -> None:
        self._submit_selection()
    
    def action_cancel(self) -> None:
        self.post_message(ApprovalResponseMessage(self.call_id, "no"))
    
    def action_quick_select_1(self) -> None:
        self.selected_index = 0
        self._submit_selection()
    
    def action_quick_select_2(self) -> None:
        self.selected_index = 1
        self._submit_selection()
    
    def action_quick_select_3(self) -> None:
        self.selected_index = 2
        self._submit_selection()
    
    def action_quick_select_4(self) -> None:
        self.selected_index = 3
        self._submit_selection()
    
    def _submit_selection(self) -> None:
        action, _ = self.OPTIONS[self.selected_index]
        
        if action == "feedback":
            # TODO: Open inline input for feedback
            # For now, treat as rejection with note
            self.post_message(ApprovalResponseMessage(
                self.call_id, 
                "feedback",
                feedback="User requested changes"
            ))
        else:
            self.post_message(ApprovalResponseMessage(self.call_id, action))
```

### `widgets/thinking.py`

```python
"""
ThinkingBlock - Collapsible thinking/reasoning section.
"""

from textual.widgets import Static
from textual.reactive import reactive
from rich.panel import Panel
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text


class ThinkingBlock(Static):
    """
    Collapsible thinking/reasoning block.
    
    Features:
    - Collapsed by default (don't overwhelm user)
    - Click to expand/collapse
    - Shows preview when collapsed
    - Displays token count when complete
    """
    
    content = reactive("")
    is_complete = reactive(False)
    token_count = reactive(0)
    expanded = reactive(False)
    
    DEFAULT_CSS = """
    ThinkingBlock {
        margin: 1 0;
        height: auto;
    }
    
    ThinkingBlock:hover {
        background: $surface-lighten-1;
    }
    """
    
    def render(self) -> Panel:
        if self.expanded:
            # Full content as markdown
            body = RichMarkdown(self.content) if self.content else Text("...")
        else:
            # Collapsed preview
            preview = self.content[:100].replace("\n", " ").strip()
            if len(self.content) > 100:
                preview += "..."
            body = Text(preview, style="dim italic")
        
        # Build title
        title_parts = ["💭 Thinking"]
        
        if self.is_complete and self.token_count:
            title_parts.append(f"({self.token_count:,} tokens)")
        elif not self.is_complete:
            title_parts.append("...")
        
        if not self.expanded:
            title_parts.append("[dim]click to expand[/dim]")
        
        title = " ".join(title_parts)
        
        return Panel(
            body,
            title=title,
            title_align="left",
            border_style="dim blue",
            padding=(0, 1),
        )
    
    def on_click(self) -> None:
        """Toggle expansion on click."""
        self.expanded = not self.expanded
    
    def append(self, content: str) -> None:
        """Append content during streaming."""
        self.content += content
    
    def finalize(self, token_count: int | None = None) -> None:
        """Mark as complete."""
        self.is_complete = True
        if token_count:
            self.token_count = token_count
```

### `widgets/message.py`

```python
"""
MessageWidget - Container for a conversation message.
"""

from textual.widgets import Static, Markdown
from textual.containers import Vertical
from textual.reactive import reactive
from rich.panel import Panel
from typing import Any

from .code_block import CodeBlock
from .tool_card import ToolCard
from .thinking import ThinkingBlock


class MessageWidget(Vertical):
    """
    Container for a single conversation message.
    
    Holds multiple blocks that are added dynamically as stream events arrive:
    - Markdown (text content)
    - CodeBlock (syntax-highlighted code)
    - ToolCard (tool execution)
    - ThinkingBlock (collapsible reasoning)
    """
    
    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        margin: 1 0;
        padding: 0 1;
    }
    
    MessageWidget.user {
        border-left: thick $primary;
    }
    
    MessageWidget.assistant {
        border-left: thick $secondary;
    }
    
    MessageWidget.system {
        border-left: thick $warning;
        opacity: 0.8;
    }
    """
    
    def __init__(self, role: str, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.add_class(role)
        
        # Track current widgets for updates
        self._blocks: list[Static] = []
        self._current_markdown: Markdown | None = None
        self._current_code: CodeBlock | None = None
        self._current_thinking: ThinkingBlock | None = None
        self._tool_cards: dict[str, ToolCard] = {}
    
    # -------------------------------------------------------------------------
    # Text Content
    # -------------------------------------------------------------------------
    
    def add_text(self, content: str) -> None:
        """
        Append text to current markdown block, or create a new one.
        """
        # If we were in code mode, end it
        self._current_code = None
        
        if self._current_markdown is None:
            self._current_markdown = Markdown("")
            self._blocks.append(self._current_markdown)
            self.mount(self._current_markdown)
        
        # Append content
        current = self._current_markdown.markup or ""
        self._current_markdown.update(current + content)
    
    # -------------------------------------------------------------------------
    # Code Blocks
    # -------------------------------------------------------------------------
    
    def start_code_block(self, language: str) -> CodeBlock:
        """
        Start a new code block.
        
        Returns the CodeBlock widget for live updates.
        """
        # End any current text or code block
        self._current_markdown = None
        if self._current_code:
            self._current_code.finalize()
        
        block = CodeBlock()
        block.language = language
        block.is_streaming = True
        
        self._blocks.append(block)
        self._current_code = block
        self.mount(block)
        
        return block
    
    def append_code(self, content: str) -> None:
        """Append to current code block."""
        if self._current_code:
            self._current_code.append(content)
    
    def end_code_block(self) -> None:
        """Finalize current code block."""
        if self._current_code:
            self._current_code.finalize()
            self._current_code = None
    
    # -------------------------------------------------------------------------
    # Tool Cards
    # -------------------------------------------------------------------------
    
    def add_tool_card(
        self,
        call_id: str,
        name: str,
        args: dict[str, Any],
        requires_approval: bool,
    ) -> ToolCard:
        """
        Add a tool card.
        
        Returns the ToolCard widget for status updates.
        """
        # End text/code mode
        self._current_markdown = None
        self._current_code = None
        
        card = ToolCard(
            call_id=call_id,
            name=name,
            args=args,
            requires_approval=requires_approval,
        )
        
        self._blocks.append(card)
        self._tool_cards[call_id] = card
        self.mount(card)
        
        return card
    
    def get_tool_card(self, call_id: str) -> ToolCard | None:
        """Get a tool card by call ID."""
        return self._tool_cards.get(call_id)
    
    # -------------------------------------------------------------------------
    # Thinking Blocks
    # -------------------------------------------------------------------------
    
    def start_thinking(self) -> ThinkingBlock:
        """
        Start a thinking block.
        
        Returns the ThinkingBlock widget for live updates.
        """
        self._current_markdown = None
        self._current_code = None
        
        block = ThinkingBlock()
        self._blocks.append(block)
        self._current_thinking = block
        self.mount(block)
        
        return block
    
    def append_thinking(self, content: str) -> None:
        """Append to current thinking block."""
        if self._current_thinking:
            self._current_thinking.append(content)
    
    def end_thinking(self, token_count: int | None = None) -> None:
        """Finalize current thinking block."""
        if self._current_thinking:
            self._current_thinking.finalize(token_count)
            self._current_thinking = None
```

### `widgets/status_bar.py`

```python
"""
StatusBar - Bottom status bar with model info, errors, and shortcuts.
"""

from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text
import asyncio


class StatusBar(Static):
    """
    Bottom status bar.
    
    Shows:
    - Current model name
    - Token count (if streaming)
    - Error messages with countdown
    - Keyboard shortcuts
    """
    
    model_name = reactive("claude-3-opus")
    token_count = reactive(0)
    is_streaming = reactive(False)
    error_message = reactive("")
    countdown = reactive(0)
    
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """
    
    def render(self) -> Text:
        parts = []
        
        # Left: Model and tokens
        left = Text()
        left.append(f"📡 {self.model_name}", style="dim")
        
        if self.is_streaming:
            left.append(" | ", style="dim")
            left.append(f"⚡ {self.token_count} tokens", style="yellow")
        
        parts.append(left)
        
        # Center: Error or countdown
        if self.error_message:
            center = Text()
            if self.countdown > 0:
                center.append(f"⏳ {self.error_message} ({self.countdown}s)", style="yellow")
            else:
                center.append(f"⚠️  {self.error_message}", style="red")
            parts.append(center)
        
        # Right: Shortcuts
        right = Text()
        right.append("Ctrl+C ", style="dim")
        right.append("interrupt", style="dim italic")
        right.append(" | ", style="dim")
        right.append("Ctrl+D ", style="dim")
        right.append("quit", style="dim italic")
        
        # Combine with spacing
        result = Text()
        result.append(parts[0])
        
        if len(parts) > 1:
            result.append("  |  ")
            result.append(parts[1])
        
        # Add right-aligned shortcuts (fill with spaces)
        # This is a simplification - proper alignment needs width calculation
        result.append("    ")
        result.append(right)
        
        return result
    
    def show_error(self, message: str, countdown: int = 0) -> None:
        """
        Show error message, optionally with countdown.
        
        If countdown > 0, will auto-decrement every second.
        """
        self.error_message = message
        self.countdown = countdown
        
        if countdown > 0:
            self._start_countdown()
    
    def clear_error(self) -> None:
        """Clear error message."""
        self.error_message = ""
        self.countdown = 0
    
    def _start_countdown(self) -> None:
        """Start countdown timer."""
        async def countdown_task():
            while self.countdown > 0:
                await asyncio.sleep(1)
                self.countdown -= 1
            self.error_message = ""
        
        asyncio.create_task(countdown_task())
    
    def set_streaming(self, is_streaming: bool) -> None:
        """Update streaming state."""
        self.is_streaming = is_streaming
        if not is_streaming:
            self.token_count = 0
    
    def update_tokens(self, count: int) -> None:
        """Update token count."""
        self.token_count = count
```

---

## Task 6: Main App (`app.py`)

```python
"""
CodingAgentApp - Main Textual application.
"""

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import TextArea
from textual.binding import Binding
from typing import TYPE_CHECKING
import asyncio

from .events import (
    UIEvent, StreamStart, StreamEnd,
    TextDelta, CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    ErrorEvent, ToolStatus,
)
from .messages import (
    ApprovalResponseMessage, StreamInterruptMessage, RetryRequestMessage,
)
from .protocol import UIProtocol, ApprovalResult, InterruptSignal, RetrySignal
from .widgets.message import MessageWidget
from .widgets.code_block import CodeBlock
from .widgets.tool_card import ToolCard
from .widgets.thinking import ThinkingBlock
from .widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from ..core.agent import Agent


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
        Binding("ctrl+c", "interrupt", "Interrupt", show=True, priority=True),
        Binding("ctrl+d", "quit", "Quit", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+l", "clear_screen", "Clear", show=False),
    ]
    
    def __init__(self, agent: "Agent", **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self.ui_protocol = UIProtocol()
        
        # Streaming state
        self._is_streaming = False
        self._streaming_task: asyncio.Task | None = None
        self._current_message: MessageWidget | None = None
        self._current_code: CodeBlock | None = None
        self._current_thinking: ThinkingBlock | None = None
        self._tool_cards: dict[str, ToolCard] = {}
        
        # Scroll state
        self._auto_scroll = True
        
        # Last request for retry
        self._last_user_input: str = ""
    
    def compose(self) -> ComposeResult:
        yield ScrollableContainer(id="conversation")
        yield TextArea(id="input", placeholder="Type a message... (Ctrl+D to quit)")
        yield StatusBar(id="status")
    
    async def on_mount(self) -> None:
        """Focus input on start."""
        self.query_one("#input", TextArea).focus()
    
    # -------------------------------------------------------------------------
    # Input Handling
    # -------------------------------------------------------------------------
    
    async def on_text_area_submitted(self, event) -> None:
        """Handle user input submission."""
        input_widget = self.query_one("#input", TextArea)
        user_input = input_widget.text.strip()
        
        if not user_input:
            return
        
        # Clear input and store for potential retry
        input_widget.clear()
        self._last_user_input = user_input
        
        # Add user message to conversation
        await self._add_user_message(user_input)
        
        # Start streaming response
        await self._stream_response(user_input)
    
    async def _add_user_message(self, content: str) -> None:
        """Add user message to conversation."""
        conversation = self.query_one("#conversation", ScrollableContainer)
        user_msg = MessageWidget(role="user")
        user_msg.add_text(content)
        await conversation.mount(user_msg)
        conversation.scroll_end()
    
    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------
    
    async def _stream_response(self, user_input: str) -> None:
        """Stream agent response and render events."""
        self._is_streaming = True
        self.ui_protocol.reset()
        
        status_bar = self.query_one("#status", StatusBar)
        status_bar.set_streaming(True)
        status_bar.clear_error()
        
        conversation = self.query_one("#conversation", ScrollableContainer)
        
        try:
            # Create task for streaming
            self._streaming_task = asyncio.create_task(
                self._process_stream(user_input, conversation)
            )
            await self._streaming_task
        
        except asyncio.CancelledError:
            # User interrupted
            if self._current_message:
                self._current_message.add_text("\n\n[Interrupted]")
        
        finally:
            self._is_streaming = False
            self._streaming_task = None
            self._current_message = None
            self._current_code = None
            self._current_thinking = None
            
            status_bar.set_streaming(False)
            self.query_one("#input", TextArea).focus()
    
    async def _process_stream(
        self, 
        user_input: str, 
        conversation: ScrollableContainer
    ) -> None:
        """Process the event stream from the agent."""
        event_stream = self.agent.stream_response(user_input, self.ui_protocol)
        
        async for event in event_stream:
            await self._handle_event(event, conversation)
            
            # Check for interrupt
            if self.ui_protocol.check_interrupted():
                break
            
            # Auto-scroll if enabled
            if self._auto_scroll:
                conversation.scroll_end()
    
    async def _handle_event(
        self, 
        event: UIEvent, 
        conversation: ScrollableContainer
    ) -> None:
        """Dispatch event to appropriate handler."""
        
        match event:
            # Stream lifecycle
            case StreamStart():
                self._current_message = MessageWidget(role="assistant")
                await conversation.mount(self._current_message)
            
            case StreamEnd(total_tokens=tokens):
                if tokens:
                    status = self.query_one("#status", StatusBar)
                    status.update_tokens(tokens)
            
            # Text content
            case TextDelta(content=text):
                if self._current_message:
                    self._current_message.add_text(text)
            
            # Code blocks
            case CodeBlockStart(language=lang):
                if self._current_message:
                    self._current_code = self._current_message.start_code_block(lang)
            
            case CodeBlockDelta(content=code):
                if self._current_message:
                    self._current_message.append_code(code)
            
            case CodeBlockEnd():
                if self._current_message:
                    self._current_message.end_code_block()
                self._current_code = None
            
            # Tool calls
            case ToolCallStart(call_id=cid, name=name, arguments=args, requires_approval=req):
                if self._current_message:
                    card = self._current_message.add_tool_card(cid, name, args, req)
                    self._tool_cards[cid] = card
                    card.scroll_visible()
            
            case ToolCallStatus(call_id=cid, status=status, message=msg):
                if cid in self._tool_cards:
                    self._tool_cards[cid].status = status
            
            case ToolCallResult(call_id=cid, status=status, result=result, error=err, duration_ms=dur):
                if cid in self._tool_cards:
                    card = self._tool_cards[cid]
                    if status == ToolStatus.SUCCESS:
                        card.set_result(result, dur)
                    elif err:
                        card.set_error(err)
                    else:
                        card.status = status
            
            # Thinking
            case ThinkingStart():
                if self._current_message:
                    self._current_thinking = self._current_message.start_thinking()
            
            case ThinkingDelta(content=text):
                if self._current_message:
                    self._current_message.append_thinking(text)
            
            case ThinkingEnd(token_count=count):
                if self._current_message:
                    self._current_message.end_thinking(count)
                self._current_thinking = None
            
            # Errors
            case ErrorEvent(error_type=etype, message=msg, recoverable=rec, retry_after=retry):
                await self._handle_error(etype, msg, rec, retry)
    
    async def _handle_error(
        self, 
        error_type: str, 
        message: str, 
        recoverable: bool,
        retry_after: int | None
    ) -> None:
        """Handle error events with appropriate recovery."""
        status_bar = self.query_one("#status", StatusBar)
        
        if error_type == "rate_limit" and retry_after:
            # Show countdown and auto-retry
            status_bar.show_error(f"Rate limited: {message}", countdown=retry_after)
            await asyncio.sleep(retry_after)
            status_bar.clear_error()
            
            if recoverable:
                # Retry the last request
                await self._stream_response(self._last_user_input)
        
        elif error_type == "network" and recoverable:
            # Show error and retry with backoff
            status_bar.show_error(f"Network error: {message}")
            await asyncio.sleep(2)  # Simple backoff
            status_bar.clear_error()
            await self._stream_response(self._last_user_input)
        
        else:
            # Non-recoverable: show error, user must manually retry
            status_bar.show_error(message)
            if self._current_message:
                self._current_message.add_text(f"\n\n⚠️ Error: {message}")
    
    # -------------------------------------------------------------------------
    # Message Handlers
    # -------------------------------------------------------------------------
    
    def on_approval_response_message(self, message: ApprovalResponseMessage) -> None:
        """Handle approval response from ToolApprovalOptions."""
        approved = message.action in ("yes", "yes_all")
        
        self.ui_protocol.submit_action(ApprovalResult(
            call_id=message.call_id,
            approved=approved,
            auto_approve_future=(message.action == "yes_all"),
            feedback=message.feedback,
        ))
        
        # Update tool card status
        if message.call_id in self._tool_cards:
            card = self._tool_cards[message.call_id]
            if approved:
                card.status = ToolStatus.APPROVED
            else:
                card.status = ToolStatus.REJECTED
    
    def on_stream_interrupt_message(self, message: StreamInterruptMessage) -> None:
        """Handle stream interrupt request."""
        self.ui_protocol.submit_action(InterruptSignal())
        if self._streaming_task:
            self._streaming_task.cancel()
    
    def on_retry_request_message(self, message: RetryRequestMessage) -> None:
        """Handle retry request."""
        self.ui_protocol.submit_action(RetrySignal())
    
    # -------------------------------------------------------------------------
    # Scroll Handling
    # -------------------------------------------------------------------------
    
    def on_scroll(self) -> None:
        """Detect user scrolling to manage auto-scroll."""
        conversation = self.query_one("#conversation", ScrollableContainer)
        
        # Disable auto-scroll if user scrolled up
        at_bottom = conversation.scroll_offset.y >= conversation.max_scroll_y - 10
        self._auto_scroll = at_bottom
    
    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    
    def action_interrupt(self) -> None:
        """Handle Ctrl+C - interrupt current stream."""
        if self._is_streaming:
            self.post_message(StreamInterruptMessage())
        else:
            # If not streaming, exit app (standard Ctrl+C behavior)
            self.exit()
    
    def action_cancel(self) -> None:
        """Handle Escape - cancel current operation."""
        # Could be used for cancelling approval dialogs, etc.
        pass
    
    def action_clear_screen(self) -> None:
        """Handle Ctrl+L - clear conversation."""
        conversation = self.query_one("#conversation", ScrollableContainer)
        conversation.remove_children()
```

---

## Task 7: Styles (`styles.tcss`)

```css
/* Main layout */
Screen {
    layout: grid;
    grid-size: 1;
    grid-rows: 1fr auto auto;
}

/* Conversation area */
#conversation {
    height: 100%;
    overflow-y: auto;
    scrollbar-gutter: stable;
    padding: 1 2;
}

/* Input area */
#input {
    height: auto;
    min-height: 3;
    max-height: 10;
    margin: 0 1 1 1;
    border: tall $primary;
}

#input:focus {
    border: tall $accent;
}

/* Status bar is styled in widget */

/* Message styling */
MessageWidget {
    height: auto;
    margin: 1 0;
    padding: 0 1;
}

MessageWidget.user {
    border-left: thick $primary;
    background: $surface;
}

MessageWidget.assistant {
    border-left: thick $secondary;
}

MessageWidget.system {
    border-left: thick $warning;
    opacity: 0.8;
}

/* Code blocks */
CodeBlock {
    height: auto;
    margin: 1 0;
}

/* Tool cards */
ToolCard {
    height: auto;
    margin: 1 0;
}

/* Thinking blocks */
ThinkingBlock {
    height: auto;
    margin: 1 0;
}

ThinkingBlock:hover {
    background: $surface-lighten-1;
}

/* Approval UI */
ToolApprovalOptions {
    height: auto;
    padding: 1;
    margin: 1 0;
    background: $surface;
    border: tall $accent;
}

ToolApprovalOptions:focus {
    border: tall $accent-lighten-1;
}
```

---

## Task 8: Agent Integration

Minimal changes needed in your existing agent:

```python
# src/core/agent.py

from src.ui.stream_processor import StreamProcessor
from src.ui.events import (
    UIEvent, ToolCallStart, ToolCallStatus, ToolCallResult, ToolStatus
)
from src.ui.protocol import UIProtocol

class Agent:
    """
    Existing agent with minimal changes for new UI.
    """
    
    def __init__(self, ...):
        # Your existing init
        self.processor = StreamProcessor(
            idle_timeout_ms=50,
            max_latency_ms=150,
            approval_checker=self._needs_approval,
        )
    
    def _needs_approval(self, tool_name: str) -> bool:
        """Check if tool requires user approval."""
        # Customize based on your tool risk levels
        dangerous_tools = {"write_file", "bash", "delete_file", "git_push"}
        return tool_name in dangerous_tools
    
    async def stream_response(
        self, 
        user_input: str, 
        ui: UIProtocol
    ) -> AsyncIterator[UIEvent]:
        """
        Stream response to UI.
        
        This is the main integration point.
        """
        # Build messages (your existing logic)
        messages = self._build_messages(user_input)
        
        # Get raw LLM stream
        raw_stream = self.llm.stream(messages, tools=self.tools)
        
        # Process through StreamProcessor
        async for event in self.processor.process(raw_stream):
            yield event
            
            # Handle tool execution
            if isinstance(event, ToolCallStart):
                # Wait for approval if required
                if event.requires_approval:
                    yield ToolCallStatus(event.call_id, ToolStatus.AWAITING_APPROVAL)
                    
                    result = await ui.wait_for_approval(
                        event.call_id,
                        event.name,
                    )
                    
                    if not result.approved:
                        yield ToolCallStatus(event.call_id, ToolStatus.REJECTED)
                        continue
                    
                    yield ToolCallStatus(event.call_id, ToolStatus.APPROVED)
                
                # Execute tool
                yield ToolCallStatus(event.call_id, ToolStatus.RUNNING)
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

## Task 9: Entry Point

```python
# src/cli.py

import asyncio
from src.ui.app import CodingAgentApp
from src.core.agent import Agent


def main():
    """Main entry point."""
    agent = Agent()  # Your existing agent init
    app = CodingAgentApp(agent=agent)
    app.run()


if __name__ == "__main__":
    main()
```

---

## Task 10: Tests

Create comprehensive tests for StreamProcessor (the critical path):

```python
# tests/ui/test_stream_processor.py

import pytest
import json
from unittest.mock import MagicMock
from src.ui.stream_processor import StreamProcessor
from src.ui.events import (
    StreamStart, StreamEnd, TextDelta,
    CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolStatus,
)


async def async_iter(items):
    """Helper to create async iterator from list."""
    for item in items:
        yield item


def make_chunk(content: str = None, tool_calls: list = None):
    """Create mock OpenAI chunk."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = content
    chunk.choices[0].delta.tool_calls = tool_calls
    return chunk


class TestToolCallAccumulation:
    """Test that tool calls are properly accumulated."""
    
    @pytest.mark.asyncio
    async def test_complete_tool_call_emits_event(self):
        """Complete tool call should emit ToolCallStart."""
        processor = StreamProcessor()
        
        # Simulate streaming tool call in parts
        tc1 = MagicMock()
        tc1.index = 0
        tc1.function = MagicMock(name="read", arguments='{"path":')
        
        tc2 = MagicMock()
        tc2.index = 0
        tc2.function = MagicMock(name="", arguments=' "config.py"}')
        
        chunks = [
            make_chunk(tool_calls=[tc1]),
            make_chunk(tool_calls=[tc2]),
        ]
        
        events = []
        async for event in processor.process(async_iter(chunks)):
            events.append(event)
        
        # Should have StreamStart, one ToolCallStart, StreamEnd
        tool_calls = [e for e in events if isinstance(e, ToolCallStart)]
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read"
        assert tool_calls[0].arguments == {"path": "config.py"}
    
    @pytest.mark.asyncio
    async def test_incomplete_json_does_not_emit(self):
        """Incomplete JSON should not emit ToolCallStart."""
        processor = StreamProcessor()
        
        # Only partial JSON
        tc = MagicMock()
        tc.index = 0
        tc.function = MagicMock(name="read", arguments='{"path": "conf')
        
        chunks = [make_chunk(tool_calls=[tc])]
        
        events = []
        async for event in processor.process(async_iter(chunks)):
            events.append(event)
        
        # Should not have ToolCallStart (incomplete)
        tool_calls = [e for e in events if isinstance(e, ToolCallStart)]
        assert len(tool_calls) == 0


class TestCodeFenceDetection:
    """Test code fence boundary detection."""
    
    @pytest.mark.asyncio
    async def test_simple_code_block(self):
        """Simple code block should emit proper events."""
        processor = StreamProcessor()
        
        chunks = [
            make_chunk(content="Here's code:\n"),
            make_chunk(content="```python\n"),
            make_chunk(content="print('hello')\n"),
            make_chunk(content="```\n"),
            make_chunk(content="That's it."),
        ]
        
        events = []
        async for event in processor.process(async_iter(chunks)):
            events.append(event)
        
        # Check event sequence
        event_types = [type(e).__name__ for e in events]
        
        assert "CodeBlockStart" in event_types
        assert "CodeBlockDelta" in event_types
        assert "CodeBlockEnd" in event_types
        
        # Check language
        start = next(e for e in events if isinstance(e, CodeBlockStart))
        assert start.language == "python"
    
    @pytest.mark.asyncio
    async def test_fence_split_across_chunks(self):
        """Fence split across chunks should still work."""
        processor = StreamProcessor()
        
        chunks = [
            make_chunk(content="Code:\n``"),
            make_chunk(content="`python\nprint('hi')\n"),
            make_chunk(content="``"),
            make_chunk(content="`\nDone."),
        ]
        
        events = []
        async for event in processor.process(async_iter(chunks)):
            events.append(event)
        
        event_types = [type(e).__name__ for e in events]
        assert "CodeBlockStart" in event_types
        assert "CodeBlockEnd" in event_types
    
    @pytest.mark.asyncio
    async def test_backticks_inside_code_block(self):
        """Backticks inside code should not close block."""
        processor = StreamProcessor()
        
        chunks = [
            make_chunk(content="```python\n"),
            make_chunk(content="s = '```'\n"),  # Backticks in string
            make_chunk(content="print(s)\n"),
            make_chunk(content="```\n"),
        ]
        
        events = []
        async for event in processor.process(async_iter(chunks)):
            events.append(event)
        
        # Should have exactly one CodeBlockStart and one CodeBlockEnd
        starts = [e for e in events if isinstance(e, CodeBlockStart)]
        ends = [e for e in events if isinstance(e, CodeBlockEnd)]
        
        assert len(starts) == 1
        assert len(ends) == 1


class TestDebouncing:
    """Test text debouncing behavior."""
    
    @pytest.mark.asyncio
    async def test_flushes_on_newline(self):
        """Should flush on natural breaks (newlines)."""
        processor = StreamProcessor(idle_timeout_ms=50, max_latency_ms=150)
        
        chunks = [
            make_chunk(content="Hello "),
            make_chunk(content="world\n"),  # Newline = flush
            make_chunk(content="More text"),
        ]
        
        events = []
        async for event in processor.process(async_iter(chunks)):
            if isinstance(event, TextDelta):
                events.append(event)
        
        # Should have at least 2 TextDeltas (flushed on newline + end)
        assert len(events) >= 2
        
        # First should end with newline
        assert events[0].content.endswith('\n')
```

---

## Implementation Order

1. **events.py** - Define the contract (10 min)
2. **messages.py** - Internal Textual messages (5 min)
3. **protocol.py** - UI ↔ Agent coordination (15 min)
4. **stream_processor.py** - Core state machine (1-2 hours) ⚠️ Most complex
5. **tests/test_stream_processor.py** - Tests first for critical path (30 min)
6. **widgets/** - Build widgets one at a time (1 hour total)
   - code_block.py (simple)
   - thinking.py (simple)
   - tool_card.py (medium - has approval UI)
   - message.py (medium - container logic)
   - status_bar.py (simple)
7. **app.py** - Wire everything together (30 min)
8. **styles.tcss** - Polish (15 min)
9. **Agent integration** - Minimal changes (15 min)
10. **End-to-end testing** - Verify flow (30 min)

---

## Dependencies

```toml
# pyproject.toml
[project]
dependencies = [
    "textual>=0.50.0",
    "rich>=13.0.0",
    "openai>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
]
```

---

## Key Reminders

1. **Never leak raw JSON** - StreamProcessor accumulates until valid
2. **Typed events, not strings** - UI never parses text
3. **Decoupled coordination** - Async queues, not shared state
4. **Test StreamProcessor thoroughly** - It's the critical path
5. **Production quality** - Error handling, edge cases, recovery
