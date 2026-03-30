# Markdown Knowledge Base - Implementation Plan

## Context

ClaraityDB (SQL) and its 16 tools have been disconnected from the agent. The SQL-based approach was not LLM-friendly - the agent had to query structured data through tools, adding token overhead and indirection. We're replacing it with a markdown knowledge base in `.claraity/knowledge/` that both the agent and user can read natively. The agent builds and maintains this knowledge through a dedicated subagent, and core knowledge is auto-loaded into every session.

---

## 1. Knowledge File Structure

```
.claraity/knowledge/
├── core.md              # Always loaded into context (~200 lines max)
├── architecture.md      # Module map, layers, data flows
├── file-guide.md        # Key files, what they do, their quirks
├── conventions.md       # Patterns, naming, do's and don'ts
├── decisions.md         # Why things are the way they are (ADR-style)
└── lessons.md           # Debugging insights, gotchas, session learnings
```

**`core.md`** (Layer 1 - always in context):
- Project name, purpose, tech stack
- Architecture summary (5-10 lines)
- Top conventions and constraints
- **Knowledge Index** - maps topics to files so the agent knows what to read and when
- **Hard limit: 200 lines** - context window is precious

Example `core.md` structure:
```markdown
# ClarAIty - Project Knowledge

## Overview
AI-powered coding agent with TUI interface. Python 3.10, Textual, OpenAI-compatible LLMs.

## Architecture (summary)
User -> CodingAgent -> MemoryManager -> MessageStore -> JSONL files
                                             |
                                      StoreAdapter (read) -> TUI

## Key Constraints
- No emojis in Python (Windows cp1252)
- StoreAdapter is READ-ONLY, MemoryManager is single writer
- Use get_logger() not logging.getLogger()

## Knowledge Index
When working on a task, read the relevant knowledge file first:
| Topic | File | Read when... |
|-------|------|-------------|
| Module relationships, data flows | .claraity/knowledge/architecture.md | Refactoring, adding features, understanding dependencies |
| What each file does, key methods | .claraity/knowledge/file-guide.md | Navigating the codebase, finding where to make changes |
| Coding patterns, naming, style | .claraity/knowledge/conventions.md | Writing new code, reviewing code |
| Why things are built this way | .claraity/knowledge/decisions.md | Questioning a design choice, considering alternatives |
| Past bugs, gotchas, debugging tips | .claraity/knowledge/lessons.md | Debugging, hitting unexpected behavior |

## Maintaining This Knowledge Base
After completing a significant task, update the relevant file if you:
- Discovered a new pattern or convention -> conventions.md
- Hit a gotcha or debugging insight -> lessons.md
- Changed architecture or added a module -> architecture.md
- Learned what a file does or its quirks -> file-guide.md
- Made or understood a design choice -> decisions.md

Do NOT update for: trivial fixes, session-specific context, or things already documented.
Keep core.md under 200 lines. Put details in topic files.
```

The key insight: **`core.md` is the instruction manual for the knowledge base itself.**
Since it's always loaded, the agent always knows:
- What knowledge files exist (the index)
- When to read which file (the "Read when..." column)
- When to update which file (the "Maintaining" section)
- What's worth saving and what's not (the do/don't rules)

No system prompt changes needed. The knowledge base is self-governing.

**Other files** (Layer 2 - agent reads based on the index above):
- No hard size limit, but aim for concise
- Agent sees the index in `core.md` every session and reads the relevant file before starting work
- User reads them in VS Code / GitHub

---

## 2. No New Tools Needed

The whole point of markdown is that it's just files. The agent already has everything it needs:

| Operation | Existing Tool | Example |
|-----------|--------------|---------|
| **Read knowledge** | `read_file` | `read_file(".claraity/knowledge/architecture.md")` |
| **Write/update knowledge** | `edit_file` / `write_file` | Edit a section, append a learning |
| **Build full knowledge base** | `delegate_to_subagent` | Delegate to `knowledge-builder` subagent |
| **Search knowledge** | `grep` / `search_code` | Search across knowledge files |

**Zero new tools. Zero new schemas. Zero additional token overhead.**

The agent is guided by system prompt instructions on when and how to maintain the knowledge files.

---

## 3. Knowledge-Builder Subagent

### Configuration
- **Name:** `knowledge-builder`
- **Purpose:** Reads the codebase and generates/updates `.claraity/knowledge/` files
- **Tools available:** `read_file`, `write_file`, `edit_file`, `list_directory`, `search_code`, `grep`, `glob` (read-heavy, write to knowledge files only)
- **Prompt:** Instructs the subagent to explore the codebase systematically and produce structured markdown files

### Prompt design
The subagent prompt should instruct it to:
1. Scan the project structure (`src/`, `tests/`, config files)
2. Read key files (agent.py, app.py, memory_manager.py, etc.)
3. Identify architecture layers, module responsibilities, data flows
4. Document conventions found in the code (naming, patterns, error handling)
5. Write findings to `.claraity/knowledge/*.md` files
6. Accept a `scope` parameter: `full` (regenerate all) or `incremental` (update specific topic)

### Registration
- Add to `src/subagents/config.py` alongside existing subagents (code-reviewer, test-writer, etc.)
- Add subagent prompt file at `.claraity/agents/knowledge-builder.md`

### Invocation
The agent delegates using its existing tool:
```
delegate_to_subagent(subagent="knowledge-builder", task="Build the full knowledge base for this project")
```

---

## 4. Auto-Loading Core Knowledge

### Approach: Extend `MemoryManager.get_context_for_llm()`

Add a new injection point after file memories (line 820) that loads `.claraity/knowledge/core.md`:

```python
# After line 820 in memory_manager.py
# 2b. Project knowledge base (core)
knowledge_core = self._load_knowledge_core()
if knowledge_core:
    context.append({
        "role": "system",
        "content": f"Project knowledge base:\n{knowledge_core}",
    })
```

### `_load_knowledge_core()` method
- Reads `.claraity/knowledge/core.md` if it exists
- Truncates to 200 lines max
- Caches the content (reload on file change or once per session)
- Returns empty string if file doesn't exist (graceful degradation)

### Why not extend `file_loader.py`?
The existing file loader uses `.opencodeagent/memory.md` with its own hierarchy. The knowledge base is a separate concern with different semantics (project knowledge vs user preferences). Keeping them separate avoids confusion.

---

## 5. Incremental Updates

All update instructions live in `core.md` itself (always loaded, self-governing). No system prompt changes needed.

### Via agent judgment (guided by core.md)
After significant work, the agent checks the "Maintaining This Knowledge Base" section in `core.md` and updates the relevant file using `edit_file`. The rules for what's worth saving and what's not are right there in the loaded context.

### Via user request
- "Build the knowledge base" -> agent delegates to `knowledge-builder` subagent
- "Update the knowledge base" -> agent delegates incremental update
- "Save what you learned" -> agent uses `edit_file` to append to `lessons.md`

---

## 6. Files to Create

| File | Purpose |
|------|---------|
| `.claraity/knowledge/core.md` | Template - initially empty, populated by subagent |
| `.claraity/knowledge/architecture.md` | Template |
| `.claraity/knowledge/file-guide.md` | Template |
| `.claraity/knowledge/conventions.md` | Template |
| `.claraity/knowledge/decisions.md` | Template |
| `.claraity/knowledge/lessons.md` | Template |
| `.claraity/agents/knowledge-builder.md` | Subagent prompt |

## 7. Files to Modify

| File | Change |
|------|--------|
| `src/memory/memory_manager.py` | Add `_load_knowledge_core()` and inject into `get_context_for_llm()` after line 820 |
| `src/subagents/config.py` | Add `knowledge-builder` subagent config |

No changes needed to `system_prompts.py` - all instructions live in `core.md` itself.

---

## 8. Implementation Order

1. **Create knowledge directory and templates** - `.claraity/knowledge/*.md` with section headers
2. **Create knowledge-builder subagent** - prompt file at `.claraity/agents/knowledge-builder.md` + config in `src/subagents/config.py`
3. **Add auto-loading** - `_load_knowledge_core()` in `memory_manager.py`
4. **Test** - run agent, delegate to knowledge-builder, verify files populated, verify `core.md` loads

---

## 9. Verification

1. **Subagent delegation:** Start agent, ask "build the knowledge base" - agent should delegate to `knowledge-builder` subagent
2. **Knowledge generation:** Verify `.claraity/knowledge/` files are populated with meaningful content
3. **Auto-loading:** Start a new session, ask "what do you know about this project?" - should reference `core.md` content without needing to read it
4. **Incremental update:** Complete a task, ask agent to update knowledge - verify relevant file updated via `edit_file`
5. **User readability:** Open `.claraity/knowledge/architecture.md` in VS Code - should be clear, well-structured markdown
6. **No new tools:** `python -c "from src.tools.tool_schemas import ALL_TOOLS; print(len(ALL_TOOLS))"` - should still show 29 (unchanged)
7. **Tests:** `pytest tests/` - no regressions
