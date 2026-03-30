"""
ClarAIty Knowledge & Task Tools

Agent-callable tools for querying the codebase knowledge DB
and managing tasks via the Beads task tracker.
"""

from typing import Any

from src.tools.base import Tool, ToolResult, ToolStatus
from src.tools.claraityignore import is_blocked


class KnowledgeScanFilesTool(Tool):
    """Auto-discover source files and add as layer 4 nodes."""

    def __init__(self):
        super().__init__(
            name="knowledge_scan_files",
            description=(
                "Auto-discover source files in the codebase and add them as layer 4 nodes "
                "in the knowledge DB. Extracts file descriptions from docstrings/comments. "
                "Language-agnostic: scans .py, .ts, .tsx, .js, .jsx, .go, .java, .rs files. "
                "Run this as the first step when building knowledge for a new repo."
            ),
        )

    def execute(self, root: str = "src", extensions: str = "", **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClaraityStore, scan_files

        try:
            with ClaraityStore() as store:
                ext_list = (
                    [e.strip() for e in extensions.split(",") if e.strip()] if extensions else None
                )
                drift = scan_files(store, root=root, extensions=ext_list)
                stats = store.get_stats()
                file_count = stats["node_types"].get("file", 0)

                lines = [f"[OK] Scanned {file_count} files from {root}/"]
                lines.append(f"Total nodes: {stats['total_nodes']}, edges: {stats['total_edges']}")
                lines.append("")
                lines.append("Drift report:")
                lines.append(f"  New files: {len(drift['new'])}")
                lines.append(f"  Modified since last scan: {len(drift['modified'])}")
                lines.append(f"  Deleted (in DB but not on disk): {len(drift['deleted'])}")
                lines.append(f"  Unchanged: {drift['unchanged']}")

                def _fmt_entry(entry, prefix):
                    """Format an enriched drift entry."""
                    out = [f"  {prefix} {entry['path']}"]
                    if entry.get("module"):
                        out[0] += f"  (module: {entry['module']})"
                    comp = entry.get("component")
                    if comp:
                        out.append(f"      Defines: {comp['name']} ({comp['id']})")
                        edges = entry.get("edges", [])
                        if edges:
                            out.append(f"      Edges ({len(edges)}):")
                            for e in edges[:5]:
                                lbl = f' "{e["label"]}"' if e.get("label") else ""
                                out.append(f"        {e['from']} --{e['type']}--> {e['to']}{lbl}")
                            if len(edges) > 5:
                                out.append(f"        ... and {len(edges) - 5} more")
                        constraints = entry.get("constraints", [])
                        if constraints:
                            names = ", ".join(c["name"] for c in constraints)
                            out.append(f"      Affected by: {names}")
                    return "\n".join(out)

                if drift["new"]:
                    lines.append("\nNew files:")
                    for entry in drift["new"][:15]:
                        lines.append(_fmt_entry(entry, "+"))
                    if len(drift["new"]) > 15:
                        lines.append(f"  ... and {len(drift['new']) - 15} more")
                if drift["modified"]:
                    lines.append("\nModified files:")
                    for entry in drift["modified"][:15]:
                        lines.append(_fmt_entry(entry, "~"))
                    if len(drift["modified"]) > 15:
                        lines.append(f"  ... and {len(drift['modified']) - 15} more")
                if drift["deleted"]:
                    lines.append("\nDeleted files (nodes to remove):")
                    for entry in drift["deleted"][:15]:
                        lines.append(_fmt_entry(entry, "-"))
                    if len(drift["deleted"]) > 15:
                        lines.append(f"  ... and {len(drift['deleted']) - 15} more")

                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="\n".join(lines),
                    metadata={**stats, "drift": drift},
                )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"File scan failed: {e}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Root directory to scan (default: 'src')",
                },
                "extensions": {
                    "type": "string",
                    "description": "Comma-separated file extensions to scan (default: .py,.ts,.tsx,.js,.jsx,.go,.java,.rs)",
                },
            },
            "required": [],
        }


class KnowledgeUpdateTool(Tool):
    """Execute multiple knowledge DB write operations in a single call."""

    def __init__(self):
        super().__init__(
            name="knowledge_update",
            description=(
                "Execute multiple knowledge DB write operations in one call. Accepts a JSON "
                "array of operations, each with an 'op' field: 'add_node', 'update_node', "
                "'add_edge', 'remove_node', 'remove_edge'. All operations run in a single "
                "DB transaction. Use this to batch-create nodes and edges efficiently "
                "instead of calling individual tools one at a time."
            ),
        )

    def execute(self, operations: str, summary: str = "", **kwargs: Any) -> ToolResult:
        import json
        from src.claraity.claraity_db import ClaraityStore

        try:
            ops = json.loads(operations)
            if not isinstance(ops, list):
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="'operations' must be a JSON array",
                )

            with ClaraityStore() as store:
                result = store.batch_operations(ops)

            lines = [f"[OK] Batch: {result['succeeded']} succeeded, {result['failed']} failed"]
            if result["errors"]:
                lines.append("Errors:")
                for err in result["errors"]:
                    lines.append(f"  {err}")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS if result["failed"] == 0 else ToolStatus.PARTIAL,
                output="\n".join(lines),
                metadata=result,
            )
        except json.JSONDecodeError as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Invalid JSON: {e}",
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Batch failed: {e}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "Human-readable summary of what this batch does "
                        "(e.g., 'Add mod-core module with 5 components and dependency edges'). "
                        "Shown in the UI tool card for quick understanding."
                    ),
                },
                "operations": {
                    "type": "string",
                    "description": (
                        'JSON array of operations. Each object must have an "op" field. '
                        "Supported ops and their fields:\n"
                        '- add_node: node_id, node_type, name, layer, description, file_path, line_count, risk_level, properties\n'
                        '- update_node: node_id, description, risk_level, line_count, properties\n'
                        '- add_edge: from_id, to_id, edge_type, label, weight\n'
                        '- remove_node: node_id\n'
                        '- remove_edge: from_id, to_id, edge_type\n'
                        "Example: "
                        '[{"op":"add_node","node_id":"comp-x","node_type":"component","name":"X","description":"..."},'
                        '{"op":"add_edge","from_id":"mod-a","to_id":"comp-x","edge_type":"contains"}]'
                    ),
                },
            },
            "required": ["summary", "operations"],
        }


class KnowledgeQueryTool(Tool):
    """Unified query tool for reading the knowledge DB.

    Consolidates: brief, module detail, file detail, search, impact, node detail.
    All parameters optional -- combine them for compound queries.
    """

    def __init__(self):
        super().__init__(
            name="knowledge_query",
            description=(
                "Query the codebase knowledge DB. All parameters optional -- combine them. "
                "Full-text search (search=), node detail (node_id=), module detail (module_id=), "
                "file context (file_path=), blast radius (impact=), architecture overview (show='brief'). "
                "Supports FTS5 syntax for search: boolean (AND/OR/NOT), prefix (stream*), "
                'phrases ("message store"). Use node_id with comma-separated IDs to get '
                "multiple nodes in one call."
            ),
        )

    def execute(
        self,
        search: str = None,
        node_id: str = None,
        node_type: str = None,
        module_id: str = None,
        file_path: str = None,
        impact: str = None,
        related_to: str = None,
        show: str = "detail",
        keyword: str = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Check .claraityignore for file_path queries
        if file_path:
            blocked, _pattern = is_blocked(file_path)
            if blocked:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Access denied: file is blocked by user policy",
                )

        from src.claraity.claraity_db import ClaraityStore

        try:
            with ClaraityStore() as store:
                md = store.query(
                    search=search,
                    node_id=node_id,
                    node_type=node_type,
                    module_id=module_id,
                    file_path=file_path,
                    impact=impact,
                    related_to=related_to,
                    show=show,
                    keyword=keyword,
                )
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=md,
                )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Query failed: {e}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": (
                        "Full-text search (FTS5). Supports: keywords ('streaming'), "
                        "boolean ('async AND NOT test'), prefix ('stream*'), "
                        'phrases (\'"message store"\'). Results ranked by relevance with snippets.'
                    ),
                },
                "node_id": {
                    "type": "string",
                    "description": (
                        "Get detail for specific node(s). Supports comma-separated IDs for "
                        "multi-node queries (e.g., 'comp-memory-manager, comp-message-store')"
                    ),
                },
                "node_type": {
                    "type": "string",
                    "description": (
                        "Filter by node type: 'module', 'component', 'system', 'decision', "
                        "'invariant', 'flow', 'file'. With search=, filters search results. "
                        "Alone, lists all nodes of that type."
                    ),
                },
                "module_id": {
                    "type": "string",
                    "description": "Module detail: components, files, dependencies (e.g., 'mod-core', 'mod-memory')",
                },
                "file_path": {
                    "type": "string",
                    "description": "File context: role, parent module, component, applicable decisions (e.g., 'src/core/agent.py')",
                },
                "impact": {
                    "type": "string",
                    "description": "Blast radius analysis for a component ID (e.g., 'comp-message-store')",
                },
                "related_to": {
                    "type": "string",
                    "description": "Show all edges involving this node ID. Combine with show='constraints' for decisions/invariants.",
                },
                "show": {
                    "type": "string",
                    "description": "Output mode: 'detail' (default), 'brief' (architecture overview), 'overview' (narrative), 'metadata', 'constraints', 'edges'",
                },
                "keyword": {
                    "type": "string",
                    "description": "Simple substring search (prefer 'search' for full-text with ranking)",
                },
            },
            "required": [],
        }


class KnowledgeSetMetadataTool(Tool):
    """Store metadata in the knowledge DB (overview, scan info, etc.)."""

    def __init__(self):
        super().__init__(
            name="knowledge_set_metadata",
            description=(
                "Store a key-value pair in the knowledge DB metadata. Use this to save "
                "the architecture overview narrative, scan info (scanned_by, repo_name), "
                "or any other metadata about the knowledge base."
            ),
        )

    def execute(self, key: str, value: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClaraityStore

        try:
            with ClaraityStore() as store:
                store.set_metadata(key, value)
            preview = value[:100] + "..." if len(value) > 100 else value
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"[OK] Set metadata: {key} = {preview}",
                metadata={"key": key},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to set metadata: {e}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Metadata key. Standard keys: "
                        "'architecture_overview' (1500-2000 char narrative of the system), "
                        "'repo_name' (project name), "
                        "'repo_language' (primary language), "
                        "'scanned_by' (model that performed the scan), "
                        "'total_files' (number of source files), "
                        "'total_lines' (approximate line count)"
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "Metadata value. For 'architecture_overview', write a narrative covering: what the system is, how it works (data flow), and key subsystems.",
                },
            },
            "required": ["key", "value"],
        }


class BeadReadyTool(Tool):
    """Get the next unblocked tasks ready to work on."""

    def __init__(self):
        super().__init__(
            name="task_list",
            description="Get tasks that are unblocked and ready to start, sorted by priority. Use to find what to work on next.",
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_beads import BeadStore, render_tasks_md

        store = BeadStore()
        try:
            md = render_tasks_md(store)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"source": "claraity_beads.db"},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query tasks: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class BeadCreateTool(Tool):
    """Create a new task in the task tracker."""

    def __init__(self):
        super().__init__(
            name="task_create",
            description="Create a new task with title, description, priority, and optional tags. Returns the generated task ID.",
        )

    def execute(
        self,
        title: str,
        description: str = "",
        priority: int = 5,
        parent_id: str = None,
        tags: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        from src.claraity.claraity_beads import BeadStore

        store = BeadStore()
        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            bid = store.add_bead(
                title=title,
                description=description,
                priority=priority,
                parent_id=parent_id,
                tags=tag_list,
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Created task: {bid} - {title}",
                metadata={"bead_id": bid},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to create task: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
                "priority": {
                    "type": "integer",
                    "description": "Priority (0=highest, 5=default)",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Parent task ID for subtasks (optional)",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (e.g., 'bug,urgent')",
                },
            },
            "required": ["title"],
        }


class BeadUpdateTool(Tool):
    """Update task status: start, close, or add notes."""

    def __init__(self):
        super().__init__(
            name="task_update",
            description="Update a task's status (start/close) or add a note. Use 'start' when beginning work, 'close' when done with a summary of what was accomplished.",
        )

    def execute(
        self,
        bead_id: str,
        action: str,
        summary: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        from src.claraity.claraity_beads import BeadStore

        store = BeadStore()
        try:
            if action == "start":
                store.update_status(bead_id, "in_progress")
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"Started: {bead_id}",
                    metadata={"bead_id": bead_id},
                )
            elif action == "close":
                store.update_status(bead_id, "closed", summary=summary or None)
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"Closed: {bead_id}",
                    metadata={"bead_id": bead_id},
                )
            elif action == "note":
                store.add_note(bead_id, summary)
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"Note added to: {bead_id}",
                    metadata={"bead_id": bead_id},
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Unknown action: {action}. Use 'start', 'close', or 'note'.",
                )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to update task: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bead_id": {"type": "string", "description": "Task ID (e.g., bd-a1b2)"},
                "action": {
                    "type": "string",
                    "enum": ["start", "close", "note"],
                    "description": "Action: 'start' (mark in_progress), 'close' (mark done), 'note' (add comment)",
                },
                "summary": {
                    "type": "string",
                    "description": "For 'close': what was accomplished. For 'note': the note content.",
                },
            },
            "required": ["bead_id", "action"],
        }


class BeadBlockTool(Tool):
    """Add a blocking dependency between two tasks."""

    def __init__(self):
        super().__init__(
            name="task_block",
            description="Add a blocking dependency: blocker_id must be completed before blocked_id can start.",
        )

    def execute(self, blocker_id: str, blocked_id: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_beads import BeadStore

        store = BeadStore()
        try:
            store.add_dependency(blocker_id, blocked_id, "blocks")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"{blocker_id} now blocks {blocked_id}",
                metadata={"blocker_id": blocker_id, "blocked_id": blocked_id},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to add dependency: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "blocker_id": {"type": "string", "description": "Task that must complete first"},
                "blocked_id": {
                    "type": "string",
                    "description": "Task that cannot start until blocker completes",
                },
            },
            "required": ["blocker_id", "blocked_id"],
        }


class KnowledgeAutoLayoutTool(Tool):
    """Auto-compute architecture diagram layout from dependency graph."""

    def __init__(self):
        super().__init__(
            name="knowledge_auto_layout",
            description=(
                "Compute flow_rank/flow_col layout positions for all modules based on "
                "their dependency graph. Uses topological sort so entry points appear at "
                "the top and infrastructure at the bottom. Call this after populating "
                "modules and edges to produce a readable architecture diagram."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClaraityStore

        try:
            with ClaraityStore() as store:
                result = store.auto_layout()
            lines = [f"[OK] Updated layout for {result['modules_updated']} nodes"]
            ranks = result.get("ranks", {})
            if ranks:
                lines.append("")
                lines.append("Layout (top to bottom):")
                for rank in sorted(ranks.keys()):
                    mods = ranks[rank]
                    names = ", ".join(mods)
                    lines.append(f"  Row {rank}: {names}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(lines),
                metadata=result,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Auto-layout failed: {e}",
            )

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class KnowledgeExportTool(Tool):
    """Export knowledge and beads DBs to JSONL for git tracking."""

    def __init__(self):
        super().__init__(
            name="knowledge_export",
            description=(
                "Export the knowledge DB and beads DB to JSONL files for git tracking. "
                "Call this after finishing modifications to the knowledge base "
                "(adding nodes, edges, or completing a scan). The JSONL files are "
                "the git-tracked source of truth."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClaraityStore
        from src.claraity.claraity_beads import BeadStore

        results = []
        try:
            with ClaraityStore() as store:
                count = store.export_jsonl()
                results.append(f"Knowledge: {count} records -> .claraity/claraity_knowledge.jsonl")
        except Exception as e:
            results.append(f"Knowledge export failed: {e}")

        try:
            with BeadStore() as store:
                count = store.export_jsonl()
                results.append(f"Beads: {count} records -> .claraity/claraity_beads.jsonl")
        except Exception as e:
            results.append(f"Beads export failed: {e}")

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output="\n".join(results),
        )

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}
