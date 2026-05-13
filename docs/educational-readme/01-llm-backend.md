# Chapter 1: The Seed -- A Raw LLM Call

> **The problem:** A language model on its own just predicts the next word. It can answer questions, but it cannot *do* anything. It has no memory of what happened before, no access to your files, no ability to run code. It is, in essence, a very sophisticated autocomplete.

---

## What is a Chat Completion?

At its core, every AI assistant -- including ClarAIty -- is built on one simple primitive:

**You send a list of messages. The model sends one back.**

That's it. The raw API call looks like this:

```python
response = openai.chat.completions.create(
    model="gpt-5.4",
    messages=[
        {"role": "system",  "content": "You are a helpful coding assistant."},
        {"role": "user",    "content": "What is a Python list?"},
    ]
)
print(response.choices[0].message.content)
```

Three roles. That's the entire vocabulary:
- `system` -- sets the rules and personality
- `user` -- the human's message
- `assistant` -- the model's reply

Everything an AI agent does -- every file it reads, every command it runs, every plan it makes -- starts with this call.

---

## The Parameters That Matter

When ClarAIty calls an LLM, it passes several key parameters (`src/llm/base.py`):

| Parameter | What it does | Why it matters |
|-----------|-------------|----------------|
| `model_name` | Which AI model to use (e.g. `gpt-5.4`, `claude-sonnet-4-5`) | Different models have different strengths and context window sizes |
| `temperature` | How creative vs deterministic the output is (0.0 = deterministic, 1.0 = creative) | Coding tasks need lower temperature -- you want consistent, correct code |
| `max_tokens` | Maximum length of the response | Prevents runaway responses |
| `context_window` | How much total text the model can "see" at once | The fundamental constraint every agent must manage |
| `stream` | Whether to receive the response word-by-word or all at once | Streaming makes the UI feel responsive -- you see output as it's generated |

---

## The Response

The model returns:
- **`content`** -- the text reply (may be empty if the model wants to use a tool instead)
- **`tool_calls`** -- a list of tools the model wants to invoke (more on this in Chapter 3)
- **`finish_reason`** -- why the model stopped: `"stop"` (natural end), `"tool_calls"` (wants to use a tool), `"length"` (hit max_tokens)
- **Token usage** -- how many tokens were consumed (this is how you're billed, and how you track context window usage)

---

## Two Providers, One Interface

ClarAIty supports multiple LLM providers through a single abstract interface (`src/llm/base.py` -- `LLMBackend`):

```
LLMBackend (abstract)
├── OpenAIBackend   -- OpenAI, local models (Ollama, vLLM, LM Studio)
└── AnthropicBackend -- Claude models (native API)
```

This means you can swap the underlying model without changing anything else in the agent. The rest of the system -- context building, tool calling, sessions -- doesn't care which provider is underneath.

> **Key insight:** The LLM is just a function. `messages in -> message out`. The entire complexity of an AI coding agent is about *what you put into that function* and *what you do with what comes out*.

---

## What's Missing (Why This Isn't an Agent Yet)

A raw chat completion has three fatal limitations for a coding agent:

1. **No memory** -- every call starts fresh. The model has no idea what was said before unless you include it in `messages`.
2. **No actions** -- it can *describe* how to write a file, but it can't actually write one.
3. **No judgement** -- it will happily answer even if it's wrong, and won't know when to stop.

The remaining chapters are the story of solving each of these problems.

---

*Source files: `src/llm/base.py`, `src/llm/openai_backend.py`, `src/llm/anthropic_backend.py`, `src/llm/config_loader.py`*
