# Prompt Caching for Claude Models: Implementation Guide

> **Audience:** Engineers calling Claude APIs via FuelIX.
> **Read time:** 5 minutes.
> **Outcome:** Understand what prompt caching is, how to enable it (~50 lines of code), and the cost savings you can expect.

---

## The Problem

Every time you call the LLM API, the provider processes your entire prompt from scratch. In an agentic loop where you call the LLM 10-20 times per task, 90%+ of the prompt is identical across calls -- the system prompt, conversation history, and tool definitions don't change. You pay to re-process those same tokens on every call.

**Prompt caching tells the provider: "You've already seen this prefix. Don't reprocess it. Start from where it changes."**

> **Note:** OpenAI models (GPT-4o, GPT-4.1) have prompt caching enabled automatically -- no code changes needed. Claude models require explicit cache markers, which is what this guide covers.

---

## The Impact

| Metric | Without Caching | With Caching |
|--------|----------------|--------------|
| Cost per cached input token | 1.0x | **0.1x** (90% discount) |
| First-call write penalty | N/A | 1.25x (25% surcharge, one-time) |
| Typical session savings | Baseline | **~40-50% input cost reduction** |

The savings compound with conversation length. By turn 5, 83% of input tokens are served from cache. By turn 10+, the ratio is even higher.

---

## How It Works

You place **cache breakpoints** on specific messages in your prompt. These tell the provider: "Cache everything up to and including this message."

```
CALL 1 (cache miss -- first time):
  [System prompt]   <-- BP1 (written to cache, 1.25x write cost)
  [User msg 1]
  [Assistant msg 1]  <-- BP2 (written to cache)
  [User msg 2]           new input, processed at full price

CALL 2 (cache hit):
  [System prompt]   <-- BP1 (cache HIT -- 0.1x cost)
  [User msg 1]
  [Assistant msg 1]
  [Tool result 1]
  [Assistant msg 2]  <-- BP2 (cache HIT -- 0.1x cost)
  [User msg 3]           only this is processed at full price
```

---

## The Two-Breakpoint Strategy

Place exactly two cache breakpoints. They capture 90%+ of the benefit with minimal complexity.

**BP1: System Prompt** -- First message in the messages array (role: system). Identical on every call. Cache it once, reuse it for the entire session.

**BP2: Second-to-Last Message** -- Walk backwards from the end, skip the final message (new user input that changes every turn), and mark the first message with content. This caches the entire conversation history prefix.

---

## Implementation (Copy-Paste Ready)

All code uses the **OpenAI SDK** format via FuelIX. The `cache_control` markers pass through the proxy's translation layer to Anthropic's API.

### Step 1: Mark Messages with Cache Control

```python
def apply_cache_control(messages: list[dict]) -> list[dict]:
    """Apply the two-breakpoint strategy to a message list.

    BP1: System prompt (first message) - static across all calls.
    BP2: Last message with content before the new user input -
         caches the conversation history prefix.
    """
    if len(messages) < 2:
        return messages

    result = [{**m} for m in messages]  # shallow copy - never mutate originals

    # BP1: Mark the system prompt
    if result[0].get("role") == "system":
        result[0] = _add_cache_marker(result[0])

    # BP2: Walk backwards from second-to-last, find last message with content.
    # We skip the final message (new user input) since it changes every turn.
    if len(result) >= 3:
        for i in range(len(result) - 2, 0, -1):
            if result[i].get("content") is not None:
                result[i] = _add_cache_marker(result[i])
                break

    return result
```

### Step 2: Add the Marker to a Message

```python
def _add_cache_marker(msg: dict) -> dict:
    """Add cache_control: {"type": "ephemeral"} to a message."""
    msg = {**msg}
    content = msg.get("content")

    if content is None:
        return msg

    # Tool role: add as sibling field (required for proxy compatibility)
    if msg.get("role") == "tool":
        msg["cache_control"] = {"type": "ephemeral"}
        return msg

    # String content: convert to Anthropic content-blocks format
    if isinstance(content, str):
        msg["content"] = [{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"},
        }]
    # List content: mark the last block
    elif isinstance(content, list) and content:
        content = [{**block} for block in content]
        content[-1]["cache_control"] = {"type": "ephemeral"}
        msg["content"] = content

    return msg
```

### Step 3: Integrate into Your LLM Call

```python
from openai import OpenAI

client = OpenAI(api_key="sk-...", base_url="https://proxy.fuelix.ai/v1")

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "first message"},
    {"role": "assistant", "content": "first response"},
    {"role": "user", "content": "second message"},  # new input
]

# Add cache breakpoints before every LLM call
cached_messages = apply_cache_control(messages)

response = client.chat.completions.create(
    model="claude-sonnet-4-20250514",
    messages=cached_messages,
    max_tokens=1024,
)
```

---

## What the API Call Actually Looks Like

After `apply_cache_control()` transforms your messages, here is the exact payload sent to the LLM. This is Turn 5 of a 5-turn conversation -- BP1 on the system prompt, BP2 on the assistant response at index 8, new user input at index 9 untouched:

```
client.chat.completions.create(
    model="claude-sonnet-4-20250514",
    max_tokens=300,
    messages=[
        {
            "role": "system",
            "content": [                              <-- BP1: string converted to content blocks
                {
                    "type": "text",
                    "text": "You are a senior software engineer AI assistant...(3987 chars)",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        },
        {
            "role": "user",
            "content": "I have a Python Flask API that handles user authentication..."
        },
        {
            "role": "assistant",
            "content": "## Critical Security Issues\n\nYour current approach has...(1072 chars)"
        },
        {
            "role": "user",
            "content": "Good points. Now I want to add rate limiting..."
        },
        {
            "role": "assistant",
            "content": "## Rate Limiting Strategy\n\n**Use Redis** for production...(990 chars)"
        },
        {
            "role": "user",
            "content": "Let's go with Redis. Can you write the rate limiting middleware?..."
        },
        {
            "role": "assistant",
            "content": "## Redis-Based Rate Limiting Middleware\n\n```python...(1059 chars)"
        },
        {
            "role": "user",
            "content": "Now I need to add refresh token rotation..."
        },
        {
            "role": "assistant",
            "content": [                              <-- BP2: string converted to content blocks
                {
                    "type": "text",
                    "text": "## Refresh Token Rotation Implementation\n\n...(1086 chars)",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        },
        {
            "role": "user",                           <-- New input: no cache marker
            "content": "One more thing - I need to add audit logging for all auth events..."
        }
    ]
)
```

**Key observations:**
- Messages with breakpoints (index 0 and 8): `content` is converted from a string to content blocks with `cache_control`
- All other messages: `content` stays as a plain string
- BP2 moves forward each turn: index 4 on Turn 3, index 6 on Turn 4, index 8 on Turn 5
- Result: 83% of input tokens served from cache on this call

---

## Tool Call Handling

In an agentic loop, the LLM calls tools and the results become part of the conversation. The same `apply_cache_control()` function handles this automatically:

```python
cached_messages = apply_cache_control([
    {"role": "system", "content": "You are a senior software engineer..."},
    {"role": "user", "content": "Read the auth module and check for SQL injection"},
    {"role": "assistant", "content": None, "tool_calls": [...]},   # content is None
    {"role": "tool", "tool_call_id": "call_abc123", "content": "def login(...):\n    ..."},
    {"role": "user", "content": "Now fix the vulnerability you found"},
])

# Result:
# [0] system    -> BP1 (content blocks with cache_control)
# [2] assistant -> skipped (content is None)
# [3] tool      -> BP2 (cache_control added as SIBLING field, content stays as string)
# [4] user      -> unchanged (new input)
```

**Important:** Tool messages require `cache_control` as a **sibling field** on the message object, not inside content blocks. This is required for the FuelIX proxy translation layer. The `_add_cache_marker` function handles this automatically.

---

## Common Pitfalls

**1. Don't mutate original messages.** Always copy before adding markers. The same message objects get reused across calls -- adding `cache_control` in-place corrupts them.

**2. Tool messages need special handling.** `cache_control` must be a sibling field, not inside content blocks:
```python
# WRONG - breaks proxy translation
msg["content"] = [{"type": "text", "text": result, "cache_control": {"type": "ephemeral"}}]

# RIGHT
msg["cache_control"] = {"type": "ephemeral"}
```

**3. Minimum token threshold.** Claude requires at least 1,024 tokens in the cached prefix for caching to activate. System prompts shorter than this will not trigger caching.

---

## Try It Yourself

Two working demo scripts are included alongside this document:

**Python:** `prompt_caching_demo.py` -- requires `pip install openai`

**Java:** `PromptCachingDemo.java` -- requires Java 11+ (no external dependencies)

Both scripts run the same 5-turn conversation twice (without caching, then with caching) and print a side-by-side cost comparison. You will be prompted for your API key, base URL, and model.

The Python demo also generates a **transaction log file** that shows the exact API call on every turn -- including the full messages array with `cache_control` fields visible. Open this log to see precisely how breakpoints are placed and how the cached portion grows with each turn.
