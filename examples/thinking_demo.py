"""
Thinking Blocks Demo — Streaming Reasoning from LLMs

Demonstrates how to enable, capture, and handle thinking/reasoning blocks
across three providers through the fuelix LiteLLM proxy:

  1. Claude Sonnet 4.5  — Opt-in thinking, proxy handles multi-turn
  2. Kimi K2.5          — Always-on reasoning, MUST echo back in multi-turn
  3. DeepSeek R1        — Always-on reasoning, MUST NOT echo back in multi-turn

Usage:
    export FUELIX_API_KEY="your-key"
    python examples/thinking_demo.py              # Run all demos
    python examples/thinking_demo.py claude        # Run only Claude demo
    python examples/thinking_demo.py kimi          # Run only Kimi demo
    python examples/thinking_demo.py deepseek      # Run only DeepSeek demo

Requirements:
    pip install openai

See also: docs/THINKING_BLOCKS.md
"""

import os
import sys

from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROXY_BASE_URL = os.environ.get("FUELIX_BASE_URL", "https://proxy.fuelix.ai/v1")
API_KEY = os.environ.get("FUELIX_API_KEY", "")

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
KIMI_MODEL = "moonshot/kimi-k2-0711"
DEEPSEEK_MODEL = "deepseek/deepseek-reasoner"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_client() -> OpenAI:
    if not API_KEY:
        print("[ERROR] Set FUELIX_API_KEY environment variable first.")
        sys.exit(1)
    return OpenAI(base_url=PROXY_BASE_URL, api_key=API_KEY)


def stream_and_capture(client: OpenAI, model: str, messages: list, **kwargs) -> dict:
    """Stream a chat completion and return captured text + reasoning.

    This is the core pattern: iterate chunks, pull text from delta.content,
    pull reasoning from model_extra (the Pydantic v2 gotcha).

    Returns dict with keys: text, reasoning, messages (updated history).
    """
    params = dict(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=kwargs.pop("max_tokens", 8192),
    )
    params.update(kwargs)

    stream = client.chat.completions.create(**params)

    text_buf = ""
    reasoning_buf = ""

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        # Regular text content
        if delta.content:
            text_buf += delta.content
            print(delta.content, end="", flush=True)

        # Reasoning / thinking content
        # IMPORTANT: Pydantic v2 stores unknown fields in model_extra.
        # hasattr(delta, 'reasoning') returns False even when the field exists.
        _extra = getattr(delta, "model_extra", None) or {}
        reasoning = _extra.get("reasoning") or _extra.get("reasoning_content")

        if reasoning:
            reasoning_buf += reasoning
            # Print reasoning in a distinct style
            print(f"\033[2m{reasoning}\033[0m", end="", flush=True)  # dim text

    print()  # newline after stream ends

    return {"text": text_buf, "reasoning": reasoning_buf}


def print_banner(title: str):
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def print_section(label: str):
    print(f"\n--- {label} ---")


# ---------------------------------------------------------------------------
# Demo 1: Claude — Opt-in thinking, proxy handles multi-turn
# ---------------------------------------------------------------------------

def demo_claude(client: OpenAI):
    print_banner("CLAUDE SONNET 4.5 — Opt-In Thinking")

    print("""
Claude requires explicit opt-in to enable thinking blocks.
We pass extra_body with thinking config. Key constraints:
  - temperature MUST be 1
  - top_p MUST NOT be sent
  - budget_tokens < max_tokens

Multi-turn: the proxy handles round-tripping automatically.
""")

    # Turn 1: Enable thinking
    messages = [
        {"role": "user", "content": "What is the sum of the first 10 prime numbers? Show your reasoning."}
    ]

    print_section("Turn 1 — Streaming with thinking enabled")
    result = stream_and_capture(
        client, CLAUDE_MODEL, messages,
        temperature=1,       # Required when thinking is enabled
        max_tokens=16384,
        extra_body={
            "thinking": {
                "type": "enabled",
                "budget_tokens": 10000,
            }
        },
    )

    print(f"\n[Captured {len(result['reasoning'])} chars of thinking, {len(result['text'])} chars of text]")

    # Turn 2: Follow-up — no special handling needed
    messages.append({"role": "assistant", "content": result["text"]})
    messages.append({"role": "user", "content": "Now what is the sum of the first 15 prime numbers?"})

    print_section("Turn 2 — Follow-up (proxy handles thinking round-trip)")
    result2 = stream_and_capture(
        client, CLAUDE_MODEL, messages,
        temperature=1,
        max_tokens=16384,
        extra_body={
            "thinking": {
                "type": "enabled",
                "budget_tokens": 10000,
            }
        },
    )

    print(f"\n[Captured {len(result2['reasoning'])} chars of thinking, {len(result2['text'])} chars of text]")
    print("\n[OK] Claude multi-turn with thinking works — no special echo-back code needed.")


# ---------------------------------------------------------------------------
# Demo 2: Kimi K2.5 — Always-on reasoning, MUST echo back
# ---------------------------------------------------------------------------

def demo_kimi(client: OpenAI):
    print_banner("KIMI K2.5 — Always-On Reasoning (MUST Echo Back)")

    print("""
Kimi K2.5 always reasons — no opt-in needed. The reasoning text
arrives via model_extra['reasoning'] in each streaming chunk.

Multi-turn: you MUST include 'reasoning_content' on the assistant
message when sending the next turn. Without it, Kimi returns 400:
  "thinking is enabled but reasoning_content is missing..."
""")

    # Turn 1
    messages = [
        {"role": "user", "content": "What is 15% of 240?"}
    ]

    print_section("Turn 1 — Capturing reasoning from stream")
    result = stream_and_capture(client, KIMI_MODEL, messages)

    print(f"\n[Captured {len(result['reasoning'])} chars of reasoning, {len(result['text'])} chars of text]")

    # Turn 2: MUST include reasoning_content in the assistant message
    messages.append({
        "role": "assistant",
        "content": result["text"],
        "reasoning_content": result["reasoning"],   # <-- REQUIRED for Kimi
    })
    messages.append({"role": "user", "content": "Now double that result."})

    print_section("Turn 2 — With reasoning_content echoed back")
    result2 = stream_and_capture(client, KIMI_MODEL, messages)

    print(f"\n[Captured {len(result2['reasoning'])} chars of reasoning, {len(result2['text'])} chars of text]")
    print("\n[OK] Kimi multi-turn works because we echoed back reasoning_content.")

    # Demonstrate the failure case (optional, commented out to avoid errors)
    # print_section("Turn 2 — WITHOUT reasoning_content (would fail)")
    # bad_messages = [
    #     {"role": "user", "content": "What is 15% of 240?"},
    #     {"role": "assistant", "content": result["text"]},  # Missing reasoning_content!
    #     {"role": "user", "content": "Now double that result."},
    # ]
    # stream_and_capture(client, KIMI_MODEL, bad_messages)  # 400 error


# ---------------------------------------------------------------------------
# Demo 3: DeepSeek R1 — Always-on reasoning, MUST NOT echo back
# ---------------------------------------------------------------------------

def demo_deepseek(client: OpenAI):
    print_banner("DEEPSEEK R1 — Always-On Reasoning (MUST NOT Echo Back)")

    print("""
DeepSeek R1 always reasons, like Kimi. The reasoning text arrives
via model_extra['reasoning_content'] in each streaming chunk.

Multi-turn: you MUST NOT include 'reasoning_content' in the
assistant message. DeepSeek rejects it with a 400 error.

This is the OPPOSITE of Kimi's requirement.
""")

    # Turn 1
    messages = [
        {"role": "user", "content": "Is 97 a prime number?"}
    ]

    print_section("Turn 1 — Capturing reasoning from stream")
    result = stream_and_capture(client, DEEPSEEK_MODEL, messages)

    print(f"\n[Captured {len(result['reasoning'])} chars of reasoning, {len(result['text'])} chars of text]")

    # Turn 2: DO NOT include reasoning_content
    messages.append({
        "role": "assistant",
        "content": result["text"],
        # NO reasoning_content — DeepSeek would return 400
    })
    messages.append({"role": "user", "content": "What about 91?"})

    print_section("Turn 2 — WITHOUT reasoning_content (required for DeepSeek)")
    result2 = stream_and_capture(client, DEEPSEEK_MODEL, messages)

    print(f"\n[Captured {len(result2['reasoning'])} chars of reasoning, {len(result2['text'])} chars of text]")
    print("\n[OK] DeepSeek multi-turn works because we stripped reasoning_content.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = get_client()

    # Parse which demo to run
    demos = {
        "claude": demo_claude,
        "kimi": demo_kimi,
        "deepseek": demo_deepseek,
    }

    if len(sys.argv) > 1:
        name = sys.argv[1].lower()
        if name not in demos:
            print(f"Unknown demo: {name}")
            print(f"Available: {', '.join(demos.keys())}")
            sys.exit(1)
        demos[name](client)
    else:
        # Run all demos
        for name, demo_fn in demos.items():
            try:
                demo_fn(client)
            except Exception as e:
                print(f"\n[ERROR] {name} demo failed: {e}")
                print("Continuing with next demo...\n")


if __name__ == "__main__":
    main()
