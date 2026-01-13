"""
ClarAIty Architecture Query Tools

Provides 6 agent-callable tools for querying structured architectural knowledge:
1. QueryComponentTool - Get detailed component information
2. QueryDependenciesTool - Get component relationships
3. QueryDecisionsTool - Get design decisions
4. QueryFlowsTool - Get execution flows
5. QueryArchitectureSummaryTool - Get architecture overview
6. SearchComponentsTool - Search components by keyword

These tools enable architecture-driven development by giving the agent
transparent access to project structure, design decisions, and dependencies.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from src.clarity.core.database.clarity_db import ClarityDB
from src.platform.windows import safe_encode_output
from .base import Tool, ToolResult, ToolStatus


# Component to Architecture Doc Section Mapping
# Maps component_id to (section_number, start_line, end_line)
COMPONENT_SECTIONS = {
    'SELF_TESTING_LAYER': ('3.1', 1238, 1579),
    'LONG_RUNNING_CONTROLLER': ('3.2', 1617, 1957),
    'CHECKPOINT_MANAGER': ('3.3', 1959, 2217),
    'ERROR_RECOVERY_SYSTEM': ('3.4', 2220, 2600),
    'META_REASONING_ENGINE': ('3.5', 2601, 3000),
    'SMART_CONTEXT_LOADER': ('3.6', 3001, 3400),
}

ARCHITECTURE_DOC_PATH = 'STATE_OF_THE_ART_AGENT_ARCHITECTURE.md'


def _get_db() -> ClarityDB:
    """Get ClarityDB instance with proper path"""
    db_path = Path('.clarity/ai-coding-agent.db')
    if not db_path.exists():
        return None
    return ClarityDB(str(db_path))


def _format_component_output(component: Dict[str, Any]) -> str:
    """Format component details for agent consumption"""
    if not component:
        return safe_encode_output("[FAIL] Component not found")

    output = []
    output.append(f"[COMPONENT] {component['id']}")
    output.append(f"Name: {component['name']}")
    output.append(f"Type: {component['type']}")
    output.append(f"Layer: {component['layer']}")
    output.append(f"Status: {component['status']}")

    if component.get('purpose'):
        output.append(f"\nPurpose:")
        output.append(f"  {component['purpose']}")

    if component.get('business_value'):
        output.append(f"\nBusiness Value:")
        output.append(f"  {component['business_value']}")

    if component.get('design_rationale'):
        output.append(f"\nDesign Rationale:")
        output.append(f"  {component['design_rationale']}")

    if component.get('responsibilities'):
        output.append(f"\nResponsibilities ({len(component['responsibilities'])}):")
        for i, resp in enumerate(component['responsibilities'], 1):
            output.append(f"  {i}. {resp}")

    return safe_encode_output("\n".join(output))


def _format_relationships_output(relationships: Dict[str, List[Dict[str, Any]]]) -> str:
    """Format relationships for agent consumption"""
    output = []

    outgoing = relationships.get('outgoing', [])
    incoming = relationships.get('incoming', [])

    if outgoing:
        output.append(f"[DEPENDENCIES] Outgoing ({len(outgoing)}):")
        for rel in outgoing:
            output.append(f"  -> {rel['target_name']} ({rel['relationship_type']})")
            if rel.get('description'):
                output.append(f"     {rel['description']}")
    else:
        output.append("[INFO] No outgoing dependencies")

    if incoming:
        output.append(f"\n[USED BY] Incoming ({len(incoming)}):")
        for rel in incoming:
            output.append(f"  <- {rel['source_name']} ({rel['relationship_type']})")
            if rel.get('description'):
                output.append(f"     {rel['description']}")
    else:
        output.append("\n[INFO] No incoming dependencies")

    return safe_encode_output("\n".join(output))


def _format_decisions_output(decisions: List[Dict[str, Any]]) -> str:
    """Format design decisions for agent consumption"""
    if not decisions:
        return safe_encode_output("[INFO] No design decisions found")

    output = []
    output.append(f"[DECISIONS] Found {len(decisions)} design decision(s)\n")

    for i, dec in enumerate(decisions, 1):
        output.append(f"[{i}] {dec['decision_type'].upper()}")
        output.append(f"Question: {dec['question']}")
        output.append(f"Solution: {dec['chosen_solution']}")

        if dec.get('rationale'):
            output.append(f"Rationale: {dec['rationale']}")

        if dec.get('alternatives_considered'):
            alts = dec['alternatives_considered']
            output.append(f"Alternatives Considered: {len(alts)}")
            for alt in alts[:3]:  # Show first 3
                output.append(f"  - {alt}")

        if dec.get('trade_offs'):
            output.append(f"Trade-offs: {dec['trade_offs']}")

        output.append(f"Decided by: {dec['decided_by']} (confidence: {dec['confidence']})")
        output.append("")  # Blank line between decisions

    return safe_encode_output("\n".join(output))


def _format_flows_output(flows: List[Dict[str, Any]]) -> str:
    """Format execution flows for agent consumption"""
    if not flows:
        return safe_encode_output("[INFO] No execution flows found")

    output = []
    output.append(f"[FLOWS] Found {len(flows)} execution flow(s)\n")

    for flow in flows:
        marker = "[PRIMARY]" if flow.get('is_primary') else "[SECONDARY]"
        output.append(f"{marker} {flow['id']}")
        output.append(f"Name: {flow['name']}")
        output.append(f"Type: {flow['flow_type']}")
        output.append(f"Trigger: {flow['trigger']}")
        output.append(f"Complexity: {flow['complexity']}")

        if flow.get('description'):
            output.append(f"Description: {flow['description']}")

        output.append("")

    return safe_encode_output("\n".join(output))


def _format_architecture_summary_output(summary: Dict[str, Any]) -> str:
    """Format architecture summary for agent consumption"""
    output = []
    output.append(f"[ARCHITECTURE SUMMARY]")
    output.append(f"Total Components: {summary['total_components']}\n")

    for layer_info in summary['layers']:
        output.append(f"[{layer_info['layer'].upper()}]")
        output.append(f"  Total: {layer_info['component_count']}")
        output.append(f"  Completed: {layer_info['completed_count']}")
        output.append(f"  In Progress: {layer_info['in_progress_count']}")
        output.append(f"  Planned: {layer_info['planned_count']}")

        # Calculate percentage
        total = layer_info['component_count']
        completed = layer_info['completed_count']
        if total > 0:
            pct = (completed / total) * 100
            output.append(f"  Progress: {pct:.1f}%")

        output.append("")

    return safe_encode_output("\n".join(output))


def _format_search_results_output(components: List[Dict[str, Any]]) -> str:
    """Format search results for agent consumption"""
    if not components:
        return safe_encode_output("[INFO] No components found matching search query")

    output = []
    output.append(f"[SEARCH RESULTS] Found {len(components)} component(s)\n")

    for comp in components:
        output.append(f"[{comp['status'].upper()}] {comp['id']}")
        output.append(f"  Name: {comp['name']}")
        output.append(f"  Layer: {comp['layer']}")
        output.append(f"  Type: {comp['type']}")

        if comp.get('purpose'):
            preview = comp['purpose'][:100] + "..." if len(comp['purpose']) > 100 else comp['purpose']
            output.append(f"  Purpose: {preview}")

        output.append("")

    return safe_encode_output("\n".join(output))


# =============================================================================
# TOOL CLASSES (Agent-callable tools)
# =============================================================================

class QueryComponentTool(Tool):
    """Tool for querying detailed component information."""

    def __init__(self):
        super().__init__(
            name="query_component",
            description="Query detailed information about a specific architectural component. Returns component details, design decisions, code artifacts, and relationships."
        )

    def execute(self, component_id: str, **kwargs: Any) -> ToolResult:
        """Query component details."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            component = db.get_component_details_full(component_id)

            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found in ClarityDB"
                )

            output = []
            output.append(_format_component_output(component))

            # Artifacts
            artifacts = component.get('artifacts', [])
            if artifacts:
                output.append(f"\n[ARTIFACTS] {len(artifacts)} code artifact(s):")
                for art in artifacts[:10]:
                    output.append(f"  - {art['type']}: {art['file_path']}")
                    if art.get('description'):
                        output.append(f"    {art['description'][:80]}...")
                if len(artifacts) > 10:
                    output.append(f"  ... and {len(artifacts) - 10} more artifacts")

            # Design Decisions
            decisions = component.get('decisions', [])
            if decisions:
                output.append(f"\n{_format_decisions_output(decisions)}")

            # Relationships
            relationships = component.get('relationships', {})
            if relationships:
                output.append(f"\n{_format_relationships_output(relationships)}")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output("\n".join(output)),
                metadata={"component_id": component_id}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query component: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to query (e.g., 'CODING_AGENT', 'OBSERVABILITY_LAYER', 'CLARITY_INTEGRATION')"
                }
            },
            "required": ["component_id"]
        }


class QueryDependenciesTool(Tool):
    """Tool for querying component dependencies and relationships."""

    def __init__(self):
        super().__init__(
            name="query_dependencies",
            description="Query component dependencies and relationships. Returns both incoming (who uses this component) and outgoing (what this component depends on) relationships."
        )

    def execute(self, component_id: str, **kwargs: Any) -> ToolResult:
        """Query component dependencies."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            component = db.get_component(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found in ClarityDB"
                )

            relationships = db.get_component_relationships(component_id)

            output = []
            output.append(f"[DEPENDENCIES] {component['name']} ({component_id})\n")
            output.append(_format_relationships_output(relationships))

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output("\n".join(output)),
                metadata={"component_id": component_id}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query dependencies: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to query relationships for"
                }
            },
            "required": ["component_id"]
        }


class QueryDecisionsTool(Tool):
    """Tool for querying design decisions."""

    def __init__(self):
        super().__init__(
            name="query_decisions",
            description="Query design decisions for a component or globally. Returns decisions with rationale, alternatives considered, and trade-offs."
        )

    def execute(self, component_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        """Query design decisions."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            if component_id:
                component = db.get_component(component_id)
                if not component:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Component '{component_id}' not found in ClarityDB"
                    )

                decisions = db.get_component_decisions(component_id)
                header = f"[DECISIONS] {component['name']} ({component_id})\n"
            else:
                decisions = db.get_all_decisions()
                header = "[DECISIONS] All Design Decisions\n"

            output = header + _format_decisions_output(decisions)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"component_id": component_id} if component_id else {}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query decisions: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to query decisions for. If not provided, returns all decisions."
                }
            },
            "required": []
        }


class QueryFlowsTool(Tool):
    """Tool for querying execution flows."""

    def __init__(self):
        super().__init__(
            name="query_flows",
            description="Query execution flows in the system. Returns flow details with steps, triggers, and component involvement."
        )

    def execute(self, flow_id: Optional[str] = None, **kwargs: Any) -> ToolResult:
        """Query execution flows."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            if flow_id:
                flow = db.get_flow_with_steps(flow_id)
                if not flow:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Flow '{flow_id}' not found in ClarityDB"
                    )

                flows = [flow]

                if flow.get('steps'):
                    output_parts = [_format_flows_output([flow])]
                    output_parts.append(f"[STEPS] {len(flow['steps'])} step(s):")
                    for step in flow['steps']:
                        output_parts.append(f"  {step['sequence']}. {step['title']} ({step['step_type']})")
                        if step.get('description'):
                            output_parts.append(f"     {step['description'][:80]}...")
                    output = "\n".join(output_parts)
                else:
                    output = _format_flows_output([flow])
            else:
                flows = db.get_all_flows()
                output = _format_flows_output(flows)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"flow_id": flow_id} if flow_id else {}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query flows: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "flow_id": {
                    "type": "string",
                    "description": "Flow ID to query. If not provided, returns all flows."
                }
            },
            "required": []
        }


class QueryArchitectureSummaryTool(Tool):
    """Tool for querying architecture summary."""

    def __init__(self):
        super().__init__(
            name="query_architecture_summary",
            description="Query architecture overview organized by layer. Returns component counts, status breakdown, and progress for each layer."
        )

    def execute(self, layer: Optional[str] = None, group_by: str = "layer", **kwargs: Any) -> ToolResult:
        """Query architecture summary."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            if group_by == "phase":
                # Get phase-based summary
                output = self._get_phase_summary(db)
            else:
                # Get layer-based summary (default)
                summary = db.get_architecture_summary()

                if layer:
                    summary['layers'] = [l for l in summary['layers'] if l['layer'] == layer]
                    if not summary['layers']:
                        return ToolResult(
                            tool_name=self.name,
                            status=ToolStatus.ERROR,
                            output=None,
                            error=f"Layer '{layer}' not found in ClarityDB"
                        )

                output = _format_architecture_summary_output(summary)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"layer": layer, "group_by": group_by} if layer else {"group_by": group_by}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to query architecture summary: {str(e)}"
            )
        finally:
            db.close()

    def _get_phase_summary(self, db) -> str:
        """Get phase-based summary."""
        result = db.conn.execute('''
            SELECT
                phase,
                phase_order,
                COUNT(*) as total,
                SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status='planned' THEN 1 ELSE 0 END) as planned
            FROM components
            WHERE phase IS NOT NULL
            GROUP BY phase, phase_order
            ORDER BY phase_order
        ''').fetchall()

        output = []
        output.append("[ARCHITECTURE SUMMARY - BY PHASE]")

        total_components = sum(r[2] for r in result)
        output.append(f"Total Components: {total_components}\n")

        for phase, order, total, completed, in_progress, planned in result:
            pct = (completed / total * 100) if total > 0 else 0
            status_marker = "[OK]" if completed == total else f"[{completed}/{total}]"

            output.append(f"{status_marker} {phase}")
            output.append(f"  Total: {total}")
            output.append(f"  Completed: {completed}")
            output.append(f"  In Progress: {in_progress}")
            output.append(f"  Planned: {planned}")
            output.append(f"  Progress: {pct:.1f}%")
            output.append("")

        return safe_encode_output("\n".join(output))

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "description": "Optional layer filter (core, execution, tools, llm, memory, rag, etc.)"
                },
                "group_by": {
                    "type": "string",
                    "description": "Group by 'layer' (default) or 'phase'",
                    "enum": ["layer", "phase"]
                }
            },
            "required": []
        }


class SearchComponentsTool(Tool):
    """Tool for searching components by keyword."""

    def __init__(self):
        super().__init__(
            name="search_components",
            description="Search components by keyword in name, purpose, or business value. Useful for discovering relevant components."
        )

    def execute(self, query: str, **kwargs: Any) -> ToolResult:
        """Search components."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            components = db.search_components(query)
            output = _format_search_results_output(components)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"query": query, "results_count": len(components)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to search components: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'testing', 'memory', 'error handling')"
                }
            },
            "required": ["query"]
        }


# =============================================================================
# MUTATION TOOLS (Status updates, artifact tracking, task management)
# =============================================================================

class GetNextTaskTool(Tool):
    """Tool for getting the next planned task with full context."""

    def __init__(self):
        super().__init__(
            name="get_next_task",
            description="Get the next planned component to work on with full context including dependencies, purpose, and suggested implementation details. Use at session start to know what to work on."
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Get next task."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Get all components and filter by status
            all_components = db.get_all_components()
            planned = [c for c in all_components if c['status'] == 'planned']

            if not planned:
                # Check if anything is in_progress
                in_progress = [c for c in all_components if c['status'] == 'in_progress']
                if in_progress:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.SUCCESS,
                        output=safe_encode_output(f"[INFO] No planned tasks. Currently in progress: {in_progress[0]['name']} ({in_progress[0]['id']})"),
                        metadata={"in_progress": in_progress[0]['id']}
                    )
                else:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.SUCCESS,
                        output=safe_encode_output("[INFO] No planned or in-progress tasks found. All components may be completed!"),
                        metadata={}
                    )

            # Sort planned components by phase_order, then phase_sequence, then ID
            # This prioritizes Phase 0 -> Phase 1 -> Phase 2 automatically
            # Within each phase, follows architecture doc timeline (sequence)
            planned_sorted = sorted(
                planned,
                key=lambda c: (c.get('phase_order', 999), c.get('phase_sequence', 999), c['id'])
            )

            # Find first component with all dependencies met
            next_task = None
            for component in planned_sorted:
                # Check if all dependencies are completed
                relationships = db.get_component_relationships(component['id'])
                outgoing = relationships.get('outgoing', [])

                if not outgoing:
                    # No dependencies, ready to start
                    next_task = component
                    break

                # Check all dependencies
                all_deps_met = all(
                    db.get_component(rel['target_id'])['status'] == 'completed'
                    for rel in outgoing
                )

                if all_deps_met:
                    next_task = component
                    break

            # Fallback: if no dependencies met, take first planned
            if not next_task:
                next_task = planned_sorted[0]

            # Get full details
            component = db.get_component_details_full(next_task['id'])

            output = []
            output.append("[NEXT TASK]")
            output.append(f"Component: {component['name']}")
            output.append(f"ID: {component['id']}")
            output.append(f"Layer: {component['layer']}")
            output.append(f"Status: {component['status']}\n")

            if component.get('purpose'):
                output.append(f"Purpose:")
                output.append(f"  {component['purpose']}\n")

            if component.get('business_value'):
                output.append(f"Business Value:")
                output.append(f"  {component['business_value']}\n")

            # Check dependencies
            relationships = component.get('relationships', {})
            outgoing = relationships.get('outgoing', [])
            if outgoing:
                output.append(f"Dependencies ({len(outgoing)}):")
                for rel in outgoing:
                    # Check if dependency is completed
                    dep = db.get_component(rel['target_id'])
                    status_marker = "[OK]" if dep['status'] == 'completed' else "[WARN]"
                    output.append(f"  {status_marker} {rel['target_name']} ({dep['status']})")
                output.append("")

            # Artifacts (suggested files)
            artifacts = component.get('artifacts', [])
            if artifacts:
                output.append(f"Suggested Files ({len(artifacts)}):")
                for art in artifacts[:5]:
                    output.append(f"  - {art['file_path']}")
                if len(artifacts) > 5:
                    output.append(f"  ... and {len(artifacts) - 5} more")
                output.append("")

            # Responsibilities
            responsibilities = component.get('responsibilities', [])
            if responsibilities:
                output.append(f"Key Responsibilities ({len(responsibilities)}):")
                for i, resp in enumerate(responsibilities[:5], 1):
                    output.append(f"  {i}. {resp}")
                if len(responsibilities) > 5:
                    output.append(f"  ... and {len(responsibilities) - 5} more")
                output.append("")

            output.append("[ACTION] Call update_component_status(component_id='{0}', new_status='in_progress') when you start".format(component['id']))

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output("\n".join(output)),
                metadata={
                    "component_id": component['id'],
                    "component_name": component['name'],
                    "dependencies_met": all(db.get_component(rel['target_id'])['status'] == 'completed' for rel in outgoing) if outgoing else True
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to get next task: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }


class UpdateComponentStatusTool(Tool):
    """Tool for updating component status."""

    def __init__(self):
        super().__init__(
            name="update_component_status",
            description="Update the status of a component (planned, in_progress, completed). Call when starting work on a component or when finishing it."
        )

    def execute(self, component_id: str, new_status: str, **kwargs: Any) -> ToolResult:
        """Update component status."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Validate status
            valid_statuses = ['planned', 'in_progress', 'completed']
            if new_status not in valid_statuses:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Invalid status '{new_status}'. Must be one of: {', '.join(valid_statuses)}"
                )

            # Get component to verify it exists
            component = db.get_component(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found in ClarityDB"
                )

            old_status = component['status']

            # Update status
            db.update_component_status(component_id, new_status)

            output = []
            output.append(f"[OK] Status updated: {component['name']}")
            output.append(f"  {old_status} -> {new_status}")

            # Calculate progress if marking as completed
            if new_status == 'completed':
                # Get phase 0 progress
                phase_0_ids = ['OBSERVABILITY_LAYER', 'CLARITY_INTEGRATION', 'WINDOWS_COMPATIBILITY',
                              'LLM_FAILURE_HANDLER', 'AGENT_INTERFACE']
                phase_0_comps = [db.get_component(cid) for cid in phase_0_ids if db.get_component(cid)]
                completed_count = sum(1 for c in phase_0_comps if c['status'] == 'completed')
                total_count = len(phase_0_comps)

                if total_count > 0:
                    progress_pct = (completed_count / total_count) * 100
                    output.append(f"\n[PROGRESS] Phase 0: {completed_count}/{total_count} ({progress_pct:.0f}%)")

            # Check for artifacts
            artifacts = db.get_component_artifacts(component_id)
            if artifacts:
                output.append(f"\n[INFO] Component has {len(artifacts)} tracked artifact(s)")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output("\n".join(output)),
                metadata={
                    "component_id": component_id,
                    "old_status": old_status,
                    "new_status": new_status
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to update component status: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to update (e.g., 'CLARITY_INTEGRATION', 'WINDOWS_COMPATIBILITY')"
                },
                "new_status": {
                    "type": "string",
                    "enum": ["planned", "in_progress", "completed"],
                    "description": "New status for the component"
                }
            },
            "required": ["component_id", "new_status"]
        }


class AddArtifactTool(Tool):
    """Tool for tracking code artifacts (files created/modified)."""

    def __init__(self):
        super().__init__(
            name="add_artifact",
            description="Track a code artifact (file) for a component. Call after creating or modifying files to maintain traceability."
        )

    def execute(self, component_id: str, file_path: str, description: str = None, **kwargs: Any) -> ToolResult:
        """Add artifact."""
        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Verify component exists
            component = db.get_component(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found in ClarityDB"
                )

            # Determine artifact type and language from file extension
            path_obj = Path(file_path)
            ext = path_obj.suffix.lower()

            if ext == '.py':
                artifact_type = 'implementation'
                language = 'python'
            elif ext in ['.md', '.txt', '.rst']:
                artifact_type = 'documentation'
                language = 'markdown'
            elif ext in ['.json', '.yaml', '.yml', '.toml', '.ini']:
                artifact_type = 'configuration'
                language = 'json' if ext == '.json' else 'yaml'
            elif ext in ['.sql']:
                artifact_type = 'database'
                language = 'sql'
            else:
                artifact_type = 'other'
                language = 'text'

            # Use filename as name and description if not provided
            name = path_obj.name
            if not description:
                description = f"File: {name}"

            # Add artifact (note: parameter is 'type_' not 'artifact_type')
            db.add_artifact(
                component_id=component_id,
                type_=artifact_type,
                name=name,
                file_path=file_path,
                description=description,
                language=language
            )

            output = []
            output.append(f"[OK] Artifact tracked: {path_obj.name}")
            output.append(f"  Component: {component['name']}")
            output.append(f"  Type: {artifact_type}")
            output.append(f"  Path: {file_path}")
            if description:
                output.append(f"  Description: {description}")

            # Get total artifacts for this component
            artifacts = db.get_component_artifacts(component_id)
            output.append(f"\n[INFO] Component now has {len(artifacts)} artifact(s)")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output("\n".join(output)),
                metadata={
                    "component_id": component_id,
                    "file_path": file_path,
                    "artifact_type": artifact_type
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to add artifact: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID this artifact belongs to"
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to the file (relative or absolute)"
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of what this file does. If not provided, uses filename."
                }
            },
            "required": ["component_id", "file_path"]
        }


class GetImplementationSpecTool(Tool):
    """Get detailed implementation specification for a component.

    Returns complete implementation guide including:
    - Method signatures with parameters, returns, exceptions
    - Acceptance criteria (definition of "done")
    - Implementation patterns and antipatterns
    - Code examples and references

    This is the enhanced version of get_next_task that provides full implementation details.
    """

    def __init__(self):
        super().__init__(
            name="get_implementation_spec",
            description="Get detailed implementation specification for a component including method signatures, acceptance criteria, and patterns"
        )

    def execute(self, component_id: str) -> ToolResult:
        """Execute tool to get implementation spec."""

        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Get component basic info
            component = db.get_component_details_full(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found"
                )

            # Check if specs exist in DB
            methods_count = db.conn.execute("""
                SELECT COUNT(*) FROM component_methods WHERE component_id = ?
            """, (component_id,)).fetchone()[0]

            # Lazy loading: Auto-extract from architecture doc if specs missing
            if methods_count == 0 and component_id in COMPONENT_SECTIONS:
                print(f"\n[AUTO-EXTRACT] Specs not found for {component_id}, extracting from architecture doc...")
                extraction_result = self._extract_and_populate(db, component_id)
                if extraction_result:
                    print(f"[AUTO-EXTRACT] Successfully populated {extraction_result['methods']} methods, {extraction_result['criteria']} criteria")
                else:
                    print(f"[WARN] Auto-extraction failed, returning empty spec")

            # Query implementation specs from new tables
            methods = db.conn.execute("""
                SELECT method_name, signature, return_type, description,
                       parameters, raises, example_usage, is_abstract
                FROM component_methods
                WHERE component_id = ?
                ORDER BY method_name
            """, (component_id,)).fetchall()

            criteria = db.conn.execute("""
                SELECT criteria_type, description, target_value,
                       validation_method, priority, status
                FROM component_acceptance_criteria
                WHERE component_id = ?
                ORDER BY
                    CASE priority
                        WHEN 'required' THEN 1
                        WHEN 'recommended' THEN 2
                        WHEN 'optional' THEN 3
                    END,
                    criteria_type
            """, (component_id,)).fetchall()

            patterns = db.conn.execute("""
                SELECT pattern_name, pattern_type, description,
                       code_example, antipatterns, reference_links
                FROM component_patterns
                WHERE component_id = ?
                ORDER BY pattern_type, pattern_name
            """, (component_id,)).fetchall()

            # Format output
            output = self._format_implementation_spec(
                component, methods, criteria, patterns
            )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                error=None,
                metadata={
                    "component_id": component_id,
                    "method_count": len(methods),
                    "criteria_count": len(criteria),
                    "pattern_count": len(patterns)
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to get implementation spec: {str(e)}"
            )
        finally:
            db.close()

    def _format_implementation_spec(
        self,
        component: dict,
        methods: list,
        criteria: list,
        patterns: list
    ) -> str:
        """Format implementation spec as readable text."""

        import json

        lines = []

        # Header
        lines.append("[IMPLEMENTATION SPEC] " + component["name"])
        lines.append("")
        lines.append(f"Component ID: {component.get('id')}")
        lines.append(f"Purpose: {component.get('purpose', 'N/A')}")
        lines.append(f"Status: {component.get('status', 'planned')}")
        lines.append("")

        # Methods Section
        if methods:
            lines.append("=" * 80)
            lines.append(f"METHODS TO IMPLEMENT ({len(methods)})")
            lines.append("=" * 80)
            lines.append("")

            for idx, method in enumerate(methods, 1):
                method_name, signature, return_type, description, params_json, raises_json, example, is_abstract = method

                lines.append(f"{idx}. {signature}")
                lines.append("")

                if description:
                    lines.append(f"   Description: {description}")
                    lines.append("")

                # Parameters
                if params_json:
                    params = json.loads(params_json)
                    if params:
                        lines.append("   Parameters:")
                        for param in params:
                            required = "required" if param.get("required") else "optional"
                            default = f", default={param['default']}" if param.get("default") else ""
                            lines.append(f"   - {param['name']} ({required}{default}): {param['type']}")
                            if param.get("description"):
                                lines.append(f"     {param['description']}")
                        lines.append("")

                # Exceptions
                if raises_json:
                    raises = json.loads(raises_json)
                    if raises:
                        lines.append(f"   Raises: {', '.join(raises)}")
                        lines.append("")

                # Example
                if example:
                    lines.append("   Example:")
                    lines.append(f"   {example}")
                    lines.append("")

        # Acceptance Criteria Section
        if criteria:
            lines.append("=" * 80)

            required_count = sum(1 for c in criteria if c[4] == "required")
            recommended_count = sum(1 for c in criteria if c[4] == "recommended")
            optional_count = sum(1 for c in criteria if c[4] == "optional")

            lines.append(f"ACCEPTANCE CRITERIA ({required_count} required, {recommended_count} recommended, {optional_count} optional)")
            lines.append("=" * 80)
            lines.append("")

            for criterion in criteria:
                criteria_type, description, target_value, validation_method, priority, status = criterion

                priority_marker = {
                    "required": "[OK] REQUIRED",
                    "recommended": "[INFO] RECOMMENDED",
                    "optional": "[INFO] OPTIONAL"
                }.get(priority, priority.upper())

                lines.append(f"{priority_marker}: {description}")
                if target_value:
                    lines.append(f"  Target: {target_value}")
                if validation_method:
                    lines.append(f"  Validation: {validation_method}")
                lines.append("")

        # Implementation Patterns Section
        if patterns:
            lines.append("=" * 80)
            lines.append(f"IMPLEMENTATION PATTERNS ({len(patterns)})")
            lines.append("=" * 80)
            lines.append("")

            for idx, pattern in enumerate(patterns, 1):
                pattern_name, pattern_type, description, code_example, antipatterns, reference_links = pattern

                lines.append(f"{idx}. Pattern: {pattern_name} ({pattern_type})")
                lines.append(f"   Why: {description}")
                lines.append("")

                if code_example:
                    lines.append("   Example Code:")
                    lines.append("   ```python")
                    for line in code_example.strip().split("\n"):
                        lines.append(f"   {line}")
                    lines.append("   ```")
                    lines.append("")

                if antipatterns:
                    lines.append("   Antipatterns:")
                    for line in antipatterns.strip().split("\n"):
                        lines.append(f"   {line}")
                    lines.append("")

                if reference_links:
                    lines.append(f"   References: {reference_links}")
                    lines.append("")

        lines.append("=" * 80)

        return safe_encode_output("\n".join(lines))

    def _extract_and_populate(self, db, component_id: str) -> Optional[Dict[str, int]]:
        """
        Extract implementation specs from architecture doc and populate DB.

        Args:
            db: ClarityDB instance
            component_id: Component to extract specs for

        Returns:
            Dict with counts of populated specs, or None if extraction failed
        """
        try:
            section_info = COMPONENT_SECTIONS.get(component_id)
            if not section_info:
                return None

            section_num, start_line, end_line = section_info

            # Read architecture doc section
            doc_path = Path(ARCHITECTURE_DOC_PATH)
            if not doc_path.exists():
                print(f"[WARN] Architecture doc not found: {ARCHITECTURE_DOC_PATH}")
                return None

            with open(doc_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Extract section content
            section_content = ''.join(lines[start_line-1:end_line])

            # Parse methods and criteria using simple pattern matching
            methods_data = self._parse_methods_from_section(section_content, component_id)
            criteria_data = self._parse_criteria_from_section(section_content, component_id)

            # Populate DB using mutation tools
            methods_added = 0
            for method_data in methods_data:
                try:
                    # Use AddMethodTool directly
                    method_id = f"method_{component_id}_{method_data['method_name']}"[:50]
                    db.conn.execute("""
                        INSERT OR IGNORE INTO component_methods (
                            id, component_id, method_name, signature, return_type,
                            description, parameters, raises, example_usage, is_abstract
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        method_id,
                        component_id,
                        method_data['method_name'],
                        method_data['signature'],
                        method_data.get('return_type'),
                        method_data.get('description', ''),
                        json.dumps(method_data.get('parameters', [])),
                        json.dumps(method_data.get('raises', [])),
                        method_data.get('example_usage'),
                        True
                    ))
                    methods_added += 1
                except Exception as e:
                    print(f"[WARN] Failed to add method {method_data.get('method_name')}: {e}")

            criteria_added = 0
            for criteria_data in criteria_data:
                try:
                    # Use AddAcceptanceCriterionTool directly
                    criterion_id = f"criterion_{component_id}_{criteria_data['criteria_type']}"[:50]
                    db.conn.execute("""
                        INSERT OR IGNORE INTO component_acceptance_criteria (
                            id, component_id, criteria_type, description,
                            target_value, validation_method, priority, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        criterion_id,
                        component_id,
                        criteria_data['criteria_type'],
                        criteria_data['description'],
                        criteria_data.get('target_value', ''),
                        criteria_data.get('validation_method', ''),
                        criteria_data.get('priority', 'required'),
                        'pending'
                    ))
                    criteria_added += 1
                except Exception as e:
                    print(f"[WARN] Failed to add criterion {criteria_data.get('criteria_type')}: {e}")

            db.conn.commit()

            return {
                'methods': methods_added,
                'criteria': criteria_added
            }

        except Exception as e:
            print(f"[ERROR] Extraction failed: {e}")
            return None

    def _parse_methods_from_section(self, content: str, component_id: str) -> List[Dict[str, Any]]:
        """Parse method signatures from architecture doc section."""
        methods = []

        # Look for method definitions in code blocks
        # Pattern: def method_name(params) -> ReturnType:
        method_pattern = r'def\s+(\w+)\s*\((.*?)\)(?:\s*->\s*([^:]+))?:'

        for match in re.finditer(method_pattern, content, re.MULTILINE | re.DOTALL):
            method_name = match.group(1)
            params_str = match.group(2)
            return_type = match.group(3).strip() if match.group(3) else None

            # Build signature
            signature = f"{method_name}({params_str})"
            if return_type:
                signature += f" -> {return_type}"

            methods.append({
                'method_name': method_name,
                'signature': signature,
                'return_type': return_type,
                'description': f"{method_name} method (auto-extracted from architecture doc)",
                'parameters': [],  # TODO: Parse parameters from params_str
                'raises': [],
                'example_usage': None
            })

        return methods

    def _parse_criteria_from_section(self, content: str, component_id: str) -> List[Dict[str, Any]]:
        """Parse acceptance criteria from architecture doc section."""
        criteria = []

        # Look for acceptance criteria sections
        # Pattern: Various patterns for criteria in the doc

        # Simple extraction: Look for bullet points with keywords
        criteria_keywords = ['must', 'should', 'test', 'coverage', 'performance', 'integration']

        for line in content.split('\n'):
            line = line.strip()
            if any(keyword in line.lower() for keyword in criteria_keywords):
                if line.startswith('-') or line.startswith('*'):
                    # Extract description
                    description = line.lstrip('-*').strip()

                    # Infer type from keywords
                    criteria_type = 'functionality'
                    if 'test' in description.lower() or 'coverage' in description.lower():
                        criteria_type = 'test_coverage'
                    elif 'performance' in description.lower():
                        criteria_type = 'performance'
                    elif 'integration' in description.lower():
                        criteria_type = 'integration'

                    criteria.append({
                        'criteria_type': criteria_type,
                        'description': description[:200],  # Limit length
                        'target_value': 'See architecture doc',
                        'validation_method': 'Manual verification',
                        'priority': 'required'
                    })

        return criteria[:5]  # Limit to first 5 to avoid noise

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to get implementation spec for (e.g., 'LLM_FAILURE_HANDLER', 'AGENT_INTERFACE')"
                }
            },
            "required": ["component_id"]
        }


class AddMethodTool(Tool):
    """Add a method signature to a component's implementation spec.

    Allows populating implementation specs without running Python scripts.
    """

    def __init__(self):
        super().__init__(
            name="add_method",
            description="Add a method signature to a component's implementation spec. Use to document methods that need to be implemented."
        )

    def execute(
        self,
        component_id: str,
        method_name: str,
        signature: str,
        description: str,
        parameters: list = None,
        return_type: str = None,
        raises: list = None,
        example_usage: str = None
    ) -> ToolResult:
        """Execute tool to add method spec."""

        import json
        import uuid

        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Verify component exists
            component = db.get_component_details_full(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found"
                )

            # Insert method
            method_id = f"method_{uuid.uuid4().hex[:8]}"

            db.conn.execute("""
                INSERT INTO component_methods (
                    id, component_id, method_name, signature, return_type,
                    description, parameters, raises, example_usage, is_abstract
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                method_id,
                component_id,
                method_name,
                signature,
                return_type,
                description,
                json.dumps(parameters or []),
                json.dumps(raises or []),
                example_usage,
                True
            ))

            db.conn.commit()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output(f"[OK] Added method '{method_name}' to {component_id}"),
                error=None,
                metadata={"method_id": method_id, "component_id": component_id}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to add method: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to add method to"
                },
                "method_name": {
                    "type": "string",
                    "description": "Method name (e.g., 'call_llm', 'handle_timeout')"
                },
                "signature": {
                    "type": "string",
                    "description": "Full method signature (e.g., 'call_llm(self, messages: List[Dict], **kwargs) -> str')"
                },
                "description": {
                    "type": "string",
                    "description": "Description of what the method does"
                },
                "parameters": {
                    "type": "array",
                    "description": "Optional list of parameter objects with name, type, description, required, default"
                },
                "return_type": {
                    "type": "string",
                    "description": "Optional return type annotation"
                },
                "raises": {
                    "type": "array",
                    "description": "Optional list of exception names this method can raise"
                },
                "example_usage": {
                    "type": "string",
                    "description": "Optional usage example"
                }
            },
            "required": ["component_id", "method_name", "signature", "description"]
        }


class AddAcceptanceCriterionTool(Tool):
    """Add an acceptance criterion to a component's implementation spec.

    Defines what "done" means for a component.
    """

    def __init__(self):
        super().__init__(
            name="add_acceptance_criterion",
            description="Add an acceptance criterion to a component (definition of done). Use to specify test coverage, integration requirements, performance targets, etc."
        )

    def execute(
        self,
        component_id: str,
        criteria_type: str,
        description: str,
        target_value: str = None,
        validation_method: str = None,
        priority: str = "required"
    ) -> ToolResult:
        """Execute tool to add acceptance criterion."""

        import uuid

        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Verify component exists
            component = db.get_component_details_full(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found"
                )

            # Validate priority
            if priority not in ["required", "recommended", "optional"]:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Priority must be 'required', 'recommended', or 'optional', got '{priority}'"
                )

            # Insert criterion
            criterion_id = f"criterion_{uuid.uuid4().hex[:8]}"

            db.conn.execute("""
                INSERT INTO component_acceptance_criteria (
                    id, component_id, criteria_type, description,
                    target_value, validation_method, priority, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                criterion_id,
                component_id,
                criteria_type,
                description,
                target_value,
                validation_method,
                priority,
                "pending"
            ))

            db.conn.commit()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output(f"[OK] Added {priority} acceptance criterion to {component_id}"),
                error=None,
                metadata={"criterion_id": criterion_id, "component_id": component_id}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to add acceptance criterion: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID to add criterion to"
                },
                "criteria_type": {
                    "type": "string",
                    "description": "Type of criterion (e.g., 'test_coverage', 'integration', 'performance', 'breaking_changes')"
                },
                "description": {
                    "type": "string",
                    "description": "Description of the criterion"
                },
                "target_value": {
                    "type": "string",
                    "description": "Optional target value (e.g., '90%', '< 100ms', '0 breaking changes')"
                },
                "validation_method": {
                    "type": "string",
                    "description": "Optional validation method (e.g., 'pytest --cov', 'Manual verification')"
                },
                "priority": {
                    "type": "string",
                    "description": "Priority: 'required', 'recommended', or 'optional' (default: required)",
                    "enum": ["required", "recommended", "optional"]
                }
            },
            "required": ["component_id", "criteria_type", "description"]
        }


class UpdateMethodTool(Tool):
    """Update an existing method specification.

    Allows refining method specs based on implementation learnings.
    """

    def __init__(self):
        super().__init__(
            name="update_method",
            description="Update an existing method specification. Use to refine signatures, parameters, or examples based on implementation learnings."
        )

    def execute(
        self,
        component_id: str,
        method_name: str,
        signature: str = None,
        description: str = None,
        parameters: list = None,
        return_type: str = None,
        raises: list = None,
        example_usage: str = None
    ) -> ToolResult:
        """Execute tool to update method spec."""

        import json

        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Verify component exists
            component = db.get_component_details_full(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found"
                )

            # Find method by name
            method = db.conn.execute("""
                SELECT id, signature, description, parameters, return_type, raises, example_usage
                FROM component_methods
                WHERE component_id = ? AND method_name = ?
            """, (component_id, method_name)).fetchone()

            if not method:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Method '{method_name}' not found in {component_id}"
                )

            method_id = method[0]

            # Build update fields (only update provided fields)
            updates = []
            values = []

            if signature is not None:
                updates.append("signature = ?")
                values.append(signature)
            if description is not None:
                updates.append("description = ?")
                values.append(description)
            if parameters is not None:
                updates.append("parameters = ?")
                values.append(json.dumps(parameters))
            if return_type is not None:
                updates.append("return_type = ?")
                values.append(return_type)
            if raises is not None:
                updates.append("raises = ?")
                values.append(json.dumps(raises))
            if example_usage is not None:
                updates.append("example_usage = ?")
                values.append(example_usage)

            if not updates:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="No fields provided to update"
                )

            # Add updated_at
            updates.append("updated_at = CURRENT_TIMESTAMP")

            # Execute update
            values.append(method_id)
            db.conn.execute(f"""
                UPDATE component_methods
                SET {', '.join(updates)}
                WHERE id = ?
            """, values)

            db.conn.commit()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output(f"[OK] Updated method '{method_name}' in {component_id}"),
                error=None,
                metadata={"method_id": method_id, "component_id": component_id, "fields_updated": len(updates) - 1}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to update method: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID containing the method"
                },
                "method_name": {
                    "type": "string",
                    "description": "Method name to update (must exist)"
                },
                "signature": {
                    "type": "string",
                    "description": "Optional: New method signature"
                },
                "description": {
                    "type": "string",
                    "description": "Optional: New description"
                },
                "parameters": {
                    "type": "array",
                    "description": "Optional: New parameter list"
                },
                "return_type": {
                    "type": "string",
                    "description": "Optional: New return type"
                },
                "raises": {
                    "type": "array",
                    "description": "Optional: New exception list"
                },
                "example_usage": {
                    "type": "string",
                    "description": "Optional: New usage example"
                }
            },
            "required": ["component_id", "method_name"]
        }


class UpdateAcceptanceCriterionTool(Tool):
    """Update an existing acceptance criterion.

    Allows refining acceptance criteria based on implementation learnings.
    """

    def __init__(self):
        super().__init__(
            name="update_acceptance_criterion",
            description="Update an existing acceptance criterion. Use to adjust targets, validation methods, or priorities based on implementation learnings."
        )

    def execute(
        self,
        component_id: str,
        criteria_type: str,
        description: str = None,
        target_value: str = None,
        validation_method: str = None,
        priority: str = None,
        status: str = None
    ) -> ToolResult:
        """Execute tool to update acceptance criterion."""

        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Verify component exists
            component = db.get_component_details_full(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found"
                )

            # Find criterion by type (assuming one criterion per type per component)
            criterion = db.conn.execute("""
                SELECT id
                FROM component_acceptance_criteria
                WHERE component_id = ? AND criteria_type = ?
            """, (component_id, criteria_type)).fetchone()

            if not criterion:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Acceptance criterion type '{criteria_type}' not found in {component_id}"
                )

            criterion_id = criterion[0]

            # Build update fields
            updates = []
            values = []

            if description is not None:
                updates.append("description = ?")
                values.append(description)
            if target_value is not None:
                updates.append("target_value = ?")
                values.append(target_value)
            if validation_method is not None:
                updates.append("validation_method = ?")
                values.append(validation_method)
            if priority is not None:
                if priority not in ["required", "recommended", "optional"]:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Priority must be 'required', 'recommended', or 'optional', got '{priority}'"
                    )
                updates.append("priority = ?")
                values.append(priority)
            if status is not None:
                if status not in ["pending", "met", "not_met"]:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Status must be 'pending', 'met', or 'not_met', got '{status}'"
                    )
                updates.append("status = ?")
                values.append(status)

            if not updates:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="No fields provided to update"
                )

            # Add updated_at
            updates.append("updated_at = CURRENT_TIMESTAMP")

            # Execute update
            values.append(criterion_id)
            db.conn.execute(f"""
                UPDATE component_acceptance_criteria
                SET {', '.join(updates)}
                WHERE id = ?
            """, values)

            db.conn.commit()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output(f"[OK] Updated acceptance criterion '{criteria_type}' in {component_id}"),
                error=None,
                metadata={"criterion_id": criterion_id, "component_id": component_id, "fields_updated": len(updates) - 1}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to update acceptance criterion: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID containing the criterion"
                },
                "criteria_type": {
                    "type": "string",
                    "description": "Criterion type to update (e.g., 'test_coverage', 'integration')"
                },
                "description": {
                    "type": "string",
                    "description": "Optional: New description"
                },
                "target_value": {
                    "type": "string",
                    "description": "Optional: New target value (e.g., '95%', '< 50ms')"
                },
                "validation_method": {
                    "type": "string",
                    "description": "Optional: New validation method"
                },
                "priority": {
                    "type": "string",
                    "description": "Optional: New priority (required/recommended/optional)",
                    "enum": ["required", "recommended", "optional"]
                },
                "status": {
                    "type": "string",
                    "description": "Optional: New status (pending/met/not_met)",
                    "enum": ["pending", "met", "not_met"]
                }
            },
            "required": ["component_id", "criteria_type"]
        }


class UpdateImplementationPatternTool(Tool):
    """Update an existing implementation pattern.

    Allows refining patterns based on implementation learnings.
    """

    def __init__(self):
        super().__init__(
            name="update_implementation_pattern",
            description="Update an existing implementation pattern. Use to refine code examples, add antipatterns, or update references based on implementation learnings."
        )

    def execute(
        self,
        component_id: str,
        pattern_name: str,
        pattern_type: str = None,
        description: str = None,
        code_example: str = None,
        antipatterns: str = None,
        reference_links: str = None
    ) -> ToolResult:
        """Execute tool to update implementation pattern."""

        db = _get_db()
        if not db:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="ClarityDB not found at .clarity/ai-coding-agent.db"
            )

        try:
            # Verify component exists
            component = db.get_component_details_full(component_id)
            if not component:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Component '{component_id}' not found"
                )

            # Find pattern by name
            pattern = db.conn.execute("""
                SELECT id
                FROM component_patterns
                WHERE component_id = ? AND pattern_name = ?
            """, (component_id, pattern_name)).fetchone()

            if not pattern:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Pattern '{pattern_name}' not found in {component_id}"
                )

            pattern_id = pattern[0]

            # Build update fields
            updates = []
            values = []

            if pattern_type is not None:
                updates.append("pattern_type = ?")
                values.append(pattern_type)
            if description is not None:
                updates.append("description = ?")
                values.append(description)
            if code_example is not None:
                updates.append("code_example = ?")
                values.append(code_example)
            if antipatterns is not None:
                updates.append("antipatterns = ?")
                values.append(antipatterns)
            if reference_links is not None:
                updates.append("reference_links = ?")
                values.append(reference_links)

            if not updates:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="No fields provided to update"
                )

            # Add updated_at
            updates.append("updated_at = CURRENT_TIMESTAMP")

            # Execute update
            values.append(pattern_id)
            db.conn.execute(f"""
                UPDATE component_patterns
                SET {', '.join(updates)}
                WHERE id = ?
            """, values)

            db.conn.commit()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=safe_encode_output(f"[OK] Updated pattern '{pattern_name}' in {component_id}"),
                error=None,
                metadata={"pattern_id": pattern_id, "component_id": component_id, "fields_updated": len(updates) - 1}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to update implementation pattern: {str(e)}"
            )
        finally:
            db.close()

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "component_id": {
                    "type": "string",
                    "description": "Component ID containing the pattern"
                },
                "pattern_name": {
                    "type": "string",
                    "description": "Pattern name to update (must exist)"
                },
                "pattern_type": {
                    "type": "string",
                    "description": "Optional: New pattern type (e.g., 'workflow', 'error_handling')"
                },
                "description": {
                    "type": "string",
                    "description": "Optional: New description (why use this pattern)"
                },
                "code_example": {
                    "type": "string",
                    "description": "Optional: New code example"
                },
                "antipatterns": {
                    "type": "string",
                    "description": "Optional: New antipatterns (what NOT to do)"
                },
                "reference_links": {
                    "type": "string",
                    "description": "Optional: New reference links"
                }
            },
            "required": ["component_id", "pattern_name"]
        }


# Export all tool classes
__all__ = [
    "QueryComponentTool",
    "QueryDependenciesTool",
    "QueryDecisionsTool",
    "QueryFlowsTool",
    "QueryArchitectureSummaryTool",
    "SearchComponentsTool",
    "GetNextTaskTool",
    "UpdateComponentStatusTool",
    "AddArtifactTool",
    "GetImplementationSpecTool",
    "AddMethodTool",
    "AddAcceptanceCriterionTool",
    "UpdateMethodTool",
    "UpdateAcceptanceCriterionTool",
    "UpdateImplementationPatternTool",
]
