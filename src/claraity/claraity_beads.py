"""
ClarAIty Beads - Task Tracking Database

Dependency-aware task management for AI coding agents.
Inspired by Steve Yegge's Beads system.

Tasks have status lifecycle: open -> in_progress -> closed
Dependencies define execution order: task A blocks task B
Cross-references to claraity_knowledge.db via ATTACH for component linkage.

Usage:
    python -m src.claraity.claraity_beads create-tasks
    python -m src.claraity.claraity_beads ready
    python -m src.claraity.claraity_beads list
    python -m src.claraity.claraity_beads brief
"""

import json
import sqlite3
import hashlib
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class BeadStore:
    """Read/write interface to claraity_beads.db."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS beads (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        description TEXT,
        status      TEXT NOT NULL DEFAULT 'open',
        priority    INTEGER NOT NULL DEFAULT 5,
        parent_id   TEXT,
        assignee    TEXT DEFAULT 'agent',
        tags        TEXT DEFAULT '[]',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        closed_at   TEXT,
        summary     TEXT,
        FOREIGN KEY (parent_id) REFERENCES beads(id)
    );

    CREATE TABLE IF NOT EXISTS dependencies (
        id          TEXT PRIMARY KEY,
        from_id     TEXT NOT NULL,
        to_id       TEXT NOT NULL,
        dep_type    TEXT NOT NULL DEFAULT 'blocks',
        created_at  TEXT NOT NULL,
        FOREIGN KEY (from_id) REFERENCES beads(id),
        FOREIGN KEY (to_id)   REFERENCES beads(id),
        UNIQUE(from_id, to_id, dep_type)
    );

    CREATE TABLE IF NOT EXISTS bead_refs (
        id          TEXT PRIMARY KEY,
        bead_id     TEXT NOT NULL,
        component_id TEXT NOT NULL,
        ref_type    TEXT NOT NULL DEFAULT 'modifies',
        FOREIGN KEY (bead_id) REFERENCES beads(id)
    );

    CREATE TABLE IF NOT EXISTS notes (
        id          TEXT PRIMARY KEY,
        bead_id     TEXT NOT NULL,
        content     TEXT NOT NULL,
        author      TEXT DEFAULT 'agent',
        created_at  TEXT NOT NULL,
        FOREIGN KEY (bead_id) REFERENCES beads(id)
    );

    CREATE INDEX IF NOT EXISTS idx_beads_status   ON beads(status);
    CREATE INDEX IF NOT EXISTS idx_beads_priority  ON beads(priority);
    CREATE INDEX IF NOT EXISTS idx_beads_parent    ON beads(parent_id);
    CREATE INDEX IF NOT EXISTS idx_deps_from       ON dependencies(from_id);
    CREATE INDEX IF NOT EXISTS idx_deps_to         ON dependencies(to_id);
    CREATE INDEX IF NOT EXISTS idx_refs_bead       ON bead_refs(bead_id);
    CREATE INDEX IF NOT EXISTS idx_refs_component  ON bead_refs(component_id);
    """

    def __init__(self, db_path: str = ".clarity/claraity_beads.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    @contextmanager
    def _cursor(self):
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def _ensure_schema(self):
        with self._cursor() as cur:
            cur.executescript(self.SCHEMA)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    @staticmethod
    def _make_id(name: str) -> str:
        """Deterministic short hash ID: bd- + 8-char hex."""
        h = hashlib.sha256(name.encode()).hexdigest()[:8]
        return f"bd-{h}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- Write -----------------------------------------------------------------

    def add_bead(
        self,
        title: str,
        description: str = "",
        priority: int = 5,
        parent_id: str = None,
        assignee: str = "agent",
        tags: list = None,
        bead_id: str = None,
    ) -> str:
        """Create a new bead (task). Returns bead ID."""
        bid = bead_id or self._make_id(title)
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR IGNORE INTO beads
                   (id, title, description, status, priority, parent_id,
                    assignee, tags, created_at, updated_at)
                   VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)""",
                (bid, title, description, priority, parent_id,
                 assignee, json.dumps(tags or []), now, now),
            )
        return bid

    def update_status(self, bead_id: str, status: str, summary: str = None):
        """Update bead status: open, in_progress, closed."""
        valid_statuses = ("open", "in_progress", "closed")
        if status not in valid_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

        now = self._now()
        with self._cursor() as cur:
            if status == "closed":
                cur.execute(
                    """UPDATE beads SET status=?, summary=?, closed_at=?, updated_at=?
                       WHERE id=?""",
                    (status, summary, now, now, bead_id),
                )
            else:
                cur.execute(
                    "UPDATE beads SET status=?, updated_at=? WHERE id=?",
                    (status, now, bead_id),
                )
            if cur.rowcount == 0:
                raise ValueError(f"Bead '{bead_id}' not found")

    def add_dependency(self, from_id: str, to_id: str, dep_type: str = "blocks") -> str:
        """Add dependency: from_id blocks to_id."""
        did = self._make_id(f"{from_id}:{to_id}:{dep_type}")
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR IGNORE INTO dependencies
                   (id, from_id, to_id, dep_type, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (did, from_id, to_id, dep_type, now),
            )
        return did

    def add_ref(self, bead_id: str, component_id: str, ref_type: str = "modifies") -> str:
        """Link a bead to a component in the knowledge DB."""
        rid = self._make_id(f"{bead_id}:{component_id}:{ref_type}")
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR IGNORE INTO bead_refs (id, bead_id, component_id, ref_type)
                   VALUES (?, ?, ?, ?)""",
                (rid, bead_id, component_id, ref_type),
            )
        return rid

    def add_note(self, bead_id: str, content: str, author: str = "agent") -> str:
        """Add a note to a bead."""
        import uuid
        nid = f"note-{uuid.uuid4().hex[:8]}"
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO notes (id, bead_id, content, author, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (nid, bead_id, content, author, now),
            )
        return nid

    # -- Read ------------------------------------------------------------------

    def get_bead(self, bead_id: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM beads WHERE id=?", (bead_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_beads(self, status: str = None) -> list[dict]:
        with self._cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM beads WHERE status=? ORDER BY priority, created_at",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM beads ORDER BY priority, created_at")
            return [dict(r) for r in cur.fetchall()]

    def get_children(self, parent_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM beads WHERE parent_id=? ORDER BY priority, created_at",
                (parent_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_dependencies(self, bead_id: str) -> dict:
        """Get blockers (what blocks this) and blocking (what this blocks)."""
        with self._cursor() as cur:
            # What blocks this bead
            cur.execute(
                """SELECT b.* FROM beads b
                   JOIN dependencies d ON d.from_id = b.id
                   WHERE d.to_id=? AND d.dep_type='blocks'""",
                (bead_id,),
            )
            blockers = [dict(r) for r in cur.fetchall()]

            # What this bead blocks
            cur.execute(
                """SELECT b.* FROM beads b
                   JOIN dependencies d ON d.to_id = b.id
                   WHERE d.from_id=? AND d.dep_type='blocks'""",
                (bead_id,),
            )
            blocking = [dict(r) for r in cur.fetchall()]

        return {"blockers": blockers, "blocking": blocking}

    def get_refs(self, bead_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM bead_refs WHERE bead_id=?", (bead_id,))
            return [dict(r) for r in cur.fetchall()]

    def get_notes(self, bead_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM notes WHERE bead_id=? ORDER BY created_at",
                (bead_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_ready(self) -> list[dict]:
        """Get beads that are open and have no open blockers (the ready frontier)."""
        with self._cursor() as cur:
            cur.execute("""
                SELECT b.* FROM beads b
                WHERE b.status = 'open'
                AND b.id NOT IN (
                    SELECT d.to_id FROM dependencies d
                    JOIN beads blocker ON d.from_id = blocker.id
                    WHERE d.dep_type = 'blocks'
                    AND blocker.status != 'closed'
                )
                ORDER BY b.priority, b.created_at
            """)
            return [dict(r) for r in cur.fetchall()]

    def get_stats(self) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT status, COUNT(*) as c FROM beads GROUP BY status")
            by_status = {r["status"]: r["c"] for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*) as c FROM beads")
            total = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM dependencies")
            deps = cur.fetchone()["c"]
        return {"total": total, "by_status": by_status, "dependencies": deps}


# ---------------------------------------------------------------------------
# Render: tasks -> Markdown for LLM consumption
# ---------------------------------------------------------------------------

def render_tasks_md(store: BeadStore) -> str:
    """Render all tasks as markdown for LLM consumption."""
    beads = store.get_all_beads()
    stats = store.get_stats()

    if not beads:
        return "# Tasks\n\nNo tasks found.\n"

    lines = []
    lines.append("# ClarAIty Tasks")
    lines.append("")

    # Stats
    by_status = stats["by_status"]
    open_c = by_status.get("open", 0)
    ip_c = by_status.get("in_progress", 0)
    closed_c = by_status.get("closed", 0)
    lines.append(f"**{stats['total']} tasks**: {open_c} open, {ip_c} in progress, {closed_c} closed")
    lines.append("")

    # Ready tasks (most important)
    ready = store.get_ready()
    if ready:
        lines.append("## Ready (unblocked, can start now)")
        lines.append("")
        for b in ready:
            tags = json.loads(b["tags"]) if b["tags"] else []
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"- **P{b['priority']}** `{b['id']}` {b['title']}{tag_str}")
            if b["description"]:
                desc = b["description"][:100]
                if len(b["description"]) > 100:
                    desc += "..."
                lines.append(f"  > {desc}")
        lines.append("")

    # In-progress
    in_progress = [b for b in beads if b["status"] == "in_progress"]
    if in_progress:
        lines.append("## In Progress")
        lines.append("")
        for b in in_progress:
            lines.append(f"- `{b['id']}` {b['title']} (assigned: {b['assignee']})")
        lines.append("")

    # Blocked (open but not ready)
    ready_ids = {b["id"] for b in ready}
    blocked = [b for b in beads if b["status"] == "open" and b["id"] not in ready_ids]
    if blocked:
        lines.append("## Blocked")
        lines.append("")
        for b in blocked:
            deps = store.get_dependencies(b["id"])
            blocker_names = [f"`{bl['id']}` {bl['title']}" for bl in deps["blockers"] if bl["status"] != "closed"]
            lines.append(f"- `{b['id']}` {b['title']}")
            if blocker_names:
                lines.append(f"  - Blocked by: {', '.join(blocker_names)}")
        lines.append("")

    # Recently closed
    closed = [b for b in beads if b["status"] == "closed"]
    if closed:
        lines.append("## Closed")
        lines.append("")
        for b in closed[-5:]:  # last 5
            summary = f" - {b['summary']}" if b.get("summary") else ""
            lines.append(f"- ~~`{b['id']}` {b['title']}~~{summary}")
        if len(closed) > 5:
            lines.append(f"- ... and {len(closed) - 5} more")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Populate: create ClarAIty DB feature tasks
# ---------------------------------------------------------------------------

def populate_claraity_tasks(store: BeadStore):
    """Create the task graph for building out ClarAIty DB features."""

    # === Epic ===
    epic = store.add_bead(
        title="ClarAIty Knowledge System",
        description="Complete implementation of codebase knowledge DB with scan, query, visualize, and task management capabilities.",
        priority=0, tags=["epic"],
    )

    # --- Phase 1: Knowledge enrichment ---
    t_files = store.add_bead(
        title="Add file nodes (layer 4) to knowledge DB",
        description="Scan all ~224 Python files and add as type='file' nodes with role descriptions. Link to parent modules via 'contains' edges and to components via 'defines' edges.",
        priority=1, parent_id=epic, tags=["knowledge", "scan"],
    )

    t_brief = store.add_bead(
        title="Split briefing into compact + detailed",
        description="Compact overview (~1500 tokens) for system prompt auto-injection. Detailed module/component info available via query tools.",
        priority=1, parent_id=epic, tags=["knowledge", "retrieval"],
    )

    # --- Phase 2: Agent query tools ---
    t_search = store.add_bead(
        title="Build search_knowledge tool",
        description="LIKE search across nodes name/description/properties. Returns matches + one-hop neighbors as markdown.",
        priority=2, parent_id=epic, tags=["tools", "retrieval"],
    )

    t_qmod = store.add_bead(
        title="Build query_module tool",
        description="Given a module ID, returns all components and files within it as markdown.",
        priority=2, parent_id=epic, tags=["tools", "retrieval"],
    )

    t_qfile = store.add_bead(
        title="Build query_file tool",
        description="Given a file path, returns its role, parent component, and related decisions as markdown.",
        priority=2, parent_id=epic, tags=["tools", "retrieval"],
    )
    store.add_dependency(t_files, t_qfile)

    t_impact = store.add_bead(
        title="Build query_impact tool",
        description="Given a component ID, follows dependency edges to show what would be affected by changes. Returns blast radius as markdown.",
        priority=2, parent_id=epic, tags=["tools", "retrieval"],
    )

    # --- Phase 3: Reverse flow test ---
    t_revtest = store.add_bead(
        title="Test reverse flow: agent queries DB for task",
        description="Start fresh agent session, give it a coding task, verify it uses knowledge DB (compact briefing + query tools) instead of re-reading files.",
        priority=3, parent_id=epic, tags=["testing", "validation"],
    )
    store.add_dependency(t_brief, t_revtest)
    store.add_dependency(t_search, t_revtest)
    store.add_dependency(t_qmod, t_revtest)

    # --- Phase 4: Non-technical analogy layer ---
    t_analogy = store.add_bead(
        title="Add non-technical analogy descriptions",
        description="Generate plain-language explanations with analogies for each module/component. Store as 'analogy' property in node. Render as separate .clarity/OVERVIEW.md.",
        priority=4, parent_id=epic, tags=["knowledge", "ux"],
    )
    store.add_dependency(t_revtest, t_analogy)

    # --- Phase 5: JSONL git export ---
    t_jsonl = store.add_bead(
        title="Add JSONL git export for both DBs",
        description="Export claraity_knowledge.db and claraity_beads.db to .jsonl files for git tracking. Rebuild DBs from JSONL on clone/branch-switch.",
        priority=4, parent_id=epic, tags=["persistence", "git"],
    )

    # --- Phase 6: VS Code integration ---
    t_vscode = store.add_bead(
        title="Integrate architecture view into VS Code webview",
        description="Port the D3.js architecture diagram from standalone HTML into the VS Code extension sidebar as a new panel. Data served via Python backend over existing stdio+TCP protocol.",
        priority=5, parent_id=epic, tags=["ui", "vscode"],
    )
    store.add_dependency(t_revtest, t_vscode)

    # --- Phase 7: Incremental re-scan ---
    t_incr = store.add_bead(
        title="Incremental re-scan on code changes",
        description="Detect changed files since last scan, update only affected nodes in knowledge DB. Avoid full re-populate.",
        priority=5, parent_id=epic, tags=["knowledge", "scan"],
    )
    store.add_dependency(t_files, t_incr)

    # Cross-references to knowledge DB components
    store.add_ref(t_files, "mod-core", "modifies")
    store.add_ref(t_files, "mod-memory", "modifies")
    store.add_ref(t_brief, "comp-coding-agent", "modifies")
    store.add_ref(t_search, "mod-tools", "modifies")
    store.add_ref(t_qmod, "mod-tools", "modifies")
    store.add_ref(t_qfile, "mod-tools", "modifies")
    store.add_ref(t_impact, "mod-tools", "modifies")
    store.add_ref(t_vscode, "mod-server", "modifies")
    store.add_ref(t_vscode, "mod-ui", "modifies")

    all_tasks = [epic, t_files, t_brief, t_search, t_qmod, t_qfile,
                 t_impact, t_revtest, t_analogy, t_jsonl, t_vscode, t_incr]
    print(f"[OK] Created {len(all_tasks)} tasks with dependencies")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("""Usage: python -m src.claraity.claraity_beads <command> [args]

Commands:
  ready                          Show unblocked tasks ready to start
  list                           List all tasks with status
  brief                          Full task briefing as markdown
  show <id>                      Show task detail with dependencies
  create <title> [--priority N] [--desc "..."] [--parent <id>] [--tags t1,t2]
                                 Create a new task
  start <id>                     Mark task as in_progress
  close <id> [--summary "..."]   Mark task as closed
  block <blocker_id> <blocked_id>  Add blocking dependency
  init                           Populate initial ClarAIty feature tasks""")
        sys.exit(1)

    cmd = sys.argv[1]
    store = BeadStore()

    try:
        if cmd == "init":
            populate_claraity_tasks(store)
            stats = store.get_stats()
            print(f"[OK] DB: {stats['total']} beads, {stats['dependencies']} dependencies")
            print(f"     Status: {stats['by_status']}")

        elif cmd == "ready":
            ready = store.get_ready()
            if ready:
                print(f"Ready tasks ({len(ready)}):\n")
                for b in ready:
                    print(f"  P{b['priority']} [{b['id']}] {b['title']}")
            else:
                print("No ready tasks.")

        elif cmd == "list":
            beads = store.get_all_beads()
            for b in beads:
                status_icon = {"open": "[ ]", "in_progress": "[>]", "closed": "[x]"}.get(b["status"], "[?]")
                print(f"  {status_icon} P{b['priority']} [{b['id']}] {b['title']}")

        elif cmd == "brief":
            print(render_tasks_md(store))

        elif cmd == "show":
            if len(sys.argv) < 3:
                print("Usage: show <bead_id>")
                sys.exit(1)
            bead = store.get_bead(sys.argv[2])
            if not bead:
                print(f"Task '{sys.argv[2]}' not found.")
                sys.exit(1)
            tags = json.loads(bead["tags"]) if bead["tags"] else []
            print(f"# {bead['title']}")
            print(f"- **ID**: {bead['id']}")
            print(f"- **Status**: {bead['status']}")
            print(f"- **Priority**: P{bead['priority']}")
            if tags:
                print(f"- **Tags**: {', '.join(tags)}")
            if bead.get("assignee"):
                print(f"- **Assignee**: {bead['assignee']}")
            if bead.get("parent_id"):
                parent = store.get_bead(bead["parent_id"])
                print(f"- **Parent**: {parent['title'] if parent else bead['parent_id']}")
            if bead.get("description"):
                print(f"\n{bead['description']}")
            if bead.get("summary"):
                print(f"\n**Summary**: {bead['summary']}")
            deps = store.get_dependencies(bead["id"])
            if deps["blockers"]:
                print(f"\n**Blocked by**:")
                for bl in deps["blockers"]:
                    print(f"  - [{bl['status']}] `{bl['id']}` {bl['title']}")
            if deps["blocking"]:
                print(f"\n**Blocks**:")
                for bl in deps["blocking"]:
                    print(f"  - [{bl['status']}] `{bl['id']}` {bl['title']}")
            refs = store.get_refs(bead["id"])
            if refs:
                print(f"\n**References**:")
                for r in refs:
                    print(f"  - {r['ref_type']} {r['component_id']}")
            notes = store.get_notes(bead["id"])
            if notes:
                print(f"\n**Notes**:")
                for n in notes:
                    print(f"  [{n['author']}] {n['content']}")

        elif cmd == "create":
            if len(sys.argv) < 3:
                print("Usage: create <title> [--priority N] [--desc \"...\"] [--parent <id>] [--tags t1,t2]")
                sys.exit(1)
            title = sys.argv[2]
            # Parse optional args
            priority = 5
            description = ""
            parent_id = None
            tags = []
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--priority" and i + 1 < len(sys.argv):
                    priority = int(sys.argv[i + 1])
                    i += 2
                elif sys.argv[i] == "--desc" and i + 1 < len(sys.argv):
                    description = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--parent" and i + 1 < len(sys.argv):
                    parent_id = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--tags" and i + 1 < len(sys.argv):
                    tags = sys.argv[i + 1].split(",")
                    i += 2
                else:
                    i += 1

            bid = store.add_bead(
                title=title, description=description,
                priority=priority, parent_id=parent_id, tags=tags,
            )
            print(f"[OK] Created task: {bid} - {title}")

        elif cmd == "start":
            if len(sys.argv) < 3:
                print("Usage: start <bead_id>")
                sys.exit(1)
            store.update_status(sys.argv[2], "in_progress")
            print(f"[OK] Started: {sys.argv[2]}")

        elif cmd == "close":
            if len(sys.argv) < 3:
                print("Usage: close <bead_id> [--summary \"...\"]")
                sys.exit(1)
            summary = None
            if len(sys.argv) >= 5 and sys.argv[3] == "--summary":
                summary = sys.argv[4]
            store.update_status(sys.argv[2], "closed", summary=summary)
            print(f"[OK] Closed: {sys.argv[2]}")

        elif cmd == "block":
            if len(sys.argv) < 4:
                print("Usage: block <blocker_id> <blocked_id>")
                sys.exit(1)
            did = store.add_dependency(sys.argv[2], sys.argv[3], "blocks")
            print(f"[OK] {sys.argv[2]} now blocks {sys.argv[3]}")

        elif cmd == "note":
            if len(sys.argv) < 4:
                print("Usage: note <bead_id> <content>")
                sys.exit(1)
            store.add_note(sys.argv[2], " ".join(sys.argv[3:]))
            print(f"[OK] Note added to {sys.argv[2]}")

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

    finally:
        store.close()


if __name__ == "__main__":
    main()
