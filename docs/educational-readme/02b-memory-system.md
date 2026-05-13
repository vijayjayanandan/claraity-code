# Chapter 2b: The Memory System -- Where Knowledge Lives

> **The problem:** An AI agent that forgets everything between sessions is like hiring a contractor who shows up each day with no memory of the blueprints, the client's preferences, or what was built yesterday. You'd spend half your time re-explaining context. The agent needs a structured way to remember -- at the right level, for the right duration.

---

## Two Kinds of Memory

Before diving into the details, it helps to understand the fundamental distinction:

**Memory you write** -- things you explicitly tell the agent about yourself, your team, or your projects. These are markdown files you (or the agent on your behalf) maintain.

**Memory the agent writes** -- things the agent figures out on its own during your sessions and saves for next time. User corrections, confirmed approaches, project decisions that only exist in conversation.

Both kinds are loaded into context before every LLM call. Neither requires you to repeat yourself across sessions.

---

## The Memory Hierarchy

ClarAIty uses a **4-level hierarchy** for memory files (`src/memory/file_loader.py`):

```
Level 1: Enterprise
  Windows:  C:/ProgramData/claraity/memory.md
  Mac/Linux: /etc/claraity/memory.md
  Scope: All users, all projects in an organisation
  Example: "Always use the internal logging library, never print()"

Level 2: User
  Path: ~/.claraity/memory.md
  Scope: You, across all your projects
  Example: "I prefer async/await. I use dark mode. Verbose error messages."

Level 3: Project (covered by CLARAITY.md and Knowledge DB instead)
  Not used -- project-level memory has dedicated mechanisms

Level 4: Imports (@syntax)
  Any memory file can pull in another: @./docs/architecture.md
  Max depth: 5 levels, circular imports detected and blocked
```

All levels are loaded at startup, combined, and injected into the system prompt. Lower levels load first; higher levels can override.

```python
# src/memory/file_loader.py, line 50
def load_hierarchy(self, starting_dir: Path | None = None) -> str:
    # Level 1: Enterprise
    # Level 2: User (~/.claraity/memory.md)
    # Level 3: Project (traverses upward -- not used for project level)
```

---

## The Agent-Managed Memory (Persistent Memory)

Separate from the hierarchy above, the agent maintains its own memory store for *this project* across sessions. This lives in:

```
.claraity/
  memory/
    MEMORY.md          ← Index file (one line per memory, links to files below)
    user-profile.md    ← Who the user is, how they work
    feedback.md        ← Corrections and confirmed approaches
    project-context.md ← Decisions and context not in the code
    references.md      ← External resources, dashboards, docs
```

`MEMORY.md` acts as a lightweight index -- each line points to a memory file with a one-line description. The agent reads the index on every session start, then reads individual files only when they seem relevant to the current task.

```markdown
# Example MEMORY.md
- [User profile](user-profile.md) -- project owner, prefers plan-first approach
- [Communication style](communication-style.md) -- concise responses, no emojis
- [Build process](build-process.md) -- PyInstaller + esbuild + vsce package
```

The agent writes to these files automatically during a session when it learns something worth remembering:
- User corrects an approach → saved to `feedback.md`
- User mentions a preference → saved to `user-profile.md`
- A project decision is made in conversation → saved to `project-context.md`
- An external resource is referenced → saved to `references.md`

---

## What the Agent Chooses to Remember

Not everything gets saved -- the agent applies judgement about what's worth persisting. The rule of thumb:

| Save this | Don't save this |
|-----------|----------------|
| User corrections ("don't do X") | Code patterns (read the code) |
| Confirmed approaches ("yes, exactly like that") | Git history (use git log) |
| User role, preferences, expertise | Debugging steps (fix is in the code) |
| Project decisions only in conversation | Things already in CLARAITY.md |
| External resource locations | Current task progress (ephemeral) |

---

## The @Import System

Memory files can pull in other markdown files using the `@` syntax:

```markdown
# ~/.claraity/memory.md
I prefer async/await for all async operations.
My default stack is Python + TypeScript + React.

@./docs/my-coding-standards.md
@./team/shared-preferences.md
```

Security rules enforced by `src/memory/file_loader.py`:
- Only `.md` files allowed
- Absolute paths blocked
- Imports restricted to project root or `~/.claraity/`
- Maximum 5 levels of nesting (circular imports detected)

---

## Writing to Memory

The agent can write to memory layers based on the scope of what needs to be remembered:

| What to remember | Where the agent writes |
|-----------------|----------------------|
| "Remember I prefer verbose errors across all projects" | `~/.claraity/memory.md` |
| "Add this gotcha to the project instructions" | `CLARAITY.md` |
| "Remember this architecture decision" | Knowledge DB |
| "Remember what we agreed today" | `.claraity/memory/` |

> **Note:** Writing to enterprise-level memory (`C:/ProgramData/claraity/memory.md`) is not yet wired up -- add those manually for now.

---

## Why Markdown Files, Not a Database?

You might wonder why memory is stored as `.md` files rather than in a database like the Knowledge DB.

**Three reasons:**

1. **Git-trackable** -- markdown files are diffable, committable, and reviewable. Your team can see exactly what the agent has learned and correct it via a PR.
2. **Human-readable** -- you can open any memory file in VS Code and read or edit it directly. No special tooling needed.
3. **Agent-editable** -- the agent can write plain text files with standard file tools. No SQL, no schema migrations.

The Knowledge DB (Chapter 7) uses SQLite for structured graph data that needs querying. Memory files use markdown for prose that needs to be read by humans and LLMs alike.

---

## What's Still Missing

With six layers of context and a persistent memory system, the agent now knows who you are, what your project does, and what was decided in past sessions. But it still can't *do* anything. It can describe how to write a file -- it just can't actually write one.

That changes in Chapter 3.

---

*Source files: `src/memory/file_loader.py`, `src/memory/memory_manager.py`, `src/core/context_builder.py`*
