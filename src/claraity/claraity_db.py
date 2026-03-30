"""
ClarAIty Knowledge DB - Codebase Knowledge Database

A property graph database that stores an LLM agent's understanding of a codebase.
Two tables: nodes (entities at multiple zoom levels) and edges (typed relationships).

Usage:
    python -m src.claraity.claraity_db populate
    python -m src.claraity.claraity_db export
    python -m src.claraity.claraity_db brief
    python -m src.claraity.claraity_db all
"""

import json
import sqlite3
import hashlib
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# ClaraityStore - thin wrapper around SQLite
# ---------------------------------------------------------------------------


class ClaraityStore:
    """Read/write interface to claraity_knowledge.db (nodes + edges property graph)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS nodes (
        id          TEXT PRIMARY KEY,
        type        TEXT NOT NULL,
        layer       INTEGER NOT NULL DEFAULT 3,
        name        TEXT NOT NULL,
        description TEXT,
        file_path   TEXT,
        line_count  INTEGER,
        risk_level  TEXT DEFAULT 'low',
        properties  TEXT DEFAULT '{}',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS edges (
        id          TEXT PRIMARY KEY,
        from_id     TEXT NOT NULL,
        to_id       TEXT NOT NULL,
        type        TEXT NOT NULL,
        weight      REAL DEFAULT 1.0,
        label       TEXT,
        properties  TEXT DEFAULT '{}',
        FOREIGN KEY (from_id) REFERENCES nodes(id),
        FOREIGN KEY (to_id)   REFERENCES nodes(id)
    );

    CREATE TABLE IF NOT EXISTS scan_metadata (
        key   TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_nodes_type  ON nodes(type);
    CREATE INDEX IF NOT EXISTS idx_nodes_layer ON nodes(layer);
    CREATE INDEX IF NOT EXISTS idx_edges_from  ON edges(from_id);
    CREATE INDEX IF NOT EXISTS idx_edges_to    ON edges(to_id);
    CREATE INDEX IF NOT EXISTS idx_edges_type  ON edges(type);
    """

    def __init__(self, db_path: str = ".claraity/claraity_knowledge.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        # Auto-import: if DB missing but JSONL exists, rebuild
        if not self.db_path.exists():
            jsonl_path = self.db_path.with_suffix(".jsonl")
            if jsonl_path.exists():
                self._rebuild_from_jsonl(jsonl_path)
                return
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

    FTS_SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
        node_id UNINDEXED,
        node_type UNINDEXED,
        name,
        description,
        extra_text,
        tokenize='unicode61'
    );
    """

    def _ensure_schema(self):
        with self._cursor() as cur:
            cur.executescript(self.SCHEMA)
            cur.executescript(self.FTS_SCHEMA)
            self._backfill_fts_if_needed(cur)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _make_id(prefix: str, name: str) -> str:
        """Deterministic short hash ID: prefix + 6-char hex."""
        h = hashlib.sha256(name.encode()).hexdigest()[:6]
        return f"{prefix}-{h}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- FTS helpers ----------------------------------------------------------

    def _build_extra_text(self, cur, node_id: str, properties: dict = None) -> str:
        """Build the extra_text column for FTS: edge labels + properties."""
        parts = []
        # Edge labels involving this node
        cur.execute(
            "SELECT label FROM edges WHERE (from_id=? OR to_id=?) AND label IS NOT NULL",
            (node_id, node_id),
        )
        for row in cur.fetchall():
            parts.append(row[0])
        # Flattened properties values
        if properties:
            for v in properties.values():
                if isinstance(v, str):
                    parts.append(v)
                elif isinstance(v, list):
                    parts.extend(str(item) for item in v)
        return " ".join(parts)

    def _upsert_fts(self, cur, node_id: str, node_type: str, name: str,
                    description: str, properties: dict = None) -> None:
        """Insert or replace a node's FTS entry."""
        extra = self._build_extra_text(cur, node_id, properties)
        cur.execute("DELETE FROM nodes_fts WHERE node_id=?", (node_id,))
        cur.execute(
            "INSERT INTO nodes_fts (node_id, node_type, name, description, extra_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, node_type, name, description or "", extra),
        )

    def _delete_fts(self, cur, node_id: str) -> None:
        """Remove a node's FTS entry."""
        cur.execute("DELETE FROM nodes_fts WHERE node_id=?", (node_id,))

    def _backfill_fts_if_needed(self, cur) -> None:
        """One-time backfill: populate FTS from existing nodes if FTS is empty."""
        fts_count = cur.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()[0]
        node_count = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        if fts_count == 0 and node_count > 0:
            self._rebuild_fts_index(cur)

    def _rebuild_fts_index(self, cur) -> None:
        """Full rebuild of FTS index from nodes table."""
        cur.execute("DELETE FROM nodes_fts")
        rows = cur.execute(
            "SELECT id, type, name, description, properties FROM nodes"
        ).fetchall()
        for row in rows:
            props = json.loads(row[4]) if row[4] else {}
            extra = self._build_extra_text(cur, row[0], props)
            cur.execute(
                "INSERT INTO nodes_fts (node_id, node_type, name, description, extra_text) "
                "VALUES (?, ?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3] or "", extra),
            )

    # -- Internal implementations (take a cursor, no commit) -----------------

    def _add_node_impl(
        self,
        cur,
        node_id: str,
        node_type: str,
        layer: int,
        name: str,
        description: str = "",
        file_path: str = None,
        line_count: int = None,
        risk_level: str = "low",
        properties: dict = None,
    ) -> None:
        now = self._now()
        cur.execute(
            """INSERT OR REPLACE INTO nodes
               (id, type, layer, name, description, file_path, line_count,
                risk_level, properties, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node_id,
                node_type,
                layer,
                name,
                description,
                file_path,
                line_count,
                risk_level,
                json.dumps(properties or {}),
                now,
                now,
            ),
        )
        self._upsert_fts(cur, node_id, node_type, name, description, properties)

    def _add_edge_impl(
        self,
        cur,
        from_id: str,
        to_id: str,
        edge_type: str,
        weight: float = 1.0,
        label: str = None,
        properties: dict = None,
    ) -> str:
        eid = self._make_id("e", f"{from_id}:{to_id}:{edge_type}")
        cur.execute(
            """INSERT OR REPLACE INTO edges
               (id, from_id, to_id, type, weight, label, properties)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (eid, from_id, to_id, edge_type, weight, label, json.dumps(properties or {})),
        )
        return eid

    def _update_node_impl(
        self,
        cur,
        node_id: str,
        description: str = None,
        risk_level: str = None,
        line_count: int = None,
        properties: dict = None,
    ) -> int:
        """Update specific fields of an existing node. Only non-None fields are changed.

        Returns the number of rows affected (0 if node not found, 1 if updated).
        """
        updates = []
        values = []
        if description is not None:
            updates.append("description=?")
            values.append(description)
        if risk_level is not None:
            updates.append("risk_level=?")
            values.append(risk_level)
        if line_count is not None:
            updates.append("line_count=?")
            values.append(line_count)
        if properties is not None:
            updates.append("properties=?")
            values.append(json.dumps(properties))

        if not updates:
            # Nothing to update; check existence
            cur.execute("SELECT id FROM nodes WHERE id=?", (node_id,))
            return 1 if cur.fetchone() else 0

        updates.append("updated_at=?")
        values.append(self._now())
        values.append(node_id)

        cur.execute(
            f"UPDATE nodes SET {', '.join(updates)} WHERE id=?",
            tuple(values),
        )
        rowcount = cur.rowcount
        # Re-index FTS with current node data
        if rowcount > 0:
            row = cur.execute(
                "SELECT type, name, description, properties FROM nodes WHERE id=?",
                (node_id,),
            ).fetchone()
            if row:
                props = json.loads(row[3]) if row[3] else {}
                self._upsert_fts(cur, node_id, row[0], row[1], row[2], props)
        return rowcount

    def _remove_node_impl(self, cur, node_id: str) -> tuple[bool, int]:
        """Remove a node and all its connected edges. Returns (node_deleted, edges_removed)."""
        self._delete_fts(cur, node_id)
        cur.execute("DELETE FROM edges WHERE from_id=? OR to_id=?", (node_id, node_id))
        edge_count = cur.rowcount
        cur.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        node_deleted = cur.rowcount > 0
        return node_deleted, edge_count

    def _remove_edge_impl(self, cur, from_id: str, to_id: str, edge_type: str) -> bool:
        """Remove an edge by its from/to/type triple. Returns True if deleted."""
        eid = self._make_id("e", f"{from_id}:{to_id}:{edge_type}")
        cur.execute("DELETE FROM edges WHERE id=?", (eid,))
        return cur.rowcount > 0

    # -- Write (public wrappers) -----------------------------------------------

    def add_node(
        self,
        id: str,
        type: str,
        layer: int,
        name: str,
        description: str = "",
        file_path: str = None,
        line_count: int = None,
        risk_level: str = "low",
        properties: dict = None,
    ) -> str:
        with self._cursor() as cur:
            self._add_node_impl(
                cur, node_id=id, node_type=type, layer=layer, name=name,
                description=description, file_path=file_path, line_count=line_count,
                risk_level=risk_level, properties=properties,
            )
        return id

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        type: str,
        weight: float = 1.0,
        label: str = None,
        properties: dict = None,
    ) -> str:
        with self._cursor() as cur:
            eid = self._add_edge_impl(
                cur, from_id=from_id, to_id=to_id, edge_type=type,
                weight=weight, label=label, properties=properties,
            )
        return eid

    def set_metadata(self, key: str, value: str):
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO scan_metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

    def update_node(
        self,
        node_id: str,
        description: str = None,
        risk_level: str = None,
        line_count: int = None,
        properties: dict = None,
    ) -> bool:
        """Update specific fields of an existing node. Only non-None fields are changed.

        Returns True if the node was found and updated.
        """
        with self._cursor() as cur:
            rowcount = self._update_node_impl(
                cur, node_id=node_id, description=description,
                risk_level=risk_level, line_count=line_count, properties=properties,
            )
            return rowcount > 0

    def remove_node(self, node_id: str) -> tuple[bool, int]:
        """Remove a node and all its connected edges. Returns (node_deleted, edges_removed)."""
        with self._cursor() as cur:
            return self._remove_node_impl(cur, node_id)

    def remove_edge(self, from_id: str, to_id: str, edge_type: str) -> bool:
        """Remove an edge by its from/to/type triple. Returns True if deleted."""
        with self._cursor() as cur:
            return self._remove_edge_impl(cur, from_id, to_id, edge_type)

    # -- Batch -----------------------------------------------------------------

    def batch_operations(self, operations: list[dict]) -> dict:
        """Execute multiple add/update/remove operations in one batch.

        Individual failures are caught and reported without stopping the batch.
        Successfully completed operations ARE committed even if later operations
        fail (partial success model).

        Each operation is a dict with an "op" key and the relevant parameters.
        Returns summary: {"succeeded": N, "failed": N, "errors": [...]}
        """
        succeeded = 0
        failed = 0
        errors = []

        with self._cursor() as cur:
            for i, op_dict in enumerate(operations):
                op = op_dict.get("op", "")
                try:
                    if op == "add_node":
                        self._add_node_impl(
                            cur,
                            node_id=op_dict["node_id"],
                            node_type=op_dict["node_type"],
                            layer=op_dict.get("layer", 3),
                            name=op_dict["name"],
                            description=op_dict.get("description", ""),
                            file_path=op_dict.get("file_path"),
                            line_count=op_dict.get("line_count"),
                            risk_level=op_dict.get("risk_level", "low"),
                            properties=op_dict.get("properties"),
                        )
                        succeeded += 1

                    elif op == "update_node":
                        rowcount = self._update_node_impl(
                            cur,
                            node_id=op_dict["node_id"],
                            description=op_dict.get("description"),
                            risk_level=op_dict.get("risk_level"),
                            line_count=op_dict.get("line_count"),
                            properties=op_dict.get("properties"),
                        )
                        if rowcount == 0:
                            failed += 1
                            errors.append(f"[{i}] update_node: node '{op_dict['node_id']}' not found")
                            continue
                        succeeded += 1

                    elif op == "add_edge":
                        self._add_edge_impl(
                            cur,
                            from_id=op_dict["from_id"],
                            to_id=op_dict["to_id"],
                            edge_type=op_dict["edge_type"],
                            weight=op_dict.get("weight", 1.0),
                            label=op_dict.get("label"),
                            properties=op_dict.get("properties"),
                        )
                        succeeded += 1

                    elif op == "remove_node":
                        self._remove_node_impl(cur, op_dict["node_id"])
                        succeeded += 1

                    elif op == "remove_edge":
                        self._remove_edge_impl(
                            cur,
                            from_id=op_dict["from_id"],
                            to_id=op_dict["to_id"],
                            edge_type=op_dict["edge_type"],
                        )
                        succeeded += 1

                    else:
                        failed += 1
                        errors.append(f"[{i}] Unknown op: {op}")

                except Exception as e:
                    failed += 1
                    errors.append(f"[{i}] {op} failed: {e}")

        return {"succeeded": succeeded, "failed": failed, "errors": errors}

    # -- Read ------------------------------------------------------------------

    def get_all_nodes(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM nodes ORDER BY layer, type, name")
            return [dict(r) for r in cur.fetchall()]

    def get_all_edges(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM edges ORDER BY type")
            return [dict(r) for r in cur.fetchall()]

    def get_metadata(self) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT key, value FROM scan_metadata")
            return {r["key"]: r["value"] for r in cur.fetchall()}

    def get_stats(self) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) as c FROM nodes")
            nodes = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM edges")
            edges = cur.fetchone()["c"]
            cur.execute("SELECT type, COUNT(*) as c FROM nodes GROUP BY type ORDER BY c DESC")
            node_types = {r["type"]: r["c"] for r in cur.fetchall()}
            cur.execute("SELECT type, COUNT(*) as c FROM edges GROUP BY type ORDER BY c DESC")
            edge_types = {r["type"]: r["c"] for r in cur.fetchall()}
        return {
            "total_nodes": nodes,
            "total_edges": edges,
            "node_types": node_types,
            "edge_types": edge_types,
        }

    @staticmethod
    def parse_properties(node: dict) -> dict:
        """Parse the properties field of a node, handling double-encoded JSON strings."""
        p = node.get("properties", "{}")
        if isinstance(p, str):
            try:
                parsed = json.loads(p)
                if isinstance(parsed, str):
                    return json.loads(parsed)
                return parsed
            except (json.JSONDecodeError, TypeError):
                return {}
        return p if isinstance(p, dict) else {}

    def query(
        self,
        node_id: str = None,
        node_type: str = None,
        related_to: str = None,
        show: str = "detail",
        keyword: str = None,
        search: str = None,
        module_id: str = None,
        file_path: str = None,
        impact: str = None,
    ) -> str:
        """Unified query tool. All parameters optional; combine for compound queries.

        Parameters:
          search="token"                   -> FTS5 full-text search (ranked, snippets)
          search="token", node_type="decision" -> FTS5 filtered by type
          node_id="comp-x"                 -> detail for that node + its edges
          node_id="comp-x, mod-core"       -> detail for multiple nodes
          node_type="invariant"            -> list all nodes of that type
          module_id="mod-core"             -> module detail (components, files, deps)
          file_path="src/core/agent.py"    -> file context (role, module, decisions)
          impact="comp-message-store"      -> blast radius analysis
          related_to="mod-core"            -> all edges involving that node
          related_to="mod-core", show="constraints" -> decisions/invariants for that node
          keyword="memory"                 -> simple substring search (prefer search= for FTS)
          show="brief"                     -> compact architecture overview
          show="overview"                  -> architecture overview from metadata
          show="metadata"                  -> all scan_metadata key-value pairs
          (no params)                      -> stats summary
        """
        sections = []

        # -- Dispatchers that return immediately (no graph needed) --
        if show == "brief":
            from src.claraity.claraity_db import render_compact_briefing
            return render_compact_briefing(self)
        if show == "overview":
            return self._query_overview()
        if show == "metadata":
            return self._query_metadata()

        # -- FTS search --
        if search:
            from src.claraity.claraity_db import render_search
            sections.append(render_search(self, search, node_type=node_type))

        # -- Module detail --
        if module_id:
            from src.claraity.claraity_db import render_module_detail
            sections.append(render_module_detail(self, module_id))

        # -- File detail --
        if file_path:
            from src.claraity.claraity_db import render_file_detail
            sections.append(render_file_detail(self, file_path))

        # -- Impact analysis --
        if impact:
            from src.claraity.claraity_db import render_impact
            sections.append(render_impact(self, impact))

        # If any of the above produced results, append node_id/keyword/type
        # below. If none of the above matched, fall through to graph queries.

        # -- Graph-based queries --
        all_nodes = None
        all_edges = None
        node_map = None

        def _ensure_graph():
            nonlocal all_nodes, all_edges, node_map
            if all_nodes is None:
                all_nodes = self.get_all_nodes()
                all_edges = self.get_all_edges()
                node_map = {n["id"]: n for n in all_nodes}

        if keyword and not search:
            _ensure_graph()
            sections.append(self._query_keyword(keyword, all_nodes))

        if node_id:
            _ensure_graph()
            # Support comma-separated node IDs
            ids = [nid.strip() for nid in node_id.split(",") if nid.strip()]
            for nid in ids:
                sections.append(self._query_node(nid, node_map, all_edges))

        if node_type and not search:
            _ensure_graph()
            sections.append(self._query_type(node_type, all_nodes))

        if related_to:
            _ensure_graph()
            sections.append(self._query_related(related_to, node_map, all_edges, show))

        if sections:
            return "\n\n---\n\n".join(sections)

        return self._query_stats()

    def _query_overview(self) -> str:
        meta = self.get_metadata()
        overview = meta.get("architecture_overview", "No architecture overview stored yet.")
        return f"# Architecture Overview\n\n{overview}"

    def _query_metadata(self) -> str:
        meta = self.get_metadata()
        if not meta:
            return "No metadata stored."
        lines = ["# Knowledge DB Metadata", ""]
        for k, v in sorted(meta.items()):
            preview = v[:200] + "..." if len(v) > 200 else v
            lines.append(f"- **{k}**: {preview}")
        return "\n".join(lines)

    def _query_keyword(self, keyword: str, all_nodes: list[dict]) -> str:
        kw = keyword.lower()
        matches = []
        for n in all_nodes:
            if n["type"] == "file" and self.parse_properties(n).get("role") == "package init":
                continue
            name_match = kw in (n.get("name") or "").lower()
            desc_match = kw in (n.get("description") or "").lower()
            if name_match or desc_match:
                matches.append(n)
        if not matches:
            return f"No results for '{keyword}'."
        lines = [f'## Search: "{keyword}" ({len(matches)} matches)', ""]
        for m in matches[:15]:
            lines.append(f"### {m['name']} ({m['type']})")
            if m.get("file_path"):
                lines.append(f"- **File**: {m['file_path']}")
            if m.get("description"):
                lines.append(f"- **Description**: {m['description']}")
            lines.append("")
        return "\n".join(lines)

    def _query_node(self, node_id: str, node_map: dict, all_edges: list[dict]) -> str:
        node = node_map.get(node_id)
        if not node:
            return f"Node '{node_id}' not found."
        lines = [
            f"## {node['name']} ({node['type']})",
            f"- **ID**: {node['id']}",
            f"- **Layer**: {node['layer']}",
        ]
        if node.get("description"):
            lines.append(f"- **Description**: {node['description']}")
        if node.get("file_path"):
            lines.append(f"- **File**: {node['file_path']}")
        if node.get("line_count"):
            lines.append(f"- **Lines**: {node['line_count']}")
        lines.append(f"- **Risk**: {node.get('risk_level', 'low')}")
        props = self.parse_properties(node)
        for k, v in props.items():
            if k in ("flow_rank", "flow_col"):
                continue
            lines.append(f"- **{k}**: {v}")
        lines.append("")
        # Edges
        out_edges = [e for e in all_edges if e["from_id"] == node_id]
        in_edges = [e for e in all_edges if e["to_id"] == node_id]
        if out_edges:
            lines.append("### Outgoing Edges")
            for e in out_edges:
                target = node_map.get(e["to_id"], {}).get("name", e["to_id"])
                lbl = f' - "{e["label"]}"' if e.get("label") else ""
                lines.append(f"- --{e['type']}--> {target}{lbl}")
            lines.append("")
        if in_edges:
            lines.append("### Incoming Edges")
            for e in in_edges:
                source = node_map.get(e["from_id"], {}).get("name", e["from_id"])
                lbl = f' - "{e["label"]}"' if e.get("label") else ""
                lines.append(f"- {source} --{e['type']}-->{lbl}")
            lines.append("")
        return "\n".join(lines)

    def _query_type(self, node_type: str, all_nodes: list[dict]) -> str:
        matches = [n for n in all_nodes if n["type"] == node_type]
        if not matches:
            return f"No nodes of type '{node_type}'."
        lines = [f"## {node_type.title()} Nodes ({len(matches)})", ""]
        for n in matches:
            desc = (n.get("description") or "")[:80]
            lines.append(f"- **{n['name']}** (`{n['id']}`): {desc}")
        return "\n".join(lines)

    def _query_related(self, related_to: str, node_map: dict, all_edges: list[dict], show: str) -> str:
        if show == "constraints":
            constraint_edges = [
                e for e in all_edges
                if e["type"] == "constrains" and e["to_id"] == related_to
            ]
            if not constraint_edges:
                return f"No constraints found for '{related_to}'."
            lines = [f"## Constraints for {related_to}", ""]
            for e in constraint_edges:
                src = node_map.get(e["from_id"])
                if src:
                    lines.append(f"- **{src['name']}** ({src['type']}): {src.get('description', '')}")
            return "\n".join(lines)
        else:
            edges = [e for e in all_edges if e["from_id"] == related_to or e["to_id"] == related_to]
            if not edges:
                return f"No edges found for '{related_to}'."
            lines = [f"## Edges for {related_to}", ""]
            for e in edges:
                src = node_map.get(e["from_id"], {}).get("name", e["from_id"])
                tgt = node_map.get(e["to_id"], {}).get("name", e["to_id"])
                lbl = f' "{e["label"]}"' if e.get("label") else ""
                lines.append(f"- {src} --{e['type']}--> {tgt}{lbl}")
            return "\n".join(lines)

    def _query_stats(self) -> str:
        stats = self.get_stats()
        lines = ["## Knowledge DB Stats"]
        lines.append(f"- **Nodes**: {stats['total_nodes']}")
        lines.append(f"- **Edges**: {stats['total_edges']}")
        if stats["node_types"]:
            lines.append(f"- **Node types**: {', '.join(f'{t}={c}' for t, c in stats['node_types'].items())}")
        if stats["edge_types"]:
            lines.append(f"- **Edge types**: {', '.join(f'{t}={c}' for t, c in stats['edge_types'].items())}")
        return "\n".join(lines)

    # -- Full-text search (FTS5) ----------------------------------------------

    @staticmethod
    def _normalize_fts_query(query: str) -> str:
        """Convert plain multi-word queries to OR queries for FTS5.

        FTS5 uses implicit AND for space-separated words, which is too strict
        for natural-language queries from the agent (e.g., "settings config panel
        subagent" would require ALL words in a single node).

        This converts plain multi-word queries to use OR so any matching word
        returns results, ranked by relevance. Explicit FTS5 syntax (AND, OR, NOT,
        quotes, prefix *, column:) is left untouched.
        """
        # If the query already uses explicit FTS5 operators, pass through as-is
        fts5_markers = (" AND ", " OR ", " NOT ", '"', "*", ":")
        if any(marker in query for marker in fts5_markers):
            return query

        words = query.split()
        if len(words) <= 1:
            return query

        return " OR ".join(words)

    def search_fts(
        self,
        query: str,
        node_type: str = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search across all node content using SQLite FTS5.

        Supports FTS5 query syntax:
          - Simple keywords: "streaming"
          - Boolean: "async AND streaming", "memory NOT test"
          - Prefix: "stream*"
          - Phrase: '"message store"'
          - Column filter: "description:persistence"

        Plain multi-word queries (no operators) are auto-converted to OR queries
        so that any matching word returns results, ranked by relevance.

        Args:
            query: FTS5 query string
            node_type: Optional filter by node type (module, component, decision, etc.)
            limit: Max results (default 20)

        Returns:
            List of dicts with node_id, node_type, name, snippet, rank.
        """
        query = self._normalize_fts_query(query)
        with self._cursor() as cur:
            if node_type:
                sql = (
                    "SELECT node_id, node_type, name, "
                    "snippet(nodes_fts, 3, '**', '**', '...', 48) as snippet, "
                    "rank "
                    "FROM nodes_fts "
                    "WHERE nodes_fts MATCH ? AND node_type = ? "
                    "ORDER BY rank "
                    "LIMIT ?"
                )
                rows = cur.execute(sql, (query, node_type, limit)).fetchall()
            else:
                sql = (
                    "SELECT node_id, node_type, name, "
                    "snippet(nodes_fts, 3, '**', '**', '...', 48) as snippet, "
                    "rank "
                    "FROM nodes_fts "
                    "WHERE nodes_fts MATCH ? "
                    "ORDER BY rank "
                    "LIMIT ?"
                )
                rows = cur.execute(sql, (query, limit)).fetchall()

            results = []
            for row in rows:
                results.append({
                    "node_id": row[0],
                    "node_type": row[1],
                    "name": row[2],
                    "snippet": row[3],
                    "rank": row[4],
                })
            return results

    def auto_layout(self) -> dict:
        """Compute flow_rank/flow_col for all modules based on dependency graph.

        Algorithm:
        1. Build directed graph from module-level edges
        2. Find strongly connected components (handles cycles)
        3. Topological sort the SCC DAG
        4. Assign flow_rank = topological depth
        5. Within each rank, sort by edge count (most connected = center)
        6. Update module node properties

        Returns: {"modules_updated": N, "ranks": {rank: [module_ids]}}
        """
        from collections import defaultdict, deque

        nodes = self.get_all_nodes()
        edges = self.get_all_edges()

        modules = {n["id"]: n for n in nodes if n["type"] == "module"}
        if not modules:
            return {"modules_updated": 0, "ranks": {}}

        # Also position system nodes at rank 0
        systems = {n["id"]: n for n in nodes if n["type"] == "system"}

        # Build adjacency list from module-to-module edges (not contains/constrains)
        # Also consider component-level edges that cross module boundaries
        child_to_module = {}
        for e in edges:
            if e["type"] == "contains" and e["from_id"] in modules:
                child_to_module[e["to_id"]] = e["from_id"]

        graph: dict[str, set[str]] = defaultdict(set)  # from -> set(to)
        reverse: dict[str, set[str]] = defaultdict(set)
        for e in edges:
            if e["type"] in ("contains", "constrains"):
                continue
            # Resolve to module level
            from_mod = modules.get(e["from_id"]) and e["from_id"]
            if not from_mod:
                from_mod = child_to_module.get(e["from_id"])
            to_mod = modules.get(e["to_id"]) and e["to_id"]
            if not to_mod:
                to_mod = child_to_module.get(e["to_id"])
            if from_mod and to_mod and from_mod != to_mod:
                graph[from_mod].add(to_mod)
                reverse[to_mod].add(from_mod)

        # Tarjan's SCC algorithm
        mod_ids = list(modules.keys())
        index_counter = [0]
        stack: list[str] = []
        lowlink: dict[str, int] = {}
        index: dict[str, int] = {}
        on_stack: set[str] = set()
        sccs: list[list[str]] = []

        def strongconnect(v: str):
            index[v] = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)

            for w in graph.get(v, set()):
                if w not in modules:
                    continue
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])

            if lowlink[v] == index[v]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == v:
                        break
                sccs.append(scc)

        for v in mod_ids:
            if v not in index:
                strongconnect(v)

        # Map each module to its SCC index
        mod_to_scc: dict[str, int] = {}
        for i, scc in enumerate(sccs):
            for m in scc:
                mod_to_scc[m] = i

        # Build SCC-level DAG
        scc_graph: dict[int, set[int]] = defaultdict(set)
        scc_in_degree: dict[int, int] = defaultdict(int)
        for i in range(len(sccs)):
            scc_in_degree[i] = 0

        for from_mod, to_mods in graph.items():
            if from_mod not in mod_to_scc:
                continue
            from_scc = mod_to_scc[from_mod]
            for to_mod in to_mods:
                if to_mod not in mod_to_scc:
                    continue
                to_scc = mod_to_scc[to_mod]
                if from_scc != to_scc and to_scc not in scc_graph[from_scc]:
                    scc_graph[from_scc].add(to_scc)
                    scc_in_degree[to_scc] += 1

        # Topological sort via Kahn's algorithm (BFS)
        queue = deque([i for i in range(len(sccs)) if scc_in_degree[i] == 0])
        scc_rank: dict[int, int] = {}
        while queue:
            scc_idx = queue.popleft()
            if scc_idx not in scc_rank:
                scc_rank[scc_idx] = 0
            for dep_scc in scc_graph.get(scc_idx, set()):
                new_rank = scc_rank[scc_idx] + 1
                scc_rank[dep_scc] = max(scc_rank.get(dep_scc, 0), new_rank)
                scc_in_degree[dep_scc] -= 1
                if scc_in_degree[dep_scc] == 0:
                    queue.append(dep_scc)

        # Handle any SCCs not reached (isolated modules)
        for i in range(len(sccs)):
            if i not in scc_rank:
                scc_rank[i] = 0

        # Assign flow_rank to modules (offset by 1 to leave room for system nodes at rank 0)
        # Isolated modules (no edges at all) go to the bottom, not the top
        max_rank = max(scc_rank.values()) if scc_rank else 0
        mod_rank: dict[str, int] = {}
        for mod_id in mod_ids:
            has_any_edge = mod_id in graph or mod_id in reverse
            if mod_id in mod_to_scc and has_any_edge:
                mod_rank[mod_id] = scc_rank[mod_to_scc[mod_id]] + 1  # +1 for system row
            else:
                mod_rank[mod_id] = max_rank + 2  # isolated modules go to bottom

        # Within each rank, sort by total edge count (most connected first, center)
        ranks: dict[int, list[str]] = defaultdict(list)
        for mod_id, rank in mod_rank.items():
            ranks[rank].append(mod_id)

        mod_edge_count: dict[str, int] = defaultdict(int)
        for from_mod, to_mods in graph.items():
            mod_edge_count[from_mod] += len(to_mods)
        for to_mod, from_mods in reverse.items():
            mod_edge_count[to_mod] += len(from_mods)

        for rank in ranks:
            ranks[rank].sort(key=lambda m: -mod_edge_count.get(m, 0))

        # Assign flow_col within each rank
        mod_col: dict[str, int] = {}
        for rank, mods in ranks.items():
            for i, mod_id in enumerate(mods):
                mod_col[mod_id] = i

        # Update module node properties
        def _parse_props(raw) -> dict:
            """Parse properties, handling double-encoded JSON strings."""
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return parsed
                    if isinstance(parsed, str):
                        return json.loads(parsed)
                except (ValueError, TypeError):
                    pass
            return {}

        updated = 0
        for mod_id in mod_ids:
            node = modules[mod_id]
            props = _parse_props(node.get("properties", "{}"))
            props["flow_rank"] = mod_rank.get(mod_id, 99)
            props["flow_col"] = mod_col.get(mod_id, 0)
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE nodes SET properties = ? WHERE id = ?",
                    (json.dumps(props), mod_id),
                )
            updated += 1

        # Update system nodes: rank 0, sorted by flow_col
        sys_col = 0
        for sys_id in sorted(systems.keys()):
            node = systems[sys_id]
            props = _parse_props(node.get("properties", "{}"))
            props["flow_rank"] = 0
            props["flow_col"] = sys_col
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE nodes SET properties = ? WHERE id = ?",
                    (json.dumps(props), sys_id),
                )
            sys_col += 1
            updated += 1

        return {
            "modules_updated": updated,
            "ranks": {r: mods for r, mods in sorted(ranks.items())},
        }

    def _rebuild_from_jsonl(self, jsonl_path: Path):
        """Rebuild this store's DB from a JSONL file (called from __init__)."""
        rebuilt = ClaraityStore.import_jsonl(str(jsonl_path), str(self.db_path))
        self.conn = rebuilt.conn
        rebuilt.conn = None  # Transfer ownership, prevent double-close

    # -- JSONL Export/Import ---------------------------------------------------

    def export_jsonl(self, path: str = ".claraity/claraity_knowledge.jsonl") -> int:
        """Export entire DB to JSONL for git tracking. Returns line count.

        Order: metadata first, then nodes, then edges (for FK-safe import).
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(out, "w", encoding="utf-8") as f:
            # Metadata
            for key, value in sorted(self.get_metadata().items()):
                f.write(json.dumps({"_t": "meta", "key": key, "value": value}, default=str) + "\n")
                count += 1
            # Nodes
            for n in self.get_all_nodes():
                rec = dict(n)
                rec["_t"] = "node"
                # Parse properties JSON string to dict for cleaner JSONL
                if isinstance(rec.get("properties"), str):
                    try:
                        rec["properties"] = json.loads(rec["properties"])
                    except (ValueError, TypeError):
                        pass
                f.write(json.dumps(rec, default=str) + "\n")
                count += 1
            # Edges
            for e in self.get_all_edges():
                rec = dict(e)
                rec["_t"] = "edge"
                if isinstance(rec.get("properties"), str):
                    try:
                        rec["properties"] = json.loads(rec["properties"])
                    except (ValueError, TypeError):
                        pass
                f.write(json.dumps(rec, default=str) + "\n")
                count += 1
        return count

    @classmethod
    def import_jsonl(
        cls, jsonl_path: str, db_path: str = ".claraity/claraity_knowledge.db"
    ) -> "ClaraityStore":
        """Rebuild SQLite DB from JSONL file. Deletes existing DB first."""
        db = Path(db_path)
        if db.exists():
            db.unlink()
        # Touch the DB file so __init__ sees it exists and skips auto-rebuild
        db.parent.mkdir(parents=True, exist_ok=True)
        db.touch()
        store = cls(db_path)
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                t = rec.pop("_t")
                if t == "meta":
                    store.set_metadata(rec["key"], rec["value"])
                elif t == "node":
                    props = rec.get("properties")
                    if isinstance(props, str):
                        props = json.loads(props)
                    store.add_node(
                        id=rec["id"],
                        type=rec["type"],
                        layer=rec.get("layer", 0),
                        name=rec["name"],
                        description=rec.get("description", ""),
                        file_path=rec.get("file_path"),
                        line_count=rec.get("line_count"),
                        risk_level=rec.get("risk_level", "low"),
                        properties=props if isinstance(props, dict) else {},
                    )
                elif t == "edge":
                    props = rec.get("properties")
                    if isinstance(props, str):
                        props = json.loads(props)
                    store.add_edge(
                        from_id=rec["from_id"],
                        to_id=rec["to_id"],
                        type=rec["type"],
                        label=rec.get("label"),
                        weight=rec.get("weight", 1.0),
                        properties=props if isinstance(props, dict) else {},
                    )
        return store

    # -- Export ----------------------------------------------------------------

    def export_graph_json(self, path: str = ".claraity/graph.json"):
        """Export full graph as JSON for D3.js visualization."""
        nodes = self.get_all_nodes()
        edges = self.get_all_edges()
        metadata = self.get_metadata()
        stats = self.get_stats()

        # Parse properties JSON strings back to dicts
        for n in nodes:
            if isinstance(n.get("properties"), str):
                n["properties"] = json.loads(n["properties"])
        for e in edges:
            if isinstance(e.get("properties"), str):
                e["properties"] = json.loads(e["properties"])

        graph = {
            "metadata": metadata,
            "stats": stats,
            "nodes": nodes,
            "edges": edges,
        }

        # Write to primary location
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2, default=str)

        # Also write to claraity-ui/ for local HTTP serving
        ui_path = Path("claraity-ui/graph.json")
        if ui_path.parent.exists():
            with open(ui_path, "w", encoding="utf-8") as f:
                json.dump(graph, f, indent=2, default=str)

        return graph


# ---------------------------------------------------------------------------
# Populate - encode ClarAIty codebase knowledge
# ---------------------------------------------------------------------------


def populate(store: ClaraityStore):
    """Populate the DB with ClarAIty codebase architectural knowledge."""

    store.set_metadata("repo_name", "ai-coding-agent")
    store.set_metadata("repo_language", "python")
    store.set_metadata("scanned_at", ClaraityStore._now())
    store.set_metadata("scanned_by", "claude-opus-4")
    store.set_metadata("total_files", "224")
    store.set_metadata("total_lines", "~79,320")

    # ======================================================================
    # LAYER 1: System Context
    # ======================================================================

    # flow_rank = vertical row (0=top), flow_col = horizontal position in row
    # Flow: User -> VS Code -> Server -> Core -> Tools/Memory/LLM -> Session -> Persistence

    store.add_node(
        id="sys-user",
        type="system",
        layer=1,
        name="User",
        description="Human developer interacting via TUI or VS Code sidebar",
        properties={"actor_type": "human", "flow_rank": 0, "flow_col": 0},
    )
    store.add_node(
        id="sys-vscode",
        type="system",
        layer=1,
        name="VS Code Extension",
        description="ClarAIty sidebar panel communicating via stdio+TCP protocol",
        properties={"protocol": "stdio+tcp", "framework": "react", "flow_rank": 0, "flow_col": 1},
    )
    store.add_node(
        id="sys-llm-api",
        type="system",
        layer=1,
        name="LLM Providers",
        description="OpenAI, Anthropic, Ollama APIs for language model inference",
        properties={
            "providers": ["openai", "anthropic", "ollama", "vllm"],
            "flow_rank": 0,
            "flow_col": 4,
        },
    )
    store.add_node(
        id="sys-filesystem",
        type="system",
        layer=1,
        name="Local Filesystem",
        description="Workspace files, project code, configuration, session data",
        properties={"flow_rank": 0, "flow_col": 5},
    )
    store.add_node(
        id="sys-lsp",
        type="system",
        layer=1,
        name="Language Server (LSP)",
        description="jedi-language-server for Python code intelligence",
        properties={"server": "jedi-language-server", "flow_rank": 0, "flow_col": 6},
    )
    store.add_node(
        id="sys-mcp",
        type="system",
        layer=1,
        name="MCP Servers",
        description="Model Context Protocol servers providing external tools",
        properties={"flow_rank": 0, "flow_col": 7},
    )
    store.add_node(
        id="sys-web",
        type="system",
        layer=1,
        name="Web / APIs",
        description="Web search, web fetch, Jira, GitHub integrations",
        properties={"flow_rank": 0, "flow_col": 8},
    )

    # ======================================================================
    # LAYER 2: Modules
    # ======================================================================

    # Modules laid out by data flow:
    # Row 1: ui, server (entry points from user/vscode)
    # Row 2: core, director (orchestration hub)
    # Row 3: tools, memory, llm, subagents (capabilities used by core)
    # Row 4: session, hooks, prompts (support layers)
    # Row 5: observability, code_intelligence, integrations, platform (infrastructure)

    modules = [
        (
            "mod-ui",
            "module",
            "src/ui/",
            "Textual TUI: app shell, widgets, formatters",
            20,
            12000,
            "high",
            {
                "key_files": [
                    "app.py",
                    "widgets/tool_card.py",
                    "widgets/message.py",
                    "store_adapter.py",
                ],
                "flow_rank": 1,
                "flow_col": 0,
            },
        ),
        (
            "mod-server",
            "module",
            "src/server/",
            "VS Code communication: stdio+TCP transport, serialization",
            4,
            3500,
            "medium",
            {
                "key_files": ["stdio_server.py", "serializers.py"],
                "flow_rank": 1,
                "flow_col": 1,
            },
        ),
        (
            "mod-core",
            "core",
            "src/core/",
            "Agent control loop, streaming, events, protocol",
            31,
            8500,
            "high",
            {
                "key_files": ["agent.py", "events.py", "protocol.py", "streaming/pipeline.py"],
                "flow_rank": 2,
                "flow_col": 0,
            },
        ),
        (
            "mod-director",
            "module",
            "src/director/",
            "Disciplined workflow: UNDERSTAND > PLAN > EXECUTE > COMPLETE",
            6,
            1500,
            "medium",
            {"key_files": ["adapter.py", "protocol.py", "tools.py"], "flow_rank": 2, "flow_col": 1},
        ),
        (
            "mod-tools",
            "module",
            "src/tools/",
            "Tool definitions, execution, file ops, search, web, delegation",
            11,
            6300,
            "medium",
            {
                "key_files": [
                    "file_operations.py",
                    "tool_schemas.py",
                    "delegation.py",
                    "web_tools.py",
                ],
                "flow_rank": 3,
                "flow_col": 0,
            },
        ),
        (
            "mod-memory",
            "module",
            "src/memory/",
            "Multi-layer memory: working, episodic, file-based, observation store",
            6,
            3700,
            "high",
            {
                "key_files": ["memory_manager.py", "working_memory.py", "observation_store.py"],
                "flow_rank": 3,
                "flow_col": 1,
            },
        ),
        (
            "mod-llm",
            "module",
            "src/llm/",
            "LLM provider abstraction: OpenAI, Anthropic, Ollama backends",
            11,
            6000,
            "medium",
            {
                "key_files": [
                    "openai_backend.py",
                    "anthropic_backend.py",
                    "base.py",
                    "failure_handler.py",
                ],
                "flow_rank": 3,
                "flow_col": 2,
            },
        ),
        (
            "mod-subagents",
            "module",
            "src/subagents/",
            "Isolated lightweight agents for task delegation",
            5,
            2900,
            "medium",
            {
                "key_files": ["subagent.py", "manager.py", "config.py"],
                "flow_rank": 3,
                "flow_col": 3,
            },
        ),
        (
            "mod-session",
            "module",
            "src/session/",
            "Unified persistence: JSONL ledger + in-memory MessageStore projection",
            15,
            3500,
            "medium",
            {
                "key_files": [
                    "store/memory_store.py",
                    "models/message.py",
                    "persistence/writer.py",
                ],
                "flow_rank": 4,
                "flow_col": 0,
            },
        ),
        (
            "mod-hooks",
            "module",
            "src/hooks/",
            "User-defined hook extensibility",
            4,
            700,
            "low",
            {"key_files": ["manager.py"], "flow_rank": 4, "flow_col": 1},
        ),
        (
            "mod-prompts",
            "module",
            "src/prompts/",
            "System prompts, subagent prompts, templates",
            5,
            4100,
            "low",
            {
                "key_files": ["system_prompts.py", "enhanced_prompts.py", "subagents/__init__.py"],
                "flow_rank": 4,
                "flow_col": 2,
            },
        ),
        (
            "mod-observability",
            "module",
            "src/observability/",
            "Structured logging, error tracking, metrics",
            10,
            4500,
            "low",
            {
                "key_files": ["logging_config.py", "log_query.py", "error_store.py"],
                "flow_rank": 5,
                "flow_col": 0,
            },
        ),
        (
            "mod-code-intel",
            "module",
            "src/code_intelligence/",
            "LSP-based code analysis and symbol context",
            5,
            2000,
            "low",
            {
                "key_files": ["lsp_client_manager.py", "lsp_runtime.py"],
                "flow_rank": 5,
                "flow_col": 1,
            },
        ),
        (
            "mod-integrations",
            "module",
            "src/integrations/",
            "MCP, Jira, secrets management",
            10,
            2500,
            "low",
            {
                "key_files": ["mcp/manager.py", "mcp/client.py", "mcp/registry.py"],
                "flow_rank": 5,
                "flow_col": 2,
            },
        ),
        (
            "mod-platform",
            "module",
            "src/platform/",
            "Cross-platform compatibility (Windows console encoding)",
            2,
            620,
            "low",
            {"key_files": ["windows.py"], "flow_rank": 5, "flow_col": 3},
        ),
    ]

    for mid, mtype, fpath, desc, files, lines, risk, props in modules:
        store.add_node(
            id=mid,
            type="module",
            layer=2,
            name=fpath,
            description=desc,
            file_path=fpath,
            line_count=lines,
            risk_level=risk,
            properties=props,
        )

    # Module inter-dependencies
    mod_deps = [
        ("mod-core", "mod-llm", "uses", "Calls LLM backends via call_llm()"),
        ("mod-core", "mod-memory", "uses", "Reads/writes context via MemoryManager"),
        ("mod-core", "mod-tools", "uses", "Executes tools via ToolExecutor"),
        ("mod-core", "mod-session", "uses", "Persists messages via MessageStore"),
        ("mod-core", "mod-observability", "uses", "Structured logging"),
        ("mod-memory", "mod-session", "uses", "Writes to MessageStore (single writer)"),
        ("mod-memory", "mod-observability", "uses", "Structured logging"),
        ("mod-ui", "mod-core", "uses", "Consumes UIEvents from agent"),
        ("mod-ui", "mod-session", "uses", "Reads from MessageStore via StoreAdapter"),
        ("mod-ui", "mod-observability", "uses", "Structured logging"),
        ("mod-tools", "mod-core", "uses", "Tool base classes, agent interface"),
        ("mod-tools", "mod-code-intel", "uses", "LSP tools call code intelligence"),
        ("mod-llm", "mod-observability", "uses", "Structured logging"),
        ("mod-server", "mod-core", "uses", "Serializes UIEvents for VS Code"),
        ("mod-server", "mod-session", "uses", "Reads store for notifications"),
        ("mod-subagents", "mod-core", "uses", "Implements AgentInterface"),
        ("mod-subagents", "mod-tools", "uses", "Scoped tool access"),
        ("mod-subagents", "mod-llm", "uses", "Own LLM backend"),
        ("mod-subagents", "mod-session", "uses", "Own MessageStore"),
        ("mod-director", "mod-core", "uses", "Phase-based gating of agent"),
        ("mod-director", "mod-prompts", "uses", "Director-specific prompts"),
        ("mod-integrations", "mod-observability", "uses", "Structured logging"),
        ("mod-code-intel", "mod-observability", "uses", "Structured logging"),
        ("mod-hooks", "mod-observability", "uses", "Structured logging"),
        ("mod-prompts", "mod-core", "uses", "References core types"),
        ("mod-prompts", "mod-memory", "uses", "References memory types"),
    ]

    for from_id, to_id, etype, label in mod_deps:
        store.add_edge(from_id, to_id, etype, label=label)

    # System context edges
    sys_edges = [
        ("sys-user", "mod-ui", "interacts", "Types commands in TUI"),
        ("sys-user", "sys-vscode", "interacts", "Uses VS Code sidebar"),
        ("sys-vscode", "mod-server", "communicates", "stdio+TCP protocol"),
        ("mod-llm", "sys-llm-api", "calls", "HTTP API requests"),
        ("mod-tools", "sys-filesystem", "reads_writes", "File operations"),
        ("mod-code-intel", "sys-lsp", "queries", "Symbol/outline requests"),
        ("mod-integrations", "sys-mcp", "connects", "MCP protocol"),
        ("mod-tools", "sys-web", "fetches", "Web search/fetch"),
    ]

    for from_id, to_id, etype, label in sys_edges:
        store.add_edge(from_id, to_id, etype, label=label)

    # ======================================================================
    # LAYER 3: Key Components
    # ======================================================================

    components = [
        # -- Core --
        (
            "comp-coding-agent",
            "component",
            "CodingAgent",
            "Main agent facade: orchestrates LLM calls, tool execution, streaming, memory",
            "src/core/agent.py",
            3307,
            "high",
            {
                "key_methods": [
                    "stream_response()",
                    "execute_tool()",
                    "call_llm()",
                    "from_config()",
                ],
                "pattern": "async generator yields UIEvents",
            },
        ),
        (
            "comp-tool-gating",
            "component",
            "ToolGatingService",
            "4-check pipeline: repeat/plan/director/approval gating before tool execution",
            "src/core/tool_gating.py",
            289,
            "medium",
            {"checks": ["repeat", "plan_mode", "director", "approval"]},
        ),
        (
            "comp-special-handlers",
            "component",
            "SpecialToolHandlers",
            "Async handlers that pause for UI interaction: clarify, plan approval, director",
            "src/core/special_tool_handlers.py",
            417,
            "medium",
            {"handlers": ["handle_clarify", "handle_plan_approval", "handle_director_approval"]},
        ),
        (
            "comp-streaming-pipeline",
            "component",
            "StreamingPipeline",
            "Canonical parser: LLM provider deltas to structured Message segments",
            "src/core/streaming/pipeline.py",
            515,
            "high",
            {
                "input": "ProviderDelta",
                "output": "Message with segments",
                "segments": [
                    "TextSegment",
                    "CodeBlockSegment",
                    "ThinkingSegment",
                    "ToolCallRefSegment",
                ],
            },
        ),
        (
            "comp-ui-protocol",
            "component",
            "UIProtocol",
            "Bidirectional communication contract between agent and UI layer",
            "src/core/protocol.py",
            645,
            "medium",
            {"actions": ["ApprovalResult", "InterruptSignal", "PauseResult", "ClarifyResult"]},
        ),
        (
            "comp-context-builder",
            "component",
            "ContextBuilder",
            "Builds LLM context from memory layers, constraints, and system prompts",
            "src/core/context_builder.py",
            490,
            "medium",
            {},
        ),
        (
            "comp-plan-mode",
            "component",
            "PlanMode",
            "Claude Code-style planning workflow: generate plan, approve, execute",
            "src/core/plan_mode.py",
            410,
            "medium",
            {},
        ),
        (
            "comp-permission-mgr",
            "component",
            "PermissionManager",
            "Controls tool approval policy: plan mode, normal mode, auto-approve mode",
            "src/core/permission_mode.py",
            None,
            "low",
            {"modes": ["plan", "normal", "auto"]},
        ),
        (
            "comp-session-mgr",
            "component",
            "SessionManager",
            "Session lifecycle: create, resume, persist, list sessions",
            "src/core/session_manager.py",
            475,
            "medium",
            {},
        ),
        # -- Memory --
        (
            "comp-memory-mgr",
            "component",
            "MemoryManager",
            "Orchestrates all memory layers; SINGLE WRITER to MessageStore",
            "src/memory/memory_manager.py",
            1450,
            "high",
            {
                "layers": ["working", "episodic", "file_based", "observation"],
                "constraint": "Only component that writes to MessageStore",
            },
        ),
        (
            "comp-working-memory",
            "component",
            "WorkingMemory",
            "Token-tracked recent conversation turns for LLM context window",
            "src/memory/working_memory.py",
            419,
            "medium",
            {},
        ),
        (
            "comp-episodic-memory",
            "component",
            "EpisodicMemory",
            "Compressed event summaries for long-term context retention",
            "src/memory/episodic_memory.py",
            None,
            "low",
            {},
        ),
        (
            "comp-observation-store",
            "component",
            "ObservationStore",
            "Reversible tool output masking to manage context window pressure",
            "src/memory/observation_store.py",
            591,
            "medium",
            {},
        ),
        (
            "comp-compaction",
            "component",
            "Summarizer",
            "LLM-based compression of conversation history to reduce token usage",
            "src/memory/compaction/summarizer.py",
            797,
            "medium",
            {},
        ),
        # -- Session --
        (
            "comp-message-store",
            "component",
            "MessageStore",
            "Thread-safe in-memory message projection with reactive subscriptions",
            "src/session/store/memory_store.py",
            1009,
            "high",
            {
                "features": ["O(1) lookup", "stream_id collapse", "tool linkage", "subscriptions"],
                "notifications": [
                    "MESSAGE_ADDED",
                    "MESSAGE_UPDATED",
                    "MESSAGE_FINALIZED",
                    "TOOL_STATE_UPDATED",
                    "BULK_LOAD_COMPLETE",
                ],
            },
        ),
        (
            "comp-message-model",
            "component",
            "Message",
            "Unified message class with segments: text, code, thinking, tool refs",
            "src/session/models/message.py",
            993,
            "medium",
            {
                "segments": [
                    "TextSegment",
                    "CodeBlockSegment",
                    "ThinkingSegment",
                    "ToolCallRefSegment",
                ]
            },
        ),
        (
            "comp-session-writer",
            "component",
            "SessionWriter",
            "Append-only JSONL file writer for session persistence",
            "src/session/persistence/writer.py",
            423,
            "low",
            {},
        ),
        (
            "comp-hydrator",
            "component",
            "SessionHydrator",
            "Replays JSONL session files into MessageStore for session resume",
            "src/session/manager/hydrator.py",
            None,
            "low",
            {},
        ),
        # -- UI --
        (
            "comp-tui-app",
            "component",
            "CodingAgentApp",
            "Main Textual TUI application: widget composition, event dispatch, store binding",
            "src/ui/app.py",
            3555,
            "high",
            {
                "key_methods": [
                    "compose()",
                    "_stream_response()",
                    "_handle_event()",
                    "replay_session()",
                ],
                "pattern": "Textual App with async event loop",
            },
        ),
        (
            "comp-store-adapter",
            "component",
            "StoreAdapter",
            "READ-ONLY bridge from MessageStore to TUI widgets (never writes)",
            "src/ui/store_adapter.py",
            550,
            "low",
            {"constraint": "READ-ONLY - no write methods allowed"},
        ),
        (
            "comp-tool-card",
            "component",
            "ToolCard",
            "Widget displaying tool execution status, arguments, results, diffs",
            "src/ui/widgets/tool_card.py",
            1083,
            "medium",
            {},
        ),
        (
            "comp-assistant-msg",
            "component",
            "AssistantMessage",
            "Widget rendering streamed assistant responses with segments",
            "src/ui/widgets/message.py",
            1165,
            "medium",
            {},
        ),
        (
            "comp-status-bar",
            "component",
            "StatusBar",
            "Displays model name, token usage, context pressure indicator",
            "src/ui/widgets/status_bar.py",
            660,
            "low",
            {},
        ),
        (
            "comp-clarify-widget",
            "component",
            "ClarifyWidget",
            "Interactive clarification form widget for agent questions",
            "src/ui/widgets/clarify_widget.py",
            639,
            "low",
            {},
        ),
        (
            "comp-subagent-card",
            "component",
            "SubAgentCard",
            "Nested card displaying delegated subagent execution progress",
            "src/ui/widgets/subagent_card.py",
            725,
            "low",
            {},
        ),
        # -- Tools --
        (
            "comp-tool-executor",
            "component",
            "ToolExecutor",
            "Tool registry and thread-pool execution engine",
            "src/tools/base.py",
            None,
            "medium",
            {},
        ),
        (
            "comp-file-ops",
            "component",
            "FileOperations",
            "File system tools: read_file, write_file, edit_file, glob, directory_tree",
            "src/tools/file_operations.py",
            865,
            "medium",
            {"tools": ["read_file", "write_file", "edit_file", "glob_files", "directory_tree"]},
        ),
        (
            "comp-delegation",
            "component",
            "DelegateToSubagent",
            "Tool for spawning isolated subagents to handle delegated tasks",
            "src/tools/delegation.py",
            651,
            "medium",
            {},
        ),
        (
            "comp-search-tools",
            "component",
            "SearchTools",
            "Code search tools: grep, ripgrep, semantic search",
            "src/tools/search_tools.py",
            772,
            "low",
            {},
        ),
        (
            "comp-web-tools",
            "component",
            "WebTools",
            "Web interaction tools: web_search, web_fetch",
            "src/tools/web_tools.py",
            1157,
            "low",
            {},
        ),
        (
            "comp-lsp-tools",
            "component",
            "LSPTools",
            "Code intelligence tools: get_file_outline, get_symbol_context",
            "src/tools/lsp_tools.py",
            650,
            "low",
            {},
        ),
        # -- LLM --
        (
            "comp-openai-backend",
            "component",
            "OpenAIBackend",
            "OpenAI-compatible API client with streaming, tool calling, vision",
            "src/llm/openai_backend.py",
            1678,
            "medium",
            {},
        ),
        (
            "comp-anthropic-backend",
            "component",
            "AnthropicBackend",
            "Anthropic API client with extended thinking, tool use, caching",
            "src/llm/anthropic_backend.py",
            1510,
            "medium",
            {},
        ),
        (
            "comp-failure-handler",
            "component",
            "FailureHandler",
            "Retry logic with exponential backoff and error classification",
            "src/llm/failure_handler.py",
            812,
            "medium",
            {},
        ),
        # -- Server --
        (
            "comp-stdio-server",
            "component",
            "StdioServer",
            "stdio+TCP server for VS Code extension communication",
            "src/server/stdio_server.py",
            1445,
            "high",
            {
                "inbound": ["chat_message", "approval_result", "pause_result"],
                "outbound": ["UIEvents", "StoreNotifications"],
            },
        ),
        # -- Subagents --
        (
            "comp-subagent",
            "component",
            "SubAgent",
            "Isolated lightweight agent with own MessageStore, LLM backend, tools",
            "src/subagents/subagent.py",
            1174,
            "medium",
            {},
        ),
        (
            "comp-subagent-mgr",
            "component",
            "SubAgentManager",
            "Discovery and lifecycle management of subagent configurations",
            "src/subagents/manager.py",
            495,
            "low",
            {},
        ),
        # -- Director --
        (
            "comp-director-adapter",
            "component",
            "DirectorAdapter",
            "State machine enforcing disciplined workflow phases",
            "src/director/adapter.py",
            None,
            "medium",
            {"phases": ["IDLE", "UNDERSTAND", "PLAN", "EXECUTE", "COMPLETE"]},
        ),
        # -- Observability --
        (
            "comp-logging",
            "component",
            "LoggingSystem",
            "structlog + stdlib integration: async-safe, JSONL, redaction, context vars",
            "src/observability/logging_config.py",
            1049,
            "low",
            {"features": ["QueueHandler", "JSONL rotation", "redaction", "context_vars"]},
        ),
        # -- Code Intelligence --
        (
            "comp-lsp-client",
            "component",
            "LSPClientManager",
            "Manages jedi-language-server lifecycle and request/response",
            "src/code_intelligence/lsp_client_manager.py",
            964,
            "low",
            {},
        ),
        # -- Hooks --
        (
            "comp-hook-mgr",
            "component",
            "HookManager",
            "Loads and executes user-defined hooks from .claraity/hooks.py",
            "src/hooks/manager.py",
            536,
            "low",
            {"events": ["PreToolUse", "PostToolUse", "SessionStart"]},
        ),
        # -- MCP --
        (
            "comp-mcp-mgr",
            "component",
            "McpConnectionManager",
            "MCP server connection lifecycle and tool discovery",
            "src/integrations/mcp/manager.py",
            None,
            "low",
            {},
        ),
    ]

    for cid, ctype, name, desc, fpath, lines, risk, props in components:
        store.add_node(
            id=cid,
            type=ctype,
            layer=3,
            name=name,
            description=desc,
            file_path=fpath,
            line_count=lines,
            risk_level=risk,
            properties=props,
        )

    # Component containment (module -> component)
    containment = [
        ("mod-core", "comp-coding-agent"),
        ("mod-core", "comp-tool-gating"),
        ("mod-core", "comp-special-handlers"),
        ("mod-core", "comp-streaming-pipeline"),
        ("mod-core", "comp-ui-protocol"),
        ("mod-core", "comp-context-builder"),
        ("mod-core", "comp-plan-mode"),
        ("mod-core", "comp-permission-mgr"),
        ("mod-core", "comp-session-mgr"),
        ("mod-memory", "comp-memory-mgr"),
        ("mod-memory", "comp-working-memory"),
        ("mod-memory", "comp-episodic-memory"),
        ("mod-memory", "comp-observation-store"),
        ("mod-memory", "comp-compaction"),
        ("mod-session", "comp-message-store"),
        ("mod-session", "comp-message-model"),
        ("mod-session", "comp-session-writer"),
        ("mod-session", "comp-hydrator"),
        ("mod-ui", "comp-tui-app"),
        ("mod-ui", "comp-store-adapter"),
        ("mod-ui", "comp-tool-card"),
        ("mod-ui", "comp-assistant-msg"),
        ("mod-ui", "comp-status-bar"),
        ("mod-ui", "comp-clarify-widget"),
        ("mod-ui", "comp-subagent-card"),
        ("mod-tools", "comp-tool-executor"),
        ("mod-tools", "comp-file-ops"),
        ("mod-tools", "comp-delegation"),
        ("mod-tools", "comp-search-tools"),
        ("mod-tools", "comp-web-tools"),
        ("mod-tools", "comp-lsp-tools"),
        ("mod-llm", "comp-openai-backend"),
        ("mod-llm", "comp-anthropic-backend"),
        ("mod-llm", "comp-failure-handler"),
        ("mod-server", "comp-stdio-server"),
        ("mod-subagents", "comp-subagent"),
        ("mod-subagents", "comp-subagent-mgr"),
        ("mod-director", "comp-director-adapter"),
        ("mod-observability", "comp-logging"),
        ("mod-code-intel", "comp-lsp-client"),
        ("mod-hooks", "comp-hook-mgr"),
        ("mod-integrations", "comp-mcp-mgr"),
    ]

    for parent, child in containment:
        store.add_edge(parent, child, "contains")

    # Component-to-component relationships
    comp_edges = [
        # CodingAgent is the hub
        ("comp-coding-agent", "comp-memory-mgr", "uses", "Reads/writes context"),
        ("comp-coding-agent", "comp-tool-gating", "uses", "Gates tool execution"),
        ("comp-coding-agent", "comp-special-handlers", "uses", "Delegates interactive tools"),
        ("comp-coding-agent", "comp-streaming-pipeline", "uses", "Parses LLM deltas"),
        ("comp-coding-agent", "comp-tool-executor", "uses", "Executes tools"),
        ("comp-coding-agent", "comp-context-builder", "uses", "Builds LLM context"),
        ("comp-coding-agent", "comp-ui-protocol", "uses", "Sends/receives UI actions"),
        ("comp-coding-agent", "comp-openai-backend", "calls", "LLM API calls"),
        ("comp-coding-agent", "comp-anthropic-backend", "calls", "LLM API calls"),
        ("comp-coding-agent", "comp-session-mgr", "uses", "Session lifecycle"),
        ("comp-coding-agent", "comp-plan-mode", "uses", "Planning workflow"),
        ("comp-coding-agent", "comp-permission-mgr", "uses", "Approval policy"),
        # Memory layer
        ("comp-memory-mgr", "comp-working-memory", "uses", "Recent turns"),
        ("comp-memory-mgr", "comp-episodic-memory", "uses", "Compressed history"),
        ("comp-memory-mgr", "comp-observation-store", "uses", "Tool output masking"),
        ("comp-memory-mgr", "comp-message-store", "writes", "SINGLE WRITER to store"),
        ("comp-memory-mgr", "comp-compaction", "uses", "Context compression"),
        # Session layer
        ("comp-message-store", "comp-session-writer", "uses", "Appends to JSONL"),
        ("comp-hydrator", "comp-message-store", "writes", "Replays JSONL into store"),
        # UI layer
        ("comp-tui-app", "comp-store-adapter", "uses", "Reads messages for display"),
        ("comp-store-adapter", "comp-message-store", "reads", "READ-ONLY bridge"),
        ("comp-tui-app", "comp-tool-card", "renders", "Tool execution display"),
        ("comp-tui-app", "comp-assistant-msg", "renders", "Message display"),
        ("comp-tui-app", "comp-status-bar", "renders", "Status display"),
        ("comp-tui-app", "comp-clarify-widget", "renders", "Clarification forms"),
        ("comp-tui-app", "comp-subagent-card", "renders", "Subagent display"),
        ("comp-tui-app", "comp-ui-protocol", "uses", "Sends user actions"),
        # Tool dispatch
        ("comp-tool-executor", "comp-file-ops", "dispatches", "File operations"),
        ("comp-tool-executor", "comp-search-tools", "dispatches", "Search operations"),
        ("comp-tool-executor", "comp-web-tools", "dispatches", "Web operations"),
        ("comp-tool-executor", "comp-lsp-tools", "dispatches", "Code intelligence"),
        ("comp-tool-executor", "comp-delegation", "dispatches", "Subagent delegation"),
        # Subagent
        ("comp-delegation", "comp-subagent", "spawns", "Creates isolated agent"),
        ("comp-subagent", "comp-subagent-mgr", "uses", "Gets configuration"),
        # Director
        ("comp-director-adapter", "comp-coding-agent", "controls", "Phase-based gating"),
        ("comp-director-adapter", "comp-tool-gating", "configures", "Director gate"),
        # Server
        ("comp-stdio-server", "comp-coding-agent", "drives", "Routes user messages"),
        ("comp-stdio-server", "comp-message-store", "reads", "Store notifications"),
        ("comp-stdio-server", "comp-ui-protocol", "bridges", "VS Code <-> agent"),
        # Code Intelligence
        ("comp-lsp-tools", "comp-lsp-client", "uses", "LSP requests"),
        # LLM
        ("comp-failure-handler", "comp-openai-backend", "wraps", "Retry logic"),
        ("comp-failure-handler", "comp-anthropic-backend", "wraps", "Retry logic"),
        # Hooks
        ("comp-coding-agent", "comp-hook-mgr", "calls", "Pre/post tool hooks"),
        # MCP
        ("comp-tool-executor", "comp-mcp-mgr", "uses", "Dynamic MCP tools"),
    ]

    for from_id, to_id, etype, label in comp_edges:
        store.add_edge(from_id, to_id, etype, label=label)

    # ======================================================================
    # CROSS-CUTTING: Design Decisions
    # ======================================================================

    decisions = [
        (
            "dec-single-writer",
            "decision",
            "Single Writer Pattern",
            "Only MemoryManager writes to MessageStore. StoreAdapter is READ-ONLY. Prevents race conditions in persistence.",
            {
                "affects": ["comp-memory-mgr", "comp-store-adapter", "comp-message-store"],
                "rationale": "Prevents race conditions in multi-consumer persistence",
            },
        ),
        (
            "dec-async-only",
            "decision",
            "Async-Only Execution",
            "All agent logic flows through stream_response() async generator. No sync paths. Removed CLI sync mode in v3.0.",
            {
                "affects": ["comp-coding-agent", "comp-tui-app"],
                "rationale": "Single code path, simpler to maintain and test",
            },
        ),
        (
            "dec-canonical-delta",
            "decision",
            "Canonical ProviderDelta Contract",
            "All LLM providers emit ProviderDelta. StreamingPipeline is the ONLY structural parser. No other component parses raw LLM output.",
            {
                "affects": [
                    "comp-streaming-pipeline",
                    "comp-openai-backend",
                    "comp-anthropic-backend",
                ],
                "rationale": "Single parsing point eliminates duplicate logic across providers",
            },
        ),
        (
            "dec-jsonl-ledger",
            "decision",
            "JSONL Ledger + In-Memory Projection",
            "JSONL file is immutable ledger. MessageStore is in-memory projection with stream_id collapse. Hydrator replays on resume.",
            {
                "affects": ["comp-session-writer", "comp-message-store", "comp-hydrator"],
                "rationale": "Append-only is crash-safe; in-memory gives fast queries",
            },
        ),
        (
            "dec-tool-gating",
            "decision",
            "4-Check Tool Gating Pipeline",
            "Every tool call passes through repeat/plan/director/approval checks before execution.",
            {
                "affects": ["comp-tool-gating", "comp-coding-agent", "comp-permission-mgr"],
                "rationale": "Defense in depth: multiple independent safety checks",
            },
        ),
        (
            "dec-structlog",
            "decision",
            "structlog for Observability",
            "All logging via get_logger() factory. JSONL output only, no console. Context vars for request tracing.",
            {
                "affects": ["comp-logging"],
                "rationale": "Structured logs enable automated analysis; no console avoids TUI corruption",
            },
        ),
        (
            "dec-no-emojis",
            "decision",
            "No Emojis in Python Code",
            "Windows console cp1252 encoding crashes on emoji characters. All Python output must use ASCII-safe markers.",
            {
                "affects": ["all"],
                "rationale": "Windows cp1252 encoding crashes on emoji codepoints",
            },
        ),
        (
            "dec-stdin-devnull",
            "decision",
            "subprocess.run stdin=DEVNULL",
            "Every subprocess.run() call must use stdin=DEVNULL. Background stdin reader thread + child inheriting stdin = Windows deadlock.",
            {
                "affects": ["comp-tool-executor", "comp-file-ops"],
                "rationale": "Prevents Windows handle deadlock in stdio mode",
            },
        ),
    ]

    for did, dtype, name, desc, props in decisions:
        store.add_node(
            id=did,
            type="decision",
            layer=0,
            name=name,
            description=desc,
            properties=props,
        )

    # Decision constraint edges
    for did, _, _, _, props in decisions:
        for comp_id in props.get("affects", []):
            if comp_id != "all":
                store.add_edge(did, comp_id, "constrains", label="design decision")

    # ======================================================================
    # CROSS-CUTTING: Invariants
    # ======================================================================

    invariants = [
        (
            "inv-tool-order",
            "invariant",
            "Tool Results Must Match Call Order",
            "Tool results must appear in same order as tool calls in the requesting message, or the LLM API rejects them.",
            {"severity": "critical", "affects": ["comp-coding-agent"]},
        ),
        (
            "inv-orphan-detection",
            "invariant",
            "No Orphaned Tool Results",
            "A tool_result with no matching tool_call in context causes LLM API rejection. Agent has _fix_orphaned_tool_calls().",
            {"severity": "critical", "affects": ["comp-coding-agent"]},
        ),
        (
            "inv-interrupt-clear",
            "invariant",
            "Clear Interrupt After Continue",
            "_interrupted flag must be cleared after Continue on a pause prompt via clear_interrupt(). Forgetting causes infinite pause loop.",
            {"severity": "high", "affects": ["comp-ui-protocol", "comp-coding-agent"]},
        ),
        (
            "inv-agent-subagent-parity",
            "invariant",
            "Agent/Subagent Metadata Parity",
            "Both agent.py and subagent.py must use build_tool_metadata() from tool_metadata.py. VS Code expects identical keys.",
            {"severity": "high", "affects": ["comp-coding-agent", "comp-subagent"]},
        ),
        (
            "inv-finalize-before-complete",
            "invariant",
            "Finalize Before Complete",
            "Assistant messages start as streaming placeholders. Must call finalize_message() before marking complete.",
            {"severity": "medium", "affects": ["comp-tui-app", "comp-message-store"]},
        ),
    ]

    for iid, itype, name, desc, props in invariants:
        store.add_node(
            id=iid,
            type="invariant",
            layer=0,
            name=name,
            description=desc,
            properties=props,
        )
        for comp_id in props.get("affects", []):
            store.add_edge(iid, comp_id, "constrains", label="invariant")

    # ======================================================================
    # CROSS-CUTTING: Execution Flows
    # ======================================================================

    flows = [
        (
            "flow-user-msg",
            "flow",
            "User Message Flow",
            "User input -> TUI -> CodingAgent.stream_response() -> LLM -> Tool loop -> UIEvents -> TUI render",
            {
                "trigger": "User presses Enter in ChatInput",
                "steps": [
                    "ChatInput -> InputSubmittedMessage",
                    "CodingAgentApp._stream_response()",
                    "CodingAgent.stream_response() [async generator]",
                    "ContextBuilder.build_context()",
                    "LLMBackend.stream() -> ProviderDelta",
                    "StreamingPipeline.process_delta() -> Segments",
                    "ToolGatingService.evaluate() -> gate decision",
                    "ToolExecutor.execute_tool() -> ToolResult",
                    "yield UIEvents (TextDelta, ToolCallStatus, etc.)",
                    "CodingAgentApp._handle_event() -> widget updates",
                    "MemoryManager.add_message() -> MessageStore",
                ],
                "complexity": "high",
            },
        ),
        (
            "flow-tool-exec",
            "flow",
            "Tool Execution Flow",
            "Tool call from LLM -> gating -> approval -> execution -> result back to LLM",
            {
                "trigger": "LLM response contains tool_calls",
                "steps": [
                    "Parse tool_calls from LLM response",
                    "ToolGatingService.evaluate() (4 checks)",
                    "UIProtocol.wait_for_approval() if needed",
                    "ToolExecutor.execute_tool()",
                    "update_tool_state() -> MessageStore notification",
                    "Tool result appended to messages",
                    "Next LLM call with tool results",
                ],
                "complexity": "medium",
            },
        ),
        (
            "flow-session-resume",
            "flow",
            "Session Resume Flow",
            "Load JSONL -> Hydrate MessageStore -> Replay UI -> Ready for input",
            {
                "trigger": "User selects existing session or app starts with session_id",
                "steps": [
                    "SessionManager.resume_session(session_id)",
                    "SessionHydrator.hydrate(jsonl_path)",
                    "Parse JSONL lines -> Message objects",
                    "MessageStore.add_message() for each",
                    "CodingAgentApp.replay_session()",
                    "Render messages in TUI",
                ],
                "complexity": "low",
            },
        ),
        (
            "flow-vscode-comm",
            "flow",
            "VS Code Communication Flow",
            "VS Code sidebar -> stdio -> StdioServer -> CodingAgent -> events -> TCP -> sidebar",
            {
                "trigger": "User sends message in VS Code sidebar",
                "steps": [
                    "Sidebar posts chat_message via stdin JSON",
                    "StdioServer reads stdin, dispatches to handler",
                    "CodingAgent.stream_response() starts",
                    "UIEvents serialized via serializers.py",
                    "Events sent over TCP data channel",
                    "Extension forwards to webview via postMessage",
                    "React components update",
                ],
                "complexity": "medium",
            },
        ),
        (
            "flow-subagent",
            "flow",
            "Subagent Delegation Flow",
            "Main agent -> delegate_to_subagent -> SubAgent process -> IPC results -> main agent",
            {
                "trigger": "Agent calls delegate_to_subagent tool",
                "steps": [
                    "DelegateToSubagent.execute()",
                    "SubAgentManager creates SubAgent config",
                    "Subprocess spawned with IPC channel",
                    "SubAgent.execute() in isolated process",
                    "Own MessageStore, own LLM backend",
                    "Results communicated via IPC",
                    "Main agent receives result, continues",
                ],
                "complexity": "medium",
            },
        ),
    ]

    for fid, ftype, name, desc, props in flows:
        store.add_node(
            id=fid,
            type="flow",
            layer=0,
            name=name,
            description=desc,
            properties=props,
        )

    print(
        f"[OK] Populated {len(components)} components, {len(modules)} modules, "
        f"{len(decisions)} decisions, {len(invariants)} invariants, {len(flows)} flows"
    )


# ---------------------------------------------------------------------------
# File Scanner: auto-populate layer 4 file nodes
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".rb", ".cs"}


def scan_files(store: ClaraityStore, root: str = "src", extensions: list[str] = None) -> dict:
    """Scan source files and add as layer 4 nodes. Language-agnostic.

    Returns a drift report:
    {
        "new": ["path1", "path2"],        # files on disk but not in DB
        "modified": ["path3"],            # files modified since last scan
        "deleted": ["path4"],             # files in DB but not on disk
        "unchanged": ["path5", ...],      # files unchanged since last scan
        "total_scanned": 228,
    }
    """
    import ast

    root_path = Path(root)
    if not root_path.exists():
        print(f"[WARN] Root path not found: {root}")
        return

    # Map directory prefixes to module node IDs
    MODULE_MAP = {
        "src/core/": "mod-core",
        "src/memory/": "mod-memory",
        "src/session/": "mod-session",
        "src/ui/": "mod-ui",
        "src/tools/": "mod-tools",
        "src/llm/": "mod-llm",
        "src/server/": "mod-server",
        "src/observability/": "mod-observability",
        "src/prompts/": "mod-prompts",
        "src/subagents/": "mod-subagents",
        "src/director/": "mod-director",
        "src/code_intelligence/": "mod-code-intel",
        "src/integrations/": "mod-integrations",
        "src/platform/": "mod-platform",
        "src/hooks/": "mod-hooks",
        "src/claraity/": "mod-claraity",
        "src/execution/": "mod-execution",
        "src/orchestration/": "mod-orchestration",
        "src/security/": "mod-security",
        "src/testing/": "mod-testing",
        "src/validation/": "mod-validation",
        "src/utils/": "mod-utils",
    }

    def get_module_id(file_path: str) -> Optional[str]:
        """Find which module a file belongs to."""
        fp = file_path.replace("\\", "/")
        for prefix, mod_id in MODULE_MAP.items():
            if fp.startswith(prefix):
                return mod_id
        return None

    def extract_description(file_path: Path) -> tuple[str, int]:
        """Extract first docstring or comment and line count. Language-agnostic."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            line_count = content.count("\n") + 1

            # Python: try AST for module docstring
            if file_path.suffix == ".py":
                try:
                    tree = ast.parse(content)
                    docstring = ast.get_docstring(tree)
                    if docstring:
                        first_line = docstring.strip().split("\n")[0].strip()
                        if len(first_line) > 120:
                            first_line = first_line[:117] + "..."
                        return first_line, line_count
                except SyntaxError:
                    pass

            # Universal: first comment line
            comment_prefixes = ["#", "//", "/*", "*", "///"]
            for line in content.split("\n")[:15]:
                stripped = line.strip()
                for prefix in comment_prefixes:
                    if stripped.startswith(prefix) and not stripped.startswith("#!"):
                        desc = stripped.lstrip("/#* ").strip()
                        if (
                            desc
                            and len(desc) > 5
                            and not desc.startswith("eslint")
                            and not desc.startswith("@")
                        ):
                            if len(desc) > 120:
                                desc = desc[:117] + "..."
                            return desc, line_count
                        break

            return "", line_count
        except Exception:
            return "", 0

    # Ensure all module nodes exist (some may not be in the main populate)
    existing_nodes = {n["id"] for n in store.get_all_nodes()}
    for prefix, mod_id in MODULE_MAP.items():
        if mod_id not in existing_nodes:
            label = prefix.replace("src/", "").rstrip("/")
            store.add_node(
                id=mod_id,
                type="module",
                layer=2,
                name=prefix,
                description="[needs description]",
                file_path=prefix,
                risk_level="low",
                properties={"flow_rank": 99, "flow_col": 0},
            )

    # Find source files matching extensions
    scan_exts = set(extensions) if extensions else DEFAULT_EXTENSIONS
    # Normalize: ensure dot prefix
    scan_exts = {e if e.startswith(".") else f".{e}" for e in scan_exts}

    skip_dirs = {
        "__pycache__",
        "node_modules",
        ".git",
        ".venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
    }

    # Build indexes from existing DB for drift detection and enrichment
    all_nodes = store.get_all_nodes()
    all_edges = store.get_all_edges()

    existing_file_nodes = {}
    for n in all_nodes:
        if n["type"] == "file" and n.get("file_path"):
            existing_file_nodes[n["file_path"]] = n

    # Index: file_path -> component node (components have file_path pointing to their source)
    file_to_component = {}
    for n in all_nodes:
        if n["type"] == "component" and n.get("file_path"):
            file_to_component[n["file_path"]] = n

    # Index: node_id -> list of connected edges (non-contains, non-constrains)
    node_edges = {}
    for e in all_edges:
        if e["type"] in ("contains", "constrains"):
            continue
        for nid in (e["from_id"], e["to_id"]):
            if nid not in node_edges:
                node_edges[nid] = []
            node_edges[nid].append(e)

    # Index: node_id -> list of constraining decisions/invariants
    node_constraints = {}
    for e in all_edges:
        if e["type"] == "constrains":
            tid = e["to_id"]
            if tid not in node_constraints:
                node_constraints[tid] = []
            # Find the decision/invariant node
            src_node = next((n for n in all_nodes if n["id"] == e["from_id"]), None)
            if src_node:
                node_constraints[tid].append(src_node)

    # Index: node_id -> node for name lookups
    node_map = {n["id"]: n for n in all_nodes}

    def enrich_file_entry(file_path: str, module_id: Optional[str]) -> dict:
        """Build enriched drift entry with component, edges, and constraints."""
        entry: dict = {"path": file_path, "module": module_id}

        comp = file_to_component.get(file_path)
        if comp:
            entry["component"] = {"id": comp["id"], "name": comp["name"]}
            # Connected edges for this component
            edges = node_edges.get(comp["id"], [])
            entry["edges"] = [
                {
                    "type": e["type"],
                    "from": node_map.get(e["from_id"], {}).get("name", e["from_id"]),
                    "to": node_map.get(e["to_id"], {}).get("name", e["to_id"]),
                    "label": e.get("label"),
                }
                for e in edges
            ]
            # Affected constraints
            constraints = node_constraints.get(comp["id"], [])
            entry["constraints"] = [{"name": c["name"], "type": c["type"]} for c in constraints]
        else:
            entry["component"] = None
            entry["edges"] = []
            entry["constraints"] = []

        return entry

    # Get last scan timestamp for mtime comparison
    metadata = store.get_metadata()
    scanned_at_str = metadata.get("scanned_at")
    scanned_at_ts = None
    if scanned_at_str:
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(scanned_at_str)
            scanned_at_ts = dt.timestamp()
        except (ValueError, TypeError):
            pass

    drift: dict = {"new": [], "modified": [], "deleted": [], "unchanged": 0, "total_scanned": 0}
    seen_paths = set()

    file_count = 0
    for src_file in sorted(root_path.rglob("*")):
        if not src_file.is_file():
            continue
        if src_file.suffix not in scan_exts:
            continue
        if any(skip in src_file.parts for skip in skip_dirs):
            continue

        # Skip files blocked by .claraityignore
        from src.tools.claraityignore import is_blocked

        if is_blocked(src_file)[0]:
            continue

        rel_path = str(src_file).replace("\\", "/")
        seen_paths.add(rel_path)
        file_name = src_file.name
        module_id = get_module_id(rel_path)

        # Drift detection: new vs modified vs unchanged
        existing = existing_file_nodes.get(rel_path)
        if existing is None:
            drift["new"].append(enrich_file_entry(rel_path, module_id))
        elif scanned_at_ts:
            try:
                file_mtime = src_file.stat().st_mtime
                if file_mtime > scanned_at_ts:
                    drift["modified"].append(enrich_file_entry(rel_path, module_id))
                else:
                    drift["unchanged"] += 1
            except OSError:
                drift["unchanged"] += 1
        else:
            drift["unchanged"] += 1

        description, line_count = extract_description(src_file)

        # Determine role from filename patterns
        role = "source"
        if file_name in ("__init__.py", "index.ts", "index.js", "mod.rs"):
            role = "package init"
        elif file_name in ("__main__.py", "main.go", "main.rs"):
            role = "entry point"
        elif (
            file_name.startswith("test_")
            or file_name.endswith("_test.go")
            or file_name.endswith(".test.ts")
            or file_name.endswith(".spec.ts")
        ):
            role = "test"

        file_id = store._make_id("file", rel_path)

        store.add_node(
            id=file_id,
            type="file",
            layer=4,
            name=file_name,
            description=description,
            file_path=rel_path,
            line_count=line_count,
            risk_level="low",
            properties={"role": role, "module": module_id or "none"},
        )

        # Link to parent module
        if module_id:
            store.add_edge(module_id, file_id, "contains")

        file_count += 1

    # Detect deleted files: in DB but not on disk
    for path, node in existing_file_nodes.items():
        if path not in seen_paths:
            mod_id = get_module_id(path)
            drift["deleted"].append(enrich_file_entry(path, mod_id))

    drift["total_scanned"] = file_count

    # Update scanned_at timestamp
    store.set_metadata("scanned_at", ClaraityStore._now())

    summary = (
        f"[OK] Scanned {file_count} files: "
        f"{len(drift['new'])} new, {len(drift['modified'])} modified, "
        f"{len(drift['deleted'])} deleted, {drift['unchanged']} unchanged"
    )
    print(summary)

    return drift


# ---------------------------------------------------------------------------
# Render: DB -> Markdown for LLM consumption
# ---------------------------------------------------------------------------


def _load_graph(store: ClaraityStore) -> dict:
    """Load and index all nodes/edges from the DB."""
    nodes = store.get_all_nodes()
    edges = store.get_all_edges()
    metadata = store.get_metadata()

    for n in nodes:
        if isinstance(n.get("properties"), str):
            n["properties"] = json.loads(n["properties"])

    node_map = {n["id"]: n for n in nodes}

    contains_edges = [e for e in edges if e["type"] == "contains"]
    mod_children = {}
    child_to_mod = {}
    for e in contains_edges:
        mod_children.setdefault(e["from_id"], []).append(e["to_id"])
        child_to_mod[e["to_id"]] = e["from_id"]

    dep_edges = [e for e in edges if e["type"] not in ("contains", "constrains")]

    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": metadata,
        "node_map": node_map,
        "mod_children": mod_children,
        "child_to_mod": child_to_mod,
        "dep_edges": dep_edges,
    }


def render_compact_briefing(store: ClaraityStore) -> str:
    """Compact overview for system prompt injection (~1500 tokens).
    Covers: modules, cross-module deps, decisions, invariants."""
    g = _load_graph(store)
    node_map, mod_children = g["node_map"], g["mod_children"]

    modules = [
        n for n in g["nodes"] if n["type"] == "module" and n["properties"].get("flow_rank", 99) < 99
    ]
    modules.sort(
        key=lambda m: (m["properties"].get("flow_rank", 99), m["properties"].get("flow_col", 99))
    )
    decisions = [n for n in g["nodes"] if n["type"] == "decision"]
    invariants = [n for n in g["nodes"] if n["type"] == "invariant"]

    repo = g["metadata"].get("repo_name", "unknown")
    lang = g["metadata"].get("repo_language", "unknown")
    total_lines = g["metadata"].get("total_lines", "?")
    total_files = g["metadata"].get("total_files", "?")

    lines = []
    lines.append(f"# Codebase: {repo} ({lang}, {total_files} files, {total_lines} lines)")
    lines.append("")

    # Modules table
    lines.append("## Modules")
    lines.append("")
    lines.append("| Module | Purpose | Components | Risk |")
    lines.append("|--------|---------|------------|------|")
    for m in modules:
        child_ids = [
            cid
            for cid in mod_children.get(m["id"], [])
            if node_map.get(cid, {}).get("type") == "component"
        ]
        label = m["name"].replace("src/", "").rstrip("/")
        desc = m["description"][:60] + ("..." if len(m["description"]) > 60 else "")
        lines.append(f"| {label} | {desc} | {len(child_ids)} | {m['risk_level']} |")
    lines.append("")

    # Cross-module dependencies
    mod_dep_edges = [
        e
        for e in g["dep_edges"]
        if e["from_id"].startswith("mod-") and e["to_id"].startswith("mod-")
    ]
    if mod_dep_edges:
        lines.append("## Key Dependencies")
        lines.append("")
        for e in mod_dep_edges:
            fl = node_map.get(e["from_id"], {}).get("name", "").replace("src/", "").rstrip("/")
            tl = node_map.get(e["to_id"], {}).get("name", "").replace("src/", "").rstrip("/")
            lbl = f" ({e['label']})" if e.get("label") else ""
            lines.append(f"- {fl} --> {tl}{lbl}")
        lines.append("")

    # Decisions
    if decisions:
        lines.append("## Decisions (must follow)")
        lines.append("")
        for d in decisions:
            lines.append(f"- **{d['name']}**: {d['description']}")
        lines.append("")

    # Invariants
    if invariants:
        lines.append("## Invariants (must not break)")
        lines.append("")
        for inv in invariants:
            sev = inv["properties"].get("severity", "medium")
            lines.append(f"- **[{sev.upper()}]** {inv['name']}: {inv['description']}")
        lines.append("")

    return "\n".join(lines)


def render_module_detail(store: ClaraityStore, module_id: str) -> str:
    """Detailed view of a single module: components + files + relationships."""
    g = _load_graph(store)
    node_map, mod_children = g["node_map"], g["mod_children"]

    mod = node_map.get(module_id)
    if not mod:
        return f"Module '{module_id}' not found."

    child_ids = mod_children.get(module_id, [])
    components = [
        node_map[cid] for cid in child_ids if node_map.get(cid, {}).get("type") == "component"
    ]
    files = [node_map[cid] for cid in child_ids if node_map.get(cid, {}).get("type") == "file"]
    label = mod["name"].replace("src/", "").rstrip("/")

    lines = []
    lines.append(f"# Module: {label}")
    lines.append(f"> {mod['description']}")
    lines.append(
        f"> Risk: {mod['risk_level']} | Files: {len(files)} | Components: {len(components)}"
    )
    lines.append("")

    # Components
    if components:
        lines.append("## Components")
        lines.append("")
        for c in components:
            lc = f" ({c['line_count']} lines)" if c.get("line_count") else ""
            lines.append(f"### {c['name']}{lc}")
            lines.append(f"- **File**: {c.get('file_path', '')}")
            lines.append(f"- **Risk**: {c['risk_level']}")
            lines.append(f"- **Purpose**: {c['description']}")

            # Outgoing edges
            out = [e for e in g["dep_edges"] if e["from_id"] == c["id"]]
            if out:
                lines.append(
                    f"- **Depends on**: {', '.join(node_map.get(e['to_id'], {}).get('name', e['to_id']) for e in out)}"
                )

            # Incoming edges
            inc = [e for e in g["dep_edges"] if e["to_id"] == c["id"]]
            if inc:
                lines.append(
                    f"- **Used by**: {', '.join(node_map.get(e['from_id'], {}).get('name', e['from_id']) for e in inc)}"
                )

            # Properties
            props = c.get("properties", {})
            for k, v in props.items():
                if k in ("flow_rank", "flow_col"):
                    continue
                if isinstance(v, list):
                    lines.append(f"- **{k}**: {', '.join(str(x) for x in v)}")
                elif v:
                    lines.append(f"- **{k}**: {v}")
            lines.append("")

    # Files
    if files:
        lines.append("## Files")
        lines.append("")
        lines.append("| File | Lines | Role | Description |")
        lines.append("|------|-------|------|-------------|")
        for f in sorted(files, key=lambda x: x.get("file_path", "")):
            desc = (f.get("description") or "")[:50]
            if len(f.get("description") or "") > 50:
                desc += "..."
            role = f.get("properties", {}).get("role", "")
            lines.append(
                f"| {f.get('file_path', '')} | {f.get('line_count', '')} | {role} | {desc} |"
            )
        lines.append("")

    return "\n".join(lines)


def render_file_detail(store: ClaraityStore, file_path: str) -> str:
    """Detail view of a single file: role, parent module/component, related decisions."""
    g = _load_graph(store)
    node_map, child_to_mod = g["node_map"], g["child_to_mod"]

    # Find file node by path
    file_node = None
    for n in g["nodes"]:
        if n["type"] == "file" and n.get("file_path") == file_path:
            file_node = n
            break

    if not file_node:
        return f"File '{file_path}' not found in knowledge DB."

    # Find parent module
    parent_mod_id = child_to_mod.get(file_node["id"])
    parent_mod = node_map.get(parent_mod_id) if parent_mod_id else None

    # Find component that this file defines (match by file_path)
    component = None
    for n in g["nodes"]:
        if n["type"] == "component" and n.get("file_path") == file_path:
            component = n
            break

    lines = []
    lines.append(f"# File: {file_path}")
    lines.append(f"- **Name**: {file_node['name']}")
    lines.append(f"- **Lines**: {file_node.get('line_count', '?')}")
    lines.append(f"- **Role**: {file_node.get('properties', {}).get('role', 'source')}")
    if file_node.get("description"):
        lines.append(f"- **Description**: {file_node['description']}")
    if parent_mod:
        lines.append(f"- **Module**: {parent_mod['name'].replace('src/', '').rstrip('/')}")
    lines.append("")

    if component:
        lines.append(f"## Defines Component: {component['name']}")
        lines.append(f"> {component.get('description', '')}")
        lines.append(f"- Risk: {component['risk_level']}")
        lines.append("")

        out = [e for e in g["dep_edges"] if e["from_id"] == component["id"]]
        if out:
            lines.append("### Depends On")
            for e in out:
                t = node_map.get(e["to_id"])
                lbl = f" - {e['label']}" if e.get("label") else ""
                lines.append(f"- {t['name'] if t else e['to_id']} ({e['type']}){lbl}")
            lines.append("")

        inc = [e for e in g["dep_edges"] if e["to_id"] == component["id"]]
        if inc:
            lines.append("### Used By")
            for e in inc:
                s = node_map.get(e["from_id"])
                lines.append(f"- {s['name'] if s else e['from_id']} ({e['type']})")
            lines.append("")

        # Related decisions
        constraints = [
            e for e in g["edges"] if e["type"] == "constrains" and e["to_id"] == component["id"]
        ]
        if constraints:
            lines.append("### Applicable Decisions/Invariants")
            for e in constraints:
                dec = node_map.get(e["from_id"])
                if dec:
                    lines.append(f"- **{dec['name']}**: {dec['description']}")
            lines.append("")

    return "\n".join(lines)


def render_search(store: ClaraityStore, keyword: str, node_type: str = None) -> str:
    """Full-text search across all knowledge content using FTS5.

    Supports boolean queries (AND/OR/NOT), prefix (stream*), phrases ("message store").
    Falls back to simple substring search if FTS5 query fails (e.g., special characters).
    """
    try:
        matches = store.search_fts(keyword, node_type=node_type, limit=20)
    except Exception:
        # FTS5 query syntax error — fall back to simple LIKE search
        matches = _fallback_search(store, keyword, node_type)

    if not matches:
        filter_note = f" (type={node_type})" if node_type else ""
        return f"No results for '{keyword}'{filter_note}."

    type_label = f" type={node_type}" if node_type else ""
    lines = [f'## Search: "{keyword}"{type_label} ({len(matches)} matches)', ""]

    for m in matches:
        lines.append(f"### {m['name']} ({m['node_type']})")
        lines.append(f"- **ID**: {m['node_id']}")
        if m.get("snippet"):
            lines.append(f"- **Match**: {m['snippet']}")
        lines.append("")

    return "\n".join(lines)


def _fallback_search(
    store: ClaraityStore, keyword: str, node_type: str = None
) -> list[dict]:
    """Simple LIKE-based search when FTS5 query syntax is invalid."""
    all_nodes = store.get_all_nodes()
    kw = keyword.lower()
    results = []
    for n in all_nodes:
        if node_type and n["type"] != node_type:
            continue
        if n["type"] == "file" and store.parse_properties(n).get("role") == "package init":
            continue
        name_match = kw in (n.get("name") or "").lower()
        desc_match = kw in (n.get("description") or "").lower()
        if name_match or desc_match:
            results.append({
                "node_id": n["id"],
                "node_type": n["type"],
                "name": n["name"],
                "snippet": (n.get("description") or "")[:200],
                "rank": 0,
            })
    return results[:20]


def render_impact(store: ClaraityStore, component_id: str) -> str:
    """Show what would be affected by changes to a component."""
    g = _load_graph(store)
    node_map = g["node_map"]

    comp = node_map.get(component_id)
    if not comp:
        return f"Component '{component_id}' not found."

    # BFS: follow incoming edges (who depends on this component)
    from collections import deque

    visited = set()
    queue = deque([(component_id, 0)])  # (node_id, depth)
    impact_chain = []  # (node, depth, edge_type)

    while queue:
        current, current_depth = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        dependents = [e for e in g["dep_edges"] if e["to_id"] == current]
        for e in dependents:
            from_node = node_map.get(e["from_id"])
            if from_node and e["from_id"] not in visited:
                impact_chain.append((from_node, current_depth + 1, e["type"]))
                queue.append((e["from_id"], current_depth + 1))

    lines = []
    lines.append(f"## Impact Analysis: {comp['name']}")
    lines.append(f"> Changing this component may affect {len(impact_chain)} other components.")
    lines.append("")

    if not impact_chain:
        lines.append("No dependents found. This component can be modified safely.")
        return "\n".join(lines)

    # Group by type
    direct = [(n, t) for n, d, t in impact_chain if d == 1]
    indirect = [(n, t) for n, d, t in impact_chain if d > 1]

    if direct:
        lines.append(f"### Direct dependents ({len(direct)})")
        for n, t in direct:
            risk = f" [{n['risk_level'].upper()}]" if n.get("risk_level") == "high" else ""
            lines.append(f"- **{n['name']}** ({t}){risk} - {n.get('file_path', '')}")
        lines.append("")

    if indirect:
        lines.append(f"### Indirect dependents ({len(indirect)})")
        for n, t in indirect:
            lines.append(f"- {n['name']} ({t}) - {n.get('file_path', '')}")
        lines.append("")

    return "\n".join(lines)


# Keep backwards compat
render_briefing = render_compact_briefing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("""Usage: python -m src.claraity.claraity_db <command> [args]

Commands:
  populate          Populate DB with architecture knowledge
  scan              Scan Python files and add as layer 4 nodes
  export            Export graph.json for visualization
  export-jsonl      Export DB to JSONL for git tracking
  import-jsonl      Rebuild DB from JSONL file
  all               populate + scan + export
  brief             Compact architecture overview (for system prompt)
  module <id>       Module detail (e.g., mod-core, mod-memory)
  file <path>       File detail (e.g., src/core/agent.py)
  search <keyword>  Search knowledge base
  impact <id>       Impact analysis (e.g., comp-message-store)""")
        sys.exit(1)

    cmd = sys.argv[1]
    store = ClaraityStore()

    try:
        if cmd in ("populate", "all"):
            populate(store)
            stats = store.get_stats()
            print(f"[OK] DB: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
            print(f"     Node types: {stats['node_types']}")
            print(f"     Edge types: {stats['edge_types']}")

        if cmd in ("scan", "all"):
            scan_files(store)
            stats = store.get_stats()
            print(f"[OK] DB after scan: {stats['total_nodes']} nodes, {stats['total_edges']} edges")

        if cmd in ("export", "all"):
            graph = store.export_graph_json()
            print(
                f"[OK] Exported graph.json: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges"
            )

        if cmd in ("export-jsonl", "all"):
            count = store.export_jsonl()
            print(f"[OK] Exported {count} records to .claraity/claraity_knowledge.jsonl")

        if cmd == "import-jsonl":
            jsonl_path = sys.argv[2] if len(sys.argv) > 2 else ".claraity/claraity_knowledge.jsonl"
            store.close()
            store = ClaraityStore.import_jsonl(jsonl_path)
            stats = store.get_stats()
            print(
                f"[OK] Rebuilt DB from JSONL: {stats['total_nodes']} nodes, {stats['total_edges']} edges"
            )

        if cmd == "brief":
            print(render_compact_briefing(store))

        elif cmd == "module":
            if len(sys.argv) < 3:
                print("Usage: module <module_id>  (e.g., mod-core)")
                sys.exit(1)
            print(render_module_detail(store, sys.argv[2]))

        elif cmd == "file":
            if len(sys.argv) < 3:
                print("Usage: file <path>  (e.g., src/core/agent.py)")
                sys.exit(1)
            print(render_file_detail(store, sys.argv[2]))

        elif cmd == "search":
            if len(sys.argv) < 3:
                print("Usage: search <keyword>")
                sys.exit(1)
            print(render_search(store, " ".join(sys.argv[2:])))

        elif cmd == "impact":
            if len(sys.argv) < 3:
                print("Usage: impact <component_id>  (e.g., comp-message-store)")
                sys.exit(1)
            print(render_impact(store, sys.argv[2]))

        elif cmd not in ("populate", "scan", "export", "export-jsonl", "import-jsonl", "all"):
            print(f"Unknown command: {cmd}")
            sys.exit(1)

    finally:
        store.close()


if __name__ == "__main__":
    main()
