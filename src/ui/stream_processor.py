"""
Stream Processor - State machine for LLM stream -> UIEvent transformation.

This is the critical path for streaming UX. It must:
1. Never leak raw JSON to the UI
2. Handle code fence edge cases
3. Debounce text for smooth rendering
4. Emit proper error events

Complexity: HIGH - extensive unit tests required.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import AsyncIterator, Iterator, Callable, Any, Optional
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
    """
    Accumulates partial tool call data until complete.

    OpenAI streams tool calls incrementally:
    - First chunk might have partial function name
    - Subsequent chunks have partial JSON arguments
    - We must wait until JSON is valid before emitting
    """

    index: int
    id: str = ""            # Tool call ID from API
    name: str = ""
    arguments: str = ""

    def is_complete(self) -> bool:
        """
        Check if we have valid, complete JSON arguments.

        Returns True only when:
        1. We have a non-empty name
        2. We have non-empty arguments
        3. Arguments parse as valid JSON
        """
        if not self.name or not self.arguments:
            return False
        try:
            json.loads(self.arguments)
            return True
        except json.JSONDecodeError:
            return False

    def parse_arguments(self) -> dict:
        """
        Parse arguments JSON.

        IMPORTANT: Call only when is_complete() returns True.
        """
        return json.loads(self.arguments)


class StreamProcessor:
    """
    Transforms raw LLM stream chunks into typed UI events.

    Features:
    - Hybrid debouncing (idle-based + max latency cap)
    - Code fence detection with edge case handling
    - Tool call accumulation (no raw JSON leaks)
    - Thinking block detection
    - Error capture and classification

    Usage:
        processor = StreamProcessor()
        async for event in processor.process(raw_stream):
            # event is a typed UIEvent
            match event:
                case TextDelta(content=text):
                    print(text)
                case ToolCallStart(name=name, arguments=args):
                    execute_tool(name, args)
    """

    # Code fence patterns
    # Opening: ```language or just ``` (with optional newline)
    FENCE_OPEN_PATTERN = re.compile(r'```(\w*)\s*\n?')
    # Closing: ``` on its own line (preceded by newline, followed by newline or end)
    FENCE_CLOSE_PATTERN = re.compile(r'\n```\s*(?:\n|$)')

    # Thinking block patterns (Claude's extended thinking format)
    THINKING_START_PATTERN = re.compile(r'<thinking>\s*')
    THINKING_END_PATTERN = re.compile(r'\s*</thinking>')

    # Alternative thinking patterns (for other models)
    ALT_THINKING_START = re.compile(r'<reasoning>\s*')
    ALT_THINKING_END = re.compile(r'\s*</reasoning>')

    def __init__(
        self,
        idle_timeout_ms: int = 50,
        max_latency_ms: int = 150,
        approval_checker: Optional[Callable[[str], bool]] = None,
    ):
        """
        Initialize StreamProcessor.

        Args:
            idle_timeout_ms: Flush text buffer after this much idle time
            max_latency_ms: Force flush after this much time (prevents UI starvation)
            approval_checker: Function to check if tool requires approval.
                             Signature: (tool_name: str) -> bool
                             Default: all tools require approval
        """
        self.idle_timeout = idle_timeout_ms / 1000
        self.max_latency = max_latency_ms / 1000
        self.approval_checker = approval_checker or (lambda name: True)

        # State machine
        self._state = StreamState.IDLE

        # Content buffers
        self._text_buffer = ""
        self._code_buffer = ""
        self._code_language = ""
        self._thinking_buffer = ""
        self._thinking_token_count = 0

        # Tool call accumulation (index -> accumulator)
        self._tool_calls: dict[int, ToolCallAccumulator] = {}

        # Track emitted tool call IDs to avoid duplicates
        self._emitted_tool_calls: set[str] = set()

        # Timing for debounce
        self._first_chunk_time: float = 0
        self._last_chunk_time: float = 0

        # Partial fence detection buffer
        self._potential_fence = ""

        # Statistics
        self._total_chunks = 0
        self._total_tokens_estimate = 0

    def reset(self) -> None:
        """Reset processor state for a new stream."""
        self._state = StreamState.IDLE
        self._text_buffer = ""
        self._code_buffer = ""
        self._code_language = ""
        self._thinking_buffer = ""
        self._thinking_token_count = 0
        self._tool_calls.clear()
        self._emitted_tool_calls.clear()
        self._first_chunk_time = 0
        self._last_chunk_time = 0
        self._potential_fence = ""
        self._total_chunks = 0
        self._total_tokens_estimate = 0

    async def process(
        self,
        raw_stream: AsyncIterator[Any],
    ) -> AsyncIterator[UIEvent]:
        """
        Main processing loop.

        Consumes raw LLM chunks (OpenAI format), yields typed UIEvents.

        Args:
            raw_stream: Async iterator yielding OpenAI-style chat completion chunks

        Yields:
            UIEvent instances (StreamStart, TextDelta, ToolCallStart, etc.)
        """
        self.reset()
        yield StreamStart()
        self._state = StreamState.TEXT

        start_time = time.monotonic()

        try:
            async for chunk in raw_stream:
                self._total_chunks += 1

                # Process different chunk formats
                async for event in self._process_chunk(chunk):
                    yield event

            # Flush remaining buffers
            async for event in self._flush_all():
                yield event

            duration_ms = int((time.monotonic() - start_time) * 1000)
            yield StreamEnd(
                total_tokens=self._total_tokens_estimate if self._total_tokens_estimate > 0 else None,
                duration_ms=duration_ms
            )

        except asyncio.CancelledError:
            # Stream was interrupted - flush what we have and re-raise
            async for event in self._flush_all():
                yield event
            raise

        except Exception as e:
            # Convert exception to error event
            for event in self._handle_error(e):
                yield event

    async def _process_chunk(self, chunk: Any) -> AsyncIterator[UIEvent]:
        """
        Process a single chunk from the LLM stream.

        Handles both OpenAI format and raw dict format.
        """
        # Handle OpenAI SDK response objects
        if hasattr(chunk, 'choices') and chunk.choices:
            delta = chunk.choices[0].delta

            # Process tool calls
            if hasattr(delta, 'tool_calls') and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    async for event in self._accumulate_tool_call(tc_delta):
                        yield event

            # Process content
            if hasattr(delta, 'content') and delta.content:
                async for event in self._process_content(delta.content):
                    yield event

            # Track usage if available
            if hasattr(chunk, 'usage') and chunk.usage:
                if hasattr(chunk.usage, 'completion_tokens'):
                    self._total_tokens_estimate = chunk.usage.completion_tokens

        # Handle raw dict format (for testing or other backends)
        elif isinstance(chunk, dict):
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})

                # Process tool calls
                if 'tool_calls' in delta:
                    for tc_delta in delta['tool_calls']:
                        async for event in self._accumulate_tool_call_dict(tc_delta):
                            yield event

                # Process content
                if 'content' in delta and delta['content']:
                    async for event in self._process_content(delta['content']):
                        yield event

    async def _accumulate_tool_call(self, delta: Any) -> AsyncIterator[UIEvent]:
        """
        Accumulate tool call deltas until we have complete, valid JSON.

        OpenAI streams tool calls as:
        - delta.index: which tool call (0, 1, 2...)
        - delta.id: unique ID for this tool call
        - delta.function.name: streamed incrementally
        - delta.function.arguments: streamed as partial JSON
        """
        idx = delta.index if hasattr(delta, 'index') else 0

        # Get or create accumulator
        if idx not in self._tool_calls:
            self._tool_calls[idx] = ToolCallAccumulator(index=idx)

        acc = self._tool_calls[idx]

        # Accumulate ID
        if hasattr(delta, 'id') and delta.id:
            acc.id = delta.id

        # Accumulate function name and arguments
        if hasattr(delta, 'function') and delta.function:
            if hasattr(delta.function, 'name') and delta.function.name:
                acc.name += delta.function.name
            if hasattr(delta.function, 'arguments') and delta.function.arguments:
                acc.arguments += delta.function.arguments

        # Check if complete and not yet emitted
        call_id = acc.id or f"tool-{idx}"
        if acc.is_complete() and call_id not in self._emitted_tool_calls:
            try:
                args = acc.parse_arguments()
                requires_approval = self.approval_checker(acc.name)

                yield ToolCallStart(
                    call_id=call_id,
                    name=acc.name,
                    arguments=args,
                    requires_approval=requires_approval,
                )

                self._emitted_tool_calls.add(call_id)
                del self._tool_calls[idx]

            except json.JSONDecodeError:
                # Still not valid JSON, wait for more data
                pass

    async def _accumulate_tool_call_dict(self, tc_delta: dict) -> AsyncIterator[UIEvent]:
        """Accumulate tool call from dict format (for testing)."""
        idx = tc_delta.get('index', 0)

        if idx not in self._tool_calls:
            self._tool_calls[idx] = ToolCallAccumulator(index=idx)

        acc = self._tool_calls[idx]

        if 'id' in tc_delta:
            acc.id = tc_delta['id']

        if 'function' in tc_delta:
            func = tc_delta['function']
            if 'name' in func and func['name']:
                acc.name += func['name']
            if 'arguments' in func and func['arguments']:
                acc.arguments += func['arguments']

        call_id = acc.id or f"tool-{idx}"
        if acc.is_complete() and call_id not in self._emitted_tool_calls:
            try:
                args = acc.parse_arguments()
                requires_approval = self.approval_checker(acc.name)

                yield ToolCallStart(
                    call_id=call_id,
                    name=acc.name,
                    arguments=args,
                    requires_approval=requires_approval,
                )

                self._emitted_tool_calls.add(call_id)
                del self._tool_calls[idx]

            except json.JSONDecodeError:
                pass

    async def _process_content(self, content: str) -> AsyncIterator[UIEvent]:
        """
        Process text content with state machine transitions.

        Handles:
        - Normal text -> accumulate in buffer
        - Code fence start -> transition to CODE_BLOCK
        - Code fence end -> transition back to TEXT
        - Thinking markers -> transition to/from THINKING
        """
        self._update_timing()

        # Estimate tokens (rough: ~4 chars per token)
        self._total_tokens_estimate += len(content) // 4

        # Route to appropriate handler based on state
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
            self._thinking_token_count += len(content.split())  # Rough word count
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
        3. Flush if buffer is getting large
        """
        if not self._text_buffer:
            return False

        now = time.monotonic()

        # Natural break: ends with newline
        if self._text_buffer.endswith('\n'):
            return True

        # Natural break: ends with sentence-ending punctuation + space
        if self._text_buffer.rstrip().endswith(('.', '!', '?', ':')):
            return True

        # Max latency exceeded
        if self._first_chunk_time and (now - self._first_chunk_time) >= self.max_latency:
            return True

        # Buffer getting large (prevent memory issues)
        if len(self._text_buffer) > 500:
            return True

        return False

    async def _check_transitions_from_text(self) -> AsyncIterator[UIEvent]:
        """
        Check for state transitions while in TEXT state.

        Handles:
        - ```language -> CODE_BLOCK
        - <thinking> -> THINKING
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

        # Check for thinking start (Claude format)
        match = self.THINKING_START_PATTERN.search(self._text_buffer)
        if not match:
            # Try alternative format
            match = self.ALT_THINKING_START.search(self._text_buffer)

        if match:
            # Flush text before thinking
            before = self._text_buffer[:match.start()]
            if before:
                yield TextDelta(content=before)

            self._state = StreamState.THINKING
            yield ThinkingStart()

            self._thinking_buffer = self._text_buffer[match.end():]
            self._text_buffer = ""
            self._thinking_token_count = 0
            self._reset_timing()
            return

    async def _check_code_fence_close(self) -> AsyncIterator[UIEvent]:
        """
        Check for closing code fence.

        Handles edge cases:
        - Fence split across chunks
        - Backticks inside code (in strings)
        - Multiple code blocks
        """
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
            # No closing fence yet - emit buffered code but keep potential fence chars
            safe_to_emit = self._code_buffer

            # Don't emit if buffer ends with potential fence start
            # This handles the case where ``` is split across chunks
            if safe_to_emit.endswith('\n`'):
                safe_to_emit = safe_to_emit[:-2]
                self._code_buffer = '\n`'
            elif safe_to_emit.endswith('\n``'):
                safe_to_emit = safe_to_emit[:-3]
                self._code_buffer = '\n``'
            elif safe_to_emit.endswith('\n```'):
                # This might be the closing fence, wait for more
                return
            elif safe_to_emit.endswith('`'):
                # Single backtick at end - might be start of fence
                safe_to_emit = safe_to_emit[:-1]
                self._code_buffer = '`'
            elif safe_to_emit.endswith('``'):
                safe_to_emit = safe_to_emit[:-2]
                self._code_buffer = '``'
            else:
                self._code_buffer = ""

            if safe_to_emit:
                yield CodeBlockDelta(content=safe_to_emit)

    async def _check_thinking_end(self) -> AsyncIterator[UIEvent]:
        """Check for thinking block end."""
        # Try both thinking formats
        match = self.THINKING_END_PATTERN.search(self._thinking_buffer)
        if not match:
            match = self.ALT_THINKING_END.search(self._thinking_buffer)

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

            # Check for new transitions
            async for event in self._check_transitions_from_text():
                yield event
        else:
            # Emit accumulated thinking content periodically to show progress
            if len(self._thinking_buffer) > 200:
                yield ThinkingDelta(content=self._thinking_buffer)
                self._thinking_buffer = ""

    async def _flush_text(self) -> AsyncIterator[UIEvent]:
        """Flush text buffer as TextDelta."""
        if self._text_buffer:
            # Don't flush if buffer might contain partial fence
            # Check for potential code fence at end
            stripped = self._text_buffer.rstrip()
            if stripped.endswith('`') and not stripped.endswith('```'):
                # Wait for more content to determine if it's a fence
                return
            if stripped.endswith('``'):
                return

            # Check for potential thinking tag at end
            if '<' in self._text_buffer[-20:]:
                # Might be start of <thinking> tag, wait
                if self._text_buffer.rstrip().endswith('<'):
                    return
                if '<t' in self._text_buffer[-15:] or '<r' in self._text_buffer[-15:]:
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
                message=f"Tool call '{acc.name}' was incomplete at stream end (index={idx})",
                recoverable=False,
            )
        self._tool_calls.clear()

    def _reset_timing(self) -> None:
        """Reset timing for debounce."""
        self._first_chunk_time = 0
        self._last_chunk_time = 0

    def _handle_error(self, error: Exception) -> Iterator[UIEvent]:
        """
        Convert exception to ErrorEvent with classification.

        Classifies errors for appropriate UI handling:
        - rate_limit: Show countdown, auto-retry
        - network: Show retry button
        - auth: Show "check API key" message
        - invalid_request: Show error, no retry
        """
        error_type = "unknown"
        message = str(error)
        recoverable = False
        retry_after = None

        # Get error class name for classification
        error_class = type(error).__name__
        error_str = str(error).lower()

        # Rate limit errors
        if "ratelimit" in error_class.lower() or "429" in message or "rate" in error_str:
            error_type = "rate_limit"
            recoverable = True
            # Try to extract retry-after value
            match = re.search(r'retry.?after[:\s]+(\d+)', message, re.IGNORECASE)
            if match:
                retry_after = int(match.group(1))
            else:
                retry_after = 60  # Default

        # Network/connection errors
        elif any(x in error_class.lower() for x in ["timeout", "connection", "network"]):
            error_type = "network"
            recoverable = True

        elif any(x in error_str for x in ["timeout", "connection", "network", "unreachable"]):
            error_type = "network"
            recoverable = True

        # Authentication errors
        elif "401" in message or "unauthorized" in error_str or "auth" in error_str:
            error_type = "auth"
            recoverable = False

        # Invalid request errors
        elif "400" in message or "invalid" in error_str or "bad request" in error_str:
            error_type = "invalid_request"
            recoverable = False

        # API errors (500, etc.)
        elif any(x in message for x in ["500", "502", "503", "504"]):
            error_type = "api_error"
            recoverable = True
            retry_after = 5  # Short retry for server errors

        yield ErrorEvent(
            error_type=error_type,
            message=message,
            recoverable=recoverable,
            retry_after=retry_after,
        )


# Export
__all__ = [
    'StreamState',
    'ToolCallAccumulator',
    'StreamProcessor',
]
