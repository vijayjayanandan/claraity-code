# Implementation Plan - Agent Fixes (Next Session)

**Based on:** RCA_COMPLETE.md
**Date Prepared:** 2025-10-13
**Estimated Time:** 3-4 hours total
**Confidence:** HIGH (all solutions validated)

---

## 🎯 Session Goal

Transform the AI coding agent from a basic chatbot into a fully functional coding assistant with:
- ✅ Working conversation memory
- ✅ File read/write capabilities
- ✅ Code understanding (RAG)
- ✅ Tool execution loop

---

## 📋 Implementation Phases

### **Phase 1: Quick Wins (15 minutes)** ⚡

**Goal:** Get immediate improvements working

#### Task 1.1: Increase Context Window (1 min)
**File:** `src/cli.py:169-172`

**Change:**
```python
# Before:
parser.add_argument(
    "--context",
    type=int,
    default=4096,  # ← Change this
    help="Context window size (default: 4096)"
)

# After:
parser.add_argument(
    "--context",
    type=int,
    default=16384,  # Using full model capacity
    help="Context window size (default: 16384)"
)
```

**Test:** Agent initialization shows 16384 tokens

#### Task 1.2: Update System Prompt (5 min)
**File:** `src/prompts/system_prompts.py`

**Find the function:** `get_context_aware_prompt()` or `get_base_system_prompt()`

**Add this at the beginning of the prompt:**
```python
base_prompt = """You are an AI coding assistant in a CONTINUOUS MULTI-TURN CONVERSATION.

CRITICAL - CONVERSATION CONTEXT:
- The messages above contain the FULL conversation history
- When users refer to "before", "earlier", or "previously", look at prior messages
- When users ask "what did I say?" or "what's my name?", reference earlier messages
- Maintain continuity across all messages - you're not starting fresh each time

Example of proper behavior:
User: "My name is Alice"
Assistant: "Hello Alice!"
User: "What's my name?"
Assistant: "Your name is Alice, as you mentioned in your previous message."

CRITICAL - TOOL USAGE:
You have access to tools for file operations and code analysis.
When users ask you to read files or analyze code, USE THE TOOLS.
Don't say "I can't access files" - you CAN via the tools provided.

Now respond based on the FULL conversation context and available tools.

---

"""
```

**Test:** Chat should remember previous messages

#### Task 1.3: Add Auto-Indexing to Chat (5 min)
**File:** `src/cli.py:221-223`

**Change:**
```python
# Before:
if args.command == "chat":
    chat_mode(agent)

# After:
if args.command == "chat":
    # Auto-index codebase for RAG support
    console.print("[cyan]Indexing codebase for RAG retrieval...[/cyan]")
    try:
        stats = agent.index_codebase(directory="./src")
        console.print(f"[green]✓ Indexed {stats['total_files']} files, {stats['total_chunks']} chunks[/green]\n")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not index codebase: {e}[/yellow]")
        console.print(f"[yellow]  Continuing without RAG support...[/yellow]\n")

    chat_mode(agent)
```

**Also update the default case (line ~230):**
```python
else:
    # Default to chat mode with auto-indexing
    console.print("[cyan]Indexing codebase for RAG retrieval...[/cyan]")
    try:
        stats = agent.index_codebase(directory="./src")
        console.print(f"[green]✓ Indexed {stats['total_files']} files, {stats['total_chunks']} chunks[/green]\n")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not index codebase: {e}[/yellow]")
        console.print(f"[yellow]  Continuing without RAG support...[/yellow]\n")

    chat_mode(agent)
```

**Test:** Chat starts with indexing message, RAG available

#### Task 1.4: Test Phase 1 (5 min)
```bash
python -m src.cli chat
```

**Test cases:**
1. "My name is Vijay" → "What's my name?" → Should remember ✅
2. "Explain the memory system" → Should use RAG ✅
3. Check context window shows 16384 ✅

**Expected:** Memory works, RAG works, larger context

---

### **Phase 2: Tool Calling Implementation (2-3 hours)** 🛠️

**Goal:** Enable file operations and code search

#### Task 2.1: Design Tool Call Protocol (30 min)

**Create:** `src/tools/protocol.md` (documentation)

**Tool Call Format:**
```
USE_TOOL: tool_name(arg1="value1", arg2="value2")
```

**Examples:**
```
USE_TOOL: read_file(path="README.md")
USE_TOOL: search_code(query="memory system", pattern="*.py")
USE_TOOL: write_file(path="test.py", content="print('hello')")
```

**File:** `src/tools/parser.py` (new file)

```python
"""Parse tool calls from LLM responses."""

import re
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class ToolCall:
    """Represents a parsed tool call."""
    name: str
    args: Dict[str, Any]
    raw_text: str


def parse_tool_calls(response: str) -> List[ToolCall]:
    """
    Parse tool calls from LLM response.

    Format: USE_TOOL: tool_name(arg1="value1", arg2="value2")

    Args:
        response: LLM response text

    Returns:
        List of ToolCall objects
    """
    tool_calls = []

    # Pattern: USE_TOOL: tool_name(arguments)
    pattern = r'USE_TOOL:\s*(\w+)\((.*?)\)'

    for match in re.finditer(pattern, response, re.MULTILINE | re.DOTALL):
        tool_name = match.group(1)
        args_str = match.group(2)

        # Parse arguments
        args = parse_arguments(args_str)

        tool_calls.append(ToolCall(
            name=tool_name,
            args=args,
            raw_text=match.group(0)
        ))

    return tool_calls


def parse_arguments(args_str: str) -> Dict[str, Any]:
    """
    Parse function arguments from string.

    Handles: arg1="value1", arg2="value2"

    Args:
        args_str: Arguments string

    Returns:
        Dictionary of arguments
    """
    args = {}

    # Pattern: key="value" or key='value'
    pattern = r'(\w+)=(["\'])(.*?)\2'

    for match in re.finditer(pattern, args_str):
        key = match.group(1)
        value = match.group(3)
        args[key] = value

    return args


def remove_tool_calls(response: str) -> str:
    """
    Remove tool call syntax from response, leaving only natural text.

    Args:
        response: LLM response with tool calls

    Returns:
        Response with tool calls removed
    """
    pattern = r'USE_TOOL:\s*\w+\(.*?\)\n?'
    return re.sub(pattern, '', response, flags=re.MULTILINE | re.DOTALL).strip()
```

**Test:** Write unit tests for parser

#### Task 2.2: Update System Prompt with Tool Descriptions (15 min)

**File:** `src/prompts/system_prompts.py`

**Add to system prompt (after conversation context section):**
```python
AVAILABLE TOOLS:
You have access to the following tools for file operations and code analysis:

1. read_file(path: str) -> str
   Read the contents of a file
   Example: USE_TOOL: read_file(path="src/agent.py")

2. write_file(path: str, content: str) -> bool
   Write content to a file (creates or overwrites)
   Example: USE_TOOL: write_file(path="test.py", content="print('hello')")

3. edit_file(path: str, old_text: str, new_text: str) -> bool
   Edit a file by replacing old_text with new_text
   Example: USE_TOOL: edit_file(path="config.py", old_text="DEBUG = False", new_text="DEBUG = True")

4. search_code(query: str, file_pattern: str = "*.py") -> List[str]
   Search for code matching a query
   Example: USE_TOOL: search_code(query="memory system", file_pattern="*.py")

5. analyze_code(path: str) -> Dict
   Analyze code structure (classes, functions, dependencies)
   Example: USE_TOOL: analyze_code(path="src/agent.py")

TOOL USAGE PROTOCOL:
- When you need to use a tool, include the tool call in your response
- Format: USE_TOOL: tool_name(arg1="value1", arg2="value2")
- You can call multiple tools in one response
- After tool execution, you'll see the results and can provide your final answer
- If a user asks you to read/write/search files, USE THE TOOLS - don't say you can't

Example conversation with tools:
User: "Read the README file"
Assistant: "I'll read that for you.
USE_TOOL: read_file(path="README.md")"
[System provides tool result]
Assistant: "Here's what's in the README: [content summary]..."
```

#### Task 2.3: Implement Tool Calling Loop (1.5 hours)

**File:** `src/core/agent.py`

**Replace `execute_task()` method (lines 154-222) with:**

```python
def execute_task(
    self,
    task_description: str,
    task_type: str = "implement",
    language: str = "python",
    use_rag: bool = True,
    stream: bool = False,
    max_tool_iterations: int = 5,
) -> AgentResponse:
    """
    Execute a coding task with tool calling support.

    Args:
        task_description: Description of the task
        task_type: Type of task (implement, debug, refactor, etc.)
        language: Programming language
        use_rag: Whether to use RAG retrieval
        stream: Whether to stream response
        max_tool_iterations: Maximum tool calling iterations

    Returns:
        Agent response
    """
    from src.tools.parser import parse_tool_calls, remove_tool_calls

    # Create task context
    task_context = TaskContext(
        task_id=str(uuid.uuid4()),
        description=task_description,
        task_type=task_type,
        key_concepts=[],
    )

    self.memory.set_task_context(task_context)

    # Add user message to memory
    self.memory.add_user_message(task_description)

    # Build initial context
    context = self.context_builder.build_context(
        user_query=task_description,
        task_type=task_type,
        language=language,
        use_rag=use_rag and len(self.indexed_chunks) > 0,
        available_chunks=self.indexed_chunks if use_rag else None,
    )

    # Tool calling loop
    final_response = ""
    tool_history = []

    for iteration in range(max_tool_iterations):
        print(f"\n[Iteration {iteration + 1}]")

        # Generate response
        if stream and iteration == max_tool_iterations - 1:
            # Only stream final response
            full_response = ""
            for chunk in self.llm.generate_stream(context):
                print(chunk.content, end="", flush=True)
                full_response += chunk.content
            print()
            response_content = full_response
        else:
            # Non-streaming for intermediate tool calls
            llm_response = self.llm.generate(context)
            response_content = llm_response.content

        # Parse for tool calls
        tool_calls = parse_tool_calls(response_content)

        if not tool_calls:
            # No tools needed, this is the final answer
            final_response = response_content
            break

        # Execute tools
        print(f"  Executing {len(tool_calls)} tool(s)...")
        tool_results = []

        for tool_call in tool_calls:
            print(f"    - {tool_call.name}({', '.join(f'{k}={v[:30]}...' if len(v) > 30 else f'{k}={v}' for k, v in tool_call.args.items())})")

            try:
                result = self.execute_tool(tool_call.name, **tool_call.args)
                tool_results.append({
                    "tool": tool_call.name,
                    "args": tool_call.args,
                    "result": result,
                    "success": True
                })
            except Exception as e:
                print(f"      ERROR: {e}")
                tool_results.append({
                    "tool": tool_call.name,
                    "args": tool_call.args,
                    "error": str(e),
                    "success": False
                })

        tool_history.extend(tool_results)

        # Format tool results for LLM
        results_text = self._format_tool_results(tool_results)

        # Add tool execution to context
        # Remove tool calls from LLM response, keep only natural language
        clean_response = remove_tool_calls(response_content)
        if clean_response:
            context.append({"role": "assistant", "content": clean_response})

        # Add tool results
        context.append({
            "role": "system",
            "content": f"<tool_results>\n{results_text}\n</tool_results>\n\nNow provide your final answer based on these tool results."
        })

    # If we exhausted iterations
    if not final_response:
        final_response = "I apologize, but I reached the maximum number of tool iterations. Please try breaking down your request into smaller steps."

    # Add final response to memory
    self.memory.add_assistant_message(final_response)

    return AgentResponse(
        content=final_response,
        tool_calls=tool_history,
        metadata={
            "task_type": task_type,
            "language": language,
            "used_rag": use_rag and len(self.indexed_chunks) > 0,
            "tool_iterations": iteration + 1,
        }
    )

def _format_tool_results(self, tool_results: List[Dict]) -> str:
    """Format tool execution results for LLM."""
    formatted = []

    for i, result in enumerate(tool_results, 1):
        if result["success"]:
            # Truncate long results
            result_str = str(result["result"])
            if len(result_str) > 1000:
                result_str = result_str[:1000] + "\n... (truncated)"

            formatted.append(
                f"Tool {i}: {result['tool']}({', '.join(f'{k}={v}' for k, v in result['args'].items())})\n"
                f"Result: {result_str}"
            )
        else:
            formatted.append(
                f"Tool {i}: {result['tool']}({', '.join(f'{k}={v}' for k, v in result['args'].items())})\n"
                f"ERROR: {result['error']}"
            )

    return "\n\n".join(formatted)
```

**Test:** Tool calls are parsed and executed

#### Task 2.4: Remove Debug Logging (1 min)

**File:** `src/core/agent.py:197-205`

**Remove the debug print statements added earlier**

#### Task 2.5: Test Tool Calling (30 min)

```bash
python -m src.cli chat
```

**Test cases:**
1. "Read the file README.md"
   - Should call `read_file` tool
   - Should display file contents

2. "Search for 'memory system' in the code"
   - Should call `search_code` tool
   - Should show matching files

3. "Read src/core/agent.py and explain what it does"
   - Should call `read_file` first
   - Then explain based on content

4. "Write a test file called hello.py with a simple print statement"
   - Should call `write_file` tool
   - Should confirm creation

**Expected:** All tool operations work

---

### **Phase 3: Integration & Polish (1 hour)** ✨

#### Task 3.1: End-to-End Testing (30 min)

**Test Scenario 1: Multi-Turn with Memory + Tools**
```
User: "My name is Vijay"
Agent: "Hello Vijay!"
User: "Read the README and tell me what this project is about"
Agent: [uses read_file tool] "This project is..."
User: "What was my name again?"
Agent: "Your name is Vijay, as you mentioned earlier"
```

**Test Scenario 2: Complex Code Understanding**
```
User: "Find the memory system implementation"
Agent: [uses search_code] "I found it in..."
User: "Now read that file and explain how it works"
Agent: [uses read_file] "The memory system..."
```

**Test Scenario 3: Code Modification**
```
User: "Create a new file called test_utils.py with a helper function"
Agent: [uses write_file] "I've created..."
User: "Now read it back to me"
Agent: [uses read_file] "Here's the content..."
```

#### Task 3.2: Error Handling (15 min)

**Add error handling for:**
- File not found
- Invalid tool calls
- Tool execution failures
- Max iterations reached

**Test edge cases:**
- "Read a file that doesn't exist"
- "Write to a protected directory"
- Complex tool call chains

#### Task 3.3: Documentation Update (15 min)

**Update README.md:**
- Add "What's New" section
- Document tool capabilities
- Add examples of tool usage
- Update feature list

**Update CLAUDE.md:**
- Mark implementation complete
- Update status to "Production Ready"
- Add "Next Steps" section

---

## 🎯 Success Criteria

### Must Pass:
- [  ] Conversation memory works (remembers across turns)
- [  ] File reading works (reads and displays content)
- [  ] Code search works (finds relevant code)
- [  ] RAG is active in chat mode (indexes on start)
- [  ] Context window is 16K (full capacity)

### Should Pass:
- [  ] File writing works
- [  ] File editing works
- [  ] Multi-step tool workflows work
- [  ] Error handling is graceful

### Nice to Have:
- [  ] Code analysis works
- [  ] Streaming works with tools
- [  ] Performance is acceptable (<5s per turn)

---

## 🚨 Potential Issues & Solutions

### Issue: Tool calls not parsed correctly
**Solution:** Check regex patterns in parser.py, add debug logging

### Issue: Infinite tool calling loop
**Solution:** max_tool_iterations limit (default 5)

### Issue: Large file contents overflow context
**Solution:** Truncate tool results to 1000 chars in `_format_tool_results()`

### Issue: LLM doesn't use tools even with instructions
**Solution:** Make system prompt even more explicit, add more examples

---

## 📝 Files to Modify

### Core Changes:
- [  ] `src/core/agent.py` - Tool calling loop
- [  ] `src/prompts/system_prompts.py` - Better prompts
- [  ] `src/cli.py` - Auto-indexing, context window

### New Files:
- [  ] `src/tools/parser.py` - Tool call parser
- [  ] `src/tools/protocol.md` - Documentation

### Documentation:
- [  ] `README.md` - Updated capabilities
- [  ] `CLAUDE.md` - Status update

---

## ⏱️ Time Breakdown

| Phase | Task | Time |
|-------|------|------|
| 1 | Context window | 1 min |
| 1 | System prompt | 5 min |
| 1 | Auto-indexing | 5 min |
| 1 | Phase 1 testing | 5 min |
| **1 Total** | | **15 min** |
| 2 | Tool protocol design | 30 min |
| 2 | System prompt tools | 15 min |
| 2 | Tool calling loop | 90 min |
| 2 | Remove debug logs | 1 min |
| 2 | Phase 2 testing | 30 min |
| **2 Total** | | **2.8 hrs** |
| 3 | End-to-end testing | 30 min |
| 3 | Error handling | 15 min |
| 3 | Documentation | 15 min |
| **3 Total** | | **1 hr** |
| **GRAND TOTAL** | | **~4 hrs** |

---

## 🎓 Learning Points

### What This Teaches:
1. **Agentic AI Design** - Tool calling loops, iterative refinement
2. **Prompt Engineering** - Explicit instructions matter
3. **System Integration** - Memory + RAG + Tools working together
4. **Error Handling** - Graceful degradation, user feedback

### Skills Developed:
- Multi-component system design
- LLM response parsing
- Tool execution orchestration
- Context window optimization

---

## 🚀 Ready to Implement!

**Session Title:** "Agent Core Features Implementation"

**Starting Point:**
```bash
cd /workspace/ai-coding-agent
source venv/bin/activate
```

**First Command:**
```bash
# Phase 1, Task 1.1
vi src/cli.py  # Change context window to 16384
```

**Validation:**
After each phase, run:
```bash
python -m src.cli chat
```

And test the success criteria for that phase.

---

**All planning complete - ready to code!** 🎯
