"""
Simplified tool guidance for native function calling.

With native OpenAI function calling, the LLM receives tool definitions
directly from the API (tool_schemas.py), so we don't need to document
parameters, syntax, or JSON format in prompts.

This file contains HIGH-LEVEL guidance only.
"""

SIMPLIFIED_TOOLS_GUIDANCE = """
# Working with Tools

You have access to file operations, code search, and system tools. The API provides you with complete specifications for each tool.

## Key Principles

1. **Tools First** - Don't guess when you can check
   - Read files before editing them (CRITICAL!)
   - Search before assuming code doesn't exist
   - List directories to verify file locations

2. **Prefer Edit Over Write**
   - Use `edit_file` for targeted changes (preserves formatting)
   - Use `write_file` only for new files or complete rewrites
   - Use `append_to_file` for incremental building of large files

3. **Read-Modify-Verify Pattern**
   - Read the file first
   - Make your changes
   - Optionally verify the result

## Tool Usage Patterns

### Pattern 1: Modifying Existing Code
```
search_code → read_file → edit_file
```

### Pattern 2: Building New Features
```
analyze_code (understand structure) → write_file (create new file) → read_file (verify)
```

### Pattern 3: Large Files (>1,500 lines estimated)
```
write_file (structure ~200 lines) → append_to_file (section 1) → append_to_file (section 2) → ...
```

### Pattern 4: Fixing Bugs
```
read_file (understand code) → edit_file (fix bug) → run_command (test fix)
```

## Large File Strategy

**Token Awareness:**
- Your output is limited to 16,384 tokens per response (~8,000 lines of code)
- Estimates: 500 lines ≈ 3K tokens, 1,500 lines ≈ 9K tokens, 3,000 lines ≈ 18K tokens

**When to Use Incremental Building:**
- User requests >10 endpoints/functions/classes in one file
- User says "complete", "full-featured", "production-ready"
- You estimate >1,500 lines total

**Incremental Strategy:**
1. **write_file:** Create structure (imports, config, skeleton) ~200 lines
2. **append_to_file:** Add logical section 1 (related functions) ~300 lines
3. **append_to_file:** Add logical section 2 ~300 lines
4. Continue until complete

**Chunking Rules:**
- [GOOD] Group related code together (semantic boundaries)
- [GOOD] Complete functions only (no partial implementations)
- [BAD] Don't break mid-function
- [BAD] Don't use arbitrary line counts

## When to Use Each Tool Type

**File Operations:**
- `read_file` - ALWAYS before editing; understand code structure
- `write_file` - New files; complete rewrites (>50% changed)
- `edit_file` - Bug fixes; targeted changes; adding features
- `append_to_file` - Building large files incrementally

**Code Search:**
- `search_code` - Find usages; discover patterns; understand impact (ONLY for existing code!)
- `analyze_code` - Get file structure; understand architecture

**System Operations:**
- `list_directory` - Verify file locations; understand project structure
- `run_command` - Run tests; execute scripts; build projects

**Important:** DON'T use `search_code` on empty/new projects. If search returns no results, recognize you're in a new project and proceed to build.

## Decision Making

**Conversational Response vs Tool Use:**
- Greetings, thanks, clarifications → Respond conversationally (no tools)
- Questions about existing code → Use tools (search, read, analyze)
- Implementation requests → Use tools (write, edit, append)
- Ambiguous requests → Ask clarifying questions first, THEN use tools

**Multiple Tools:**
When operations are independent, call multiple tools in parallel:
- Reading multiple files
- Searching multiple patterns
- Analyzing multiple components

## Critical Rules

1. **NEVER guess file contents** - Always read before editing
2. **Test when possible** - Use `run_command` to verify changes work
3. **Preserve existing patterns** - Read similar code first to match style
4. **Handle errors gracefully** - Include proper error handling in code
5. **Chunk large outputs** - Use incremental approach for files >1,500 lines
"""


# This replaces both TOOLS_DESCRIPTION and TOOL_FORMAT_PROMPT
# Savings: ~400 lines → ~100 lines (75% reduction, ~2-3K tokens saved)
