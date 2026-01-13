# Context Window Progress Bar

Real-time context window usage tracking in the TUI status bar.

## Overview

The context window progress bar displays how much of the LLM's context window is being used, updating after each LLM call with **actual token counts** from the provider (not estimates).

```
Status bar format:
/ Streaming | 01:17 [AUTO]                    8.5k ████░░░░░░ 200k
                                               ^    ^         ^
                                               |    |         └── Context limit
                                               |    └── Progress bar (color-coded)
                                               └── Tokens used
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Flow                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  OpenAI API                                                      │
│      │                                                           │
│      │ stream_options: {include_usage: true}                     │
│      ▼                                                           │
│  OpenAIBackend.generate_with_tools_stream_async()                │
│      │                                                           │
│      │ StreamChunk(prompt_tokens=8500, ...)                      │
│      ▼                                                           │
│  CodingAgent.stream_response()                                   │
│      │                                                           │
│      │ yield ContextUpdated(used=8500, limit=200000)             │
│      ▼                                                           │
│  CodingAgentApp._dispatch_event()                                │
│      │                                                           │
│      │ status_bar.update_context(8500, 200000)                   │
│      ▼                                                           │
│  StatusBar._render_context_bar()                                 │
│      │                                                           │
│      └──► "8.5k ████░░░░░░ 200k"                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Files Modified

| File | Changes |
|------|---------|
| `src/llm/base.py` | Added `stream_usage` config flag and token fields to `StreamChunk` |
| `src/llm/openai_backend.py` | Request and capture usage from streaming API |
| `src/core/agent.py` | Emit `ContextUpdated` events with real usage |
| `src/ui/events.py` | Added `ContextUpdated` event type |
| `src/ui/app.py` | Handle `ContextUpdated` events |
| `src/ui/widgets/status_bar.py` | Render context progress bar |

## Implementation Details

### 1. StreamChunk Token Fields (`src/llm/base.py`)

```python
class StreamChunk(BaseModel):
    content: str
    done: bool = False
    # ... existing fields ...

    # Token usage (populated on final chunk when done=True)
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
```

### 2. LLMConfig Stream Usage Flag (`src/llm/base.py`)

```python
class LLMConfig(BaseModel):
    # ... existing fields ...

    # Stream usage tracking (OpenAI-specific, may not work with all providers)
    stream_usage: bool = Field(
        default_factory=lambda: os.getenv("STREAM_USAGE", "true").lower() == "true"
    )
```

**Environment variable:** Set `STREAM_USAGE=false` for providers that don't support `stream_options`.

### 3. OpenAI Backend Usage Capture (`src/llm/openai_backend.py`)

```python
# Conditionally add stream_options (OpenAI-specific)
if getattr(self.config, 'stream_usage', True):
    params["stream_options"] = {"include_usage": True}

# Capture usage from streaming response
async for chunk in stream:
    if hasattr(chunk, 'usage') and chunk.usage:
        prompt_tokens = chunk.usage.prompt_tokens
        completion_tokens = chunk.usage.completion_tokens
        total_tokens = chunk.usage.total_tokens
    # ... process content ...

# Include in final chunk
yield StreamChunk(
    done=True,
    prompt_tokens=prompt_tokens,
    completion_tokens=completion_tokens,
    total_tokens=total_tokens,
)
```

### 4. Agent Event Emission (`src/core/agent.py`)

```python
# After each LLM response completes
if chunk.done:
    if (chunk.prompt_tokens is not None
        and self.context_builder
        and self.context_builder.max_context_tokens > 0):
        yield ContextUpdated(
            used=chunk.prompt_tokens,
            limit=self.context_builder.max_context_tokens,
            pressure_level=self._get_pressure_level(chunk.prompt_tokens),
        )
```

### 5. ContextUpdated Event (`src/ui/events.py`)

```python
@dataclass(frozen=True)
class ContextUpdated:
    """Context window usage updated after each LLM call."""
    used: int           # prompt_tokens from LLM response
    limit: int          # max_context_tokens from config
    pressure_level: str # "green", "yellow", "orange", or "red"
```

### 6. Status Bar Rendering (`src/ui/widgets/status_bar.py`)

```python
def _render_context_bar(self) -> Text:
    # Format: "8.5k ████░░░░░░ 200k"
    used_k = self.context_used / 1000
    limit_k = self.context_limit / 1000
    percent = (self.context_used / self.context_limit) * 100

    # Color coding based on usage
    if percent >= 90:
        bar_style = "red"      # Critical
    elif percent >= 80:
        bar_style = "yellow"   # Warning
    elif percent >= 60:
        bar_style = "cyan"     # Moderate
    else:
        bar_style = "green"    # Healthy
```

## Pressure Levels

| Level | Utilization | Color | Meaning |
|-------|-------------|-------|---------|
| Green | < 70% | Green | Plenty of headroom |
| Yellow | 70-84% | Cyan | Getting full |
| Orange | 85-94% | Yellow | Near limit |
| Red | >= 95% | Red | Critical - compaction needed |

## Why Real Usage vs Estimates?

| Approach | Accuracy | When Available |
|----------|----------|----------------|
| tiktoken estimate | ~85-95% | Before LLM call |
| **LLM response usage** | **100%** | **After LLM call** |

We use **LLM response usage** because:
1. It's the ground truth (provider's actual tokenizer)
2. Updates after each turn (reflects tool results added to context)
3. No estimation drift over long conversations

The tiktoken estimate is still used internally for:
- Pre-flight context budget allocation
- Deciding what to truncate before sending

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAM_USAGE` | `true` | Enable stream usage tracking |
| `CONTEXT_WINDOW` | Provider default | Max context window size |

### Disabling for Incompatible Providers

Some OpenAI-compatible providers (Groq, Together.ai, local LLMs) may not support `stream_options`. Disable with:

```bash
# .env
STREAM_USAGE=false
```

The progress bar will still work using the initial tiktoken estimate, just without per-turn updates.

## Testing

```bash
# Run the TUI
python -m src.cli

# Send a message and observe:
# 1. Progress bar appears after first LLM response
# 2. Updates after each tool call cycle
# 3. Color changes as usage increases
```

## Code Review Fixes Applied

### First Code Review (External)

| Issue | Fix |
|-------|-----|
| P0: API compatibility | Made `stream_options` conditional via config flag |
| P1: Duplicate emission | Removed initial tiktoken estimate emission |
| P1: Null checks | Added guards on `context_builder` access |
| P1: Narrow terminals | Skip progress bar if terminal too narrow |
| P1: Invalid config | Added warning log for invalid `max_context_tokens` |

### Second Code Review (Agent Self-Review)

| Issue | Fix |
|-------|-----|
| P0: `pressure_level` not passed | Added `pressure` param to `update_context()`, stored in reactive attr |
| P1: Inconsistent thresholds | StatusBar now uses agent's pressure level (70/85/95%) instead of local calc |
| P2: Dead code in number formatting | Changed `else` branch to `.2f` for small values |
| P2: Missing input validation | Added validation for negative values, clamping, pressure validation |
| P3: Exception too broad | Narrowed to `(AttributeError, RuntimeError)` |
| P3: Magic number (bar_width) | Kept as-is - fixed width provides consistency |
| ~~P0: Character encoding~~ | FALSE POSITIVE - Textual/Rich handles Unicode properly |
