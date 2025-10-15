"""
Test if Qwen3-Coder 30B can follow JSON format instructions for tool calling.
This validates our approach before implementation.
"""

import requests
import json
import time
import re

# System prompt with JSON tool format instructions
SYSTEM_PROMPT = """You are an expert AI coding assistant with access to tools.

# Available Tools

1. **read_file** - Read contents of a file
   - Parameters: file_path (string)

2. **write_file** - Write content to a file
   - Parameters: file_path (string), content (string)

3. **search_code** - Search for code in the indexed codebase
   - Parameters: query (string), language (string, optional)

4. **list_files** - List files in a directory
   - Parameters: directory (string)

# Tool Calling Format

When you need to use a tool, respond with a JSON object in this EXACT format:

```json
{
  "thoughts": "Brief explanation of what you're doing and why",
  "tool_calls": [
    {
      "tool": "tool_name",
      "arguments": {
        "arg1": "value1",
        "arg2": "value2"
      }
    }
  ]
}
```

# Important Rules

1. **ALWAYS** wrap your JSON in ```json and ``` markers
2. Use the exact field names: "thoughts", "tool_calls", "tool", "arguments"
3. You can call multiple tools in one response by adding more objects to tool_calls array
4. After seeing tool results, provide a natural language response to the user

# Example

User: "Read the file utils.py"

Assistant Response:
```json
{
  "thoughts": "The user wants to read utils.py. I'll use the read_file tool.",
  "tool_calls": [
    {
      "tool": "read_file",
      "arguments": {
        "file_path": "utils.py"
      }
    }
  ]
}
```

Now respond to the user's request below using this exact format.
"""


def extract_json_from_response(response_text):
    """Extract JSON from markdown code blocks."""
    # Try to find JSON in code blocks
    json_pattern = r'```json\s*\n(.*?)\n```'
    matches = re.findall(json_pattern, response_text, re.DOTALL)
    
    if matches:
        return matches[0]
    
    # Fallback: try to find raw JSON
    try:
        # Look for {...} pattern
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            return response_text[json_start:json_end]
    except:
        pass
    
    return None


def test_json_format(user_message, test_name):
    """Test if Qwen3 follows JSON format for given user message."""
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"{'='*80}")
    print(f"User: {user_message}\n")
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    
    start = time.time()
    
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen3-coder:30b",
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temp for consistent format
                    "num_ctx": 131072
                }
            },
            timeout=60
        )
        
        elapsed = time.time() - start
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("message", {}).get("content", "")
            
            print(f"Response ({elapsed:.1f}s):")
            print(content)
            print()
            
            # Try to parse JSON
            json_text = extract_json_from_response(content)
            
            if json_text:
                try:
                    parsed = json.loads(json_text)
                    
                    # Validate structure
                    has_thoughts = "thoughts" in parsed
                    has_tool_calls = "tool_calls" in parsed
                    
                    if has_tool_calls and isinstance(parsed["tool_calls"], list):
                        valid_calls = all(
                            "tool" in call and "arguments" in call
                            for call in parsed["tool_calls"]
                        )
                    else:
                        valid_calls = False
                    
                    print(f"{'='*80}")
                    print("VALIDATION:")
                    print(f"{'='*80}")
                    print(f"  ✓ JSON found and parsed successfully")
                    print(f"  {'✓' if has_thoughts else '✗'} Has 'thoughts' field")
                    print(f"  {'✓' if has_tool_calls else '✗'} Has 'tool_calls' field")
                    print(f"  {'✓' if valid_calls else '✗'} Tool calls have correct structure")
                    
                    if has_tool_calls and parsed["tool_calls"]:
                        print(f"\n  Tool calls found: {len(parsed['tool_calls'])}")
                        for i, call in enumerate(parsed["tool_calls"], 1):
                            print(f"    {i}. {call.get('tool', 'UNKNOWN')} - {call.get('arguments', {})}")
                    
                    all_valid = has_thoughts and has_tool_calls and valid_calls
                    
                    print(f"\n  {'✅ PASS' if all_valid else '❌ FAIL'} - Format is {'correct' if all_valid else 'incorrect'}")
                    
                    return all_valid
                    
                except json.JSONDecodeError as e:
                    print(f"{'='*80}")
                    print(f"❌ FAIL - JSON parsing error: {e}")
                    return False
            else:
                print(f"{'='*80}")
                print(f"❌ FAIL - No JSON found in response")
                return False
        else:
            print(f"❌ ERROR: {response.status_code}")
            print(response.text)
            return False
            
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "="*80)
    print("Testing Qwen3-Coder 30B JSON Tool Format Compliance")
    print("="*80)
    
    tests = [
        ("Read the file at src/core/agent.py", "Simple file read"),
        ("Search for all functions that use MemoryManager", "Code search"),
        ("Read agent.py and then search for functions using memory", "Multiple tools"),
    ]
    
    results = []
    
    for user_msg, test_name in tests:
        result = test_json_format(user_msg, test_name)
        results.append((test_name, result))
        time.sleep(2)  # Brief pause between tests
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {test_name}")
    
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    
    print(f"\nTotal: {passed_count}/{total} tests passed")
    
    if passed_count == total:
        print("\n🎉 SUCCESS! Qwen3 can follow JSON tool format.")
        print("   Ready to implement tool calling loop!")
    elif passed_count > 0:
        print("\n⚠️  PARTIAL SUCCESS - Some tests passed.")
        print("   May need to refine prompt instructions.")
    else:
        print("\n❌ FAILED - Qwen3 cannot follow JSON format consistently.")
        print("   Need to try alternative approach.")
