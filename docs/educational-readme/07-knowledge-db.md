# Chapter 7: Understanding the Codebase -- The Knowledge Graph

> **The problem:** An agent that can read files is useful. An agent that *understands* how the codebase is organized is something else entirely. Without structure, every question about the code requires the agent to read dozens of files from scratch, burning context and time. "What does the core module depend on?" shouldn't require reading 50 files to answer.

---

## The Idea: A Map, Not a Library

Imagine the difference between a library and a map of a city.

A library has all the books -- but to answer "how do I get from the airport to the hotel?" you'd have to read every travel guide and piece together the answer yourself.

A map answers that question instantly. It doesn't contain every detail, but it captures the *structure* -- what's where, what connects to what, how far apart things are.

ClarAIty's Knowledge DB is the map. The source code is the library. The agent uses the map to orient itself quickly, then dips into specific books (files) when it needs detail.

---

## What Gets Stored: A Property Graph

The Knowledge DB is a **property graph** -- two tables in SQLite: **nodes** and **edges**.

```
Nodes = things that exist in the codebase
Edges = relationships between them
```

A node might be a module, a component, a file, a decision, or an architectural invariant. An edge might say "core depends on llm" or "MemoryManager is the single writer to MessageStore".

The actual schema:

```sql
-- src/claraity/claraity_db.py, line 33
CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,    -- e.g. "mod-core", "comp-agent"
    type        TEXT NOT NULL,       -- module | component | file | decision | invariant | flow
    layer       INTEGER NOT NULL,    -- 1=system, 2=module, 3=component, 4=file
    name        TEXT NOT NULL,       -- human-readable name
    description TEXT,                -- what it does
    file_path   TEXT,                -- source file path
    line_count  INTEGER,             -- size indicator
    risk_level  TEXT DEFAULT 'low',  -- low | medium | high | critical (agent-assigned)
    properties  TEXT DEFAULT '{}'    -- JSON blob for arbitrary metadata
);

CREATE TABLE edges (
    id          TEXT PRIMARY KEY,
    from_id     TEXT NOT NULL,       -- FOREIGN KEY -> nodes(id), enforced by PRAGMA
    to_id       TEXT NOT NULL,       -- FOREIGN KEY -> nodes(id), enforced by PRAGMA
    type        TEXT NOT NULL,       -- uses | contains | constrains | calls | reads_writes
    weight      REAL DEFAULT 1.0,    -- reserved for future use (always 1.0 today)
    label       TEXT                 -- human-readable description of the relationship
);
```

A few things worth understanding about this schema:

**`risk_level` is agent judgment, not automated.** The default is `"low"`. When the knowledge-builder reads the code, it assigns higher levels based on what it finds -- `"high"` or `"critical"` for files touching authentication, persistence, security boundaries, or core message routing. No static analysis rule; the agent reads the file, understands what it does, and judges accordingly. This is one of the places where LLM understanding replaces what a traditional linter would infer from syntax.

**`weight` is a reserved field.** Always `1.0`; never set to anything else in the current codebase. It exists for future use cases -- relationship strength, call frequency, dependency criticality. No code currently reads it for any purpose.

**Foreign keys are declared AND enforced.** The schema declares `FOREIGN KEY` constraints on both `from_id` and `to_id`. SQLite only enforces those declarations when `PRAGMA foreign_keys = ON` -- and the codebase sets it on every connection (`claraity_db.py:88`). WAL journal mode is also enabled for concurrent read safety (`claraity_db.py:89`).

Simple. Two tables. But from this structure, the agent can answer questions that would otherwise require reading hundreds of files.

---

## Four Layers of Zoom

Nodes are organized into four layers, like a map with different zoom levels:

```
Layer 1 -- System Context
  The world around the codebase: User, VS Code Extension, LLM Providers,
  Local Filesystem, MCP Servers, Web APIs.
  "What does this system interact with?"

Layer 2 -- Modules
  Major subsystems: core, ui, memory, session, llm, tools, server, subagents...
  "What are the big moving parts?"

Layer 3 -- Components
  Key classes within modules: CodingAgent, MemoryManager, MessageStore,
  StreamingPipeline, SessionWriter, ToolGatingService...
  "What are the important pieces inside each module?"

Layer 4 -- Files
  Individual source files with descriptions extracted from docstrings.
  "Where exactly does this live?"
```

Zoom out to layer 1 and you see the whole system at a glance. Zoom in to layer 4 and you're looking at individual files. The agent uses whatever zoom level answers the current question.

---

## Decisions and Invariants: The Rules That Must Not Break

Beyond files and modules, the Knowledge DB stores two special node types that most knowledge systems don't capture:

**Decisions** -- architectural choices and the reasoning behind them.

```
Decision: "Tool List Fetch: On-Demand via Python (not disk)"
Rationale: Always fresh -- picks up MCP tools added mid-session.
           No startup overhead. config_loaded fires on every settings
           open so piggybacking would be wasteful.
```

**Invariants** -- constraints that must never be violated, tagged by severity.

```
[CRITICAL] Single Writer to MessageStore
  MemoryManager is the ONLY component authorized to write to MessageStore.
  If broken: race conditions, duplicate messages, broken seq ordering.

[CRITICAL] No Emojis in Python Code
  Windows uses cp1252 encoding which cannot encode emojis.
  If broken: application crashes with UnicodeEncodeError.

[HIGH] Always Use get_logger() Not logging.getLogger()
  If broken: log output appears on stdout, corrupting TUI rendering.
```

These aren't just documentation. The agent reads them before making changes. An invariant tagged `[CRITICAL]` is a hard constraint -- the agent knows not to violate it.

---

## Full-Text Search with FTS5

SQLite has a built-in full-text search engine called FTS5. ClarAIty adds a virtual table alongside the main nodes table:

```sql
-- src/claraity/claraity_db.py, line 101
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    node_id     UNINDEXED,
    node_type   UNINDEXED,
    name,
    description,
    extra_text,             -- edge labels + property values
    tokenize='unicode61'    -- Unicode-aware tokenization
);
```

This means the agent can ask questions in plain language:

```
knowledge_query(search="streaming message finalization")
knowledge_query(search="single writer AND MessageStore")
knowledge_query(search="compaction OR context window")
```

Results are ranked by relevance with highlighted snippets -- exactly like a search engine, but over the codebase's architectural knowledge rather than web pages.

Multi-word queries without explicit operators are automatically converted to OR queries (any matching word returns results, ranked by how many match). Explicit FTS5 syntax (`AND`, `NOT`, `"phrase"`, `prefix*`) passes through unchanged.

---

## Why SQLite? Why Not a Vector Database?

This question comes up immediately. Vector databases (Pinecone, Chroma, pgvector) are the fashionable choice for AI knowledge retrieval. Why SQLite?

| Property | SQLite + FTS5 | Vector DB |
|----------|--------------|-----------|
| **Installation** | Zero -- Python stdlib | Docker, server, API key |
| **Query type** | Keyword + structure | Semantic similarity |
| **Relationship queries** | Native SQL joins | Not supported |
| **Schema** | Enforced, typed | Schema-free |
| **Git-trackable** | Yes (via JSONL export) | No |
| **Offline** | Always | Often requires server |
| **Query transparency** | Exact match, reproducible | Probabilistic, varies |

For a *structured* knowledge graph -- where you want to ask "what does mod-core depend on?" or "find all critical invariants" -- SQL is the right tool. Vector search excels at "find me something semantically similar to this paragraph", which is less useful for architectural navigation.

The FTS5 table gives keyword search on top of the structured graph. You get the best of both: exact relationship traversal AND keyword discovery.

---

## The JSONL Export: Making It Git-Trackable

SQLite is a binary file. Binary files and git don't mix -- you can't diff them, review them in a PR, or see what changed.

So ClarAIty exports the entire database to a JSONL file after every knowledge scan:

```python
# src/claraity/claraity_db.py, line 1060
def export_jsonl(self, path=".claraity/claraity_knowledge.jsonl"):
    with open(out, "w", encoding="utf-8") as f:
        # Order: metadata first, then nodes, then edges (FK-safe)
        for key, value in self.get_metadata().items():
            f.write(json.dumps({"_t": "meta", "key": key, "value": value}) + "\n")
        for node in self.get_all_nodes():
            node["_t"] = "node"
            f.write(json.dumps(node) + "\n")
        for edge in self.get_all_edges():
            edge["_t"] = "edge"
            f.write(json.dumps(edge) + "\n")
```

The JSONL file is committed to git. The SQLite `.db` file is in `.gitignore`.

The pattern is the same as session persistence (Chapter 5): **JSONL is the ledger, SQLite is the derived projection**. If the `.db` file is missing or corrupted, it's rebuilt automatically from the JSONL on next startup:

```python
# src/claraity/claraity_db.py, line 76
if not self.db_path.exists():
    jsonl_path = self.db_path.with_suffix(".jsonl")
    if jsonl_path.exists():
        self._rebuild_from_jsonl(jsonl_path)  # Auto-import on startup
```

---

## The Architecture Diagram: Auto-Layout

Every module node has `flow_rank` and `flow_col` properties that position it in a dependency-ordered diagram. The agent computes these automatically using **Tarjan's algorithm** for strongly connected components, followed by a topological sort:

```
flow_rank = vertical position (0 = top, entry points; higher = deeper infrastructure)
flow_col  = horizontal position within a rank (most connected nodes in the center)
```

The result is a diagram where data flows top to bottom:

```
Row 0: User  VS Code Extension  LLM Providers  Filesystem
Row 1: ui         server
Row 2: core       director
Row 3: tools    memory    llm    subagents
Row 4: session  hooks    prompts
Row 5: observability  integrations  platform
```

This is what the trace panel in the VS Code sidebar renders -- not a hand-drawn diagram, but a computed layout from the live knowledge graph.

---

## What's Stored Right Now

For this repository, the knowledge graph contains:

```
Nodes:
  - 6  system nodes   (User, VS Code, LLM Providers, Filesystem, MCP, Web)
  - 22 module nodes   (core, ui, memory, session, llm, tools, server, ...)
  - 40+ component nodes (CodingAgent, MemoryManager, MessageStore, ...)
  - Decisions         (12 architectural decisions with rationale)
  - Invariants        (9 constraints with severity levels)
  - Files             (245 source files auto-scanned)

Edges:
  - uses / depends-on (module dependencies)
  - contains          (module contains component/file)
  - constrains        (invariant constrains component)
  - calls / reads_writes / communicates (system-level flows)
```

The agent uses this map before reading any file. "Which module handles session persistence?" is a graph query, not a file search. The answer is immediate.

---

## How the Knowledge Graph Gets Built

The knowledge-builder is a specialized subagent (`knowledge-builder`) with a restricted tool set: `read_file`, `list_directory`, `grep`, `glob`, plus the knowledge write tools. No write tools for code -- only for the DB.

It works in six phases:

```
Phase 1: Assess current state
  knowledge_query(show='brief') -- what's already in the DB?

Phase 2: Scan project structure
  list_directory(), glob() -- find the actual layout (src/, lib/, app/, etc.)
  The root is discovered, not assumed -- repos don't always have a src/ folder

Phase 3: Read the source code
  read_file()  -- entry points, key abstractions, large files (line-range targeted)
  grep()       -- trace imports, find callers, verify relationships
  glob()       -- locate files by pattern

  Stratified reading:
    Thorough:   entry points, base classes, facades, files >500 lines
    Selective:  utilities, helpers, data models
    Skip:       generated files, __pycache__, node_modules, lock files

Phase 4: Populate the DB
  knowledge_scan_files(root="src")
    -> Auto-seeds layer 4 file nodes
    -> Extracts description from Python AST docstring (accurate),
       or first comment line in first 15 lines (for TS/Go/Java/etc.),
       or leaves blank if neither exists
    -> This is a TIME SAVER, not a replacement for reading
       Files with no/bad comments get "" -- the subagent fills them in

  knowledge_update([...batch of add_node/update_node/add_edge ops...])
    -> System nodes (layer 1): User, VS Code, LLM Providers, DB...
    -> Module nodes (layer 2): one per major directory, real descriptions
       from reading the code -- not from comments
    -> Component nodes (layer 3): architecturally significant classes only
    -> Decisions and invariants: observed from reading the architecture
    -> Edges with meaningful labels: traced from actual import chains

  knowledge_set_metadata({repo_name, architecture_overview})
    -> 1500-2000 char narrative written by the agent after reading the code

Phase 5: Auto-layout + self-review
  knowledge_auto_layout() -- compute diagram positions
  knowledge_query(show='brief') -- verify the overview looks right
  knowledge_query(module_id='mod-core') -- spot-check a key module

Phase 6: Export
  knowledge_export() -- write JSONL for git tracking (always last)
```

**The key point:** comments and docstrings are a shortcut for files that already document themselves well. For everything else -- and for modules, components, decisions, and invariants -- the agent reads the actual code and builds its understanding the same way a senior engineer would onboard to a new codebase.

---

## How the Agent Uses It

In practice, a typical sequence looks like this:

```
User: "Why does the agent sometimes restart the streaming pipeline?"

Agent:
  1. knowledge_query(search="streaming pipeline restart")
     -> Finds: StreamingPipeline component, process_provider_delta()
     -> Finds: invariant "StreamingPipeline is the Single Canonical Parser"

  2. knowledge_query(file_path="src/memory/memory_manager.py")
     -> Role: sole writer to MessageStore, owns streaming pipeline
     -> Relevant decision: "MemoryManager resets pipeline on finalization"

  3. read_file("src/memory/memory_manager.py", start_line=580, end_line=598)
     -> Confirms: self._streaming_pipeline = None after finalization

  Agent: "The pipeline is reset to None after every stream finalization
          (line 587) -- by design. Each new assistant response creates
          a fresh pipeline via start_assistant_stream()..."
```

Two knowledge queries replaced what would otherwise be a blind search through 245 files.

---

## What's Next

The Knowledge DB captures static structure -- what exists, what depends on what, what rules apply. But sometimes the problem is harder: the codebase is unfamiliar, the task is complex, and you need a plan before you start touching files.

That's what Chapter 8 addresses: the Beads task tracker -- how ClarAIty tracks work across sessions so the agent never loses its place.

---

*Source files: `src/claraity/claraity_db.py`, `src/claraity/__init__.py`, `.claraity/claraity_knowledge.jsonl`*
