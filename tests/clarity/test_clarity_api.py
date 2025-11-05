"""
Tests for ClarAIty FastAPI Server

Tests all REST endpoints and WebSocket functionality.
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
import tempfile
import shutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.clarity.api.main import app, DB_PATH
from src.clarity.core.database import ClarityDB


@pytest.fixture(scope="module")
def test_db():
    """Create a test database with sample data"""
    # Create temporary database
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_clarity.db"

    db = ClarityDB(str(db_path))

    # Create session
    session_id = db.create_session(
        project_name="Test Project",
        session_type="documentation",
        mode="document"
    )

    # Add components
    db.add_component(
        component_id="TEST1",
        name="TestComponent1",
        type_="core-class",
        layer="core",
        purpose="Test component 1",
        business_value="Test value",
        design_rationale="Test rationale",
        responsibilities=["test1", "test2"],
        status="completed"
    )

    db.add_component(
        component_id="TEST2",
        name="TestComponent2",
        type_="orchestrator",
        layer="workflow",
        purpose="Test component 2",
        business_value="Test value 2",
        design_rationale="Test rationale 2",
        responsibilities=["test3"],
        status="planned"
    )

    # Add artifacts
    db.add_artifact(
        component_id="TEST1",
        type_="file",
        name="test1.py",
        file_path="src/test1.py",
        description="Test file"
    )

    db.add_artifact(
        component_id="TEST1",
        type_="class",
        name="TestComponent1",
        file_path="src/test1.py",
        line_start=10,
        line_end=50,
        description="Test class"
    )

    # Add decisions
    db.add_decision(
        component_id="TEST1",
        decision_type="architecture",
        question="How to structure test component?",
        chosen_solution="Use class-based design",
        rationale="Better encapsulation",
        alternatives_considered=["Function-based", "Module-based"],
        trade_offs="More boilerplate"
    )

    # Add relationships
    db.add_component_relationship(
        source_id="TEST1",
        target_id="TEST2",
        relationship_type="depends-on",
        description="Test1 depends on Test2"
    )

    db.close()

    # Override DB_PATH for tests
    import src.clarity.api.main as main_module
    original_db_path = main_module.DB_PATH
    main_module.DB_PATH = db_path

    yield {"db_path": db_path, "session_id": session_id}

    # Cleanup
    main_module.DB_PATH = original_db_path
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(test_db):
    """Create test client"""
    return TestClient(app)


# Health Check Tests
class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_root(self, client):
        """Test root endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ClarAIty API"

    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data
        assert "statistics" in data


# Component Tests
class TestComponentEndpoints:
    """Test component-related endpoints"""

    def test_get_all_components(self, client):
        """Test getting all components"""
        response = client.get("/components")
        assert response.status_code == 200
        components = response.json()
        assert len(components) == 2
        assert components[0]["id"] in ["TEST1", "TEST2"]

    def test_get_components_with_layer_filter(self, client):
        """Test filtering components by layer"""
        response = client.get("/components?layer=core")
        assert response.status_code == 200
        components = response.json()
        assert len(components) == 1
        assert components[0]["layer"] == "core"

    def test_get_components_with_type_filter(self, client):
        """Test filtering components by type"""
        response = client.get("/components?type=orchestrator")
        assert response.status_code == 200
        components = response.json()
        assert len(components) == 1
        assert components[0]["type"] == "orchestrator"

    def test_get_components_with_status_filter(self, client):
        """Test filtering components by status"""
        response = client.get("/components?status=completed")
        assert response.status_code == 200
        components = response.json()
        assert len(components) == 1
        assert components[0]["status"] == "completed"

    def test_get_components_with_limit(self, client):
        """Test limiting number of components"""
        response = client.get("/components?limit=1")
        assert response.status_code == 200
        components = response.json()
        assert len(components) == 1

    def test_search_components(self, client):
        """Test searching components"""
        response = client.get("/components/search?q=TestComponent1")
        assert response.status_code == 200
        components = response.json()
        assert len(components) >= 1
        assert any("TestComponent1" in c["name"] for c in components)

    def test_search_components_missing_query(self, client):
        """Test search without query parameter"""
        response = client.get("/components/search")
        assert response.status_code == 422  # Validation error

    def test_get_component_details(self, client):
        """Test getting component details"""
        response = client.get("/components/TEST1")
        assert response.status_code == 200
        component = response.json()
        assert component["id"] == "TEST1"
        assert component["name"] == "TestComponent1"
        assert "artifacts" in component
        assert "decisions" in component
        assert "relationships" in component
        assert len(component["artifacts"]) == 2
        assert len(component["decisions"]) == 1

    def test_get_nonexistent_component(self, client):
        """Test getting nonexistent component"""
        response = client.get("/components/NONEXISTENT")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_component_relationships(self, client):
        """Test getting component relationships"""
        response = client.get("/components/TEST1/relationships")
        assert response.status_code == 200
        data = response.json()
        assert "outgoing" in data
        assert "incoming" in data
        assert len(data["outgoing"]) == 1

    def test_get_relationships_nonexistent_component(self, client):
        """Test getting relationships for nonexistent component"""
        response = client.get("/components/NONEXISTENT/relationships")
        assert response.status_code == 404

    def test_get_component_decisions(self, client):
        """Test getting component design decisions"""
        response = client.get("/components/TEST1/decisions")
        assert response.status_code == 200
        decisions = response.json()
        assert len(decisions) == 1
        assert decisions[0]["component_id"] == "TEST1"
        assert decisions[0]["decision_type"] == "architecture"

    def test_get_decisions_nonexistent_component(self, client):
        """Test getting decisions for nonexistent component"""
        response = client.get("/components/NONEXISTENT/decisions")
        assert response.status_code == 404


# Architecture Tests
class TestArchitectureEndpoints:
    """Test architecture summary endpoints"""

    def test_get_architecture_summary(self, client):
        """Test getting architecture summary"""
        response = client.get("/architecture")
        assert response.status_code == 200
        data = response.json()
        assert "project_name" in data
        assert "total_components" in data
        assert "total_artifacts" in data
        assert "layers" in data
        assert data["total_components"] == 2


# Decision Tests
class TestDecisionEndpoints:
    """Test design decision endpoints"""

    def test_get_all_decisions(self, client):
        """Test getting all decisions"""
        response = client.get("/decisions")
        assert response.status_code == 200
        decisions = response.json()
        assert len(decisions) >= 1

    def test_get_decisions_with_type_filter(self, client):
        """Test filtering decisions by type"""
        response = client.get("/decisions?decision_type=architecture")
        assert response.status_code == 200
        decisions = response.json()
        assert all(d["decision_type"] == "architecture" for d in decisions)

    def test_get_decisions_with_limit(self, client):
        """Test limiting number of decisions"""
        response = client.get("/decisions?limit=1")
        assert response.status_code == 200
        decisions = response.json()
        assert len(decisions) <= 1


# Relationship Tests
class TestRelationshipEndpoints:
    """Test relationship endpoints"""

    def test_get_all_relationships(self, client):
        """Test getting all relationships"""
        response = client.get("/relationships")
        assert response.status_code == 200
        relationships = response.json()
        assert len(relationships) >= 1

    def test_get_relationships_with_type_filter(self, client):
        """Test filtering relationships by type"""
        response = client.get("/relationships?relationship_type=depends-on")
        assert response.status_code == 200
        relationships = response.json()
        assert all(r["relationship_type"] == "depends-on" for r in relationships)


# Validation Tests
class TestValidationEndpoints:
    """Test validation endpoints"""

    def test_record_validation(self, client, test_db):
        """Test recording user validation"""
        validation_data = {
            "session_id": test_db["session_id"],
            "artifact_type": "component",
            "artifact_id": "TEST1",
            "ai_proposal": "Proposed design",
            "user_response": "approved"
        }
        response = client.post("/validate", json=validation_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "validation_id" in data


# Statistics Tests
class TestStatisticsEndpoints:
    """Test statistics endpoints"""

    def test_get_statistics(self, client):
        """Test getting statistics"""
        response = client.get("/statistics")
        assert response.status_code == 200
        stats = response.json()
        assert "total_components" in stats
        assert "total_artifacts" in stats
        assert "total_relationships" in stats
        assert stats["total_components"] == 2


# WebSocket Tests
class TestWebSocketEndpoints:
    """Test WebSocket endpoints"""

    def test_websocket_connection(self, client):
        """Test WebSocket connection"""
        with client.websocket_connect("/ws/generate/test-session") as websocket:
            # Should receive connection confirmation
            data = websocket.receive_json()
            assert data["type"] == "connected"
            assert data["session_id"] == "test-session"

    def test_websocket_ping_pong(self, client):
        """Test WebSocket ping/pong"""
        with client.websocket_connect("/ws/generate/test-session") as websocket:
            # Receive connection confirmation
            websocket.receive_json()

            # Send ping
            websocket.send_json({"type": "ping"})

            # Should receive pong
            data = websocket.receive_json()
            assert data["type"] == "pong"

    def test_websocket_validation_response(self, client):
        """Test sending validation response via WebSocket"""
        with client.websocket_connect("/ws/generate/test-session") as websocket:
            # Receive connection confirmation
            websocket.receive_json()

            # Send validation response
            websocket.send_json({
                "type": "validation_response",
                "artifact_id": "TEST1",
                "response": "approved"
            })

            # Should receive acknowledgment
            data = websocket.receive_json()
            assert data["type"] == "validation_received"

    def test_websocket_unknown_message_type(self, client):
        """Test sending unknown message type"""
        with client.websocket_connect("/ws/generate/test-session") as websocket:
            # Receive connection confirmation
            websocket.receive_json()

            # Send unknown message type
            websocket.send_json({"type": "unknown"})

            # Should receive error
            data = websocket.receive_json()
            assert data["type"] == "error"
            assert "Unknown message type" in data["message"]


# Error Handling Tests
class TestErrorHandling:
    """Test error handling"""

    def test_database_not_found(self):
        """Test error when database doesn't exist"""
        # Create client with non-existent database
        import src.clarity.api.main as main_module
        original_db_path = main_module.DB_PATH
        main_module.DB_PATH = Path("/nonexistent/path/db.db")

        client = TestClient(app)
        response = client.get("/components")
        assert response.status_code == 503
        assert "Database not found" in response.json()["detail"]

        # Restore
        main_module.DB_PATH = original_db_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
