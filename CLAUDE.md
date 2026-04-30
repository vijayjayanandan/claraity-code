# ClarAIty AI Coding Agent - Claude Instructions

## QUICK START

```bash
# Run TUI (only interface)
python -m src.cli

# Run tests
pytest tests/

# Query logs
python -m src.observability.log_query --tail 50
```

---

## CLARAITY KNOWLEDGE DB

Before reading files to understand the codebase, query the knowledge DB first. It contains a pre-scanned understanding of the architecture, components, files, decisions, and invariants.

### Knowledge Queries
```bash
# Architecture overview (compact, use at session start)
python -m src.claraity.claraity_db brief

# Module detail (components + files)
python -m src.claraity.claraity_db module mod-core

# File detail (role, component, decisions that apply)
python -m src.claraity.claraity_db file src/core/agent.py

# Search knowledge base
python -m src.claraity.claraity_db search "memory"

# Impact analysis (what breaks if I change this)
python -m src.claraity.claraity_db impact comp-message-store
```

### Task Management (Beads)
```bash
# See what's ready to work on
python -m src.claraity.claraity_beads ready

# Full task briefing with blocked/ready/closed
python -m src.claraity.claraity_beads brief

# Show task detail
python -m src.claraity.claraity_beads show bd-xxxx

# Create a task
python -m src.claraity.claraity_beads create "Task title" --priority 2 --desc "Description" --tags tag1,tag2

# Start working on a task
python -m src.claraity.claraity_beads start bd-xxxx

# Close a task
python -m src.claraity.claraity_beads close bd-xxxx --summary "What was done"

# Add blocking dependency (A must complete before B)
python -m src.claraity.claraity_beads block bd-aaaa bd-bbbb

# Add a note to a task
python -m src.claraity.claraity_beads note bd-xxxx "Progress update"
```

### Module IDs
`mod-core`, `mod-memory`, `mod-session`, `mod-ui`, `mod-tools`, `mod-llm`, `mod-server`, `mod-observability`, `mod-prompts`, `mod-subagents`, `mod-code-intel`, `mod-integrations`, `mod-platform`, `mod-hooks`

---

## CODEBASE MAP

```
src/
├── cli.py                      # Entry point: TUI launcher (~335 lines)
├── core/
│   ├── agent.py                # CodingAgent facade (~2,617 lines) - see cheat sheet below
│   ├── tool_loop_state.py      # ToolLoopState dataclass (86 lines) - loop iteration state
│   ├── tool_gating.py          # ToolGatingService (289 lines) - tool gating checks
│   ├── special_tool_handlers.py # SpecialToolHandlers - clarify/plan approval
│   ├── stream_phases.py        # Helper functions (154 lines) - context/constraint/results builders
│   └── error_recovery.py       # Error recovery logic
├── ui/app.py                   # AgentApp (3300 lines) - see cheat sheet below
├── memory/
│   ├── memory_manager.py       # MemoryManager - SINGLE WRITER for persistence
│   └── working_memory.py       # WorkingMemory - conversation context
├── session/store/
│   └── memory_store.py         # MessageStore - in-memory + JSONL append
├── llm/
│   ├── base.py                 # LLMBackend abstract base
│   └── openai_backend.py       # OpenAI/compatible API implementation
├── tools/
│   ├── file_operations.py      # read_file, write_file, edit_file, etc.
│   ├── document_extractor.py   # Subprocess PDF/DOCX text extractor (crash isolation)
│   └── tool_schemas.py         # Tool definitions for LLM
├── observability/
│   ├── logging_config.py       # Logging setup (all logs to JSONL, no console)
│   └── transcript_logger.py    # Session transcript writer
└── prompts/system_prompts.py   # System prompt templates
```

**See:** `docs/AGENT_DECOMPOSITION.md` for the full refactoring report.

---

## BIG FILE CHEAT SHEETS

### agent.py (~2,617 lines) - CodingAgent

**Control Flow:**
```
User Input → stream_response() [async only]
    → ToolGatingService.evaluate() — gating (repeat/plan/approval)
    → SpecialToolHandlers — clarify, plan approval
    → execute_tool() for normal tools
    → stream_phases helpers — context/constraint/results builders
    → loop until no more tool_calls
    → yield StreamEnd
```

**Key Methods (by line number):**
| Line | Method | Purpose |
|------|--------|---------|
| 178 | `__init__` | Constructor - sets up tools, memory, LLM, gating, special handlers |
| 569 | `_register_tools` | Register tool definitions for LLM |
| 699 | `_fix_orphaned_tool_calls` | Removes tool_calls without matching results |
| 1007 | `stream_response` | ASYNC streaming generator - sole entry point |
| 2157 | `execute_tool` | Single tool execution |
| 2184 | `call_llm` | Raw LLM API call |
| 2307 | `resume_session_from_jsonl` | Session resume logic |
| 2594 | `shutdown` | Cleanup on exit |

**Extracted Modules (see `docs/AGENT_DECOMPOSITION.md` for details):**
| Module | Purpose |
|--------|---------|
| `tool_gating.py` | 3-check gating (repeat, plan mode, approval) |
| `special_tool_handlers.py` | Async handlers that pause for UI (clarify, plan approval) |
| `stream_phases.py` | Helpers: context message, constraint injection, skipped results, pause stats |
| `tool_loop_state.py` | Dataclass replacing 12+ local variables in stream_response |

**Common Modifications:**
- Tool gating/approval: `src/core/tool_gating.py` (ToolGatingService)
- Adding new tools: `_register_tools` (line 569)
- Context building: Look for `messages` list construction before `call_llm`
- Streaming behavior: `stream_response` (line 1007)
- Special tool handling: `src/core/special_tool_handlers.py`

---

### app.py (3300 lines) - AgentApp (Textual TUI)

**Control Flow:**
```
App starts → compose() builds widgets → on_mount() initializes
User types → InputSubmittedMessage → _stream_response()
    → Creates AssistantMessage widget
    → _process_stream() handles UIEvents
    → _handle_event() dispatches to specific handlers
Store updates → _handle_store_notification() → UI refresh
```

**Key Methods (by line number):**
| Line | Method | Purpose |
|------|--------|---------|
| 629 | `__init__` | Constructor - requires agent or stream_handler |
| 775 | `compose` | Widget layout - header, conversation, input |
| 788 | `on_mount` | Startup - focus input, load session |
| 846 | `on_input_submitted_message` | User pressed Enter |
| 1107 | `_stream_response` | Main response handler |
| 1246 | `_process_stream` | Iterates UIEvents from agent |
| 1331 | `_handle_event` | UIEvent dispatch (text, tool, error, etc.) |
| 1657 | `_finalize_current_message` | Mark message complete |
| 2201 | `bind_store` | Connect to MessageStore for persistence |
| 2305 | `_handle_store_notification` | React to store changes |
| 2341 | `_on_store_message_added` | New message from store |
| 3087 | `replay_session` | Load and display saved session |

**Common Modifications:**
- New widget types: `compose()` (line 775) and `_handle_event()` (line 1331)
- Message rendering: `_on_store_message_added` (line 2341)
- Keyboard shortcuts: Look for `action_*` methods
- Store integration: `_handle_store_notification` (line 2305)

---

## KEY ABSTRACTIONS

| Class | File | Purpose |
|-------|------|---------|
| `CodingAgent` | `src/core/agent.py` | Main agent facade - delegates to gating, handlers, phases |
| `ToolGatingService` | `src/core/tool_gating.py` | Tool gating: repeat/plan/approval checks |
| `SpecialToolHandlers` | `src/core/special_tool_handlers.py` | Async UI-pausing handlers: clarify, plan approval |
| `ToolLoopState` | `src/core/tool_loop_state.py` | Dataclass carrying loop state through iterations |
| `MemoryManager` | `src/memory/memory_manager.py` | Orchestrates persistence - ONLY component that writes to store |
| `MessageStore` | `src/session/store/memory_store.py` | In-memory message storage + JSONL file append |
| `StoreAdapter` | `src/ui/store_adapter.py` | READ-ONLY - bridges MessageStore to TUI (never writes) |
| `AgentApp` | `src/ui/app.py` | Textual-based TUI application |

**Data flow:**
```
User → CodingAgent → MemoryManager → MessageStore → .claraity/sessions/*.jsonl
                                           ↓
                                    StoreAdapter (read) → TUI
```

---

## HARD CONSTRAINTS (must follow)

### 1. Logging - Use Our Framework
```python
# WRONG - causes duplicate handlers, breaks TUI
import logging
logger = logging.getLogger(__name__)

# RIGHT
from src.observability import get_logger
logger = get_logger(__name__)
```
All logs go to JSONL file only. No console output (breaks TUI).

### 2. No Emojis in Python Code
Windows console uses cp1252 encoding. Emojis crash the app.
```python
# WRONG
print("✅ Success!")
logger.info("🚀 Starting...")

# RIGHT
print("[OK] Success!")
logger.info("[START] Starting...")
```
Exception: Emojis OK in markdown docs.

### 3. StoreAdapter is READ-ONLY
Never add write methods to StoreAdapter. MemoryManager is the single writer.

---

## KNOWN GOTCHAS

1. **Logging race condition (fixed):** Module-level `get_logger()` calls auto-configure logging during import. Solution: all modes log to file only, no console handler.

2. **Tool result ordering:** Tool results must appear in same order as tool calls in the message that requested them, or LLM gets confused.

3. **Orphan tool results:** If a tool_result has no matching tool_call in context, the LLM API rejects it. Agent has orphan detection in `_check_for_orphaned_tool_results()`.

4. **Async in TUI:** The TUI runs async. Never use blocking calls (input(), time.sleep()) in code that runs during TUI mode.

5. **Stream finalization:** Assistant messages start as streaming placeholders, then get finalized with `finalize_message()`. Don't assume content is complete until finalized.

6. **Agent/Subagent parity:** Both `agent.py` and `subagent.py` emit tool state updates via `update_tool_state()`. The VS Code serializer (`serializers.py`) and webview expect identical metadata keys from both. Use `build_tool_metadata()` from `src/core/tool_metadata.py` in both paths. If you add new metadata keys, update the shared builder.

7. **Protocol interrupt lifecycle:** `_interrupted` must be cleared after "Continue" on a pause prompt (via `clear_interrupt()`). See STATE LIFECYCLE comment in `protocol.py`. Forgetting this causes the pause prompt to re-appear on every subsequent iteration.

8. **subprocess.run stdin inheritance (stdio mode):** Every `subprocess.run()` call MUST include `stdin=subprocess.DEVNULL`. In stdio mode, a background thread reads stdin for JSON commands. Without DEVNULL, child processes inherit the stdin handle, causing a deadlock on Windows — the subprocess hangs, freezing the event loop until data arrives on stdin. This doesn't affect TUI or WebSocket modes (no stdin reader thread).

9. **Document parsing runs in subprocess:** `read_file` for PDF/DOCX delegates to `document_extractor.py` via `subprocess.run()`. This isolates C-library crashes (PyMuPDF/MuPDF) from the agent process. Security guards (file size 10MB, zip bomb detection, 10K line cap, 30s timeout) are enforced. The in-process extraction methods were removed — all extraction logic lives in `document_extractor.py` only.

---

## AGENT/SUBAGENT/VSCODE PARITY CHECKLIST

When modifying tool state emission, store events, or protocol signals, verify all three consumers stay in sync:

| What changed | Check agent.py | Check subagent.py | Check sidebar-provider.ts |
|---|---|---|---|
| New metadata key in `update_tool_state()` | Update `build_tool_metadata()` | Uses same builder | Update `updateToolCard()` |
| New store event type (e.g. MESSAGE_FINALIZED) | Emits via MemoryManager | Emits via SubAgent's MessageStore | Handle in `case 'store':` |
| New interactive event (clarify, plan, etc.) | Emits via protocol | May need IPC relay in delegation.py | Handle in `case 'interactive':` |
| Protocol state change (_interrupted, etc.) | Check `stream_response()` | Check `delegation.execute_async()` | Check webview button handlers |

**Key files in the data path:** `subagent.py` -> `runner.py` (IPC) -> `delegation.py` -> `subagent_bridge.py` -> `serializers.py` -> WebSocket -> `sidebar-provider.ts`

---

## SESSION PERSISTENCE

- **Location:** `.claraity/sessions/<session_id>.jsonl`
- **Format:** One JSON object per line: `{"role": "...", "meta": {...}, "content": "..."}`
- **Resume:** JSONL replayed into MessageStore on session load

---

## LOGS & DIAGNOSTICS

- **Application logs:** `.claraity/logs/app.jsonl` (structured JSONL, all log levels)
- **Metrics DB:** `.claraity/metrics.db` (SQLite, performance metrics and error tracking)
- **Query logs:** `python -m src.observability.log_query --tail 50`
- **Subagent transcripts:** `.claraity/sessions/subagents/<name>-<session_id>.jsonl`

---

## TESTING

```bash
# Unit tests
pytest tests/

# Specific test file
pytest tests/tools/test_file_operations.py -v

# Live agent test (requires API key)
python test_agent_interface_live.py
```

---

## COMPLETED REFACTORS

### 1. agent.py Decomposition
**See:** `docs/AGENT_DECOMPOSITION.md` for full report.
**Results:** 4 modules extracted (946 lines). 44 new tests. 0 regressions.

### 2. CLI Mode Removal (async-only consolidation)
Removed all sync execution paths (`chat()`, `_execute_with_tools()`, `execute_task()`, `_execute_direct()`, CLI entry points). Single async path via `stream_response()`. ~2,670 lines removed across agent.py, cli.py, cli_ui.py (deleted), delegation.py, clarify_tool.py, special_tool_handlers.py.

**Remaining opportunities:**
1. Rewrite `stream_response()` as ~180-line orchestrator (deferred - high risk due to async generator yields)
2. Extract segment rendering in app.py (4 copies -> 1 helper)
3. Split `_handle_event()` in app.py (325 lines -> dispatcher + 14 handlers)

---

## ONGOING DOCUMENTATION TASKS

### System Reminders Documentation
**File**: `SYSTEM_REMINDERS.md`

Whenever you observe a new type of system reminder (XML tags like `<system-reminder>`) injected by Claude Code CLI into your context, document it in SYSTEM_REMINDERS.md:

1. Add the reminder type with full text example
2. Document when it's injected (trigger conditions)
3. Note any variables/substitutions
4. Explain its purpose
5. Add entry to Session Log with date

This helps us understand Claude Code's contextual guidance system so we can replicate similar patterns in our custom agent.

---

## WHEN TO USE CODE REVIEWER

Launch code-reviewer subagent for:
- Changes touching 3+ files
- Async/TUI coordination changes
- Agent control loop modifications
- Persistence layer changes

Quality gates: 4.5+ APPROVE | 3.5-4.4 REQUEST CHANGES | <3.5 REJECT

---

## JIRA & CONFLUENCE

**See:** `JIRA_CONFLUENCE.md` for complete guide on:
- Creating user stories with dev/test subtasks
- Uploading documentation to Confluence
- Linking Jira issues to Confluence pages
- Search, query, and workflow patterns

**Quick reference:**
- Cloud ID: `fcd96f11-1610-4860-b036-6fb42ce58d98`
- Confluence Space: ClarAIty Code (CC) - Space ID: `557060`
- Jira Project: ClarAIty Code (CC) - Project Key: `CC`
