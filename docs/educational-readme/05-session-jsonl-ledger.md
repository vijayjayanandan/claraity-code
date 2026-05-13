# Chapter 5: Never Losing Work -- The Session Ledger

> **The problem:** Everything we've built so far lives in memory. The moment you close VS Code, it's gone. The conversation, the tool calls, the decisions made, the files changed -- all of it vanishes. An agent that forgets everything every time you close the editor isn't a coding partner, it's a notepad that resets itself.

---

## First: Two Concepts You Need to Know

Before diving into how sessions are saved, you need two mental models: **turns** and **streams**. Everything else in this chapter builds on them.

---

### What Is a Turn?

A **turn** is one round of the conversation.

You say something. The agent does everything it needs to do in response -- reads files, runs commands, thinks, writes code. Then it replies. That entire cycle -- your message plus all the agent's activity -- is one turn.

Think of it like a board game: you move your piece (one turn), then the opponent moves their piece (one turn). In a conversation with the agent, you each take turns.

In the JSONL file, one turn looks like multiple lines:

```jsonl
{"role": "user",      "content": "Refactor the auth module"}
{"role": "assistant", "content": "I'll start by reading the current implementation..."}
{"role": "assistant", "content": null, "tool_calls": [{"name": "read_file", ...}]}
{"role": "tool",      "content": "...file contents..."}
{"role": "assistant", "content": "I can see the issue. Here's my plan..."}
```

Five lines. One turn. The user spoke once; the agent read a file, thought about it, and replied.

The codebase tracks this explicitly:

```python
# src/memory/memory_manager.py, line 191
def add_user_message(self, content, ...):
    self._current_turn_id += 1  # Each user message starts a new turn
```

And `MessageStore` knows what belongs to a turn:

```python
# src/session/store/memory_store.py, line 836
def get_turn_uuids(self, user_message_uuid):
    # A "turn" = user message + all subsequent assistant/tool messages
    # until the next user message
```

This is what allows features like **"delete this turn"** -- the store knows exactly which messages to remove.

---

### What Is a Stream?

A **stream** is how the agent's response arrives.

The LLM doesn't wait until it has finished thinking, then send you the whole reply at once. It sends words one at a time, in real time -- like someone typing in front of you. That continuous flow of partial content is called a **stream**.

Think of it this way:
- **No streaming:** You wait 30 seconds staring at a blank screen, then the entire reply appears instantly.
- **Streaming:** Words appear as they're generated, one by one, like a typewriter.

One turn can contain multiple streams. Here's why: if the agent needs to call tools, it streams a response ("I'll read that file..."), then the tools run (not a stream -- that's a separate execution), then it streams another response ("Here's what I found..."). Two streams, one turn.

A stream is identified by a `stream_id`. Every chunk that arrives for the same response shares the same `stream_id`, so the system knows to assemble them together.

```python
# src/memory/memory_manager.py, line 504
def start_assistant_stream(self, provider=None, model=None):
    # Called once at the start of each new assistant response
    self._streaming_pipeline = StreamingPipeline(
        session_id=self._message_store_session_id,
        parent_uuid=self._last_parent_uuid,
        ...
    )
```

---

## The Core Idea: A Ledger, Not a Database

Now that you understand turns and streams, here's how ClarAIty saves them.

ClarAIty persists every session as a **JSONL file** (JSON Lines) -- one JSON object per line, appended in order, never modified. This is an intentional design choice called an **append-only ledger**, the same pattern used by financial systems, Kafka, and git itself.

```
.claraity/
  sessions/
    session_abc123.jsonl   <- each session is one file
    session_def456.jsonl
```

A real session file looks like this:

```jsonl
{"role": "user", "content": "Refactor the auth module", "meta": {"session_id": "abc123", "timestamp": "2025-04-17T10:00:00Z", "seq": 1}}
{"role": "assistant", "content": "I'll start by reading the current implementation...", "meta": {"session_id": "abc123", "seq": 2}}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "name": "read_file", "arguments": {"file_path": "src/auth.py"}}], "meta": {"seq": 3}}
{"role": "tool", "tool_call_id": "call_1", "content": "...file contents...", "meta": {"seq": 4}}
{"role": "assistant", "content": "I can see the issue. Let me fix the login function...", "meta": {"seq": 5, "stop_reason": "end_turn"}}
```

Each line is a complete, self-contained JSON object. The file grows forward -- nothing is ever deleted or rewritten.

---

## Why JSONL? Why Not a Database?

This is one of the most deliberate architectural decisions in ClarAIty:

| Property | JSONL Ledger | SQLite Database |
|----------|-------------|-----------------|
| **Crash safety** | Append-only: partial writes don't corrupt existing data | Transactions can be interrupted mid-write |
| **Git-trackable** | Plain text, diffable, committable | Binary format, not diffable |
| **Human-readable** | Open in any editor, grep-able | Requires tooling to inspect |
| **Streaming writes** | Append one line at a time, flush immediately | Requires commit after each transaction |
| **Recovery** | Truncated last line is tolerated (crash recovery) | Corrupted journal may require repair |
| **Simplicity** | No schema, no migrations | Schema changes require migrations |

> **The ledger is the source of truth. Everything else is derived from it.**

The in-memory `MessageStore` is not a database -- it's a **projection** of the ledger. If the agent crashes, you restart, and the ledger replays into a fresh `MessageStore`. The conversation is restored exactly as it was.

---

## The Ledger vs The Projection

This distinction is fundamental and enforced throughout the codebase:

```
JSONL file (ledger)              MessageStore (projection)
─────────────────────────        ──────────────────────────
Append-only                      In-memory, rebuilt on resume
Every finalized event recorded   Assistant messages collapsed by stream_id
Line order = true history        Ordered by seq for display
Never modified                   Updated reactively as events arrive
Source of truth                  Derived -- never authoritative for persistence
```

**Why collapse assistant messages?**

During streaming, an assistant response arrives as hundreds of small chunks -- one per word, sometimes. Writing every chunk to the JSONL file would create enormous bloat. A single response could produce 500 lines instead of 1.

So the system does something smarter: it only writes twice per stream.

```python
# src/session/persistence/writer.py
elif notification.event == StoreEvent.MESSAGE_UPDATED:
    # Skip streaming updates -- too many, would bloat the JSONL file
    # Only MESSAGE_ADDED (first chunk) and MESSAGE_FINALIZED (complete) are persisted
    pass
elif notification.event == StoreEvent.MESSAGE_FINALIZED:
    await self.write_message(notification.message)
    await self.flush()  # Flush immediately -- crash safe after this line
```

Think of it like a sports broadcast. You don't record every frame -- you record "game started" and "final score". The play-by-play is shown live but not archived.

---

## How It Actually Works: Five Questions Answered

These are the questions most developers ask when they first read the code.

### 1. Do we log every streaming chunk to JSONL?

**No.** Only two events per assistant response are persisted:
- `MESSAGE_ADDED` -- the very first chunk (stream has begun)
- `MESSAGE_FINALIZED` -- the complete, final message (stream is done)

All intermediate `MESSAGE_UPDATED` events (the hundreds of chunks in between) are shown live in the UI but deliberately skipped for persistence. This keeps session files lean.

**Analogy:** A sticky note on a whiteboard. `MESSAGE_ADDED` = someone picks up a marker and starts writing. `MESSAGE_FINALIZED` = they cap the marker and step back. You don't photograph every pen stroke -- only the finished note.

### 2. Who sets MESSAGE_ADDED and MESSAGE_FINALIZED?

`MessageStore.add_message()` emits `MESSAGE_ADDED` the first time it sees a `stream_id`. It emits `MESSAGE_UPDATED` for every subsequent chunk with that same `stream_id`.

`MessageStore.finalize_message()` emits `MESSAGE_FINALIZED` -- called by `MemoryManager.process_provider_delta()` when the provider signals the stream is complete.

```python
# src/memory/memory_manager.py, line 578
message = self._streaming_pipeline.process_delta(delta)

if message is not None:
    # Stream finalized - write to MessageStore (SINGLE WRITER)
    message.meta.seq = self._message_store.next_seq()
    self._message_store.add_message(message)
    self._last_parent_uuid = message.uuid
    self._streaming_pipeline = None  # Reset for next stream
```

### 3. How does the agent know the stream has ended?

The LLM provider sends a special field called `finish_reason` in the final delta. It's `None` for every intermediate chunk, and set to a value only at the very end.

Possible values:
- `"stop"` -- natural end of response
- `"tool_calls"` -- agent wants to call tools next
- `"length"` -- hit the model's maximum token limit

**Analogy:** Like a phone call. The LLM doesn't just go silent -- it says a specific goodbye word (`finish_reason: "stop"`). Without that signal, silence could mean "still thinking" or "connection dropped". The goodbye word removes the ambiguity.

When `finish_reason` is not `None`, the streaming pipeline finalizes the message and returns it. That return value signals `MemoryManager` to write it to the store.

### 4. How do we tie different streams to a single turn?

Every message stores a `parent_uuid` pointing to the message before it. The `_last_parent_uuid` field in `MemoryManager` tracks the most recently written message.

```python
# Each new message is chained to the previous one
session_message = SessionMessage.create_user(
    content=content,
    parent_uuid=self._last_parent_uuid,   # <- points to previous message
    ...
)
self._message_store.add_message(session_message)
self._last_parent_uuid = session_message.uuid  # <- update the chain pointer
```

This creates a linked chain: user message -> assistant response -> tool results -> next assistant response. On session resume, replaying the JSONL reconstructs the chain and every message knows its place in the conversation tree.

**Analogy:** Like a paper chain. Each link knows which link it was attached to. Replay the chain in order and you reconstruct the full conversation, even if the messages were written minutes apart.

### 5. What is flush()?

`flush()` is Python's way of saying "write this to disk now, don't wait."

When you write to a file, the data doesn't go directly to disk. It sits in an in-memory buffer in the Python process. The OS decides when to actually write it to the physical drive -- could be milliseconds, could be seconds later.

If the process crashes before the OS writes the buffer, the data is lost.

`flush()` forces the OS to accept the data immediately. After `flush()` returns, the data survives a process crash -- even if VS Code crashes, even if Python dies, the message is on disk.

```python
await self.write_message(notification.message)
await self.flush()  # <- After this line, crash-safe
```

**Analogy:** Like hitting Save in Word. Before you hit Save, your words exist only in RAM -- a power cut and they're gone. After Save, the OS has them.

**Why not `os.fsync()`?** That would go one step further -- guaranteeing the data survives even a power failure by flushing the OS's own disk cache. We deliberately don't do this because `fsync()` is slow (it blocks until the physical disk confirms the write). For a conversational agent, losing the last message on a power cut is an acceptable tradeoff for keeping the UI responsive.

---

## The Write Pipeline

When a message is created, it flows through a reactive pipeline:

```
Agent creates message
        |
        v
MemoryManager (sole writer)
        |
        v
MessageStore.add_message()   <- in-memory projection updated
        |
        v (reactive subscription)
SessionWriter.write_message()  <- JSONL line appended
        |
        v
flush()  <- OS buffer flushed
        |
        v
Data survives process crash
```

**MemoryManager is the sole writer** -- no other component is allowed to write to `MessageStore` directly. This is enforced as a hard architectural invariant. Violating it causes race conditions, duplicate messages, and broken sequence ordering.

**File created lazily** -- the JSONL file and its parent directory are not created until the first message is written. This prevents empty session files from appearing in the session list.

**Restrictive file permissions** -- on POSIX systems (Mac/Linux), the session file is set to `600` (owner read/write only) on creation. Your conversation history is private.

---

## Security: Secrets Never Hit Disk

Before any message is written to the JSONL file, it passes through secret redaction:

```python
# src/session/persistence/writer.py
safe_data = redact_dict(data)
if "content" in safe_data and isinstance(safe_data["content"], str):
    safe_data["content"] = redact_secrets(safe_data["content"])
line = json.dumps(safe_data, ensure_ascii=False)
self._file.write(line + "\n")
```

API keys, tokens, passwords, and other secrets detected in message content are redacted before persistence. What you type in the chat never leaks to disk in plaintext.

---

## Session Resume

When you reopen VS Code and resume a session, the JSONL file is replayed line by line into a fresh `MessageStore`:

```python
# src/session/persistence/parser.py
def load_session(file_path, store=None):
    # Streaming parse -- no readlines(), no full file in memory
    for line_number, item in parse_file_iter(path):
        store.add_message(item)  # Rebuilds the projection
    return store
```

Key properties of the parser:
- **Streaming** -- reads line by line, never loads the full file into memory. A 500MB session file is handled the same way as a 5KB one.
- **Tolerant last line** -- if the process crashed mid-write, the last line may be truncated. The parser skips it gracefully rather than refusing to load the session.
- **10MB line size limit** -- a single JSONL line over 10MB is rejected as a DoS protection measure.
- **Unknown roles skipped** -- future format additions don't break older parsers.
- **Parent chain restored** -- `_last_parent_uuid` is set from the last message in the store, so new messages continue the chain correctly.

---

## Where Sessions Live

```
.claraity/
  sessions/
    <session-id>.jsonl            <- main agent sessions
    subagents/
      <name>-<session-id>.jsonl   <- subagent transcripts (separate files)
```

Sessions are never automatically deleted. They accumulate as a complete history of every conversation you've had with the agent in this project.

---

## What's Still Missing

Session persistence solves the "forgetting" problem for conversations. But what happens when a conversation gets so long that it no longer fits in the context window? You can't keep the entire session history in every LLM call -- models have limits (typically 128K to 200K tokens).

That's what Chapter 6 solves: how ClarAIty automatically summarizes and compacts old conversation history to keep the agent running indefinitely without losing important context.

---

*Source files: `src/session/persistence/writer.py`, `src/session/persistence/parser.py`, `src/session/store/memory_store.py`, `src/memory/memory_manager.py`*
