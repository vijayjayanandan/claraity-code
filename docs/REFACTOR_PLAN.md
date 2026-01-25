# Refactoring Plan: agent.py and app.py

**Created:** 2026-01-24
**Status:** Ready for implementation
**Estimated Savings:** 1,000-1,250 lines (~17% reduction)

---

## Overview

Code review identified significant optimization opportunities in the two largest files:
- `src/core/agent.py` (4,200 lines) → Target: ~3,400-3,600 lines
- `src/ui/app.py` (3,300 lines) → Target: ~2,850-2,900 lines

---

## Priority 1: Split `stream_response()` (CRITICAL)

**File:** `src/core/agent.py`
**Current:** Lines 2063-3342 (1,280 lines)
**Target:** ~300 lines with 5 helper methods

### Problem
Single async generator method handling 8 different concerns. Unmaintainable and untestable.

### Solution
Extract these helper methods:

```python
# 1. Budget checking (lines 2201-2281)
def _check_budget_limits(self) -> Optional[str]:
    """Returns pause_reason if any limit hit, None otherwise."""

# 2. LLM streaming with error recovery (lines 2299-2510)
async def _stream_llm_with_recovery(self, messages, ...) -> AsyncIterator[...]:
    """Handles LLM streaming and provider error recovery."""

# 3. Error budget pause flow (lines 2982-3083, 3133-3234)
async def _handle_error_budget_pause(self, error_context, ...) -> bool:
    """Handles pause flow when error budget exceeded. Returns True to continue."""

# 4. Single tool execution (lines 2752-2935)
async def _execute_single_tool(self, tool_call, ...) -> ToolResult:
    """Executes one tool with approval flow and error handling."""

# 5. Oversized output handling (lines 760-781, 999-1018, 2832-2876)
def _format_oversized_output_error(self, tool_name: str, output_size: int) -> str:
    """Returns consistent error message for oversized tool output."""
```

### Verification
- All existing tests pass
- Manual test: Run TUI, execute multi-tool task, verify streaming works

---

## Priority 2: Extract Segment Rendering (HIGH)

**File:** `src/ui/app.py`
**Duplicated at:** Lines 2393-2443, 2519-2561, 2599-2643, 2820-2871
**Savings:** ~120 lines

### Problem
Same segment rendering logic copied 4 times:
1. `_on_store_message_added()`
2. `_flush_store_updates()`
3. `_on_store_message_finalized()`
4. `_on_store_bulk_load_complete()`

### Solution
Extract to single helper:

```python
async def _render_segments(
    self,
    widget: MessageWidget,
    segments: List[Segment],
    message: Message
) -> None:
    """Render segments to a message widget.

    Handles: TextSegment, CodeBlockSegment, ThinkingSegment,
             ToolCallRefSegment, ToolCallSegment
    """
    for segment in segments:
        if isinstance(segment, TextSegment):
            widget.append_text(segment.content)
        elif isinstance(segment, CodeBlockSegment):
            widget.append_code_block(segment.code, segment.language)
        # ... etc
```

### Verification
- Session replay works correctly
- Live streaming displays properly
- Bulk load (resume) renders all message types

---

## Priority 3: Split `_handle_event()` (HIGH)

**File:** `src/ui/app.py`
**Current:** Lines 1331-1656 (325 lines, 14+ cases)
**Target:** ~50 lines dispatcher + 14 small handlers

### Problem
Giant match/case block handling all UIEvent types. Hard to test individual handlers.

### Solution
Extract each case to its own method:

```python
async def _handle_event(self, event: UIEvent, msg: AssistantMessage) -> None:
    """Dispatch UIEvent to specific handler."""
    handlers = {
        "stream_start": self._on_stream_start,
        "text_delta": self._on_text_delta,
        "tool_call_start": self._on_tool_call_start,
        "tool_call_complete": self._on_tool_call_complete,
        "approval_request": self._on_approval_request,
        "error": self._on_error,
        "stream_end": self._on_stream_end,
        # ... etc
    }
    handler = handlers.get(event.type)
    if handler:
        await handler(event, msg)

async def _on_stream_start(self, event: UIEvent, msg: AssistantMessage) -> None:
    """Handle stream_start event."""
    # ~15 lines

async def _on_text_delta(self, event: UIEvent, msg: AssistantMessage) -> None:
    """Handle text_delta event."""
    # ~20 lines

# ... etc for each event type
```

### Verification
- All event types still handled correctly
- Streaming text appears properly
- Tool cards render and update

---

## Priority 4: Remove Dead Code (MEDIUM)

### agent.py Dead Code

| Lines | Code | Reason |
|-------|------|--------|
| 1368-1386 | `_format_tool_results()` | Never called |
| 1389-1407 | `_display_analysis()` | Only used by deprecated workflow mode |
| 1409-1427 | `_workflow_progress_callback()` | Only used by deprecated workflow mode |
| 1428-1529 | `_execute_with_workflow()` | Workflow mode deprecated |
| 1531-1586 | `_generate_success_response()`, `_generate_failure_response()` | Only used by workflow |

**Decision needed:** Is workflow mode (`force_workflow=True`) still needed? If not, remove ~200 lines.

### app.py Dead Code

| Lines | Code | Reason |
|-------|------|--------|
| 13 | `Input` import | Never used (uses ChatInput) |
| 888-914 | `_prune_old_messages()` | Disabled, always returns early |
| 743-747 | Full streaming mode variables | Mode hardcoded to "segmented" |
| 1781-1843 | `_buffer_len()`, `_schedule_flush()`, `_delayed_flush()`, `_flush_deltas()`, `_cleanup_flush()` | Only used in "full" mode which is disabled |
| 3087-3167 | `replay_session()`, `start_replay_mode()` | Unused, session replay uses `_load_session()` |

**Estimated removal:** ~180 lines

---

## Priority 5: Consolidate Duplicate Patterns (MEDIUM)

### agent.py Duplications

| Pattern | Locations | Extract To |
|---------|-----------|------------|
| Hook manager UserPromptSubmit | Lines 1743-1776, 1895-1926, 3381-3409 | `_emit_user_prompt_hook()` |
| Working memory transcript persistence | Lines 1641-1657, 1979-1997, 3450-3466 | `_persist_turn_messages()` |
| Message store null checks | 14 occurrences | `_get_message_store()` or ensure always set |

### app.py Duplications

| Pattern | Locations | Extract To |
|---------|-----------|------------|
| Logger re-import in methods | Lines 2675, 2715, 2746, 3051 | Module-level `logger = get_logger(__name__)` |
| Inline imports in loops | Lines 2386-2389, 2500-2503, 2593-2597, 2814-2818 | Move to module level |

---

## Priority 6: Fix Logging Violations (LOW)

**File:** `src/ui/app.py`, Line 22

```python
# WRONG (current)
import logging
logger = logging.getLogger(__name__)

# RIGHT (should be)
from src.observability import get_logger
logger = get_logger(__name__)
```

This violates the project guideline in CLAUDE.md.

---

## Implementation Order

1. **Phase 1: Low-risk removals**
   - Remove dead code (Priority 4)
   - Fix logging violations (Priority 6)
   - Move inline imports to module level
   - Run tests to verify nothing breaks

2. **Phase 2: Extract helpers**
   - Extract `_render_segments()` in app.py (Priority 2)
   - Extract `_handle_error_budget_pause()` in agent.py
   - Extract `_format_oversized_output_error()` in agent.py
   - Run tests after each extraction

3. **Phase 3: Major refactors**
   - Split `_handle_event()` (Priority 3)
   - Split `stream_response()` (Priority 1)
   - These are higher risk - do one at a time with full test runs

---

## Testing Checklist

After each phase:
- [ ] `pytest tests/` passes
- [ ] TUI starts: `python -m src.cli --tui`
- [ ] Can send message and receive streaming response
- [ ] Tool execution works (try a file read)
- [ ] Tool approval flow works
- [ ] Session resume works (`/resume` command)
- [ ] Error handling works (trigger an intentional error)

---

## Notes

- Line numbers are from 2026-01-24 analysis. They may shift as code changes.
- Use `Read file offset=X limit=50` to verify locations before editing.
- Consider creating a feature branch for this refactor work.
- Run code-reviewer agent after completing each priority to validate improvements.
