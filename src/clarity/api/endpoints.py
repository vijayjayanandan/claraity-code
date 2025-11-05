"""
FastAPI REST Endpoints for ClarAIty

Exposes ClarAIty functionality via REST API.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Body, Depends
from pydantic import BaseModel, Field

from ..core.database import ClarityDB, ClarityDBError
from ..core.generator import ClarityGenerator, ClarityGeneratorError
from ..core.blueprint import Blueprint
from ..api.state import state_manager
from ..sync.orchestrator import SyncOrchestrator
from ..config import get_config

logger = logging.getLogger(__name__)

# Global instances (will be set by server on startup)
db: Optional[ClarityDB] = None
generator: Optional[ClarityGenerator] = None
sync_orchestrator: Optional[SyncOrchestrator] = None


def set_dependencies(
    _db: Optional[ClarityDB] = None,
    _generator: Optional[ClarityGenerator] = None,
    _sync_orchestrator: Optional[SyncOrchestrator] = None
):
    """Set global dependencies (called by server on startup)."""
    global db, generator, sync_orchestrator
    db = _db
    generator = _generator
    sync_orchestrator = _sync_orchestrator

# Create API router
router = APIRouter(prefix="/api/clarity", tags=["clarity"])


# ========== Pydantic Models ==========

class StatusResponse(BaseModel):
    """System status response."""
    status: str = Field(..., description="System status (ok, error)")
    clarity_enabled: bool = Field(..., description="Whether ClarAIty is enabled")
    mode: str = Field(..., description="ClarAIty mode (auto, always, manual)")
    database_connected: bool = Field(..., description="Database connection status")
    sync_enabled: bool = Field(..., description="Auto-sync enabled")
    last_sync: Optional[str] = Field(None, description="Last sync timestamp (ISO format)")
    components_count: int = Field(..., description="Total components in database")
    timestamp: str = Field(..., description="Response timestamp")


class ComponentResponse(BaseModel):
    """Component response."""
    id: str  # Component IDs are strings (e.g., 'AGENTRESPONSE')
    name: str
    type: str
    purpose: Optional[str] = None
    layer: Optional[str] = None
    file_path: Optional[str] = None
    created_at: Optional[str] = None


class BlueprintCreateRequest(BaseModel):
    """Request to create a new blueprint."""
    task_description: str = Field(..., description="Task description for blueprint generation")
    codebase_context: Optional[str] = Field(None, description="Optional codebase context")


class BlueprintResponse(BaseModel):
    """Blueprint response."""
    blueprint: Dict[str, Any] = Field(..., description="Blueprint data")
    session_id: str = Field(..., description="Session ID")
    status: str = Field(..., description="Blueprint status (pending, approved, rejected)")


class ApprovalRequest(BaseModel):
    """Blueprint approval/rejection request."""
    session_id: str = Field(..., description="Session ID")
    feedback: Optional[str] = Field(None, description="Optional feedback for rejection")


class ScanRequest(BaseModel):
    """Scan request."""
    scope: str = Field("incremental", description="Scan scope (full, incremental)")
    directory: Optional[str] = Field(None, description="Directory to scan (for full scan)")


# ========== Endpoints ==========

@router.get("/status", response_model=StatusResponse)
async def get_status():
    """
    Get system status.

    Returns current status of ClarAIty system including:
    - Configuration
    - Database connection
    - Sync status
    - Component count
    """
    try:
        config = get_config()

        # Get database status
        db_connected = False
        component_count = 0
        try:
            if db:
                component_count = len(db.get_all_components())
                db_connected = True
        except Exception as e:
            logger.warning(f"Database error in status check: {e}")

        # Get sync status
        sync_status = sync_orchestrator.get_status() if sync_orchestrator else {}

        return StatusResponse(
            status="ok",
            clarity_enabled=config.enabled,
            mode=config.mode,
            database_connected=db_connected,
            sync_enabled=config.auto_sync,
            last_sync=sync_status.get('last_sync'),
            components_count=component_count,
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        logger.error(f"Error getting status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/architecture")
async def get_architecture():
    """
    Get architecture summary with component counts by layer.

    Returns:
        - project_name: Name of the project
        - total_components: Total number of components
        - total_artifacts: Total number of code artifacts
        - total_relationships: Total number of relationships
        - total_decisions: Total number of design decisions
        - layers: List of layers with component counts
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        # Get statistics from database
        stats = db.get_statistics()

        # Get components grouped by layer
        components = db.get_all_components()
        layer_counts = {}
        for comp in components:
            layer = comp.get('layer', 'unknown')
            if layer not in layer_counts:
                layer_counts[layer] = {
                    'layer': layer,
                    'component_count': 0,
                    'completed_count': 0,
                    'in_progress_count': 0,
                    'planned_count': 0
                }
            layer_counts[layer]['component_count'] += 1

            # Status based on metadata (if available)
            status = comp.get('status', 'completed')
            if status == 'completed':
                layer_counts[layer]['completed_count'] += 1
            elif status == 'in_progress':
                layer_counts[layer]['in_progress_count'] += 1
            elif status == 'planned':
                layer_counts[layer]['planned_count'] += 1

        return {
            'project_name': 'AI Coding Agent',
            'total_components': stats['total_components'],
            'total_artifacts': stats['total_artifacts'],
            'total_relationships': stats['total_relationships'],
            'total_decisions': stats['total_decisions'],
            'layers': list(layer_counts.values())
        }

    except ClarityDBError as e:
        logger.error(f"Database error getting architecture: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting architecture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/components", response_model=List[ComponentResponse])
async def list_components(
    layer: Optional[str] = Query(None, description="Filter by layer"),
    file_path: Optional[str] = Query(None, description="Filter by file path"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results")
):
    """
    List components.

    Supports filtering by:
    - layer: Component layer (core, workflow, memory, etc.)
    - file_path: File path
    - limit: Maximum results (default: 100)
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        # Query database with layer filter
        components = db.get_all_components(layer=layer)

        # Apply additional filters manually
        if file_path:
            components = [c for c in components if c.get('file_path') == file_path]

        # Limit results
        components = components[:limit]

        # Convert to response models
        return [
            ComponentResponse(
                id=c['id'],
                name=c['name'],
                type=c['type'],
                purpose=c.get('purpose'),
                layer=c.get('layer'),
                file_path=c.get('file_path'),
                created_at=c.get('created_at')
            )
            for c in components
        ]

    except ClarityDBError as e:
        logger.error(f"Database error listing components: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        logger.error(f"Error listing components: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/components/{component_id}")
async def get_component(
    component_id: int
):
    """Get component by ID with full details."""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        component = db.get_component(component_id)

        if not component:
            raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

        # Get related artifacts
        artifacts = db.get_component_artifacts(component_id)

        # Get relationships
        relationships = db.get_component_relationships(component_id)

        return {
            "component": component,
            "artifacts": artifacts,
            "relationships": relationships
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting component {component_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprint", response_model=BlueprintResponse)
async def get_current_blueprint():
    """Get current blueprint (if any)."""
    try:
        state = await state_manager.get_state()

        if not state:
            raise HTTPException(status_code=404, detail="No active blueprint")

        return BlueprintResponse(
            blueprint=state['blueprint'],
            session_id=state['session_id'],
            status=state['status']
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting blueprint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blueprint", response_model=BlueprintResponse)
async def create_blueprint(
    request: BlueprintCreateRequest
):
    """
    Create new blueprint from task description.

    This endpoint generates an architecture blueprint using LLM.
    The blueprint can then be approved or rejected via /blueprint/approve or /blueprint/reject.
    """
    try:
        if not generator:
            # Create generator if not injected
            generator = ClarityGenerator()

        logger.info(f"Generating blueprint for task: {request.task_description[:100]}")

        # Generate blueprint
        blueprint = generator.generate_blueprint(
            task_description=request.task_description,
            codebase_context=request.codebase_context or ""
        )

        # Store in state manager
        session_id = await state_manager.set_blueprint(blueprint)

        logger.info(f"Blueprint generated: session_id={session_id}")

        return BlueprintResponse(
            blueprint=blueprint.to_dict(),
            session_id=session_id,
            status="pending"
        )

    except ClarityGeneratorError as e:
        logger.error(f"Blueprint generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating blueprint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/blueprint/approve")
async def approve_blueprint(request: ApprovalRequest):
    """
    Approve current blueprint.

    This signals that the user has reviewed and approved the architecture plan.
    Code generation can proceed.
    """
    try:
        # Verify session
        state = await state_manager.get_state()
        if not state or state['session_id'] != request.session_id:
            raise HTTPException(status_code=404, detail="Blueprint not found or session mismatch")

        # Approve
        success = await state_manager.approve()

        if not success:
            raise HTTPException(status_code=500, detail="Failed to approve blueprint")

        logger.info(f"Blueprint approved: session_id={request.session_id}")

        return {
            "status": "approved",
            "session_id": request.session_id,
            "message": "Blueprint approved successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving blueprint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/blueprint/reject")
async def reject_blueprint(request: ApprovalRequest):
    """
    Reject current blueprint.

    This signals that the user wants changes to the architecture plan.
    Optional feedback can be provided for refinement.
    """
    try:
        # Verify session
        state = await state_manager.get_state()
        if not state or state['session_id'] != request.session_id:
            raise HTTPException(status_code=404, detail="Blueprint not found or session mismatch")

        # Reject
        success = await state_manager.reject(feedback=request.feedback)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to reject blueprint")

        logger.info(f"Blueprint rejected: session_id={request.session_id}")

        return {
            "status": "rejected",
            "session_id": request.session_id,
            "feedback": request.feedback,
            "message": "Blueprint rejected"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting blueprint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan")
async def trigger_scan(
    request: ScanRequest
):
    """
    Trigger codebase scan.

    Supports two scopes:
    - 'incremental': Re-sync changed files (fast)
    - 'full': Full rescan of codebase (slow, thorough)
    """
    try:
        if not sync_orchestrator:
            raise HTTPException(status_code=503, detail="Sync orchestrator not available")

        logger.info(f"Triggering {request.scope} scan")

        if request.scope == "full":
            # Full rescan
            result = await sync_orchestrator.full_rescan(directory=request.directory)
        elif request.scope == "incremental":
            # Trigger sync (will process any pending changes)
            result = await sync_orchestrator.sync_files([], [], [])
        else:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {request.scope}")

        return {
            "status": "completed" if result.success else "failed",
            "scope": request.scope,
            "files_analyzed": result.files_analyzed,
            "components_added": result.components_added,
            "components_updated": result.components_updated,
            "duration_seconds": result.duration_seconds,
            "errors": result.errors
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows")
async def list_flows(
):
    """List execution flows."""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        flows = db.get_all_flows()

        return {
            "flows": flows,
            "count": len(flows)
        }

    except Exception as e:
        logger.error(f"Error listing flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{flow_id}")
async def get_flow(
    flow_id: int
):
    """Get flow by ID with steps."""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        flow = db.get_flow(flow_id)

        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Get steps
        steps = db.get_flow_steps(flow_id)

        return {
            "flow": flow,
            "steps": steps
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting flow {flow_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/relationships")
async def list_relationships(
    source_id: Optional[int] = Query(None, description="Filter by source component ID"),
    target_id: Optional[int] = Query(None, description="Filter by target component ID")
):
    """List component relationships."""
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        if source_id:
            rel_dict = db.get_component_relationships(source_id)
            # Flatten outgoing and incoming into a single list
            relationships = rel_dict.get('outgoing', []) + rel_dict.get('incoming', [])
        elif target_id:
            # Get relationships where this is the target
            all_rels = db.get_all_relationships()
            relationships = [r for r in all_rels if r['target_id'] == target_id]
        else:
            relationships = db.get_all_relationships()

        return {
            "relationships": relationships,
            "count": len(relationships)
        }

    except Exception as e:
        logger.error(f"Error listing relationships: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/architecture/layers")
async def get_layer_architecture():
    """
    Get layer-to-layer architecture overview.

    Returns:
        - layers: List of layers with component counts
        - connections: Inter-layer relationships (derived from component relationships)

    This endpoint provides Level 1 view for the multi-level architecture diagram.
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        # Get all components grouped by layer
        components = db.get_all_components()
        layer_map = {}
        for comp in components:
            layer = comp.get('layer', 'other')
            if layer not in layer_map:
                layer_map[layer] = []
            layer_map[layer].append(comp)

        # Build layer nodes
        layers = [
            {
                "id": layer,
                "name": layer,
                "count": len(comps)
            }
            for layer, comps in layer_map.items()
        ]

        # Get all relationships
        all_relationships = db.get_all_relationships()

        # Build component ID to layer mapping
        component_to_layer = {comp['id']: comp.get('layer', 'other') for comp in components}

        # Derive layer-to-layer connections
        layer_connections = {}
        for rel in all_relationships:
            from_layer = component_to_layer.get(rel['source_id'], 'other')
            to_layer = component_to_layer.get(rel['target_id'], 'other')

            # Only count inter-layer relationships
            if from_layer != to_layer:
                key = f"{from_layer}→{to_layer}"
                if key not in layer_connections:
                    layer_connections[key] = {
                        "source": from_layer,
                        "target": to_layer,
                        "count": 0,
                        "types": set()
                    }
                layer_connections[key]["count"] += 1
                layer_connections[key]["types"].add(rel.get('relationship_type', 'unknown'))

        # Convert to list
        connections = [
            {
                "source": conn["source"],
                "target": conn["target"],
                "count": conn["count"],
                "types": list(conn["types"])
            }
            for conn in layer_connections.values()
        ]

        return {
            "layers": layers,
            "connections": connections
        }

    except Exception as e:
        logger.error(f"Error getting layer architecture: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/layers/{layer_name}/components")
async def get_layer_components(layer_name: str):
    """
    Get components within a specific layer with their relationships.

    Args:
        layer_name: Name of the layer (e.g., 'core', 'workflow')

    Returns:
        - components: List of components in this layer
        - relationships: Relationships between components in this layer
        - external_connections: Summary of connections to other layers

    This endpoint provides Level 2 view for the multi-level architecture diagram.
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        # Get components in this layer
        components = db.get_all_components(layer=layer_name)

        if not components:
            raise HTTPException(status_code=404, detail=f"Layer '{layer_name}' not found or has no components")

        # Get component IDs in this layer
        component_ids = {comp['id'] for comp in components}

        # Get all relationships
        all_relationships = db.get_all_relationships()

        # Filter relationships within this layer
        internal_relationships = []
        external_outgoing = {}
        external_incoming = {}

        for rel in all_relationships:
            from_id = rel['source_id']
            to_id = rel['target_id']
            from_in_layer = from_id in component_ids
            to_in_layer = to_id in component_ids

            if from_in_layer and to_in_layer:
                # Internal relationship
                internal_relationships.append({
                    "id": rel['id'],
                    "from_component_id": from_id,
                    "to_component_id": to_id,
                    "relationship_type": rel.get('relationship_type', 'unknown')
                })
            elif from_in_layer:
                # Outgoing to another layer
                # Get target component to find its layer
                target_comp = next((c for c in db.get_all_components() if c['id'] == to_id), None)
                if target_comp:
                    target_layer = target_comp.get('layer', 'other')
                    external_outgoing[target_layer] = external_outgoing.get(target_layer, 0) + 1
            elif to_in_layer:
                # Incoming from another layer
                source_comp = next((c for c in db.get_all_components() if c['id'] == from_id), None)
                if source_comp:
                    source_layer = source_comp.get('layer', 'other')
                    external_incoming[source_layer] = external_incoming.get(source_layer, 0) + 1

        return {
            "layer": layer_name,
            "components": components,
            "relationships": internal_relationships,
            "external_connections": {
                "outgoing": external_outgoing,
                "incoming": external_incoming
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting layer components for '{layer_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities")
async def get_capabilities():
    """Get system capabilities grouped by function.

    Returns capability cards for the Dashboard tab with readiness percentages.
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")

        # Get all components
        components = db.get_all_components()

        # Define capability mappings based on layers and component types
        capabilities = [
            {
                "name": "Planning & Analysis",
                "description": "Analyze tasks and create execution plans",
                "components": ["TaskAnalyzer", "TaskPlanner"],
                "readiness": 95,
                "layer": "workflow"
            },
            {
                "name": "Execution",
                "description": "Execute plans with tool integration",
                "components": ["ExecutionEngine", "ToolExecutor"],
                "readiness": 100,
                "layer": "workflow"
            },
            {
                "name": "Verification",
                "description": "Verify results and ensure quality",
                "components": ["VerificationLayer"],
                "readiness": 85,
                "layer": "workflow"
            },
            {
                "name": "Memory Management",
                "description": "Context and learning across sessions",
                "components": ["MemoryManager", "WorkingMemory", "EpisodicMemory", "SemanticMemory"],
                "readiness": 90,
                "layer": "memory"
            },
            {
                "name": "Code Understanding",
                "description": "RAG-based semantic code search",
                "components": ["CodeIndexer", "Embedder", "HybridRetriever"],
                "readiness": 80,
                "layer": "rag"
            }
        ]

        return {
            "capabilities": capabilities,
            "count": len(capabilities)
        }

    except Exception as e:
        logger.error(f"Error getting capabilities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
