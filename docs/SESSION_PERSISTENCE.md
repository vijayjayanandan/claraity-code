# Session Persistence Module (Schema v2.1)

> JSONL-based session persistence for the ClarAIty CLI coding agent.

**Version:** Schema v2.1
**Location:** `src/session/`
**Last Updated:** 2026-01-19

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module Structure](#module-structure)
3. [Message Schema](#message-schema)
4. [JSONL File Format](#jsonl-file-format)
5. [Provider Translation](#provider-translation)
6. [Streaming Collapse](#streaming-collapse)
7. [Compaction Handling](#compaction-handling)
8. [API Reference](#api-reference)
9. [Usage Examples](#usage-examples)
10. [Design Decisions](#design-decisions)

---

## Architecture Overview

The session persistence module implements a **Ledger/Projection** architecture:

```
                    LEDGER (Source of Truth)
                    +--------------------+
                    |  session.jsonl     |
                    |  (append-only)     |
                    +--------------------+
                             |
                             | parse_file_iter()
                             v
                    +--------------------+
                    |  MessageStore      |
                    |  (projection)      |
                    +--------------------+
                    | - Collapsed        |
                    | - Indexed          |
                    | - Filtered         |
                    +--------------------+
                             |
                             | subscribe()
                             v
                    +--------------------+
                    |  SessionWriter     |
                    |  (reactive)        |
                    +--------------------+
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Ledger** | JSONL file - append-only, full fidelity, immutable history |
| **Projection** | MessageStore - collapsed, indexed, filtered view |
| **Seq** | Sequence number = line number during replay, monotonic counter at runtime |
| **stream_id** | Collapse key for streaming messages (assistant messages with same stream_id merge) |

### Data Flow

1. **Write Path:** Message -> Store -> (subscription) -> Writer -> JSONL
2. **Read Path:** JSONL -> Parser -> Store (with collapse)
3. **LLM Context:** Store -> `get_llm_context()` -> OpenAI format (meta stripped)

---

## Module Structure

```
src/session/
|-- __init__.py           # Public API exports
|
|-- models/
|   |-- __init__.py       # Model exports
|   |-- base.py           # Utilities: generate_uuid, now_iso, SessionContext
|   |-- message.py        # Unified Message class with segments
|
|-- store/
|   |-- __init__.py       # Store exports
|   |-- memory_store.py   # MessageStore with indexes and projections
|
|-- persistence/
|   |-- __init__.py       # Persistence exports
|   |-- parser.py         # JSONL parser with tolerant last-line handling
|   |-- writer.py         # Thread-safe async writer with drain-on-close
|
|-- providers/
|   |-- __init__.py       # Provider exports
|   |-- openai.py         # OpenAI response translator
|   |-- anthropic.py      # Anthropic response translator
|
|-- manager/
    |-- __init__.py       # Manager exports
    |-- session_manager.py # Session lifecycle management
```

---

## Message Schema

The schema uses **OpenAI message format as the canonical shape** with ClarAIty extensions in the `meta` field.

### Message Structure

```python
@dataclass
class Message:
    # OpenAI Core (sent to LLM)
    role: str                              # "system" | "user" | "assistant" | "tool"
    content: Optional[str]                 # Message text (null for tool-only responses)
    tool_calls: List[ToolCall]             # Tool invocations (assistant only)
    tool_call_id: Optional[str]            # Tool result reference (tool only)

    # ClarAIty Extensions
    meta: MessageMeta                      # Stripped for LLM context

    # Runtime Only (NOT persisted)
    _raw_response: Optional[Dict[str, Any]]
```

### MessageMeta Fields

```python
@dataclass
class MessageMeta:
    # Required
    schema_version: int          # Current: 1
    uuid: str                    # Unique message identifier
    seq: int                     # Sequence number (ordering key)
    timestamp: str               # ISO 8601 timestamp
    session_id: str              # Session identifier
    parent_uuid: Optional[str]   # Parent message (conversation threading)
    is_sidechain: bool           # Alternate response (not mainline)

    # Streaming
    stream_id: Optional[str]             # Collapse key for streaming
    provider_message_id: Optional[str]   # Provider's message ID

    # Provider
    provider: Optional[str]      # "anthropic" | "openai" | "ollama" | "local"
    model: Optional[str]         # Model identifier

    # Completion
    stop_reason: Optional[str]   # "complete" | "tool_use" | "max_tokens" | "streaming" | "error"
    usage: Optional[TokenUsage]  # Token usage statistics

    # Content Ordering (v2.1)
    segments: Optional[List[Segment]]  # Preserves interleaving order

    # Thinking
    thinking: Optional[str]              # Extended thinking content
    thinking_signature: Optional[str]    # Thinking signature (Anthropic)

    # Tool Execution (role=tool only)
    status: Optional[str]        # "success" | "error" | "timeout" | "cancelled"
    duration_ms: Optional[int]   # Execution duration
    exit_code: Optional[int]     # Process exit code
    truncated: Optional[bool]    # Output was truncated

    # System Events
    event_type: Optional[str]            # "compact_boundary" | "turn_duration" | "session_start"
    include_in_llm_context: Optional[bool]

    # Compaction
    pre_tokens: Optional[int]            # Tokens before compaction
    logical_parent_uuid: Optional[str]   # Parent before compaction

    # UI Hints
    is_compact_summary: Optional[bool]           # This is a compaction summary
    is_visible_in_transcript_only: Optional[bool] # Exclude from LLM context

    # Extensible
    extra: Optional[Dict[str, Any]]
```

### Segment Types

Segments preserve the original interleaving order of content blocks:

```python
@dataclass
class TextSegment:
    type: str = "text"       # Always "text"
    content: str             # Text content

@dataclass
class ToolCallSegment:
    type: str = "tool_call"  # Always "tool_call"
    tool_call_index: int     # Index into tool_calls array

@dataclass
class ThinkingSegment:
    type: str = "thinking"   # Always "thinking"
    content: str             # Thinking content
```

### ToolCall Structure

```python
@dataclass
class ToolCall:
    id: str                      # Unique tool call ID
    function: ToolCallFunction   # Function details
    type: str = "function"       # Always "function"
    meta: Dict[str, Any]         # ClarAIty extensions (optional)

@dataclass
class ToolCallFunction:
    name: str        # Function name
    arguments: str   # JSON string of arguments
```

### TokenUsage

```python
@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
```

---

## JSONL File Format

Each line in the JSONL file is a complete JSON object representing one message or snapshot.

### Message Line Example

```json
{
  "role": "user",
  "content": "Please help me write a Python function",
  "meta": {
    "schema_version": 1,
    "uuid": "550e8400-e29b-41d4-a716-446655440000",
    "seq": 1,
    "timestamp": "2026-01-19T10:30:00.000Z",
    "session_id": "abc123-def456",
    "parent_uuid": null,
    "is_sidechain": false
  }
}
```

### Assistant with Tool Calls

```json
{
  "role": "assistant",
  "content": "I'll help you create that function. Let me write a file for you.",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "write_file",
        "arguments": "{\"path\": \"example.py\", \"content\": \"def hello(): pass\"}"
      }
    }
  ],
  "meta": {
    "schema_version": 1,
    "uuid": "550e8400-e29b-41d4-a716-446655440001",
    "seq": 2,
    "timestamp": "2026-01-19T10:30:05.000Z",
    "session_id": "abc123-def456",
    "parent_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "is_sidechain": false,
    "stream_id": "stream_a1b2c3d4e5f6",
    "provider": "anthropic",
    "model": "claude-opus-4-5-20251101",
    "stop_reason": "tool_use",
    "usage": {
      "input_tokens": 150,
      "output_tokens": 75
    },
    "segments": [
      {"type": "text", "content": "I'll help you create that function. Let me write a file for you."},
      {"type": "tool_call", "tool_call_index": 0}
    ]
  }
}
```

### Tool Result

```json
{
  "role": "tool",
  "content": "File written successfully: example.py (25 bytes)",
  "tool_call_id": "call_abc123",
  "meta": {
    "schema_version": 1,
    "uuid": "550e8400-e29b-41d4-a716-446655440002",
    "seq": 3,
    "timestamp": "2026-01-19T10:30:06.000Z",
    "session_id": "abc123-def456",
    "parent_uuid": "550e8400-e29b-41d4-a716-446655440001",
    "is_sidechain": false,
    "status": "success",
    "duration_ms": 45
  }
}
```

### Compaction Boundary

```json
{
  "role": "system",
  "content": "[Compaction boundary - 150 messages summarized]",
  "meta": {
    "schema_version": 1,
    "uuid": "550e8400-e29b-41d4-a716-446655440100",
    "seq": 100,
    "timestamp": "2026-01-19T11:00:00.000Z",
    "session_id": "abc123-def456",
    "parent_uuid": null,
    "is_sidechain": false,
    "event_type": "compact_boundary",
    "include_in_llm_context": false,
    "pre_tokens": 50000
  }
}
```

### File Snapshot (Non-Message)

```json
{
  "type": "file_snapshot",
  "uuid": "550e8400-e29b-41d4-a716-446655440200",
  "timestamp": "2026-01-19T10:30:00.000Z",
  "session_id": "abc123-def456",
  "snapshots": [
    {
      "file_path": "/project/example.py",
      "content": "def hello(): pass",
      "hash": "abc123..."
    }
  ],
  "backups": []
}
```

---

## Provider Translation

### OpenAI Translation

OpenAI is the primary/canonical format. Translation is straightforward since the schema matches.

**Response to Message (`from_openai`):**

```python
from src.session import from_openai

# Convert OpenAI API response to Message
message = from_openai(
    response=api_response,
    session_id="abc123",
    parent_uuid="parent-uuid",
    seq=store.next_seq(),
    stream_id=None  # Auto-generated if not provided
)
```

**Messages to API format (`to_openai`):**

```python
from src.session import to_openai

# Convert Messages to OpenAI API request format
api_messages = to_openai(messages)
# Returns list of dicts with meta stripped
```

**Stop Reason Mapping:**

| OpenAI finish_reason | ClarAIty stop_reason |
|---------------------|---------------------|
| "stop" | "complete" |
| "tool_calls" | "tool_use" |
| "length" | "max_tokens" |
| "content_filter" | "stop_sequence" |
| None | "streaming" |

### Anthropic Translation

Anthropic responses require flattening content blocks into the OpenAI-compatible structure.

**Response to Message (`from_anthropic`):**

```python
from src.session import from_anthropic

# Convert Anthropic API response to Message
message = from_anthropic(
    response=api_response,
    session_id="abc123",
    parent_uuid="parent-uuid",
    seq=store.next_seq(),
    stream_id=None
)
```

**Content Block Mapping:**

| Anthropic Block | Unified Format |
|-----------------|----------------|
| `text` | Concatenated to `content` |
| `tool_use` | Added to `tool_calls[]` |
| `thinking` | Stored in `meta.thinking` |

**Messages to Anthropic format (`to_anthropic`):**

```python
from src.session import to_anthropic, get_system_prompt

# Get system prompt (Anthropic takes it separately)
system = get_system_prompt(messages)

# Convert Messages to Anthropic format
api_messages = to_anthropic(messages)
```

**Anthropic-Specific Handling:**
- System messages are excluded from the messages array (use `get_system_prompt()`)
- Tool results become `user` role with `tool_result` content type
- Thinking blocks are expanded back to content blocks

**Stop Reason Mapping:**

| Anthropic stop_reason | ClarAIty stop_reason |
|----------------------|---------------------|
| "end_turn" | "complete" |
| "tool_use" | "tool_use" |
| "max_tokens" | "max_tokens" |
| "stop_sequence" | "stop_sequence" |
| None | "streaming" |

---

## Streaming Collapse

The MessageStore collapses streaming messages using `stream_id` as the key.

### Behavior

1. **Same stream_id:** Later messages replace earlier ones
2. **Different seq:** Each streaming update gets a new seq
3. **Final state:** Only the final accumulated message persists in the projection

```
JSONL File (Ledger):         Memory Store (Projection):
+-------------------+        +-------------------+
| seq=1 stream_a    | ---+   |                   |
| seq=2 stream_a    |    |   | seq=3 stream_a    |  (collapsed)
| seq=3 stream_a    | ---+-->|                   |
| seq=4 stream_b    | ------>| seq=4 stream_b    |
+-------------------+        +-------------------+
```

### Implementation

```python
# In MessageStore.add_message():
if message.is_assistant:
    stream_id = message.get_collapse_key()  # Returns meta.stream_id
    if stream_id and stream_id in self._by_stream_id:
        # Replace previous entry
        old_uuid = self._by_stream_id[stream_id]
        self._remove_from_indexes(old_uuid)
        del self._messages[old_uuid]
        # Free old seq slot
        del self._by_seq[old_seq]
```

### Why stream_id (not provider_message_id)?

- **provider_message_id:** Set by the provider, may not be available during streaming
- **stream_id:** Generated client-side, immediately available, consistent across chunks

---

## Compaction Handling

Compaction reduces token usage by summarizing old messages while preserving full history in the JSONL.

### Compaction Boundary

A system message marks where compaction occurred:

```python
Message.create_system(
    content="[Compaction: 150 messages summarized]",
    session_id=session_id,
    seq=store.next_seq(),
    event_type="compact_boundary",
    include_in_llm_context=False,
    pre_tokens=50000
)
```

### Store Projections

The store provides compaction-aware views:

```python
# Transcript view (for UI)
messages = store.get_transcript_view(include_pre_compaction=False)
# Returns: messages with seq > compact_boundary_seq

# LLM context (for API calls)
context = store.get_llm_context(max_messages=100)
# Returns: post-compaction messages, meta stripped, OpenAI format

# Access boundary marker
boundary = store.get_compact_boundary()
# Returns: the compact_boundary system message (for banner rendering)

# Check compaction status
if store.has_compaction():
    summary = store.get_compact_summary()
```

### Exclusion Rules

Messages excluded from LLM context:

1. `meta.include_in_llm_context == False`
2. `meta.event_type in ("compact_boundary", "turn_duration")`
3. `meta.is_visible_in_transcript_only == True`
4. `seq <= last_compact_boundary_seq` (pre-compaction)

---

## API Reference

### Message Factory Methods

```python
# Create user message
msg = Message.create_user(
    content="Hello",
    session_id="abc123",
    parent_uuid="parent-uuid",
    seq=store.next_seq()
)

# Create assistant message
msg = Message.create_assistant(
    content="Hi there!",
    session_id="abc123",
    parent_uuid="user-uuid",
    seq=store.next_seq(),
    tool_calls=[...],
    stream_id="stream_abc123"
)

# Create tool result
msg = Message.create_tool(
    tool_call_id="call_abc",
    content="Result...",
    session_id="abc123",
    parent_uuid="assistant-uuid",
    seq=store.next_seq(),
    status="success",
    duration_ms=150
)

# Create system message
msg = Message.create_system(
    content="System event",
    session_id="abc123",
    seq=store.next_seq(),
    event_type="compact_boundary"
)
```

### Message Methods

```python
# Serialization
dict_data = message.to_dict()       # Full serialization (for JSONL)
llm_data = message.to_llm_dict()    # OpenAI format (meta stripped)

# Deserialization
message = Message.from_dict(data, seq=line_number)

# Role checks
message.is_user      # bool
message.is_assistant # bool
message.is_tool      # bool
message.is_system    # bool

# Content access
text = message.get_text_content()   # Returns "" if None
has_tools = message.has_tool_calls()
segments = message.get_ordered_content()  # Returns segments or synthesized
tool_ids = message.get_tool_call_ids()

# Streaming
collapse_key = message.get_collapse_key()  # Returns stream_id for assistant

# Context inclusion
include = message.should_include_in_context  # bool
```

### MessageStore

```python
from src.session import MessageStore

store = MessageStore()

# Add message (handles collapse, indexes)
store.add_message(message)

# Get next sequence number (store owns seq authority)
seq = store.next_seq()

# Lookups
msg = store.get_message(uuid)
msg = store.get_by_seq(seq)

# Ordering
messages = store.get_ordered_messages()
messages = store.get_messages_after_seq(50)

# Tool linkage (O(1))
result = store.get_tool_result(tool_call_id)
tool_ids = store.get_tool_calls_for_assistant(assistant_uuid)

# Projections
transcript = store.get_transcript_view(include_pre_compaction=False)
context = store.get_llm_context(max_messages=100)
context_msgs = store.get_llm_context_messages()

# Sidechains
mainline = store.get_mainline_messages()
sidechains = store.get_sidechains(parent_uuid)
count = store.get_sidechain_count(parent_uuid)

# Threading
children = store.get_children(uuid)
thread = store.get_thread(uuid)  # Root to UUID

# Compaction
has_compact = store.has_compaction()
boundary = store.get_compact_boundary()
summary = store.get_compact_summary()

# Subscriptions (reactive UI)
unsubscribe = store.subscribe(callback)
store._notify(notification)

# Bulk operations
store.begin_bulk_load()
store.end_bulk_load()
store.clear()

# Properties
store.session_id
store.message_count
store.is_empty
store.max_seq
```

### SessionWriter

```python
from src.session import SessionWriter

writer = SessionWriter(
    file_path="session.jsonl",
    on_error=error_callback,
    drain_timeout=5.0
)

# Lifecycle (async)
await writer.open()
writer.bind_to_store(store)  # Auto-persist on MESSAGE_ADDED
await writer.close()         # Drains pending writes

# Manual writes
result = await writer.write_message(message)
result = await writer.write_snapshot(snapshot)
result = await writer.write_raw(dict_data)
await writer.flush()

# Properties
writer.file_path
writer.total_writes
writer.total_bytes
writer.is_open
writer.pending_writes
```

### SessionManager

```python
from src.session import SessionManager

manager = SessionManager(
    sessions_dir=".claraity/sessions",
    version="1.0.0"
)

# Create new session
info = manager.create_session(
    cwd="/project",
    git_branch="main",
    slug="swift-fox-123"
)

# Resume existing session
info = manager.resume_session(
    session_id="abc123",
    on_progress=lambda current, total: print(f"{current}/{total}")
)

# Start writer (async)
await manager.start_writer()

# Close session
await manager.close()

# Discovery
sessions = manager.list_sessions(limit=10)
recent = manager.get_recent_session()
exists = manager.session_exists(session_id)
path = manager.get_session_file_path(session_id)
deleted = manager.delete_session(session_id)

# Accessors
manager.store       # MessageStore
manager.context     # SessionContext
manager.info        # SessionInfo
manager.is_active   # bool
manager.sessions_dir
```

### Parser Functions

```python
from src.session import (
    parse_line,
    parse_file_iter,
    load_session,
    validate_session_file,
    get_session_info,
    ParseError
)

# Parse single line
item = parse_line(json_line, line_number=1)
# Returns Message | FileHistorySnapshot | None

# Streaming iterator
for line_num, item in parse_file_iter(path, tolerant_last_line=True):
    if isinstance(item, Message):
        store.add_message(item)

# Load complete session
store = load_session(
    file_path="session.jsonl",
    store=existing_store,  # Optional
    on_progress=callback
)

# Validate file
is_valid, errors = validate_session_file(path)

# Quick info
info = get_session_info(path)
# Returns: {"session_id": ..., "first_timestamp": ..., "line_count": ...}
```

### Convenience Functions

```python
from src.session import create_session_file, append_to_session

# Create empty file
path = create_session_file("session.jsonl")

# One-off append (async)
result = await append_to_session("session.jsonl", message)
```

---

## Usage Examples

### Basic Session Workflow

```python
import asyncio
from src.session import (
    SessionManager,
    Message,
    from_anthropic,
)

async def main():
    # Initialize manager
    manager = SessionManager(sessions_dir=".claraity/sessions")

    # Create new session
    info = manager.create_session(cwd="/my/project")
    print(f"Session: {info.session_id}")

    # Start writer
    await manager.start_writer()

    # Add user message
    user_msg = Message.create_user(
        content="Hello, Claude!",
        session_id=info.session_id,
        parent_uuid=None,
        seq=manager.store.next_seq()
    )
    manager.store.add_message(user_msg)

    # Simulate API response
    api_response = {
        "content": [{"type": "text", "text": "Hello! How can I help?"}],
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 8}
    }

    # Convert and add assistant message
    assistant_msg = from_anthropic(
        response=api_response,
        session_id=info.session_id,
        parent_uuid=user_msg.uuid,
        seq=manager.store.next_seq()
    )
    manager.store.add_message(assistant_msg)

    # Get LLM context for next API call
    context = manager.store.get_llm_context()
    print(f"Context messages: {len(context)}")

    # Close session
    await manager.close()

asyncio.run(main())
```

### Resume Existing Session

```python
async def resume_and_continue():
    manager = SessionManager()

    # Find most recent session
    recent = manager.get_recent_session()
    if not recent:
        print("No sessions found")
        return

    # Resume with progress
    def on_progress(current, total):
        print(f"Loading: {current}/{total}")

    info = manager.resume_session(recent, on_progress=on_progress)
    print(f"Resumed {info.message_count} messages")

    # Start writer for new messages
    await manager.start_writer()

    # Continue conversation...
    # manager.store.add_message(...)

    await manager.close()
```

### Reactive UI Updates

```python
from src.session import MessageStore, StoreEvent, StoreNotification

def on_store_event(notification: StoreNotification):
    if notification.event == StoreEvent.MESSAGE_ADDED:
        msg = notification.message
        print(f"[{msg.role}] {msg.get_text_content()[:50]}...")
    elif notification.event == StoreEvent.BULK_LOAD_COMPLETE:
        count = notification.metadata.get("message_count", 0)
        print(f"Loaded {count} messages")

store = MessageStore()
unsubscribe = store.subscribe(on_store_event)

# Messages trigger callbacks automatically
store.add_message(message)

# Cleanup
unsubscribe()
```

### Custom Provider Translation

```python
from src.session import (
    Message, MessageMeta, ToolCall, ToolCallFunction,
    generate_uuid, now_iso, generate_stream_id
)

def from_custom_provider(response: dict, session_id: str, parent_uuid: str, seq: int) -> Message:
    """Convert custom provider response to Message."""

    # Extract content from your provider's format
    content = response.get("output", {}).get("text", "")

    # Convert tool calls if present
    tool_calls = []
    for tc in response.get("actions", []):
        tool_calls.append(ToolCall(
            id=tc["id"],
            function=ToolCallFunction(
                name=tc["name"],
                arguments=json.dumps(tc["params"])
            )
        ))

    return Message(
        role="assistant",
        content=content or None,
        tool_calls=tool_calls,
        meta=MessageMeta(
            uuid=generate_uuid(),
            seq=seq,
            timestamp=now_iso(),
            session_id=session_id,
            parent_uuid=parent_uuid,
            is_sidechain=False,
            stream_id=generate_stream_id(),
            provider="custom",
            model=response.get("model"),
            stop_reason="complete" if response.get("done") else "streaming"
        )
    )
```

---

## Design Decisions

### 1. OpenAI as Canonical Format

**Decision:** Use OpenAI message format (role, content, tool_calls, tool_call_id) as the base schema.

**Rationale:**
- Most LLM providers support or translate to OpenAI format
- Simple, flat structure is easy to serialize and query
- Anthropic content blocks can be flattened without data loss
- `meta` field provides escape hatch for provider-specific data

**Tradeoffs:**
- Anthropic's rich content blocks are denormalized
- Must preserve interleaving order separately (`meta.segments`)

### 2. Store Owns Seq Authority (v3.1 Patch 1)

**Decision:** `MessageStore.next_seq()` is the single authority for sequence numbers.

**Rationale:**
- Avoids race conditions with global counters
- Store knows its current max from loaded messages
- New sessions start at seq=0 naturally
- Resumed sessions continue from loaded max

**Implementation:**
```python
def next_seq(self) -> int:
    with self._lock:
        self._max_seq += 1
        return self._max_seq
```

### 3. Collapse by stream_id (v2.1)

**Decision:** Use client-generated `stream_id` for streaming collapse, not `provider_message_id`.

**Rationale:**
- `provider_message_id` may not be available until stream completes
- `stream_id` is generated immediately, available on first chunk
- Provides reliable collapse key throughout streaming

### 4. _raw_response is Runtime-Only

**Decision:** Store original provider response in `_raw_response` but exclude from serialization.

**Rationale:**
- Useful for debugging during runtime
- Contains redundant data (already extracted to fields)
- JSONL file stays compact and provider-agnostic

### 5. Tolerant Last-Line Parsing

**Decision:** Skip corrupted last line by default during file parsing.

**Rationale:**
- Crash recovery: process may have died mid-write
- Better to lose one partial message than fail entire load
- Use `tolerant_last_line=False` for strict validation

### 6. Drain-on-Close (v3.1 Patch 3)

**Decision:** Writer waits for pending writes before closing.

**Rationale:**
- Prevents data loss when closing during active writes
- Configurable timeout (default 5s)
- Logs warning if drain times out

---

## See Also

- `docs/CLARAITY_SESSION_SCHEMA_v2.1.md` - Original schema specification
- `docs/CLAUDE_CODE_REFACTOR_INSTRUCTIONS.md` - Refactoring guidelines
- `src/observability/` - Logging infrastructure
- `src/memory/compaction/` - Compaction implementation
