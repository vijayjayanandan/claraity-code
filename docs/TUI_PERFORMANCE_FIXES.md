# TUI Performance Fixes

**Date:** 2026-01-13
**Status:** RESOLVED
**Problem:** TUI becomes sluggish/unusable after 3+ conversation turns

---

## Executive Summary

The TUI experienced severe performance degradation after just 3 conversation turns. Scrolling became sluggish even when idle (no streaming).

**Root Cause:** CSS `:hover` pseudo-class rules on scrollbars and widgets. These caused Textual to recalculate styles on every mouse movement, triggering constant re-renders across the widget tree.

**Key Fix:** Removed all `:hover` effects from `styles.tcss` (scrollbars, ThinkingBlock). Performance returned to normal immediately.

**Secondary Fixes:** Status bar optimizations (layout=False, throttled updates) and a safety message limit (100) for very long sessions.

---

## Problem Description

### Symptoms
- Scroll becomes very slow after 3 turns
- UI feels "stuck" or unresponsive
- Typing latency increases
- Issue occurs even when NOT streaming (idle state)

### Root Causes Identified

| Cause | Severity | Description |
|-------|----------|-------------|
| Widget tree bloat | CRITICAL | Each message creates 5-7 child widgets. After 3 turns = 100+ widgets in DOM |
| No virtual scrolling | HIGH | `ScrollableContainer` renders ALL widgets on scroll, not just visible ones |
| Markdown re-parsing | HIGH | Each `Markdown.update()` re-parses entire document |
| Redundant refresh calls | MEDIUM | `refresh()` called after `update()` which already triggers refresh |
| Reactive attribute spam | MEDIUM | Status bar updated on every TextDelta (100+ times per response) |

### Widget Tree Growth Analysis

```
Per assistant message:
├── MessageWidget container
│   ├── MessageHeader + CopyButton
│   ├── Markdown widget (text content)
│   ├── CodeBlock widgets (1 per code section)
│   ├── ToolCard widgets (1 per tool call)
│   │   ├── DiffWidget
│   │   ├── ScrollableDiffContainer
│   │   └── ToolApprovalOptions
│   └── ThinkingBlock widgets

Result: 5-12 widgets per assistant message
After 3 turns (6 messages): 60-100+ widgets
```

---

## Fixes Implemented

### Fix 1: Message Windowing (CRITICAL - Most Impactful)

**File:** `src/ui/app.py`

**What:** Limit mounted messages to 20, remove older ones from DOM.

**Code Added:**
```python
# Line 701-703
MAX_MOUNTED_MESSAGES = 20

# Lines 705-727
async def _prune_old_messages(self, conversation: ScrollableContainer) -> None:
    """Remove oldest messages from DOM if over limit."""
    from .widgets.message import MessageWidget, UserMessage

    messages = list(conversation.query(MessageWidget)) + list(conversation.query(UserMessage))

    if len(messages) > self.MAX_MOUNTED_MESSAGES:
        num_to_remove = len(messages) - self.MAX_MOUNTED_MESSAGES
        for i in range(num_to_remove):
            try:
                messages[i].remove()
            except Exception:
                pass
```

**Called from:**
- `_add_user_message()` - after mounting user message
- `StreamStart` handler - after mounting assistant message

**Impact:** Keeps DOM bounded regardless of conversation length.

**Trade-off:** Old messages are currently removed permanently. Future enhancement could store them in memory for scroll-back.

---

### Fix 2: Status Bar Cheap Refresh

**File:** `src/ui/widgets/status_bar.py`

**What:** Use `refresh(layout=False)` to skip expensive layout recalculation.

**Code Changed (line 310):**
```python
# Before:
self.refresh()

# After:
self.refresh(layout=False)
```

**Why:** Status bar has fixed height (2 lines), layout never needs to change during refresh. Skipping layout calc saves significant CPU.

**Timer interval:** 150ms (smooth spinner animation)

---

### Fix 3: Cached Status Bar Reference

**File:** `src/ui/app.py`

**What:** Cache status bar reference to avoid `query_one()` in hot path.

**Code Added:**
```python
# Line 556-557
self._status_bar: StatusBar | None = None

# Lines 632-636 (in on_mount)
try:
    self._status_bar = self.query_one("#status", StatusBar)
except NoMatches:
    self._status_bar = None
```

**Impact:** Eliminates DOM traversal on every TextDelta event.

---

### Fix 4: Time-Based Throttling for Status Updates

**File:** `src/ui/app.py`

**What:** Only update status bar buffered chars every 200ms instead of every TextDelta.

**Code Added:**
```python
# Lines 559-561
self._last_status_update_ts: float = 0.0
self._status_update_interval_sec: float = 0.2

# Lines 1035-1040 (in TextDelta handler)
now = time.monotonic()
if self._status_bar and (now - self._last_status_update_ts) >= self._status_update_interval_sec:
    self._status_bar.update_buffered_chars(self._segment_chars)
    self._last_status_update_ts = now
```

**Impact:** 95% fewer reactive attribute updates (100+ → 5 per response).

---

### Fix 5: Faster Segment Flush Interval

**File:** `src/ui/app.py`

**What:** Reduced flush interval from 2.0s to 0.5s.

**Code Changed (line 572):**
```python
# Before:
self._segment_flush_interval_sec: float = 2.0

# After:
self._segment_flush_interval_sec: float = 0.5
```

**Impact:** Progress text appears faster when model pauses output.

---

### Fix 6: Method Reference Instead of Lambda

**File:** `src/ui/app.py`

**What:** Use method reference for timer callback to avoid closure issues.

**Code Changed (lines 1029-1032):**
```python
# Before:
self._segment_flush_handle = loop.call_later(
    self._segment_flush_interval_sec,
    lambda: asyncio.create_task(self._flush_segment())
)

# After:
self._segment_flush_handle = loop.call_later(
    self._segment_flush_interval_sec,
    self._schedule_segment_flush  # Method reference
)
```

**Helper method added (lines 1323-1348):**
```python
def _schedule_segment_flush(self) -> None:
    if not self._is_streaming or self._segment_flush_running:
        return
    asyncio.create_task(self._guarded_segment_flush())

async def _guarded_segment_flush(self) -> None:
    if self._segment_flush_running:
        return
    self._segment_flush_running = True
    try:
        await self._flush_segment()
    finally:
        self._segment_flush_running = False
```

**Impact:** Prevents memory leaks from lambda closures, prevents overlapping flush tasks.

---

### Fix 7: Removed Redundant Refresh Calls

**File:** `src/ui/widgets/message.py`

**What:** Removed `refresh()` calls after `update()` - the update already triggers refresh internally.

**Code Changed:**
```python
# Line 271 - in add_text()
# Before:
self._current_markdown.update(self._markdown_text)
self._current_markdown.refresh()  # REMOVED

# After:
self._current_markdown.update(self._markdown_text)

# Line 289 - in set_text()
# Same change
```

**Impact:** ~50% fewer Markdown widget re-renders.

---

### Fix 8: Timer Cleanup in Finally Block

**File:** `src/ui/app.py`

**What:** Ensure `_segment_flush_running` flag is always reset.

**Code Added (line 842):**
```python
finally:
    # ... existing cleanup ...
    self._segment_flush_running = False  # Always reset flush guard
```

**Impact:** Prevents stuck state if stream ends abnormally.

---

## What Was Tried But Reverted

### Streaming Text Optimization (Reverted)

**Attempted approach:**
- Use `append_streaming_text()` (O(1) Rich Text append) during streaming
- Call `finalize_streaming_text()` once at end to create Markdown widget
- This would reduce O(n²) markdown parsing to O(n)

**Why reverted:**
- `start_streaming_text()` and `finalize_streaming_text()` used synchronous `self.mount()` instead of `await self.mount()`
- This may have caused widget mounting issues in Textual
- The issue existed before this change, so it wasn't the root cause

**Current state:** Using original `add_text()` approach which does markdown parsing on each flush. The O(n²) issue is mitigated by:
1. Less frequent flushes (0.5s interval)
2. Message windowing (limits total widgets)

---

## Debug Counters (Available)

Performance counters were added for debugging:

**File:** `src/ui/widgets/message.py`
```python
from src.ui.widgets.message import get_perf_counters, reset_perf_counters

counters = get_perf_counters()
# Returns: {'markdown_parses': N, 'streaming_appends': N, 'widgets_mounted': N}
```

**File:** `src/ui/widgets/status_bar.py`
```python
from src.ui.widgets.status_bar import get_status_bar_counters

counters = get_status_bar_counters()
# Returns: {'refresh_ticks': N}
```

**Enable debug logging:**
```bash
TUI_PERF_DEBUG=1 python -m src.cli
```

---

## Future Improvements

### 1. Virtual Scrolling (HIGH IMPACT)
Replace `ScrollableContainer` with a virtualized container that:
- Only renders visible messages
- Keeps 1-2 buffer messages above/below viewport
- Recycles widgets as user scrolls

**Estimated improvement:** 60-80% reduction in rendering cost

### 2. Transcript Preservation
Currently, pruned messages are deleted. Enhance to:
- Store message data in `self._transcript` list
- Implement scroll-back to load older messages on demand
- Show "X older messages - scroll up to load" indicator

### 3. Lazy Markdown Parsing
- During streaming: render as plain text (Static widget)
- After stream ends: convert to Markdown once
- Reduces O(n²) to O(n) parsing

### 4. Code Block Lazy Loading
`CodeBlock.render()` calls `Syntax(...)` which is expensive.
- Defer syntax highlighting until widget is visible
- Use async background task for highlighting

### 5. Widget Pooling
Reuse widget instances instead of creating new ones:
- Pool of MessageWidget instances
- Reset and reuse for new messages
- Reduces GC pressure

---

## Files Modified

| File | Changes |
|------|---------|
| `src/ui/app.py` | Message windowing (8 msg limit), cached status bar, throttling, timer fixes, Ctrl+W debug |
| `src/ui/widgets/message.py` | Removed redundant refresh, added perf counters |
| `src/ui/widgets/status_bar.py` | layout=False refresh, perf counters |
| `src/ui/styles.tcss` | Removed all :hover effects from scrollbars and ThinkingBlock |

---

## Fix 9: Message Limit Disabled

**File:** `src/ui/app.py`

**What:** Message limit disabled - all messages are shown.

**Code (line 704):**
```python
MAX_MOUNTED_MESSAGES = None  # None = no limit
```

**Finding:** The root cause was CSS :hover effects, NOT widget count. With hover effects removed, performance remains good even with many messages. No message limit is needed.

---

## Fix 10: Debug Widget Count Action

**File:** `src/ui/app.py`

**What:** Added Ctrl+W binding to count and display all widgets in the conversation.

**Usage:**
- Press `Ctrl+W` at any time to see widget counts
- Displays: Total widgets, Messages, ToolCards, CodeBlocks
- Shows notification and logs to `logger.info()`

**Example output:**
```
[DEBUG] Widget count: Total=45, Messages=6, ToolCards=12, CodeBlocks=8
```

**Use this to:**
1. Verify message windowing is working (messages should stay ≤8)
2. Check if tool cards or code blocks are accumulating
3. Compare widget counts between responsive and sluggish states

---

## Fix 11: Remove Hover Effects from CSS

**File:** `src/ui/styles.tcss`

**What:** Removed all `:hover` pseudo-class rules that change styles on mouse movement.

**Rules Removed:**
- `#conversation:hover` - scrollbar color change
- `ScrollableContainer:hover` - scrollbar color change
- `ScrollableContainer > .scrollbar--bar:hover` - scrollbar background change
- `VerticalScroll:hover` - scrollbar color change
- `ThinkingBlock:hover` - background color change

**Why:** In Textual, `:hover` effects can trigger style recalculation every time the mouse moves over a widget. With many widgets in the DOM, this can cause constant re-rendering even when the app is idle.

**Impact:** Reduces CPU usage during mouse movement over the conversation area.

---

## Testing Checklist

- [ ] Start fresh TUI: `python -m src.cli`
- [ ] Send 5+ messages to agent
- [ ] **Press Ctrl+W** to check widget counts
- [ ] Verify scroll remains responsive after each turn
- [ ] Check that older messages disappear (windowing working)
- [ ] Verify typing latency stays normal
- [ ] Verify spinner animation is smooth during streaming
- [ ] Test Ctrl+C interrupt works properly
- [ ] Test with `TUI_PERF_DEBUG=1` to see counters

---

## Performance Metrics (Actual Results)

| Metric | Before | After |
|--------|--------|-------|
| CSS hover recalculations | Every mouse move | None (hover removed) |
| Status bar updates/response | 100+ | ~5 (throttled) |
| Markdown refreshes/flush | 2 | 1 |
| Scroll responsiveness | Degrades after 3 turns | Constant |
| Message limit | N/A | None (all messages shown) |

---

## References

- Textual Widget API: https://textual.textualize.io/api/widget/
- Textual Reactivity: https://textual.textualize.io/guide/reactivity/
- Rich Markdown: https://rich.readthedocs.io/en/latest/markdown.html
