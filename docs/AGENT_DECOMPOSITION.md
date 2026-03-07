# Agent.py Decomposition - Refactoring Report

## Overview

`src/core/agent.py` was a 3,949-line "God Class" with 57 methods. The critical pain point was `stream_response()` at 1,226 lines with nesting depth 9 and 85 branches. The sync equivalent `_execute_with_tools()` (367 lines) duplicated significant gating logic.

This refactoring decomposed CodingAgent into focused modules while preserving every public API, constructor signature, and all existing test behavior.

## Results

| Metric | Before | After |
|--------|--------|-------|
| `agent.py` lines | 3,949 | 3,381 (-568) |
| Extracted modules | 0 | 4 new files (946 lines) |
| Duplicated gating logic | 2 copies (sync + async) | 1 shared service |
| Test coverage of tool loop | 0 tests | 44 new tests |
| Total test suite | 1,696 passed | 1,708 passed |
| Regressions | - | 0 |

## New File Structure

```
src/core/
    agent.py                  # CodingAgent facade (3,381 lines, down from 3,949)
    tool_loop_state.py        # NEW: ToolLoopState dataclass (86 lines)
    tool_gating.py            # NEW: ToolGatingService (289 lines)
    special_tool_handlers.py  # NEW: Clarify/PlanApproval/DirectorApproval (417 lines)
    stream_phases.py          # NEW: Shared helper functions (154 lines)
    cli_ui.py                 # EXISTING (unchanged)
    error_recovery.py         # EXISTING (unchanged)
```

## What Each Module Does

### tool_loop_state.py (Phase 1)

A `@dataclass` replacing 12+ local variables that were scattered across `stream_response()`:

- **Accumulated counters**: `tool_call_count`, `iteration`, `pause_continue_count`
- **Per-iteration state**: `response_content`, `tool_calls`, `tool_messages`, `blocked_calls`, `user_rejected`, `provider_error`
- **Budget constants**: `MAX_TOOL_CALLS=200`, `ABSOLUTE_MAX_ITERATIONS=50`, etc.
- **Methods**: `reset_iteration()`, `reset_budgets_after_continue()`, `elapsed_seconds`

**Analogy**: Like a clipboard that the tool loop carries through each iteration, instead of juggling 12 loose variables.

### tool_gating.py (Phase 2)

Consolidates the 4 gating checks that were duplicated in both sync and async tool loops:

| Check | Priority | What it does |
|-------|----------|-------------|
| `check_repeat()` | 1 (highest) | Blocks calls that failed with identical args before |
| `check_plan_mode_gate()` | 2 | Restricts writes when plan mode is active |
| `check_director_gate()` | 3 | Restricts writes based on director phase |
| `needs_approval()` | 4 | Determines if user approval is needed (permission mode) |

The `evaluate()` method runs all 4 checks in priority order and returns a `GateResult` with action = `ALLOW`, `DENY`, `NEEDS_APPROVAL`, or `BLOCKED_REPEAT`.

**Analogy**: Like a security checkpoint that every tool call passes through - one checkpoint shared by both the CLI and TUI pathways, instead of two separate checkpoints with duplicated rules.

### special_tool_handlers.py (Phase 3)

Three async tool handlers that pause the tool loop for UI interaction:

| Handler | Lines | What it does |
|---------|-------|-------------|
| `handle_clarify()` | ~105 | Ask structured questions, wait for user answers |
| `handle_plan_approval()` | ~150 | Submit plan for approval, wait for accept/reject |
| `handle_director_plan_approval()` | ~110 | Submit director plan, wait for approval |

All three follow the same pattern: validate -> persist event -> wait for UIProtocol response -> persist response -> return result.

**Analogy**: Like specialized clerks at the security checkpoint who handle special cases (questions, approvals) that require stopping and waiting for the user.

### stream_phases.py (Phase 4)

Shared helper functions used by both the sync (`_execute_with_tools`) and async (`stream_response`) tool loops:

| Function | What it does |
|----------|-------------|
| `build_assistant_context_message()` | Builds the `{"role": "assistant", "tool_calls": [...]}` dict for LLM context |
| `inject_controller_constraint()` | Appends a "blocked calls" constraint message to context |
| `fill_skipped_tool_results()` | Generates stub tool_results for unprocessed calls (after rejection) |
| `build_pause_stats()` | Computes stats dict for pause prompt widgets |

**Analogy**: Like shared utility forms that both the CLI counter and TUI counter use, instead of each counter having its own copy of each form.

## Data Flow

```
User Input
    |
    v
CodingAgent.stream_response()  or  CodingAgent._execute_with_tools()
    |                                    |
    |--- ToolGatingService.evaluate() ---|  (shared gating)
    |                                    |
    |--- SpecialToolHandlers ---|        |  (async only - clarify, plan approval)
    |                           |        |
    |--- stream_phases helpers --|--------|  (shared helpers)
    |                                    |
    v                                    v
UIEvents (TUI)                    ToolExecutionResult (CLI)
```

## What Was NOT Changed

| Preserved | Detail |
|-----------|--------|
| Constructor signature | All 18 params unchanged |
| Public method signatures | `chat()`, `stream_response()`, `execute_task()`, `execute_tool()`, `call_llm()` |
| Public attributes | `hook_manager`, `subagent_manager`, `plan_mode_state`, `tool_executor`, `llm`, `memory`, `working_directory`, `permission_manager`, `director_adapter`, `task_state` |
| AgentInterface compliance | `call_llm`, `execute_tool`, `get_context`, `update_memory` still on CodingAgent |
| All existing tests | 1,696 passed baseline preserved |

## Phase 5: Deferred

The full rewrite of `stream_response()` into a ~180-line orchestrator was **deferred**. The method is an async generator with deeply nested `yield`/`break`/`continue` logic, multiple `try`/`except` levels, and complex state mutations. Converting yields to return-list patterns across 1,000+ lines of intertwined control flow carries high regression risk.

The extracted helpers already provide the core value:
- Shared gating logic (eliminates duplication)
- Testable components (44 new tests)
- Reduced agent.py by 568 lines

The orchestrator rewrite can be done incrementally in a future session.

## New Tests

| File | Tests | Type |
|------|-------|------|
| `tests/core/conftest.py` | - | Shared fixtures (live_agent, MockUIProtocol, make_tool_call) |
| `tests/core/test_tool_loop_integration.py` | 12 | Integration tests using real API |
| `tests/core/test_tool_gating.py` | 20 | Unit tests for all gating checks |
| `tests/core/test_stream_phases.py` | 12 | Unit tests for helper functions |

**Integration tests** (real API via FuelIX proxy):
- Pure text response (no tools)
- Tool call execution and loop-back
- Plan mode gating
- Director mode gating
- User rejection flow
- Oversized output handling
- Sync `_execute_with_tools` path
- Sync `chat()` path

## Verification

Every phase was verified with:
1. `python -c "import ast; ast.parse(open('src/core/agent.py').read())"` - syntax check
2. `python -c "from src.core.agent import CodingAgent"` - import check
3. `pytest tests/core/ -v` - core test suite (124 tests)
4. `pytest tests/ -x -q` - full test suite (1,708 passed, 12 skipped, 0 regressions)
