# ClarAIty Code - Agent Instructions

## SELF-REFERENTIAL CODEBASE

This repository (`ai-coding-agent`) is the source code of the agent itself (ClarAIty Code).
When working in this repo, I am reading and potentially modifying my own implementation.
Extra care is warranted when modifying core, tools, prompts, session, or memory modules --
changes here directly affect my own behaviour.

---

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

## CODEBASE MAP

```
src/
├── cli.py                      # Entry point: TUI launcher (~335 lines)
├── core/
│   ├── agent.py                # CodingAgent facade (~2,617 lines) - see cheat sheet below
│   ├── tool_loop_state.py      # ToolLoopState dataclass (86 lines) - loop iteration state
│   ├── tool_gating.py          # ToolGatingService (289 lines) - tool gating checks
│   ├── special_tool_handlers.py # SpecialToolHandlers (417 lines) - clarify/plan/director approval
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

## BIG FILE CHEAT SHEETS

### agent.py (~2,617 lines) - CodingAgent

**Control Flow:**
```
User Input → stream_response() [async only]
    → ToolGatingService.evaluate() — gating (repeat/plan/director/approval)
    → SpecialToolHandlers — clarify, plan approval, director approval
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

## KNOWN GOTCHAS

1. **Logging race condition (fixed):** Module-level `get_logger()` calls auto-configure logging during import. Solution: all modes log to file only, no console handler.

2. **Tool result ordering:** Tool results must appear in same order as tool calls in the message that requested them, or LLM gets confused.

3. **Orphan tool results:** If a tool_result has no matching tool_call in context, the LLM API rejects it. Agent has orphan detection in `_check_for_orphaned_tool_results()`.

4. **Async in TUI:** The TUI runs async. Never use blocking calls (input(), time.sleep()) in code that runs during TUI mode.

5. **Stream finalization:** Assistant messages start as streaming placeholders, then get finalized with `finalize_message()`. Don't assume content is complete until finalized.

6. **Agent/Subagent parity:** Both `agent.py` and `subagent.py` emit tool state updates via `update_tool_state()`. The VS Code serializer (`serializers.py`) and webview expect identical metadata keys from both. Use `build_tool_metadata()` from `src/core/tool_metadata.py` in both paths. If you add new metadata keys, update the shared builder.

7. **Protocol interrupt lifecycle:** `_interrupted` must be cleared after "Continue" on a pause prompt (via `clear_interrupt()`). See STATE LIFECYCLE comment in `protocol.py`. Forgetting this causes the pause prompt to re-appear on every subsequent iteration.

8. **subprocess.run stdin inheritance (stdio mode):** Every `subprocess.run()` call MUST include `stdin=subprocess.DEVNULL`. In stdio mode, a background thread reads stdin for JSON commands. Without DEVNULL, child processes inherit the stdin handle, causing a deadlock on Windows -- the subprocess hangs, freezing the event loop until data arrives on stdin. This doesn't affect TUI or WebSocket modes (no stdin reader thread).

9. **Document parsing runs in subprocess:** `read_file` for PDF/DOCX delegates to `document_extractor.py` via `subprocess.run()`. This isolates C-library crashes (PyMuPDF/MuPDF) from the agent process. Security guards (file size 10MB, zip bomb detection, 10K line cap, 30s timeout) are enforced. The in-process extraction methods were removed -- all extraction logic lives in `document_extractor.py` only.

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

## LOGS & DIAGNOSTICS

- **Application logs:** `.claraity/logs/app.jsonl` (structured JSONL, all log levels)
- **Metrics DB:** `.claraity/metrics.db` (SQLite, performance metrics and error tracking)
- **Query logs:** `python -m src.observability.log_query --tail 50`
- **Subagent transcripts:** `.claraity/sessions/subagents/<name>-<session_id>.jsonl`

