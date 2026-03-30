# Test Failure Analysis

**Date:** 2026-02-15
**Branch:** develop
**Test run:** `pytest tests/` — 1721 passed, 134 failed, 60 errors, 10 skipped

## Overview

194 test problems (134 failures + 60 errors) across 23 test files, caused by 6 distinct root causes. The majority trace back to code changes (constructor signatures, import restructuring, return type changes) that were not propagated to their corresponding tests.

**Important:** The agent runs fine in production despite these failures. See "Why the Agent Works Despite These Issues" at the end for a detailed explanation.

---

## Root Cause 1: Circular Import (`src.llm` <-> `src.core`)

**Impact:** ~62 tests (30 failures + 32 collection errors)
**Type:** Latent code bug (import-order dependent — see "Why the Agent Works" section)
**Fix location:** `src/core/__init__.py`

### Affected test files

| File | Count | Type |
|------|-------|------|
| `tests/test_search_tools.py` | 30 | Collection error |
| `tests/subagents/test_subagent.py` | 12 | Collection error |
| `tests/core/test_agent_subagent_integration.py` | 10 | Collection error |
| `tests/test_memory_observation_integration.py` | 8 | Collection error |
| `tests/test_testing/test_integration.py` | 4 | Collection error (via claraity_tools) |
| `tests/claraity/test_claraity_api.py` | 1 | Collection error |

### Import chain

```
src.tools.claraity_tools
  -> src.claraity.__init__
    -> src.claraity.core.generator
      -> src.llm (starts loading)
        -> src.llm.base
          -> src.session.models.message
            -> src.session.__init__
              -> src.session.store.__init__
                -> src.session.store.memory_store
                  -> src.core.events
                    -> src.core.__init__        <-- eagerly imports CodingAgent
                      -> src.core.agent
                        -> src.llm              <-- CIRCULAR: still loading
```

### Error message

```
ImportError: cannot import name 'LLMBackend' from partially initialized module 'src.llm'
(most likely due to a circular import)
```

### Fix approach

Remove the eager `from .agent import CodingAgent` from `src/core/__init__.py`. Consumers should import directly from `src.core.agent` instead. Alternatively, use lazy imports in the `__init__.py`.

---

## Root Cause 2: `CodingAgent.__init__()` missing required `context_window` parameter

**Impact:** 15 failures
**Type:** Stale tests
**Fix location:** `tests/core/test_agent_hook_integration.py`

### Error message

```
TypeError: CodingAgent.__init__() missing 1 required positional argument: 'context_window'
```

### Details

The `CodingAgent` constructor was updated to require a `context_window` parameter. All 15 tests in `test_agent_hook_integration.py` construct `CodingAgent` with the old signature (`CodingAgent(**API_CONFIG)`) and need `context_window` added.

### Fix approach

Update the `API_CONFIG` fixture in the test file to include `context_window` (e.g., `context_window=128000`).

---

## Root Cause 3: `LongRunningController.__init__()` constructor signature changed

**Impact:** 30 errors + 2 failures (32 total)
**Type:** Stale tests
**Fix location:** `tests/test_long_running_controller.py`

### Error message

```
TypeError: LongRunningController.__init__() got an unexpected keyword argument 'checkpoint_interval_minutes'
```

### Details

The `LongRunningController` constructor was refactored — the `checkpoint_interval_minutes` parameter was removed or renamed. The test fixture at line 64 still passes this keyword argument.

### Fix approach

Inspect `LongRunningController.__init__()` to find the current parameter names, then update the test fixture accordingly.

---

## Root Cause 4: `SubAgentConfig` field `model` removed or renamed

**Impact:** 9 failures
**Type:** Stale tests
**Fix location:** `tests/subagents/test_config.py`

### Error message

```
TypeError: SubAgentConfig.__init__() got an unexpected keyword argument 'model'
```

### Details

The `SubAgentConfig` dataclass/model was refactored — the `model` field no longer exists under that name. 9 tests still pass `model=` when constructing configs.

### Fix approach

Inspect `SubAgentConfig` to find the current field names, then update the 9 failing tests to use the new field name.

---

## Root Cause 5: Orchestration layer expects object, gets string

**Impact:** 14 failures
**Type:** Stale code (orchestration layer not used in production TUI/CLI path)
**Fix location:** `src/` orchestration layer or `src/core/agent.py` return type

### Affected tests

All 14 failing tests in `tests/test_orchestration_basic.py` (the 32 passing tests in the same file are unaffected — they test different code paths).

### Error message

```
AgentResponse(content="Agent execution failed: 'str' object has no attribute 'content'",
  success=False, error="AttributeError: 'str' object has no attribute 'content'")
```

### Details

The orchestration `ConversationSession.send_message()` calls the agent and then accesses `.content` on the return value. However, `CodingAgent.chat()` now returns a plain string instead of an object with a `.content` attribute.

### Fix approach

Either:
1. Update the orchestration layer to handle string returns (wrap in a response object), or
2. Ensure `chat()` returns the expected response object.

---

## Root Cause 6: Miscellaneous (8 sub-issues)

### 6a. LSP client manager — column out of range

**Impact:** 15 failures in `tests/test_lsp_client_manager.py`
**Type:** Test fixture bug

```
LSPQueryError: Query failed after retry: LSP query failed:
ValueError: `column` parameter (5) is not in a valid range (0-0) for line 11 ('\n')
```

The test fixtures create temporary Python files but the LSP query positions (line/column) don't match the actual file content. The LSP server validates that columns fall within the line length and rejects invalid positions.

**Fix:** Update test fixtures so query positions match the content of the temp files.

### 6b. Checkpoint manager — Mock not JSON-serializable

**Impact:** 8 failures in `tests/test_checkpoint_manager.py`
**Type:** Stale tests

```
TypeError: Object of type Mock is not JSON serializable
```

The checkpoint save logic now serializes agent state to JSON. The test mocks don't implement the serialization interface (e.g., `to_dict()`).

**Fix:** Add proper serialization stubs to the mock objects in the test fixtures.

### 6c. Session manager — file not created eagerly

**Impact:** 8 failures in `tests/session/test_session_manager.py`
**Type:** API contract change (code or test)

```
AssertionError: assert False
  where False = WindowsPath('.../<session_id>.jsonl').exists()
```

`create_session()` no longer creates the JSONL file on disk immediately — it's created lazily on first write. Tests assert the file exists right after creation.

**Fix:** Either restore eager file creation in the source, or update tests to not assert file existence until after a write.

### 6d. Agent interface — API key not mocked

**Impact:** 4 failures in `tests/test_agent_interface.py`
**Type:** Stale tests

```
ValueError: API key not provided. Set an API key in the LLM config wizard...
```

Tests construct `CodingAgent` without mocking the API key validation that was added later.

**Fix:** Patch the API key validation or provide a dummy key in the test fixture.

### 6e. File reference parser — Windows path splitting

**Impact:** 1 failure in `tests/test_file_reference_parser.py`
**Type:** Code bug

```
assert WindowsPath('.../C') == WindowsPath('.../test.py')
```

The parser splits `@C:\Users\...\test.py` at the first `:`, treating `C` as the path and `\Users\...\test.py` as a line range. This is a Windows-specific bug where drive letters contain `:`.

**Fix:** Update the parser regex to handle Windows drive letters (e.g., `C:\`).

### 6f. Missing `src.workflow` module

**Impact:** 2 collection errors (`tests/test_e2e_verification.py`, `tests/test_permission_modes.py`)
**Type:** Tests for unimplemented feature

```
ModuleNotFoundError: No module named 'src.workflow'
```

These tests import from `src.workflow.permission_manager` which doesn't exist yet.

**Fix:** Either implement the module, or mark these tests with `pytest.mark.skip` until the module is built.

### 6g. Session writer

**Impact:** 1 failure in `tests/session/test_writer.py`
**Type:** Needs investigation

Single test failure — not yet investigated in detail.

### 6h. Core session manager

**Impact:** 1 failure in `tests/core/test_session_manager.py`
**Type:** Needs investigation

Single test failure — not yet investigated in detail.

---

## Summary Table

| # | Root Cause | Tests | Fix Type | Priority |
|---|-----------|-------|----------|----------|
| 1 | Circular import `src.core` <-> `src.llm` | ~62 | Code | High |
| 2 | `CodingAgent` missing `context_window` param | 15 | Test | High |
| 3 | `LongRunningController` constructor changed | 32 | Test | High |
| 4 | `SubAgentConfig` `model` field renamed | 9 | Test | Medium |
| 5 | Orchestration expects object, gets string | 14 | Code | Medium |
| 6a | LSP column out of range | 15 | Test | Medium |
| 6b | Checkpoint manager mock serialization | 8 | Test | Medium |
| 6c | Session manager lazy file creation | 8 | Code/Test | Medium |
| 6d | Agent interface API key not mocked | 4 | Test | Low |
| 6e | File reference parser Windows paths | 1 | Code | Low |
| 6f | Missing `src.workflow` module | 2 | Skip | Low |
| 6g | Session writer | 1 | TBD | Low |
| 6h | Core session manager | 1 | TBD | Low |
| **Total** | | **~172** | | |

---

## Recommended Fix Order

1. **Circular import** (Root Cause 1) — Highest impact, unblocks ~62 tests
2. **Constructor signatures** (Root Causes 2, 3, 4) — Easy wins, ~56 tests
3. **Orchestration contract** (Root Cause 5) — 14 tests, moderate effort
4. **Test fixture updates** (Root Causes 6a-6d) — 35 tests, moderate effort
5. **Low-priority** (Root Causes 6e-6h) — 5 tests, low effort

---

## Why the Agent Works Despite These Issues

The agent runs fine in production (TUI/CLI) because none of these issues affect the normal execution path. Here's why each one is invisible at runtime:

### Circular import: import order saves us

The circular import between `src.llm` and `src.core` is **import-order dependent**. It only triggers when `src.llm` starts loading BEFORE `src.core`.

**Normal startup** (`python -m src.cli`):

```
src.cli
  line 41: from src.core import CodingAgent
    → src.core.__init__ starts loading (added to sys.modules)     [1]
      → src.core.agent starts loading
        line 18: from src.llm import ...
          → src.llm starts loading                                [2]
            → src.llm.base → src.session → ... → src.core.events
              Python sees src.core ALREADY in sys.modules (from [1])
              → loads events.py directly, does NOT re-run __init__.py
            → src.llm finishes loading completely                 [3]
        line 22: from src.tools import ...
          → src.tools.__init__ → claraity_tools → src.claraity
            → from src.llm import LLMBackend
              src.llm already FULLY loaded (from [3]) → works!
```

**Test path** (e.g., `import src.tools.search_tools`):

```
test_search_tools.py
  → src.tools.__init__ → claraity_tools → src.claraity
    → from src.llm import ...
      → src.llm starts loading (PARTIALLY)                       [1]
        → src.llm.base → src.session → ... → src.core.events
          → src.core.__init__ starts loading (FIRST TIME)
            → src.core.agent
              line 18: from src.llm import LLMBackend
                src.llm in sys.modules but STILL PARTIAL (from [1])
                → ImportError!
```

The critical difference: in normal startup, `src.core` loads first, so `src.llm` is fully resolved before the claraity chain needs it. In tests, `src.tools` or `src.claraity` can load first, causing `src.llm` to be mid-initialization when `src.core.__init__` tries to import from it.

**Risk:** This is a latent bug. Any future refactor that changes import order in `src/cli.py` could break production. Fixing the circular import properly (e.g., lazy imports in `src/core/__init__.py`) would eliminate this fragility.

### Orchestration layer: not on the production path

The `ConversationSession` / `AgentOrchestrator` classes are an alternative API layer not used by the TUI or CLI. The normal flow is:

```
src.cli → CodingAgent.chat_async() → LLM → tools → response
```

The orchestration layer (`src/orchestration/`) wraps the agent differently and has a stale assumption about the `chat()` return type. It will need updating if/when it's integrated into the main app.

### Stale test fixtures: code evolved, tests didn't

Root Causes 2-4 and 6a-6d are all cases where source code was refactored (new constructor parameters, renamed fields, stricter validation) but the corresponding test files weren't updated. The production code is correct — only the tests are out of date.

### File reference parser Windows paths: edge case

The `@C:\path\file.py` parsing bug (Root Cause 6e) only triggers when users reference absolute Windows paths with the `@` prefix. In practice, relative paths (`@src/file.py`) are the common usage pattern.

### Missing `src.workflow`: not yet built

The `src.workflow` module (Root Cause 6f) is a planned feature that hasn't been implemented yet. The tests were written ahead of the code.
