# VS Code Integration -- Technical Design Document

**Status:** Draft (post-review)
**Author:** ClarAIty Team
**Date:** 2026-02-17
**Version:** 1.1 (review findings resolved)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Architecture](#3-architecture) -- includes Dual Subscription Model
4. [Wire Protocol Specification](#4-wire-protocol-specification) -- UIEvent + StoreNotification + Synthetic messages
5. [Component Design](#5-component-design)
6. [File Diff Flow](#6-file-diff-flow) -- server-side pre-computed diffs
7. [Tool Approval Flow](#7-tool-approval-flow) -- via StoreNotification path
8. [Extension to WebView Protocol](#8-extension--webview-protocol)
9. [Session Management](#9-session-management)
10. [Phasing](#10-phasing)
11. [File Structure](#11-file-structure)
12. [Testing Strategy](#12-testing-strategy)
13. [Known Challenges & Mitigations](#13-known-challenges--mitigations)
14. [References](#14-references)
- [Appendix A: Glossary](#appendix-a-glossary)
- [Appendix B: Configuration](#appendix-b-configuration)
- [Appendix C: Review History](#appendix-c-review-history)

---

## 1. Overview

### What This Is

A VS Code extension that connects to the ClarAIty AI Coding Agent over WebSocket, providing a rich IDE-integrated experience. The agent runs as a local Python server. The extension embeds a React-based chat panel in a VS Code WebView and bridges agent events to native VS Code features: diff editor for file changes, diagnostics, file decorations, and inline actions.

### Why We Are Building It

The current TUI (Textual-based terminal app in `src/ui/app.py`) is the primary interface. It works well for terminal-centric workflows, but has limitations:

- **No native diff review** -- File edits are shown as text in the chat stream. Users cannot see side-by-side diffs, navigate hunks, or selectively accept changes.
- **No IDE integration** -- The TUI cannot open files at specific lines, show diagnostics, or leverage the editor's language services.
- **Approval friction** -- Tool approvals happen in the same terminal stream, without structured UI affordances like buttons, checkboxes, or inline actions.
- **Limited discoverability** -- New users expect an extension marketplace experience, not a `pip install` + terminal workflow.

### Inspiration: Cline

The architecture draws heavily from [Cline](https://github.com/cline/cline) (formerly Claude Dev), specifically:

- **WebView panel** with React chat UI inside VS Code
- **`postMessage` bridge** between extension host and WebView
- **`TextDocumentContentProvider`** for virtual documents used with `vscode.diff`
- **Tool approval as first-class UI** with Accept/Reject buttons in the chat stream

The key difference: Cline embeds the LLM client directly in the extension. ClarAIty keeps the agent as a separate Python process, communicating via WebSocket. This preserves our existing agent architecture, session persistence, and tool execution infrastructure.

---

## 2. Goals & Non-Goals

### Phase 1 Goals (MVP)

- [x] Python WebSocket server (`src/server/`) wrapping existing `CodingAgent`
- [x] VS Code extension with WebView chat panel
- [x] Bidirectional message streaming (text + markdown + code blocks)
- [x] Tool approval flow: agent requests approval, user clicks Accept/Reject in WebView
- [x] File diff review via native `vscode.diff` command
- [x] Session creation and persistence (reusing existing JSONL infrastructure)
- [x] Context window usage indicator
- [x] Basic error display and recovery

### Phase 2 Goals (Planned)

- [ ] Session resume and session picker
- [ ] Permission mode switching (Normal/Auto/Plan) from the extension
- [ ] Thinking/reasoning block display (collapsible)
- [ ] Pause/Continue flow for budget limits
- [ ] Clarify interview widget
- [ ] Plan approval widget
- [ ] Multiple concurrent sessions
- [ ] Extension settings UI for LLM configuration

### Phase 3 Goals (Future)

- [ ] Inline code actions ("ClarAIty: Explain", "ClarAIty: Refactor")
- [ ] Diagnostics integration (agent-detected issues as VS Code problems)
- [ ] Git integration (show agent commits in SCM view)
- [ ] File watcher for collaborative editing (detect external file changes)
- [ ] Director mode UI (phase progress bar, slice tracker)
- [ ] Marketplace publishing

### Explicit Non-Goals

- **Replacing the TUI** -- The terminal interface remains the primary interface. VS Code is an alternative frontend.
- **Embedding the LLM client in TypeScript** -- The agent stays in Python. No LLM API calls from the extension.
- **Remote server support** -- Phase 1 targets localhost only. Remote support deferred.
- **Authentication/multi-user** -- Single-user, single-machine.

---

## 3. Architecture

### System Diagram

```
+------------------------------------------------------------------+
|                        VS Code Extension Host                     |
|                                                                   |
|  +--------------------+       postMessage        +--------------+ |
|  |   Extension Host   | <---------------------> |   WebView     | |
|  |                    |       (TypeScript)       |  (React App)  | |
|  |  - WebSocket client|                          |               | |
|  |  - ContentProvider |                          |  - Chat UI    | |
|  |  - Diff commands   |                          |  - Tool cards | |
|  |  - Status bar      |                          |  - Markdown   | |
|  +--------+-----------+                          +---------------+ |
|           |                                                       |
+-----------|-------------------------------------------------------+
            | WebSocket (ws://localhost:9120)
            |
+-----------|-------------------------------------------------------+
|           v                       Python Server                   |
|  +--------+-----------+                                           |
|  | WebSocketProtocol  |  (extends UIProtocol)                     |
|  |  - JSON serialize  |                                           |
|  |  - JSON deserialize|                                           |
|  |  - Dual subscriber |  <--- subscribes to BOTH sources         |
|  +--+-------------+---+                                           |
|     |             |                                               |
|     |  (1)        | (2)                                           |
|     |  UIEvent    | StoreNotification                             |
|     |  iterator   | callback                                     |
|     |             |                                               |
|  +--v-------------+---+    +------------------+                   |
|  |   CodingAgent      |--->| MemoryManager    |                  |
|  |  stream_response() |    | (single writer)  |                  |
|  +--------+-----------+    +--------+---------+                  |
|           |                         |                             |
|  +--------v-----------+    +--------v---------+                  |
|  |  ToolExecutor      |    |  MessageStore    |---> JSONL files  |
|  |  (updates store    |--->|  .subscribe()    |                  |
|  |   tool state)      |    +------------------+                  |
|  +--------------------+                                           |
+------------------------------------------------------------------+
```

### Component Responsibilities

| Component | Responsibility | Language |
|-----------|---------------|----------|
| `WebSocketProtocol` | Extends `UIProtocol` (protocol.py line 113). Subscribes to both the UIEvent stream (from `stream_response()`) and `MessageStore.subscribe()` for tool state/message lifecycle. Serializes both to JSON. Deserializes JSON to `UserAction`. Manages WebSocket connection lifecycle. Uses `asyncio.Lock` for send concurrency. | Python |
| `AgentServer` | HTTP/WS server. Creates `CodingAgent` instances. Routes WebSocket connections to protocol instances. Health check endpoint. | Python |
| Extension Host | VS Code extension entry point. Manages WebSocket connection. Owns `TextDocumentContentProvider` for diff URIs. Bridges WebSocket messages to/from WebView via `postMessage`. | TypeScript |
| WebView React App | Chat UI. Renders markdown, code blocks, tool cards, approval buttons, context bar. Communicates with extension host via `postMessage`. | TypeScript/React |

### Data Flow: Dual Subscription Model

The `WebSocketProtocol` consumes **two** data sources and multiplexes them onto a single WebSocket connection. This mirrors how the TUI works: `AgentApp` iterates UIEvents from `stream_response()` for text/code/thinking deltas, and separately subscribes to `MessageStore` for tool state and message lifecycle events.

```
User types message in WebView
    |
    v
[WebView] --postMessage--> [Extension Host] --WebSocket JSON--> [Python Server]
    |                                                                  |
    |                                                    CodingAgent.stream_response()
    |                                                         |              |
    |                                              (1) UIEvent iterator    (2) Agent updates
    |                                              (text, code, thinking,    MessageStore
    |                                               context, errors)        .update_tool_state()
    |                                                         |              |
    |                                                         v              v
    |                                                   WebSocketProtocol  MessageStore
    |                                                   .send_event()      .subscribe()
    |                                                         |              |
    |                                                         v              v
    |                                                  {"type":"event",...} {"type":"store",...}
    |                                                         \            /
    |                                                          \          /
    |                                                    Single WebSocket
    |                                                           |
[WebView] <--postMessage-- [Extension Host] <--WebSocket JSON--+
    |
    v
Renders:
  "event" messages -> TextDelta->markdown, CodeBlock->syntax, Thinking->collapsible
  "store" messages -> tool_state_updated->ToolCard, message_added->chat history
```

**Source 1: UIEvent async iterator** from `stream_response()`:
- `TextDelta`, `CodeBlockStart/Delta/End` -- streaming text content
- `ThinkingStart/Delta/End` -- reasoning blocks
- `StreamStart`, `StreamEnd` -- stream lifecycle
- `ContextUpdated`, `ContextCompacted` -- context window status
- `FileReadEvent` -- file read notifications
- `ErrorEvent` -- recoverable errors
- `PausePromptStart/End` -- budget pause flow (Phase 2 UI)

**Source 2: `MessageStore.subscribe()`** for store notifications:
- `TOOL_STATE_UPDATED` -- tool execution lifecycle (PENDING -> AWAITING_APPROVAL -> RUNNING -> SUCCESS/ERROR)
- `MESSAGE_ADDED` -- new message persisted to store
- `MESSAGE_UPDATED` -- existing message content updated
- `MESSAGE_FINALIZED` -- stream complete, message fully rendered

**Why two sources?** Tool call events (`ToolCallStart`, `ToolCallStatus`, `ToolCallResult` in `events.py`) are **legacy types kept for backward compatibility** (events.py lines 108-147). They are no longer yielded by the agent. Instead, the agent calls `self.memory.message_store.update_tool_state()` which emits `StoreNotification(event=TOOL_STATE_UPDATED)`. The TUI handles this in `_on_store_tool_state_updated()` (app.py line 3533). The `WebSocketProtocol` must follow the same pattern.

### Threading Model

```
Python Server Process
  |
  +-- Main Thread: asyncio event loop
  |     |
  |     +-- WebSocket handler (one per connection)
  |     +-- CodingAgent.stream_response() coroutine -> yields UIEvents
  |     +-- UIEvent serialization + send (via asyncio.Lock)
  |     +-- StoreNotification callback -> loop.call_soon_threadsafe() -> send
  |     +-- UserAction deserialization + delivery to UIProtocol
  |
  +-- Tool execution: runs in executor (thread pool) for blocking I/O
  |     |
  |     +-- Calls MessageStore.update_tool_state() (triggers StoreNotification)
```

The existing `CodingAgent` async path (`_execute_with_tools_async`, agent.py line 900) is reused without modification. The `WebSocketProtocol` replaces what `AgentApp` (app.py) does today: it consumes the `UIEvent` async iterator AND subscribes to `MessageStore` notifications, forwarding both over the wire instead of rendering them in Textual widgets.

**Concurrency note:** `StoreNotification` callbacks may fire from the tool executor thread pool (since `update_tool_state()` is called during tool execution). The `WebSocketProtocol` must use `loop.call_soon_threadsafe()` to schedule WebSocket sends on the event loop, and protect the WebSocket send path with `asyncio.Lock` to prevent interleaved frames. See Section 5.1.3 for implementation details.

---

## 4. Wire Protocol Specification

All messages are JSON objects sent over a single WebSocket connection. Every message has a `type` field for dispatching.

### 4.1 Transport

- **URL:** `ws://localhost:9120/ws`
- **Encoding:** UTF-8 JSON, one message per WebSocket frame
- **Heartbeat:** WebSocket ping/pong every 30 seconds
- **Reconnection:** Client reconnects with exponential backoff (1s, 2s, 4s, 8s, max 30s)

### 4.2 Server-to-Client Messages (Agent -> Extension)

Server-to-client messages come from **two sources** (see "Dual Subscription Model" in Section 3):

1. **`"type": "event"`** -- Serialized `UIEvent` objects from `stream_response()`. These are ephemeral streaming signals (text deltas, code blocks, thinking, context, errors).
2. **`"type": "store"`** -- Serialized `StoreNotification` objects from `MessageStore.subscribe()`. These represent persisted state changes (tool lifecycle, message persistence, stream finalization).
3. **`"type": "session_info"` / `"type": "session_history"`** -- Synthetic server-only messages not derived from either source (see Section 4.2.11).

The following subsections document UIEvent-derived messages from `src/core/events.py` (lines 1-302).

#### 4.2.1 Stream Lifecycle

```jsonc
// StreamStart (events.py line 41)
// NOTE: StreamStart is an empty dataclass (no fields). Session ID is sent
// separately in the "session_info" synthetic message (Section 4.2.11).
{
  "type": "stream_start"
}

// StreamEnd (events.py line 50)
{
  "type": "stream_end",
  "total_tokens": 1523,
  "duration_ms": 4200
}
```

#### 4.2.2 Text Content

```jsonc
// TextDelta (events.py line 64)
{
  "type": "text_delta",
  "content": "Here is the implementation:\n\n"
}
```

#### 4.2.3 Code Blocks

```jsonc
// CodeBlockStart (events.py line 78)
{
  "type": "code_block_start",
  "language": "python"
}

// CodeBlockDelta (events.py line 93)
{
  "type": "code_block_delta",
  "content": "def hello():\n    print(\"world\")\n"
}

// CodeBlockEnd (events.py line 99)
{
  "type": "code_block_end"
}
```

#### 4.2.4 Tool Calls (via StoreNotification, NOT UIEvent stream)

**IMPORTANT:** The `ToolCallStart`, `ToolCallStatus`, and `ToolCallResult` dataclasses in `events.py` (lines 108-147) are **legacy types kept for backward compatibility**. They are **no longer yielded** by the agent's `stream_response()` iterator. Instead, tool state flows through `MessageStore`:

1. Agent calls `self.memory.message_store.update_tool_state(call_id, state)`
2. `MessageStore` emits `StoreNotification(event=TOOL_STATE_UPDATED, ...)`
3. `WebSocketProtocol`'s store subscription callback serializes and sends

Wire format for tool state updates (note `"type": "store"` wrapper):

```jsonc
// Tool state: PENDING (tool call parsed, queued)
{
  "type": "store",
  "event": "tool_state_updated",
  "data": {
    "call_id": "call_abc123",
    "tool_name": "edit_file",
    "status": "pending",
    "arguments": {
      "file_path": "/src/main.py",
      "old_string": "def foo():\n    pass",
      "new_string": "def foo():\n    return 42"
    },
    "requires_approval": true
  }
}

// Tool state: AWAITING_APPROVAL (waiting for user)
{
  "type": "store",
  "event": "tool_state_updated",
  "data": {
    "call_id": "call_abc123",
    "tool_name": "edit_file",
    "status": "awaiting_approval"
  }
}

// Tool state: RUNNING (approved, executing)
{
  "type": "store",
  "event": "tool_state_updated",
  "data": {
    "call_id": "call_abc123",
    "tool_name": "edit_file",
    "status": "running",
    "message": "Editing file..."
  }
}

// Tool state: SUCCESS (completed)
{
  "type": "store",
  "event": "tool_state_updated",
  "data": {
    "call_id": "call_abc123",
    "tool_name": "edit_file",
    "status": "success",
    "result": "File edited successfully",
    "duration_ms": 45
  }
}

// Tool state: ERROR (failed)
{
  "type": "store",
  "event": "tool_state_updated",
  "data": {
    "call_id": "call_abc123",
    "tool_name": "edit_file",
    "status": "error",
    "error": "File not found: /src/main.py",
    "duration_ms": 12
  }
}
```

**ToolStatus values** (canonical source: `src/core/tool_status.py`, `ToolStatus` enum):

| Value | Wire String | Description |
|-------|-------------|-------------|
| `PENDING` | `"pending"` | Queued, not yet started |
| `AWAITING_APPROVAL` | `"awaiting_approval"` | Waiting for user confirmation |
| `APPROVED` | `"approved"` | User approved, about to execute |
| `REJECTED` | `"rejected"` | User rejected |
| `RUNNING` | `"running"` | Currently executing |
| `SUCCESS` | `"success"` | Completed successfully |
| `ERROR` | `"error"` | Completed with error |
| `TIMEOUT` | `"timeout"` | Tool execution timed out |
| `CANCELLED` | `"cancelled"` | User cancelled mid-execution |
| `SKIPPED` | `"skipped"` | Blocked (e.g., repeated failed call) |

**ToolStatus normalization note:** Two `ToolStatus` enums exist in the codebase: `src/core/events.py` defines both `FAILED` and `ERROR` as separate values; `src/core/tool_status.py` defines only `ERROR` (no `FAILED`). The **canonical source for the wire protocol is `src/core/tool_status.py`**. The serializer must normalize `FAILED` to `"error"` on the wire. The extension should only expect the values listed above.

#### 4.2.5 Thinking/Reasoning

```jsonc
// ThinkingStart (events.py line 155)
{
  "type": "thinking_start"
}

// ThinkingDelta (events.py line 164)
{
  "type": "thinking_delta",
  "content": "Let me analyze the file structure..."
}

// ThinkingEnd (events.py line 170)
{
  "type": "thinking_end",
  "token_count": 342
}
```

#### 4.2.6 Pause/Continue (Phase 2 UI -- wire types defined in Phase 1)

> **Note:** The wire message types are defined in Phase 1 so the serializer is complete, but the extension UI for Pause/Continue (the pause widget with Continue/Stop buttons) is deferred to Phase 2. In Phase 1, the extension should log these messages but not render a pause widget.

```jsonc
// PausePromptStart (events.py line 183)
{
  "type": "pause_prompt_start",
  "reason": "Tool call budget reached (20/20)",
  "reason_code": "tool_budget",
  "pending_todos": ["Implement auth module", "Write tests"],
  "stats": {
    "tool_calls": 20,
    "tool_budget": 20,
    "wall_time_seconds": 180,
    "iterations": 8
  }
}

// PausePromptEnd (events.py line 196)
{
  "type": "pause_prompt_end",
  "continue_work": true,
  "feedback": "Focus on the auth module first"
}
```

#### 4.2.7 Context Window

```jsonc
// ContextUpdated (events.py line 207)
{
  "type": "context_updated",
  "used": 45000,
  "limit": 128000,
  "pressure_level": "green"   // "green" | "yellow" | "orange" | "red"
}

// ContextCompacted (events.py line 218)
{
  "type": "context_compacted",
  "messages_removed": 5,
  "tokens_before": 120000,
  "tokens_after": 80000
}
```

#### 4.2.8 File Operations

```jsonc
// FileReadEvent (events.py line 260)
{
  "type": "file_read",
  "path": "src/core/agent.py",
  "lines_read": 200,
  "truncated": false
}
```

#### 4.2.9 Errors

```jsonc
// ErrorEvent (events.py line 233)
{
  "type": "error",
  "error_type": "rate_limit",   // "provider_timeout" | "network" | "rate_limit" | "api_error" | "auth"
  "user_message": "Rate limited. Retrying in 30 seconds...",
  "error_id": "err-789",
  "recoverable": true,
  "retry_after": 30
}
```

#### 4.2.10 Store Notification Messages

These messages originate from `MessageStore.subscribe()` callbacks, not from the UIEvent stream. They carry the `"type": "store"` wrapper to distinguish them from UIEvent-derived messages.

```jsonc
// Message lifecycle: new message added to store
{
  "type": "store",
  "event": "message_added",
  "data": {
    "uuid": "msg-uuid-123",
    "role": "assistant",
    "content": "I'll help you with that...",
    "stream_id": "stream-456"
  }
}

// Message lifecycle: existing message updated (content appended during streaming)
{
  "type": "store",
  "event": "message_updated",
  "data": {
    "uuid": "msg-uuid-123",
    "role": "assistant",
    "content": "I'll help you with that. Let me edit the file..."
  }
}

// Message lifecycle: stream finalized (no more updates)
{
  "type": "store",
  "event": "message_finalized",
  "data": {
    "stream_id": "stream-456"
  }
}

// Tool state: see Section 4.2.4 for tool_state_updated messages
```

#### 4.2.11 Synthetic Messages (Server-Only)

These messages are generated by the server itself, not derived from UIEvent or StoreNotification. They are used for connection handshake and session management.

```jsonc
// Sent once on connection establishment
{
  "type": "session_info",
  "session_id": "abc-def-123",
  "model_name": "qwen3-coder:30b",
  "permission_mode": "normal",    // "normal" | "auto" | "plan"
  "working_directory": "C:/Projects/my-app"
}
```

### 4.3 Client-to-Server Messages (Extension -> Agent)

These correspond to the `UserAction` types defined in `src/core/protocol.py` (lines 29-89).

#### 4.3.1 Chat Message

```jsonc
{
  "type": "chat_message",
  "content": "Add error handling to the login function",
  "attachments": []    // Future: file references, images
}
```

#### 4.3.2 Approval Result

Maps to `ApprovalResult` (protocol.py line 30):

```jsonc
{
  "type": "approval_result",
  "call_id": "call_abc123",
  "approved": true,
  "auto_approve_future": false,
  "feedback": null
}
```

#### 4.3.3 Interrupt Signal

Maps to `InterruptSignal` (protocol.py line 42):

```jsonc
{
  "type": "interrupt"
}
```

#### 4.3.4 Retry Signal

Maps to `RetrySignal` (protocol.py line 49):

```jsonc
{
  "type": "retry"
}
```

#### 4.3.5 Pause Result

Maps to `PauseResult` (protocol.py line 57):

```jsonc
{
  "type": "pause_result",
  "continue_work": true,
  "feedback": "Focus on auth module first"
}
```

#### 4.3.6 Clarify Result (Phase 2+)

> **Deferred to Phase 2.** While `ClarifyResult` is defined in `protocol.py` (line 66), there is no corresponding trigger event currently yielded by the agent. Clarify requests are delivered through `MessageStore` as system events, not through the UIEvent stream. The wire type is defined here for completeness, but the extension should not implement a Clarify UI in Phase 1.

Maps to `ClarifyResult` (protocol.py line 66):

```jsonc
{
  "type": "clarify_result",
  "call_id": "call_xyz789",
  "submitted": true,
  "responses": {
    "q1": "option_a",
    "q2": ["option_b", "option_c"]
  },
  "chat_instead": false,
  "chat_message": null
}
```

#### 4.3.7 Plan Approval Result

Maps to `PlanApprovalResult` (protocol.py line 78):

```jsonc
{
  "type": "plan_approval_result",
  "plan_hash": "sha256-abc...",
  "approved": true,
  "auto_accept_edits": false,
  "feedback": null
}
```

#### 4.3.8 Session Commands

```jsonc
// Create new session
{
  "type": "session_new"
}

// Resume existing session
{
  "type": "session_resume",
  "session_id": "abc-def-123"
}

// List sessions
{
  "type": "session_list"
}
```

### 4.4 Complete Server-to-Client Mapping Table

#### UIEvent Messages (from `stream_response()` iterator)

| UIEvent Class | Wire `type` | Fields | Notes |
|---------------|-------------|--------|-------|
| `StreamStart` | `"stream_start"` | (none) | Empty dataclass. Session ID sent separately in `session_info`. |
| `StreamEnd` | `"stream_end"` | `total_tokens`, `duration_ms` | |
| `TextDelta` | `"text_delta"` | `content` | |
| `CodeBlockStart` | `"code_block_start"` | `language` | |
| `CodeBlockDelta` | `"code_block_delta"` | `content` | |
| `CodeBlockEnd` | `"code_block_end"` | (none) | |
| `ThinkingStart` | `"thinking_start"` | (none) | |
| `ThinkingDelta` | `"thinking_delta"` | `content` | |
| `ThinkingEnd` | `"thinking_end"` | `token_count` | |
| `PausePromptStart` | `"pause_prompt_start"` | `reason`, `reason_code`, `pending_todos`, `stats` | Wire type defined Phase 1; UI deferred to Phase 2 |
| `PausePromptEnd` | `"pause_prompt_end"` | `continue_work`, `feedback` | Wire type defined Phase 1; UI deferred to Phase 2 |
| `ContextUpdated` | `"context_updated"` | `used`, `limit`, `pressure_level` | |
| `ContextCompacted` | `"context_compacted"` | `messages_removed`, `tokens_before`, `tokens_after` | |
| `FileReadEvent` | `"file_read"` | `path`, `lines_read`, `truncated` | |
| `ErrorEvent` | `"error"` | `error_type`, `user_message`, `error_id`, `recoverable`, `retry_after` | |

**Legacy UIEvent types NOT on the wire** (no longer yielded by agent):

| UIEvent Class | Replacement | Notes |
|---------------|------------|-------|
| `ToolCallStart` | `store:tool_state_updated` | Legacy; kept for backward compat in events.py |
| `ToolCallStatus` | `store:tool_state_updated` | Legacy; tool status via MessageStore |
| `ToolCallResult` | `store:tool_state_updated` | Legacy; tool results via MessageStore |

#### StoreNotification Messages (from `MessageStore.subscribe()`)

| StoreEvent | Wire `type` | Wire `event` | Key `data` Fields |
|-----------|-------------|-------------|-------------------|
| `TOOL_STATE_UPDATED` | `"store"` | `"tool_state_updated"` | `call_id`, `tool_name`, `status`, `arguments`, `requires_approval`, `result`, `error`, `duration_ms`, `message` |
| `MESSAGE_ADDED` | `"store"` | `"message_added"` | `uuid`, `role`, `content`, `stream_id` |
| `MESSAGE_UPDATED` | `"store"` | `"message_updated"` | `uuid`, `role`, `content` |
| `MESSAGE_FINALIZED` | `"store"` | `"message_finalized"` | `stream_id` |

#### Synthetic Messages (server-generated)

| Message | Wire `type` | Fields | Notes |
|---------|-------------|--------|-------|
| Session info | `"session_info"` | `session_id`, `model_name`, `permission_mode`, `working_directory` | Sent on connection |
| Session history | `"session_history"` | `messages[]` | Phase 2: sent on session resume |

### 4.5 Complete UserAction-to-JSON Mapping Table

| UserAction Class | `type` Wire String | Fields | Phase |
|-----------------|-------------------|--------|-------|
| `ApprovalResult` | `"approval_result"` | `call_id`, `approved`, `auto_approve_future`, `feedback` | 1 |
| `InterruptSignal` | `"interrupt"` | (none) | 1 |
| `RetrySignal` | `"retry"` | (none) | 1 |
| `PauseResult` | `"pause_result"` | `continue_work`, `feedback` | 2 (wire defined P1, UI deferred) |
| `ClarifyResult` | `"clarify_result"` | `call_id`, `submitted`, `responses`, `chat_instead`, `chat_message` | 2 (no trigger event in P1) |
| `PlanApprovalResult` | `"plan_approval_result"` | `plan_hash`, `approved`, `auto_accept_edits`, `feedback` | 2 |

---

## 5. Component Design

### 5.1 Python Server (`src/server/`)

#### 5.1.1 File: `src/server/__init__.py`

Exports `start_server`, `AgentServer`, `WebSocketProtocol`.

#### 5.1.2 File: `src/server/app.py` -- AgentServer

```python
class AgentServer:
    """HTTP + WebSocket server wrapping CodingAgent.

    Responsibilities:
    - Start/stop aiohttp server on configurable port
    - Health check endpoint (GET /health)
    - WebSocket endpoint (GET /ws)
    - Agent lifecycle management (create, configure, shutdown)
    - Graceful shutdown on SIGINT/SIGTERM
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9120,
        working_directory: str = ".",
        agent_kwargs: dict = None,   # Passed to CodingAgent.__init__
    ):
        ...

    async def start(self) -> None:
        """Start the HTTP/WS server."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown: close WebSocket connections, stop agent."""
        ...

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle a new WebSocket connection.

        Creates a WebSocketProtocol and runs the agent event loop.
        Only one active connection at a time in Phase 1.
        """
        ...

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health -- returns {"status": "ok", "session_id": "..."}"""
        ...
```

**Dependencies:** `aiohttp` for async HTTP/WS server.

#### 5.1.3 File: `src/server/ws_protocol.py` -- WebSocketProtocol

```python
class WebSocketProtocol(UIProtocol):
    """WebSocket-based UIProtocol implementation.

    Extends UIProtocol (protocol.py line 113) to:
    - Serialize UIEvents to JSON and send over WebSocket
    - Subscribe to MessageStore for tool state and message lifecycle
    - Receive JSON from WebSocket and convert to UserAction
    - Manage the send/receive pumps

    This is the functional equivalent of what AgentApp does
    for the Textual TUI, but for WebSocket clients.

    CONCURRENCY MODEL:
    - UIEvents arrive on the asyncio event loop (from stream_response iterator)
    - StoreNotifications may arrive from the tool executor thread pool
    - Both paths write to the same WebSocket
    - An asyncio.Lock protects all WebSocket sends to prevent interleaved frames
    - StoreNotification callbacks use loop.call_soon_threadsafe() to schedule
      sends on the event loop before acquiring the lock
    """

    def __init__(self, ws: web.WebSocketResponse, session_id: str,
                 message_store: MessageStore):
        super().__init__()
        self._ws = ws
        self._session_id = session_id
        self._store = message_store
        self._send_lock = asyncio.Lock()     # Protects WebSocket sends
        self._loop = asyncio.get_event_loop()
        self._unsubscribe: Callable | None = None

    # --- Dual Subscription Setup ---

    def _subscribe_to_store(self) -> None:
        """Subscribe to MessageStore for tool state and message events.

        The callback may be invoked from a thread pool thread (tool execution),
        so it uses loop.call_soon_threadsafe() to schedule the async send
        on the event loop.
        """
        def on_notification(notification: StoreNotification) -> None:
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._send_store_notification(notification)
            )

        self._unsubscribe = self._store.subscribe(on_notification)

    async def _send_store_notification(self, notification: StoreNotification) -> None:
        """Serialize a StoreNotification to JSON and send over WebSocket.

        Acquires _send_lock to prevent interleaved frames with UIEvent sends.
        """
        data = serialize_store_notification(notification)
        if data is not None:
            async with self._send_lock:
                await self._ws.send_json(data)

    # --- Serialization (Agent -> Client) ---

    async def send_event(self, event: UIEvent) -> None:
        """Serialize a UIEvent to JSON and send over WebSocket.

        Acquires _send_lock to prevent interleaved frames with store notifications.
        Uses dataclasses.asdict() with special-case overrides for non-trivial types.
        """
        data = serialize_event(event)
        if data is not None:
            async with self._send_lock:
                await self._ws.send_json(data)

    # --- Deserialization (Client -> Agent) ---

    async def receive_loop(self) -> None:
        """Read JSON messages from WebSocket and dispatch.

        Runs in parallel with the agent event loop.
        Converts JSON to UserAction and calls submit_action().
        """
        ...

    def _deserialize_action(self, data: dict) -> UserAction | None:
        """Convert JSON dict to UserAction.

        Uses the mapping table from Section 4.5.
        Returns None for unrecognized message types (logged as warning).
        """
        msg_type = data.get("type")
        if msg_type == "approval_result":
            return ApprovalResult(
                call_id=data["call_id"],
                approved=data["approved"],
                auto_approve_future=data.get("auto_approve_future", False),
                feedback=data.get("feedback"),
            )
        elif msg_type == "interrupt":
            return InterruptSignal()
        # ... all action types from Section 4.5
        ...

    # --- Connection lifecycle ---

    async def run(self, agent: CodingAgent) -> None:
        """Main loop: subscribe to store, then concurrently run
        receive_loop and agent event processing.

        On shutdown, unsubscribes from store.
        """
        self._subscribe_to_store()
        try:
            # Run receive_loop and agent stream_response concurrently
            ...
        finally:
            if self._unsubscribe:
                self._unsubscribe()
```

#### 5.1.4 File: `src/server/serializers.py` -- Event Serialization Helpers

```python
"""Pure functions for UIEvent/StoreNotification <-> JSON conversion.

Separated from WebSocketProtocol for unit testing without WebSocket dependencies.

Serialization strategy:
- Use dataclasses.asdict() as the default serializer for UIEvent dataclasses
- Apply special-case overrides for types that need transformation:
  - Enum values -> .name.lower() (e.g., ToolStatus.SUCCESS -> "success")
  - StreamStart -> empty dict (no fields)
  - FAILED status -> normalized to "error" (see ToolStatus note in Section 4.2.4)
- StoreNotification serialization extracts relevant fields from the
  notification + embedded ToolExecutionState/Message objects
"""

from dataclasses import asdict
from src.core.events import *
from src.core.protocol import *
from src.core.tool_status import ToolStatus as CanonicalToolStatus
from src.session.store.memory_store import StoreNotification, StoreEvent


def serialize_event(event: UIEvent, session_id: str = "") -> dict | None:
    """Convert UIEvent to JSON-serializable dict.

    Uses dataclasses.asdict() with special-case overrides.
    Returns None for legacy event types (ToolCallStart/Status/Result).
    """
    # Skip legacy tool events (handled via StoreNotification)
    if isinstance(event, (ToolCallStart, ToolCallStatus, ToolCallResult)):
        return None

    data = asdict(event)
    data["type"] = _event_type_name(event)

    # Normalize enum values to lowercase strings
    for key, value in data.items():
        if isinstance(value, Enum):
            data[key] = value.name.lower()

    return data


def serialize_store_notification(notification: StoreNotification) -> dict | None:
    """Convert StoreNotification to JSON-serializable dict.

    Returns None for events not relevant to the wire protocol
    (e.g., BULK_LOAD_COMPLETE, STORE_CLEARED).
    """
    ...


def deserialize_action(data: dict) -> UserAction | None:
    """Convert JSON dict to UserAction. Returns None for unknown types."""
    ...


def serialize_tool_status(status) -> str:
    """Convert ToolStatus enum to wire string.

    Normalizes FAILED -> "error" to match the canonical ToolStatus
    enum in src/core/tool_status.py.
    """
    name = status.name.lower()
    if name == "failed":
        return "error"
    return name
```

#### 5.1.5 File: `src/server/__main__.py` -- CLI Entry Point

```python
"""Start the ClarAIty VS Code server.

Usage:
    python -m src.server                    # Default: localhost:9120
    python -m src.server --port 9121        # Custom port
    python -m src.server --host 0.0.0.0     # Bind all interfaces (not recommended)

Windows note:
    On Windows, the default ProactorEventLoop has issues with some async
    operations. This module sets WindowsSelectorEventLoopPolicy before
    starting the server to ensure compatibility with aiohttp.
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### 5.2 VS Code Extension (`claraity-vscode/`)

#### 5.2.1 File: `src/extension.ts` -- Extension Entry Point

```typescript
import * as vscode from 'vscode';
import { ClarAItySidebarProvider } from './sidebar-provider';
import { AgentConnection } from './agent-connection';
import { DiffContentProvider } from './diff-provider';

export function activate(context: vscode.ExtensionContext) {
    // Register the diff content provider
    const diffProvider = new DiffContentProvider();
    context.subscriptions.push(
        vscode.workspace.registerTextDocumentContentProvider(
            'claraity-diff', diffProvider
        )
    );

    // Register the sidebar webview provider
    const connection = new AgentConnection();
    const sidebarProvider = new ClarAItySidebarProvider(
        context.extensionUri, connection, diffProvider
    );
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'claraity.chatView', sidebarProvider
        )
    );

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('claraity.newChat', () => { ... }),
        vscode.commands.registerCommand('claraity.interrupt', () => { ... }),
        vscode.commands.registerCommand('claraity.acceptDiff', (uri) => { ... }),
        vscode.commands.registerCommand('claraity.rejectDiff', (uri) => { ... }),
    );

    // Status bar item
    const statusBar = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Left, 100
    );
    statusBar.text = '$(sparkle) ClarAIty';
    statusBar.command = 'claraity.newChat';
    statusBar.show();
    context.subscriptions.push(statusBar);
}

export function deactivate() {
    // Cleanup WebSocket connection
}
```

#### 5.2.2 File: `src/agent-connection.ts` -- WebSocket Client

```typescript
import { EventEmitter } from 'vscode';

export interface ServerMessage {
    type: string;
    [key: string]: any;
}

export class AgentConnection {
    private ws: WebSocket | null = null;
    private reconnectTimer: NodeJS.Timeout | null = null;
    private reconnectDelay = 1000;

    // Events for consumers
    public readonly onMessage = new EventEmitter<ServerMessage>();
    public readonly onConnected = new EventEmitter<void>();
    public readonly onDisconnected = new EventEmitter<void>();

    constructor(
        private url: string = 'ws://localhost:9120/ws'
    ) {}

    connect(): void { ... }
    disconnect(): void { ... }
    send(message: object): void { ... }

    private handleMessage(data: string): void {
        const msg = JSON.parse(data) as ServerMessage;
        this.onMessage.fire(msg);
    }

    private scheduleReconnect(): void {
        this.reconnectTimer = setTimeout(() => {
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
            this.connect();
        }, this.reconnectDelay);
    }
}
```

#### 5.2.3 File: `src/sidebar-provider.ts` -- WebView Provider

```typescript
import * as vscode from 'vscode';
import { AgentConnection, ServerMessage } from './agent-connection';
import { DiffContentProvider } from './diff-provider';
import { ExtensionMessage, WebViewMessage } from './types';

export class ClarAItySidebarProvider implements vscode.WebviewViewProvider {
    private view?: vscode.WebviewView;

    constructor(
        private extensionUri: vscode.Uri,
        private connection: AgentConnection,
        private diffProvider: DiffContentProvider,
    ) {
        // Forward server messages to webview
        this.connection.onMessage.event((msg) => {
            this.handleServerMessage(msg);
        });
    }

    resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        token: vscode.CancellationToken
    ): void {
        this.view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.extensionUri],
        };
        webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);

        // Handle messages from webview
        webviewView.webview.onDidReceiveMessage((message: WebViewMessage) => {
            this.handleWebviewMessage(message);
        });
    }

    /**
     * Server -> Extension -> WebView message routing.
     *
     * Most messages pass through directly to the WebView. Some trigger
     * VS Code native actions:
     * - store:tool_state_updated for file edit tools -> opens diff editor
     *   (when status is "awaiting_approval" and diff data is present)
     */
    private handleServerMessage(msg: ServerMessage): void {
        // Forward to webview for rendering
        this.postToWebview({ type: 'serverMessage', payload: msg });

        // Side effects for store:tool_state_updated on file edit tools
        if (msg.type === 'store'
            && msg.event === 'tool_state_updated'
            && msg.data?.status === 'awaiting_approval'
            && this.isFileEditTool(msg.data?.tool_name)
            && msg.data?.diff) {
            this.openDiffEditor(msg);
        }
    }

    /**
     * WebView -> Extension -> Server message routing.
     */
    private handleWebviewMessage(msg: WebViewMessage): void {
        switch (msg.type) {
            case 'chatMessage':
                this.connection.send({
                    type: 'chat_message',
                    content: msg.content,
                });
                break;
            case 'approvalResult':
                this.connection.send({
                    type: 'approval_result',
                    call_id: msg.callId,
                    approved: msg.approved,
                    auto_approve_future: msg.autoApproveFuture ?? false,
                    feedback: msg.feedback ?? null,
                });
                break;
            case 'interrupt':
                this.connection.send({ type: 'interrupt' });
                break;
            // ... other message types
        }
    }

    private isFileEditTool(name: string): boolean {
        return ['write_file', 'edit_file', 'append_to_file'].includes(name);
    }

    private openDiffEditor(msg: ServerMessage): void {
        // See Section 6 for detailed diff flow
    }

    private postToWebview(message: ExtensionMessage): void {
        this.view?.webview.postMessage(message);
    }

    private getHtmlForWebview(webview: vscode.Webview): string {
        // Returns HTML that loads the React app bundle
    }
}
```

#### 5.2.4 File: `src/diff-provider.ts` -- TextDocumentContentProvider

```typescript
import * as vscode from 'vscode';

/**
 * Provides virtual document content for the claraity-diff:// URI scheme.
 *
 * Used to show file diffs in VS Code's native diff editor. The URI encodes:
 * - The call_id (for linking back to the tool call)
 * - A side indicator: "before" or "after"
 *
 * URI format: claraity-diff://call_id/side?path=encoded_file_path
 *
 * Example:
 *   claraity-diff://call_abc123/before?path=%2Fsrc%2Fmain.py
 *   claraity-diff://call_abc123/after?path=%2Fsrc%2Fmain.py
 */
export class DiffContentProvider implements vscode.TextDocumentContentProvider {
    private contents = new Map<string, string>();
    private onDidChangeEmitter = new vscode.EventEmitter<vscode.Uri>();
    public onDidChange = this.onDidChangeEmitter.event;

    /**
     * Store content for a diff side and notify VS Code that the document changed.
     * Called by the extension when a file edit tool call arrives.
     *
     * The onDidChangeEmitter.fire() call is required so that VS Code
     * re-reads the content via provideTextDocumentContent() if the
     * document was already opened (e.g., user re-requests "View Diff").
     */
    setContent(callId: string, side: 'before' | 'after', content: string): void {
        const key = `${callId}/${side}`;
        this.contents.set(key, content);

        // Notify VS Code that this virtual document's content has changed
        const uri = vscode.Uri.parse(`claraity-diff://${callId}/${side}`);
        this.onDidChangeEmitter.fire(uri);
    }

    provideTextDocumentContent(uri: vscode.Uri): string {
        // URI authority = callId, path = /side
        const key = `${uri.authority}${uri.path}`;
        return this.contents.get(key) ?? '';
    }

    /**
     * Clear stored content for a call (after accept/reject).
     */
    clearContent(callId: string): void {
        this.contents.delete(`${callId}/before`);
        this.contents.delete(`${callId}/after`);
    }
}
```

### 5.3 WebView React App (`claraity-vscode/webview-ui/`)

#### 5.3.1 Component Tree

```
<App>
  <ConnectionStatus />           -- "Connected" / "Reconnecting..."
  <ContextBar />                 -- Context window usage bar
  <ChatHistory>
    <UserMessage />              -- User's message bubble
    <AssistantMessage>           -- Agent response (streaming)
      <MarkdownBlock />          -- Rendered markdown text
      <CodeBlock />              -- Syntax-highlighted code
      <ThinkingBlock />          -- Collapsible thinking (Phase 2)
      <ToolCard>                 -- Tool execution card
        <ToolHeader />           -- Tool name + status icon
        <ToolArguments />        -- Collapsed args display
        <ApprovalButtons />      -- Accept / Reject / Auto-approve
        <ToolResult />           -- Result or error display
      </ToolCard>
    </AssistantMessage>
    <ErrorBanner />              -- Recoverable error with retry button
  </ChatHistory>
  <ChatInput />                  -- Text input + send button + interrupt
</App>
```

#### 5.3.2 Key Component: `ToolCard`

```typescript
interface ToolCardProps {
    callId: string;
    name: string;
    arguments: Record<string, any>;
    requiresApproval: boolean;
    status: ToolStatus;
    result?: string;
    error?: string;
    durationMs?: number;
    onApprove: (callId: string, autoFuture: boolean) => void;
    onReject: (callId: string, feedback?: string) => void;
}

function ToolCard({ callId, name, arguments, requiresApproval, status, ... }: ToolCardProps) {
    // Renders:
    // - Header: tool name (e.g., "edit_file") + status badge
    // - Arguments: collapsible JSON view
    // - If requiresApproval && status === "awaiting_approval":
    //     Accept button, Reject button, "Always allow" checkbox
    // - If status === "success": green result preview
    // - If status === "error": red error message
    // - For file edit tools: "View Diff" button
}
```

#### 5.3.3 State Management

The WebView uses React `useReducer` for state management. No external state library.

```typescript
interface ChatState {
    messages: ChatMessage[];
    isStreaming: boolean;
    connectionStatus: 'connected' | 'disconnected' | 'reconnecting';
    contextUsage: { used: number; limit: number; level: string } | null;
    sessionId: string | null;
    pendingApprovals: Map<string, ToolCallInfo>;
}

type ChatAction =
    | { type: 'SERVER_MESSAGE'; payload: ServerMessage }
    | { type: 'USER_MESSAGE'; content: string }
    | { type: 'CONNECTION_STATUS'; status: string }
    | { type: 'CLEAR' };

function chatReducer(state: ChatState, action: ChatAction): ChatState {
    if (action.type === 'SERVER_MESSAGE') {
        const msg = action.payload;
        switch (msg.type) {
            case 'stream_start':
                return { ...state, isStreaming: true, ... };
            case 'text_delta':
                // Append to current assistant message
                ...
            case 'store':
                // Handle store notifications (tool state, message lifecycle)
                if (msg.event === 'tool_state_updated') {
                    // Add or update tool card in current message
                    ...
                }
                ...
            case 'stream_end':
                return { ...state, isStreaming: false, ... };
            // ... handle all server message types
        }
    }
    ...
}
```

#### 5.3.4 Build Tooling

The WebView app is built with:
- **Vite** for bundling (fast HMR during development)
- **React 18** with TypeScript
- **VS Code CSS variables** for theming (e.g., `var(--vscode-editor-background)`, `var(--vscode-button-background)`). **Note:** `@vscode/webview-ui-toolkit` is deprecated as of 2024 and should NOT be used. Use native VS Code CSS custom properties directly for consistent theming. See [VS Code Webview theming guide](https://code.visualstudio.com/api/extension-guides/webview#theming-webview-content).
- **react-markdown** + `rehype-highlight` for markdown rendering with syntax highlighting

The build output is a single `webview.js` bundle that the extension loads into the WebView HTML.

---

## 6. File Diff Flow

This is the most important VS Code-native integration. When the agent edits a file, the user sees a side-by-side diff in VS Code's built-in diff editor, with Accept/Reject actions.

### Step-by-Step Walkthrough

```
Step 1: Agent decides to edit a file
  Agent calls edit_file(file_path="/src/main.py", old_string="...", new_string="...")
  Agent calls MessageStore.update_tool_state() with status=AWAITING_APPROVAL

Step 2: Server pre-computes diff content and sends
  WebSocketProtocol's StoreNotification callback detects a file edit tool
  in AWAITING_APPROVAL state. It pre-computes the before/after content
  server-side and includes them in the tool state metadata:

  {
    "type": "store",
    "event": "tool_state_updated",
    "data": {
      "call_id": "call_abc123",
      "tool_name": "edit_file",
      "status": "awaiting_approval",
      "arguments": {
        "file_path": "/src/main.py",
        "old_string": "def foo():\n    pass",
        "new_string": "def foo():\n    return 42"
      },
      "requires_approval": true,
      "diff": {
        "original_content": "# main.py\n\ndef foo():\n    pass\n\ndef bar():\n    ...",
        "modified_content": "# main.py\n\ndef foo():\n    return 42\n\ndef bar():\n    ..."
      }
    }
  }

  WHY server-side pre-computation: The naive TypeScript `String.replace(oldString,
  newString)` only replaces the FIRST occurrence, which may produce incorrect
  diffs when old_string appears multiple times. The Python server has the actual
  edit_file logic and can compute the correct result. For write_file,
  original_content is "" (or current file content if overwriting) and
  modified_content is the full content argument. For append_to_file,
  original_content is current file content and modified_content is
  current + appended content.

Step 3: Extension host receives and opens diff
  SidebarProvider.handleServerMessage() detects edit_file tool with diff data:

  a) Extract pre-computed content from the message:
     const original = msg.data.diff.original_content;
     const modified = msg.data.diff.modified_content;

  b) Store both sides in DiffContentProvider:
     diffProvider.setContent("call_abc123", "before", original);
     diffProvider.setContent("call_abc123", "after", modified);

  c) Construct virtual URIs:
     const beforeUri = vscode.Uri.parse(
       `claraity-diff://call_abc123/before?path=${encodeURIComponent(filePath)}`
     );
     const afterUri = vscode.Uri.parse(
       `claraity-diff://call_abc123/after?path=${encodeURIComponent(filePath)}`
     );

  d) Open VS Code diff editor:
     await vscode.commands.executeCommand('vscode.diff',
       beforeUri,
       afterUri,
       `ClarAIty: ${path.basename(filePath)}`,
       { preview: true }
     );

Step 4: User reviews diff in native diff editor
  - Side-by-side view with syntax highlighting
  - Can navigate hunks with standard diff shortcuts
  - Sees green/red coloring for additions/deletions

Step 5: WebView shows tool card with approval buttons
  The WebView simultaneously renders a ToolCard for "edit_file" with:
  - [Accept] button  -- approves the edit
  - [Reject] button  -- rejects the edit
  - "View Diff" link -- (re)focuses the diff editor tab
  - "Always allow edit_file" checkbox

Step 6a: User clicks Accept
  WebView sends postMessage:
    { type: 'approvalResult', callId: 'call_abc123', approved: true }

  Extension host forwards to server:
    { type: 'approval_result', call_id: 'call_abc123', approved: true }

  Server deserializes to ApprovalResult, calls UIProtocol.submit_action()

  Agent receives approval, executes the edit_file tool

  Server sends store notification:
    { "type": "store", "event": "tool_state_updated",
      "data": { "call_id": "call_abc123", "status": "success", ... } }

  Extension host closes the diff editor tab:
    diffProvider.clearContent('call_abc123');

Step 6b: User clicks Reject
  Same flow but approved=false.
  Agent receives rejection, skips tool execution.
  Extension host closes the diff editor tab.
  Agent reports rejection to LLM and continues.

Step 7: For write_file (new file)
  Server sends diff.original_content as empty string.
  diff.modified_content is the full file content.
  Diff editor shows all lines as additions (green).
```

### Diff URI Scheme

```
claraity-diff://{call_id}/{side}?path={encoded_file_path}

Examples:
  claraity-diff://call_abc123/before?path=%2Fsrc%2Fmain.py
  claraity-diff://call_abc123/after?path=%2Fsrc%2Fmain.py
```

| URI Component | Value | Purpose |
|---------------|-------|---------|
| Scheme | `claraity-diff` | Registered with `TextDocumentContentProvider` |
| Authority | `call_abc123` | Links to the tool call for accept/reject |
| Path | `/before` or `/after` | Which side of the diff |
| Query `path` | URL-encoded file path | Original file path (for display and language detection) |

### Handling `edit_file` vs `write_file` vs `append_to_file`

The server pre-computes `diff.original_content` and `diff.modified_content` for each tool type. The extension does not replicate Python edit logic.

| Tool | `diff.original_content` | `diff.modified_content` | Computed By |
|------|------------------------|------------------------|-------------|
| `edit_file` | Current file content read from disk | Content with `old_string` replaced by `new_string` | Python `edit_file` tool logic |
| `write_file` | Empty string (or current content if file exists) | Full `content` argument | Server |
| `append_to_file` | Current file content | Current content + appended `content` | Server |

---

## 7. Tool Approval Flow

### Lifecycle Sequence

```
+----------+  +--------+  +----------+  +-----------+  +----------+  +-------+
|  Agent   |  | Store  |  |  Server  |  | Extension |  |  WebView |  | User  |
+----+-----+  +---+----+  +----+-----+  +-----+-----+  +----+-----+  +---+---+
     |             |            |              |              |             |
     | update_     |            |              |              |             |
     | tool_state  |            |              |              |             |
     | (AWAITING_  |            |              |              |             |
     |  APPROVAL)  |            |              |              |             |
     +------------>|            |              |              |             |
     |             | StoreNotif |              |              |             |
     |             | TOOL_STATE |              |              |             |
     |             | _UPDATED   |              |              |             |
     |             +----------->|              |              |             |
     |             |            | store:       |              |             |
     |             |            | tool_state_  |              |             |
     |             |            | updated (WS) |              |             |
     |             |            +------------->|              |             |
     |             |            |              | postMessage  |             |
     |             |            |              | (serverMsg)  |             |
     |             |            |              +------------->|             |
     |             |            |              |              | Render      |
     |             |            |              |              | ToolCard    |
     |             |            |              |              | w/ buttons  |
     |             |            |              |              +------------>|
     |             |            |              |              |             |
     | UIProtocol. |            |              |              |   Click     |
     | wait_for_   |            |              |              |   Accept    |
     | approval()  |            |              |              |<------------+
     | (BLOCKED)   |            |              |              |             |
     |             |            |              | postMessage  |             |
     |             |            |              | (approval)   |             |
     |             |            |              |<-------------+             |
     |             |            | approval_    |              |             |
     |             |            | result (WS)  |              |             |
     |             |            |<-------------+              |             |
     |             |            |              |              |             |
     | Approval    |            |              |              |             |
     | Result (via |            |              |              |             |
     | submit_     |            |              |              |             |
     | action)     |            |              |              |             |
     |<-----------[Server]      |              |              |             |
     |             |            |              |              |             |
     | Execute tool|            |              |              |             |
     +----+        |            |              |              |             |
     |    |        |            |              |              |             |
     |<---+        |            |              |              |             |
     |             |            |              |              |             |
     | update_     |            |              |              |             |
     | tool_state  |            |              |              |             |
     | (SUCCESS)   |            |              |              |             |
     +------------>|            |              |              |             |
     |             | StoreNotif |              |              |             |
     |             +----------->|              |              |             |
     |             |            | store:       |              |             |
     |             |            | tool_state_  |              |             |
     |             |            | updated (WS) |              |             |
     |             |            +------------->|              |             |
     |             |            |              | postMessage  |             |
     |             |            |              +------------->|             |
     |             |            |              |              | Update      |
     |             |            |              |              | ToolCard    |
     |             |            |              |              | status      |
     |             |            |              |              +------------>|
```

### Auto-Approve Behavior

When the user checks "Always allow" for a tool and clicks Accept:

1. WebView sends `auto_approve_future: true` in the approval result
2. Server deserializes and calls `UIProtocol.submit_action(ApprovalResult(auto_approve_future=True))`
3. `UIProtocol.submit_action()` adds the tool name to `self._auto_approve` set (protocol.py line 392)
4. Future calls to the same tool return immediately from `wait_for_approval()` (protocol.py line 191). The store notification for these auto-approved tools will show `status: "running"` (or `"success"`) without passing through `"awaiting_approval"`
5. The WebView sees these auto-approved tools arrive as `store:tool_state_updated` without an `"awaiting_approval"` state, and renders them with an "Auto-approved" badge instead of approval buttons

### Approval Timeout

Phase 1 does not implement approval timeout. The agent blocks indefinitely on `UIProtocol.wait_for_approval()`. The user can interrupt via the Interrupt button (sends `InterruptSignal`), which cancels pending approval futures (protocol.py line 416-418).

---

## 8. Extension <-> WebView Protocol

The `postMessage` bridge uses typed messages. Both directions are defined below.

### 8.1 Extension -> WebView Messages

```typescript
/**
 * Messages sent from extension host to WebView via webview.postMessage().
 */
type ExtensionMessage =
    | { type: 'serverMessage'; payload: ServerMessage }
    | { type: 'connectionStatus'; status: 'connected' | 'disconnected' | 'reconnecting' }
    | { type: 'sessionInfo'; sessionId: string; model: string; permissionMode: string }
    | { type: 'diffOpened'; callId: string; filePath: string }
    | { type: 'diffClosed'; callId: string; accepted: boolean }
    | { type: 'themeChanged'; isDark: boolean };
```

### 8.2 WebView -> Extension Messages

```typescript
/**
 * Messages sent from WebView to extension host via vscode.postMessage().
 */
type WebViewMessage =
    | { type: 'chatMessage'; content: string }
    | { type: 'approvalResult'; callId: string; approved: boolean; autoApproveFuture?: boolean; feedback?: string }
    | { type: 'interrupt' }
    | { type: 'retry' }
    | { type: 'pauseResult'; continueWork: boolean; feedback?: string }
    | { type: 'viewDiff'; callId: string }
    | { type: 'openFile'; filePath: string; line?: number }
    | { type: 'copyToClipboard'; text: string }
    | { type: 'ready' };  // WebView finished loading
```

### 8.3 TypeScript Interface Definitions

```typescript
// --- Wire protocol types (WebSocket JSON) ---

interface ServerMessage {
    type: string;
    [key: string]: any;
}

// Discriminated union for typed handling
type TypedServerMessage =
    // UIEvent-derived messages
    | StreamStartMessage
    | StreamEndMessage
    | TextDeltaMessage
    | CodeBlockStartMessage
    | CodeBlockDeltaMessage
    | CodeBlockEndMessage
    | ThinkingStartMessage
    | ThinkingDeltaMessage
    | ThinkingEndMessage
    | PausePromptStartMessage
    | PausePromptEndMessage
    | ContextUpdatedMessage
    | ContextCompactedMessage
    | FileReadMessage
    | ErrorMessage
    // StoreNotification-derived messages
    | StoreToolStateUpdatedMessage
    | StoreMessageAddedMessage
    | StoreMessageUpdatedMessage
    | StoreMessageFinalizedMessage
    // Synthetic messages
    | SessionInfoMessage;

interface StreamStartMessage {
    type: 'stream_start';
    // Empty: StreamStart is an empty dataclass. Session ID is in session_info.
}

interface StreamEndMessage {
    type: 'stream_end';
    total_tokens: number | null;
    duration_ms: number | null;
}

interface TextDeltaMessage {
    type: 'text_delta';
    content: string;
}

interface CodeBlockStartMessage {
    type: 'code_block_start';
    language: string;
}

interface CodeBlockDeltaMessage {
    type: 'code_block_delta';
    content: string;
}

interface CodeBlockEndMessage {
    type: 'code_block_end';
}

// ToolStatus wire values (canonical: src/core/tool_status.py)
// Note: "failed" is NOT included -- events.py FAILED is normalized to "error"
type ToolStatus =
    | 'pending'
    | 'awaiting_approval'
    | 'approved'
    | 'rejected'
    | 'running'
    | 'success'
    | 'error'
    | 'timeout'
    | 'cancelled'
    | 'skipped';

// --- StoreNotification-derived messages ---
// These use "type": "store" with an "event" discriminator

interface StoreToolStateUpdatedMessage {
    type: 'store';
    event: 'tool_state_updated';
    data: {
        call_id: string;
        tool_name: string;
        status: ToolStatus;
        arguments?: Record<string, any>;
        requires_approval?: boolean;
        result?: any;
        error?: string | null;
        duration_ms?: number | null;
        message?: string | null;
        // Pre-computed diff content for file edit tools (see Section 6)
        diff?: {
            original_content: string;
            modified_content: string;
        };
    };
}

interface StoreMessageAddedMessage {
    type: 'store';
    event: 'message_added';
    data: {
        uuid: string;
        role: 'user' | 'assistant' | 'system' | 'tool_result';
        content: string;
        stream_id?: string;
    };
}

interface StoreMessageUpdatedMessage {
    type: 'store';
    event: 'message_updated';
    data: {
        uuid: string;
        role: string;
        content: string;
    };
}

interface StoreMessageFinalizedMessage {
    type: 'store';
    event: 'message_finalized';
    data: {
        stream_id: string;
    };
}

interface ThinkingStartMessage {
    type: 'thinking_start';
}

interface ThinkingDeltaMessage {
    type: 'thinking_delta';
    content: string;
}

interface ThinkingEndMessage {
    type: 'thinking_end';
    token_count: number | null;
}

interface PausePromptStartMessage {
    type: 'pause_prompt_start';
    reason: string;
    reason_code: string;
    pending_todos: string[];
    stats: Record<string, any>;
}

interface PausePromptEndMessage {
    type: 'pause_prompt_end';
    continue_work: boolean;
    feedback: string | null;
}

interface ContextUpdatedMessage {
    type: 'context_updated';
    used: number;
    limit: number;
    pressure_level: 'green' | 'yellow' | 'orange' | 'red';
}

interface ContextCompactedMessage {
    type: 'context_compacted';
    messages_removed: number;
    tokens_before: number;
    tokens_after: number;
}

interface FileReadMessage {
    type: 'file_read';
    path: string;
    lines_read: number;
    truncated: boolean;
}

interface ErrorMessage {
    type: 'error';
    error_type: 'provider_timeout' | 'network' | 'rate_limit' | 'api_error' | 'auth';
    user_message: string;
    error_id: string;
    recoverable: boolean;
    retry_after: number | null;
}

interface SessionInfoMessage {
    type: 'session_info';
    session_id: string;
    model_name: string;
    permission_mode: 'normal' | 'auto' | 'plan';
    working_directory: string;
}

// --- Client-to-server message types ---

interface ChatMessagePayload {
    type: 'chat_message';
    content: string;
    attachments?: any[];
}

interface ApprovalResultPayload {
    type: 'approval_result';
    call_id: string;
    approved: boolean;
    auto_approve_future?: boolean;
    feedback?: string | null;
}

interface InterruptPayload {
    type: 'interrupt';
}

interface RetryPayload {
    type: 'retry';
}

interface PauseResultPayload {
    type: 'pause_result';
    continue_work: boolean;
    feedback?: string | null;
}

interface ClarifyResultPayload {
    type: 'clarify_result';
    call_id: string;
    submitted: boolean;
    responses?: Record<string, any> | null;
    chat_instead?: boolean;
    chat_message?: string | null;
}

interface PlanApprovalResultPayload {
    type: 'plan_approval_result';
    plan_hash: string;
    approved: boolean;
    auto_accept_edits?: boolean;
    feedback?: string | null;
}

type ClientMessage =
    | ChatMessagePayload
    | ApprovalResultPayload
    | InterruptPayload
    | RetryPayload
    | PauseResultPayload
    | ClarifyResultPayload
    | PlanApprovalResultPayload;
```

---

## 9. Session Management

### 9.1 Session Lifecycle

Sessions in the VS Code integration follow the same JSONL-based persistence model as the TUI (see `docs/SESSION_PERSISTENCE.md`). The server manages sessions via `MemoryManager` (the single writer) and `MessageStore`.

```
Extension connects to server
    |
    v
Server creates new session (or resumes existing)
    |
    v
Server sends session_info message
    |
    v
Extension displays session ID in status bar
    |
    v
User chats... agent streams responses...
    |
    v
MemoryManager persists each turn to JSONL
(.clarity/sessions/<session_id>.jsonl)
    |
    v
Extension disconnects (or user closes VS Code)
    |
    v
Session remains on disk for future resume
```

### 9.2 Session Creation

When the extension connects to the server:

1. Server checks if there is an active session (from a previous connection)
2. If no active session, creates a new one:
   - Generates UUID via `uuid.uuid4()`
   - Creates `MessageStore` instance
   - Initializes JSONL file at `.clarity/sessions/<session_id>.jsonl`
   - Wires `MemoryManager` to store
3. Sends `session_info` message to client with session ID, model, and permission mode

### 9.3 Session Resume (Phase 2)

When the extension sends `session_resume`:

1. Server loads JSONL file via `CodingAgent.resume_session_from_jsonl()` (agent.py line 3640)
2. Replays messages into `MessageStore`
3. Sends the replayed message history to the client as a batch:

```jsonc
{
    "type": "session_history",
    "messages": [
        { "role": "user", "content": "..." },
        { "role": "assistant", "content": "...", "segments": [...] },
        ...
    ]
}
```

4. Client renders the history in the chat view
5. Sends `session_info` with the resumed session's metadata

### 9.4 Session Persistence Format

Unchanged from existing format. The JSONL file at `.clarity/sessions/<session_id>.jsonl` contains one JSON object per line:

```jsonc
{"role": "user", "meta": {"uuid": "...", "timestamp": "..."}, "content": "Add error handling"}
{"role": "assistant", "meta": {"uuid": "...", "stream_id": "...", "segments": [...]}, "content": "I'll add try/catch..."}
{"role": "tool_result", "meta": {"tool_call_id": "...", "tool_name": "edit_file"}, "content": "File edited successfully"}
```

---

## 10. Phasing

### Phase 1: MVP (4-6 weeks)

| # | Feature | Status |
|---|---------|--------|
| 1 | Python WebSocket server (`src/server/`) | Planned |
| 2 | UIEvent JSON serialization | Planned |
| 3 | UserAction JSON deserialization | Planned |
| 4 | VS Code extension scaffold (package.json, activation) | Planned |
| 5 | WebSocket client in extension host | Planned |
| 6 | WebView with React chat UI | Planned |
| 7 | Markdown rendering with syntax highlighting | Planned |
| 8 | TextDelta streaming display | Planned |
| 9 | ToolCard component with status badges | Planned |
| 10 | Tool approval flow (Accept/Reject buttons) | Planned |
| 11 | File diff via `vscode.diff` + `TextDocumentContentProvider` | Planned |
| 12 | Context window usage bar | Planned |
| 13 | Error display with retry | Planned |
| 14 | Session creation (auto on connect) | Planned |
| 15 | Connection status indicator | Planned |
| 16 | Interrupt button (sends InterruptSignal) | Planned |
| 17 | Status bar item | Planned |

### Phase 2: Polish (3-4 weeks)

| # | Feature | Status |
|---|---------|--------|
| 1 | Session resume + session picker | Planned |
| 2 | Permission mode switching (Normal/Auto/Plan) | Planned |
| 3 | Thinking/reasoning block (collapsible) | Planned |
| 4 | Pause/Continue flow | Planned |
| 5 | Clarify interview widget | Planned |
| 6 | Plan approval widget | Planned |
| 7 | Auto-approve "Always allow" persistence | Planned |
| 8 | Code block copy button | Planned |
| 9 | File path click-to-open | Planned |
| 10 | Extension settings (port, model, etc.) | Planned |

### Phase 3: Advanced (Ongoing)

| # | Feature | Status |
|---|---------|--------|
| 1 | Inline code actions (right-click menu) | Future |
| 2 | Diagnostics integration | Future |
| 3 | Git SCM integration | Future |
| 4 | Multiple concurrent sessions | Future |
| 5 | Director mode UI | Future |
| 6 | File watcher for collaborative edits | Future |
| 7 | Marketplace publishing | Future |
| 8 | Remote server support | Future |

---

## 11. File Structure

### New Python Files

```
src/
  server/
    __init__.py              # Exports: start_server, AgentServer, WebSocketProtocol
    __main__.py              # CLI entry: python -m src.server [--port 9120]
    app.py                   # AgentServer: HTTP + WebSocket server
    ws_protocol.py           # WebSocketProtocol: extends UIProtocol for WebSocket
    serializers.py           # Pure functions: serialize_event(), deserialize_action()
```

### New VS Code Extension Files

```
claraity-vscode/
  .vscode/
    launch.json              # Debug configuration for extension development
    tasks.json               # Build tasks
  src/
    extension.ts             # activate() / deactivate()
    agent-connection.ts      # WebSocket client + reconnection logic
    sidebar-provider.ts      # WebviewViewProvider implementation
    diff-provider.ts         # TextDocumentContentProvider for claraity-diff://
    types.ts                 # TypeScript interfaces (wire protocol + postMessage)
    utils.ts                 # Helpers: URI construction, path encoding
  webview-ui/
    src/
      App.tsx                # Root component
      index.tsx              # React entry point
      state/
        reducer.ts           # Chat state reducer
        types.ts             # State types
      components/
        ChatHistory.tsx      # Message list container
        UserMessage.tsx      # User message bubble
        AssistantMessage.tsx  # Agent response (streaming)
        MarkdownBlock.tsx    # Markdown renderer
        CodeBlock.tsx        # Syntax-highlighted code block
        ThinkingBlock.tsx    # Collapsible thinking block (Phase 2)
        ToolCard.tsx         # Tool execution card with approval
        ToolArguments.tsx    # Collapsed argument display
        ApprovalButtons.tsx  # Accept/Reject/Auto-approve
        ErrorBanner.tsx      # Recoverable error display
        ConnectionStatus.tsx # Connection indicator
        ContextBar.tsx       # Context window usage bar
        ChatInput.tsx        # Text input + send + interrupt
      hooks/
        useVSCodeApi.ts      # vscode.postMessage wrapper
        useTheme.ts          # VS Code theme detection
      styles/
        global.css           # Base styles using VS Code CSS custom properties (no @vscode/webview-ui-toolkit)
    vite.config.ts           # Vite build configuration
    tsconfig.json            # TypeScript config for webview
    package.json             # WebView dependencies (React, etc.)
  package.json               # Extension manifest (contributes, activationEvents)
  tsconfig.json              # TypeScript config for extension host
  esbuild.js                 # Extension host bundler config
  README.md                  # Extension readme (for marketplace)
  CHANGELOG.md               # Version history
```

### Files NOT Modified

The following existing files are reused without modification:

| File | Why |
|------|-----|
| `src/core/events.py` | UIEvent types are consumed by `WebSocketProtocol` via serialization |
| `src/core/protocol.py` | `UIProtocol` is the base class for `WebSocketProtocol` |
| `src/core/agent.py` | `CodingAgent` is used as-is; the server calls `stream_response()` |
| `src/memory/memory_manager.py` | Single writer pattern unchanged |
| `src/session/store/memory_store.py` | In-memory store + JSONL unchanged |
| `src/tools/*` | All tool implementations unchanged |

---

## 12. Testing Strategy

### 12.1 Python Server Tests

#### Unit Tests: Serializers

```
tests/server/test_serializers.py
```

- Test every `UIEvent` type serializes to correct JSON shape
- Test every `UserAction` type deserializes from JSON correctly
- Test unknown message types return `None` (not crash)
- Test `ToolStatus` enum serialization round-trips
- Test edge cases: `None` fields, empty strings, large payloads

Example:

```python
def test_serialize_text_delta():
    event = TextDelta(content="Hello world")
    result = serialize_event(event)
    assert result == {"type": "text_delta", "content": "Hello world"}

def test_deserialize_approval_result():
    data = {"type": "approval_result", "call_id": "c1", "approved": True}
    action = deserialize_action(data)
    assert isinstance(action, ApprovalResult)
    assert action.call_id == "c1"
    assert action.approved is True
    assert action.auto_approve_future is False  # default

def test_deserialize_unknown_type():
    data = {"type": "unknown_future_message"}
    assert deserialize_action(data) is None
```

#### Integration Tests: WebSocket Server

```
tests/server/test_ws_protocol.py
tests/server/test_app.py
```

- Test WebSocket connection lifecycle (connect, exchange messages, disconnect)
- Test health endpoint returns 200
- Test full chat round-trip: send chat_message, receive stream of events, verify order
- Test approval flow: send store:tool_state_updated (awaiting_approval), reply with approval_result
- Test interrupt: send interrupt during streaming, verify cancellation
- Test graceful shutdown

#### Mock Agent Tests

Use a mock `CodingAgent` that yields predetermined `UIEvent` sequences to test the server without an LLM.

### 12.2 VS Code Extension Tests

#### Unit Tests

```
claraity-vscode/src/test/
  serialization.test.ts    # Type guard tests for message parsing
  diff-provider.test.ts    # URI parsing, content storage/retrieval
  reducer.test.ts          # Chat state reducer logic
```

#### Integration Tests

Using VS Code Extension Testing framework (`@vscode/test-electron`):

- Test extension activates without errors
- Test WebView loads and sends `ready` message
- Test diff editor opens with correct content
- Test status bar item appears

### 12.3 WebView Component Tests

Using Vitest + React Testing Library:

```
claraity-vscode/webview-ui/src/test/
  ToolCard.test.tsx        # Renders approval buttons when awaiting
  ChatHistory.test.tsx     # Scrolls to bottom on new message
  MarkdownBlock.test.tsx   # Renders markdown correctly
  reducer.test.ts          # State transitions for all message types
```

### 12.4 End-to-End Verification

Manual checklist for each phase:

**Phase 1 Smoke Test:**
1. Start Python server: `python -m src.server`
2. Open VS Code with extension installed
3. Type a message in the chat panel
4. Verify streaming text appears
5. Trigger a file edit (e.g., "create a hello.py file")
6. Verify diff editor opens with correct content
7. Click Accept, verify file is created
8. Verify context bar shows usage
9. Click Interrupt during streaming, verify it stops
10. Verify `.clarity/sessions/` contains JSONL file

---

## 13. Known Challenges & Mitigations

### 13.1 Windows Encoding (cp1252)

**Challenge:** The ClarAIty agent runs on Windows where the default console encoding is cp1252. Emojis and certain Unicode characters crash the app (documented in CLAUDE.md).

**Mitigation:**
- The WebSocket transport is UTF-8. JSON encoding handles all Unicode correctly.
- The Python server does not write to the console; it uses `get_logger()` which writes to JSONL files.
- The VS Code WebView is a Chromium-based renderer that handles all Unicode.
- **Risk eliminated** for the VS Code path. The constraint only applies to CLI/TUI console output.

### 13.2 Single Connection Limit (Phase 1)

**Challenge:** Phase 1 supports only one WebSocket connection at a time.

**Mitigation:**
- Server rejects additional connections with a clear error message: `{"type": "error", "error_type": "connection_limit", "user_message": "Another client is already connected"}`
- Phase 2 will add session multiplexing

### 13.3 Agent Threading Model

**Challenge:** `CodingAgent` was designed for single-consumer use (one TUI or one CLI). The server must not introduce concurrent access.

**Mitigation:**
- One `CodingAgent` instance per server process (not per connection)
- One active `stream_response()` coroutine at a time
- The `WebSocketProtocol.receive_loop()` runs concurrently but only submits `UserAction` via the thread-safe `UIProtocol` queue

### 13.4 Tool Execution Blocking

**Challenge:** Some tools (e.g., `run_command`) execute blocking I/O. In the TUI, this runs in the asyncio event loop's thread pool executor.

**Mitigation:**
- Same pattern: `tool_executor.execute_tool_async()` already uses `asyncio.to_thread()` for blocking tools
- No change needed. The server's event loop handles this identically to the TUI.

### 13.5 Large Tool Results

**Challenge:** Tool results (e.g., `read_file` on a large file) can be very large. Sending them over WebSocket to the extension adds latency and memory pressure.

**Mitigation:**
- The agent already has a `_max_tool_output_chars` limit (agent.py) that returns an error for oversized outputs
- Tool results are displayed as collapsible summaries in the ToolCard, not rendered in full
- Phase 2 may add chunked transfer for large results

### 13.6 WebView State Loss

**Challenge:** VS Code may destroy and recreate WebView panels (e.g., when the panel is hidden and reshown, or on window reload).

**Mitigation:**
- Use `webview.setState()` / `webview.getState()` to persist chat state across WebView recreation
- On WebView reload, request current session state from server
- Connection survives WebView recreation (WebSocket is owned by extension host, not WebView)

### 13.7 Diff Editor Lifecycle

**Challenge:** The user might close the diff editor tab without clicking Accept/Reject.

**Mitigation:**
- Register `vscode.workspace.onDidCloseTextDocument` listener for `claraity-diff://` URIs
- If a diff document is closed while approval is pending, prompt the user: "You closed the diff for edit_file. Approve or reject?"
- Alternatively, the approval buttons remain visible in the WebView ToolCard regardless of whether the diff editor is open

### 13.8 WebSocket Reconnection

**Challenge:** The WebSocket connection may drop (server restart, network blip).

**Mitigation:**
- Extension host reconnects with exponential backoff
- On reconnect, server sends `session_info` for the current session
- WebView shows "Reconnecting..." indicator during disconnection
- Messages sent during disconnection are queued and replayed on reconnect (best effort)

---

## 14. References

### ClarAIty Source Code

| File | Purpose | Key Lines |
|------|---------|-----------|
| `src/core/events.py` | UIEvent types (the server serializes these) | Lines 1-302 (all event dataclasses) |
| `src/core/protocol.py` | UIProtocol base class (the server extends this) | Lines 113-543 (UIProtocol class) |
| `src/core/agent.py` | CodingAgent (the server wraps this) | Line 204 (class def), line 900 (async tool loop) |
| `src/ui/app.py` | AgentApp TUI (reference implementation for event handling) | Line 1331 (`_handle_event` -- how TUI handles UIEvents) |
| `src/ui/store_adapter.py` | StoreAdapter (reference for event-to-store mapping) | Lines 1-80 |
| `src/session/store/memory_store.py` | MessageStore (in-memory + JSONL persistence) | Lines 1-100 |
| `src/core/streaming/pipeline.py` | StreamingPipeline (canonical delta parser) | Lines 1-80 |
| `src/core/session_manager.py` | Session save/load/list | Lines 1-460 |
| `src/core/permission_mode.py` | PermissionMode enum and PermissionManager | Lines 1-59 |
| `src/core/render_meta.py` | RenderMetaRegistry (approval metadata for tool calls) | Lines 1-76 |
| `src/core/cancel_token.py` | CancelToken for cooperative cancellation | Lines 1-31 |
| `docs/SESSION_PERSISTENCE.md` | Session JSONL format specification | Full document |
| `docs/TUI_ARCHITECTURE.md` | TUI architecture (reference for event handling patterns) | Full document |
| `docs/UNIFIED_PERSISTENCE_ARCHITECTURE.md` | Persistence design (MemoryManager as single writer) | Full document |

### External References

- **Cline (Claude Dev):** [github.com/cline/cline](https://github.com/cline/cline) -- The primary inspiration for the VS Code integration pattern. Key files to study:
  - `src/core/webview/ClineProvider.ts` -- WebviewViewProvider implementation
  - `src/integrations/editor/DiffViewProvider.ts` -- TextDocumentContentProvider for diffs
  - `webview-ui/src/` -- React chat UI
- **VS Code Extension API:**
  - [WebviewViewProvider](https://code.visualstudio.com/api/references/vscode-api#WebviewViewProvider)
  - [TextDocumentContentProvider](https://code.visualstudio.com/api/references/vscode-api#TextDocumentContentProvider)
  - [vscode.diff command](https://code.visualstudio.com/api/references/commands#commands)
  - [Extension Testing](https://code.visualstudio.com/api/working-with-extensions/testing-extension)
- **VS Code Webview UI Toolkit:** [github.com/microsoft/vscode-webview-ui-toolkit](https://github.com/microsoft/vscode-webview-ui-toolkit) -- **DEPRECATED** (archived 2024). Use VS Code CSS custom properties directly instead. See [Webview theming docs](https://code.visualstudio.com/api/extension-guides/webview#theming-webview-content).
- **aiohttp WebSocket Server:** [docs.aiohttp.org/en/stable/web_quickstart.html#websockets](https://docs.aiohttp.org/en/stable/web_quickstart.html#websockets)

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **UIEvent** | A frozen dataclass emitted by the agent during streaming. Defined in `src/core/events.py`. |
| **UserAction** | A frozen dataclass representing user input sent to the agent. Defined in `src/core/protocol.py`. |
| **UIProtocol** | The bidirectional communication layer between agent and UI. Uses async queues and futures. |
| **WebSocketProtocol** | The new subclass of UIProtocol that serializes events to JSON over WebSocket. |
| **MessageStore** | In-memory projection of session messages with JSONL persistence. Single writer is MemoryManager. |
| **StoreAdapter** | Read-only bridge from UIEvents to MessageStore. Used by TUI, not by VS Code extension. |
| **StreamingPipeline** | The canonical parser for LLM deltas. Produces Message objects with segments. |
| **RenderMetaRegistry** | Ephemeral registry mapping tool_call_id to approval metadata. |
| **ToolCard** | React component in the WebView that displays a tool call with status and approval buttons. |
| **DiffContentProvider** | VS Code TextDocumentContentProvider for `claraity-diff://` virtual documents. |

## Appendix B: Configuration

### Server Configuration

The server reads configuration from the same `.env` file as the CLI/TUI:

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CLARAITY_SERVER_HOST` | `127.0.0.1` | Server bind address |
| `CLARAITY_SERVER_PORT` | `9120` | Server port |
| `LLM_MODEL` | (required) | Model name |
| `LLM_BACKEND` | (required) | Backend type (openai/ollama) |
| `LLM_HOST` | (required) | LLM API base URL |
| `MAX_CONTEXT_TOKENS` | (required) | Context window size |

### Extension Configuration

VS Code settings (`contributes.configuration` in `package.json`):

| Setting | Default | Description |
|---------|---------|-------------|
| `claraity.serverUrl` | `ws://localhost:9120/ws` | WebSocket server URL |
| `claraity.autoConnect` | `true` | Connect automatically on extension activation |
| `claraity.diffEditorAutoOpen` | `true` | Auto-open diff editor for file edits |

---

## Appendix C: Review History

### Review 1: Internal Architecture Review

| Field | Value |
|-------|-------|
| **Date** | 2026-02-17 |
| **Reviewer** | Internal architecture review |
| **Score** | 3.5/5 -- REQUEST CHANGES |
| **Status** | RESOLVED |

**Critical Findings (resolved):**

1. **Tool events flow through MessageStore, not UIEvent stream.** The original document incorrectly assumed `ToolCallStart`/`ToolCallStatus`/`ToolCallResult` were yielded by `stream_response()`. They are legacy types (events.py lines 108-147), no longer yielded. Tool state flows through `MessageStore.update_tool_state()` -> `StoreNotification(TOOL_STATE_UPDATED)`. **Fix:** Added "Dual Subscription Model" section (Section 3), updated architecture diagram, data flow, wire protocol (Section 4.2.4, 4.2.10), and `WebSocketProtocol` design (Section 5.1.3).

2. **StreamStart has no fields.** Original showed `session_id` and `stream_id` as fields. The actual dataclass is empty (`pass`). **Fix:** Updated wire format to `{"type": "stream_start"}` with empty data. Session ID sent via `session_info` synthetic message.

3. **`chat_async()` vs `stream_response()`.** Original referenced `chat_async()` in several places. The correct entry point is `stream_response(user_input, ui_protocol, attachments)`. **Fix:** Replaced all references.

**Important Findings (resolved):**

4. **Two ToolStatus enums.** `events.py` has FAILED and ERROR as separate values; `tool_status.py` has only ERROR. **Fix:** Documented `tool_status.py` as canonical for wire format. Serializer normalizes FAILED to "error".

5. **No Clarify trigger event exists.** `ClarifyResult` is defined but there is no corresponding UIEvent to trigger the clarify UI. **Fix:** Deferred to Phase 2 with explanatory note.

6. **edit_file diff: naive String.replace() only replaces first occurrence.** **Fix:** Server now pre-computes `original_content` and `modified_content` in tool state metadata. Extension does not replicate Python edit logic.

7. **WebSocket send concurrency.** Two writers (UIEvent loop + StoreNotification callback) can interleave frames. **Fix:** Added `asyncio.Lock` to `WebSocketProtocol` and `loop.call_soon_threadsafe()` for store callbacks.

8. **DiffContentProvider missing `onDidChange` fire.** **Fix:** Added `this.onDidChangeEmitter.fire(uri)` to `setContent()`.

**Reviewer Suggestions (incorporated):**

- Pause/Continue marked as "Phase 2 only" in phasing table and wire protocol section
- Serialization uses `dataclasses.asdict()` with special-case overrides
- Windows `SelectorEventLoopPolicy` added to `__main__.py` design
- `@vscode/webview-ui-toolkit` noted as deprecated; use VS Code CSS custom properties
- "Synthetic Messages" subsection added (Section 4.2.11) for server-only messages
