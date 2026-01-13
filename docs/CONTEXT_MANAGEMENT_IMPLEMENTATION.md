# Context Management Implementation

**Date:** 2025-01-13
**Status:** Complete
**Review Ready:** Yes (GPT-5.2, Claude, etc.)

---

## Executive Summary

This document describes the implementation of Claude Code-style context management for our AI coding agent. The changes address two critical issues:

1. **Silent tool output truncation** - Tool outputs were silently truncated to 2000 characters, causing the LLM to receive incomplete data and fabricate responses
2. **Uncontrolled context growth** - Auto-compaction happened silently inside WorkingMemory with no user notification

---

## Problem Statement

### Issue 1: Silent Truncation (Critical Bug)

**Symptom:** When reading a 794-line Java file, the agent only received 48 lines and fabricated the rest of its analysis.

**Root Cause:** Three locations in `agent.py` silently truncated tool output to 2000 characters:

```python
# BEFORE (silent truncation)
if isinstance(output, str) and len(output) > 2000:
    output = output[:2000] + "\n... (truncated)"
```

**Impact:**
- LLM receives incomplete data
- LLM cannot know data was truncated
- LLM fabricates analysis based on partial information
- User trusts fabricated output

### Issue 2: Uncontrolled Auto-Compaction

**Symptom:** Context window usage dropped unexpectedly (15K → 14K) with no notification.

**Root Cause:** `WorkingMemory` auto-compacted whenever token count exceeded `max_tokens`:

```python
# BEFORE (auto-compaction in add_message)
def add_message(self, role, content, metadata=None):
    # ... add message ...
    if self.get_current_token_count() > self.max_tokens:
        self._compact()  # Silent, no notification
```

**Impact:**
- User unaware of context loss
- No control over when compaction happens
- Debugging context issues is difficult

---

## Solution Design

### Design Principles

1. **Explicit over implicit** - No silent data loss
2. **User notification** - Inform user when context is modified
3. **Separation of concerns** - WorkingMemory stores data, Orchestrator makes policy decisions
4. **Claude Code pattern** - Return errors with actionable guidance for large outputs

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        BEFORE                                    │
├─────────────────────────────────────────────────────────────────┤
│  Tool Output → Silent Truncation → LLM (incomplete data)        │
│  WorkingMemory → Auto-compact (silent) → Data loss              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        AFTER                                     │
├─────────────────────────────────────────────────────────────────┤
│  Tool Output → Size Check → ERROR with guidance → LLM retries   │
│  Agent Loop → Check threshold → Compact → UI Notification       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### Phase 1: Tool Output Truncation Fix

**Goal:** Replace silent truncation with Claude Code-style error messages.

**Files Modified:** `src/core/agent.py`

#### Change 1.0: Add Missing Import

```python
# Line 5 - Added 'os' import for environment variable access
# BEFORE:
import asyncio
import logging
import traceback

# AFTER:
import asyncio
import logging
import os  # NEW
import traceback
```

#### Change 1.1: Location 1 (line ~714)

**Context:** `_process_tool_calls()` method - handles tool execution in non-streaming mode.

```python
# BEFORE (lines 713-715):
if isinstance(output, str) and len(output) > 2000:
    output = output[:2000] + f"\n... (truncated {len(output) - 2000} characters)"

# AFTER:
max_output_chars = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "100000"))
if isinstance(output, str) and len(output) > max_output_chars:
    error_msg = (
        f"Error: Output too large ({len(output):,} characters, limit is {max_output_chars:,}). "
        f"For read_file: use offset and limit parameters to read specific portions of the file. "
        f"For grep/search: use head_limit parameter to limit results. "
        f"For command output: consider piping through head/tail."
    )
    tool_result = {
        "tool": tool_name,
        "arguments": tool_args,
        "success": False,
        "error": error_msg
    }
    tool_messages.append({
        "role": "tool",
        "tool_call_id": call_id,
        "name": tool_name,
        "content": error_msg
    })
    continue  # Skip to next tool call
```

#### Change 1.2: Location 2 (line ~938)

**Context:** Another `_process_tool_calls()` code path.

```python
# Same pattern as Location 1 - replaced silent truncation with error + guidance
```

#### Change 1.3: Location 3 (line ~2428)

**Context:** `stream_response()` method - handles tool execution in streaming mode.

```python
# BEFORE (lines 2426-2429):
if result.is_success():
    output = result.output
    if isinstance(output, str) and len(output) > 2000:
        output = output[:2000] + "\n... (truncated)"

# AFTER:
if result.is_success():
    output = result.output

    # Claude Code style: return ERROR with guidance for oversized output
    max_output_chars = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "100000"))
    if isinstance(output, str) and len(output) > max_output_chars:
        error_msg = (
            f"Error: Output too large ({len(output):,} characters, limit is {max_output_chars:,}). "
            f"For read_file: use offset and limit parameters to read specific portions of the file. "
            f"For grep/search: use head_limit parameter to limit results. "
            f"For command output: consider piping through head/tail."
        )
        yield ToolCallResult(
            call_id=call_id,
            status=ToolStatus.FAILED,
            error=error_msg,
            duration_ms=duration_ms,
        )
        tool_messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": tc.name,
            "content": error_msg
        })
        continue  # Skip to next tool call
```

**Configuration:**
- Environment variable: `TOOL_OUTPUT_MAX_CHARS`
- Default: 100,000 characters
- Can be adjusted per deployment

---

### Phase 2: Remove Auto-Compaction from WorkingMemory

**Goal:** Make WorkingMemory a pure data store; move compaction policy to orchestrator.

**File Modified:** `src/memory/working_memory.py`

#### Change 2.1: Remove auto-compaction from `add_message()`

```python
# BEFORE (lines 73-84):
def add_message(self, role: MessageRole, content: str, metadata: Optional[Dict] = None) -> None:
    message = Message(
        role=role,
        content=content,
        timestamp=datetime.now(),
        metadata=metadata or {},
        token_count=self.count_tokens(content),
    )
    self.messages.append(message)

    # Auto-compact if over budget
    if self.get_current_token_count() > self.max_tokens:
        self._compact()

# AFTER:
def add_message(self, role: MessageRole, content: str, metadata: Optional[Dict] = None) -> None:
    message = Message(
        role=role,
        content=content,
        timestamp=datetime.now(),
        metadata=metadata or {},
        token_count=self.count_tokens(content),
    )
    self.messages.append(message)
    # NOTE: No auto-compaction here. Orchestrator is responsible for calling
    # compact() when context threshold is reached. This ensures user is notified.
```

#### Change 2.2: Remove auto-compaction from `add_code_context()`

```python
# BEFORE (lines 86-92):
def add_code_context(self, code_context: CodeContext) -> None:
    self.code_contexts.append(code_context)

    # Auto-compact if needed
    if self.get_current_token_count() > self.max_tokens:
        self._compact()

# AFTER:
def add_code_context(self, code_context: CodeContext) -> None:
    self.code_contexts.append(code_context)
    # NOTE: No auto-compaction here. Orchestrator is responsible for calling
    # compact() when context threshold is reached. This ensures user is notified.
```

#### Change 2.3: Make `_compact()` public and return count

```python
# BEFORE (lines 98-130):
def _compact(self) -> None:
    """
    Compact working memory by removing or summarizing old messages.
    Uses importance-based retention strategy.
    """
    if len(self.messages) <= 2:
        return
    # ... compaction logic ...
    self.messages = sorted(retained_messages + recent_messages, key=lambda m: m.timestamp)

# AFTER:
def compact(self) -> int:
    """
    Compact working memory by removing or summarizing old messages.
    Uses importance-based retention strategy.

    Called by orchestrator when context threshold is reached.
    Returns number of messages removed for notification purposes.
    """
    original_count = len(self.messages)

    if original_count <= 2:
        return 0

    # ... same compaction logic ...

    self.messages = sorted(retained_messages + recent_messages, key=lambda m: m.timestamp)

    return original_count - len(self.messages)
```

---

### Phase 2b: Update MemoryManager

**File Modified:** `src/memory/memory_manager.py`

#### Change 2b.1: Add `needs_compaction()` method

```python
# NEW METHOD (lines 769-786):
def needs_compaction(self, threshold: float = 0.85) -> bool:
    """
    Check if context usage exceeds threshold and compaction is needed.

    Called by orchestrator to decide whether to trigger compaction with user notification.

    Args:
        threshold: Trigger compaction when usage exceeds this fraction (default: 85%)

    Returns:
        True if compaction is recommended
    """
    current = (
        self.working_memory.get_current_token_count()
        + self.episodic_memory.current_token_count
    )
    available = self.total_context_tokens - self.system_prompt_tokens
    return current > (available * threshold)
```

#### Change 2b.2: Update `optimize_context()` to return count

```python
# BEFORE:
def optimize_context(self, target_tokens: Optional[int] = None) -> None:
    # ... logic ...
    if current > target:
        self.working_memory._compact()

# AFTER:
def optimize_context(self, target_tokens: Optional[int] = None) -> int:
    """
    Optimize context to fit within target token budget.

    Called by orchestrator when needs_compaction() returns True.

    Returns:
        Number of messages removed from working memory (for user notification)
    """
    # ... same logic ...
    messages_removed = 0
    if current > target:
        messages_removed = self.working_memory.compact()  # Now public, returns count
    return messages_removed
```

---

### Phase 3: Orchestrator-Level Compaction with UI Notification

**Goal:** Check compaction threshold in agent loop and notify user via UI.

#### Change 3.1: New UI Event

**File Modified:** `src/ui/events.py`

```python
# NEW EVENT (lines 246-261):
@dataclass(frozen=True)
class ContextCompacted:
    """
    Context was compacted to free up space.

    Emitted when orchestrator triggers compaction due to threshold breach.
    UI should display a notification like "Compacting conversation history..."

    Attributes:
        messages_removed: Number of messages removed from working memory
        tokens_before: Token count before compaction
        tokens_after: Token count after compaction
    """
    messages_removed: int
    tokens_before: int
    tokens_after: int
```

Also added to `UIEvent` union and `__all__` exports.

#### Change 3.2: Add compaction check in agent loop

**File Modified:** `src/core/agent.py`

```python
# In stream_response() imports (line ~1851):
from src.ui.events import (
    UIEvent, StreamStart, StreamEnd, TextDelta,
    ToolCallStart, ToolCallStatus, ToolCallResult, ToolStatus,
    PausePromptStart, PausePromptEnd, ContextUpdated, ContextCompacted,  # Added
)

# In agentic loop, after blocked_calls.clear() (lines 2047-2058):
# Check for context compaction (only after iteration 1, when tool results accumulate)
if iteration > 1 and self.memory.needs_compaction(threshold=0.85):
    tokens_before = self.memory.working_memory.get_current_token_count()
    messages_removed = self.memory.optimize_context()
    tokens_after = self.memory.working_memory.get_current_token_count()

    if messages_removed > 0:
        yield ContextCompacted(
            messages_removed=messages_removed,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )
```

**Why `iteration > 1`?**
- First LLM call has minimal context (system prompt + user message)
- Context grows from tool results accumulating
- No need to check compaction on first iteration

#### Change 3.3: StatusBar info message capability

**File Modified:** `src/ui/widgets/status_bar.py`

```python
# NEW reactive attribute (line 81):
info_message = reactive("")  # Temporary info message (auto-clears)

# NEW methods (lines 370-384):
def show_info(self, message: str, duration: float = 3.0) -> None:
    """
    Show temporary info message (auto-clears after duration).

    Args:
        message: Info message to display
        duration: Seconds before auto-clear (default 3s)
    """
    self.info_message = message
    self.set_timer(duration, self._clear_info)

def _clear_info(self) -> None:
    """Clear info message."""
    self.info_message = ""

# Updated idle check (line 133):
if not self.is_streaming and not self.current_tool and not self.error_message and not self.info_message:

# NEW render case (lines 165-169):
elif self.info_message:
    # Info state - badge style (blue/cyan for informational)
    result.append(" INFO ", style="bold #1e1e1e on #3794ff")
    result.append(" ", style="")
    result.append(f"{self.info_message}", style="#3794ff")
```

#### Change 3.4: App event handler

**File Modified:** `src/ui/app.py`

```python
# Updated import (line 35):
ContextUpdated, ContextCompacted,

# NEW event handler (lines 1261-1267):
# Context compaction notification
case ContextCompacted(messages_removed=removed, tokens_before=before, tokens_after=after):
    try:
        status_bar = self.query_one("#status", StatusBar)
        status_bar.show_info(f"Compacting conversation history... ({removed} messages removed)", duration=4.0)
    except NoMatches:
        pass
```

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `src/core/agent.py` | Added `os` import, 3 truncation fixes, compaction check in loop |
| `src/memory/working_memory.py` | Removed auto-compaction, made `compact()` public with return value |
| `src/memory/memory_manager.py` | Added `needs_compaction()`, updated `optimize_context()` return |
| `src/ui/events.py` | Added `ContextCompacted` event |
| `src/ui/widgets/status_bar.py` | Added `info_message` reactive, `show_info()` method, render logic |
| `src/ui/app.py` | Added `ContextCompacted` import and handler |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TOOL_OUTPUT_MAX_CHARS` | 100000 | Maximum tool output size before error |
| Compaction threshold | 0.85 (85%) | Context usage level that triggers compaction |
| Info message duration | 4.0 seconds | How long compaction notification shows |

---

## Testing Checklist

### Phase 1: Tool Output Truncation

- [ ] Read a large file (>100K chars) and verify error message is returned
- [ ] Verify error message includes actionable guidance
- [ ] Verify LLM receives error and retries with offset/limit parameters
- [ ] Test with custom `TOOL_OUTPUT_MAX_CHARS` value

### Phase 2: WorkingMemory Changes

- [ ] Verify `add_message()` no longer auto-compacts
- [ ] Verify `add_code_context()` no longer auto-compacts
- [ ] Verify `compact()` is accessible (not `_compact()`)
- [ ] Verify `compact()` returns correct message count

### Phase 3: Orchestrator Compaction

- [ ] Verify compaction check only runs when `iteration > 1`
- [ ] Verify `needs_compaction()` correctly detects threshold breach
- [ ] Verify `ContextCompacted` event is yielded
- [ ] Verify StatusBar shows info notification
- [ ] Verify notification auto-clears after 4 seconds

---

## Architectural Decisions

### Why return error instead of truncating?

**Claude Code pattern:** When output exceeds limits, return an error with guidance so the LLM can retry with appropriate parameters. This is better than silent truncation because:

1. LLM knows the data is incomplete
2. LLM receives actionable guidance to fix the issue
3. No fabrication based on partial data
4. User sees explicit feedback

### Why check compaction at iteration > 1?

The first LLM call cannot exhaust context because:
- It starts with only system prompt + user message
- No tool results have accumulated yet

Context grows from tool results being added after each iteration. Checking at `iteration > 1` ensures we only compact when there's actually accumulated data.

### Why 85% threshold?

- **Too low (e.g., 50%):** Frequent unnecessary compaction
- **Too high (e.g., 95%):** Risk of hitting actual limits
- **85%:** Provides buffer for tool results while minimizing unnecessary compaction

### Why separate concerns (WorkingMemory vs Orchestrator)?

- **WorkingMemory:** Pure data store, no policy decisions
- **Orchestrator (Agent):** Makes policy decisions, controls when compaction happens
- **UI:** Receives events, displays notifications

This separation allows:
- Testing each component independently
- Changing compaction policy without modifying storage
- User notification at the orchestrator level

---

## Review Questions for Other LLMs

1. **Error message clarity:** Is the error message for large outputs clear and actionable?

2. **Threshold selection:** Is 85% the right compaction threshold? Should it be configurable?

3. **Iteration check:** Is `iteration > 1` the correct condition, or should we check after tool results are added?

4. **UI notification:** Is 4 seconds the right duration for the compaction notification?

5. **Missing edge cases:** Are there scenarios where this implementation might fail?

6. **Performance:** Does the `needs_compaction()` check add significant overhead to each iteration?

7. **Testing:** Are there additional test cases that should be covered?

---

## Post-Review Fixes (P1 Issues)

After code review, the following issues were identified and fixed:

### P1 Fix #1: Timer Accumulation in `show_info()`

**Issue:** Multiple rapid calls to `show_info()` created multiple timers. Earlier timers would fire and clear the info message prematurely.

**File:** `src/ui/widgets/status_bar.py`

```python
# BEFORE:
def show_info(self, message: str, duration: float = 3.0) -> None:
    self.info_message = message
    self.set_timer(duration, self._clear_info)  # No cancellation!

# AFTER:
def __init__(self, ...):
    ...
    self._info_timer: Timer | None = None  # Track timer

def show_info(self, message: str, duration: float = 3.0) -> None:
    # Cancel any existing info timer to prevent premature clearing
    if self._info_timer:
        self._info_timer.stop()
    self.info_message = message
    self._info_timer = self.set_timer(duration, self._clear_info)

def _clear_info(self) -> None:
    self.info_message = ""
    self._info_timer = None  # Clear reference
```

### P1 Fix #2: Division by Zero in `needs_compaction()`

**Issue:** If `total_context_tokens == system_prompt_tokens`, then `available = 0`, causing unexpected behavior.

**File:** `src/memory/memory_manager.py`

```python
# BEFORE:
def needs_compaction(self, threshold: float = 0.85) -> bool:
    ...
    available = self.total_context_tokens - self.system_prompt_tokens
    return current > (available * threshold)

# AFTER:
def needs_compaction(self, threshold: float = 0.85) -> bool:
    # Validate threshold bounds
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold}")

    current = (...)
    available = self.total_context_tokens - self.system_prompt_tokens

    # Guard against division by zero or negative available space
    if available <= 0:
        return False  # No usable space to manage, don't trigger compaction

    return current > (available * threshold)
```

### P1 Fix #3: Environment Variable Parsed Repeatedly

**Issue:** `os.getenv("TOOL_OUTPUT_MAX_CHARS", "100000")` was parsed on every tool execution, causing inefficiency.

**File:** `src/core/agent.py`

```python
# BEFORE (in 3 locations):
max_output_chars = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "100000"))

# AFTER:
# In __init__:
self._max_tool_output_chars = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "100000"))

# In tool execution code (all 3 locations):
if isinstance(output, str) and len(output) > self._max_tool_output_chars:
    error_msg = f"Error: Output too large ({len(output):,} characters, limit is {self._max_tool_output_chars:,})..."
```

### P1 Fix #4: Inconsistent Error Handling Across Locations

**Issue:** Location 3 (stream_response) was missing `tool_execution_history` tracking that locations 1 and 2 had.

**File:** `src/core/agent.py`

```python
# BEFORE (Location 3 - stream_response):
yield ToolCallResult(...)
tool_messages.append({...})
continue  # Missing history tracking!

# AFTER:
yield ToolCallResult(...)
tool_messages.append({...})
# Track in execution history for debugging/testing
self.tool_execution_history.append({
    "tool": tc.name,
    "arguments": tc.arguments,
    "success": False,
    "error": error_msg
})
continue
```

---

## Updated Files Summary (After P1 Fixes)

| File | Original Changes | P1 Fixes |
|------|------------------|----------|
| `src/core/agent.py` | 3 truncation fixes, compaction check | Env var caching, history tracking |
| `src/memory/memory_manager.py` | `needs_compaction()`, `optimize_context()` | Bounds validation, zero guard |
| `src/ui/widgets/status_bar.py` | `info_message`, `show_info()` | Timer cancellation |

---

## Appendix: Full Diff Reference

For exact line-by-line changes, run:
```bash
git diff HEAD -- src/core/agent.py src/memory/working_memory.py src/memory/memory_manager.py src/ui/events.py src/ui/widgets/status_bar.py src/ui/app.py
```
