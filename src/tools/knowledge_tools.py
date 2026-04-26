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
                        "- add_node: node_id, node_type, name, layer, description, file_path, line_count, risk_level, properties\n"
                        "- update_node: node_id, description, risk_level, line_count, properties\n"
                        "- add_edge: from_id, to_id, edge_type, label, weight\n"
                        "- remove_node: node_id\n"
                        "- remove_edge: from_id, to_id, edge_type\n"
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
                        "phrases ('\"message store\"'). Results ranked by relevance with snippets."
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

    NUMERIC_KEYS = {"total_files", "total_lines"}

    def __init__(self):
        super().__init__(
            name="knowledge_set_metadata",
            description=(
                "Store one or more key-value pairs in the knowledge DB metadata. "
                "Pass a JSON object with all metadata to set in a single call. "
                "Note: total_files, total_lines, and repo_language are auto-computed "
                "by knowledge_scan_files -- you only need to set repo_name, "
                "architecture_overview, and optionally scanned_by."
            ),
        )

    def execute(self, metadata: str = "", **kwargs: Any) -> ToolResult:
        import json as _json

        from src.claraity.claraity_db import ClaraityStore

        try:
            pairs = _json.loads(metadata)
            if not isinstance(pairs, dict) or not pairs:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error='\'metadata\' must be a non-empty JSON object, e.g. {"repo_name": "MyProject", "architecture_overview": "..."}',
                )
        except (_json.JSONDecodeError, TypeError) as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Invalid JSON in 'metadata' parameter: {e}",
            )

        # Validate numeric keys
        for k, v in pairs.items():
            if k in self.NUMERIC_KEYS:
                try:
                    int(v)
                except (ValueError, TypeError):
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Metadata key '{k}' requires a plain integer, got: {repr(v)}",
                    )

        try:
            results = []
            with ClaraityStore() as store:
                for key, value in pairs.items():
                    store.set_metadata(key, str(value))
                    preview = str(value)[:80] + "..." if len(str(value)) > 80 else str(value)
                    results.append(f"  {key} = {preview}")

            output = f"[OK] Set {len(pairs)} metadata key(s):\n" + "\n".join(results)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"keys": list(pairs.keys())},
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
                "metadata": {
                    "type": "string",
                    "description": (
                        "JSON object of key-value pairs to store. Example: "
                        '{"repo_name": "MyProject", "architecture_overview": "A web app that..."}. '
                        "Standard keys: "
                        "'architecture_overview' (1500-2000 char narrative of the system), "
                        "'repo_name' (human-readable project name), "
                        "'scanned_by' (model that performed the scan). "
                        "Note: total_files, total_lines, and repo_language are auto-computed "
                        "by knowledge_scan_files -- do not set them manually."
                    ),
                },
            },
            "required": ["metadata"],
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


class BeadShowTool(Tool):
    """Get full detail for a specific task."""

    def __init__(self):
        super().__init__(
            name="task_show",
            description=(
                "Get full detail for a specific task: description, design, acceptance criteria, "
                "notes, dependencies, and metadata. Use when picking up a task to understand "
                "what needs to be done and where a previous session left off."
            ),
        )

    def execute(self, bead_id: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_beads import BeadStore, render_bead_detail

        store = BeadStore()
        try:
            md = render_bead_detail(store, bead_id)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"bead_id": bead_id},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to show task: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bead_id": {
                    "type": "string",
                    "description": "Task ID (e.g., bd-a1b2)",
                },
            },
            "required": ["bead_id"],
        }


class BeadCreateTool(Tool):
    """Create a new task in the task tracker."""

    def __init__(self):
        super().__init__(
            name="task_create",
            description=(
                "Create a new task with title, description, priority, type, and optional deps.\n\n"
                "Always provide a meaningful description with context about why this issue exists, "
                "what needs to be done, and how you discovered it. Use deps to link back to the "
                "task you were working on (e.g., 'discovered-from:bd-a1b2')."
            ),
        )

    def execute(
        self,
        title: str,
        description: str = "",
        priority: int = 5,
        parent_id: str = None,
        tags: str = "",
        issue_type: str = "task",
        external_ref: str = None,
        design: str = "",
        acceptance_criteria: str = "",
        estimated_minutes: int = None,
        deps: str = "",
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
                issue_type=issue_type,
                external_ref=external_ref,
                design=design,
                acceptance_criteria=acceptance_criteria,
                estimated_minutes=estimated_minutes,
            )
            # Parse and add dependencies: "discovered-from:bd-a1b2,blocks:bd-c3d4"
            dep_results = []
            if deps:
                for dep_spec in deps.split(","):
                    dep_spec = dep_spec.strip()
                    if not dep_spec:
                        continue
                    if ":" in dep_spec:
                        dep_type, dep_id = dep_spec.split(":", 1)
                        dep_type, dep_id = dep_type.strip(), dep_id.strip()
                    else:
                        dep_type, dep_id = "blocks", dep_spec.strip()
                    if not dep_id:
                        dep_results.append(f"[SKIP] Empty target in '{dep_spec}'")
                        continue
                    # "blocks:X" means new task blocks X -> X depends on new task
                    if dep_type == "blocks":
                        store.add_dependency(bid, dep_id, "blocks")
                        dep_results.append(f"{bid} blocks {dep_id}")
                    else:
                        # Other types: dep_id is the source, new task is the target
                        store.add_dependency(dep_id, bid, dep_type)
                        dep_results.append(f"{bid} {dep_type} {dep_id}")

            output = f"Created task: {bid} - {title}"
            if dep_results:
                output += "\nDeps: " + "; ".join(dep_results)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
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
                "description": {
                    "type": "string",
                    "description": "Why this issue exists, what needs to be done, how you discovered it",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority (0=highest, 5=default, 9=lowest)",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Parent task ID for subtasks",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (e.g., 'bug,urgent')",
                },
                "issue_type": {
                    "type": "string",
                    "enum": ["bug", "feature", "task", "epic", "chore", "decision"],
                    "description": "Issue type (default: task)",
                },
                "external_ref": {
                    "type": "string",
                    "description": "External reference (e.g., jira-CC-42, gh-123)",
                },
                "design": {
                    "type": "string",
                    "description": "Technical design notes or approach",
                },
                "acceptance_criteria": {
                    "type": "string",
                    "description": "Definition of done",
                },
                "estimated_minutes": {
                    "type": "integer",
                    "description": "Effort estimate in minutes",
                },
                "deps": {
                    "type": "string",
                    "description": (
                        "Comma-separated dependencies: 'type:id' or just 'id' (default: blocks). "
                        "Types: blocks, discovered-from, related, caused-by, tracks, validates. "
                        "Example: 'discovered-from:bd-a1b2,blocks:bd-c3d4'"
                    ),
                },
            },
            "required": ["title"],
        }


class BeadUpdateTool(Tool):
    """Update task status, lifecycle, or add notes."""

    def __init__(self):
        super().__init__(
            name="task_update",
            description=(
                "Update a task's lifecycle. Actions: start (begin work), close (done), "
                "note (add comment), defer (park), reopen (un-close/un-defer), "
                "claim (atomic ownership for parallel sessions)."
            ),
        )

    def execute(
        self,
        bead_id: str,
        action: str,
        summary: str = "",
        close_reason: str = "",
        defer_until: str = "",
        claimant: str = "",
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
                store.update_status(
                    bead_id,
                    "closed",
                    summary=summary or None,
                    close_reason=close_reason or None,
                )
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
            elif action == "defer":
                store.defer(bead_id, until=defer_until or None)
                msg = f"Deferred: {bead_id}"
                if defer_until:
                    msg += f" until {defer_until}"
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=msg,
                    metadata={"bead_id": bead_id},
                )
            elif action == "reopen":
                store.reopen(bead_id)
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"Reopened: {bead_id}",
                    metadata={"bead_id": bead_id},
                )
            elif action == "claim":
                claimant_id = claimant or "agent"
                ok = store.claim(bead_id, claimant_id)
                if ok:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.SUCCESS,
                        output=f"Claimed: {bead_id} by {claimant_id}",
                        metadata={"bead_id": bead_id},
                    )
                else:
                    bead = store.get_bead(bead_id)
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Already claimed by {bead['assignee']}",
                    )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Unknown action: {action}. Use start, close, note, defer, reopen, or claim.",
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
                    "enum": ["start", "close", "note", "defer", "reopen", "claim"],
                    "description": (
                        "start: begin work. close: mark done. note: add comment. "
                        "defer: park task. reopen: un-close or un-defer. "
                        "claim: atomic ownership (prevents parallel sessions from double-claiming)."
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": "For close: what was accomplished. For note: the content.",
                },
                "close_reason": {
                    "type": "string",
                    "description": "For close: why it was closed (e.g., 'resolved', 'wontfix', 'duplicate').",
                },
                "defer_until": {
                    "type": "string",
                    "description": "For defer: ISO8601 date when task should reappear in ready queue.",
                },
                "claimant": {
                    "type": "string",
                    "description": "For claim: identity of claimer (e.g., 'claraity:session-abc'). Default: 'agent'.",
                },
            },
            "required": ["bead_id", "action"],
        }


class BeadLinkTool(Tool):
    """Add a typed dependency between two tasks."""

    def __init__(self):
        super().__init__(
            name="task_link",
            description=(
                "Add a typed dependency between two tasks. Default: 'blocks' (from_id must "
                "complete before to_id can start). Use other types for non-blocking relationships: "
                "related, discovered-from, caused-by, tracks, validates, supersedes."
            ),
        )

    def execute(
        self,
        from_id: str,
        to_id: str,
        dep_type: str = "blocks",
        **kwargs: Any,
    ) -> ToolResult:
        from src.claraity.claraity_beads import BeadStore

        store = BeadStore()
        try:
            store.add_dependency(from_id, to_id, dep_type)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"{from_id} --({dep_type})--> {to_id}",
                metadata={"from_id": from_id, "to_id": to_id, "dep_type": dep_type},
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
                "from_id": {"type": "string", "description": "Source task ID"},
                "to_id": {"type": "string", "description": "Target task ID"},
                "dep_type": {
                    "type": "string",
                    "enum": [
                        "blocks",
                        "conditional-blocks",
                        "waits-for",
                        "related",
                        "discovered-from",
                        "caused-by",
                        "tracks",
                        "validates",
                        "supersedes",
                        "duplicates",
                    ],
                    "description": "Dependency type (default: blocks). Blocking types affect the ready queue.",
                },
            },
            "required": ["from_id", "to_id"],
        }


# Backward compatibility alias
BeadBlockTool = BeadLinkTool


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
        from src.claraity.claraity_beads import BeadStore
        from src.claraity.claraity_db import ClaraityStore

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
