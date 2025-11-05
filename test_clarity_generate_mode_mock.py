#!/usr/bin/env python3
"""
Demo: ClarAIty Generate Mode (Mock Version)

Demonstrates the complete Generate Mode flow with a pre-built blueprint.
Shows what happens when ClarAIty generates an architecture plan.
"""

import sys
import logging
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from clarity import (
    Blueprint,
    Component,
    DesignDecision,
    FileAction,
    Relationship,
    ComponentType,
    FileActionType,
    RelationType,
    ApprovalServer,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def create_mock_blueprint() -> Blueprint:
    """Create a mock blueprint for FastAPI server demo."""

    blueprint = Blueprint(
        task_description="Build ClarAIty FastAPI Server and React UI Integration",
        estimated_complexity="medium",
        estimated_time="3-4 hours",
        prerequisites=[
            "FastAPI installed (pip install fastapi uvicorn)",
            "React development environment (Node.js, npm)",
            "Existing ClarAIty core module (generator, blueprint)",
        ],
        risks=[
            "WebSocket connection handling complexity",
            "CORS configuration for React development",
            "Blueprint state management race conditions",
        ],
    )

    # Components
    blueprint.components = [
        Component(
            name="FastAPIServer",
            type=ComponentType.CLASS,
            purpose="Main FastAPI application server for ClarAIty API",
            responsibilities=[
                "Initialize FastAPI app with CORS middleware",
                "Register REST endpoints for blueprint operations",
                "Register WebSocket endpoint for real-time updates",
                "Serve static React build files",
            ],
            file_path="src/clarity/api/server.py",
            layer="api",
            key_methods=["create_app", "start_server", "shutdown"],
            dependencies=["BlueprintStateManager", "WebSocketHandler"],
        ),
        Component(
            name="BlueprintStateManager",
            type=ComponentType.CLASS,
            purpose="Manage blueprint state and lifecycle",
            responsibilities=[
                "Store current blueprint in memory",
                "Handle blueprint creation, approval, rejection",
                "Notify WebSocket clients of state changes",
                "Validate blueprint operations",
            ],
            file_path="src/clarity/api/state.py",
            layer="api",
            key_methods=["set_blueprint", "get_blueprint", "approve", "reject", "notify_clients"],
            dependencies=["Blueprint", "WebSocketHandler"],
        ),
        Component(
            name="WebSocketHandler",
            type=ComponentType.CLASS,
            purpose="Handle WebSocket connections for real-time updates",
            responsibilities=[
                "Manage active WebSocket connections",
                "Broadcast blueprint updates to all clients",
                "Handle client connection/disconnection",
                "Stream blueprint generation progress",
            ],
            file_path="src/clarity/api/websocket.py",
            layer="api",
            key_methods=["connect", "disconnect", "broadcast", "send_to_client"],
            dependencies=[],
        ),
        Component(
            name="BlueprintEndpoints",
            type=ComponentType.MODULE,
            purpose="REST API endpoints for blueprint operations",
            responsibilities=[
                "GET /api/blueprint - Retrieve current blueprint",
                "POST /api/blueprint - Create new blueprint from task",
                "PUT /api/blueprint/approve - Approve current blueprint",
                "PUT /api/blueprint/reject - Reject with feedback",
            ],
            file_path="src/clarity/api/endpoints.py",
            layer="api",
            key_methods=["get_blueprint", "create_blueprint", "approve_blueprint", "reject_blueprint"],
            dependencies=["BlueprintStateManager", "ClarityGenerator"],
        ),
    ]

    # Design Decisions
    blueprint.design_decisions = [
        DesignDecision(
            decision="Use FastAPI for REST API framework",
            rationale="FastAPI provides automatic API documentation, type validation with Pydantic, and excellent WebSocket support. It's fast, modern, and aligns with existing Python stack.",
            alternatives_considered=[
                "Flask - More mature but lacks async support and automatic validation",
                "Django REST Framework - Too heavyweight for this use case",
            ],
            trade_offs="Learning curve for team unfamiliar with FastAPI, but benefits outweigh costs",
            category="technology",
        ),
        DesignDecision(
            decision="In-memory blueprint state (no database for MVP)",
            rationale="For MVP, we only need to track one active blueprint at a time. In-memory storage is simple and fast. Can add persistence later if needed.",
            alternatives_considered=[
                "SQLite database - Adds complexity for MVP",
                "Redis - External dependency overkill for single blueprint",
            ],
            trade_offs="Lose state on server restart, but acceptable for MVP demo",
            category="architecture",
        ),
        DesignDecision(
            decision="WebSocket for real-time updates instead of polling",
            rationale="Blueprint generation can take 10-30 seconds. WebSocket provides instant updates without client polling overhead. Better UX.",
            alternatives_considered=[
                "HTTP polling - Simple but wasteful and delays",
                "Server-Sent Events (SSE) - One-way only, need bidirectional",
            ],
            trade_offs="WebSocket connection management complexity, but FastAPI handles it well",
            category="architecture",
        ),
        DesignDecision(
            decision="Separate React app (not embedded in FastAPI)",
            rationale="Keep frontend and backend decoupled. Allows independent development, hot reload, and easier testing. FastAPI serves static build for production.",
            alternatives_considered=[
                "Jinja2 templates - Less interactive, no modern React benefits",
                "Fully embedded SPA - Harder to develop and debug",
            ],
            trade_offs="Need CORS configuration for development, but cleaner separation",
            category="architecture",
        ),
    ]

    # File Actions
    blueprint.file_actions = [
        FileAction(
            file_path="src/clarity/api/__init__.py",
            action=FileActionType.CREATE,
            description="Create API module __init__ with exports",
            estimated_lines=15,
            components_affected=["FastAPIServer"],
        ),
        FileAction(
            file_path="src/clarity/api/server.py",
            action=FileActionType.CREATE,
            description="Implement FastAPI server with CORS and endpoint registration",
            estimated_lines=120,
            components_affected=["FastAPIServer"],
        ),
        FileAction(
            file_path="src/clarity/api/state.py",
            action=FileActionType.CREATE,
            description="Implement blueprint state manager with in-memory storage",
            estimated_lines=80,
            components_affected=["BlueprintStateManager"],
        ),
        FileAction(
            file_path="src/clarity/api/websocket.py",
            action=FileActionType.MODIFY,
            description="Enhance existing WebSocket handler for blueprint streaming",
            estimated_lines=100,
            components_affected=["WebSocketHandler"],
        ),
        FileAction(
            file_path="src/clarity/api/endpoints.py",
            action=FileActionType.CREATE,
            description="Implement REST endpoints with Pydantic models",
            estimated_lines=150,
            components_affected=["BlueprintEndpoints"],
        ),
        FileAction(
            file_path="src/clarity/ui/react/package.json",
            action=FileActionType.CREATE,
            description="Create React app package.json (placeholder for now)",
            estimated_lines=30,
            components_affected=[],
        ),
    ]

    # Relationships
    blueprint.relationships = [
        Relationship(
            source="FastAPIServer",
            target="BlueprintStateManager",
            type=RelationType.USES,
            description="Server uses state manager for all blueprint operations",
        ),
        Relationship(
            source="FastAPIServer",
            target="WebSocketHandler",
            type=RelationType.USES,
            description="Server registers WebSocket handler for /ws/blueprint endpoint",
        ),
        Relationship(
            source="BlueprintEndpoints",
            target="BlueprintStateManager",
            type=RelationType.CALLS,
            description="Endpoints call state manager methods for CRUD operations",
        ),
        Relationship(
            source="BlueprintEndpoints",
            target="ClarityGenerator",
            type=RelationType.CALLS,
            description="POST /api/blueprint calls generator to create new blueprint",
        ),
        Relationship(
            source="BlueprintStateManager",
            target="WebSocketHandler",
            type=RelationType.CALLS,
            description="State manager broadcasts updates via WebSocket",
        ),
    ]

    return blueprint


def main():
    """Run mock ClarAIty Generate Mode demo."""
    print("=" * 80)
    print("🚀 ClarAIty Generate Mode Demo (Mock)")
    print("=" * 80)
    print()
    print("Task: Build ClarAIty FastAPI Server + React UI")
    print("This demonstrates the COMPLETE Generate Mode workflow!")
    print()
    print("Note: Using pre-built blueprint (no LLM call) for demo purposes.")
    print()

    # Step 1: Show mock blueprint generation
    print("📋 Step 1: Generating architecture blueprint...")
    print()

    blueprint = create_mock_blueprint()

    print("✅ Blueprint generated successfully!")
    print()
    print(blueprint.summary())
    print()

    # Step 2: Show approval UI
    print("🖼️  Step 2: Launching approval UI in browser...")
    print()
    print("The blueprint will open in your browser.")
    print("Review the architecture and click 'Approve' or 'Reject'.")
    print()

    try:
        server = ApprovalServer(blueprint, port=8765)
        decision = server.start_and_wait()

        print()
        print(f"✅ Decision received: {'APPROVED' if decision.approved else 'REJECTED'}")
        print()

        if decision.approved:
            print("🎉 Blueprint approved! In a full implementation, we would now:")
            print("   1. Generate code for each component:")
            print("      - FastAPIServer (120 lines)")
            print("      - BlueprintStateManager (80 lines)")
            print("      - WebSocketHandler (100 lines)")
            print("      - BlueprintEndpoints (150 lines)")
            print("   2. Create/modify files as specified (6 file actions)")
            print("   3. Run tests and verification")
            print()
            print("📊 Estimated implementation:")
            print(f"   - Complexity: {blueprint.estimated_complexity}")
            print(f"   - Time: {blueprint.estimated_time}")
            print(f"   - Components: {len(blueprint.components)}")
            print(f"   - Design Decisions: {len(blueprint.design_decisions)}")
            print()
        else:
            print("❌ Blueprint rejected. In a full implementation, we would:")
            print("   1. Ask user for specific feedback")
            print("   2. Refine the blueprint using ClarityGenerator")
            print("   3. Show updated blueprint for re-approval")
            print()

    except KeyboardInterrupt:
        print()
        print("⚠️  Demo interrupted by user")
        print()
    except Exception as e:
        print(f"❌ Approval UI failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()
    print("=" * 80)
    print("✅ ClarAIty Generate Mode Demo Complete!")
    print("=" * 80)
    print()
    print("What we demonstrated:")
    print("  1. ✅ Task → Architecture Blueprint (with mock data)")
    print("  2. ✅ Blueprint structure:")
    print("      - 4 components with detailed responsibilities")
    print("      - 4 design decisions with rationale & alternatives")
    print("      - 6 file actions (create/modify) with estimates")
    print("      - 5 relationships showing component interactions")
    print("      - Prerequisites and risks identified upfront")
    print("  3. ✅ Interactive approval UI in browser")
    print("  4. ✅ User can approve/reject BEFORE any code is generated")
    print()
    print("🎯 Key Value:")
    print("   The user sees the COMPLETE PLAN before execution begins.")
    print("   No more 'shooting in the dark' during AI code generation!")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
