"""
Comprehensive tests for StreamProcessor.

These tests cover:
1. Tool call accumulation (no raw JSON leaks)
2. Code fence detection (edge cases)
3. Thinking block handling
4. Debouncing behavior
5. Error handling
6. State transitions
"""

import pytest
import json
from unittest.mock import MagicMock
from typing import AsyncIterator, Any

from src.ui.stream_processor import StreamProcessor, StreamState, ToolCallAccumulator
from src.ui.events import (
    StreamStart, StreamEnd, TextDelta,
    CodeBlockStart, CodeBlockDelta, CodeBlockEnd,
    ToolCallStart, ToolCallStatus, ToolCallResult,
    ThinkingStart, ThinkingDelta, ThinkingEnd,
    ErrorEvent, ToolStatus,
)


# =============================================================================
# Test Helpers
# =============================================================================

async def async_iter(items: list) -> AsyncIterator[Any]:
    """Helper to create async iterator from list."""
    for item in items:
        yield item


def make_content_chunk(content: str) -> dict:
    """Create a mock chunk with text content."""
    return {
        'choices': [{
            'delta': {
                'content': content
            }
        }]
    }


def make_tool_chunk(index: int, tool_id: str = None, name: str = None, arguments: str = None) -> dict:
    """Create a mock chunk with tool call delta."""
    tc = {'index': index}
    if tool_id:
        tc['id'] = tool_id
    if name or arguments:
        tc['function'] = {}
        if name:
            tc['function']['name'] = name
        if arguments:
            tc['function']['arguments'] = arguments

    return {
        'choices': [{
            'delta': {
                'tool_calls': [tc]
            }
        }]
    }


async def collect_events(processor: StreamProcessor, chunks: list) -> list:
    """Collect all events from processing chunks."""
    events = []
    async for event in processor.process(async_iter(chunks)):
        events.append(event)
    return events


def filter_events(events: list, event_type: type) -> list:
    """Filter events by type."""
    return [e for e in events if isinstance(e, event_type)]


def get_event_types(events: list) -> list[str]:
    """Get list of event type names."""
    return [type(e).__name__ for e in events]


# =============================================================================
# ToolCallAccumulator Tests
# =============================================================================

class TestToolCallAccumulator:
    """Tests for ToolCallAccumulator helper class."""

    def test_empty_accumulator_not_complete(self):
        """Empty accumulator should not be complete."""
        acc = ToolCallAccumulator(index=0)
        assert acc.is_complete() is False

    def test_name_only_not_complete(self):
        """Name without arguments should not be complete."""
        acc = ToolCallAccumulator(index=0, name="read_file")
        assert acc.is_complete() is False

    def test_partial_json_not_complete(self):
        """Partial JSON arguments should not be complete."""
        acc = ToolCallAccumulator(index=0, name="read_file", arguments='{"path": "con')
        assert acc.is_complete() is False

    def test_complete_json_is_complete(self):
        """Valid JSON arguments should be complete."""
        acc = ToolCallAccumulator(index=0, name="read_file", arguments='{"path": "config.py"}')
        assert acc.is_complete() is True

    def test_parse_arguments(self):
        """Should correctly parse JSON arguments."""
        acc = ToolCallAccumulator(
            index=0,
            name="write_file",
            arguments='{"path": "test.py", "content": "print(1)"}'
        )
        args = acc.parse_arguments()
        assert args == {"path": "test.py", "content": "print(1)"}

    def test_empty_object_is_complete(self):
        """Empty JSON object {} should be complete."""
        acc = ToolCallAccumulator(index=0, name="list_files", arguments='{}')
        assert acc.is_complete() is True


# =============================================================================
# Tool Call Accumulation Tests
# =============================================================================

class TestToolCallAccumulation:
    """Test that tool calls are properly accumulated before emission."""

    @pytest.mark.asyncio
    async def test_complete_tool_call_emits_event(self):
        """Complete tool call should emit ToolCallStart event."""
        processor = StreamProcessor()

        chunks = [
            make_tool_chunk(0, tool_id="call_1", name="read_file", arguments='{"path": "test.py"}'),
        ]

        events = await collect_events(processor, chunks)
        tool_calls = filter_events(events, ToolCallStart)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].arguments == {"path": "test.py"}
        assert tool_calls[0].call_id == "call_1"

    @pytest.mark.asyncio
    async def test_streamed_tool_call_accumulates(self):
        """Tool call streamed in parts should accumulate before emission."""
        processor = StreamProcessor()

        # Simulate streaming: name first, then arguments in parts
        chunks = [
            make_tool_chunk(0, tool_id="call_1", name="read"),
            make_tool_chunk(0, name="_file"),
            make_tool_chunk(0, arguments='{"pa'),
            make_tool_chunk(0, arguments='th": '),
            make_tool_chunk(0, arguments='"config.py"}'),
        ]

        events = await collect_events(processor, chunks)
        tool_calls = filter_events(events, ToolCallStart)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].arguments == {"path": "config.py"}

    @pytest.mark.asyncio
    async def test_incomplete_json_does_not_emit(self):
        """Incomplete JSON should not emit ToolCallStart."""
        processor = StreamProcessor()

        # Only partial JSON, never completed
        chunks = [
            make_tool_chunk(0, tool_id="call_1", name="read_file", arguments='{"path": "conf'),
        ]

        events = await collect_events(processor, chunks)
        tool_calls = filter_events(events, ToolCallStart)

        # Should not emit tool call (incomplete)
        assert len(tool_calls) == 0

        # Should emit error about incomplete tool call
        errors = filter_events(events, ErrorEvent)
        assert len(errors) == 1
        assert errors[0].error_type == "incomplete_tool_call"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        """Multiple tool calls should all be accumulated correctly."""
        processor = StreamProcessor()

        chunks = [
            make_tool_chunk(0, tool_id="call_1", name="read_file", arguments='{"path": "a.py"}'),
            make_tool_chunk(1, tool_id="call_2", name="read_file", arguments='{"path": "b.py"}'),
        ]

        events = await collect_events(processor, chunks)
        tool_calls = filter_events(events, ToolCallStart)

        assert len(tool_calls) == 2
        assert tool_calls[0].call_id == "call_1"
        assert tool_calls[1].call_id == "call_2"

    @pytest.mark.asyncio
    async def test_no_duplicate_emissions(self):
        """Same tool call should not be emitted twice."""
        processor = StreamProcessor()

        # Same tool call ID appears multiple times (simulating API quirk)
        chunks = [
            make_tool_chunk(0, tool_id="call_1", name="read_file", arguments='{"path": "test.py"}'),
            make_tool_chunk(0, arguments=''),  # Additional delta with same index
        ]

        events = await collect_events(processor, chunks)
        tool_calls = filter_events(events, ToolCallStart)

        assert len(tool_calls) == 1

    @pytest.mark.asyncio
    async def test_approval_checker_integration(self):
        """Approval checker should be called for each tool call."""
        approvals = []

        def checker(name: str) -> bool:
            approvals.append(name)
            return name == "write_file"  # Only write_file needs approval

        processor = StreamProcessor(approval_checker=checker)

        chunks = [
            make_tool_chunk(0, tool_id="c1", name="read_file", arguments='{}'),
            make_tool_chunk(1, tool_id="c2", name="write_file", arguments='{}'),
        ]

        events = await collect_events(processor, chunks)
        tool_calls = filter_events(events, ToolCallStart)

        assert approvals == ["read_file", "write_file"]
        assert tool_calls[0].requires_approval is False
        assert tool_calls[1].requires_approval is True


# =============================================================================
# Code Fence Detection Tests
# =============================================================================

class TestCodeFenceDetection:
    """Test code fence boundary detection."""

    @pytest.mark.asyncio
    async def test_simple_code_block(self):
        """Simple code block should emit proper events."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("Here's code:\n"),
            make_content_chunk("```python\n"),
            make_content_chunk("print('hello')\n"),
            make_content_chunk("```\n"),
            make_content_chunk("That's it."),
        ]

        events = await collect_events(processor, chunks)
        event_types = get_event_types(events)

        assert "CodeBlockStart" in event_types
        assert "CodeBlockDelta" in event_types
        assert "CodeBlockEnd" in event_types

        # Check language
        start = filter_events(events, CodeBlockStart)[0]
        assert start.language == "python"

    @pytest.mark.asyncio
    async def test_code_block_no_language(self):
        """Code block without language should default to 'text'."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("```\n"),
            make_content_chunk("some code\n"),
            make_content_chunk("```\n"),
        ]

        events = await collect_events(processor, chunks)
        start = filter_events(events, CodeBlockStart)[0]

        assert start.language == "text"

    @pytest.mark.asyncio
    async def test_fence_split_across_chunks(self):
        """Fence split across chunks should still work."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("Code:\n``"),
            make_content_chunk("`python\nprint('hi')\n"),
            make_content_chunk("``"),
            make_content_chunk("`\nDone."),
        ]

        events = await collect_events(processor, chunks)
        event_types = get_event_types(events)

        assert "CodeBlockStart" in event_types
        assert "CodeBlockEnd" in event_types

    @pytest.mark.asyncio
    async def test_multiple_code_blocks(self):
        """Multiple code blocks in sequence."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("First:\n```python\nprint(1)\n```\n"),
            make_content_chunk("Second:\n```javascript\nconsole.log(2)\n```\n"),
        ]

        events = await collect_events(processor, chunks)
        starts = filter_events(events, CodeBlockStart)
        ends = filter_events(events, CodeBlockEnd)

        assert len(starts) == 2
        assert len(ends) == 2
        assert starts[0].language == "python"
        assert starts[1].language == "javascript"

    @pytest.mark.asyncio
    async def test_unclosed_code_block(self):
        """Unclosed code block should still emit CodeBlockEnd at stream end."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("```python\nprint('never closed')"),
        ]

        events = await collect_events(processor, chunks)

        assert len(filter_events(events, CodeBlockStart)) == 1
        assert len(filter_events(events, CodeBlockEnd)) == 1

    @pytest.mark.asyncio
    async def test_backticks_at_chunk_boundary(self):
        """Backticks at chunk boundary should be handled correctly."""
        processor = StreamProcessor()

        # Code block where closing fence is split
        chunks = [
            make_content_chunk("```py\nx=1\n"),
            make_content_chunk("`"),
            make_content_chunk("``"),
            make_content_chunk("\ndone"),
        ]

        events = await collect_events(processor, chunks)

        # Should have proper code block lifecycle
        assert len(filter_events(events, CodeBlockStart)) == 1
        assert len(filter_events(events, CodeBlockEnd)) == 1


# =============================================================================
# Thinking Block Tests
# =============================================================================

class TestThinkingBlocks:
    """Test thinking/reasoning block handling."""

    @pytest.mark.asyncio
    async def test_simple_thinking_block(self):
        """Simple thinking block should emit proper events."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("Let me think...\n<thinking>\n"),
            make_content_chunk("Analyzing the problem...\n"),
            make_content_chunk("</thinking>\n"),
            make_content_chunk("Here's my answer."),
        ]

        events = await collect_events(processor, chunks)
        event_types = get_event_types(events)

        assert "ThinkingStart" in event_types
        assert "ThinkingDelta" in event_types
        assert "ThinkingEnd" in event_types

    @pytest.mark.asyncio
    async def test_thinking_token_count(self):
        """ThinkingEnd should include token count."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("<thinking>"),
            make_content_chunk("word " * 50),  # 50 words
            make_content_chunk("</thinking>"),
        ]

        events = await collect_events(processor, chunks)
        end = filter_events(events, ThinkingEnd)[0]

        # Should have some token count (rough word estimate)
        assert end.token_count is not None
        assert end.token_count > 0

    @pytest.mark.asyncio
    async def test_unclosed_thinking_block(self):
        """Unclosed thinking block should emit ThinkingEnd at stream end."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("<thinking>I'm thinking..."),
        ]

        events = await collect_events(processor, chunks)

        assert len(filter_events(events, ThinkingStart)) == 1
        assert len(filter_events(events, ThinkingEnd)) == 1

    @pytest.mark.asyncio
    async def test_alternative_reasoning_tags(self):
        """Should handle <reasoning> tags too."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("<reasoning>"),
            make_content_chunk("Some reasoning here"),
            make_content_chunk("</reasoning>"),
        ]

        events = await collect_events(processor, chunks)

        assert len(filter_events(events, ThinkingStart)) == 1
        assert len(filter_events(events, ThinkingEnd)) == 1


# =============================================================================
# Debouncing Tests
# =============================================================================

class TestDebouncing:
    """Test text debouncing behavior."""

    @pytest.mark.asyncio
    async def test_flushes_on_newline(self):
        """Should flush on natural breaks (newlines)."""
        processor = StreamProcessor(idle_timeout_ms=50, max_latency_ms=150)

        chunks = [
            make_content_chunk("Hello "),
            make_content_chunk("world\n"),
            make_content_chunk("More text"),
        ]

        events = await collect_events(processor, chunks)
        text_events = filter_events(events, TextDelta)

        # Should have at least 2 TextDeltas (flushed on newline + end)
        assert len(text_events) >= 2

    @pytest.mark.asyncio
    async def test_accumulates_without_newline(self):
        """Should accumulate text when no natural break."""
        processor = StreamProcessor(idle_timeout_ms=50, max_latency_ms=1000)

        chunks = [
            make_content_chunk("Hello "),
            make_content_chunk("world "),
            make_content_chunk("how "),
            make_content_chunk("are you"),
        ]

        events = await collect_events(processor, chunks)
        text_events = filter_events(events, TextDelta)

        # All text should be in one or few events (accumulated)
        total_text = "".join(e.content for e in text_events)
        assert total_text == "Hello world how are you"

    @pytest.mark.asyncio
    async def test_flushes_on_sentence_end(self):
        """Should flush on sentence-ending punctuation."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("This is a sentence."),
            make_content_chunk(" And another!"),
        ]

        events = await collect_events(processor, chunks)
        text_events = filter_events(events, TextDelta)

        # Should flush on period
        assert len(text_events) >= 2


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error classification and handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Rate limit errors should be classified correctly."""
        processor = StreamProcessor()

        async def failing_stream():
            raise Exception("Rate limit exceeded. Retry after 60 seconds.")
            yield  # Make it an async generator

        events = []
        async for event in processor.process(failing_stream()):
            events.append(event)

        errors = filter_events(events, ErrorEvent)
        assert len(errors) == 1
        assert errors[0].error_type == "rate_limit"
        assert errors[0].recoverable is True
        assert errors[0].retry_after == 60

    @pytest.mark.asyncio
    async def test_network_error(self):
        """Network errors should be classified correctly."""
        processor = StreamProcessor()

        async def failing_stream():
            raise ConnectionError("Connection refused")
            yield

        events = []
        async for event in processor.process(failing_stream()):
            events.append(event)

        errors = filter_events(events, ErrorEvent)
        assert len(errors) == 1
        assert errors[0].error_type == "network"
        assert errors[0].recoverable is True

    @pytest.mark.asyncio
    async def test_auth_error(self):
        """Auth errors should be classified correctly."""
        processor = StreamProcessor()

        async def failing_stream():
            raise Exception("401 Unauthorized: Invalid API key")
            yield

        events = []
        async for event in processor.process(failing_stream()):
            events.append(event)

        errors = filter_events(events, ErrorEvent)
        assert len(errors) == 1
        assert errors[0].error_type == "auth"
        assert errors[0].recoverable is False


# =============================================================================
# State Transition Tests
# =============================================================================

class TestStateTransitions:
    """Test state machine transitions."""

    @pytest.mark.asyncio
    async def test_initial_state(self):
        """Processor should start in IDLE state."""
        processor = StreamProcessor()
        assert processor._state == StreamState.IDLE

    @pytest.mark.asyncio
    async def test_text_to_code_transition(self):
        """Should transition from TEXT to CODE_BLOCK on fence."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("Text ```python\ncode"),
        ]

        events = await collect_events(processor, chunks)

        # Should have text, then code block
        event_types = get_event_types(events)
        text_idx = event_types.index("TextDelta")
        code_idx = event_types.index("CodeBlockStart")
        assert text_idx < code_idx

    @pytest.mark.asyncio
    async def test_code_to_text_transition(self):
        """Should transition from CODE_BLOCK to TEXT on closing fence."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("```python\ncode\n```\nmore text"),
        ]

        events = await collect_events(processor, chunks)
        event_types = get_event_types(events)

        # Order should be: Start, CodeBlockStart, CodeBlockDelta, CodeBlockEnd, TextDelta, End
        code_end_idx = event_types.index("CodeBlockEnd")

        # Find TextDelta that comes after CodeBlockEnd
        text_deltas_after = [
            i for i, t in enumerate(event_types)
            if t == "TextDelta" and i > code_end_idx
        ]
        assert len(text_deltas_after) > 0

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        """Reset should clear all state."""
        processor = StreamProcessor()
        processor._state = StreamState.CODE_BLOCK
        processor._text_buffer = "some text"
        processor._code_buffer = "some code"
        processor._tool_calls[0] = ToolCallAccumulator(index=0, name="test")

        processor.reset()

        assert processor._state == StreamState.IDLE
        assert processor._text_buffer == ""
        assert processor._code_buffer == ""
        assert len(processor._tool_calls) == 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.mark.asyncio
    async def test_mixed_content_and_tools(self):
        """Handle mixed content: text, code, and tool calls."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("I'll read the file:\n"),
            make_tool_chunk(0, tool_id="c1", name="read_file", arguments='{"path": "test.py"}'),
            make_content_chunk("\nHere's what I found:\n"),
            make_content_chunk("```python\nprint('hello')\n```\n"),
            make_content_chunk("That's the code."),
        ]

        events = await collect_events(processor, chunks)
        event_types = get_event_types(events)

        # Should have all event types
        assert "TextDelta" in event_types
        assert "ToolCallStart" in event_types
        assert "CodeBlockStart" in event_types
        assert "CodeBlockEnd" in event_types
        assert "StreamStart" in event_types
        assert "StreamEnd" in event_types

    @pytest.mark.asyncio
    async def test_stream_end_includes_stats(self):
        """StreamEnd should include duration."""
        processor = StreamProcessor()

        chunks = [
            make_content_chunk("Hello world!"),
        ]

        events = await collect_events(processor, chunks)
        end = filter_events(events, StreamEnd)[0]

        assert end.duration_ms is not None
        assert end.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        """Empty stream should still emit Start/End."""
        processor = StreamProcessor()

        events = await collect_events(processor, [])
        event_types = get_event_types(events)

        assert "StreamStart" in event_types
        assert "StreamEnd" in event_types


# Run with: pytest tests/ui/test_stream_processor.py -v
