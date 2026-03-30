# Beads Gap Analysis: Original vs ClarAIty

Study of [steveyegge/beads](https://github.com/steveyegge/beads) (Go/Dolt) compared to our `src/claraity/claraity_beads.py` (Python/SQLite).

---

## 1. SCHEMA COMPARISON

### Original: 15 tables + 2 views + 5 wisp tables

| Table | Purpose | ClarAIty Equivalent |
|-------|---------|-------------------|
| `issues` | Primary work items (~55 columns) | `beads` (12 columns) |
| `dependencies` | Typed relationships (18+ types) | `dependencies` (1 type: blocks) |
| `labels` | Normalized label table | `tags` JSON column |
| `comments` | Threaded discussion | `notes` table (flat) |
| `events` | Audit trail (created, updated, status_changed, etc.) | None |
| `config` | Key-value settings | None |
| `metadata` | Project metadata | None |
| `child_counters` | Hierarchical ID tracking (bd-abc.1, bd-abc.2) | None (uses parent_id FK) |
| `issue_snapshots` | Compaction snapshots | None |
| `compaction_snapshots` | Tiered compaction storage | None |
| `repo_mtimes` | File sync tracking | None |
| `routes` | Repo routing for federation | None |
| `issue_counter` | Sequential ID mode | None |
| `interactions` | AI interaction tracking (prompts, responses, tokens) | None |
| `federation_peers` | Multi-repo federation | None |
| `wisps` | Ephemeral work items (same schema as issues) | None |
| `wisp_labels/deps/events/comments` | Wisp auxiliary tables | None |
| **VIEW** `ready_issues` | Pre-computed ready frontier | Computed in Python |
| **VIEW** `blocked_issues` | Pre-computed blocked set | Computed in Python |

### Original `issues` table: Key columns we're missing

```sql
-- Status & workflow
status VARCHAR(32)          -- open|in_progress|blocked|deferred|closed|pinned|hooked + custom
issue_type VARCHAR(32)      -- bug|feature|task|epic|chore|decision|message|molecule|event + custom

-- Content (beyond title/description)
design TEXT                 -- Design notes
acceptance_criteria TEXT    -- Definition of done
spec_id VARCHAR(1024)       -- Linked specification

-- Scheduling
due_at DATETIME             -- Deadline
defer_until DATETIME        -- Hidden from ready until this date

-- External integration
external_ref VARCHAR(255)   -- e.g., gh-9, jira-ABC-123
source_system VARCHAR(255)  -- Federation source

-- Assignment
owner VARCHAR(255)          -- Human owner (git author email)
estimated_minutes INT       -- Effort estimate

-- Compaction metadata
compaction_level INT        -- 0=none, 1=tier1, 2=tier2
compacted_at DATETIME
original_size INT

-- Close detail
close_reason TEXT           -- Why it was closed (vs our summary which is what was done)
closed_by_session VARCHAR   -- Which session closed it

-- Metadata
metadata JSON               -- Arbitrary extension JSON

-- Gate/await fields
await_type VARCHAR(32)      -- gh:run|gh:pr|timer|human|mail
await_id VARCHAR(255)       -- PR number, run ID, etc.
timeout_ns BIGINT           -- Max wait
waiters TEXT                -- Notification targets

-- Molecule/work coordination
mol_type VARCHAR(32)        -- swarm|patrol|work
work_type VARCHAR(32)       -- mutex|open_competition

-- Ephemeral/special
ephemeral TINYINT(1)        -- Not synced via git
pinned TINYINT(1)           -- Persistent context marker
is_template TINYINT(1)      -- Read-only template

-- Activity
last_activity DATETIME      -- Last meaningful action
```

### Original `dependencies` table: Key differences

```sql
-- Our schema
id TEXT PK, from_id TEXT, to_id TEXT, dep_type TEXT DEFAULT 'blocks', created_at TEXT

-- Their schema (note: composite PK, no synthetic id)
issue_id VARCHAR(255) NOT NULL,       -- The issue that has the dependency
depends_on_id VARCHAR(255) NOT NULL,  -- The issue it depends on
type VARCHAR(32) NOT NULL DEFAULT 'blocks',
created_by VARCHAR(255) NOT NULL,     -- Who created it
metadata JSON,                        -- Type-specific data (e.g., gate config)
thread_id VARCHAR(255),               -- For replies-to threading
PRIMARY KEY (issue_id, depends_on_id)
```

**18+ dependency types vs our 1:**

| Category | Types | Blocking? |
|----------|-------|-----------|
| Workflow | `blocks`, `conditional-blocks`, `waits-for`, `parent-child` | Yes (except parent-child) |
| Association | `related`, `discovered-from`, `tracks`, `caused-by`, `validates` | No |
| Graph | `replies-to`, `relates-to`, `duplicates`, `supersedes` | No |
| Entity (HOP) | `authored-by`, `assigned-to`, `approved-by`, `attests` | No |
| Lifecycle | `until`, `delegated-from` | Special |

---

## 2. READY QUEUE ALGORITHM

### Original: 5-step computation in `ComputeBlockedIDsInTx`

```
Step 1: Load all active (non-closed/non-pinned) issue IDs
Step 2: Load all blocking dependencies (blocks, waits-for, conditional-blocks)
Step 3: Direct blockers - if both issue AND target active -> issue is blocked
Step 4: Waits-for gates - evaluate gate conditions against dynamic children
Step 5: Build blockedSet

Then in GetReadyWorkInTx:
WHERE (status = 'open' OR status = 'in_progress')
  AND (pinned = 0)
  AND (ephemeral = 0)
  AND (defer_until IS NULL OR defer_until <= NOW())
  AND id NOT IN (children of deferred parents)
  AND id NOT IN (blockedSet)
  AND id NOT IN (children of blocked issues)
  AND issue_type NOT IN ('merge-request','gate','molecule','message','agent','role','rig')
ORDER BY <sort_policy>
```

### ClarAIty: Simple subquery

```sql
WHERE b.status='open'
  AND b.id NOT IN (
    SELECT d.to_id FROM dependencies d
    JOIN beads blocker ON d.from_id=blocker.id
    WHERE blocker.status != 'closed'
  )
ORDER BY priority, created_at
```

### Key differences:
1. Original considers `in_progress` as potentially ready (if unblocked)
2. Original excludes deferred tasks AND their children
3. Original excludes children of blocked parents (transitive)
4. Original has 3 sort policies: `priority`, `oldest`, `hybrid` (default)
5. Original's `hybrid` policy: recent (<48h) by priority, older by FIFO
6. Original filters by assignee, labels, metadata, issue_type
7. Original has `--claim` atomic operation (compare-and-swap on assignee)

### Atomic claim (`--claim`):
```sql
UPDATE issues
SET assignee = ?, status = 'in_progress', updated_at = ?
WHERE id = ? AND (assignee = '' OR assignee IS NULL)
-- Returns error if already claimed by different actor
-- Idempotent if claimed by same actor
```

---

## 3. CONTEXT PRIMING (`bd prime`)

### Two output modes:

**MCP Mode (~50 tokens):**
- Brief session close protocol (1 paragraph)
- 5 core rules
- Memory injection (compact, 150 char/line)
- Adapts to config: stealth (no git), ephemeral branch (no push), normal (full push)

**CLI Mode (~1-2k tokens):**
- Detailed session close checklist
- All essential commands grouped by category
- Common workflow examples
- Memory injection (full format)

### Customization: 3-level fallback
1. Local `.beads/PRIME.md` (project-specific)
2. Redirected `.beads` location (shared)
3. Global `~/.config/beads/PRIME.md` (user-wide)
4. Built-in default

### Session hooks:
- **SessionStart** -> `bd prime` (ensures agent knows beads)
- **PreCompact** -> `bd prime` (re-injects after context compression)

### ClarAIty: Nothing equivalent
- No session-start briefing
- No context re-injection after compression
- Agent discovers beads via CLAUDE.md only

---

## 4. SESSION CLOSE ("Land the Plane")

### Original: Mandatory 7-step protocol

1. **File issues** for remaining work (`bd create`)
2. **Quality gates** - lint + test (file P0 if they fail)
3. **Close completed beads** (`bd close <ids> --reason`)
4. **PUSH TO REMOTE** (mandatory, retry until success)
5. **Clean git state** (stash clear, prune)
6. **Verify clean** (`git status` shows up-to-date)
7. **Handoff** - summary + recommended next-session prompt

### ClarAIty: No protocol
- Session just ends
- No push enforcement
- No handoff prompt
- No quality gate requirement

---

## 5. COMPACTION (Memory Decay)

### Original: 3 workflows

**Analyze mode** (agent-driven):
```bash
bd compact --analyze --json    # Export candidates with full content
```

**Apply mode** (accept summary):
```bash
bd compact --apply --id bd-42 --summary summary.txt
```

**Auto mode** (AI-powered, needs API key):
```bash
bd compact --auto --all
```

### Tiers:
- Tier 1: 30+ days closed -> ~70% reduction (semantic summary)
- Tier 2: 90+ days closed -> ~95% reduction (ultra-compressed)

### Storage:
- `issue_snapshots` table preserves original content
- `compaction_snapshots` table stores tiered compressed versions
- Reduction recorded in issue comments

### ClarAIty: None
- Closed tasks accumulate forever
- No summarization or archival

---

## 6. RECOMMENDED SCHEMA MIGRATION

### Phase 1: Core Schema Upgrade (High Impact, Low Risk)

**Expand `beads` table:**
```sql
-- Add columns
ALTER TABLE beads ADD COLUMN issue_type TEXT DEFAULT 'task';
ALTER TABLE beads ADD COLUMN close_reason TEXT DEFAULT '';
ALTER TABLE beads ADD COLUMN external_ref TEXT;
ALTER TABLE beads ADD COLUMN due_at TEXT;         -- ISO8601
ALTER TABLE beads ADD COLUMN defer_until TEXT;     -- ISO8601
ALTER TABLE beads ADD COLUMN estimated_minutes INTEGER;
ALTER TABLE beads ADD COLUMN metadata TEXT DEFAULT '{}';  -- JSON
ALTER TABLE beads ADD COLUMN pinned INTEGER DEFAULT 0;
ALTER TABLE beads ADD COLUMN owner TEXT DEFAULT '';
ALTER TABLE beads ADD COLUMN design TEXT DEFAULT '';
ALTER TABLE beads ADD COLUMN acceptance_criteria TEXT DEFAULT '';
ALTER TABLE beads ADD COLUMN compaction_level INTEGER DEFAULT 0;
ALTER TABLE beads ADD COLUMN last_activity TEXT;
```

**Expand statuses:** `open`, `in_progress`, `blocked`, `deferred`, `closed`, `pinned`, `hooked`

**Expand dependency types:** Add `dep_type` values: `related`, `discovered-from`, `caused-by`, `conditional-blocks`, `waits-for`, `parent-child` (keep `blocks` default)

**Add `created_by` to dependencies:**
```sql
ALTER TABLE dependencies ADD COLUMN created_by TEXT DEFAULT 'agent';
ALTER TABLE dependencies ADD COLUMN metadata TEXT DEFAULT '{}';  -- JSON for gate config
```

**Add `events` table:**
```sql
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    bead_id TEXT NOT NULL REFERENCES beads(id),
    event_type TEXT NOT NULL,  -- created|updated|status_changed|closed|reopened|...
    actor TEXT DEFAULT 'agent',
    old_value TEXT,
    new_value TEXT,
    comment TEXT,
    created_at TEXT NOT NULL
);
```

### Phase 2: Ready Queue Upgrade

- Support `in_progress` in ready (if unblocked)
- Exclude deferred + children of deferred
- Exclude children of blocked parents (transitive)
- Add `hybrid` sort policy (recent by priority, older by FIFO)
- Add `--claim` atomic operation
- Add assignee/label/type filtering

### Phase 3: Session Lifecycle

- Implement `bd prime` equivalent (token-optimized briefing)
- Implement "land the plane" protocol (close + push + handoff)
- Implement session handoff prompt generation
- Hook into session start and context compression events

### Phase 4: Compaction

- Add `compaction_snapshots` table
- Implement analyze/apply workflow
- Tier 1 (30d, 70%) and Tier 2 (90d, 95%) policies
- Agent-driven summarization via LLM

### Phase 5: Advanced (Optional)

- Gates (gh:pr, timer, human)
- Molecules/wisps (templates + ephemeral)
- Federation (multi-repo)
- Messaging (inter-agent mail)

---

## 7. WHAT NOT TO COPY

1. **Dolt storage** - We use SQLite + JSONL. This works fine. Don't switch.
2. **Counter-based IDs** - Hash-based is sufficient for our scale.
3. **Wisp tables** - Parallel table structure adds complexity. Use a flag column instead.
4. **Federation** - Multi-repo coordination is overkill for now.
5. **Interactions table** - We already have observability via Langfuse + JSONL logs.
6. **HOP entity types** (authored-by, assigned-to, approved-by, attests) - Enterprise feature.

---

*Generated 2026-03-29 from study of steveyegge/beads (Go, ~1362 files)*
