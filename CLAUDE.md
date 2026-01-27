# AI Coding Agent - Claude Instructions

## QUICK START

```bash
# Run TUI mode (primary interface)
python -m src.cli --tui

# Run CLI mode (simple chat)
python -m src.cli

# Run tests
pytest tests/

# Query logs
python -m src.observability.log_query --tail 50
```

---

## CODEBASE MAP

```
src/
├── cli.py                  # Entry point: main() at line 1484
├── core/agent.py           # CodingAgent (4200 lines) - see cheat sheet below
├── ui/app.py               # AgentApp (3300 lines) - see cheat sheet below
├── memory/
│   ├── memory_manager.py   # MemoryManager - SINGLE WRITER for persistence
│   └── working_memory.py   # WorkingMemory - conversation context
├── session/store/
│   └── memory_store.py     # MessageStore - in-memory + JSONL append
├── llm/
│   ├── base.py             # LLMBackend abstract base
│   └── openai_backend.py   # OpenAI/compatible API implementation
├── tools/
│   ├── file_operations.py  # read_file, write_file, edit_file, etc.
│   └── tool_schemas.py     # Tool definitions for LLM
├── observability/
│   ├── logging_config.py   # Logging setup (all logs to JSONL, no console)
│   └── transcript_logger.py # Session transcript writer
└── prompts/system_prompts.py # System prompt templates
```

---

## BIG FILE CHEAT SHEETS

### agent.py (4200 lines) - CodingAgent

**Control Flow:**
```
User Input → chat() or chat_async()
    → _execute_with_tools() or _execute_with_tools_async()
        → call_llm() → LLM returns tool_calls
        → execute_tool() for each tool
        → loop until no more tool_calls
    → return final response
```

**Key Methods (by line number):**
| Line | Method | Purpose |
|------|--------|---------|
| 197 | `__init__` | Constructor - sets up tools, memory, LLM backend |
| 583 | `_execute_with_tools` | SYNC tool loop - most modifications happen here |
| 900 | `_execute_with_tools_async` | ASYNC tool loop - TUI uses this |
| 1108 | `_fix_orphaned_tool_calls` | Removes tool_calls without matching results |
| 1234 | `_prompt_tool_approval` | CLI approval prompt |
| 1718 | `execute_task` | High-level task execution with planning |
| 1868 | `chat` | SYNC chat interface - CLI uses this |
| 2063 | `stream_response` | Streaming generator for responses |
| 3344 | `chat_async` | ASYNC chat interface - TUI uses this |
| 3478 | `execute_tool` | Single tool execution |
| 3505 | `call_llm` | Raw LLM API call |
| 3640 | `resume_session_from_jsonl` | Session resume logic |

**Common Modifications:**
- Tool approval logic: `_prompt_tool_approval` (line 1234)
- Adding new tools: `_register_tools` (line 502)
- Context building: Look for `messages` list construction before `call_llm`
- Streaming behavior: `stream_response` (line 2063)

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
| `CodingAgent` | `src/core/agent.py` | Main agent loop - processes user input, calls LLM, executes tools |
| `MemoryManager` | `src/memory/memory_manager.py` | Orchestrates persistence - ONLY component that writes to store |
| `MessageStore` | `src/session/store/memory_store.py` | In-memory message storage + JSONL file append |
| `StoreAdapter` | `src/ui/store_adapter.py` | READ-ONLY - bridges MessageStore to TUI (never writes) |
| `AgentApp` | `src/ui/app.py` | Textual-based TUI application |

**Data flow:**
```
User → CodingAgent → MemoryManager → MessageStore → .clarity/sessions/*.jsonl
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

---

## SESSION PERSISTENCE

- **Location:** `.clarity/sessions/<session_id>.jsonl`
- **Format:** One JSON object per line: `{"role": "...", "meta": {...}, "content": "..."}`
- **Resume:** JSONL replayed into MessageStore on session load

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

## PENDING REFACTOR

**See:** `docs/REFACTOR_PLAN.md` for detailed plan to reduce agent.py and app.py by ~1,000 lines.

**Top 3 priorities:**
1. Split `stream_response()` (1280 lines → ~300)
2. Extract segment rendering (4 copies → 1 helper)
3. Split `_handle_event()` (325 lines → dispatcher + 14 handlers)

---

## WHEN TO USE CODE REVIEWER

Launch code-reviewer subagent for:
- Changes touching 3+ files
- Async/TUI coordination changes
- Agent control loop modifications
- Persistence layer changes

Quality gates: 4.5+ APPROVE | 3.5-4.4 REQUEST CHANGES | <3.5 REJECT
