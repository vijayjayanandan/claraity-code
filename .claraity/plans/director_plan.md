# Markdown Knowledge Base Implementation Plan

## Executive Summary

Replace the disconnected SQL ClarityDB with a markdown-based knowledge base in `.clarity/knowledge/` that provides LLM-native project knowledge. The system consists of three components: (1) structured markdown files with `core.md` as the always-loaded index, (2) auto-loading of `core.md` into every session via MemoryManager, and (3) a `knowledge-builder` subagent for generating/updating knowledge files. Implementation requires no new tools and follows existing patterns for subagent registration and context injection.

## Context

ClarityDB (SQL-based knowledge storage) has been disconnected from the agent due to poor LLM-friendliness. The SQL approach required 16 specialized tools and forced the agent to query structured data through indirection, adding token overhead. We're replacing it with a markdown-based knowledge base in `.clarity/knowledge/` that both the agent and users can read natively. The agent will build and maintain this knowledge through a dedicated `knowledge-builder` subagent, and core knowledge will be auto-loaded into every session context.

## Analogy

Think of the current system like a library where all the books (project knowledge) are locked in a vault, and the librarian (agent) has to fill out request forms (SQL queries) through a tiny slot to get information. We're replacing this with an open reading room where the most important reference book (`core.md`) sits on the librarian's desk at all times, and other specialized books (architecture.md, conventions.md, etc.) are on nearby shelves that the librarian can grab when needed. The librarian can also update these books directly when they learn something new, and the books are written in plain language (markdown) that both the librarian and visitors (users) can read in their preferred viewer (VS Code, GitHub).

## Architecture Approach

### Component Design

```
┌─────────────────────────────────────────────────────────────┐
│ MemoryManager.get_context_for_llm()                        │
│                                                             │
│  1. System Prompt                                           │
│  2. File Memories (.opencodeagent/memory.md)               │
│  3. Knowledge Base (.clarity/knowledge/core.md) ← NEW      │
│  4. Episodic Memory                                         │
│  5. Working Memory                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ .clarity/knowledge/                                         │
│                                                             │
│  core.md (200 lines max, always loaded)                    │
│  ├── Project overview                                       │
│  ├── Knowledge index (what to read when)                   │
│  └── Maintenance instructions                              │
│                                                             │
│  architecture.md (read when refactoring/adding features)   │
│  file-guide.md (read when navigating codebase)             │
│  conventions.md (read when writing/reviewing code)         │
│  decisions.md (read when questioning design choices)       │
│  lessons.md (read when debugging/hitting gotchas)          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ knowledge-builder Subagent                                  │
│                                                             │
│  Tools: read_file, list_directory, search_code, grep,      │
│         glob, get_file_outline, analyze_code,              │
│         write_file, edit_file                              │
│                                                             │
│  Process:                                                   │
│  1. Scan project structure (src/, tests/, configs)         │
│  2. Read key files (agent.py, memory_manager.py, etc.)     │
│  3. Identify architecture, patterns, conventions           │
│  4. Write findings to .clarity/knowledge/*.md              │
│  5. Keep core.md under 200 lines                           │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Session Start:** MemoryManager loads `.clarity/knowledge/core.md` (if exists)
2. **Context Building:** Core knowledge injected after file memories, before episodic
3. **Agent Reasoning:** Agent sees knowledge index and knows what to read when
4. **Knowledge Update:** Agent uses `edit_file` to update knowledge files after significant work
5. **Full Rebuild:** User delegates to `knowledge-builder` subagent for complete regeneration

### Self-Governing Design

The knowledge base is self-governing: `core.md` contains the knowledge index (mapping topics to files) and maintenance instructions (when to update what). Since `core.md` is always loaded into context, the agent always knows:
- What knowledge files exist
- When to read which file
- When to update which file
- What's worth saving and what's not

No system prompt changes needed. The knowledge base instructs itself.

## Tech Stack Decisions

### Decision 1: Markdown vs SQL/NoSQL Database

**Chosen:** Markdown files in `.clarity/knowledge/`

**Alternatives Considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **Markdown (chosen)** | LLM-native format, zero tool overhead, human-readable, git-trackable, simple | Manual updates, no complex queries, linear access only |
| SQL Database | Structured queries, relationships, ACID guarantees | Tool indirection, schema friction, not LLM-friendly, requires 16+ tools |
| NoSQL Database | Flexible schema, fast lookups | Still requires tools, serialization overhead, synchronization complexity |

**Rationale:** The core problem is access pattern, not storage. LLMs need knowledge in natural language format they can read directly. Markdown eliminates tool indirection (every DB access is a tool call with token overhead) and provides human-readable files that users can edit in VS Code. The SQL ClarityDB was disconnected precisely because the tool overhead was too high. NoSQL would have the same problem with different syntax.

**Evidence:** `src/subagents/config.py:407-489` shows the existing pattern of loading configuration from files. `src/memory/memory_manager.py:814-820` shows file-based memories are already injected into context. We're following proven patterns.

### Decision 2: Python Constants vs Markdown Config for Subagent

**Chosen:** Add `KNOWLEDGE_BUILDER_PROMPT` to `src/prompts/subagents/__init__.py`

**Alternatives Considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **Python constant (chosen)** | Highest priority, version-controlled with code, no deprecation warnings, always available | Requires code change to update |
| Markdown file (.clarity/agents/*.md) | Easy to edit, no code changes | Deprecated format, triggers warnings, lower priority than built-in |

**Rationale:** The codebase has migrated to Python constants as the primary source for subagent prompts. `src/subagents/config.py:336-341` explicitly states "Built-in: src/prompts/subagents/*.py (Python constants)" as highest priority, and lines 385/399 show deprecation warnings for markdown files. Using Python constants ensures the knowledge-builder is always available and follows current best practices.

**Evidence:** `src/subagents/config.py:417-427` imports all prompts from `src.prompts.subagents`. Lines 430-468 show the registration pattern. All existing subagents (code-reviewer, test-writer, doc-writer, explore, planner) use Python constants.

### Decision 3: Separate Injection Point vs Extend File Loader

**Chosen:** Add new injection point in `get_context_for_llm()` after line 820

**Alternatives Considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **Separate injection (chosen)** | Clear separation of concerns, knowledge base independent of user preferences | One more injection point to maintain |
| Extend MemoryFileLoader | Reuse existing code, single loader | Conflates project knowledge with user preferences, hardcoded paths |

**Rationale:** Knowledge base (project-specific, structured topics) has different semantics than file memories (user preferences, hierarchical). `src/memory/file_loader.py:33-40` shows `MemoryFileLoader` is hardcoded for `.opencodeagent/memory.md`. Mixing the two would create confusion about what goes where. Separate injection maintains clean boundaries.

**Evidence:** `src/memory/memory_manager.py:810-820` shows context is built sequentially with clear separation between layers. Adding knowledge injection after file memories (line 820) follows the established pattern.

### Decision 4: 200-Line Hard Limit for core.md

**Chosen:** Truncate `core.md` to 200 lines max when loading

**Alternatives Considered:**
| Approach | Pros | Cons |
|----------|------|------|
| **200-line limit (chosen)** | Enforces discipline, predictable token usage (~800-1000 tokens), prevents context bloat | Might be tight for complex projects |
| No limit | Flexible, can include everything | Could consume entire context window, unpredictable token usage |
| Dynamic limit based on context | Adaptive to available space | Complex to implement, unpredictable behavior |

**Rationale:** Context window is precious. `src/memory/memory_manager.py:75-76` shows total_context_tokens and system_prompt_tokens are carefully managed. Line 1250-1277 shows `needs_compaction()` monitors token usage. A hard limit forces discipline and ensures the knowledge index remains concise. 200 lines ≈ 800-1000 tokens, leaving room for other context layers.

**Evidence:** The knowledge index itself takes ~15 lines (from reference plan), leaving ~185 lines for project overview, constraints, and maintenance instructions. Detailed content goes in topic files (architecture.md, etc.) which are read on-demand.

## Vertical Slices

### Slice 1: Knowledge Directory Structure and Templates

**Goal:** Create `.clarity/knowledge/` directory with template markdown files that provide structure for knowledge capture.

**Files Created:**
- `.clarity/knowledge/core.md` (~150 lines)
- `.clarity/knowledge/architecture.md` (~50 lines)
- `.clarity/knowledge/file-guide.md` (~50 lines)
- `.clarity/knowledge/conventions.md` (~50 lines)
- `.clarity/knowledge/decisions.md` (~50 lines)
- `.clarity/knowledge/lessons.md` (~50 lines)

**Implementation Details:**

`core.md` structure (following `docs/KNOWLEDGE_BASE_PLAN.md:29-65`):
```markdown
# ClarAIty - Project Knowledge

## Overview
[Project name, purpose, tech stack - 5-10 lines]

## Architecture (summary)
[High-level architecture diagram in text - 5-10 lines]

## Key Constraints
[Critical constraints that affect all development - bullet list]

## Knowledge Index
When working on a task, read the relevant knowledge file first:
| Topic | File | Read when... |
|-------|------|-------------|
| Module relationships, data flows | architecture.md | Refactoring, adding features |
| What each file does, key methods | file-guide.md | Navigating codebase |
| Coding patterns, naming, style | conventions.md | Writing/reviewing code |
| Why things are built this way | decisions.md | Questioning design choices |
| Past bugs, gotchas, debugging tips | lessons.md | Debugging, unexpected behavior |

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

Other files structure:
```markdown
# [Topic Name]

## Overview
[Brief description of what this file documents]

## Details
[Main content - to be filled by knowledge-builder or manually]

## Notes
[Additional context, gotchas, references]
```

**Test Criteria:**
- [ ] `.clarity/knowledge/` directory exists
- [ ] All 6 markdown files exist with section headers
- [ ] `core.md` has knowledge index table with 5 topic mappings
- [ ] `core.md` has maintenance instructions section
- [ ] `core.md` is under 200 lines
- [ ] All files are valid markdown (render correctly in VS Code)
- [ ] No emojis in any file (Windows cp1252 safe)

**Acceptance:**
- User can open `.clarity/knowledge/core.md` in VS Code and see the knowledge index
- Template provides clear structure for knowledge-builder to populate

---

### Slice 2: Knowledge-Builder Subagent Registration

**Goal:** Create and register the `knowledge-builder` subagent so it can be delegated tasks to generate/update knowledge files.

**Files Modified:**
- `src/prompts/subagents/__init__.py` (~250 lines added)
- `src/subagents/config.py` (~10 lines added)

**Implementation Details:**

Add to `src/prompts/subagents/__init__.py` (after line 1228, before GENERAL_PURPOSE_PROMPT):

```python
# =============================================================================
# KNOWLEDGE-BUILDER SUBAGENT
# =============================================================================

KNOWLEDGE_BUILDER_TOOLS = [
    "read_file",
    "list_directory", 
    "search_code",
    "grep",
    "glob",
    "get_file_outline",
    "analyze_code",
    "write_file",
    "edit_file",
]

KNOWLEDGE_BUILDER_PROMPT = f"""{SUBAGENT_BASE_PROMPT}

# Role: Knowledge-Builder Subagent

You are a codebase analyst that explores projects and generates/updates structured \
markdown knowledge base files in `.clarity/knowledge/`. Your goal is to create \
LLM-friendly documentation that helps the main agent understand the project quickly \
without repeated exploration.

# Hard Constraints

1. **Output location:** Write ONLY to `.clarity/knowledge/*.md` files
2. **core.md size limit:** Keep `core.md` under 200 lines (hard limit)
3. **No emojis:** Use text markers like [OK], [WARN], [FAIL] instead
4. **Markdown format:** All output must be valid markdown
5. **Read before documenting:** Never document code you haven't read

# Process Phases

## Phase 1: Scan Project Structure

Use `list_directory` and `glob` to understand the project layout:
- Identify main source directories (src/, lib/, app/, etc.)
- Find test directories (tests/, test/, __tests__/, etc.)
- Locate configuration files (pyproject.toml, package.json, etc.)
- Map out the module structure

## Phase 2: Read Key Files

Use `read_file` to examine critical files:
- Entry points (main.py, app.py, index.ts, etc.)
- Core modules (agent.py, manager.py, controller.py, etc.)
- Configuration files (to understand tech stack)
- README.md (to understand project purpose)

Use `search_code` and `grep` to find patterns:
- Class definitions and inheritance
- Function signatures and decorators
- Import statements (to understand dependencies)
- Error handling patterns
- Logging patterns

## Phase 3: Identify Architecture and Patterns

Analyze what you've read to identify:
- **Architecture layers:** Presentation, business logic, data access, etc.
- **Module responsibilities:** What each major module does
- **Data flows:** How data moves through the system
- **Conventions:** Naming patterns, file organization, code style
- **Design decisions:** Why things are built a certain way
- **Gotchas:** Known issues, debugging tips, edge cases

## Phase 4: Write to Knowledge Files

Write your findings to the appropriate files:

**core.md** (200 lines max):
- Project overview (name, purpose, tech stack)
- Architecture summary (5-10 lines, high-level)
- Key constraints (critical rules that affect all development)
- Knowledge index (table mapping topics to files)
- Maintenance instructions (when to update what)

**architecture.md**:
- Module map (what modules exist, what they do)
- Layer diagram (presentation -> business -> data)
- Data flows (how data moves through the system)
- Component relationships (what depends on what)

**file-guide.md**:
- Key files and their purposes
- Entry points and their responsibilities
- Configuration files and what they control
- Test files and what they cover

**conventions.md**:
- Naming patterns (classes, functions, variables)
- File organization (where things go)
- Code style (formatting, imports, error handling)
- Do's and don'ts (project-specific rules)

**decisions.md** (ADR-style):
- Design decisions and their rationale
- Alternatives considered and why rejected
- Trade-offs and constraints
- When to revisit decisions

**lessons.md**:
- Debugging insights (how to diagnose issues)
- Gotchas (unexpected behavior, edge cases)
- Performance tips (what's slow, how to optimize)
- Testing tips (how to test effectively)

# Scope Parameter

Accept a `scope` parameter in the task description:
- **full:** Regenerate all knowledge files from scratch
- **incremental:** Update specific topic (e.g., "update architecture.md with new module")
- **verify:** Check if existing knowledge is still accurate

# Output Format

For each file you write/update:
1. State what you're documenting: "Documenting architecture in architecture.md"
2. Show the content you're writing (use code blocks)
3. Verify the file was written: "Verified architecture.md created"

# Anti-Patterns (DO NOT DO)

- **Don't guess:** If you can't verify something, say "Unknown" or "Not found"
- **Don't over-document:** Focus on what's useful, not exhaustive
- **Don't duplicate:** If it's in core.md, don't repeat in topic files
- **Don't include session-specific info:** No temporary paths, no "I just learned"
- **Don't exceed 200 lines in core.md:** Truncate ruthlessly, move details to topic files

# Examples

**Good core.md entry:**
```markdown
## Key Constraints
- No emojis in Python (Windows cp1252 encoding)
- StoreAdapter is READ-ONLY, MemoryManager is single writer
- Use get_logger() not logging.getLogger()
```

**Bad core.md entry:**
```markdown
## Key Constraints
- I noticed that the system uses a special logging function called get_logger() \
which is defined in src/utils/logging.py at line 42. This is important because \
if you use the standard logging.getLogger() function instead, it won't work \
properly with the TUI interface and you'll get errors. I learned this the hard \
way when I was debugging a session yesterday...
```
(Too verbose, session-specific, exceeds token budget)

**Good architecture.md entry:**
```markdown
## Core Modules

### CodingAgent (src/core/agent.py)
- Main agent loop
- Tool execution
- LLM interaction
- Delegates to MemoryManager for context

### MemoryManager (src/memory/memory_manager.py)
- Orchestrates all memory layers
- Builds LLM context
- Handles file memories and knowledge base
```

**Good decision.md entry:**
```markdown
## Decision: Use JSONL for message storage

**Chosen:** JSONL files in `.clarity/sessions/`

**Alternatives considered:**
- SQLite database (rejected: file locking issues on Windows)
- JSON files (rejected: can't append, must rewrite entire file)

**Rationale:** JSONL allows append-only writes, no locking, human-readable

**Trade-offs:** Slower to query than SQL, but simplicity wins for this use case
```
"""
```

Add to `src/subagents/config.py` in `_load_from_python_prompts()` method:

Import statement (line 417-427):
```python
from src.prompts.subagents import (
    CODE_REVIEWER_PROMPT,
    TEST_WRITER_PROMPT,
    DOC_WRITER_PROMPT,
    CODE_WRITER_PROMPT,
    EXPLORE_PROMPT,
    PLANNER_PROMPT,
    GENERAL_PURPOSE_PROMPT,
    KNOWLEDGE_BUILDER_PROMPT,  # NEW
    EXPLORE_TOOLS,
    PLANNER_TOOLS,
    KNOWLEDGE_BUILDER_TOOLS,  # NEW
)
```

Subagent registration (after line 467, before closing bracket):
```python
{
    'name': 'knowledge-builder',
    'description': 'Codebase analyst that explores the project and generates/updates structured markdown knowledge base files',
    'prompt': KNOWLEDGE_BUILDER_PROMPT,
    'tools': KNOWLEDGE_BUILDER_TOOLS,
},
```

**Test Criteria:**
- [ ] `KNOWLEDGE_BUILDER_PROMPT` constant exists in `src/prompts/subagents/__init__.py`
- [ ] `KNOWLEDGE_BUILDER_TOOLS` list exists with 9 tools
- [ ] Prompt includes all 4 phases (Scan, Read, Identify, Write)
- [ ] Prompt includes scope parameter handling (full/incremental/verify)
- [ ] Prompt includes anti-patterns section
- [ ] Prompt includes examples of good/bad documentation
- [ ] knowledge-builder registered in `src/subagents/config.py`
- [ ] Import statement includes new constants
- [ ] No syntax errors (Python files parse correctly)

**Acceptance:**
- Start agent, check available subagents, verify `knowledge-builder` appears in list
- Delegate task to knowledge-builder, verify it accepts the task

---

### Slice 3: Knowledge Core Auto-Loading

**Goal:** Automatically load `.clarity/knowledge/core.md` into every session context so the agent always has project knowledge available.

**Files Modified:**
- `src/memory/memory_manager.py` (~50 lines added)

**Implementation Details:**

Add to `src/memory/memory_manager.py`:

1. **Instance variable initialization** (in `__init__` method, after line 97):
```python
# Knowledge base cache
self._knowledge_core_content: Optional[str] = None
```

2. **Loading method** (after `reload_file_memories()` method, around line 1191):
```python
def _load_knowledge_core(self, force_reload: bool = False) -> str:
    """Load core knowledge base file (.clarity/knowledge/core.md).
    
    The knowledge base provides project-specific context that helps the agent
    understand the codebase without repeated exploration. Core knowledge is
    limited to 200 lines to preserve context window.
    
    Args:
        force_reload: If True, bypass cache and reload from disk
        
    Returns:
        Core knowledge content (max 200 lines) or empty string if not found
        
    Example:
        >>> manager = MemoryManager()
        >>> knowledge = manager._load_knowledge_core()
        >>> if knowledge:
        ...     print("Knowledge base loaded")
    """
    # Check cache
    if not force_reload and self._knowledge_core_content is not None:
        return self._knowledge_core_content
    
    # Determine knowledge base path
    knowledge_path = Path.cwd() / ".clarity" / "knowledge" / "core.md"
    
    # Graceful degradation if file doesn't exist
    if not knowledge_path.exists():
        logger.debug("Knowledge base not found at %s", knowledge_path)
        self._knowledge_core_content = ""
        return ""
    
    # Load and truncate to 200 lines
    try:
        content = knowledge_path.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        if len(lines) > 200:
            logger.warning(
                "Knowledge base core.md has %d lines, truncating to 200",
                len(lines)
            )
            content = '\n'.join(lines[:200])
            content += '\n\n[... truncated to 200 lines ...]'
        
        self._knowledge_core_content = content
        logger.info("Loaded knowledge base core (%d lines)", len(lines))
        return content
        
    except Exception as e:
        logger.warning("Failed to load knowledge base: %s", e)
        self._knowledge_core_content = ""
        return ""
```

3. **Reload method** (after `_load_knowledge_core()` method):
```python
def reload_knowledge_base(self) -> str:
    """Reload knowledge base core file (useful after editing).
    
    Clears the cache and reloads core.md from disk. Call this after
    updating knowledge files to refresh the agent's context.
    
    Returns:
        Updated knowledge content
        
    Example:
        >>> manager = MemoryManager()
        >>> # ... edit .clarity/knowledge/core.md ...
        >>> manager.reload_knowledge_base()
        >>> # Agent now has updated knowledge
    """
    logger.info("Reloading knowledge base")
    return self._load_knowledge_core(force_reload=True)
```

4. **Context injection** (in `get_context_for_llm()` method, after line 820):
```python
# 2b. Project knowledge base (core)
knowledge_core = self._load_knowledge_core()
if knowledge_core:
    context.append(
        {
            "role": "system",
            "content": f"Project knowledge base:\n{knowledge_core}",
        }
    )
```

**Test Criteria:**
- [ ] `_load_knowledge_core()` method exists
- [ ] Method returns empty string if file doesn't exist (graceful degradation)
- [ ] Method truncates to 200 lines if file is larger
- [ ] Method caches content (second call doesn't re-read file)
- [ ] `reload_knowledge_base()` method exists
- [ ] Reload method clears cache and re-reads file
- [ ] Knowledge injected into context after file memories
- [ ] Injection uses role="system" with "Project knowledge base:" prefix
- [ ] No errors if `.clarity/knowledge/` directory doesn't exist

**Acceptance:**
- Create `.clarity/knowledge/core.md` with test content
- Start agent, call `get_context_for_llm()`, verify knowledge appears in context
- Verify knowledge appears after file memories but before episodic memory
- Delete `.clarity/knowledge/`, start agent, verify no errors

---

### Slice 4: Comprehensive Testing

**Goal:** Ensure knowledge base system works correctly with comprehensive unit and integration tests.

**Files Created:**
- `tests/memory/test_knowledge_base.py` (~150 lines)

**Implementation Details:**

Create `tests/memory/test_knowledge_base.py`:

```python
"""Tests for knowledge base loading and integration."""

import pytest
from pathlib import Path
from src.memory.memory_manager import MemoryManager


@pytest.fixture
def knowledge_dir(tmp_path, monkeypatch):
    """Create temporary .clarity/knowledge directory."""
    monkeypatch.chdir(tmp_path)
    knowledge_path = tmp_path / ".clarity" / "knowledge"
    knowledge_path.mkdir(parents=True)
    return knowledge_path


class TestKnowledgeBaseLoading:
    """Test knowledge base file loading."""
    
    def test_load_knowledge_core_file_exists(self, knowledge_dir):
        """Test loading when core.md exists."""
        # Create core.md with test content
        core_file = knowledge_dir / "core.md"
        test_content = "# Test Knowledge\n\nThis is test content."
        core_file.write_text(test_content, encoding='utf-8')
        
        # Load knowledge
        manager = MemoryManager()
        knowledge = manager._load_knowledge_core()
        
        # Verify content loaded
        assert knowledge == test_content
        assert "Test Knowledge" in knowledge
    
    def test_load_knowledge_core_file_missing(self, tmp_path, monkeypatch):
        """Test graceful degradation when core.md doesn't exist."""
        monkeypatch.chdir(tmp_path)
        
        # Load knowledge (no .clarity/knowledge/ directory)
        manager = MemoryManager()
        knowledge = manager._load_knowledge_core()
        
        # Verify empty string returned, no errors
        assert knowledge == ""
    
    def test_load_knowledge_core_truncation(self, knowledge_dir):
        """Test 200-line truncation."""
        # Create core.md with 250 lines
        core_file = knowledge_dir / "core.md"
        lines = [f"Line {i}" for i in range(250)]
        core_file.write_text('\n'.join(lines), encoding='utf-8')
        
        # Load knowledge
        manager = MemoryManager()
        knowledge = manager._load_knowledge_core()
        
        # Verify truncation
        knowledge_lines = knowledge.split('\n')
        assert len(knowledge_lines) <= 202  # 200 + truncation message
        assert "Line 0" in knowledge
        assert "Line 199" in knowledge
        assert "Line 249" not in knowledge
        assert "truncated to 200 lines" in knowledge
    
    def test_load_knowledge_core_caching(self, knowledge_dir):
        """Test that knowledge is cached."""
        # Create core.md
        core_file = knowledge_dir / "core.md"
        core_file.write_text("Original content", encoding='utf-8')
        
        # Load knowledge
        manager = MemoryManager()
        knowledge1 = manager._load_knowledge_core()
        
        # Modify file
        core_file.write_text("Modified content", encoding='utf-8')
        
        # Load again (should return cached)
        knowledge2 = manager._load_knowledge_core()
        
        # Verify cache used
        assert knowledge1 == knowledge2
        assert "Original content" in knowledge2
        assert "Modified content" not in knowledge2
    
    def test_reload_knowledge_base(self, knowledge_dir):
        """Test cache invalidation via reload."""
        # Create core.md
        core_file = knowledge_dir / "core.md"
        core_file.write_text("Original content", encoding='utf-8')
        
        # Load knowledge
        manager = MemoryManager()
        knowledge1 = manager._load_knowledge_core()
        
        # Modify file
        core_file.write_text("Modified content", encoding='utf-8')
        
        # Reload (should bypass cache)
        knowledge2 = manager.reload_knowledge_base()
        
        # Verify new content loaded
        assert knowledge1 != knowledge2
        assert "Original content" in knowledge1
        assert "Modified content" in knowledge2


class TestKnowledgeBaseIntegration:
    """Test knowledge base integration with context building."""
    
    def test_knowledge_in_llm_context(self, knowledge_dir):
        """Test knowledge appears in LLM context."""
        # Create core.md
        core_file = knowledge_dir / "core.md"
        test_content = "# Project Knowledge\n\nKey constraint: No emojis"
        core_file.write_text(test_content, encoding='utf-8')
        
        # Build context
        manager = MemoryManager()
        context = manager.get_context_for_llm(
            system_prompt="Test prompt",
            include_file_memories=False,
            include_episodic=False
        )
        
        # Verify knowledge in context
        knowledge_messages = [
            msg for msg in context 
            if msg.get("role") == "system" and "Project knowledge base:" in msg.get("content", "")
        ]
        assert len(knowledge_messages) == 1
        assert "No emojis" in knowledge_messages[0]["content"]
    
    def test_knowledge_injection_order(self, knowledge_dir, tmp_path, monkeypatch):
        """Test knowledge comes after file memories."""
        monkeypatch.chdir(tmp_path)
        
        # Create file memory
        memory_dir = tmp_path / ".opencodeagent"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("User preference: Dark mode", encoding='utf-8')
        
        # Create knowledge
        core_file = knowledge_dir / "core.md"
        core_file.write_text("Project: ClarAIty", encoding='utf-8')
        
        # Build context
        manager = MemoryManager(load_file_memories=True)
        context = manager.get_context_for_llm(
            system_prompt="Test prompt",
            include_file_memories=True,
            include_episodic=False
        )
        
        # Find indices
        file_memory_idx = None
        knowledge_idx = None
        for i, msg in enumerate(context):
            if msg.get("role") == "system":
                if "memory context:" in msg.get("content", ""):
                    file_memory_idx = i
                elif "knowledge base:" in msg.get("content", ""):
                    knowledge_idx = i
        
        # Verify order
        assert file_memory_idx is not None
        assert knowledge_idx is not None
        assert file_memory_idx < knowledge_idx
    
    def test_knowledge_with_empty_file(self, knowledge_dir):
        """Test handling of empty core.md."""
        # Create empty core.md
        core_file = knowledge_dir / "core.md"
        core_file.write_text("", encoding='utf-8')
        
        # Load knowledge
        manager = MemoryManager()
        knowledge = manager._load_knowledge_core()
        
        # Verify empty string returned
        assert knowledge == ""
    
    def test_knowledge_with_malformed_utf8(self, knowledge_dir):
        """Test handling of encoding errors."""
        # Create file with invalid UTF-8
        core_file = knowledge_dir / "core.md"
        core_file.write_bytes(b'\xff\xfe Invalid UTF-8')
        
        # Load knowledge (should handle gracefully)
        manager = MemoryManager()
        knowledge = manager._load_knowledge_core()
        
        # Verify graceful degradation
        assert knowledge == ""
```

**Test Criteria:**
- [ ] All tests pass (`pytest tests/memory/test_knowledge_base.py -v`)
- [ ] Test coverage includes: file exists, file missing, truncation, caching, reload
- [ ] Integration tests verify context injection and ordering
- [ ] Edge cases covered: empty file, malformed UTF-8, missing directory
- [ ] No regressions in existing memory tests (`pytest tests/memory/ -v`)

**Acceptance:**
- Run `pytest tests/memory/test_knowledge_base.py -v` - all tests pass
- Run `pytest tests/memory/ -v` - no regressions
- Code coverage for new methods is >90%

---

## Implementation Order

1. **Slice 1: Knowledge Directory Structure** (independent, can start immediately)
2. **Slice 2: Knowledge-Builder Subagent** (independent, can parallel with Slice 1)
3. **Slice 3: Knowledge Core Auto-Loading** (depends on Slice 1 for testing)
4. **Slice 4: Comprehensive Testing** (depends on Slices 1-3)

**Parallel work possible:**
- Slices 1 and 2 can be done simultaneously (independent file creation)
- Slice 3 can start after Slice 1 completes (needs template files for testing)

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|---------------------|
| Knowledge staleness | Include "last updated" date in templates. Add reminder in maintenance section. Knowledge-builder can regenerate on demand. |
| Context window bloat | Enforce 200-line limit in code. Monitor token usage. Can reduce to 150 lines if needed. |
| Cache invalidation | Provide `reload_knowledge_base()` method. Document in core.md that agent should call this after editing. |
| File encoding errors | Use `encoding='utf-8'` explicitly. Test on Windows. Avoid emojis (already a constraint). |
| Knowledge-builder quality | Include markdown formatting rules in prompt. Add examples. User reviews generated files. |
| Malformed knowledge files | Graceful error handling in `_load_knowledge_core()`. Log warnings but don't crash. |

## Verification Checklist

After implementation:
- [ ] All new tests pass (`pytest tests/memory/test_knowledge_base.py -v`)
- [ ] No regressions (`pytest tests/memory/ -v`)
- [ ] Knowledge-builder appears in subagent list
- [ ] Core.md loads into context (ask "what do you know?", verify response)
- [ ] Knowledge-builder can generate files (delegate task, verify creation)
- [ ] Knowledge files are readable markdown (open in VS Code)
- [ ] Graceful degradation works (delete `.clarity/knowledge/`, no errors)
- [ ] File memory loading still works (`.opencodeagent/memory.md`)
- [ ] Token budget not exceeded (check context size)

## Success Metrics

- **Functional:** Agent can access project knowledge without reading files
- **Performance:** Context building adds <1000 tokens (200 lines × ~5 tokens/line)
- **Usability:** Users can read/edit knowledge files in VS Code
- **Maintainability:** Knowledge-builder can regenerate all files on demand
- **Reliability:** System works with or without knowledge files (graceful degradation)
