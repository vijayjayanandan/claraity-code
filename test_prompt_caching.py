"""
Prompt Caching Diagnostic Script
=================================
Simulates how ClarAIty agent sends LLM requests to verify prompt caching
through the FuelIX proxy for both OpenAI and Anthropic models.

Test pattern (mirrors agent's tool loop):
  Turn 1: [system + tools] + user message
  Turn 2: [system + tools] + user + assistant + tool_call + tool_result + user
  Turn 3: [system + tools] + same growing context + another user message

The system prompt and tools are IDENTICAL across all turns (like the real agent).
Only the conversation history grows.

Usage:
    python test_prompt_caching.py                  # Uses default model from config
    python test_prompt_caching.py <model_name>     # Override model
"""

import os
import sys
import time
import json
import yaml
from openai import OpenAI

# ==========================================================================
#  Configuration
# ==========================================================================
CONFIG_PATH = os.path.join(os.path.dirname(__file__), ".clarity", "config.yaml")

if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    llm_config = config.get("llm", {})
    BASE_URL = llm_config.get("base_url", "")
    MODEL = llm_config.get("model", "")
    if len(sys.argv) > 1:
        MODEL = sys.argv[1]
        print(f"[OK] Model overridden via CLI: {MODEL}")
    print(f"[OK] Loaded config from {CONFIG_PATH}")
else:
    print(f"[WARN] Config file not found: {CONFIG_PATH}")
    BASE_URL = os.getenv("LLM_HOST", "")
    MODEL = os.getenv("LLM_MODEL", "")

API_KEY = ""
try:
    from src.llm.credential_store import load_api_key
    API_KEY = load_api_key()
    if API_KEY:
        print("[OK] Loaded API key from OS keyring")
except ImportError:
    pass

if not API_KEY:
    API_KEY = os.getenv("OPENAI_API_KEY", "")
    if API_KEY:
        print("[OK] Loaded API key from OPENAI_API_KEY env var")

if not all([BASE_URL, API_KEY, MODEL]):
    print("[ERROR] Missing required configuration:")
    print(f"  base_url (from config.yaml) = {'(set)' if BASE_URL else '(missing)'}")
    print(f"  API key (keyring/env)        = {'(set)' if API_KEY else '(missing)'}")
    print(f"  model (from config.yaml)     = {'(set)' if MODEL else '(missing)'}")
    sys.exit(1)

IS_ANTHROPIC = "claude" in MODEL.lower()

print(f"Endpoint : {BASE_URL}")
print(f"Model    : {MODEL}")
print(f"Provider : {'Anthropic (cache_control mode)' if IS_ANTHROPIC else 'OpenAI (automatic caching)'}")
print("-" * 60)

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ==========================================================================
#  Build realistic system prompt and tools (mirrors agent behavior)
# ==========================================================================

# System prompt similar to what get_system_prompt() produces (~2000 tokens)
SYSTEM_PROMPT = """You are ClarAIty, an AI coding agent. You help users with software engineering tasks
including writing code, debugging, refactoring, and explaining code.

## Core Principles
- Read before modifying: Always read a file before editing it
- Minimal changes: Only change what is needed to accomplish the task
- Explain your reasoning before writing code
- Never introduce security vulnerabilities
- Follow existing code patterns and conventions

## Tool Usage Guidelines
- Use read_file to examine files before modifying them
- Use write_file for new files, edit_file for modifications
- Use run_command for shell operations (git, tests, builds)
- Use web_search for external information
- Always verify your changes after making them

## Response Format
- Be concise and direct
- Use markdown for formatting
- Show code in fenced code blocks with language identifiers
- Explain the "why" not just the "what"
""" + (
    "You are an expert in Python, JavaScript, TypeScript, Java, Go, Rust, C++, and other languages. "
    "You understand design patterns, testing strategies, and software architecture. "
) * 60  # Pad to ~1500+ tokens to exceed 1024 minimum


# Realistic tool definitions (subset of what the agent sends)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use this to examine code before making changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                    "start_line": {"type": "integer", "description": "Starting line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line number (inclusive)"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to create"},
                    "content": {"type": "string", "description": "Content to write to the file"}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by replacing a specific string with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to edit"},
                    "old_string": {"type": "string", "description": "The exact string to find and replace"},
                    "new_string": {"type": "string", "description": "The replacement string"}
                },
                "required": ["file_path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return the output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to execute"},
                    "working_directory": {"type": "string", "description": "Directory to run the command in"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"]
            }
        }
    },
]


def build_system_message(use_cache_control):
    """Build system message with or without Anthropic cache_control."""
    if use_cache_control:
        return {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    else:
        return {"role": "system", "content": SYSTEM_PROMPT}


def extract_cache_info(usage):
    """Extract all caching-related fields from the usage object."""
    info = {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }

    details = getattr(usage, "prompt_tokens_details", None)
    if details:
        info["cached_tokens"] = getattr(details, "cached_tokens", None)
        info["cache_creation_tokens"] = getattr(details, "cache_creation_tokens", None)
    else:
        info["cached_tokens"] = None
        info["cache_creation_tokens"] = None

    info["cache_creation_input_tokens"] = getattr(usage, "cache_creation_input_tokens", None)
    info["cache_read_input_tokens"] = getattr(usage, "cache_read_input_tokens", None)

    return info


def dump_raw_usage(usage):
    """Dump the raw usage object for inspection."""
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    elif hasattr(usage, "__dict__"):
        return usage.__dict__
    return str(usage)


def print_cache_summary(cache_info):
    """Print a one-line cache summary."""
    parts = []
    parts.append(f"prompt={cache_info['prompt_tokens']}")

    # OpenAI-style
    if cache_info["cached_tokens"] is not None and cache_info["cached_tokens"] > 0:
        parts.append(f"cached={cache_info['cached_tokens']}")

    # Anthropic-style
    if cache_info["cache_creation_input_tokens"] is not None and cache_info["cache_creation_input_tokens"] > 0:
        parts.append(f"cache_write={cache_info['cache_creation_input_tokens']}")
    if cache_info["cache_read_input_tokens"] is not None and cache_info["cache_read_input_tokens"] > 0:
        parts.append(f"cache_read={cache_info['cache_read_input_tokens']}")

    return " | ".join(parts)


def run_turn(label, messages):
    """Make an API call and return the response + cache info."""
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")

    start = time.time()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=200,
            temperature=0.2,
        )
    except Exception as e:
        print(f"[ERROR] API call failed: {e}")
        return None, None

    elapsed = time.time() - start

    # Extract response content
    msg = response.choices[0].message
    content = msg.content or ""
    tool_calls = msg.tool_calls or []

    try:
        display = content[:100].encode('ascii', errors='replace').decode('ascii') if content else "(no text)"
    except Exception:
        display = "(could not display)"

    print(f"  Time    : {elapsed:.2f}s")
    print(f"  Content : {display}")
    if tool_calls:
        for tc in tool_calls:
            print(f"  Tool    : {tc.function.name}({tc.function.arguments[:80]})")

    cache_info = None
    if response.usage:
        cache_info = extract_cache_info(response.usage)
        print(f"  Tokens  : {print_cache_summary(cache_info)}")
        print(f"  Raw     : {json.dumps(dump_raw_usage(response.usage), indent=4, default=str)}")

    return response, cache_info


# ==========================================================================
#  Simulate agent's multi-turn tool loop
# ==========================================================================
print(f"\n{'#' * 70}")
print(f"  SIMULATING AGENT TOOL LOOP")
print(f"  System prompt + {len(TOOLS)} tools stay identical across all turns.")
print(f"  Conversation history grows each turn (just like the real agent).")
print(f"{'#' * 70}")

system_msg = build_system_message(use_cache_control=IS_ANTHROPIC)

# --- Turn 1: Initial user request ---
messages = [
    system_msg,
    {"role": "user", "content": "Read the file src/cli.py and tell me what the main function does."},
]

r1, c1 = run_turn("Turn 1: User asks to read a file (fresh context)", messages)

# --- Turn 2: Simulate tool call + result, then next LLM call ---
# (Mimics what happens after agent executes read_file tool)
messages.append({
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_001",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"file_path": "src/cli.py"})
            }
        }
    ]
})
messages.append({
    "role": "tool",
    "tool_call_id": "call_001",
    "content": "def main():\n    parser = argparse.ArgumentParser()\n    parser.add_argument('--tui', action='store_true')\n    args = parser.parse_args()\n    if args.tui:\n        run_tui()\n    else:\n        run_cli()\n"
})

r2, c2 = run_turn("Turn 2: After tool execution (system+tools same, history grew)", messages)

# --- Turn 3: Another iteration - assistant responds, user asks follow-up ---
if r2 and r2.choices[0].message.content:
    messages.append({
        "role": "assistant",
        "content": r2.choices[0].message.content,
    })
else:
    messages.append({
        "role": "assistant",
        "content": "The main function sets up argument parsing and launches either TUI or CLI mode.",
    })

messages.append({
    "role": "user",
    "content": "Now add a --version flag to main().",
})

r3, c3 = run_turn("Turn 3: Follow-up request (system+tools same, history grew more)", messages)

# --- Turn 4: Another tool call iteration ---
messages.append({
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_002",
            "type": "function",
            "function": {
                "name": "edit_file",
                "arguments": json.dumps({
                    "file_path": "src/cli.py",
                    "old_string": "parser = argparse.ArgumentParser()",
                    "new_string": "parser = argparse.ArgumentParser()\n    parser.add_argument('--version', action='version', version='1.0.0')"
                })
            }
        }
    ]
})
messages.append({
    "role": "tool",
    "tool_call_id": "call_002",
    "content": "[OK] File edited successfully: src/cli.py"
})

r4, c4 = run_turn("Turn 4: After another tool execution (4th call, same prefix)", messages)

# --- Turn 5: Rapid-fire 5th call to test cache stability ---
messages.append({
    "role": "assistant",
    "content": "Done. I added --version flag to the argument parser.",
})
messages.append({
    "role": "user",
    "content": "Run the tests to verify nothing broke.",
})

r5, c5 = run_turn("Turn 5: User asks to run tests (5th call, same prefix)", messages)


# ==========================================================================
#  Summary Table
# ==========================================================================
print(f"\n{'=' * 70}")
print(f"  RESULTS SUMMARY")
print(f"{'=' * 70}")

all_results = [
    ("Turn 1", c1),
    ("Turn 2", c2),
    ("Turn 3", c3),
    ("Turn 4", c4),
    ("Turn 5", c5),
]

if IS_ANTHROPIC:
    print(f"\n  {'Turn':<10} {'Prompt':>8} {'Cache Write':>13} {'Cache Read':>12} {'Hit?':>6}")
    print(f"  {'-'*10} {'-'*8} {'-'*13} {'-'*12} {'-'*6}")

    hits = 0
    total = 0
    for label, ci in all_results:
        if ci is None:
            print(f"  {label:<10} {'ERROR':>8}")
            continue
        total += 1
        write = ci.get("cache_creation_input_tokens") or 0
        read = ci.get("cache_read_input_tokens") or 0
        hit = "YES" if read > 0 else "no"
        if read > 0:
            hits += 1
        print(f"  {label:<10} {ci['prompt_tokens']:>8} {write:>13} {read:>12} {hit:>6}")

    print(f"\n  Cache hit rate: {hits}/{total} turns ({hits/total*100:.0f}% of turns after first)")
    print(f"  First turn is always a cache write (expected).")

    if hits >= 3:
        print(f"\n  [RESULT] Caching works well! Consistent cache hits across the tool loop.")
        print(f"  Adding cache_control to context_builder.py will give ~90% savings on the")
        print(f"  system prompt tokens for every turn after the first.")
    elif hits >= 1:
        print(f"\n  [RESULT] Caching works but with some misses (likely load balancer routing).")
        print(f"  Still worth enabling - partial cache hits save money over no caching.")
    else:
        print(f"\n  [RESULT] No cache hits detected. FuelIX may not be passing cache_control")
        print(f"  through to Anthropic, or load balancing prevents cache reuse.")

else:
    print(f"\n  {'Turn':<10} {'Prompt':>8} {'Cached':>8} {'Hit?':>6}")
    print(f"  {'-'*10} {'-'*8} {'-'*8} {'-'*6}")

    hits = 0
    total = 0
    for label, ci in all_results:
        if ci is None:
            print(f"  {label:<10} {'ERROR':>8}")
            continue
        total += 1
        cached = ci.get("cached_tokens") or 0
        hit = "YES" if cached > 0 else "no"
        if cached > 0:
            hits += 1
        print(f"  {label:<10} {ci['prompt_tokens']:>8} {cached:>8} {hit:>6}")

    print(f"\n  Cache hit rate: {hits}/{total} turns")
