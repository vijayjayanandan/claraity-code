"""StreamingPipeline - Single canonical parser for LLM deltas.

This is the ONLY place in the codebase that makes structural decisions:
- Detecting code fences (``` blocks)
- Assembling tool call JSON from incremental deltas
- Detecting thinking block boundaries
- Deciding when to flush text segments

The TUI renders segments directly - it does ZERO parsing.
"""

import re
from typing import Optional, List

from src.observability import get_logger
from src.session.models.message import (
    Message, MessageMeta, Segment,
    TextSegment, CodeBlockSegment, ToolCallRefSegment, ThinkingSegment,
    ToolCall, ToolCallFunction, TokenUsage
)
from src.session.models.base import generate_uuid, now_iso, generate_stream_id
from src.llm.base import ProviderDelta, ToolCallDelta

from .state import StreamingState, ToolCallAccumulator

logger = get_logger("core.streaming.pipeline")

# Regex patterns for structural detection
CODE_FENCE_START = re.compile(r'^```(\w*)\s*$', re.MULTILINE)
CODE_FENCE_END = re.compile(r'^```\s*$', re.MULTILINE)
THINKING_START = re.compile(r'<thinking>', re.IGNORECASE)
THINKING_END = re.compile(r'</thinking>', re.IGNORECASE)


class StreamingPipeline:
    """
    SINGLE CANONICAL PARSER for all structural decisions.

    Converts raw LLM deltas into Message objects with fully-parsed segments.
    Owned by Agent/Core layer. UI-agnostic.

    Usage:
        pipeline = StreamingPipeline(session_id="...", parent_uuid="...")

        for delta in provider_stream:
            message = pipeline.process_delta(delta)
            if message:
                # Stream complete, message is finalized
                store.add_message(message)

        # Or get current state for live UI updates:
        current = pipeline.get_current_state()
    """

    def __init__(
        self,
        session_id: str,
        parent_uuid: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize the streaming pipeline.

        Args:
            session_id: Current session ID
            parent_uuid: Parent message UUID (usually last user message)
            provider: Provider name (e.g., "openai", "anthropic")
            model: Model name
        """
        self._session_id = session_id
        self._parent_uuid = parent_uuid
        self._state: Optional[StreamingState] = None
        self._provider = provider
        self._model = model

    @property
    def is_streaming(self) -> bool:
        """Check if currently processing a stream."""
        return self._state is not None

    @property
    def current_stream_id(self) -> Optional[str]:
        """Get current stream_id if streaming."""
        return self._state.stream_id if self._state else None

    def process_delta(self, delta: ProviderDelta) -> Optional[Message]:
        """
        Process a single provider delta.

        Args:
            delta: ProviderDelta from provider adapter

        Returns:
            Finalized Message when complete (finish_reason set), None otherwise.
        """
        # Initialize state on first delta
        if self._state is None:
            self._state = StreamingState(
                stream_id=delta.stream_id or generate_stream_id(),
                session_id=self._session_id,
                parent_uuid=self._parent_uuid,
                provider=self._provider,
                model=self._model
            )
            logger.debug(f"Stream started: {self._state.stream_id}")

        # Process text delta
        if delta.text_delta:
            self._process_text_delta(delta.text_delta)

        # Process thinking delta (native provider support)
        if delta.thinking_delta:
            self._process_thinking_delta(delta.thinking_delta)

        # Process tool call delta
        if delta.tool_call_delta:
            self._process_tool_call_delta(delta.tool_call_delta)

        # Store usage if provided (convert dict to TokenUsage)
        if delta.usage:
            self._state.usage = TokenUsage.from_dict(delta.usage) if isinstance(delta.usage, dict) else delta.usage

        # Finalize on finish_reason
        if delta.finish_reason:
            return self._finalize_message(delta.finish_reason)

        return None

    def get_current_state(self) -> Optional[Message]:
        """
        Get current in-flight message state for live UI updates.

        Returns:
            Current Message state (not finalized), or None if not streaming.
        """
        if self._state is None:
            return None

        return self._build_message(stop_reason="streaming")

    def reset(self) -> None:
        """Reset pipeline state for new stream."""
        self._state = None

    # =========================================================================
    # Text Processing
    # =========================================================================

    def _process_text_delta(self, text: str) -> None:
        """
        Process text delta with structural parsing.

        Detects and handles:
        - Code blocks (``` fences)
        - Thinking blocks (<thinking> tags) if not using native thinking_delta
        """
        if self._state is None:
            return

        # Add to appropriate buffer based on current state
        if self._state.in_code_block:
            self._process_code_block_delta(text)
        elif self._state.in_thinking:
            self._process_thinking_text_delta(text)
        else:
            self._process_normal_text_delta(text)

    def _process_normal_text_delta(self, text: str) -> None:
        """Process text outside of code blocks and thinking blocks."""
        state = self._state

        # Accumulate text
        state.text_buffer += text
        state.full_text_content += text

        # Check for code fence start
        if '```' in state.text_buffer:
            self._check_code_fence_start()

        # Check for thinking tag start (if not using native thinking)
        if '<thinking>' in state.text_buffer.lower():
            self._check_thinking_start()

    def _check_code_fence_start(self) -> None:
        """Check if text buffer contains a code fence start."""
        state = self._state

        # Look for ``` followed by optional language and newline
        # We need to handle streaming where ``` and language might arrive separately
        # A code fence start is complete when we see: ```language\n (newline ends the fence line)

        # Only process if we have at least one complete line (ends with newline)
        if '\n' not in state.text_buffer:
            return

        lines = state.text_buffer.split('\n')

        # Check all complete lines (all except possibly the last one if no trailing newline)
        # If buffer ends with newline, last element is empty string - all lines are complete
        check_lines = lines[:-1] if state.text_buffer and not state.text_buffer.endswith('\n') else lines[:-1] if lines[-1] == '' else lines

        for i, line in enumerate(check_lines):
            stripped = line.strip()
            # Match opening fence: starts with ``` but is not just ``` (which could be closing)
            # Also not ```...``` (inline code)
            if stripped.startswith('```'):
                # Check it's not a closing fence (just ```) or inline (```x```)
                rest = stripped[3:]
                if rest and rest.endswith('```'):
                    # Inline code block like ```code```, skip
                    continue
                if not rest or rest.isidentifier() or rest.replace('-', '').replace('_', '').isalnum():
                    # Valid opening fence with optional language
                    lang = rest.strip()

                    # Calculate position in buffer
                    pre_lines = '\n'.join(lines[:i])
                    if pre_lines:
                        pre_lines += '\n'

                    # Flush text before the fence as a segment
                    if pre_lines.strip():
                        state.segments.append(TextSegment(content=pre_lines))

                    # Start code block
                    state.in_code_block = True
                    state.code_block_language = lang
                    state.code_block_content = ""

                    # Clear buffer, keeping text after the fence line
                    post_fence = '\n'.join(lines[i + 1:])
                    state.text_buffer = ""

                    # Process any remaining text as code
                    if post_fence:
                        self._process_code_block_delta(post_fence)
                    return

    def _process_code_block_delta(self, text: str) -> None:
        """Process text inside a code block."""
        state = self._state

        # Accumulate code content
        state.code_block_content += text
        state.full_text_content += text

        # Check for code fence end
        if '```' in state.code_block_content:
            match = CODE_FENCE_END.search(state.code_block_content)
            if match:
                # Extract code content before the closing fence
                code_content = state.code_block_content[:match.start()].rstrip('\n')

                # Add code block segment
                state.segments.append(CodeBlockSegment(
                    language=state.code_block_language,
                    content=code_content
                ))

                # Exit code block mode
                state.in_code_block = False
                state.code_block_language = ""

                # Any text after closing fence goes back to normal processing
                post_fence = state.code_block_content[match.end():]
                state.code_block_content = ""

                if post_fence:
                    state.text_buffer = post_fence
                    # Check for another code fence
                    if '```' in post_fence:
                        self._check_code_fence_start()

    def _check_thinking_start(self) -> None:
        """Check if text buffer contains a thinking tag start."""
        state = self._state

        match = THINKING_START.search(state.text_buffer)
        if match:
            # Flush text before the tag as a segment
            pre_tag_text = state.text_buffer[:match.start()]
            if pre_tag_text.strip():
                state.segments.append(TextSegment(content=pre_tag_text))

            # Start thinking block
            state.in_thinking = True
            state.thinking_content = ""

            # Clear buffer, keeping any text after the tag
            post_match = state.text_buffer[match.end():]
            state.text_buffer = ""

            if post_match:
                self._process_thinking_text_delta(post_match)

    def _process_thinking_text_delta(self, text: str) -> None:
        """Process text inside a thinking block (tag-based)."""
        state = self._state

        state.thinking_content += text

        # Check for thinking end tag
        if '</thinking>' in state.thinking_content.lower():
            match = THINKING_END.search(state.thinking_content)
            if match:
                # Extract thinking content
                thinking_text = state.thinking_content[:match.start()]

                # Add thinking segment
                if thinking_text.strip():
                    state.segments.append(ThinkingSegment(content=thinking_text))

                # Exit thinking mode
                state.in_thinking = False

                # Any text after closing tag goes back to normal processing
                post_tag = state.thinking_content[match.end():]
                state.thinking_content = ""

                if post_tag:
                    state.text_buffer = post_tag
                    state.full_text_content += post_tag

    # =========================================================================
    # Native Thinking Processing (provider-level)
    # =========================================================================

    def _process_thinking_delta(self, text: str) -> None:
        """
        Process native thinking delta from provider.

        This is for providers that emit thinking as a separate stream
        (e.g., Claude with extended thinking).
        """
        if self._state is None:
            return

        # Accumulate thinking content
        self._state.thinking_content += text
        # Also accumulate as reasoning_content for echo-back (Kimi K2.5 etc.)
        self._state.reasoning_content += text

    # =========================================================================
    # Tool Call Processing
    # =========================================================================

    def _process_tool_call_delta(self, delta: ToolCallDelta) -> None:
        """Process incremental tool call data."""
        if self._state is None:
            return

        state = self._state
        index = delta.index

        # Get or create accumulator for this index
        if index not in state.tool_call_accumulators:
            state.tool_call_accumulators[index] = ToolCallAccumulator()

        acc = state.tool_call_accumulators[index]

        # Update accumulator fields
        if delta.id:
            acc.id = delta.id
        if delta.name:
            acc.name = delta.name
        if delta.arguments_delta:
            acc.arguments_buffer += delta.arguments_delta

    # =========================================================================
    # Finalization
    # =========================================================================

    def _finalize_message(self, finish_reason: str) -> Message:
        """
        Build final Message with all segments.

        Args:
            finish_reason: The finish reason from provider

        Returns:
            Finalized Message object
        """
        state = self._state

        # Flush any pending content
        self._flush_pending()

        # Convert tool call accumulators to ToolCall objects
        self._finalize_tool_calls()

        # Build message
        message = self._build_message(stop_reason=finish_reason)

        logger.debug(
            f"Stream finalized: {state.stream_id}, segments={len(state.segments)}, "
            f"reasoning={len(state.reasoning_content) if state.reasoning_content else 0}, "
            f"tool_calls={len(state.tool_calls)}, finish={finish_reason}"
        )

        # Reset state
        self._state = None

        return message

    def _flush_pending(self) -> None:
        """Flush any pending content to segments."""
        state = self._state
        if state is None:
            return

        # Flush native thinking content FIRST (appears above text in UI)
        # Must come before text flush so segment order matches live rendering.
        if state.thinking_content and not any(
            isinstance(s, ThinkingSegment) for s in state.segments
        ):
            state.segments.append(ThinkingSegment(content=state.thinking_content))

        # Flush pending code block
        if state.in_code_block and state.code_block_content:
            state.segments.append(CodeBlockSegment(
                language=state.code_block_language,
                content=state.code_block_content.rstrip('\n')
            ))
            state.in_code_block = False
            state.code_block_content = ""

        # Flush pending thinking (tag-based, if not already added above)
        if state.in_thinking and state.thinking_content:
            if not any(isinstance(s, ThinkingSegment) for s in state.segments):
                state.segments.append(ThinkingSegment(content=state.thinking_content))
            state.in_thinking = False

        # Flush pending text buffer
        if state.text_buffer.strip():
            state.segments.append(TextSegment(content=state.text_buffer))
            state.text_buffer = ""

    def _finalize_tool_calls(self) -> None:
        """Convert tool call accumulators to ToolCall objects and add segments."""
        state = self._state
        if state is None:
            return

        # Flush any pending text before tool calls
        if state.text_buffer.strip():
            state.segments.append(TextSegment(content=state.text_buffer))
            state.text_buffer = ""

        # Convert accumulators to tool calls
        for index in sorted(state.tool_call_accumulators.keys()):
            acc = state.tool_call_accumulators[index]
            if acc.is_complete():
                tool_call = acc.to_tool_call()
                state.tool_calls.append(tool_call)

                # Add segment referencing by ID
                state.segments.append(ToolCallRefSegment(tool_call_id=tool_call.id))

    def _build_message(self, stop_reason: str) -> Message:
        """Build Message from current state."""
        state = self._state

        # Determine final stop reason
        if state.tool_calls and stop_reason not in ("streaming", "error"):
            stop_reason = "tool_use"

        return Message(
            role="assistant",
            content=state.full_text_content or None,
            tool_calls=list(state.tool_calls),
            meta=MessageMeta(
                uuid=generate_uuid(),
                seq=0,  # Caller sets seq
                timestamp=now_iso(),
                session_id=state.session_id,
                parent_uuid=state.parent_uuid,
                stream_id=state.stream_id,
                stop_reason=stop_reason,
                usage=state.usage,
                segments=list(state.segments) if state.segments else None,
                thinking=state.thinking_content or None,
                reasoning_content=state.reasoning_content or None,
                provider=state.provider,
                model=state.model,
            )
        )
