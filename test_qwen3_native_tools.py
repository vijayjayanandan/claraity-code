"""
Test Ollama's native tool calling support with Qwen3-Coder 30B.
Uses Ollama's built-in tools parameter.
"""

import requests
import json
import time

# Define tools in Ollama's format (OpenAI-compatible)
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file at the given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for code snippets in the indexed codebase",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "language": {
                        "type": "string",
                        "description": "Optional programming language filter"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Test message that should trigger tool usage
messages = [
    {
        "role": "system",
        "content": "You are a helpful coding assistant. Use the available tools to help the user."
    },
    {
        "role": "user",
        "content": "Please read the file at 'src/core/agent.py' and tell me what the main class is called."
    }
]

print("="*80)
print("Testing Ollama Native Tool Calling with Qwen3-Coder 30B")
print("="*80)
print(f"\nTools provided: {len(tools)}")
for tool in tools:
    print(f"  - {tool['function']['name']}: {tool['function']['description']}")

print(f"\nUser request: {messages[1]['content']}")
print("\n" + "="*80)
print("Sending request to Ollama with tools parameter...")
print("="*80 + "\n")

start = time.time()

try:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen3-coder:30b",
            "messages": messages,
            "tools": tools,  # Native tool calling
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 131072
            }
        },
        timeout=120
    )

    elapsed = time.time() - start

    if response.status_code == 200:
        data = response.json()
        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])

        print(f"✓ SUCCESS in {elapsed:.1f}s\n")

        print("="*80)
        print("RESPONSE ANALYSIS:")
        print("="*80)

        print(f"\nMessage role: {message.get('role', 'N/A')}")
        print(f"Has content: {bool(content)}")
        print(f"Has tool_calls: {bool(tool_calls)}")

        if tool_calls:
            print(f"\n✓ MODEL REQUESTED TOOL CALLS!")
            print(f"Number of tool calls: {len(tool_calls)}")
            print("\nTool calls:")
            for i, call in enumerate(tool_calls, 1):
                print(f"\n  Tool call #{i}:")
                print(f"    Function: {call.get('function', {}).get('name', 'N/A')}")
                print(f"    Arguments: {json.dumps(call.get('function', {}).get('arguments', {}), indent=6)}")
        else:
            print(f"\n✗ NO TOOL CALLS - Model responded with text instead")

        if content:
            print(f"\nMessage content:")
            print(f"  {content[:500]}{'...' if len(content) > 500 else ''}")

        print("\n" + "="*80)
        print("RAW RESPONSE DATA:")
        print("="*80)
        print(json.dumps(data, indent=2))

        # Verdict
        print("\n" + "="*80)
        print("VERDICT:")
        print("="*80)
        if tool_calls:
            print("✓ Native tool calling WORKS with Qwen3-Coder 30B!")
            print("  We can use Ollama's built-in tool support.")
        else:
            print("✗ Native tool calling FAILED - model didn't use tools")
            print("  We'll need to implement custom tool calling parsing.")

    else:
        print(f"✗ ERROR: {response.status_code}")
        print(f"Response: {response.text}")

        print("\n" + "="*80)
        print("VERDICT:")
        print("="*80)
        print("✗ Native tool calling FAILED with error")
        print("  We'll need to implement custom tool calling parsing.")

except Exception as e:
    print(f"✗ EXCEPTION: {e}")
    print("\n" + "="*80)
    print("VERDICT:")
    print("="*80)
    print("✗ Native tool calling FAILED with exception")
    print("  We'll need to implement custom tool calling parsing.")
