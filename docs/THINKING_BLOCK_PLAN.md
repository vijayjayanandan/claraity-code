# Plan: Wire Up Live Thinking Block Rendering

## Context

ClarAIty has complete infrastructure for displaying thinking blocks (extended thinking / chain-of-thought reasoning) in the TUI — a `ThinkingBlock` widget, UIEvent types, StoreAdapter handlers, and pipeline accumulation. However, **none of it is connected during live streaming**. The agent never yields `ThinkingStart`/`ThinkingDelta`/`ThinkingEnd` events, and the TUI has no handler for them. Result: users never see thinking blocks.

This plan wires up the existing infrastructure so thinking blocks render **live during streaming** from the Anthropic native backend (`ProviderDelta.thinking_delta`).

**Scope**: Native `thinking_delta` from Anthropic backend only. Tag-based `<thinking>` parsing (OpenAI proxy) is left as-is for now — it currently renders as raw text, no regression.

---

## What Already Works (no changes needed)

| Component | File | Status |
|-----------|------|--------|
| `ThinkingBlock` widget | `src/ui/widgets/thinking.py` | Collapsible panel, click to expand, token count |
| `start_thinking()` / `append_thinking()` / `end_thinking()` | `src/ui/widgets/message.py:558-608` | Mounts/updates/finalizes ThinkingBlock |
| `ThinkingStart` / `ThinkingDelta` / `ThinkingEnd` events | `src/core/events.py:155-175` | Defined, exported |
| `StoreAdapter._handle_thinking_*` | `src/ui/store_adapter.py:437-471` | Accumulates thinking for persistence |
| Pipeline accumulation | `src/core/streaming/pipeline.py:329-340` | Accumulates `thinking_content` |
| Session replay rendering | `src/ui/app.py:3318-3322` | Renders ThinkingSegment on replay |
| `self._current_thinking` attribute | `src/ui/app.py:802` | Exists, cleared on finalize |

---

## Files to Change

| # | File | Action | What |
|---|------|--------|------|
| 1 | `src/core/agent.py` | **EDIT** | Yield ThinkingStart/ThinkingDelta/ThinkingEnd in streaming loop |
| 2 | `src/ui/app.py` | **EDIT** | Add event handlers in `_handle_event()` |
| 3 | `tests/core/test_thinking_events.py` | **NEW** | Test event emission logic |

---

## Implementation Steps

### Step 1: Agent yields thinking events (`src/core/agent.py`)

**1a. Add imports** (~line 17 where UIEvent imports are):

Add `ThinkingStart, ThinkingDelta, ThinkingEnd` to the existing event imports.

**1b. Add thinking state flag** (line ~2822, before the `async for delta` loop):

```python
_thinking_active = False
```

**1c. Yield thinking events in the streaming loop** (lines 2824-2838):

Replace the current loop body with:

```python
async for delta in llm_stream:
    finalized_message = self.memory.process_provider_delta(delta)

    # Yield thinking deltas to TUI for live rendering
    if delta.thinking_delta:
        if not _thinking_active:
            _thinking_active = True
            yield ThinkingStart()
        yield ThinkingDelta(content=delta.thinking_delta)

    # End thinking block if text or tool_call arrives
    if delta.text_delta or delta.tool_call_delta:
        if _thinking_active:
            _thinking_active = False
            yield ThinkingEnd()

    # Yield text deltas to TUI for incremental rendering
    if delta.text_delta:
        yield TextDelta(content=delta.text_delta)

    if delta.usage:
        last_usage = delta.usage

    if ui.check_interrupted():
        break
```

**1d. Close thinking on stream end** (after the `async for` loop, before line 2840):

```python
if _thinking_active:
    _thinking_active = False
    yield ThinkingEnd()
```

**Why `tool_call_delta` also closes thinking**: Anthropic's extended thinking finishes before tool_use blocks. If the model goes thinking -> tool_use (no text in between), we still need to close the thinking block.

### Step 2: TUI handles thinking events (`src/ui/app.py`)

**2a. Add handlers in `_handle_event()`** (insert between TextDelta handler at line 2069 and PausePromptStart at line 2071):

```python
# ThinkingStart -- flush text segment, create thinking block
elif isinstance(event, ThinkingStart):
    await self._flush_segment()
    if not self._current_message:
        self._current_message = AssistantMessage()
        await conversation.mount(self._current_message)
    try:
        await self._current_message.set_loading(False)
    except Exception:
        pass
    self._current_thinking = self._current_message.start_thinking()

# ThinkingDelta -- append to current thinking block
elif isinstance(event, ThinkingDelta):
    if self._current_thinking:
        self._current_thinking.append(event.content)

# ThinkingEnd -- finalize thinking block
elif isinstance(event, ThinkingEnd):
    if self._current_message:
        self._current_message.end_thinking(event.token_count)
    self._current_thinking = None
```

**Key design decisions**:
- `_flush_segment()` before ThinkingStart: Same pattern as PausePromptStart (line 2072). Buffered text must render before the thinking block starts, or ordering is wrong.
- Create `_current_message` defensively: Thinking can be the first content from the LLM (before any text). Same pattern as TextDelta handler (lines 2049-2051).
- Append directly to `_current_thinking` (the ThinkingBlock widget): Bypasses segment buffering — thinking content renders immediately via Textual's reactive attributes. No timer-based flush needed.
- `ThinkingEnd` passes `token_count=None` for now: Token count arrives later in the `usage` dict. The widget handles `None` gracefully.

### Step 3: Tests (`tests/core/test_thinking_events.py`)

Test the event emission logic extracted from the agent's streaming loop:

- `test_thinking_deltas_yield_start_delta_end`: thinking -> text -> verify ThinkingStart, ThinkingDelta(s), ThinkingEnd, TextDelta
- `test_thinking_end_on_stream_end`: thinking -> finish -> verify ThinkingEnd emitted
- `test_thinking_end_on_tool_call`: thinking -> tool_call_delta -> verify ThinkingEnd emitted
- `test_no_thinking_events_without_thinking_delta`: text only -> no thinking events

---

## Verification

1. `pytest tests/core/test_thinking_events.py -v` — New tests pass
2. `pytest tests/` — No regressions
3. **Manual test** — Set `backend_type: anthropic` with `thinking_budget` in config, ask a complex question, verify:
   - A "Thinking..." panel appears during streaming (collapsed, cyan border)
   - Content streams into it progressively
   - It finalizes to "Thinking" (blue border) when text response begins
   - Click to expand shows full thinking content
