"""
ClarAIty FastAPI Server

Provides REST API endpoints for querying architecture clarity data.
"""

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.clarity.core.database import ClarityDB
from src.clarity.api.websocket import websocket_endpoint


# Pydantic models for request/response
class ComponentResponse(BaseModel):
    """Component data response"""
    id: str
    name: str
    type: str
    layer: str
    status: str
    purpose: Optional[str] = None
    business_value: Optional[str] = None
    design_rationale: Optional[str] = None
    responsibilities: Optional[List[str]] = None
    created_at: Optional[str] = None


class ComponentDetailResponse(ComponentResponse):
    """Full component details with artifacts and relationships"""
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    relationships: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)


class DesignDecisionResponse(BaseModel):
    """Design decision data"""
    id: str
    component_id: str
    decision_type: str
    question: str
    chosen_solution: str
    rationale: str
    alternatives_considered: Optional[List[str]] = None
    trade_offs: Optional[str] = None
    decided_by: str
    confidence: float
    created_at: Optional[str] = None


class RelationshipResponse(BaseModel):
    """Component relationship data"""
    id: str
    source_id: str
    source_name: Optional[str] = None
    target_id: str
    target_name: Optional[str] = None
    relationship_type: str
    description: Optional[str] = None
    criticality: str


class ArchitectureSummaryResponse(BaseModel):
    """Architecture overview summary"""
    project_name: str
    total_components: int
    total_artifacts: int
    total_relationships: int
    total_decisions: int
    layers: List[Dict[str, Any]]


class ValidationRequest(BaseModel):
    """User validation request"""
    session_id: str
    artifact_type: str
    artifact_id: str
    ai_proposal: str
    user_response: str


class SessionResponse(BaseModel):
    """Generation session data"""
    id: str
    project_name: str
    session_type: str
    mode: str
    status: str
    started_at: str
    completed_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# Initialize FastAPI app
app = FastAPI(
    title="ClarAIty API",
    description="Architecture Clarity Visualization API",
    version="1.0.0"
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",  # Browser treats localhost and 127.0.0.1 as different origins
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database path (configurable via environment variable)
DB_PATH = Path(".clarity/ai-coding-agent.db")


def get_db() -> ClarityDB:
    """Get database connection"""
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Database not found at {DB_PATH}. Please run populate_from_codebase.py first."
        )
    return ClarityDB(str(DB_PATH))


@app.get("/", tags=["health"])
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ClarAIty API",
        "version": "1.0.0"
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Detailed health check"""
    try:
        db = get_db()
        stats = db.get_statistics()
        db.close()
        return {
            "status": "healthy",
            "database": "connected",
            "statistics": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/architecture", response_model=ArchitectureSummaryResponse, tags=["architecture"])
async def get_architecture_summary():
    """
    Get complete architecture summary

    Returns overview of all components, layers, and statistics.
    """
    try:
        db = get_db()
        summary = db.get_architecture_summary()
        stats = db.get_statistics()
        db.close()

        return ArchitectureSummaryResponse(
            project_name=summary.get('project_name', 'AI Coding Agent'),
            total_components=stats['total_components'],
            total_artifacts=stats['total_artifacts'],
            total_relationships=stats['total_relationships'],
            total_decisions=stats['total_decisions'],
            layers=summary.get('layers', [])
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/components", response_model=List[ComponentResponse], tags=["components"])
async def get_all_components(
    layer: Optional[str] = Query(None, description="Filter by layer"),
    type: Optional[str] = Query(None, description="Filter by type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Max results")
):
    """
    Get all components with optional filters

    Query parameters:
    - layer: Filter by architectural layer
    - type: Filter by component type
    - status: Filter by component status
    - limit: Maximum number of results (default: 100)
    """
    try:
        db = get_db()
        components = db.get_all_components()
        db.close()

        # Apply filters
        if layer:
            components = [c for c in components if c.get('layer') == layer]
        if type:
            components = [c for c in components if c.get('type') == type]
        if status:
            components = [c for c in components if c.get('status') == status]

        # Apply limit
        components = components[:limit]

        return [ComponentResponse(**comp) for comp in components]
    except HTTPException:
        raise
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/components/search", response_model=List[ComponentResponse], tags=["components"])
async def search_components(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results")
):
    """
    Search components by name or purpose

    Query parameters:
    - q: Search query (minimum 1 character)
    - limit: Maximum number of results (default: 20)
    """
    try:
        db = get_db()
        results = db.search_components(q)
        db.close()

        # Apply limit
        results = results[:limit]

        return [ComponentResponse(**comp) for comp in results]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/components/{component_id}", response_model=ComponentDetailResponse, tags=["components"])
async def get_component(component_id: str):
    """
    Get detailed component information

    Includes artifacts, design decisions, and relationships.
    """
    try:
        db = get_db()
        component = db.get_component_details_full(component_id)
        db.close()

        if not component:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{component_id}' not found"
            )

        return ComponentDetailResponse(**component)
    except HTTPException:
        raise
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/components/{component_id}/relationships", response_model=Dict[str, List[RelationshipResponse]], tags=["components"])
async def get_component_relationships(component_id: str):
    """
    Get all relationships for a component

    Returns both incoming and outgoing relationships.
    """
    try:
        db = get_db()

        # Check if component exists
        component = db.get_component(component_id)
        if not component:
            db.close()
            raise HTTPException(
                status_code=404,
                detail=f"Component '{component_id}' not found"
            )

        relationships = db.get_component_relationships(component_id)
        db.close()

        return {
            "outgoing": [RelationshipResponse(**rel) for rel in relationships['outgoing']],
            "incoming": [RelationshipResponse(**rel) for rel in relationships['incoming']]
        }
    except HTTPException:
        raise
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/components/{component_id}/decisions", response_model=List[DesignDecisionResponse], tags=["components"])
async def get_component_decisions_endpoint(component_id: str):
    """
    Get all design decisions for a component
    """
    try:
        db = get_db()

        # Check if component exists
        component = db.get_component(component_id)
        if not component:
            db.close()
            raise HTTPException(
                status_code=404,
                detail=f"Component '{component_id}' not found"
            )

        decisions = db.get_component_decisions(component_id)
        db.close()

        return [DesignDecisionResponse(**dec) for dec in decisions]
    except HTTPException:
        raise
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/decisions", response_model=List[DesignDecisionResponse], tags=["decisions"])
async def get_all_decisions(
    decision_type: Optional[str] = Query(None, description="Filter by decision type"),
    limit: int = Query(100, ge=1, le=1000, description="Max results")
):
    """
    Get all design decisions

    Query parameters:
    - decision_type: Filter by type (architecture, implementation, technology, pattern)
    - limit: Maximum number of results (default: 100)
    """
    try:
        db = get_db()
        decisions = db.get_all_decisions()
        db.close()

        # Apply filter
        if decision_type:
            decisions = [d for d in decisions if d.get('decision_type') == decision_type]

        # Apply limit
        decisions = decisions[:limit]

        return [DesignDecisionResponse(**dec) for dec in decisions]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/relationships", response_model=List[RelationshipResponse], tags=["relationships"])
async def get_all_relationships(
    relationship_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(100, ge=1, le=1000, description="Max results")
):
    """
    Get all component relationships

    Query parameters:
    - relationship_type: Filter by type (imports, extends, uses, depends-on)
    - limit: Maximum number of results (default: 100)
    """
    try:
        db = get_db()
        relationships = db.get_all_relationships()
        db.close()

        # Apply filter
        if relationship_type:
            relationships = [r for r in relationships if r.get('relationship_type') == relationship_type]

        # Apply limit
        relationships = relationships[:limit]

        return [RelationshipResponse(**rel) for rel in relationships]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions", response_model=List[SessionResponse], tags=["sessions"])
async def get_sessions(
    limit: int = Query(10, ge=1, le=100, description="Max results")
):
    """
    Get all generation sessions
    """
    try:
        db = get_db()
        # Get all sessions (need to add this method to ClarityDB if not exists)
        # For now, use get_statistics to get session info
        stats = db.get_statistics()
        db.close()

        # TODO: Implement get_all_sessions in ClarityDB
        # Placeholder response
        return []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate", tags=["validation"])
async def record_validation(validation: ValidationRequest):
    """
    Record user validation response

    Stores user's approval/rejection of AI-generated artifacts.
    """
    try:
        db = get_db()

        validation_id = db.add_validation(
            session_id=validation.session_id,
            artifact_type=validation.artifact_type,
            artifact_id=validation.artifact_id,
            ai_proposal=validation.ai_proposal,
            user_response=validation.user_response
        )

        db.close()

        return {
            "status": "success",
            "validation_id": validation_id,
            "message": "Validation recorded successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/statistics", tags=["statistics"])
async def get_statistics():
    """
    Get database statistics

    Returns counts of all entities in the database.
    """
    try:
        db = get_db()
        stats = db.get_statistics()
        db.close()

        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/generate/{session_id}")
async def websocket_generation(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time generation updates

    Streams architecture generation events including:
    - Component creation
    - Design decisions
    - Code generation
    - Validation requests
    - Progress updates
    - Error notifications

    Path parameters:
    - session_id: Generation session ID to subscribe to
    """
    await websocket_endpoint(websocket, session_id)


# Run with: uvicorn src.clarity.api.main:app --reload --port 8000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
