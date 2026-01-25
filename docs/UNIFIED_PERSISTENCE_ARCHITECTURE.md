# Unified Message Persistence Architecture - Implementation Plan

**Version:** 2.0
**Status:** Ready for Review
**Last Updated:** 2026-01-21

---

## Executive Summary

This document outlines the architecture for unified message persistence where:

1. **Agent/Core owns the single canonical streaming pipeline** - All structural parsing (code fences, tool calls, thinking blocks) happens in one place
2. **MessageStore contains fully renderable segments** - TUI performs zero parsing
3. **TUI is a pure renderer** - Renders segments directly, no structural inference
4. **JSONL persistence is boundary-only** - Only finalized states are persisted
5. **Live, replay, and resume use identical render paths** - All render from MessageStore projection

---

## Goals and Non-Goals

### Goals

- **Single Source of Truth**: One canonical pipeline converts raw LLM deltas to segments
- **Pure Renderer TUI**: TUI renders pre-parsed segments with zero structural parsing
- **Replay Parity**: Replayed sessions produce identical final state as live sessions
- **Clean Separation**: Provider → Pipeline → Store → TUI (unidirectional, no backflow)

### Non-Goals

- **Streaming Animation Replay**: Replay does NOT reproduce per-token growth or intermediate states
- **Full-Fidelity Ledger**: We do NOT persist every delta for replay animation
- **TUI-Driven Parsing**: TUI must NEVER parse markdown fences, assemble tool JSON, or infer structure

### Definition of "Replay Parity"

Replay parity means the replayed session produces:
- Same final message boundaries
- Same segment structure (type, order, content)
- Same ordering of messages
- Same final content

Replay parity does NOT mean:
- Same streaming animation timing
- Same intermediate states during generation
- Per-token replay fidelity

---

## 1. Current Architecture (Broken)

### Problems

1. **Dual Parsing Stages**:
   - `StreamProcessor` (TUI) converts raw chunks → UIEvents
   - `StoreAdapter` (TUI) converts UIEvents → Segments
   - Two places make structural decisions = inconsistency risk

2. **Duplicate Writers**:
   - `StoreAdapter` writes to MessageStore
   - `MemoryManager` writes to MessageStore
   - Same message written twice = duplicates

3. **TUI Does Structural Parsing**:
   - TUI detects code fences via regex
   - TUI assembles tool call JSON
   - TUI infers thinking block boundaries

4. **Missing Segment Types**:
   - No `CodeBlockSegment` - code blocks embedded in text with markdown
   - TUI must parse ``` fences to render code blocks

### Current Data Flow (Broken)

```
LLM Provider
     │
     │ raw streaming chunks
     ▼
┌─────────────────────────────────────────────────────────────┐
│                         TUI LAYER                            │
│  ┌─────────────────┐      ┌─────────────────┐               │
│  │ StreamProcessor │ ───► │  StoreAdapter   │               │
│  │ (parses chunks  │      │ (builds segments│               │
│  │  into UIEvents) │      │  writes to store│               │
│  └─────────────────┘      └────────┬────────┘               │
│         ▲                          │                         │
│         │ STRUCTURAL PARSING       │ WRITES                  │
│         │ IN TUI (BAD!)            │                         │
└─────────┼──────────────────────────┼─────────────────────────┘
          │                          │
          │                          ▼
          │                 ┌─────────────────┐
          │                 │  MessageStore   │◄─── MemoryManager
          │                 │  (DUPLICATES!)  │     ALSO WRITES (BAD!)
          │                 └─────────────────┘
          │
    ┌─────┴─────┐
    │  Agent    │
    │ (yields   │
    │ UIEvents) │
    └───────────┘
```

---

## 2. Proposed Architecture (Fixed)

### Design Principles

1. **Single Canonical Pipeline**: Agent/Core owns all structural parsing
2. **Fully Renderable Segments**: MessageStore contains segments TUI can render directly
3. **Pure Renderer TUI**: TUI maps segments to widgets, nothing else
4. **Boundary-Only Persistence**: Only finalized states written to JSONL
5. **Unified Render Path**: Live, replay, resume all render from MessageStore

### Proposed Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      PROVIDER LAYER                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ LLM Provider Adapters (OpenAI, Anthropic, etc.)         │    │
│  │                                                          │    │
│  │ CONTRACT: Emit raw deltas ONLY                          │    │
│  │ - text_delta: str                                        │    │
│  │ - tool_call_delta: {id, name, arguments_delta}          │    │
│  │ - finish_reason: str | None                              │    │
│  │                                                          │    │
│  │ MUST NOT:                                                │    │
│  │ - Decide message boundaries                              │    │
│  │ - Emit UI structure (segments, code blocks)             │    │
│  │ - Parse markdown or code fences                          │    │
│  └──────────────────────────┬──────────────────────────────┘    │
└─────────────────────────────┼────────────────────────────────────┘
                              │ raw deltas
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT/CORE LAYER                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ StreamingPipeline (SINGLE CANONICAL PARSER)             │    │
│  │ Location: src/core/streaming/pipeline.py                │    │
│  │                                                          │    │
│  │ SOLE RESPONSIBILITY: Convert raw deltas → Segments      │    │
│  │                                                          │    │
│  │ Detects and emits:                                       │    │
│  │ - TextSegment(content)                                   │    │
│  │ - CodeBlockSegment(language, content)                    │    │
│  │ - ToolCallSegment(tool_call_index)                       │    │
│  │ - ToolResultSegment(tool_call_id, status, content)      │    │
│  │ - ThinkingSegment(content)                               │    │
│  │                                                          │    │
│  │ Handles:                                                 │    │
│  │ - Code fence detection (``` parsing)                     │    │
│  │ - Tool call JSON assembly                                │    │
│  │ - Thinking block boundaries (<thinking> tags)           │    │
│  │ - Message finalization                                   │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                              │ Segments + ToolCalls              │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ MemoryManager (SINGLE WRITER)                            │    │
│  │ Location: src/memory/memory_manager.py                   │    │
│  │                                                          │    │
│  │ - Receives finalized messages from StreamingPipeline     │    │
│  │ - ONLY component that writes to MessageStore             │    │
│  │ - Maintains conversation context for LLM                 │    │
│  └──────────────────────────┬──────────────────────────────┘    │
└─────────────────────────────┼────────────────────────────────────┘
                              │ SINGLE WRITER
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PERSISTENCE LAYER                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ MessageStore                                             │    │
│  │ Location: src/session/store/memory_store.py              │    │
│  │                                                          │    │
│  │ Contains FULLY RENDERABLE Messages:                      │    │
│  │ - role: user | assistant | tool                          │    │
│  │ - content: str                                           │    │
│  │ - tool_calls: List[ToolCall]                             │    │
│  │ - tool_call_id: str (for role=tool)                      │    │
│  │ - meta.segments: List[Segment] ◄── FULLY PARSED          │    │
│  │                                                          │    │
│  │ Segment types (TUI renders directly):                    │    │
│  │ - TextSegment(content: str)                              │    │
│  │ - CodeBlockSegment(language: str, content: str)          │    │
│  │ - ToolCallSegment(tool_call_index: int)                  │    │
│  │ - ToolResultSegment(tool_call_id: str, content: str)    │    │
│  │ - ThinkingSegment(content: str)                          │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                              │                                   │
│  ┌──────────────────────────┴──────────────────────────────┐    │
│  │ SessionWriter (BOUNDARY-ONLY POLICY)                     │    │
│  │ Location: src/session/persistence/writer.py              │    │
│  │                                                          │    │
│  │ Persists ONLY finalized boundaries:                      │    │
│  │ - user_message_finalized                                 │    │
│  │ - assistant_message_finalized                            │    │
│  │ - tool_call_finalized (within assistant message)         │    │
│  │ - tool_result_finalized                                  │    │
│  │ - compaction_boundary_finalized                          │    │
│  │ - agent_state_snapshot                                   │    │
│  │                                                          │    │
│  │ Does NOT persist:                                        │    │
│  │ - Streaming deltas                                       │    │
│  │ - Intermediate states                                    │    │
│  │ - Per-token updates                                      │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │ Store Notifications           │
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│       TUI LAYER         │     │     JSONL FILE          │
│  (PURE RENDERER)        │     │  (Boundary-only)        │
│                         │     └─────────────────────────┘
│  Subscribes to store    │
│  notifications          │
│                         │
│  Renders segments       │
│  directly:              │
│  - TextSegment →        │
│    Static(text)         │
│  - CodeBlockSegment →   │
│    CodeBlock(lang,code) │
│  - ToolCallSegment →    │
│    ToolCard(...)        │
│  - ThinkingSegment →    │
│    ThinkingBlock(...)   │
│                         │
│  ZERO PARSING:          │
│  - No ``` detection     │
│  - No JSON assembly     │
│  - No markdown parsing  │
│  - No boundary inference│
└─────────────────────────┘
```

---

## 3. Component Specifications

### 3.1 Provider Adapters (Contract)

**Location:** `src/llm/*.py`

**Contract: Raw Deltas Only**

Providers MUST emit only:
```python
@dataclass
class ProviderDelta:
    """Raw delta from LLM provider. No structural decisions."""
    text_delta: Optional[str] = None           # Raw text chunk
    tool_call_delta: Optional[ToolCallDelta] = None  # Tool call accumulation
    finish_reason: Optional[str] = None        # "stop", "tool_calls", etc.
    usage: Optional[TokenUsage] = None         # Token counts (on finish)

@dataclass
class ToolCallDelta:
    """Incremental tool call data."""
    index: int                    # Tool call index in current message
    id: Optional[str] = None      # Tool call ID (first delta only)
    name: Optional[str] = None    # Function name (first delta only)
    arguments_delta: str = ""     # JSON arguments chunk
```

Providers MUST NOT:
- Parse markdown or code fences
- Decide message boundaries
- Emit UI events or segments
- Assemble complete tool call JSON (pipeline does this)
- Make sentence/paragraph boundary decisions

### 3.2 StreamingPipeline (Canonical Parser)

**Location:** `src/core/streaming/pipeline.py` (NEW)

**Sole Responsibility:** Convert raw provider deltas into fully-parsed segments.

```python
class StreamingPipeline:
    """
    SINGLE CANONICAL PARSER for all structural decisions.

    Converts raw LLM deltas → Message with fully-parsed segments.
    Owned by Agent/Core layer. UI-agnostic.
    """

    def __init__(self, session_id: str, parent_uuid: Optional[str] = None):
        self._session_id = session_id
        self._parent_uuid = parent_uuid
        self._state: Optional[StreamingState] = None

    def process_delta(self, delta: ProviderDelta) -> Optional[Message]:
        """
        Process a single provider delta.

        Returns:
            Message when finalized (finish_reason is set), None otherwise.
        """
        # Initialize state on first delta
        if self._state is None:
            self._state = StreamingState(...)

        # Accumulate text with structural parsing
        if delta.text_delta:
            self._process_text_delta(delta.text_delta)

        # Accumulate tool calls
        if delta.tool_call_delta:
            self._process_tool_call_delta(delta.tool_call_delta)

        # Finalize on finish_reason
        if delta.finish_reason:
            return self._finalize_message(delta.usage)

        return None

    def _process_text_delta(self, text: str) -> None:
        """
        Process text delta with structural parsing.

        Detects and emits:
        - Code blocks (``` fences)
        - Thinking blocks (<thinking> tags)
        - Plain text segments
        """
        # Accumulate into buffer
        self._state.text_buffer += text

        # Detect code fence start: ```language
        if self._detect_code_fence_start():
            self._flush_text_segment()
            self._start_code_block()

        # Detect code fence end: ```
        elif self._state.in_code_block and self._detect_code_fence_end():
            self._end_code_block()

        # Detect thinking start: <thinking>
        elif self._detect_thinking_start():
            self._flush_text_segment()
            self._start_thinking_block()

        # Detect thinking end: </thinking>
        elif self._state.in_thinking and self._detect_thinking_end():
            self._end_thinking_block()

    def _finalize_message(self, usage: Optional[TokenUsage]) -> Message:
        """Build final Message with all segments."""
        # Flush any pending content
        self._flush_pending()

        return Message(
            role="assistant",
            content=self._state.full_text_content,
            tool_calls=self._state.tool_calls,
            meta=MessageMeta(
                uuid=generate_uuid(),
                seq=0,  # Caller sets seq
                timestamp=now_iso(),
                session_id=self._session_id,
                parent_uuid=self._parent_uuid,
                stream_id=self._state.stream_id,
                segments=self._state.segments,  # FULLY PARSED
                token_usage=usage,
            )
        )
```

**Segment Types Emitted:**

```python
# In src/session/models/message.py

@dataclass
class TextSegment(Segment):
    """Plain text content."""
    type: str = "text"
    content: str = ""

@dataclass
class CodeBlockSegment(Segment):
    """Code block with language."""
    type: str = "code_block"
    language: str = ""
    content: str = ""

@dataclass
class ToolCallSegment(Segment):
    """Reference to tool call in message.tool_calls array."""
    type: str = "tool_call"
    tool_call_index: int = 0

@dataclass
class ToolResultSegment(Segment):
    """Tool execution result."""
    type: str = "tool_result"
    tool_call_id: str = ""
    status: str = "success"  # success, error, timeout
    content: str = ""

@dataclass
class ThinkingSegment(Segment):
    """Extended thinking/reasoning content."""
    type: str = "thinking"
    content: str = ""
```

### 3.3 MemoryManager (Single Writer)

**Location:** `src/memory/memory_manager.py`

**Responsibility:** Single writer to MessageStore.

```python
class MemoryManager:
    def __init__(self, ...):
        self._message_store: Optional[MessageStore] = None
        self._streaming_pipeline: Optional[StreamingPipeline] = None

    def start_assistant_stream(self) -> None:
        """Initialize streaming pipeline for new assistant message."""
        self._streaming_pipeline = StreamingPipeline(
            session_id=self._message_store_session_id,
            parent_uuid=self._last_parent_uuid
        )

    def process_provider_delta(self, delta: ProviderDelta) -> Optional[Message]:
        """
        Process provider delta through canonical pipeline.

        Returns:
            Finalized Message when complete, None during streaming.
        """
        if self._streaming_pipeline is None:
            return None

        message = self._streaming_pipeline.process_delta(delta)

        if message:
            # Finalized - write to store (SINGLE WRITER)
            message.meta.seq = self._message_store.next_seq()
            self._message_store.add_message(message)
            self._last_parent_uuid = message.uuid
            self._streaming_pipeline = None

        return message

    def add_user_message(self, content: str) -> Message:
        """Add user message (no streaming, immediate finalization)."""
        message = Message.create_user(
            content=content,
            session_id=self._message_store_session_id,
            parent_uuid=self._last_parent_uuid,
            seq=self._message_store.next_seq()
        )
        self._message_store.add_message(message)
        self._last_parent_uuid = message.uuid
        return message

    def add_tool_result(self, tool_call_id: str, content: str,
                        status: str = "success", ...) -> Message:
        """Add tool result message."""
        message = Message.create_tool(
            tool_call_id=tool_call_id,
            content=content,
            status=status,
            session_id=self._message_store_session_id,
            parent_uuid=self._last_parent_uuid,
            seq=self._message_store.next_seq()
        )
        self._message_store.add_message(message)
        self._last_parent_uuid = message.uuid
        return message
```

### 3.4 SessionWriter (Boundary-Only Policy)

**Location:** `src/session/persistence/writer.py`

**Policy:** Persist only finalized boundaries.

```python
class WritePolicy(Enum):
    """JSONL write policy."""
    BOUNDARY_ONLY = "boundary_only"      # Default: only finalized states
    CRASH_RESILIENT = "crash_resilient"  # Optional: + periodic snapshots

class SessionWriter:
    """
    Writes finalized messages to JSONL.

    Default policy: BOUNDARY_ONLY
    - Persists only when messages are finalized
    - No intermediate streaming states
    - Replay shows final state, not streaming animation
    """

    def __init__(self,
                 file_path: Path,
                 policy: WritePolicy = WritePolicy.BOUNDARY_ONLY):
        self._policy = policy
        self._file_path = file_path

    def bind_to_store(self, store: MessageStore) -> None:
        """Subscribe to store notifications for persistence."""
        store.subscribe(self._on_store_notification)

    def _on_store_notification(self, notification: StoreNotification) -> None:
        """Handle store notification - write if policy allows."""
        match notification.event:
            case StoreEvent.MESSAGE_FINALIZED:
                # Always write finalized messages
                self._write_message(notification.message)

            case StoreEvent.MESSAGE_ADDED:
                # Only write if CRASH_RESILIENT policy
                if self._policy == WritePolicy.CRASH_RESILIENT:
                    self._write_message(notification.message)

            case StoreEvent.MESSAGE_UPDATED:
                # Never write intermediate updates
                pass
```

**Events Persisted (BOUNDARY_ONLY policy):**

| Event | Persisted | Description |
|-------|-----------|-------------|
| `user_message_finalized` | YES | User submits message |
| `assistant_message_finalized` | YES | LLM completes response |
| `tool_result_finalized` | YES | Tool execution completes |
| `compaction_boundary` | YES | Context compaction marker |
| `agent_state_snapshot` | YES | Todo state, etc. |
| `streaming_delta` | NO | Intermediate token |
| `message_updated` | NO | Partial accumulation |

**Crash-Resilient Option (Optional):**

For crash resilience without replay animation, add periodic snapshots:
- Write current message state every N seconds during streaming
- On crash recovery, resume from last snapshot
- Replay still shows final state only

This is NOT for replay fidelity - only for crash recovery.

### 3.5 TUI (Pure Renderer)

**Location:** `src/ui/app.py`

**Responsibility:** Render segments directly. Zero parsing.

```python
class CodingAgentApp(App):
    """
    TUI is a PURE RENDERER.

    - Subscribes to MessageStore notifications
    - Renders segments directly to widgets
    - NEVER parses markdown, code fences, or JSON
    - NEVER decides message structure
    """

    async def _render_message(self, message: Message, container) -> None:
        """Render message by mapping segments to widgets."""
        widget = AssistantMessage() if message.is_assistant else UserMessage()
        await container.mount(widget)

        if message.is_assistant and message.meta.segments:
            for segment in message.meta.segments:
                await self._render_segment(segment, widget, message)
        else:
            # Fallback: render content directly
            await widget.add_text(message.content)

    async def _render_segment(self, segment: Segment, widget, message: Message) -> None:
        """
        Render a single segment to the appropriate widget.

        NO PARSING - direct mapping from segment type to widget.
        """
        match segment:
            case TextSegment(content=text):
                # Direct text render - no markdown parsing
                await widget.add_text(text)

            case CodeBlockSegment(language=lang, content=code):
                # Direct code block - no fence detection needed
                await widget.add_code_block(lang, code)

            case ToolCallSegment(tool_call_index=idx):
                # Look up tool call from message
                tc = message.tool_calls[idx]
                card = widget.add_tool_card(tc.id, tc.function.name, tc.arguments)
                self._tool_cards[tc.id] = card

            case ToolResultSegment(tool_call_id=tcid, content=content, status=status):
                # Update existing tool card
                if tcid in self._tool_cards:
                    if status == "success":
                        self._tool_cards[tcid].set_result(content)
                    else:
                        self._tool_cards[tcid].set_error(content)

            case ThinkingSegment(content=text):
                # Direct thinking block render
                await widget.add_thinking(text)
```

---

## 4. Unified Render Path

All three modes use identical render path:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   LIVE MODE     │     │  REPLAY MODE    │     │  RESUME MODE    │
│                 │     │                 │     │                 │
│ Provider deltas │     │ Load JSONL      │     │ Load JSONL      │
│       │         │     │       │         │     │       │         │
│       ▼         │     │       ▼         │     │       ▼         │
│ StreamingPipe-  │     │ MessageStore    │     │ MessageStore    │
│ line            │     │ (projection)    │     │ (projection)    │
│       │         │     │       │         │     │       │         │
│       ▼         │     │       │         │     │       │         │
│ MemoryManager   │     │       │         │     │ MemoryManager   │
│       │         │     │       │         │     │ (context)       │
│       ▼         │     │       │         │     │       │         │
│ MessageStore    │     │       │         │     │       │         │
└───────┬─────────┘     └───────┬─────────┘     └───────┬─────────┘
        │                       │                       │
        └───────────────────────┴───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Store Notification    │
                    │ (MESSAGE_FINALIZED)   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │ TUI._render_message() │
                    │ (identical for all)   │
                    └───────────────────────┘
```

**Guarantee:** If JSONL contains identical messages, replay/resume produces identical UI state as live.

---

## 5. File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `src/core/streaming/__init__.py` | **NEW** | Package init |
| `src/core/streaming/pipeline.py` | **NEW** | StreamingPipeline (canonical parser) |
| `src/core/streaming/state.py` | **NEW** | StreamingState dataclass |
| `src/session/models/message.py` | **MODIFY** | Add CodeBlockSegment, ToolResultSegment |
| `src/memory/memory_manager.py` | **MODIFY** | Add process_provider_delta(), remove add_assistant_message() store writes |
| `src/llm/base.py` | **MODIFY** | Define ProviderDelta contract |
| `src/llm/openai_backend.py` | **MODIFY** | Emit ProviderDelta (raw deltas only) |
| `src/llm/anthropic_backend.py` | **MODIFY** | Emit ProviderDelta (raw deltas only) |
| `src/ui/stream_processor.py` | **DELETE** | Replaced by StreamingPipeline |
| `src/ui/store_adapter.py` | **MODIFY** | Remove segment building, keep for backward compat |
| `src/ui/app.py` | **MODIFY** | Render from segments only, remove structural parsing |
| `src/session/persistence/writer.py` | **MODIFY** | Add WritePolicy enum, default BOUNDARY_ONLY |

---

## 6. Migration Path

### Phase 1: Add New Components
1. Create `src/core/streaming/pipeline.py`
2. Add `CodeBlockSegment`, `ToolResultSegment` to message.py
3. Define `ProviderDelta` contract in `src/llm/base.py`

### Phase 2: Update MemoryManager
1. Add `process_provider_delta()` method
2. Integrate StreamingPipeline
3. Remove duplicate store writes from existing methods

### Phase 3: Update Providers
1. Modify OpenAI backend to emit `ProviderDelta`
2. Modify Anthropic backend to emit `ProviderDelta`
3. Verify providers don't make structural decisions

### Phase 4: Update TUI
1. Remove `StreamProcessor` (or keep as thin adapter)
2. Update `_render_segment()` to handle all segment types
3. Remove all markdown/fence parsing from TUI

### Phase 5: Update SessionWriter
1. Add `WritePolicy` enum
2. Default to `BOUNDARY_ONLY`
3. Verify only finalized events persisted

### Phase 6: Testing
1. Unit tests for StreamingPipeline
2. Integration tests for full flow
3. Replay parity tests (final state comparison)
4. Regression tests for existing JSONL files

---

## 7. Open Questions

1. **Backward Compatibility**: How do we handle existing JSONL files without CodeBlockSegment?
   - Option A: Migration script to reparse content into segments
   - Option B: Fallback rendering path for legacy messages

2. **Streaming UI Feedback**: With boundary-only persistence, how does TUI show streaming progress?
   - TUI still receives deltas for live display (not persisted)
   - Store notifications are for final state only

3. **Code Block Language Detection**: If LLM doesn't specify language after ```, how do we detect?
   - Option A: Default to "text"
   - Option B: Heuristic detection (risky - adds parsing back)
   - Recommendation: Option A (default to "text")

4. **Tool Call Streaming**: Tool calls stream incrementally. When do we emit ToolCallSegment?
   - On first delta: emit segment with index
   - On subsequent deltas: update tool_calls array
   - On finish: finalize with complete arguments

5. **Thinking Block Detection**: Currently uses `<thinking>` tags. Is this stable across providers?
   - May need provider-specific detection
   - Or standardize on single format

---

## Appendix A: Segment Type Reference

| Segment Type | Fields | Description | TUI Widget |
|--------------|--------|-------------|------------|
| `TextSegment` | `content: str` | Plain text | `Static(text)` |
| `CodeBlockSegment` | `language: str, content: str` | Code with syntax highlighting | `CodeBlock(lang, code)` |
| `ToolCallSegment` | `tool_call_index: int` | Reference to tool_calls[i] | `ToolCard(...)` |
| `ToolResultSegment` | `tool_call_id: str, status: str, content: str` | Tool execution result | Updates `ToolCard` |
| `ThinkingSegment` | `content: str` | Extended thinking/reasoning | `ThinkingBlock(...)` |

---

## Appendix B: JSONL Message Format (v2.1 with Segments)

```json
{
  "role": "assistant",
  "content": "Here's a Python function:\n\ndef hello():\n    print(\"Hello\")\n\nLet me run it for you.",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "run_code",
        "arguments": "{\"code\": \"print('Hello')\"}"
      }
    }
  ],
  "meta": {
    "uuid": "msg-uuid-123",
    "seq": 5,
    "timestamp": "2026-01-21T10:30:00Z",
    "session_id": "session-abc",
    "stream_id": "stream-xyz",
    "segments": [
      {"type": "text", "content": "Here's a Python function:\n"},
      {"type": "code_block", "language": "python", "content": "def hello():\n    print(\"Hello\")"},
      {"type": "text", "content": "\nLet me run it for you."},
      {"type": "tool_call", "tool_call_index": 0}
    ]
  }
}
```
