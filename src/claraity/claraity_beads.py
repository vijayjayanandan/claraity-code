"""
ClarAIty Beads - Task Tracking Database

Dependency-aware task management for AI coding agents.
Inspired by Steve Yegge's Beads system (github.com/steveyegge/beads).

Statuses: open -> in_progress -> closed  (core lifecycle)
          open -> blocked                (dependency-blocked)
          open -> deferred               (deliberately parked)
          pinned                         (persistent context)
          hooked                         (actively claimed by worker)

Dependencies define execution order with typed relationships:
  Blocking:     blocks, conditional-blocks, waits-for
  Association:  related, discovered-from, caused-by, tracks, validates
  Graph:        supersedes, duplicates, parent-child

Cross-references to claraity_knowledge.db via ATTACH for component linkage.

Usage:
    python -m src.claraity.claraity_beads ready
    python -m src.claraity.claraity_beads list
    python -m src.claraity.claraity_beads brief
    python -m src.claraity.claraity_beads show <id>
    python -m src.claraity.claraity_beads claim <id> [--as NAME]
"""

import json
import sqlite3
import hashlib
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# -- Constants -----------------------------------------------------------------

VALID_STATUSES = (
    "open", "in_progress", "blocked", "deferred",
    "closed", "pinned", "hooked",
)

STATUS_CATEGORIES = {
    "active": ("open",),
    "wip": ("in_progress", "blocked", "hooked"),
    "done": ("closed",),
    "frozen": ("deferred", "pinned"),
}

VALID_ISSUE_TYPES = ("bug", "feature", "task", "epic", "chore", "decision")

# Dependency types that affect the ready queue
BLOCKING_DEP_TYPES = ("blocks", "conditional-blocks", "waits-for")

# Non-blocking dependency types (accepted, don't affect ready)
ASSOCIATION_DEP_TYPES = (
    "related", "discovered-from", "caused-by", "tracks",
    "validates", "supersedes", "duplicates", "parent-child",
)


class BeadStore:
    """Read/write interface to claraity_beads.db."""

    # Tables are created first; indexes are created after migration
    # so that new columns exist before indexing them.
    _SCHEMA_TABLES = """
    CREATE TABLE IF NOT EXISTS beads (
        id                  TEXT PRIMARY KEY,
        title               TEXT NOT NULL,
        description         TEXT,
        status              TEXT NOT NULL DEFAULT 'open',
        priority            INTEGER NOT NULL DEFAULT 5,
        parent_id           TEXT,
        assignee            TEXT DEFAULT 'agent',
        tags                TEXT DEFAULT '[]',
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        closed_at           TEXT,
        summary             TEXT,
        issue_type          TEXT DEFAULT 'task',
        close_reason        TEXT DEFAULT '',
        external_ref        TEXT,
        due_at              TEXT,
        defer_until         TEXT,
        estimated_minutes   INTEGER,
        metadata            TEXT DEFAULT '{}',
        pinned              INTEGER DEFAULT 0,
        design              TEXT DEFAULT '',
        acceptance_criteria TEXT DEFAULT '',
        last_activity       TEXT,
        FOREIGN KEY (parent_id) REFERENCES beads(id)
    );

    CREATE TABLE IF NOT EXISTS dependencies (
        id          TEXT PRIMARY KEY,
        from_id     TEXT NOT NULL,
        to_id       TEXT NOT NULL,
        dep_type    TEXT NOT NULL DEFAULT 'blocks',
        created_at  TEXT NOT NULL,
        created_by  TEXT DEFAULT 'agent',
        metadata    TEXT DEFAULT '{}',
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

    CREATE TABLE IF NOT EXISTS events (
        id          TEXT PRIMARY KEY,
        bead_id     TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        actor       TEXT DEFAULT 'agent',
        old_value   TEXT,
        new_value   TEXT,
        comment     TEXT,
        created_at  TEXT NOT NULL,
        FOREIGN KEY (bead_id) REFERENCES beads(id)
    );
    """

    _SCHEMA_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_beads_status      ON beads(status);
    CREATE INDEX IF NOT EXISTS idx_beads_priority     ON beads(priority);
    CREATE INDEX IF NOT EXISTS idx_beads_parent       ON beads(parent_id);
    CREATE INDEX IF NOT EXISTS idx_beads_issue_type   ON beads(issue_type);
    CREATE INDEX IF NOT EXISTS idx_beads_assignee     ON beads(assignee);
    CREATE INDEX IF NOT EXISTS idx_beads_defer        ON beads(defer_until);
    CREATE INDEX IF NOT EXISTS idx_beads_due          ON beads(due_at);
    CREATE INDEX IF NOT EXISTS idx_beads_external_ref ON beads(external_ref);
    CREATE INDEX IF NOT EXISTS idx_deps_from          ON dependencies(from_id);
    CREATE INDEX IF NOT EXISTS idx_deps_to            ON dependencies(to_id);
    CREATE INDEX IF NOT EXISTS idx_deps_type          ON dependencies(dep_type);
    CREATE INDEX IF NOT EXISTS idx_refs_bead          ON bead_refs(bead_id);
    CREATE INDEX IF NOT EXISTS idx_refs_component     ON bead_refs(component_id);
    CREATE INDEX IF NOT EXISTS idx_events_bead        ON events(bead_id);
    CREATE INDEX IF NOT EXISTS idx_events_type        ON events(event_type);
    CREATE INDEX IF NOT EXISTS idx_events_created     ON events(created_at);
    """

    # Column migrations for existing DBs (CREATE TABLE IF NOT EXISTS
    # won't add columns to tables that already exist).
    _MIGRATIONS = [
        # beads table
        "ALTER TABLE beads ADD COLUMN issue_type TEXT DEFAULT 'task'",
        "ALTER TABLE beads ADD COLUMN close_reason TEXT DEFAULT ''",
        "ALTER TABLE beads ADD COLUMN external_ref TEXT",
        "ALTER TABLE beads ADD COLUMN due_at TEXT",
        "ALTER TABLE beads ADD COLUMN defer_until TEXT",
        "ALTER TABLE beads ADD COLUMN estimated_minutes INTEGER",
        "ALTER TABLE beads ADD COLUMN metadata TEXT DEFAULT '{}'",
        "ALTER TABLE beads ADD COLUMN pinned INTEGER DEFAULT 0",
        "ALTER TABLE beads ADD COLUMN design TEXT DEFAULT ''",
        "ALTER TABLE beads ADD COLUMN acceptance_criteria TEXT DEFAULT ''",
        "ALTER TABLE beads ADD COLUMN last_activity TEXT",
        # dependencies table
        "ALTER TABLE dependencies ADD COLUMN created_by TEXT DEFAULT 'agent'",
        "ALTER TABLE dependencies ADD COLUMN metadata TEXT DEFAULT '{}'",
    ]

    def __init__(self, db_path: str = ".claraity/claraity_beads.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        # Auto-import: if DB missing but JSONL exists, rebuild
        if not self.db_path.exists():
            jsonl_path = self.db_path.with_suffix(".jsonl")
            if jsonl_path.exists():
                rebuilt = BeadStore.import_jsonl(str(jsonl_path), str(self.db_path))
                self.conn = rebuilt.conn
                rebuilt.conn = None
                return
        self._ensure_schema()
        self._migrate_existing_db()
        self._ensure_indexes()

    @contextmanager
    def _cursor(self):
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path), timeout=5.0)
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
            cur.executescript(self._SCHEMA_TABLES)

    def _ensure_indexes(self):
        with self._cursor() as cur:
            cur.executescript(self._SCHEMA_INDEXES)

    def _migrate_existing_db(self):
        """Add new columns to existing tables (idempotent).

        SQLite doesn't support IF NOT EXISTS for ALTER TABLE,
        so we catch 'duplicate column name' errors.
        """
        with self._cursor() as cur:
            for sql in self._MIGRATIONS:
                try:
                    cur.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    @staticmethod
    def _make_id(name: str) -> str:
        """Deterministic short hash ID: bd- + 8-char hex."""
        h = hashlib.sha256(name.encode()).hexdigest()[:8]
        return f"bd-{h}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _record_event(
        self,
        cur,
        bead_id: str,
        event_type: str,
        old_value: str = None,
        new_value: str = None,
        actor: str = "agent",
        comment: str = None,
    ):
        """Record an event in the audit trail (must be called within _cursor context)."""
        eid = f"ev-{uuid.uuid4().hex[:8]}"
        cur.execute(
            """INSERT INTO events
               (id, bead_id, event_type, actor, old_value, new_value, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, bead_id, event_type, actor, old_value, new_value, comment, self._now()),
        )

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
        issue_type: str = "task",
        external_ref: str = None,
        due_at: str = None,
        defer_until: str = None,
        estimated_minutes: int = None,
        metadata: dict = None,
        design: str = "",
        acceptance_criteria: str = "",
    ) -> str:
        """Create a new bead (task). Returns bead ID."""
        bid = bead_id or self._make_id(title)
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR IGNORE INTO beads
                   (id, title, description, status, priority, parent_id,
                    assignee, tags, created_at, updated_at, issue_type,
                    external_ref, due_at, defer_until, estimated_minutes,
                    metadata, design, acceptance_criteria, last_activity)
                   VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bid,
                    title,
                    description,
                    priority,
                    parent_id,
                    assignee,
                    json.dumps(tags or []),
                    now,
                    now,
                    issue_type,
                    external_ref,
                    due_at,
                    defer_until,
                    estimated_minutes,
                    json.dumps(metadata or {}),
                    design,
                    acceptance_criteria,
                    now,
                ),
            )
            if cur.rowcount > 0:
                self._record_event(cur, bid, "created", None, "open")
        return bid

    def update_status(
        self,
        bead_id: str,
        status: str,
        summary: str = None,
        close_reason: str = None,
    ):
        """Update bead status. See VALID_STATUSES for allowed values."""
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}"
            )

        now = self._now()
        with self._cursor() as cur:
            cur.execute("SELECT status FROM beads WHERE id=?", (bead_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Bead '{bead_id}' not found")
            old_status = row["status"]

            if status == "closed":
                cur.execute(
                    """UPDATE beads SET status=?, summary=?, close_reason=?,
                       closed_at=?, updated_at=?, last_activity=?
                       WHERE id=?""",
                    (status, summary, close_reason or "", now, now, now, bead_id),
                )
            elif status == "deferred":
                cur.execute(
                    "UPDATE beads SET status=?, updated_at=?, last_activity=? WHERE id=?",
                    (status, now, now, bead_id),
                )
            else:
                cur.execute(
                    "UPDATE beads SET status=?, updated_at=?, last_activity=? WHERE id=?",
                    (status, now, now, bead_id),
                )

            self._record_event(cur, bead_id, "status_changed", old_status, status)

    def claim(self, bead_id: str, claimant: str) -> bool:
        """Atomically claim a task (compare-and-swap on assignee).

        Returns True if claimed successfully, False if already claimed by another.
        Idempotent: re-claiming by same actor returns True.
        """
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                "SELECT assignee, status FROM beads WHERE id=?", (bead_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Bead '{bead_id}' not found")

            # Idempotent: already claimed by same actor
            if row["assignee"] == claimant and row["status"] == "in_progress":
                return True

            # Atomic CAS: only claim if unassigned or default 'agent'
            cur.execute(
                """UPDATE beads
                   SET assignee=?, status='in_progress', updated_at=?, last_activity=?
                   WHERE id=?
                   AND (assignee IS NULL OR assignee = '' OR assignee = 'agent')""",
                (claimant, now, now, bead_id),
            )
            if cur.rowcount == 0:
                return False

            self._record_event(
                cur, bead_id, "claimed",
                row["assignee"], claimant,
            )
            return True

    def reopen(self, bead_id: str):
        """Reopen a closed or deferred task. Clears defer_until."""
        now = self._now()
        with self._cursor() as cur:
            cur.execute("SELECT status FROM beads WHERE id=?", (bead_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Bead '{bead_id}' not found")
            old_status = row["status"]

            cur.execute(
                """UPDATE beads SET status='open', defer_until=NULL,
                   updated_at=?, last_activity=? WHERE id=?""",
                (now, now, bead_id),
            )
            self._record_event(cur, bead_id, "reopened", old_status, "open")

    def defer(self, bead_id: str, until: str = None):
        """Defer a task. Optionally set defer_until date (ISO8601)."""
        now = self._now()
        with self._cursor() as cur:
            cur.execute("SELECT status FROM beads WHERE id=?", (bead_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Bead '{bead_id}' not found")
            old_status = row["status"]

            cur.execute(
                """UPDATE beads SET status='deferred', defer_until=?,
                   updated_at=?, last_activity=? WHERE id=?""",
                (until, now, now, bead_id),
            )
            self._record_event(
                cur, bead_id, "status_changed", old_status, "deferred",
                comment=f"defer_until={until}" if until else None,
            )

    def add_dependency(
        self,
        from_id: str,
        to_id: str,
        dep_type: str = "blocks",
        created_by: str = "agent",
        metadata: dict = None,
    ) -> str:
        """Add dependency: from_id relates to to_id via dep_type."""
        did = self._make_id(f"{from_id}:{to_id}:{dep_type}")
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR IGNORE INTO dependencies
                   (id, from_id, to_id, dep_type, created_at, created_by, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (did, from_id, to_id, dep_type, now, created_by,
                 json.dumps(metadata or {})),
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
        nid = f"note-{uuid.uuid4().hex[:8]}"
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO notes (id, bead_id, content, author, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (nid, bead_id, content, author, now),
            )
        return nid

    def add_event(
        self,
        bead_id: str,
        event_type: str,
        old_value: str = None,
        new_value: str = None,
        actor: str = "agent",
        comment: str = None,
    ) -> str:
        """Record an event (public API). Returns event ID."""
        eid = f"ev-{uuid.uuid4().hex[:8]}"
        now = self._now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO events
                   (id, bead_id, event_type, actor, old_value, new_value, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, bead_id, event_type, actor, old_value, new_value, comment, now),
            )
        return eid

    def update_metadata(self, bead_id: str, metadata: dict):
        """Merge keys into bead's metadata JSON."""
        now = self._now()
        with self._cursor() as cur:
            cur.execute("SELECT metadata FROM beads WHERE id=?", (bead_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Bead '{bead_id}' not found")
            existing = json.loads(row["metadata"] or "{}")
            existing.update(metadata)
            cur.execute(
                "UPDATE beads SET metadata=?, updated_at=?, last_activity=? WHERE id=?",
                (json.dumps(existing), now, now, bead_id),
            )

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

    def get_all_blockers(self) -> dict[str, list[dict]]:
        """Bulk-fetch all blocker relationships. Returns {bead_id: [blocker_beads]}.

        Considers all blocking dependency types: blocks, conditional-blocks, waits-for.
        """
        placeholders = ",".join("?" for _ in BLOCKING_DEP_TYPES)
        with self._cursor() as cur:
            cur.execute(
                f"""SELECT d.to_id AS bead_id, b.id, b.title, b.status, d.dep_type
                   FROM dependencies d
                   JOIN beads b ON b.id = d.from_id
                   WHERE d.dep_type IN ({placeholders})""",
                BLOCKING_DEP_TYPES,
            )
            result: dict[str, list[dict]] = {}
            for row in cur.fetchall():
                bead_id = row["bead_id"]
                if bead_id not in result:
                    result[bead_id] = []
                result[bead_id].append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "status": row["status"],
                        "dep_type": row["dep_type"],
                    }
                )
        return result

    def get_dependencies(self, bead_id: str) -> dict:
        """Get all dependencies for a bead, grouped by direction.

        Returns {blockers: [...], blocking: [...], associations: [...]}.
        """
        with self._cursor() as cur:
            # What blocks this bead (blocking dep types, from_id -> this)
            placeholders = ",".join("?" for _ in BLOCKING_DEP_TYPES)
            cur.execute(
                f"""SELECT b.*, d.dep_type FROM beads b
                   JOIN dependencies d ON d.from_id = b.id
                   WHERE d.to_id=? AND d.dep_type IN ({placeholders})""",
                (bead_id, *BLOCKING_DEP_TYPES),
            )
            blockers = [dict(r) for r in cur.fetchall()]

            # What this bead blocks (blocking dep types, this -> to_id)
            cur.execute(
                f"""SELECT b.*, d.dep_type FROM beads b
                   JOIN dependencies d ON d.to_id = b.id
                   WHERE d.from_id=? AND d.dep_type IN ({placeholders})""",
                (bead_id, *BLOCKING_DEP_TYPES),
            )
            blocking = [dict(r) for r in cur.fetchall()]

            # Non-blocking associations (both directions)
            cur.execute(
                f"""SELECT b.*, d.dep_type, 'outgoing' as direction FROM beads b
                   JOIN dependencies d ON d.to_id = b.id
                   WHERE d.from_id=? AND d.dep_type NOT IN ({placeholders})
                   UNION ALL
                   SELECT b.*, d.dep_type, 'incoming' as direction FROM beads b
                   JOIN dependencies d ON d.from_id = b.id
                   WHERE d.to_id=? AND d.dep_type NOT IN ({placeholders})""",
                (bead_id, *BLOCKING_DEP_TYPES, bead_id, *BLOCKING_DEP_TYPES),
            )
            associations = [dict(r) for r in cur.fetchall()]

        return {"blockers": blockers, "blocking": blocking, "associations": associations}

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

    def get_events(self, bead_id: str) -> list[dict]:
        """Get audit trail for a bead."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM events WHERE bead_id=? ORDER BY created_at",
                (bead_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_ready(self) -> list[dict]:
        """Get beads that are open, not pinned, not deferred, and have no active blockers.

        The ready frontier: tasks an agent can start working on right now.
        Respects defer_until (hidden until date passes) and all blocking dep types.
        """
        now = self._now()
        placeholders = ",".join("?" for _ in BLOCKING_DEP_TYPES)
        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT b.* FROM beads b
                WHERE b.status = 'open'
                AND (b.pinned = 0 OR b.pinned IS NULL)
                AND (b.defer_until IS NULL OR b.defer_until <= ?)
                AND b.id NOT IN (
                    SELECT d.to_id FROM dependencies d
                    JOIN beads blocker ON d.from_id = blocker.id
                    WHERE d.dep_type IN ({placeholders})
                    AND blocker.status NOT IN ('closed', 'pinned')
                )
                ORDER BY b.priority, b.created_at
                """,
                (now, *BLOCKING_DEP_TYPES),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_stats(self) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT status, COUNT(*) as c FROM beads GROUP BY status")
            by_status = {r["status"]: r["c"] for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*) as c FROM beads")
            total = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM dependencies")
            deps = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM events")
            events = cur.fetchone()["c"]
        return {
            "total": total,
            "by_status": by_status,
            "dependencies": deps,
            "events": events,
        }

    # -- JSONL Export/Import ---------------------------------------------------

    def export_jsonl(self, path: str = ".claraity/claraity_beads.jsonl") -> int:
        """Export entire DB to JSONL for git tracking. Returns line count.

        Order: beads first, then dependencies, refs, notes, events (for FK-safe import).
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(out, "w", encoding="utf-8") as f:
            # Beads
            for b in self.get_all_beads():
                rec = dict(b)
                rec["_t"] = "bead"
                f.write(json.dumps(rec, default=str) + "\n")
                count += 1
            # Dependencies
            with self._cursor() as cur:
                cur.execute("SELECT * FROM dependencies ORDER BY created_at")
                for row in cur.fetchall():
                    rec = dict(row)
                    rec["_t"] = "dep"
                    f.write(json.dumps(rec, default=str) + "\n")
                    count += 1
            # Refs
            with self._cursor() as cur:
                cur.execute("SELECT * FROM bead_refs")
                for row in cur.fetchall():
                    rec = dict(row)
                    rec["_t"] = "ref"
                    f.write(json.dumps(rec, default=str) + "\n")
                    count += 1
            # Notes
            with self._cursor() as cur:
                cur.execute("SELECT * FROM notes ORDER BY created_at")
                for row in cur.fetchall():
                    rec = dict(row)
                    rec["_t"] = "note"
                    f.write(json.dumps(rec, default=str) + "\n")
                    count += 1
            # Events
            with self._cursor() as cur:
                cur.execute("SELECT * FROM events ORDER BY created_at")
                for row in cur.fetchall():
                    rec = dict(row)
                    rec["_t"] = "event"
                    f.write(json.dumps(rec, default=str) + "\n")
                    count += 1
        return count

    @classmethod
    def import_jsonl(
        cls, jsonl_path: str, db_path: str = ".claraity/claraity_beads.db"
    ) -> "BeadStore":
        """Rebuild SQLite DB from JSONL file. Deletes existing DB first.

        Backward compatible: handles old JSONL files missing new columns.
        """
        db = Path(db_path)
        if db.exists():
            db.unlink()
        store = cls(db_path)
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                t = rec.pop("_t")
                if t == "bead":
                    with store._cursor() as cur:
                        cur.execute(
                            """INSERT OR IGNORE INTO beads
                               (id, title, description, status, priority, parent_id,
                                assignee, tags, created_at, updated_at, closed_at, summary,
                                issue_type, close_reason, external_ref, due_at, defer_until,
                                estimated_minutes, metadata, pinned, design,
                                acceptance_criteria, last_activity)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                rec["id"],
                                rec["title"],
                                rec.get("description"),
                                rec.get("status", "open"),
                                rec.get("priority", 5),
                                rec.get("parent_id"),
                                rec.get("assignee"),
                                rec.get("tags"),
                                rec.get("created_at"),
                                rec.get("updated_at"),
                                rec.get("closed_at"),
                                rec.get("summary"),
                                rec.get("issue_type", "task"),
                                rec.get("close_reason", ""),
                                rec.get("external_ref"),
                                rec.get("due_at"),
                                rec.get("defer_until"),
                                rec.get("estimated_minutes"),
                                rec.get("metadata", "{}"),
                                rec.get("pinned", 0),
                                rec.get("design", ""),
                                rec.get("acceptance_criteria", ""),
                                rec.get("last_activity"),
                            ),
                        )
                elif t == "dep":
                    with store._cursor() as cur:
                        cur.execute(
                            """INSERT OR IGNORE INTO dependencies
                               (id, from_id, to_id, dep_type, created_at, created_by, metadata)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                rec["id"],
                                rec["from_id"],
                                rec["to_id"],
                                rec.get("dep_type", "blocks"),
                                rec.get("created_at"),
                                rec.get("created_by", "agent"),
                                rec.get("metadata", "{}"),
                            ),
                        )
                elif t == "ref":
                    with store._cursor() as cur:
                        cur.execute(
                            """INSERT OR IGNORE INTO bead_refs
                               (id, bead_id, component_id, ref_type)
                               VALUES (?, ?, ?, ?)""",
                            (
                                rec["id"],
                                rec["bead_id"],
                                rec["component_id"],
                                rec.get("ref_type", "modifies"),
                            ),
                        )
                elif t == "note":
                    with store._cursor() as cur:
                        cur.execute(
                            """INSERT OR IGNORE INTO notes
                               (id, bead_id, content, author, created_at)
                               VALUES (?, ?, ?, ?, ?)""",
                            (
                                rec["id"],
                                rec["bead_id"],
                                rec.get("content", ""),
                                rec.get("author", "agent"),
                                rec.get("created_at"),
                            ),
                        )
                elif t == "event":
                    with store._cursor() as cur:
                        cur.execute(
                            """INSERT OR IGNORE INTO events
                               (id, bead_id, event_type, actor, old_value,
                                new_value, comment, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                rec["id"],
                                rec["bead_id"],
                                rec.get("event_type", ""),
                                rec.get("actor", "agent"),
                                rec.get("old_value"),
                                rec.get("new_value"),
                                rec.get("comment"),
                                rec.get("created_at"),
                            ),
                        )
        return store


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
    blocked_c = by_status.get("blocked", 0)
    deferred_c = by_status.get("deferred", 0)

    parts = [f"{open_c} open", f"{ip_c} in progress", f"{closed_c} closed"]
    if blocked_c:
        parts.append(f"{blocked_c} blocked")
    if deferred_c:
        parts.append(f"{deferred_c} deferred")
    lines.append(f"**{stats['total']} tasks**: {', '.join(parts)}")
    lines.append("")

    # Ready tasks (most important)
    ready = store.get_ready()
    if ready:
        lines.append("## Ready (unblocked, can start now)")
        lines.append("")
        for b in ready:
            tags = json.loads(b["tags"]) if b["tags"] else []
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            type_str = f" ({b['issue_type']})" if b.get("issue_type") and b["issue_type"] != "task" else ""
            lines.append(f"- **P{b['priority']}**{type_str} `{b['id']}` {b['title']}{tag_str}")
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

    # Blocked (status='blocked' OR open with unmet deps)
    ready_ids = {b["id"] for b in ready}
    ip_ids = {b["id"] for b in in_progress}
    blocked = [
        b for b in beads
        if (b["status"] == "blocked")
        or (b["status"] == "open" and b["id"] not in ready_ids)
    ]
    if blocked:
        lines.append("## Blocked")
        lines.append("")
        for b in blocked:
            deps = store.get_dependencies(b["id"])
            blocker_names = [
                f"`{bl['id']}` {bl['title']}"
                for bl in deps["blockers"]
                if bl["status"] not in ("closed", "pinned")
            ]
            lines.append(f"- `{b['id']}` {b['title']}")
            if blocker_names:
                lines.append(f"  - Blocked by: {', '.join(blocker_names)}")
        lines.append("")

    # Deferred
    deferred = [b for b in beads if b["status"] == "deferred"]
    if deferred:
        lines.append("## Deferred")
        lines.append("")
        for b in deferred:
            until = f" (until {b['defer_until']})" if b.get("defer_until") else ""
            lines.append(f"- `{b['id']}` {b['title']}{until}")
        lines.append("")

    # Pinned (persistent context)
    pinned = [b for b in beads if b["status"] == "pinned" or b.get("pinned")]
    if pinned:
        lines.append("## Pinned (persistent context)")
        lines.append("")
        for b in pinned:
            lines.append(f"- `{b['id']}` {b['title']}")
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
        priority=0,
        tags=["epic"],
    )

    # --- Phase 1: Knowledge enrichment ---
    t_files = store.add_bead(
        title="Add file nodes (layer 4) to knowledge DB",
        description="Scan all ~224 Python files and add as type='file' nodes with role descriptions. Link to parent modules via 'contains' edges and to components via 'defines' edges.",
        priority=1,
        parent_id=epic,
        tags=["knowledge", "scan"],
    )

    t_brief = store.add_bead(
        title="Split briefing into compact + detailed",
        description="Compact overview (~1500 tokens) for system prompt auto-injection. Detailed module/component info available via query tools.",
        priority=1,
        parent_id=epic,
        tags=["knowledge", "retrieval"],
    )

    # --- Phase 2: Agent query tools ---
    t_search = store.add_bead(
        title="Build search_knowledge tool",
        description="LIKE search across nodes name/description/properties. Returns matches + one-hop neighbors as markdown.",
        priority=2,
        parent_id=epic,
        tags=["tools", "retrieval"],
    )

    t_qmod = store.add_bead(
        title="Build query_module tool",
        description="Given a module ID, returns all components and files within it as markdown.",
        priority=2,
        parent_id=epic,
        tags=["tools", "retrieval"],
    )

    t_qfile = store.add_bead(
        title="Build query_file tool",
        description="Given a file path, returns its role, parent component, and related decisions as markdown.",
        priority=2,
        parent_id=epic,
        tags=["tools", "retrieval"],
    )
    store.add_dependency(t_files, t_qfile)

    t_impact = store.add_bead(
        title="Build query_impact tool",
        description="Given a component ID, follows dependency edges to show what would be affected by changes. Returns blast radius as markdown.",
        priority=2,
        parent_id=epic,
        tags=["tools", "retrieval"],
    )

    # --- Phase 3: Reverse flow test ---
    t_revtest = store.add_bead(
        title="Test reverse flow: agent queries DB for task",
        description="Start fresh agent session, give it a coding task, verify it uses knowledge DB (compact briefing + query tools) instead of re-reading files.",
        priority=3,
        parent_id=epic,
        tags=["testing", "validation"],
    )
    store.add_dependency(t_brief, t_revtest)
    store.add_dependency(t_search, t_revtest)
    store.add_dependency(t_qmod, t_revtest)

    # --- Phase 4: Non-technical analogy layer ---
    t_analogy = store.add_bead(
        title="Add non-technical analogy descriptions",
        description="Generate plain-language explanations with analogies for each module/component. Store as 'analogy' property in node. Render as separate .claraity/OVERVIEW.md.",
        priority=4,
        parent_id=epic,
        tags=["knowledge", "ux"],
    )
    store.add_dependency(t_revtest, t_analogy)

    # --- Phase 5: JSONL git export ---
    t_jsonl = store.add_bead(
        title="Add JSONL git export for both DBs",
        description="Export claraity_knowledge.db and claraity_beads.db to .jsonl files for git tracking. Rebuild DBs from JSONL on clone/branch-switch.",
        priority=4,
        parent_id=epic,
        tags=["persistence", "git"],
    )

    # --- Phase 6: VS Code integration ---
    t_vscode = store.add_bead(
        title="Integrate architecture view into VS Code webview",
        description="Port the D3.js architecture diagram from standalone HTML into the VS Code extension sidebar as a new panel. Data served via Python backend over existing stdio+TCP protocol.",
        priority=5,
        parent_id=epic,
        tags=["ui", "vscode"],
    )
    store.add_dependency(t_revtest, t_vscode)

    # --- Phase 7: Incremental re-scan ---
    t_incr = store.add_bead(
        title="Incremental re-scan on code changes",
        description="Detect changed files since last scan, update only affected nodes in knowledge DB. Avoid full re-populate.",
        priority=5,
        parent_id=epic,
        tags=["knowledge", "scan"],
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

    all_tasks = [
        epic,
        t_files,
        t_brief,
        t_search,
        t_qmod,
        t_qfile,
        t_impact,
        t_revtest,
        t_analogy,
        t_jsonl,
        t_vscode,
        t_incr,
    ]
    print(f"[OK] Created {len(all_tasks)} tasks with dependencies")


# ---------------------------------------------------------------------------
# CLI: Status icons for all statuses
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "open": "[ ]",
    "in_progress": "[>]",
    "blocked": "[!]",
    "deferred": "[~]",
    "closed": "[x]",
    "pinned": "[*]",
    "hooked": "[@]",
}


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
                                 [--type bug|feature|task|epic|chore|decision]
                                 [--ref EXT_REF] [--due DATE] [--design "..."]
  start <id>                     Mark task as in_progress
  close <id> [--summary "..."] [--reason "..."]
                                 Mark task as closed
  claim <id> [--as NAME]         Atomically claim a task
  defer <id> [--until DATE]      Defer task (optionally until a date)
  reopen <id>                    Reopen a closed or deferred task
  block <blocker_id> <blocked_id>  Add blocking dependency
  link <from_id> <to_id> [--type TYPE]
                                 Add typed dependency (default: related)
  note <id> <content>            Add a note to a task
  events <id>                    Show event history for a task
  init                           Populate initial ClarAIty feature tasks
  export-jsonl                   Export DB to JSONL for git tracking
  import-jsonl [path]            Rebuild DB from JSONL file""")
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
                    type_str = f" ({b['issue_type']})" if b.get("issue_type") and b["issue_type"] != "task" else ""
                    print(f"  P{b['priority']}{type_str} [{b['id']}] {b['title']}")
            else:
                print("No ready tasks.")

        elif cmd == "list":
            beads = store.get_all_beads()
            for b in beads:
                icon = _STATUS_ICONS.get(b["status"], "[?]")
                type_str = f" ({b['issue_type']})" if b.get("issue_type") and b["issue_type"] != "task" else ""
                print(f"  {icon} P{b['priority']}{type_str} [{b['id']}] {b['title']}")

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
            print(f"- **Type**: {bead.get('issue_type', 'task')}")
            if tags:
                print(f"- **Tags**: {', '.join(tags)}")
            if bead.get("assignee"):
                print(f"- **Assignee**: {bead['assignee']}")
            if bead.get("parent_id"):
                parent = store.get_bead(bead["parent_id"])
                print(f"- **Parent**: {parent['title'] if parent else bead['parent_id']}")
            if bead.get("external_ref"):
                print(f"- **External**: {bead['external_ref']}")
            if bead.get("due_at"):
                print(f"- **Due**: {bead['due_at']}")
            if bead.get("defer_until"):
                print(f"- **Deferred until**: {bead['defer_until']}")
            if bead.get("estimated_minutes"):
                print(f"- **Estimate**: {bead['estimated_minutes']} min")
            if bead.get("description"):
                print(f"\n{bead['description']}")
            if bead.get("design"):
                print(f"\n**Design**: {bead['design']}")
            if bead.get("acceptance_criteria"):
                print(f"\n**Acceptance Criteria**: {bead['acceptance_criteria']}")
            if bead.get("summary"):
                print(f"\n**Summary**: {bead['summary']}")
            if bead.get("close_reason"):
                print(f"**Close Reason**: {bead['close_reason']}")
            deps = store.get_dependencies(bead["id"])
            if deps["blockers"]:
                print(f"\n**Blocked by**:")
                for bl in deps["blockers"]:
                    print(f"  - [{bl['status']}] `{bl['id']}` {bl['title']}")
            if deps["blocking"]:
                print(f"\n**Blocks**:")
                for bl in deps["blocking"]:
                    print(f"  - [{bl['status']}] `{bl['id']}` {bl['title']}")
            if deps.get("associations"):
                print(f"\n**Related**:")
                for a in deps["associations"]:
                    print(f"  - ({a['dep_type']}) `{a['id']}` {a['title']}")
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
            # Metadata (if non-empty)
            meta = json.loads(bead.get("metadata") or "{}")
            if meta:
                print(f"\n**Metadata**: {json.dumps(meta, indent=2)}")

        elif cmd == "create":
            if len(sys.argv) < 3:
                print('Usage: create <title> [--priority N] [--desc "..."] [--parent <id>]'
                      ' [--tags t1,t2] [--type TYPE] [--ref EXT_REF] [--due DATE]')
                sys.exit(1)
            title = sys.argv[2]
            # Parse optional args
            priority = 5
            description = ""
            parent_id = None
            tags = []
            issue_type = "task"
            external_ref = None
            due_at = None
            design = ""
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
                elif sys.argv[i] == "--type" and i + 1 < len(sys.argv):
                    issue_type = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--ref" and i + 1 < len(sys.argv):
                    external_ref = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--due" and i + 1 < len(sys.argv):
                    due_at = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--design" and i + 1 < len(sys.argv):
                    design = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1

            bid = store.add_bead(
                title=title,
                description=description,
                priority=priority,
                parent_id=parent_id,
                tags=tags,
                issue_type=issue_type,
                external_ref=external_ref,
                due_at=due_at,
                design=design,
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
                print('Usage: close <bead_id> [--summary "..."] [--reason "..."]')
                sys.exit(1)
            summary = None
            close_reason = None
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--summary" and i + 1 < len(sys.argv):
                    summary = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--reason" and i + 1 < len(sys.argv):
                    close_reason = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1
            store.update_status(sys.argv[2], "closed", summary=summary, close_reason=close_reason)
            print(f"[OK] Closed: {sys.argv[2]}")

        elif cmd == "claim":
            if len(sys.argv) < 3:
                print("Usage: claim <bead_id> [--as NAME]")
                sys.exit(1)
            claimant = "agent"
            if len(sys.argv) >= 5 and sys.argv[3] == "--as":
                claimant = sys.argv[4]
            ok = store.claim(sys.argv[2], claimant)
            if ok:
                print(f"[OK] Claimed: {sys.argv[2]} by {claimant}")
            else:
                bead = store.get_bead(sys.argv[2])
                print(f"[FAIL] Already claimed by {bead['assignee']}")
                sys.exit(1)

        elif cmd == "defer":
            if len(sys.argv) < 3:
                print("Usage: defer <bead_id> [--until DATE]")
                sys.exit(1)
            until = None
            if len(sys.argv) >= 5 and sys.argv[3] == "--until":
                until = sys.argv[4]
            store.defer(sys.argv[2], until=until)
            msg = f"[OK] Deferred: {sys.argv[2]}"
            if until:
                msg += f" until {until}"
            print(msg)

        elif cmd == "reopen":
            if len(sys.argv) < 3:
                print("Usage: reopen <bead_id>")
                sys.exit(1)
            store.reopen(sys.argv[2])
            print(f"[OK] Reopened: {sys.argv[2]}")

        elif cmd == "block":
            if len(sys.argv) < 4:
                print("Usage: block <blocker_id> <blocked_id>")
                sys.exit(1)
            store.add_dependency(sys.argv[2], sys.argv[3], "blocks")
            print(f"[OK] {sys.argv[2]} now blocks {sys.argv[3]}")

        elif cmd == "link":
            if len(sys.argv) < 4:
                print("Usage: link <from_id> <to_id> [--type TYPE]")
                sys.exit(1)
            dep_type = "related"
            if len(sys.argv) >= 6 and sys.argv[4] == "--type":
                dep_type = sys.argv[5]
            store.add_dependency(sys.argv[2], sys.argv[3], dep_type)
            print(f"[OK] {sys.argv[2]} --({dep_type})--> {sys.argv[3]}")

        elif cmd == "note":
            if len(sys.argv) < 4:
                print("Usage: note <bead_id> <content>")
                sys.exit(1)
            store.add_note(sys.argv[2], " ".join(sys.argv[3:]))
            print(f"[OK] Note added to {sys.argv[2]}")

        elif cmd == "events":
            if len(sys.argv) < 3:
                print("Usage: events <bead_id>")
                sys.exit(1)
            events = store.get_events(sys.argv[2])
            if events:
                print(f"Events for {sys.argv[2]} ({len(events)}):\n")
                for ev in events:
                    ts = ev["created_at"][:19] if ev.get("created_at") else "?"
                    detail = ""
                    if ev.get("old_value") and ev.get("new_value"):
                        detail = f" {ev['old_value']} -> {ev['new_value']}"
                    elif ev.get("new_value"):
                        detail = f" -> {ev['new_value']}"
                    comment = f"  ({ev['comment']})" if ev.get("comment") else ""
                    print(f"  [{ts}] {ev['event_type']}{detail}{comment}")
            else:
                print(f"No events for {sys.argv[2]}.")

        elif cmd == "export-jsonl":
            count = store.export_jsonl()
            print(f"[OK] Exported {count} records to .claraity/claraity_beads.jsonl")

        elif cmd == "import-jsonl":
            jsonl_path = sys.argv[2] if len(sys.argv) > 2 else ".claraity/claraity_beads.jsonl"
            store.close()
            store = BeadStore.import_jsonl(jsonl_path)
            stats = store.get_stats()
            print(
                f"[OK] Rebuilt DB from JSONL: {stats['total']} beads, {stats['dependencies']} dependencies"
            )

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

    finally:
        store.close()


if __name__ == "__main__":
    main()
