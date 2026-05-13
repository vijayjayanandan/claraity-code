# Chapter 8: Remembering What to Do -- The Beads Task Tracker

> **The problem:** An AI agent can hold a conversation. It can read files, run code, and reason about problems. But across sessions -- when you close the IDE and come back tomorrow -- it remembers nothing. It doesn't know what it was working on, what's blocked, what comes next. Every session starts from scratch. You end up managing the agent's to-do list yourself, in your head, which defeats the purpose.

---

## What Are Beads?

Beads is ClarAIty's built-in task tracker. Not a plugin, not a third-party integration -- it lives directly inside the agent. The agent can create tasks, update them, link them, note progress, and pick up where it left off across sessions.

The name comes from Steve Yegge's [Beads system](https://github.com/steveyegge/beads) -- the idea of stringing work items together into a dependency graph, like beads on a wire.

Every task you see in the agent's sidebar (`bd-c4bb0a76`, `bd-0f27ff0a`, etc.) is a bead, stored in a SQLite database at `.claraity/claraity_beads.db`.

---

## The Two Files

Beads uses the same dual-persistence pattern as the Knowledge DB (Chapter 7):

```
.claraity/
  claraity_beads.db      -- SQLite (fast, queryable, the working copy)
  claraity_beads.jsonl   -- JSONL  (git-trackable, the ledger)
```

The SQLite DB is the live database the agent reads and writes during a session. The JSONL file is the git-tracked export -- every task, every dependency, every note, one JSON object per line. When you clone the repo or switch branches, the JSONL is what travels with you. The SQLite DB is rebuilt from it on startup if it's missing.

```python
# src/claraity/claraity_beads.py, line 187
if not self.db_path.exists():
    jsonl_path = self.db_path.with_suffix(".jsonl")
    if jsonl_path.exists():
        rebuilt = BeadStore.import_jsonl(str(jsonl_path), str(self.db_path))
```

---

## The Schema: Five Tables

The database has five tables, each with a clear responsibility:

```
beads          -- the tasks themselves
dependencies   -- relationships between tasks
bead_refs      -- links from tasks to knowledge DB components
notes          -- timestamped progress notes on a task
events         -- full audit trail (every status change, claim, etc.)
```

### beads -- the tasks

Every bead (task) has:

| Column | What it stores | Example |
|--------|---------------|---------|
| `id` | Short deterministic hash | `bd-0f27ff0a` |
| `title` | One-line summary | `"README Step 8: Beads"` |
| `description` | Why it exists, what to do | Full context paragraph |
| `status` | Current state (see lifecycle below) | `"open"` |
| `priority` | 0 (highest) to 9 (lowest) | `3` |
| `issue_type` | bug / feature / task / epic / chore / decision | `"task"` |
| `parent_id` | Parent epic (FK to beads.id) | `"bd-ac608b45"` |
| `tags` | JSON array of labels | `["readme", "beads"]` |
| `design` | Technical approach notes | Architecture decisions |
| `acceptance_criteria` | Definition of done | Checklist |
| `estimated_minutes` | Effort estimate | `45` |
| `external_ref` | Jira/GitHub ticket link | `"gh-123"` |
| `defer_until` | ISO8601 date -- don't show until then | `"2026-05-01"` |
| `last_activity` | Timestamp of last update | Used for stale claim detection |

### dependencies -- how tasks relate

Dependencies define execution order. They come in two flavours:

**Blocking** (prevent a task from starting):
- `blocks` -- Task A must finish before Task B can start
- `conditional-blocks` -- Task A conditionally blocks Task B
- `waits-for` -- Task A is waiting on an external signal

**Association** (informational, don't affect the ready queue):
- `discovered-from` -- this task was found while working on another
- `caused-by` -- this task exists because of a bug/decision elsewhere
- `related` -- loosely related work
- `validates` -- this task verifies another
- `supersedes` -- this task replaces an older one

```python
# src/claraity/claraity_beads.py, line 56
BLOCKING_DEP_TYPES = ("blocks", "conditional-blocks", "waits-for")
```

### notes -- progress log

Notes are append-only timestamped text entries on a task. The agent adds them automatically at session end to record what was done and what remains. This is how context survives across sessions -- the next session reads the notes and picks up exactly where the previous one left off.

```
- [2026-04-22T12:27] (agent) Extracted middleware. 3 call sites remaining.
```

### events -- the audit trail

Every status change, every claim, every reopen is recorded in the `events` table automatically. You can ask the agent "what happened to task bd-0f27ff0a?" and it will show you the full history.

```
[2026-04-22T08:00] created -> open
[2026-04-22T12:15] status_changed: open -> in_progress
[2026-04-22T12:27] released: claraity:session-abc -> agent
```

---

## Task IDs: Deterministic, Not Random

Most task trackers assign sequential IDs (JIRA-123, #456). Beads uses **deterministic hash IDs** instead:

```python
# src/claraity/claraity_beads.py, line 249
@staticmethod
def _make_id(name: str) -> str:
    h = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"bd-{h}"
```

The ID is derived from the task title (or the dep pair for dependencies). This means:
- Creating the same task twice produces the same ID -- it's idempotent (`INSERT OR IGNORE`)
- IDs are stable across branches and clones
- You can reference a task ID in code or comments and it will always point to the right thing

The tradeoff: if you rename a task, its ID changes. For that reason, the title is treated as the stable identifier -- rename with care.

---

## The Task Lifecycle

```
         open
        /    \
 in_progress  deferred  (parked for now)
     |
   closed     blocked   (unmet dependencies)
              pinned    (persistent context, always visible)
```

The key transition is from `open` to `in_progress`. This happens via **claiming**:

```python
# src/claraity/claraity_beads.py, line 378
def claim(self, bead_id: str, claimant: str) -> bool:
    """Atomically claim a task (compare-and-swap on assignee)."""
    cur.execute(
        """UPDATE beads
           SET assignee=?, status='in_progress', updated_at=?, last_activity=?
           WHERE id=?
           AND (assignee IS NULL OR assignee = '' OR assignee = 'agent')""",
        (claimant, now, now, bead_id),
    )
    if cur.rowcount == 0:
        return False  # already claimed by someone else
```

The SQL `WHERE` clause is an atomic compare-and-swap: the update only succeeds if the task is still unassigned. This is how multiple parallel agent sessions can safely pick up tasks without double-claiming. If the rowcount is 0, the task was already grabbed.

---

## The Ready Queue

The most important query in the whole system: **what can I work on right now?**

```python
# src/claraity/claraity_beads.py, line 720
def get_ready(self) -> list[dict]:
    """Get beads that are open and available for work.
    The ready frontier: tasks an agent can start right now."""
```

A task is **ready** if ALL of the following are true:
1. Status is `open` (or `in_progress` with a stale claim -- more than 30 minutes idle)
2. Not pinned or deferred (or defer_until has passed)
3. Has no blocking dependencies that are still unresolved

The SQL expresses this as a subquery exclusion:

```sql
AND b.id NOT IN (
    SELECT d.to_id FROM dependencies d
    JOIN beads blocker ON d.from_id = blocker.id
    WHERE d.dep_type IN ('blocks', 'conditional-blocks', 'waits-for')
    AND blocker.status NOT IN ('closed', 'pinned')
)
```

In plain English: "don't show me this task if anything that blocks it is still open." This is the dependency graph doing its job -- you see only actionable work.

---

## Stale Claim Recovery

What happens if an agent session crashes mid-task? The task would be stuck `in_progress` forever, claimed by a dead session. Beads handles this with **stale claim detection**:

```python
# src/claraity/claraity_beads.py, line 541
STALE_CLAIM_MINUTES = 30
```

Any task that's been `in_progress` but hasn't had its `last_activity` timestamp updated in 30 minutes is treated as abandoned and reappears in the ready queue. The agent calls `touch()` at the end of each response stream to keep claims fresh.

On graceful shutdown, `release_session()` returns all claimed tasks back to the pool explicitly:

```python
# src/claraity/claraity_beads.py, line 564
def release_session(self, session_id: str) -> int:
    """Release all tasks claimed by this session back to the pool."""
```

---

## JSONL Export: Git as the Backup

At any point, the entire database can be exported to JSONL:

```python
# src/claraity/claraity_beads.py, line 787
def export_jsonl(self, path: str = ".claraity/claraity_beads.jsonl") -> int:
    """Export entire DB to JSONL for git tracking. Returns line count.
    Order: beads first, then dependencies, refs, notes, events (for FK-safe import)."""
```

The export order matters: beads must come before dependencies (which reference bead IDs), notes, and events. This ensures a clean sequential import with no foreign key violations.

Each record gets a `_t` field marking its type:

```json
{"_t": "bead", "id": "bd-0f27ff0a", "title": "README Step 8: Beads", ...}
{"_t": "dep",  "id": "bd-abc123", "from_id": "bd-0f27ff0a", "to_id": "bd-ac608b45", ...}
{"_t": "note", "id": "note-xyz", "bead_id": "bd-0f27ff0a", "content": "Done.", ...}
```

Commit the JSONL after a session ends and the full task graph -- every task, every note, every event -- travels with the repository. Switch branches, clone on a new machine, and the BeadStore rebuilds itself automatically.

---

## How the Agent Uses It

At session start, the agent calls `get_ready()` and renders the result into context via `render_tasks_md()`. This markdown summary of open and in-progress tasks is injected into the LLM's context (Chapter 2, Layer 6).

The agent interacts with Beads through a set of tools exposed to the LLM:
- `task_list` -- show the ready queue
- `task_show` -- full detail on one task
- `task_create` -- create a new task
- `task_update` -- start / close / note / defer / reopen
- `task_link` -- add a typed dependency

When the agent discovers new work while executing a task (a bug it noticed, a related refactor needed), it creates a linked task immediately rather than keeping it in its head:

```
task_create(title="...", deps="discovered-from:bd-current-task")
```

This is the mechanism that allows work to persist across sessions without relying on the agent's context window.

---

## Why Not Just Use GitHub Issues?

Good question. The answer is latency and context.

GitHub Issues require a network call, an API key, and a format optimized for humans reading in a browser. Beads is local SQLite -- zero latency, no auth, structured for programmatic access. More importantly, the ready queue query (dependency resolution, stale claim detection, defer_until filtering) would require complex GitHub API calls to reproduce. The agent can query Beads in a single SQL statement.

The `external_ref` field is the bridge: a bead can link to a GitHub issue (`gh-123`) or a Jira ticket (`jira-CC-42`) without being hosted there. The internal task tracker manages execution state; the external tracker manages stakeholder communication.

---

*Source files: `src/claraity/claraity_beads.py`*
