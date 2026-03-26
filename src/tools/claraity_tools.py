"""
ClarAIty Knowledge & Task Tools

Agent-callable tools for querying the codebase knowledge DB
and managing tasks via the Beads task tracker.
"""

from typing import Any

from src.tools.base import Tool, ToolResult, ToolStatus
from src.tools.clarityignore import is_blocked


class ClaraityScanFilesTool(Tool):
    """Auto-discover source files and add as layer 4 nodes."""

    def __init__(self):
        super().__init__(
            name="claraity_scan_files",
            description=(
                "Auto-discover source files in the codebase and add them as layer 4 nodes "
                "in the knowledge DB. Extracts file descriptions from docstrings/comments. "
                "Language-agnostic: scans .py, .ts, .tsx, .js, .jsx, .go, .java, .rs files. "
                "Run this as the first step when building knowledge for a new repo."
            ),
        )

    def execute(self, root: str = "src", extensions: str = "", **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore, scan_files

        store = ClarityStore()
        try:
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
        finally:
            store.close()

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


class ClaraityAddNodeTool(Tool):
    """Add a node to the knowledge DB."""

    def __init__(self):
        super().__init__(
            name="claraity_add_node",
            description=(
                "Add a node to the codebase knowledge graph. Nodes represent architectural "
                "entities: systems (layer 1), modules (layer 2), components (layer 3), "
                "decisions, invariants, or flows (layer 0). Use this to build the agent's "
                "understanding of a codebase during scanning."
            ),
        )

    def execute(
        self,
        node_id: str,
        node_type: str,
        name: str,
        description: str = "",
        layer: int = 3,
        file_path: str = None,
        line_count: int = None,
        risk_level: str = "low",
        properties: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        import json
        from src.claraity.claraity_db import ClarityStore

        store = ClarityStore()
        try:
            props = json.loads(properties) if properties else {}
            store.add_node(
                id=node_id,
                type=node_type,
                layer=layer,
                name=name,
                description=description,
                file_path=file_path,
                line_count=line_count,
                risk_level=risk_level,
                properties=props,
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"[OK] Added {node_type} node: {node_id} ({name})",
                metadata={"node_id": node_id, "type": node_type},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to add node: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "Unique node ID. Convention: sys-<name>, mod-<name>, comp-<name>, dec-<name>, inv-<name>, flow-<name>",
                },
                "node_type": {
                    "type": "string",
                    "enum": ["system", "module", "component", "decision", "invariant", "flow"],
                    "description": "Node type",
                },
                "name": {"type": "string", "description": "Human-readable name"},
                "description": {"type": "string", "description": "What this entity does/is"},
                "layer": {
                    "type": "integer",
                    "description": "Zoom level: 0=cross-cutting, 1=system context, 2=modules, 3=components",
                },
                "file_path": {"type": "string", "description": "Source file path (for components)"},
                "line_count": {"type": "integer", "description": "Lines of code"},
                "risk_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Risk level for modifications",
                },
                "properties": {
                    "type": "string",
                    "description": 'JSON string of additional properties (e.g., \'{"key_methods": ["foo", "bar"]}\')',
                },
            },
            "required": ["node_id", "node_type", "name"],
        }


class ClaraityAddEdgeTool(Tool):
    """Add a relationship edge between two nodes."""

    def __init__(self):
        super().__init__(
            name="claraity_add_edge",
            description=(
                "Add a relationship edge between two nodes in the knowledge graph. "
                "Edge types: 'uses', 'calls', 'contains', 'writes', 'reads', 'emits', "
                "'constrains', 'dispatches', 'renders', 'spawns', 'controls', 'bridges'. "
                "Use 'contains' for module->component hierarchy."
            ),
        )

    def execute(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        label: str = None,
        **kwargs: Any,
    ) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore

        store = ClarityStore()
        try:
            eid = store.add_edge(from_id, to_id, edge_type, label=label)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"[OK] Added edge: {from_id} --{edge_type}--> {to_id}",
                metadata={"edge_id": eid, "from": from_id, "to": to_id, "type": edge_type},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to add edge: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "from_id": {"type": "string", "description": "Source node ID"},
                "to_id": {"type": "string", "description": "Target node ID"},
                "edge_type": {
                    "type": "string",
                    "description": "Relationship type (uses, calls, contains, writes, reads, emits, constrains, dispatches, renders, spawns, controls, bridges)",
                },
                "label": {
                    "type": "string",
                    "description": "Optional description of the relationship",
                },
            },
            "required": ["from_id", "to_id", "edge_type"],
        }


class ClaraityRemoveNodeTool(Tool):
    """Remove a node and its edges from the knowledge DB."""

    def __init__(self):
        super().__init__(
            name="claraity_remove_node",
            description="Remove a node and all its connected edges from the knowledge graph. Use for corrections when the scanned architecture is wrong.",
        )

    def execute(self, node_id: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore

        store = ClarityStore()
        try:
            node_deleted, edge_count = store.remove_node(node_id)

            if node_deleted:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"[OK] Removed node {node_id} and {edge_count} connected edges",
                    metadata={"node_id": node_id, "edges_removed": edge_count},
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Node '{node_id}' not found",
                )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to remove node: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "ID of the node to remove"},
            },
            "required": ["node_id"],
        }


class QueryKnowledgeBriefTool(Tool):
    """Get compact architecture overview of the codebase."""

    def __init__(self):
        super().__init__(
            name="claraity_brief",
            description="Get a compact architecture overview of the codebase: modules, dependencies, design decisions, and invariants. Use at session start or when you need to understand the overall structure.",
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore, render_compact_briefing

        store = ClarityStore()
        try:
            md = render_compact_briefing(store)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"source": "claraity_knowledge.db"},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query knowledge DB: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class QueryModuleTool(Tool):
    """Get detailed information about a specific module."""

    def __init__(self):
        super().__init__(
            name="claraity_module",
            description="Get detailed information about a module: its components, files, dependencies, and relationships. Use when you need to understand or modify a specific module.",
        )

    def execute(self, module_id: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore, render_module_detail

        store = ClarityStore()
        try:
            md = render_module_detail(store, module_id)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"module_id": module_id},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query module: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "module_id": {
                    "type": "string",
                    "description": "Module ID (e.g., mod-core, mod-memory, mod-ui, mod-tools, mod-llm, mod-server, mod-session, mod-subagents, mod-director, mod-observability, mod-hooks, mod-integrations, mod-code-intel, mod-prompts, mod-platform)",
                },
            },
            "required": ["module_id"],
        }


class QueryFileTool(Tool):
    """Get information about a specific file's role and context."""

    def __init__(self):
        super().__init__(
            name="claraity_file",
            description="Get a file's role, parent module, component it defines, dependencies, and applicable design decisions. Use BEFORE reading a file to understand its context.",
        )

    def execute(self, file_path: str, **kwargs: Any) -> ToolResult:
        # Check .clarityignore
        blocked, _pattern = is_blocked(file_path)
        if blocked:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Access denied: file is blocked by user policy",
            )

        from src.claraity.claraity_db import ClarityStore, render_file_detail

        store = ClarityStore()
        try:
            md = render_file_detail(store, file_path)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"file_path": file_path},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query file: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "File path relative to project root (e.g., src/core/agent.py)",
                },
            },
            "required": ["file_path"],
        }


class SearchKnowledgeTool(Tool):
    """Search the codebase knowledge base by keyword."""

    def __init__(self):
        super().__init__(
            name="claraity_search",
            description="Search the codebase knowledge base by keyword. Returns matching components, modules, files, decisions, and their relationships. Use when you need to find relevant code for a task.",
        )

    def execute(self, keyword: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore, render_search

        store = ClarityStore()
        try:
            md = render_search(store, keyword)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"keyword": keyword},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to search knowledge: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (e.g., 'memory', 'auth', 'streaming', 'retry')",
                },
            },
            "required": ["keyword"],
        }


class QueryImpactTool(Tool):
    """Analyze the impact of changing a component."""

    def __init__(self):
        super().__init__(
            name="claraity_impact",
            description="Show what would be affected by changing a component. Returns direct and indirect dependents (blast radius). Use BEFORE modifying a component to understand risk.",
        )

    def execute(self, component_id: str, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore, render_impact

        store = ClarityStore()
        try:
            md = render_impact(store, component_id)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=md,
                metadata={"component_id": component_id},
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query impact: {e}",
            )
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID (e.g., comp-coding-agent, comp-memory-mgr, comp-message-store, comp-tui-app)",
                },
            },
            "required": ["component_id"],
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


class ClaraityAutoLayoutTool(Tool):
    """Auto-compute architecture diagram layout from dependency graph."""

    def __init__(self):
        super().__init__(
            name="claraity_auto_layout",
            description=(
                "Compute flow_rank/flow_col layout positions for all modules based on "
                "their dependency graph. Uses topological sort so entry points appear at "
                "the top and infrastructure at the bottom. Call this after populating "
                "modules and edges to produce a readable architecture diagram."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore

        store = ClarityStore()
        try:
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
        finally:
            store.close()

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class ClaraityExportTool(Tool):
    """Export knowledge and beads DBs to JSONL for git tracking."""

    def __init__(self):
        super().__init__(
            name="claraity_export",
            description=(
                "Export the knowledge DB and beads DB to JSONL files for git tracking. "
                "Call this after finishing modifications to the knowledge base "
                "(adding nodes, edges, or completing a scan). The JSONL files are "
                "the git-tracked source of truth."
            ),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        from src.claraity.claraity_db import ClarityStore
        from src.claraity.claraity_beads import BeadStore

        results = []
        try:
            store = ClarityStore()
            try:
                count = store.export_jsonl()
                results.append(f"Knowledge: {count} records -> .clarity/claraity_knowledge.jsonl")
            finally:
                store.close()
        except Exception as e:
            results.append(f"Knowledge export failed: {e}")

        try:
            store = BeadStore()
            try:
                count = store.export_jsonl()
                results.append(f"Beads: {count} records -> .clarity/claraity_beads.jsonl")
            finally:
                store.close()
        except Exception as e:
            results.append(f"Beads export failed: {e}")

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output="\n".join(results),
        )

    def _get_parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}
