"""
Test Qwen3-Coder 30B with realistic coding agent prompt.
Mimics what Cursor/Claude Code would send.
"""

import requests
import json
import time

# Read actual source files to include in context
with open('src/core/agent.py', 'r') as f:
    agent_code = f.read()

with open('src/memory/memory_manager.py', 'r') as f:
    memory_code = f.read()

# Realistic system prompt (similar to Cursor/Claude Code)
SYSTEM_PROMPT = """You are an expert AI coding assistant with deep knowledge of software engineering.

# Your Capabilities
- Read and analyze existing code
- Write new code or modify existing code
- Debug issues and explain errors
- Understand complex codebases
- Use tools to interact with files

# Available Tools
You have access to the following tools:

1. read_file(file_path: str) -> str
   Read contents of a file at the given path

2. write_file(file_path: str, content: str) -> bool
   Write content to a file (creates or overwrites)

3. edit_file(file_path: str, old_content: str, new_content: str) -> bool
   Replace old_content with new_content in a file

4. search_code(query: str, language: str = None) -> List[CodeChunk]
   Search for relevant code snippets in the indexed codebase

# Tool Calling Format
When you want to use a tool, respond with:
<tool_call>
<tool_name>read_file</tool_name>
<parameters>
{"file_path": "src/example.py"}
</parameters>
</tool_call>

# Response Guidelines
- Be concise and precise
- Reference specific line numbers when discussing code
- Explain your reasoning
- For code changes, show before/after
- Use the user's coding style

# Current Context
You have access to the complete source code of the current project in the messages below."""

# Build messages like a real coding agent would
messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    },
    {
        "role": "system",
        "content": f"""# File: src/core/agent.py
```python
{agent_code}
```"""
    },
    {
        "role": "system",
        "content": f"""# File: src/memory/memory_manager.py
```python
{memory_code}
```"""
    },
    {
        "role": "user",
        "content": """I'm looking at the CodingAgent class and I notice that tools are registered but never actually called.

Looking at the `chat()` and `execute_task()` methods in agent.py (lines 234-252 and 154-232), I can see:
1. It builds context from memory
2. Sends context to LLM
3. Gets response
4. Stores response in memory

But there's no loop to parse the LLM response for tool calls and execute them. The tool_executor exists but is only used manually via `execute_tool()`.

Can you:
1. Explain why this is a problem
2. Suggest how to implement a tool calling loop
3. Point out where in the code it should be added

Be specific about line numbers and implementation details."""
    }
]

# Calculate token counts (approximate)
def count_tokens(text):
    """Rough token estimation"""
    return len(text.split()) * 1.3

total_tokens = sum(count_tokens(json.dumps(msg)) for msg in messages)

print(f"\n{'='*80}")
print(f"Testing Qwen3-Coder 30B with Realistic Coding Agent Prompt")
print(f"{'='*80}")
print(f"\nPrompt Statistics:")
print(f"  Messages: {len(messages)}")
print(f"  System messages: {len([m for m in messages if m['role'] == 'system'])}")
print(f"  Total characters: {sum(len(m['content']) for m in messages):,}")
print(f"  Estimated tokens: ~{int(total_tokens):,}")
print(f"  Source files included: 2 (agent.py, memory_manager.py)")
print(f"  Total source lines: ~720 lines")
print(f"\n{'='*80}")
print(f"Sending request to Ollama...")
print(f"{'='*80}\n")

# Call Ollama API
start_time = time.time()

response = requests.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "qwen3-coder:30b",
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 131072,  # 128K context
        }
    },
    timeout=300  # 5 minute timeout
)

elapsed = time.time() - start_time

if response.status_code == 200:
    data = response.json()
    assistant_response = data.get("message", {}).get("content", "")

    print(f"[ASSISTANT RESPONSE]")
    print(f"{'='*80}")
    print(assistant_response)
    print(f"\n{'='*80}")
    print(f"\nResponse Statistics:")
    print(f"  Response time: {elapsed:.2f}s")
    print(f"  Response length: {len(assistant_response)} characters")
    print(f"  Response tokens: ~{int(count_tokens(assistant_response))}")

    # Analyze response quality
    print(f"\n{'='*80}")
    print(f"Quality Analysis:")
    print(f"{'='*80}")

    checks = {
        "Mentioned line numbers": any(str(i) in assistant_response for i in range(150, 260)),
        "Referenced execute_task()": "execute_task" in assistant_response.lower(),
        "Mentioned tool_executor": "tool_executor" in assistant_response.lower() or "tool executor" in assistant_response.lower(),
        "Suggested solution": "loop" in assistant_response.lower() or "parse" in assistant_response.lower(),
        "Referenced specific code": "agent.py" in assistant_response.lower() or "method" in assistant_response.lower(),
    }

    for check, passed in checks.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check}")

    score = sum(checks.values()) / len(checks) * 100
    print(f"\n  Overall Quality Score: {score:.0f}%")

else:
    print(f"ERROR: {response.status_code}")
    print(response.text)
