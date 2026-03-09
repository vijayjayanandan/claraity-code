"""Stream-to-Store Adapter - Bridges UIEvents to MessageStore.

This adapter listens to UIEvents from StreamProcessor and converts them
into Message objects that are added to the MessageStore with proper
stream_id for collapse semantics.

Architecture:
    StreamProcessor -> UIEvents -> StoreAdapter -> MessageStore
                                                       |
                                                       v
                                               SessionWriter -> JSONL

The adapter maintains state to track:
- Current stream_id for message collapse
- Accumulated text content
- Segments list for interleaving order
- Tool calls array

Phase 6 Design:
- Adapter consumes UIEvents at the same boundaries as the TUI
- Messages are updated incrementally with stable stream_id
- Finalization emits MESSAGE_FINALIZED for the stream
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from src.observability import get_logger
from src.session.models.base import generate_stream_id, generate_uuid, now_iso
from src.session.models.message import (
    Message,
    MessageMeta,
    Segment,
    TextSegment,
    ThinkingSegment,
    TokenUsage,
    ToolCall,
    ToolCallFunction,
    ToolCallSegment,
)

from .events import (
    CodeBlockDelta,
    CodeBlockEnd,
    CodeBlockStart,
    ErrorEvent,
    StreamEnd,
    StreamStart,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolCallResult,
    ToolCallStart,
    ToolCallStatus,
    UIEvent,
)

if TYPE_CHECKING:
    from src.session.store.memory_store import MessageStore

logger = get_logger("ui.store_adapter")


@dataclass
class StreamingState:
    """Tracks state of the current streaming message."""

    stream_id: str
    session_id: str
    parent_uuid: str | None

    # Content accumulation
    text_content: str = ""
    thinking_content: str = ""
    code_content: str = ""
    code_language: str = ""

    # Segments for interleaving order
    segments: list[Segment] = field(default_factory=list)

    # Tool calls
    tool_calls: list[ToolCall] = field(default_factory=list)

    # State tracking
    in_code_block: bool = False
    in_thinking: bool = False
    current_text_segment_start: int = 0  # Track where current text segment starts

    # Metrics
    total_tokens: int | None = None
    duration_ms: int | None = None
    thinking_tokens: int | None = None


class StoreAdapter:
    """
    Adapts UIEvents to MessageStore operations.

    Usage:
        adapter = StoreAdapter(store, session_id)

        # During streaming
        for event in stream_processor.process(chunks):
            adapter.handle_event(event)

    The adapter:
    1. Creates a new Message on StreamStart
    2. Updates the message on content events (text, code, tool, thinking)
    3. Finalizes the message on StreamEnd

    All updates use the same stream_id, so the store collapses them
    into a single message entry (projection), while the writer persists
    each update to the JSONL ledger.
    """

    def __init__(
        self,
        store: "MessageStore",
        session_id: str,
        parent_uuid: str | None = None,
        flush_on_boundary: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            store: MessageStore to update
            session_id: Current session ID
            parent_uuid: Parent message UUID (usually last user message)
            flush_on_boundary: If True, update store at each content boundary
                              If False, only update on finalization
        """
        self._store = store
        self._session_id = session_id
        self._parent_uuid = parent_uuid
        self._flush_on_boundary = flush_on_boundary

        # Current streaming state (None when not streaming)
        self._state: StreamingState | None = None

    @property
    def is_streaming(self) -> bool:
        """Check if currently processing a stream."""
        return self._state is not None

    @property
    def current_stream_id(self) -> str | None:
        """Get current stream_id if streaming."""
        return self._state.stream_id if self._state else None

    def set_parent_uuid(self, parent_uuid: str | None) -> None:
        """Update parent UUID for next message."""
        self._parent_uuid = parent_uuid

    def handle_event(self, event: UIEvent) -> None:
        """
        Handle a UIEvent and update the store accordingly.

        Args:
            event: UIEvent from StreamProcessor
        """
        match event:
            # Stream lifecycle
            case StreamStart():
                self._handle_stream_start()
            case StreamEnd(total_tokens=tokens, duration_ms=duration):
                self._handle_stream_end(tokens, duration)

            # Text content
            case TextDelta(content=text):
                self._handle_text_delta(text)

            # Code blocks
            case CodeBlockStart(language=lang):
                self._handle_code_start(lang)
            case CodeBlockDelta(content=code):
                self._handle_code_delta(code)
            case CodeBlockEnd():
                self._handle_code_end()

            # Tool calls
            case ToolCallStart(call_id=cid, name=name, arguments=args, requires_approval=req):
                self._handle_tool_start(cid, name, args, req)
            case ToolCallStatus():
                pass  # Status updates don't affect message content
            case ToolCallResult(
                call_id=cid, status=status, result=result, error=err, duration_ms=dur
            ):
                self._handle_tool_result(cid, status, result, err, dur)

            # Thinking
            case ThinkingStart():
                self._handle_thinking_start()
            case ThinkingDelta(content=text):
                self._handle_thinking_delta(text)
            case ThinkingEnd(token_count=tokens):
                self._handle_thinking_end(tokens)

            # Errors
            case ErrorEvent():
                pass  # Errors are handled separately, don't affect message store

            case _:
                logger.debug(f"Unhandled event type: {type(event).__name__}")

    # =========================================================================
    # Stream Lifecycle
    # =========================================================================

    def _handle_stream_start(self) -> None:
        """Initialize new streaming message state."""
        if self._state is not None:
            # Expected after Ctrl+C interrupt - previous stream wasn't finalized
            logger.info(
                "StreamStart: finalizing incomplete previous stream (normal after interrupt)"
            )
            self._finalize_current()

        self._state = StreamingState(
            stream_id=generate_stream_id(),
            session_id=self._session_id,
            parent_uuid=self._parent_uuid,
        )

        logger.debug(f"Stream started: {self._state.stream_id}")

        # Create initial message in store
        self._flush_to_store()

    def _handle_stream_end(self, total_tokens: int | None, duration_ms: int | None) -> None:
        """Finalize the streaming message."""
        if self._state is None:
            # Expected when finally block sends StreamEnd after normal completion
            logger.debug("StreamEnd: no active stream (already finalized)")
            return

        self._state.total_tokens = total_tokens
        self._state.duration_ms = duration_ms

        self._finalize_current()

    def _finalize_current(self) -> None:
        """Finalize and flush the current message."""
        if self._state is None:
            return

        # Flush any pending text segment
        self._flush_text_segment()

        # Final update to store
        self._flush_to_store(finalize=True)

        # Per UNIFIED_PERSISTENCE_ARCHITECTURE_FINAL.md Section 3.7:
        # StoreAdapter is READ-ONLY. MemoryManager is the SINGLE WRITER.
        # Finalization is handled by MemoryManager via StreamingPipeline.
        # Removed: self._store.finalize_message(stream_id)

        stream_id = self._state.stream_id
        logger.debug(f"Stream state cleared: {stream_id}")

        # Clear state
        self._state = None

    # =========================================================================
    # Text Content
    # =========================================================================

    def _handle_text_delta(self, text: str) -> None:
        """Accumulate text content."""
        if self._state is None:
            logger.warning("TextDelta without active stream")
            return

        self._state.text_content += text

        # In boundary mode, flush to store on each delta
        # (The StreamProcessor already batches deltas appropriately)
        if self._flush_on_boundary:
            self._flush_to_store()

    def _flush_text_segment(self) -> None:
        """Flush accumulated text as a segment."""
        if self._state is None:
            return

        # Get text since last segment
        text_since_last = self._state.text_content[self._state.current_text_segment_start :]

        if text_since_last.strip():
            self._state.segments.append(TextSegment(content=text_since_last))
            self._state.current_text_segment_start = len(self._state.text_content)

    # =========================================================================
    # Code Blocks
    # =========================================================================

    def _handle_code_start(self, language: str) -> None:
        """Start a code block."""
        if self._state is None:
            return

        # Flush any pending text before code block
        self._flush_text_segment()

        self._state.in_code_block = True
        self._state.code_language = language
        self._state.code_content = ""

    def _handle_code_delta(self, code: str) -> None:
        """Accumulate code content."""
        if self._state is None or not self._state.in_code_block:
            return

        self._state.code_content += code

    def _handle_code_end(self) -> None:
        """End code block and add to content."""
        if self._state is None or not self._state.in_code_block:
            return

        # Add code block as markdown code fence to text content
        lang = self._state.code_language or ""
        code = self._state.code_content

        # Append code fence to text content
        code_fence = f"\n```{lang}\n{code}\n```\n"
        self._state.text_content += code_fence

        # Note: We don't add a separate segment for code blocks
        # They're embedded in the text content as markdown

        self._state.in_code_block = False
        self._state.code_content = ""
        self._state.code_language = ""

        if self._flush_on_boundary:
            self._flush_to_store()

    # =========================================================================
    # Tool Calls
    # =========================================================================

    def _handle_tool_start(
        self, call_id: str, name: str, arguments: dict, requires_approval: bool
    ) -> None:
        """Add a tool call to the message."""
        if self._state is None:
            return

        # Flush any pending text before tool call
        self._flush_text_segment()

        # Create ToolCall object
        tool_call = ToolCall(
            id=call_id,
            function=ToolCallFunction(name=name, arguments=json.dumps(arguments)),
            meta={"requires_approval": requires_approval},
        )

        self._state.tool_calls.append(tool_call)

        # Add ToolCallSegment for ordering
        tool_index = len(self._state.tool_calls) - 1
        self._state.segments.append(ToolCallSegment(tool_call_index=tool_index))

        if self._flush_on_boundary:
            self._flush_to_store()

    def _handle_tool_result(
        self,
        call_id: str,
        status,  # ToolStatus enum
        result,
        error: str | None,
        duration_ms: int | None,
    ) -> None:
        """
        Handle tool result by persisting as a separate role="tool" message.

        Tool results are stored as separate messages that reference the
        tool_call_id from the assistant's tool_call. This is required for
        valid LLM context and session replay.
        """
        from .events import ToolStatus as ToolStatusEnum

        # Determine content and status string
        if status == ToolStatusEnum.SUCCESS:
            content = result or ""
            status_str = "success"
        elif status == ToolStatusEnum.ERROR:
            content = error or "Unknown error"
            status_str = "error"
        elif status == ToolStatusEnum.TIMEOUT:
            content = error or "Tool execution timed out"
            status_str = "timeout"
        elif status == ToolStatusEnum.CANCELLED:
            content = error or "Tool execution cancelled"
            status_str = "cancelled"
        else:
            content = result or error or ""
            status_str = "success"

        # Persist tool result as separate message
        self.add_tool_result(
            tool_call_id=call_id, content=content, status=status_str, duration_ms=duration_ms
        )

    def add_tool_result(
        self,
        tool_call_id: str,
        content: str,
        status: str = "success",
        duration_ms: int | None = None,
        exit_code: int | None = None,
    ) -> Message:
        """
        Add a tool result as a separate message.

        Tool results are role="tool" messages that reference the tool_call_id.

        Args:
            tool_call_id: ID of the tool call this responds to
            content: Tool output content
            status: Execution status ("success", "error", etc.)
            duration_ms: Execution duration
            exit_code: Exit code for bash tools

        Returns:
            The created tool result Message
        """
        # Per UNIFIED_PERSISTENCE_ARCHITECTURE_FINAL.md Section 3.7:
        # StoreAdapter is READ-ONLY. MemoryManager is the SINGLE WRITER.
        # Tool results are added by MemoryManager.add_tool_result().
        # Return None since we don't create the message here.
        return None

    # =========================================================================
    # Thinking Blocks
    # =========================================================================

    def _handle_thinking_start(self) -> None:
        """Start a thinking block.

        Note: Thinking is rendered live via ThinkingStart/Delta/End UIEvents
        in app.py._handle_event(). This handler accumulates state for segment
        completeness but _flush_to_store() is a no-op (MemoryManager is the
        single writer; see UNIFIED_PERSISTENCE_ARCHITECTURE).
        """
        if self._state is None:
            return

        # Flush any pending text before thinking
        self._flush_text_segment()

        self._state.in_thinking = True
        self._state.thinking_content = ""

    def _handle_thinking_delta(self, text: str) -> None:
        """Accumulate thinking content."""
        if self._state is None or not self._state.in_thinking:
            return

        self._state.thinking_content += text

    def _handle_thinking_end(self, token_count: int | None) -> None:
        """End thinking block."""
        if self._state is None or not self._state.in_thinking:
            return

        self._state.thinking_tokens = token_count

        # Add ThinkingSegment
        if self._state.thinking_content.strip():
            self._state.segments.append(ThinkingSegment(content=self._state.thinking_content))

        self._state.in_thinking = False

        if self._flush_on_boundary:
            self._flush_to_store()

    # =========================================================================
    # Store Operations
    # =========================================================================

    def _flush_to_store(self, finalize: bool = False) -> None:
        """
        Build Message from current state and add to store.

        Uses stream_id for collapse semantics - subsequent calls
        update the same logical message in the store projection.
        """
        if self._state is None:
            return

        # Build usage info if available
        usage = None
        if self._state.total_tokens is not None:
            usage = TokenUsage(output_tokens=self._state.total_tokens)

        # Build segments list (clone to avoid mutation issues)
        segments = list(self._state.segments)

        # Add any pending text as final segment (for finalization)
        if finalize:
            text_since_last = self._state.text_content[self._state.current_text_segment_start :]
            if text_since_last.strip():
                segments.append(TextSegment(content=text_since_last))

        # Determine stop_reason
        stop_reason = "complete" if finalize else "streaming"
        if self._state.tool_calls:
            stop_reason = "tool_use" if finalize else "streaming"

        # Build message
        # Per UNIFIED_PERSISTENCE_ARCHITECTURE_FINAL.md Section 3.7:
        # StoreAdapter is READ-ONLY. MemoryManager is the SINGLE WRITER.
        # Store writes removed - MemoryManager.process_provider_delta() handles this.
        pass

    # =========================================================================
    # User Message Helper
    # =========================================================================

    def add_user_message(self, content: str) -> Message:
        """
        Add a user message to the store.

        Convenience method for adding user input before streaming starts.

        Args:
            content: User message content

        Returns:
            The created Message
        """
        message = Message.create_user(
            content=content,
            session_id=self._session_id,
            parent_uuid=self._parent_uuid,
            seq=self._store.next_seq(),
        )

        self._store.add_message(message)

        # Update parent for next message
        self._parent_uuid = message.uuid

        return message
