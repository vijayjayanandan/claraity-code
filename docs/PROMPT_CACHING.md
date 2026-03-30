# Prompt Caching

## Overview

Prompt caching reduces the cost and latency of LLM API calls by reusing previously processed prompt prefixes. When the beginning of a prompt matches a prior request, the provider can serve those tokens from cache instead of reprocessing them from scratch.

This matters for ClarAIty because the agent's tool loop sends many requests per session, each sharing the same system prompt and a growing conversation history prefix. Without caching, the provider re-encodes the entire prefix on every call. With caching:

- **Cache reads** are billed at 10% of the normal input token rate (90% savings).
- **Cache writes** incur a 25% surcharge on the first occurrence.
- **Net effect** across a typical session: 30-60% reduction in input token costs, plus measurably lower latency on cache-hit turns.

## How It Works

### Two-Breakpoint Strategy

The implementation places two cache breakpoints (BP1 and BP2) in the message list sent to the LLM API. Everything before a breakpoint is eligible for cache reuse on subsequent calls.

```
Messages sent to LLM:
  [system prompt]        <-- BP1 (static across session)
  [user message 1]
  [assistant response 1]
  [tool_call]
  [tool_result]
  [assistant response 2] <-- BP2 (conversation history prefix)
  [user message N]       <-- new content (never cached)
```

**BP1 -- System prompt.** The first message (role=system) is identical across every turn in a session. Caching it avoids re-encoding the system prompt plus tool definitions on every call.

**BP2 -- Conversation history prefix.** Placed on a message near the end of the history (second-to-last with content). As the conversation grows, more of the prefix can be served from cache on each successive turn.

### Provider Differences

- **OpenAI models** (GPT-4o, GPT-4.1, etc.) -- Caching is automatic. The API detects repeated prefixes without any special markup. Our code passes messages through unchanged.
- **Anthropic models** (Claude) -- Caching requires explicit `cache_control: {"type": "ephemeral"}` markers on content blocks. Our code injects these markers at BP1 and BP2 before sending the request.

## Architecture

### Files and Classes

| File | Component | Role |
|------|-----------|------|
| `src/llm/cache_tracker.py` | `CacheTracker` | Accumulates per-session cache metrics (reads, writes, hits, total tokens) |
| `src/llm/openai_backend.py` | `_apply_cache_control()` | Injects `cache_control` breakpoints for Anthropic models; no-op for others |
| `src/llm/openai_backend.py` | `_add_cache_control_to_message()` | Converts a message's content to content-blocks format with `cache_control` |
| `src/llm/openai_backend.py` | `_extract_cached_tokens()` | Extracts `cached_tokens` from the usage object's `prompt_tokens_details` |
| `src/llm/openai_backend.py` | `_is_anthropic_model()` | Returns `True` if the configured model name contains "claude" |
| `src/llm/openai_backend.py` | `log_cache_summary()` | Delegates to `CacheTracker.format_summary()` and logs the result |
| `src/llm/base.py` | `LLMResponse.cached_tokens` | Field on the response model for cached prompt token count |
| `src/llm/base.py` | `StreamChunk.cached_tokens` | Same field on the streaming chunk model |
| `src/core/agent.py` | `shutdown()` | Calls `llm.log_cache_summary()` on agent teardown |
| `src/ui/app.py` | `on_unmount()` | Calls `agent.llm.log_cache_summary()` directly during TUI teardown |
| `src/cli.py` | exit + Ctrl+C paths | Both call `agent.shutdown()`, which triggers the cache summary log |

### Data Flow

```
API Response
  |
  v
_extract_cached_tokens(usage) --> cached token count
  |
  v
cache_tracker.record(usage)   --> accumulates session totals
  |
  v
logger.info("[CACHE] ...")    --> per-turn log line
  :
  : (on session exit)
  v
log_cache_summary()           --> session-level summary log
```

### Per-Turn Logging (7 Methods)

Every method in `OpenAIBackend` that receives a response or final stream chunk records cache metrics and emits a `[CACHE]` log line:

| Method (line) | Mode |
|---------------|------|
| `generate()` (208) | Sync, no tools |
| `generate_stream()` (277) | Sync streaming, no tools |
| `generate_with_tools()` (391) | Sync, with tools |
| `generate_with_tools_stream()` (525) | Sync streaming, with tools |
| `generate_with_tools_stream_async()` (749) | Async streaming, with tools |
| `generate_provider_deltas()` (980) | Sync `ProviderDelta` streaming |
| `generate_provider_deltas_async()` (1123) | Async `ProviderDelta` streaming |

The agent's primary code paths use the async and `ProviderDelta` methods. The sync methods are used by CLI mode and subagents.

## Breakpoint Placement

### BP1: System Prompt

Applied to the first message if its role is `"system"`. The system prompt is static for the entire session (same instructions, same tool definitions), making it an ideal cache target.

```python
# In _apply_cache_control():
if result[0].get("role") == "system":
    result[0] = self._add_cache_control_to_message(result[0])
```

The `_add_cache_control_to_message()` method converts the message content to Anthropic's content-blocks format:

```python
# String content becomes:
{"content": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}

# List content gets cache_control on the last block:
{"content": [...existing_blocks, {**last_block, "cache_control": {"type": "ephemeral"}}]}
```

Messages with `content=None` (tool-call-only assistant messages) are returned unchanged.

### BP2: Conversation History Prefix

Applied to the second-to-last message that has content. The code walks backward from the penultimate position, skipping any assistant messages that have `content=None` (these are tool-call-only messages that cannot carry a `cache_control` marker):

```python
# In _apply_cache_control():
if len(result) >= 3:
    for i in range(len(result) - 2, 0, -1):
        if result[i].get("content") is not None:
            result[i] = self._add_cache_control_to_message(result[i])
            break
```

This ensures the longest possible conversation prefix is cached. The final message (typically the latest user input) is excluded because it changes every turn.

## Savings Calculation

`CacheTracker.summary()` computes the effective cost reduction using a 3-bucket formula.

**Bucket definitions:**

| Bucket | Tokens | Cost Multiplier |
|--------|--------|-----------------|
| Cache reads | Tokens served from cache | 0.1x (90% discount) |
| Cache writes | Tokens written to cache | 1.25x (25% surcharge) |
| Uncached | Remaining tokens | 1.0x (full price) |

**Formula:**

```
uncached_tokens = total_input - cache_read - cache_write
cost_without_caching = total_input * 1.0
cost_with_caching = (cache_read * 0.1) + (cache_write * 1.25) + (uncached * 1.0)
savings_pct = (cost_without - cost_with) / cost_without * 100
```

The summary also tracks hit rate (percentage of calls that had any cache read tokens).

## Provider Compatibility

| Provider / Model | Caching Mechanism | Code Changes Needed | FuelIX Proxy Support |
|------------------|-------------------|---------------------|----------------------|
| OpenAI (GPT-4o, GPT-4.1, etc.) | Automatic server-side | None -- prefix matching is implicit | Works: `prompt_tokens_details.cached_tokens` returned |
| Anthropic (Claude 3.5/3.7/4) | Explicit `cache_control` markers | Yes -- `_apply_cache_control()` injects markers | Works: FuelIX passes markers through to Anthropic |
| Kimi K2.5 | Unknown at proxy level | None | `prompt_tokens_details` returns `null` -- cannot confirm caching status |

**Note on FuelIX:** The codebase accesses all models through an OpenAI-compatible proxy at `https://proxy.fuelix.ai/v1`. Anthropic models are accessed via this proxy using the OpenAI SDK, which is why `cache_control` markers must be injected into the OpenAI message format rather than using Anthropic's native SDK.

## Monitoring

### Per-Turn Cache Log

Every LLM call emits a `[CACHE]` log line to `.claraity/logs/app.jsonl`:

```json
{"level": "INFO", "logger": "llm.openai_backend", "message": "[CACHE] prompt=4523 cached=3200"}
```

To view per-turn cache metrics:

```bash
python -m src.observability.log_query --search "[CACHE]" --tail 20
```

### Session Summary

On clean exit, a `[CACHE SUMMARY]` line is logged:

```json
{"level": "INFO", "logger": "llm.openai_backend", "message": "[CACHE SUMMARY] 12 calls | 9 cache hits (75.0%) | 38,400 tokens served from cache | ~42.3% effective input cost reduction"}
```

To find session summaries:

```bash
python -m src.observability.log_query --search "[CACHE SUMMARY]"
```

### Interpreting Results

- **Hit rate > 60%** -- Caching is working well. The system prompt and conversation prefix are being reused effectively.
- **Hit rate 30-60%** -- Partial caching. Likely affected by load balancer routing (see Known Limitations).
- **Hit rate 0%** -- Either the provider does not support caching, the proxy is not passing through cache markers, or all requests are hitting different backend servers.
- **cached=0 on turn 1** -- Expected. The first turn is always a cache write (or an implicit cache miss on OpenAI).

## Diagnostic Script

The file `test_prompt_caching.py` in the project root is a standalone diagnostic that simulates the agent's multi-turn tool loop to verify caching behavior for any model.

### Usage

```bash
# Use the default model from .claraity/config.yaml
python test_prompt_caching.py

# Override with a specific model
python test_prompt_caching.py gpt-4o
python test_prompt_caching.py claude-3-7-sonnet-20250219
```

### What It Does

1. Loads configuration from `.claraity/config.yaml` (base URL, model) and API key from the OS keyring or environment.
2. Builds a realistic system prompt padded to exceed 1024 tokens (the minimum for most caching implementations) plus 5 tool definitions.
3. Runs 5 sequential turns that mirror the agent's tool loop:
   - Turn 1: System + user message (cache write)
   - Turn 2: Same prefix + tool_call + tool_result (should cache-hit the prefix)
   - Turn 3: Same prefix + assistant + user follow-up
   - Turn 4: Same prefix + another tool_call + tool_result
   - Turn 5: Same prefix + user follow-up
4. Prints a summary table showing prompt tokens, cached tokens, and whether each turn was a cache hit.
5. For Anthropic models, it automatically adds `cache_control` markers to the system message (matching the agent's behavior). For OpenAI models, it relies on automatic caching.

### Example Output (Anthropic via FuelIX)

```
Turn       Prompt   Cache Write   Cache Read   Hit?
---------- -------- ------------- ------------ ------
Turn 1         4200          4200            0     no
Turn 2         4800             0         4200    YES
Turn 3         5100             0         4800    YES
Turn 4         5500             0         5100    YES
Turn 5         5800             0         5500    YES

Cache hit rate: 4/5 turns (80% of turns after first)
```

## Known Limitations

### FuelIX Load Balancer Causes Cache Misses

The FuelIX proxy load-balances requests across multiple backend servers. If consecutive requests from the same session are routed to different servers, the cache is not shared between them. This produces approximately 40-60% cache miss rates in practice. The caching still provides net savings because the turns that do hit cache save significantly.

### generate_stream() StreamChunk Missing cached_tokens

The `generate_stream()` method (line 277) records `[CACHE]` log lines and calls `cache_tracker.record()`, but the `StreamChunk` objects it yields do not carry `cached_tokens` values. In practice this method is not used by the agent's main tool loop (which uses `generate_with_tools_stream_async` or `generate_provider_deltas_async`), so the gap has no real impact.

### Session Summary Requires Clean Exit

The `[CACHE SUMMARY]` log is only emitted when:

- **TUI mode:** `on_unmount()` fires during normal app teardown.
- **CLI mode:** `agent.shutdown()` is called from the `exit`/`quit` handler or the `KeyboardInterrupt` (Ctrl+C) handler.

If the process is killed with `SIGKILL` (kill -9) or crashes before reaching the shutdown path, the session summary is lost. Per-turn `[CACHE]` log lines are still available since they are written immediately.

### Minimum Token Threshold

Most providers require the cached prefix to exceed a minimum token count (typically 1024 tokens for OpenAI, 1024 for Anthropic) before caching activates. The agent's system prompt plus tool definitions easily exceed this threshold in practice, but very short system prompts in test scenarios may not trigger caching.
