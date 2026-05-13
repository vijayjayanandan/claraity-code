# Chapter 2: Building the Mind -- The Context Builder

> **The problem:** A raw LLM call is stateless. Every time you call it, it starts fresh with no knowledge of your project, no memory of past conversations, no awareness of your coding standards, and no idea what tasks are in progress. Sending just the user's message is like hiring a brilliant contractor who shows up with no blueprints, no project history, and no tools list -- every single day.

---

## What Is Context?

Remember from Chapter 1: the LLM only sees what you put in the `messages` list. Nothing more. So the question becomes:

**What should you put in there -- and in what order?**

This is the job of the **Context Builder** (`src/core/context_builder.py`). Before every LLM call, it assembles a carefully ordered stack of information from multiple sources and packages it into a single `messages` list.

Think of it like preparing a briefing document for a consultant before every meeting. The consultant is brilliant but forgetful -- so you hand them everything they need, every time.

---

## The Six Layers

ClarAIty's context builder assembles information from six distinct sources, in this order:

```
+----------------------------------------------------------+
|  1. SYSTEM PROMPT   -- Agent identity, rules, safety     |
+----------------------------------------------------------+
|  2. CLARAITY.md     -- This project's instructions       |
+----------------------------------------------------------+
|  3. KNOWLEDGE DB    -- Architecture brief (auto-built)   |
+----------------------------------------------------------+
|  4. MEMORY FILES    -- Your preferences (enterprise/user)|
+----------------------------------------------------------+
|  5. PERSISTENT MEM  -- What the agent learned over time  |
+----------------------------------------------------------+
|  6. CONVERSATION    -- What was said in this session     |
+----------------------------------------------------------+
                    |
                    v
              [ LLM CALL ]
```

Each layer has a distinct **scope** and **owner**:

| Layer | Scope | Written by |
|-------|-------|-----------|
| System Prompt | All users, all projects | ClarAIty team |
| CLARAITY.md | This project | You or the agent |
| Knowledge DB | This project | Agent (auto-built) |
| Memory Files | All your projects | You or the agent (enterprise/user) |
| Persistent Memory | This project, cross-session | Agent (auto-written) |
| Conversation | This session | Both |

### Layer 1: System Prompt
The foundational instructions that define the agent's identity, capabilities, and rules. This is what makes the LLM behave like a coding agent rather than a chatbot. It includes safety rules, tool usage guidelines, and behavioral constraints.

```python
# src/core/context_builder.py, line 255
system_prompt = get_system_prompt(language=language, task_type=task_type)
```

### Layer 2: CLARAITY.md
A project-specific instruction file that lives in your repository root. It tells the agent about *this* codebase -- key files, gotchas, architectural decisions, coding conventions. The agent reads it once at startup and caches it for the session. The agent can also update it directly when you ask -- for example: *"Add this gotcha to CLARAITY.md so you remember it next time."*

```python
# src/core/context_builder.py, line 286
project_instructions = self._cached_project_instructions or ""
```

> ClarAIty's own repository has a `CLARAITY.md` with a full codebase map, known gotchas, and architectural decisions. Every project you use ClarAIty on can have its own -- the agent reads and applies it automatically.

### Layer 3: Knowledge DB
A compact architectural brief auto-generated from the project's knowledge graph (SQLite database). It summarises modules, components, key decisions, and invariants -- giving the agent an architectural awareness it would otherwise have to rediscover from scratch every session. Covered in depth in Chapter 7.

```python
# src/core/context_builder.py, line 304
knowledge_brief = self._cached_knowledge_brief or ""
```

### Layer 4: Memory Files (Enterprise + User)
Preferences and standards that apply across *all* your projects -- not just this one. Loaded from two locations:

- **Enterprise:** `C:/ProgramData/claraity/memory.md` (Windows) or `/etc/claraity/memory.md` (Mac/Linux) -- organisation-wide standards
- **User:** `~/.claraity/memory.md` -- your personal preferences across all projects

Examples of what lives here: *"I always prefer async/await"*, *"Use 2-space indentation"*, *"Never use `print()` for logging."*

The agent can write to these files on request. Enterprise-level writes are not yet wired up -- for now, add those manually.

### Layer 5: Persistent Memory
What the agent has learned about *this project specifically* across sessions. Stored in `.claraity/memory/` as individual markdown files, with `MEMORY.md` acting as an index. The agent writes these automatically -- you don't have to ask. Covered in depth in Chapter 2b.

```python
# src/core/context_builder.py, line 339
persistent_mem = self.memory.persistent_memory_content
```

### Layer 6: Conversation History
The actual back-and-forth of the current session -- every user message, every assistant reply, every tool call and its result. This is retrieved from the **Message Store** (covered in Chapter 5).

```python
# src/core/context_builder.py, line 382
memory_context = self.memory.get_context_for_llm(include_episodic=True)
```

---

## The Budget Problem

Here's the fundamental constraint: **context windows are finite.**

Models like GPT-4o have a context window of ~128,000 tokens. That sounds large -- until you add up a long conversation, a full codebase knowledge brief, memory files, tool schemas (38 tools!), and the user's query. It fills up fast.

ClarAIty tracks this with a `ContextAssemblyReport` (`src/core/context_builder.py`, line 27) that measures token usage across every bucket:

| Bucket | What it contains | Budget allocation |
|--------|-----------------|-------------------|
| System prompt | Identity + rules + CLARAITY.md + Knowledge DB + Memory | 15% of context |
| Tool schemas | Definitions of all 38 tools the LLM can call | ~3,000 tokens (fixed) |
| File references | Files the user explicitly attached | Variable |
| Agent state | In-progress tasks | Small |
| Conversation | The actual dialogue | Remainder |
| Reserved output | Space for the LLM's reply | 12,000 tokens |
| Safety buffer | Emergency headroom | 2,000 tokens |

The pressure level is tracked as a colour:

```
GREEN  < 60% used   -- plenty of headroom
YELLOW 60-80% used  -- getting full
ORANGE 80-90% used  -- approaching limit
RED    > 90% used   -- compaction needed
```

When it hits **RED**, compaction kicks in (Chapter 6).

---

## The Trace Panel Shows This Live

The **Context Builder** node in the trace panel diagram is not just a label -- when you press Play and watch a request being processed, you can see each of these five layers being fetched and assembled in real time. Each source lights up as it's loaded.

This is what makes ClarAIty different from a black-box AI: you can literally watch the context being assembled before the LLM is called.

---

## Why Caching Matters

Notice that layers 2, 3, and 4 are loaded **once at startup and cached** for the entire session:

```python
# src/core/context_builder.py, line 177
def _load_cached_sources(self) -> None:
    self._cached_project_instructions = self._load_project_instructions()
    self._cached_knowledge_brief = self._load_knowledge_brief()
```

CLARAITY.md and the knowledge DB don't change during a conversation. Reading them from disk or querying SQLite on every single LLM call would add latency to every response. Caching them eliminates that cost while keeping the context fresh.

---

## What's Still Missing

Even with five layers of context, there's still a problem: **what happens when the conversation gets so long it no longer fits?** A context window is a sliding window -- you can't keep everything forever.

That's what Chapters 5 and 6 address: how the conversation is stored, and what happens when it gets too long.

---

*Source files: `src/core/context_builder.py`, `src/prompts/system_prompts.py`, `src/memory/memory_manager.py`*
