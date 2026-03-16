# ClarAIty Architecture Deep Dive

> **Purpose**: Complete architectural trace of ClarAIty from VS Code Extension (React) through every layer to persistence. Optimized for LLM consumption and usable as a training guide for building a cutting-edge coding agent.
>
> **Scope**: VS Code React webview -> Extension Host -> stdio transport -> Python server -> Agent core -> LLM -> Tools -> Memory -> Persistence -> Observability
>
> **Out of scope**: TUI, CLI, WebSocket transport, inline HTML webview

---

## 1. System Topology

```mermaid
graph TB
    subgraph "VS Code Extension"
        WV[React Webview<br/>22 components, 1215-line reducer]
        EH[Extension Host<br/>extension.ts + sidebar-provider.ts]
        PM[postMessage API]
        WV <-->|ExtensionMessage / WebViewMessage| PM
        PM <-->|postMessage| EH
    end

    subgraph "Transport Layer"
        STDIN[stdin pipe<br/>JSON-RPC commands]
        TCP[TCP socket<br/>JSON-RPC events]
        EH -->|ClientMessage| STDIN
        TCP -->|ServerMessage| EH
    end

    subgraph "Python Server"
        STDIO[StdioProtocol<br/>stdio_server.py 1081 lines]
        JRPC[jsonrpc.py<br/>envelope wrap/unwrap]
        SER[serializers.py<br/>UIEvent <-> JSON]
        CFG[config_handler.py<br/>LLM config CRUD]
        SAB[subagent_bridge.py<br/>subagent event relay]
        STDIN --> STDIO
        STDIO --> TCP
        STDIO --> JRPC
        STDIO --> SER
        STDIO --> CFG
        STDIO --> SAB
    end

    subgraph "Agent Core"
        AGT[CodingAgent<br/>agent.py 3078 lines]
        TG[ToolGatingService<br/>4-layer permission]
        STH[SpecialToolHandlers<br/>clarify/plan/director]
        SP[StreamPhases<br/>context builders]
        TLS[ToolLoopState<br/>budget tracking]
        ER[ErrorRecovery<br/>retry prevention]
        AGT --> TG
        AGT --> STH
        AGT --> SP
        AGT --> TLS
        AGT --> ER
    end

    subgraph "Tool System"
        TE[ToolExecutor<br/>25+ tools]
        FO[FileOperations<br/>read/write/edit/append]
        DEL[DelegationTool<br/>subprocess IPC]
        KT[KnowledgeTools<br/>KB manifest]
        MCP[MCP Integration<br/>external tools]
        TE --> FO
        TE --> DEL
        TE --> KT
        TE --> MCP
    end

    subgraph "LLM Backend"
        LLM[LLMBackend ABC]
        OAI[OpenAIBackend<br/>1600 lines]
        ANT[AnthropicBackend<br/>1400 lines]
        OLL[OllamaBackend<br/>193 lines]
        FH[FailureHandler<br/>retry + backoff]
        CS[CredentialStore<br/>keyring + env]
        LLM --> OAI
        LLM --> ANT
        LLM --> OLL
        LLM --> FH
        LLM --> CS
    end

    subgraph "Memory & Context"
        MM[MemoryManager<br/>single writer]
        WM[WorkingMemory<br/>recent context]
        EM[EpisodicMemory<br/>compressed history]
        CB[ContextBuilder<br/>token budgeting]
        MM --> WM
        MM --> EM
        AGT --> CB
        CB --> MM
    end

    subgraph "Persistence"
        MS[MessageStore<br/>in-memory projection]
        SW[SessionWriter<br/>async JSONL]
        JSONL[(session.jsonl<br/>ledger)]
        MS --> SW
        SW --> JSONL
    end

    subgraph "Observability"
        LOG[structlog<br/>JSONL + SQLite]
        TL[TranscriptLogger]
        ES[ErrorStore<br/>metrics.db]
    end

    STDIO <--> AGT
    AGT --> TE
    AGT --> LLM
    AGT --> MM
    MM --> MS
```

---

## 2. Layer-by-Layer Architecture Trace

### 2.1 React Webview (claraity-vscode/webview-ui/)

**Entry**: `main.tsx` -> `App.tsx` -> central `useReducer(appReducer, initialState)`

**State Machine**: `state/reducer.ts` (1,215 lines) — single source of truth for all UI state.

```
AppState {
  // Connection
  connected, sessionId, modelName, permissionMode, workingDirectory
  // Chat
  messages[], isStreaming, markdownBuffer
  // Timeline (flat ordered array — core rendering abstraction)
  timeline: TimelineEntry[]  // user_message | assistant_text | tool | thinking | code | subagent | error
  // Tool Cards
  toolCards: Record<callId, ToolStateData>
  toolOrder: string[]  // insertion order
  toolCardOwners: Record<callId, subagentId>  // subagent ownership
  // Interactive Widgets
  pendingApproval, pausePrompt, clarifyRequest, planApproval
  // Subagents
  subagents: Record<id, SubagentInfo>
  promotedApprovals: Record<callId, ToolStateData>  // elevated to conversation level
  // Context
  contextUsed, contextLimit, sessionTotalTokens, sessionTurnCount
  // Panels
  activePanel: "chat" | "config" | "jira" | "sessions"
}
```

**Timeline Pattern**: Text accumulates in `markdownBuffer`. Before any non-text entry (tool card, thinking block, code block, subagent), `commitMarkdownBuffer()` flushes accumulated text into a `assistant_text` timeline entry. This maintains correct interleaving of prose and structured content.

**Silent Tools**: Internal tools (`task_*`, `plan`, `director_*`) are hidden from timeline (line 26-36).

**Components** (22 files):

| Component | Lines | Purpose |
|-----------|-------|---------|
| `ChatHistory` | 329 | Timeline renderer with auto-scroll gate (<40px from bottom) |
| `InputBox` | 293 | Textarea + @mention + paste images + file attachments |
| `ToolCard` | 100+ | Tool execution card with approval buttons, auto-diff-open |
| `SubagentCard` | 98 | Nested tool cards with live status ticker |
| `PauseWidget` | 80+ | Pause prompt with stats + continue/stop |
| `ClarifyWidget` | 80+ | Dynamic questions (radio/checkbox/text) |
| `PlanWidget` | 100+ | Plan approval with markdown preview |
| `ConfigPanel` | 100+ | Full LLM config (backend, model, params, subagent overrides) |
| `StreamingStatus` | 80+ | Real-time status line with elapsed timer |

**Message Passing**: `useVSCode` hook wraps `acquireVsCodeApi()`. All communication via `postMessage()` / `window.addEventListener("message")`. 40+ bidirectional message types defined in `types.ts`.

---

### 2.2 Extension Host (claraity-vscode/src/)

**Entry**: `extension.ts:activate()` (line 24, 501 lines total)

**Activation sequence** (stdio mode):
```
activate()
  -> resolveLaunchConfig()     // python-env.ts: detect dev/installed/bundled
  -> new StdioConnection()     // stdio-connection.ts: subprocess + TCP
  -> new ClarAItySidebarProvider()  // sidebar-provider.ts: webview provider
  -> wireConnection()          // extension.ts:102: attach event handlers
  -> stdioConn.connect()       // spawn process, create TCP listener
```

**Key Files**:

| File | Lines | Purpose |
|------|-------|---------|
| `extension.ts` | 501 | Activation, commands (14), lifecycle, wireConnection() |
| `sidebar-provider.ts` | 1900+ | WebviewViewProvider, message routing, diff editor, terminal queue |
| `stdio-connection.ts` | 292 | Spawn Python process, stdin write, TCP read |
| `jsonrpc.ts` | 48 | JSON-RPC 2.0 envelope (stdio only) |
| `types.ts` | 380 | All wire protocol type definitions |
| `server-manager.ts` | 219 | Python server spawn + health poll (WebSocket mode) |
| `python-env.ts` | 200+ | Python/package detection + auto-upgrade |
| `code-lens-provider.ts` | 100 | Inline Accept/Reject/View Diff at top of modified files |
| `file-decoration-provider.ts` | 62 | "AI" badge on agent-modified files |
| `undo-manager.ts` | 156 | File snapshot checkpoints (max 10), per-turn undo |
| `workspace-detector.ts` | 200+ | Auto-detect language, framework, test runner |

**wireConnection()** (line 102-187) — the central nervous system:
```
conn.onMessage(msg):
  stream_start     -> undoManager.beginCheckpoint()
  tool_state_updated:
    write_file/edit_file:
      awaiting_approval -> codeLens.addPendingChange() + undoManager.snapshotFile()
      running           -> undoManager.snapshotFile()  (auto-approve path)
      success           -> fileDecorations.markModified() + codeLens.remove()
      rejected/error    -> codeLens.remove()
    run_command + running -> echo to terminal
  stream_end       -> undoManager.commitCheckpoint() -> postToWebview(undoAvailable)
  session_info     -> clear all state (decorations, codeLens, undo)
```

**Diff Editor** (sidebar-provider.ts:592-706): Uses virtual document content provider (`claraity-diff:` URI scheme). No temp files — content stored in memory, freed on approval/rejection.

**Terminal Queue** (sidebar-provider.ts:60-235): Sequential command execution in persistent "[ClarAIty] Commands" terminal. Wraps commands with exit code detection, sends results back to agent.

**Secret Management**: API keys stored in VS Code `SecretStorage` (never written to config files). Injected via environment variables when spawning Python process.

---

### 2.3 Stdio Transport

**Architecture**: stdin (commands TO agent) + TCP socket (events FROM agent).

**Why TCP instead of stdout?** Windows libuv bug: stdout pipe `data` events don't fire reliably in VS Code Extension Host. TCP sockets use a different libuv code path that works.

**StdioConnection.connect()** (stdio-connection.ts:113-223):
```
1. Create TCP server on random port (OS assigns)
2. Resolve agent binary: bundled exe -> python -m src.server
3. Spawn: args=[...resolved, '--stdio', '--data-port', port]
   stdio=['pipe', 'ignore', 'pipe']  (stdin, stdout=ignore, stderr=pipe)
   env={PYTHONUNBUFFERED=1, CLARAITY_API_KEY, TAVILY_API_KEY}
4. TCP server accepts connection from agent
5. On socket.data: buffer + split by \n + parse JSON-RPC + fire onMessage
6. On process.exit: fire onDisconnected
```

**JSON-RPC Envelope** (jsonrpc.ts, 48 lines):
```
Internal: { type: "chat_message", content: "..." }
   -> wrapNotification()
Wire:     { jsonrpc: "2.0", method: "chat_message", params: { content: "..." } }
   -> unwrapMessage()
Internal: { type: "chat_message", content: "..." }
```

---

### 2.4 Python Stdio Server (src/server/)

**Entry**: `__main__.py` -> `run_stdio_server()` in `stdio_server.py` (1081 lines)

**StdioProtocol** extends `UIProtocol` (from `src/core/protocol.py`).

**Concurrency model**:
```
asyncio Event Loop (main thread)
  |-- receive_loop()          reads from _stdin_queue, dispatches handlers
  |-- main loop               waits on _chat_queue, calls agent.stream_response()
  |-- send_event()            writes to TCP with _send_lock

Background Thread (_stdin_reader_thread)
  |-- sys.stdin.buffer        blocking read
  |-- call_soon_threadsafe()  posts to _stdin_queue
```

**Message dispatch** (receive_loop, lines 256-361):

| Message Type | Handler | Destination |
|-------------|---------|-------------|
| `chat_message` | -> `_chat_queue` | Main loop -> agent.stream_response() |
| `get_config` / `save_config` / `list_models` | -> config_handler.py | Direct response via TCP |
| `set_mode` / `set_auto_approve` | -> agent methods | Direct response |
| `new_session` / `list_sessions` / `resume_session` | -> session handlers | State reset + history replay |
| `get_jira_profiles` / `save_jira_config` / etc. | -> Jira handlers | Direct response |
| Other (approval, interrupt, pause, clarify, plan) | -> `deserialize_action()` -> `submit_action()` | UIProtocol future resolution |

**Streaming response flow** (lines 1043-1070):
```python
async for event in agent.stream_response(user_input=content, ui=protocol, attachments=...):
    await protocol.send_event(event)  # serialize_event() -> wrap_notification() -> TCP
```

**Hot-swap LLM config** (lines 382-405): After `save_config`, if successful, calls `agent.reconfigure_llm(cfg, api_key)` to switch model/backend without restart.

**Serialization** (serializers.py, 320 lines): Pure functions converting UIEvents and StoreNotifications to JSON. Maps class names to wire types (e.g., `StreamStart` -> `"stream_start"`, `TextDelta` -> `"text_delta"`). Handles tool state, messages, interactive events (clarify, plan approval), and subagent lifecycle.

---

### 2.5 Agent Core (src/core/)

**CodingAgent** (`agent.py`, 3,078 lines) — the orchestrator.

**stream_response()** (line 1170) — the main loop:

```
User Input
  -> MemoryManager.add_user_message()
  -> ContextBuilder.build_context()  [token budgeting]

  while True:  # Tool execution loop
    -> call_llm() [streaming]
       -> yield StreamStart, TextDelta, ThinkingDelta, CodeBlockDelta, StreamEnd
       -> accumulate tool_calls from response

    if no tool_calls: break  # Pure text response

    for each tool_call:
      Phase A: GATING
        -> ToolGatingService.evaluate(tool_name, tool_args)
           Layer 1: Repeat detection (SHA256 signature)
           Layer 2: Plan mode gate (read-only enforcement)
           Layer 3: Director gate (phase restriction)
           Layer 4: Approval check (human-in-the-loop)

        -> If BLOCKED_REPEAT: skip, inject constraint message
        -> If DENY: skip, inject gate_response for LLM
        -> If NEEDS_APPROVAL: wait_for_approval() via UIProtocol

      Phase B: EXECUTION
        B1 (serial): Special tools (clarify, plan_approval) — pause for UI
        B2 (parallel): Normal tools — asyncio.gather() for independence

      Phase C: MERGE
        -> build_assistant_context_message() [tool_calls + content]
        -> fill_skipped_tool_results() [for gated/cancelled tools]
        -> MemoryManager.add_assistant_message()
        -> update_tool_state() via MessageStore [emits StoreNotification]

    Budget checks:
      if tool_call_count >= 200: pause
      if iteration >= 50: force stop
      if error_budget exceeded: pause
      if wall_time exceeded: pause
```

**Supporting modules**:

| Module | Lines | Purpose |
|--------|-------|---------|
| `tool_gating.py` | 350+ | 4-layer permission checks: repeat -> plan -> director -> approval |
| `special_tool_handlers.py` | 417 | Async handlers that pause for UI interaction |
| `stream_phases.py` | 174 | Pure functions for context assembly (no I/O) |
| `tool_loop_state.py` | 87 | Dataclass: MAX_TOOL_CALLS=200, MAX_ITERATIONS=50, budgets |
| `error_recovery.py` | 374 | SHA256 repeat detection, per-error-type budgets, approach history |
| `tool_metadata.py` | 94 | Shared metadata builder (agent + subagent parity) |
| `context_builder.py` | 469 | Token-budgeted context assembly with pressure levels |
| `protocol.py` | 300+ | UIProtocol: bidirectional agent<->UI communication |
| `events.py` | 300+ | UIEvent types: StreamStart, TextDelta, ToolCallStart, etc. |
| `permission_mode.py` | 61 | NORMAL / AUTO / PLAN modes |
| `plan_mode.py` | 400+ | Plan-then-execute workflow with SHA256 plan hash |

**UIProtocol** — the bidirectional contract:
```
Agent -> UI:  yield UIEvent (StreamStart, TextDelta, ToolCallStart, ErrorEvent, etc.)
UI -> Agent:  submit_action(UserAction)
              - ApprovalResult(call_id, approved, auto_approve_future, feedback)
              - InterruptSignal()
              - PauseResult(continue_work, feedback)
              - ClarifyResult(call_id, submitted, responses)
              - PlanApprovalResult(plan_hash, approved, feedback)
```

**Error Recovery** strategy:
- Same exact call signature (SHA256): blocked immediately (1 failure = no retry)
- Same tool + same error type: max 2-4 failures per request
- Total tool failures: max 10 per request
- Approach history maintained for LLM context (last 10 attempts)

---

### 2.6 Tool System (src/tools/)

**ToolExecutor** manages registry of 25+ tools with timeout configuration:

```python
DEFAULT_TIMEOUT = 120s
OVERRIDES = {
    "run_command": 600s,
    "delegate_to_subagent": None,  # internal pause handles it
    "get_file_outline": 90s,
    "web_search": 45s,
    "web_fetch": 60s,
}
```

**File Operations** (`file_operations.py`, 400+ lines):
- `ReadFileTool`: Streaming reads, line ranges, 2000-char line truncation, max 1000 lines default
- `WriteFileTool`: Create only, parent dir creation
- `EditFileTool`: Exact text find/replace, whitespace-sensitive
- `AppendToFileTool`: Append or create, newline handling
- Security: `validate_path_security()`, workspace boundary enforcement

**Delegation** (`delegation.py`, 400+ lines):
- Subprocess-based subagent execution with JSON-line IPC
- `MAX_DELEGATION_DEPTH = 2` (prevents infinite recursion)
- Events: registered -> notification (tool state, messages) -> done
- SubagentBridge relays events to VS Code via protocol

**Subagent System** (src/subagents/):
- `SubAgent` (1,174 lines): Independent context, own MessageStore, configurable LLM
- `Runner` (393 lines): Subprocess entry point, bootstraps from stdin JSON
- `Manager` (495 lines): Discovery from `.clarity/subagents/`, config loading
- Tool subset: file ops, search, LSP, commands — no task tools, plan mode, nested delegation

---

### 2.7 LLM Backend (src/llm/)

**Abstract interface** (`base.py`, 372 lines):

```python
class LLMBackend(ABC):
    async def astream(messages, tools) -> AsyncIterator[StreamChunk]
    def generate_with_tools(messages, tools) -> LLMResponse
    def count_tokens(text) -> int
    def is_available() -> bool
    def list_models() -> list[str]
```

**Key design**: `ProviderDelta` is the **canonical streaming contract**. All backends must emit `ProviderDelta` objects — providers MUST NOT parse markdown/code fences. The streaming pipeline downstream handles that.

**Implementations**:

| Backend | Lines | Features |
|---------|-------|----------|
| `OpenAIBackend` | 1600+ | OpenAI/Azure/Groq/DashScope/Together.ai, ThinkTagParser for `<think>` blocks |
| `AnthropicBackend` | 1400+ | Native Claude API, extended thinking with signatures, prompt caching |
| `OllamaBackend` | 193 | Local inference, model pull, approximate token counting |

**FailureHandler** (813 lines):
- Exponential backoff: standard (2^n, cap 15s), rate limit (10s base, cap 30s)
- Full jitter prevents thundering herd
- Error classification: retryable (timeout, rate limit, 503) vs fatal (invalid key, context exceeded)
- User feedback: countdown display for delays >= 10s

**CredentialStore** (213 lines):
- Priority: keyring (OS credential store) -> config.yaml -> env var
- Never silently drops credentials
- VS Code extension injects via `CLARAITY_API_KEY` env var (highest priority)

---

### 2.8 Memory & Context (src/memory/, src/core/context_builder.py)

**MemoryManager** (1000+ lines) — **single writer** for all persistence:

```
Three Memory Layers:
  WorkingMemory  — Recent conversation (LIFO, bounded, compaction via summarization)
  EpisodicMemory — Compressed summaries of past episodes
  ObservationStore — External storage for large tool outputs (pointer-based masking)
```

**WorkingMemory compaction** (420 lines):
1. Keep system messages + last 2 messages always
2. Group tool calls with their results (prevent orphaning)
3. Evict oldest groups until under 90% budget
4. Generate summary of evicted messages
5. Store in `pending_continuation_summary` for next turn injection

**ContextBuilder** (469 lines) — token-budgeted context assembly:

```
Budget Allocation:
  System prompt:    15%
  File references:  auto
  Agent state:      auto (incomplete todos)
  Working memory:   ~70%
  Buffer:           15%

Pressure Levels:
  GREEN  (<60%)  — plenty of headroom
  YELLOW (60-80%) — warning in logs
  ORANGE (80-90%) — consider compaction
  RED    (>90%)  — critical, compaction triggered
```

---

### 2.9 Persistence (src/session/)

**MessageStore** (400+ lines) — in-memory **projection** (not ledger):

```
JSONL file = source of truth (ledger)
MessageStore = derived view with indexes:
  _messages:        uuid -> Message          (primary)
  _by_seq:          seq -> uuid              (ordering)
  _by_stream_id:    stream_id -> uuid        (assistant message collapse)
  _tool_results:    tool_call_id -> uuid     (tool linkage)
  _assistant_tools: assistant_uuid -> [ids]  (reverse index)
  _clarify_*:       call_id -> uuid          (interactive flow)
```

**v2.1 Innovation**: Assistant messages collapsed by `stream_id` — multiple streaming updates to same message resolve to latest version. Prevents duplicates.

**SessionWriter** (150+ lines): Async JSONL writer with drain-on-close (up to 5s wait for pending writes). Binds to MessageStore via reactive subscription.

**StoreEvents**: MESSAGE_ADDED, MESSAGE_UPDATED, MESSAGE_FINALIZED, TOOL_STATE_UPDATED, BULK_LOAD_COMPLETE

**Single Writer Rule**: Only MemoryManager writes to MessageStore. TUI/VS Code reads via StoreAdapter (read-only) or StoreNotification subscriptions.

---

### 2.10 Observability (src/observability/)

**Logging stack**:
```
structlog.get_logger()
  -> stdlib Logger
    -> QueueHandler (non-blocking, 10K queue)
      -> QueueListener
        |-> RotatingFileHandler (.clarity/logs/app.jsonl)
        |-> SQLiteLogHandler (.clarity/metrics.db)
```

**Context propagation**: `ContextVar` for run_id, session_id, stream_id, request_id, component, operation — async-safe across await boundaries.

**Redaction**: Automatic pattern-based redaction of API keys (sk-*, Bearer, AKIA), database URIs, generic tokens. REDACT_MAX_LENGTH=500 for long strings.

**Error taxonomy** (ErrorStore): PROVIDER_TIMEOUT, PROVIDER_ERROR, TOOL_TIMEOUT, TOOL_ERROR, UI_GUARD_SKIPPED, BUDGET_PAUSE, UNEXPECTED

**TranscriptLogger**: Separate JSONL for conversation replay/audit. Head/tail preservation for truncated content (max 20K chars).

---

## 3. Critical Data Flows

### 3.1 User Message -> Agent Response

```mermaid
sequenceDiagram
    participant WV as React Webview
    participant EH as Extension Host
    participant SP as StdioProtocol
    participant AG as CodingAgent
    participant LLM as LLM Backend
    participant MS as MessageStore

    WV->>EH: postMessage({type: "chatMessage", content, images})
    EH->>EH: sendChatWithAttachments() — prepend projectContext, read files, base64 images
    EH->>SP: stdin: {type: "chat_message", content, images} (JSON-RPC wrapped)
    SP->>SP: receive_loop() -> _chat_queue.put()
    SP->>AG: agent.stream_response(user_input, ui=protocol, attachments)
    AG->>MS: MemoryManager.add_user_message()
    AG->>AG: ContextBuilder.build_context() [token budgeting]
    AG->>LLM: astream(messages, tools)

    loop Streaming
        LLM-->>AG: ProviderDelta (content/tool_calls/thinking)
        AG-->>SP: yield UIEvent (TextDelta/ThinkingDelta/etc)
        SP-->>EH: TCP: serialize_event() -> wrap_notification()
        EH-->>WV: postMessage({type: "serverMessage", payload})
        WV-->>WV: dispatch(action) -> appReducer -> re-render
    end

    AG->>MS: MemoryManager.add_assistant_message()
    MS->>MS: SessionWriter -> JSONL append
```

### 3.2 Tool Approval Flow

```mermaid
sequenceDiagram
    participant WV as React Webview
    participant EH as Extension Host
    participant SP as StdioProtocol
    participant AG as CodingAgent

    AG->>AG: ToolGatingService.evaluate() -> NEEDS_APPROVAL
    AG->>SP: update_tool_state(status=awaiting_approval)
    SP-->>EH: TCP: tool_state_updated
    EH->>EH: codeLens.addPendingChange() + undoManager.snapshotFile()
    EH-->>WV: serverMessage -> ToolCard with approve/reject

    alt User clicks Approve
        WV->>EH: postMessage({type: "approvalResult", approved: true})
        EH->>SP: stdin: {type: "approval_result", approved: true}
        SP->>SP: deserialize_action() -> submit_action(ApprovalResult)
        SP->>AG: UIProtocol future resolves -> execute tool
    else User clicks View Diff
        WV->>EH: postMessage({type: "showDiff", callId, toolName, args})
        EH->>EH: openDiffEditor() -> vscode.diff with virtual documents
    end
```

### 3.3 Subagent Lifecycle

```mermaid
sequenceDiagram
    participant AG as Main Agent
    participant DT as DelegationTool
    participant RP as Runner Process
    participant SA as SubAgent
    participant BR as SubagentBridge
    participant EH as Extension Host

    AG->>DT: execute_async("code-reviewer", task)
    DT->>RP: spawn subprocess, stdin: SubprocessInput JSON
    RP->>SA: Create SubAgent (own LLM, MessageStore, ToolExecutor)
    RP->>DT: stdout: {event: "registered", subagent_id, name}
    DT->>BR: bridge.register(subagent_id, store, ...)
    BR-->>EH: TCP: {type: "subagent", event: "registered"}

    loop Subagent Execution
        SA->>SA: stream_response() -> tool calls -> results
        RP->>DT: stdout: {event: "notification", ...}
        DT->>BR: bridge.push_notification()
        BR-->>EH: TCP: tool_state_updated / message_added
    end

    RP->>DT: stdout: {event: "done", result: SubAgentResult}
    DT->>BR: bridge.unregister(subagent_id)
    BR-->>EH: TCP: {type: "subagent", event: "unregistered"}
    DT->>AG: return ToolResult
```

---

## 4. State Machines

### 4.1 Tool Execution State

```mermaid
stateDiagram-v2
    [*] --> pending: tool_call received
    pending --> awaiting_approval: needs_approval=true
    pending --> running: auto_approved or no approval needed
    awaiting_approval --> approved: user approves
    awaiting_approval --> rejected: user rejects
    approved --> running: begin execution
    running --> success: tool completes
    running --> error: tool fails
    running --> timeout: exceeded timeout_s
    running --> cancelled: user interrupts
    pending --> skipped: gated (repeat/plan/director)
    rejected --> [*]
    success --> [*]
    error --> [*]
    timeout --> [*]
    cancelled --> [*]
    skipped --> [*]
```

### 4.2 Agent Loop State

```mermaid
stateDiagram-v2
    [*] --> streaming: stream_response() called
    streaming --> tool_gating: tool_calls received
    tool_gating --> tool_execution: gate passed
    tool_gating --> constraint_injection: gate blocked (repeat)
    tool_gating --> approval_wait: needs_approval
    approval_wait --> tool_execution: approved
    approval_wait --> constraint_injection: rejected
    tool_execution --> streaming: more tool_calls possible
    tool_execution --> pause_check: budget check
    pause_check --> pause_prompt: budget exceeded
    pause_prompt --> streaming: user continues
    pause_prompt --> [*]: user stops
    streaming --> [*]: no tool_calls (pure text response)
    constraint_injection --> streaming: retry with constraint
```

---

## 5. Dead Code, Duplication & Architectural Issues

### 5.1 Dead Code

| Issue | File | Impact |
|-------|------|--------|
| Unused imports `StreamEnd, StreamStart` | `src/server/app.py:22-23` | LOW |
| `MockLanguageServer` class never instantiated | `src/code_intelligence/lsp_client_manager.py:957` | MEDIUM |
| `_run_vitest()` and `_run_cargo()` stubbed, not implemented | `src/testing/test_runner.py` | LOW |

### 5.2 Duplication

| Issue | Files | Impact | Fix |
|-------|-------|--------|-----|
| **Duplicate StreamingState classes** | `core/streaming/state.py:40` vs `ui/store_adapter.py:67` | **HIGH** — two independent state machines for one concept | Use core version as canonical, remove from store_adapter |
| Subagent name list hardcoded 3x | `ui/llm_config_screen.py:153`, `server/config_handler.py:14`, config_loader | MEDIUM | Extract to shared constant |
| Error response formatting repeated 10+ times | `server/ws_protocol.py` (throughout) | MEDIUM | Extract `send_error()` helper |
| Token counting re-implemented per backend | `ollama_backend.py`, `working_memory.py`, `context_builder.py` | MEDIUM | Shared TokenCounter utility |

### 5.3 God Classes

| Class | File | Lines | Responsibilities | Recommendation |
|-------|------|-------|-----------------|----------------|
| `WebSocketProtocol` | `ws_protocol.py` | 658 | Event serialization + action deserialization + chat + sessions + config + Jira + mode switching | Extract JiraHandler, ConfigHandler, SessionHandler |
| `StdioProtocol` | `stdio_server.py` | 925 | Same as WebSocket + TCP management | Same extraction pattern |
| `ClarAItySidebarProvider` | `sidebar-provider.ts` | 1900+ | Webview provider + message routing + diff editor + terminal + file picker | Extract DiffManager, TerminalQueue (already partial) |

### 5.4 Architectural Smells

| Smell | Location | Impact | Recommendation |
|-------|----------|--------|----------------|
| Circular import chain | `core.__init__ -> agent -> llm -> session -> events -> core.__init__` | LOW (mitigated with lazy `__getattr__`) | Move events.py outside core |
| UIProtocol has 17+ methods | `protocol.py` | MEDIUM — all implementations tightly coupled | Split into ApprovalHandler, PauseHandler, ActionQueue interfaces |
| No automatic compaction trigger | `working_memory.py` | MEDIUM — memory bloats if orchestrator forgets | Add token threshold check in add_message() |
| Inconsistent state patterns | Various dataclasses vs implicit state | LOW | Document standard pattern |

### 5.5 What I Would Do Differently as Lead Architect

1. **Protocol multiplexing**: Both StdioProtocol and WebSocketProtocol duplicate 80% of their message handling logic. I'd extract a `MessageRouter` class that both protocols delegate to, keeping protocol-specific code limited to transport mechanics (TCP vs WebSocket read/write).

2. **Command pattern for message dispatch**: The 175-line `receive_loop()` match statement should be a command registry. Each message type gets a registered handler class. This makes the system open for extension without modifying the core loop.

3. **Streaming pipeline as first-class abstraction**: The `StreamingState` duplication signals a missing abstraction. I'd create a unified `StreamingPipeline` that both server serialization and TUI rendering consume. One pipeline, multiple consumers.

4. **Tool system extensibility**: Tools are currently registered in a monolithic `_register_tools()` method. I'd use a plugin/registry pattern with auto-discovery (decorators or entry points), making it trivial to add tools without touching agent.py.

5. **Context builder as pipeline**: Context assembly is procedural. I'd model it as a pipeline of `ContextStage` objects (system prompt stage, file refs stage, memory stage, etc.) that can be composed, reordered, and individually tested.

6. **Separate wire protocol from domain events**: The current system mixes UIEvent types (domain) with their serialization (wire). I'd have clean domain events that are protocol-agnostic, with serializers being a separate concern that can be swapped (e.g., MessagePack for performance).

---

## 6. Key Invariants & Constraints

These rules MUST be maintained for system correctness:

1. **Single Writer**: Only `MemoryManager` writes to `MessageStore`. Violation causes data races.
2. **Tool result ordering**: Results must match tool_call order in the preceding assistant message.
3. **Orphan prevention**: Every `tool_call` must have a corresponding `tool_result`. `_fix_orphaned_tool_calls()` enforces this.
4. **stdin=subprocess.DEVNULL**: ALL subprocess.run() calls in stdio mode. Violation causes Windows deadlock.
5. **No emojis in Python**: Windows cp1252 encoding. Violation crashes the app.
6. **Agent/Subagent parity**: Both must use `build_tool_metadata()`. Divergence breaks VS Code rendering.
7. **Interrupt lifecycle**: `_interrupted` must be cleared after "Continue" on pause. Violation causes infinite pause loops.
8. **stream_id collapse**: Assistant messages with same stream_id are merged (latest wins). Multiple consumers depend on this.
9. **JSON-RPC envelope**: Only stdio transport uses JSON-RPC wrapping. WebSocket sends raw typed messages.
10. **Secret isolation**: API keys NEVER in config files. Keyring or env vars only. VS Code SecretStorage on the extension side.

---

## 7. File Manifest

### VS Code Extension (claraity-vscode/)
```
src/
  extension.ts              501 lines  Entry point, commands, lifecycle
  sidebar-provider.ts      1900 lines  WebviewViewProvider, routing, diff
  stdio-connection.ts       292 lines  Subprocess + TCP transport
  jsonrpc.ts                 48 lines  JSON-RPC 2.0 envelope
  types.ts                  380 lines  All wire protocol types
  agent-connection.ts       168 lines  WebSocket client (alt transport)
  server-manager.ts         219 lines  Server health polling
  python-env.ts             200 lines  Python/package detection
  code-lens-provider.ts     100 lines  Accept/Reject/Diff CodeLens
  file-decoration-provider.ts 62 lines  "AI" file badges
  undo-manager.ts           156 lines  File snapshot checkpoints
  workspace-detector.ts     200 lines  Project context detection

webview-ui/src/
  App.tsx                   250 lines  Root component
  state/reducer.ts         1215 lines  Central state machine
  hooks/useVSCode.ts         68 lines  postMessage bridge
  components/ (22 files)   ~2500 lines  All React components
  utils/ (3 files)          ~100 lines  Markdown, tools, text helpers
  types.ts                  187 lines  Webview message types
  index.css                 650 lines  Design system (VS Code tokens)
```

### Python Server (src/server/)
```
__main__.py                 155 lines  Entry point, mode dispatch
stdio_server.py            1081 lines  StdioProtocol + main loop
jsonrpc.py                   43 lines  JSON-RPC 2.0 utilities
serializers.py              320 lines  UIEvent/Store -> JSON
config_handler.py           253 lines  Config CRUD
subagent_bridge.py          103 lines  Subagent event relay
app.py                      666 lines  HTTP+WS server (reference)
ws_protocol.py              650 lines  WebSocket protocol (reference)
```

### Agent Core (src/core/)
```
agent.py                   3078 lines  CodingAgent orchestrator
tool_gating.py              350 lines  4-layer permission checks
special_tool_handlers.py    417 lines  UI-pausing handlers
stream_phases.py            174 lines  Context assembly helpers
tool_loop_state.py           87 lines  Loop state dataclass
error_recovery.py           374 lines  Repeat prevention + budgets
tool_metadata.py             94 lines  Shared metadata builder
context_builder.py          469 lines  Token-budgeted context
protocol.py                 300 lines  UIProtocol (agent<->UI)
events.py                   300 lines  UIEvent types
permission_mode.py           61 lines  NORMAL/AUTO/PLAN
plan_mode.py                400 lines  Plan-then-execute workflow
```

### LLM Backend (src/llm/)
```
base.py                     372 lines  Abstract base + ProviderDelta
openai_backend.py          1600 lines  OpenAI-compatible APIs
anthropic_backend.py       1400 lines  Native Claude API
ollama_backend.py           193 lines  Local Ollama inference
failure_handler.py          813 lines  Retry + exponential backoff
credential_store.py         213 lines  Keyring + env fallback
config_loader.py            476 lines  Layered configuration
cache_tracker.py            109 lines  Prompt cache metrics
```

### Memory & Persistence (src/memory/, src/session/)
```
memory_manager.py          1000 lines  Single writer orchestrator
working_memory.py           420 lines  Recent context + compaction
episodic_memory.py          100 lines  Compressed history
observation_store.py        150 lines  External tool output storage
memory_store.py             400 lines  In-memory projection + indexes
session_manager.py          150 lines  Session lifecycle
scanner.py                  100 lines  Session discovery
writer.py                   150 lines  Async JSONL with drain-on-close
message.py                  200 lines  Unified message model (v2.1)
```

### Tools & Subagents (src/tools/, src/subagents/)
```
file_operations.py          400 lines  read/write/edit/append/list
delegation.py               400 lines  Subprocess IPC
knowledge_tools.py           ~  lines  KB manifest tools
tool_schemas.py              ~  lines  Tool definitions
subagent.py                1174 lines  Lightweight agent
runner.py                   393 lines  Subprocess entry point
manager.py                  495 lines  Discovery + lifecycle
```

---

## 8. How to Build a Coding Agent Like This

### Architecture Principles (derived from ClarAIty)

1. **Streaming-first**: Never buffer full responses. Stream from LLM through every layer to UI.
2. **Protocol-agnostic core**: Agent yields events, doesn't know about transport. UI submits actions through an abstract protocol.
3. **Single writer persistence**: One component owns writes. Everyone else reads via subscriptions.
4. **Layered gating**: Permission checks as composable layers, not monolithic if/else.
5. **Budget-aware context**: Token counting at every stage with pressure thresholds.
6. **Subagent isolation**: Independent context windows prevent cross-contamination.
7. **Error recovery with memory**: Track failed attempts to prevent infinite retry loops.
8. **Human-in-the-loop by default**: Approval for destructive operations, with opt-in auto-approve.

### Implementation Order (recommended)

```
Phase 1: Core Loop
  1. LLM backend abstraction (provider-agnostic streaming)
  2. Tool executor (registry, timeout, parallel execution)
  3. Agent loop (stream -> tool calls -> execute -> repeat)
  4. Simple persistence (JSONL append)

Phase 2: Intelligence
  5. Context builder (token budgeting, pressure levels)
  6. Memory layers (working + episodic + compaction)
  7. Error recovery (repeat detection, retry budgets)
  8. System prompts (identity, verification, anti-hallucination)

Phase 3: Safety
  9. Permission system (gating layers)
  10. Approval workflow (UI protocol, async futures)
  11. Plan mode (read-only enforcement, plan hash verification)

Phase 4: UI Integration
  12. Event serialization (domain events -> wire format)
  13. Transport layer (stdio/WebSocket/etc)
  14. VS Code extension (webview provider, diff editor, undo)
  15. React webview (state machine, timeline rendering)

Phase 5: Scale
  16. Subagent system (subprocess isolation, IPC)
  17. MCP integration (external tools)
  18. Observability (structured logging, error store, metrics)
```
