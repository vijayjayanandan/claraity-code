# Thinking Blocks: A Guide to LLM Reasoning in Streaming

A learning guide for Telus engineers accessing models through the **fuelix LiteLLM proxy**.

For a runnable demo, see [`examples/thinking_demo.py`](../examples/thinking_demo.py).

---

## What Are Thinking Blocks?

Modern LLMs can "think before they speak" — they generate an internal chain-of-thought before producing the final answer. Different providers call this different things:

- **Claude** calls them **thinking blocks**
- **Kimi K2.5** calls it **reasoning**
- **DeepSeek R1** calls it **reasoning_content**

The concept is the same: the model works through the problem step by step, then gives you a polished answer. Some models let you see this reasoning; others keep it hidden.

---

## Two Questions Every Developer Must Answer

When working with thinking blocks, you face two decisions:

### 1. How do I turn it on?

Some models reason by default. Others require you to opt in.

| Model | Reasoning | To enable |
|-------|-----------|-----------|
| Claude (Sonnet 4.5, Opus, etc.) | **Opt-in** | Pass `extra_body` with thinking config |
| Kimi K2.5 | **Always on** | Nothing — reasoning is always in the stream |
| DeepSeek R1 | **Always on** | Nothing — reasoning is always in the stream |
| OpenAI o1/o3/o4-mini | **Always on** | Cannot access reasoning text (only token counts) |

### 2. What do I do with reasoning in multi-turn conversations?

This is where it gets tricky. When you send a follow-up message, do you include the model's reasoning from the previous turn?

| Model | Rule | Why |
|-------|------|-----|
| Kimi K2.5 | **MUST include** | The model expects its reasoning context. Without it, you get a 400 error. |
| DeepSeek R1 | **MUST NOT include** | The API rejects `reasoning_content` in assistant messages. You get a 400 error. |
| Claude (via proxy) | **Don't worry about it** | LiteLLM proxy handles round-tripping automatically. |

Yes, Kimi and DeepSeek have **opposite** requirements. This is the most common source of bugs.

---

## How Streaming Delivers Thinking Blocks

When you stream a response through the fuelix proxy using the OpenAI SDK, each chunk arrives as a `ChoiceDelta` object. Regular text comes through `delta.content`. But where does reasoning go?

### The `model_extra` Gotcha

The OpenAI SDK uses Pydantic v2 with `extra='allow'`. Fields the SDK doesn't know about (like `reasoning` from Kimi) are stored in a hidden `model_extra` dictionary. Here's the trap:

```python
delta = chunk.choices[0].delta

# What you'd expect to work — DOES NOT WORK
hasattr(delta, 'reasoning')          # False!
getattr(delta, 'reasoning', None)    # None!

# What actually works
_extra = getattr(delta, 'model_extra', None) or {}
reasoning = _extra.get('reasoning') or _extra.get('reasoning_content')
```

This is the single most common mistake when implementing thinking block capture. `hasattr` and `getattr` do not see Pydantic v2 extra fields. You **must** go through `model_extra`.

---

## Provider Walkthrough

All examples use the OpenAI SDK through the fuelix LiteLLM proxy.

### Claude — Opt-In Thinking

Claude requires explicit enablement. Pass the thinking configuration via `extra_body`:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://proxy.fuelix.ai/v1",
    api_key="your-api-key",
)

stream = client.chat.completions.create(
    model="claude-sonnet-4-5-20250929",
    messages=[{"role": "user", "content": "Explain quantum entanglement"}],
    max_tokens=16384,
    stream=True,
    temperature=1,        # REQUIRED when thinking is enabled
    extra_body={
        "thinking": {
            "type": "enabled",
            "budget_tokens": 10000,  # Max tokens the model can use for thinking
        }
    },
)

for chunk in stream:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta

    if delta.content:
        print(delta.content, end="")

    _extra = getattr(delta, 'model_extra', None) or {}
    reasoning = _extra.get('reasoning') or _extra.get('reasoning_content')
    if reasoning:
        print(f"[THINKING] {reasoning}", end="")
```

**Constraints when thinking is enabled:**
- `temperature` must be `1` (Claude rejects other values)
- `top_p` must not be sent (Claude rejects `temperature` + `top_p` together)
- `budget_tokens` must be less than `max_tokens`

**Multi-turn:** No special handling needed — the proxy manages thinking block round-tripping.

### Kimi K2.5 — Always-On Reasoning (Must Echo Back)

Kimi K2.5 always reasons. The reasoning text arrives via `model_extra['reasoning']`:

```python
stream = client.chat.completions.create(
    model="moonshot/kimi-k2-0711",
    messages=[{"role": "user", "content": "What is 15% of 240?"}],
    max_tokens=8192,
    stream=True,
)

reasoning_buffer = ""
text_buffer = ""

for chunk in stream:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta

    if delta.content:
        text_buffer += delta.content

    _extra = getattr(delta, 'model_extra', None) or {}
    reasoning = _extra.get('reasoning') or _extra.get('reasoning_content')
    if reasoning:
        reasoning_buffer += reasoning
```

**Multi-turn — the critical part.** When sending the next message, you must include the accumulated reasoning as `reasoning_content` on the assistant message:

```python
messages = [
    {"role": "user", "content": "What is 15% of 240?"},
    {
        "role": "assistant",
        "content": text_buffer,
        "reasoning_content": reasoning_buffer,   # REQUIRED — omitting this causes 400 error
    },
    {"role": "user", "content": "Now double that result"},
]
```

Without `reasoning_content`, Kimi returns:
> `"thinking is enabled but reasoning_content is missing in assistant tool call message at index N"`

### DeepSeek R1 — Always-On Reasoning (Must NOT Echo Back)

DeepSeek R1 also always reasons, but uses `reasoning_content` in `model_extra`:

```python
stream = client.chat.completions.create(
    model="deepseek/deepseek-reasoner",
    messages=[{"role": "user", "content": "Prove that sqrt(2) is irrational"}],
    max_tokens=8192,
    stream=True,
)
```

Capture reasoning the same way as Kimi. But for multi-turn, **strip it**:

```python
messages = [
    {"role": "user", "content": "Prove that sqrt(2) is irrational"},
    {
        "role": "assistant",
        "content": text_buffer,
        # DO NOT include reasoning_content — DeepSeek returns 400
    },
    {"role": "user", "content": "Now prove sqrt(3) is irrational"},
]
```

### OpenAI Reasoning Models (o1, o3, o4-mini)

These models reason internally, but the Chat Completions API does **not** expose the reasoning text. You only get a `reasoning_tokens` count in the usage stats. If you need to see reasoning text, OpenAI's newer Responses API can provide reasoning summaries, but LiteLLM proxy uses the Chat Completions API.

---

## Common Mistakes

**1. Using `hasattr`/`getattr` for reasoning fields**
These don't work with Pydantic v2 extra fields. Always use `model_extra`. See the gotcha section above.

**2. Sending `temperature` and `top_p` together with Claude thinking**
Claude rejects this combination. Remove `top_p` from your params when thinking is enabled.

**3. Echoing back reasoning to DeepSeek (or forgetting to echo to Kimi)**
These are opposite requirements. A common pattern is to have a per-model flag:

```python
ECHO_BACK_REASONING = {
    "kimi": True,      # Must include reasoning_content
    "deepseek": False,  # Must NOT include reasoning_content
    "claude": False,    # Proxy handles it
}
```

**4. Setting Anthropic SDK base_url with `/v1`**
The Anthropic SDK appends `/v1/messages` automatically. If your base_url already ends in `/v1`, you get `/v1/v1/messages` (404). Use `https://proxy.fuelix.ai` not `https://proxy.fuelix.ai/v1`.

**5. Setting `budget_tokens` >= `max_tokens`**
The thinking budget must be strictly less than `max_tokens`. If equal or greater, the API rejects the request.

**6. Kimi parallel tool calls with reasoning**
Kimi K2.5 can be unreliable with parallel tool calls when reasoning is active. If using tool calling, set `parallel_tool_calls=False`.
