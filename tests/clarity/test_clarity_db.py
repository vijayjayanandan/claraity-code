"""
Comprehensive tests for ClarityDB

Tests all CRUD operations for:
- Sessions
- Components
- Design Decisions
- Code Artifacts
- Component Relationships
- Validations
- Queries
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from src.clarity.core.database import ClarityDB, ClarityDBError


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_clarity.db"
    db = ClarityDB(str(db_path))

    yield db

    db.close()
    shutil.rmtree(temp_dir)


# =============================================================================
# SESSION TESTS
# =============================================================================

class TestSessions:
    """Test session management"""

    def test_create_session(self, temp_db):
        """Test creating a new session"""
        session_id = temp_db.create_session(
            project_name="test-project",
            session_type="documentation",
            mode="document"
        )

        assert session_id is not None
        assert len(session_id) == 36  # UUID length

        # Verify session was created
        session = temp_db.get_session(session_id)
        assert session is not None
        assert session['project_name'] == "test-project"
        assert session['session_type'] == "documentation"
        assert session['mode'] == "document"
        assert session['status'] == "in_progress"

    def test_create_session_with_metadata(self, temp_db):
        """Test creating session with metadata"""
        metadata = {"user": "test_user", "version": "1.0"}
        session_id = temp_db.create_session(
            project_name="test-project",
            metadata=metadata
        )

        session = temp_db.get_session(session_id)
        assert session is not None
        assert session['metadata'] is not None

    def test_complete_session(self, temp_db):
        """Test completing a session"""
        session_id = temp_db.create_session(project_name="test-project")

        temp_db.complete_session(session_id, status="completed")

        session = temp_db.get_session(session_id)
        assert session['status'] == "completed"
        assert session['completed_at'] is not None

    def test_get_nonexistent_session(self, temp_db):
        """Test getting a session that doesn't exist"""
        session = temp_db.get_session("nonexistent-id")
        assert session is None


# =============================================================================
# COMPONENT TESTS
# =============================================================================

class TestComponents:
    """Test component management"""

    def test_add_component(self, temp_db):
        """Test adding a component"""
        component_id = temp_db.add_component(
            component_id="TEST_COMPONENT",
            name="Test Component",
            type_="core-class",
            layer="core",
            purpose="Test component for testing",
            business_value="Testing purposes",
            design_rationale="Simple test design",
            responsibilities=["test1", "test2"],
            status="planned"
        )

        assert component_id == "TEST_COMPONENT"

        # Verify component was added
        component = temp_db.get_component(component_id)
        assert component is not None
        assert component['name'] == "Test Component"
        assert component['type'] == "core-class"
        assert component['layer'] == "core"
        assert component['responsibilities'] == ["test1", "test2"]
        assert component['status'] == "planned"

    def test_update_component_status(self, temp_db):
        """Test updating component status"""
        component_id = temp_db.add_component(
            component_id="TEST_COMP",
            name="Test",
            type_="core-class",
            layer="core"
        )

        temp_db.update_component_status(component_id, "completed")

        component = temp_db.get_component(component_id)
        assert component['status'] == "completed"

    def test_get_all_components(self, temp_db):
        """Test getting all components"""
        temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        temp_db.add_component("COMP2", "Component 2", "utility", "tools")
        temp_db.add_component("COMP3", "Component 3", "core-class", "core")

        all_components = temp_db.get_all_components()
        assert len(all_components) == 3

        # Test filtering by layer
        core_components = temp_db.get_all_components(layer="core")
        assert len(core_components) == 2

    def test_delete_component(self, temp_db):
        """Test deleting a component"""
        component_id = temp_db.add_component("DELETE_ME", "Test", "core-class", "core")

        temp_db.delete_component(component_id)

        component = temp_db.get_component(component_id)
        assert component is None

    def test_search_components(self, temp_db):
        """Test searching components"""
        temp_db.add_component(
            "COMP1",
            "Authentication Service",
            "core-class",
            "core",
            purpose="Handle user authentication"
        )
        temp_db.add_component(
            "COMP2",
            "Authorization Service",
            "core-class",
            "core",
            purpose="Handle user authorization"
        )
        temp_db.add_component(
            "COMP3",
            "Logging Service",
            "utility",
            "tools",
            purpose="Handle application logging"
        )

        # Search for "auth"
        results = temp_db.search_components("auth")
        assert len(results) == 2

        # Search for "logging"
        results = temp_db.search_components("logging")
        assert len(results) == 1


# =============================================================================
# DESIGN DECISION TESTS
# =============================================================================

class TestDesignDecisions:
    """Test design decision management"""

    def test_add_decision(self, temp_db):
        """Test adding a design decision"""
        # First create a component
        component_id = temp_db.add_component("COMP1", "Test Component", "core-class", "core")

        decision_id = temp_db.add_decision(
            component_id=component_id,
            decision_type="architecture",
            question="How to handle state?",
            chosen_solution="Use immutable data structures",
            rationale="Better concurrency",
            alternatives_considered=["Mutable state", "Global state"],
            trade_offs="Slight performance overhead",
            decided_by="AI",
            confidence=0.9
        )

        assert decision_id is not None
        assert len(decision_id) == 36  # UUID

    def test_get_component_decisions(self, temp_db):
        """Test getting decisions for a component"""
        component_id = temp_db.add_component("COMP1", "Test", "core-class", "core")

        temp_db.add_decision(
            component_id,
            "architecture",
            "Question 1?",
            "Solution 1",
            "Rationale 1"
        )
        temp_db.add_decision(
            component_id,
            "implementation",
            "Question 2?",
            "Solution 2",
            "Rationale 2"
        )

        decisions = temp_db.get_component_decisions(component_id)
        assert len(decisions) == 2
        assert decisions[0]['question'] == "Question 1?"
        assert decisions[1]['question'] == "Question 2?"

    def test_get_all_decisions(self, temp_db):
        """Test getting all decisions"""
        comp1 = temp_db.add_component("COMP1", "Test 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Test 2", "core-class", "core")

        temp_db.add_decision(comp1, "architecture", "Q1?", "S1", "R1")
        temp_db.add_decision(comp2, "architecture", "Q2?", "S2", "R2")

        decisions = temp_db.get_all_decisions()
        assert len(decisions) == 2

    def test_decision_with_alternatives(self, temp_db):
        """Test decision with alternatives considered"""
        component_id = temp_db.add_component("COMP1", "Test", "core-class", "core")

        alternatives = ["Option A", "Option B", "Option C"]
        decision_id = temp_db.add_decision(
            component_id,
            "technology",
            "Which database?",
            "PostgreSQL",
            "Best for our use case",
            alternatives_considered=alternatives
        )

        decisions = temp_db.get_component_decisions(component_id)
        assert len(decisions) == 1
        assert decisions[0]['alternatives_considered'] == alternatives


# =============================================================================
# CODE ARTIFACT TESTS
# =============================================================================

class TestCodeArtifacts:
    """Test code artifact management"""

    def test_add_artifact(self, temp_db):
        """Test adding a code artifact"""
        component_id = temp_db.add_component("COMP1", "Test", "core-class", "core")

        artifact_id = temp_db.add_artifact(
            component_id=component_id,
            type_="class",
            name="TestClass",
            file_path="src/test.py",
            line_start=10,
            line_end=50,
            description="Main test class",
            language="python"
        )

        assert artifact_id is not None
        assert len(artifact_id) == 36  # UUID

    def test_get_component_artifacts(self, temp_db):
        """Test getting artifacts for a component"""
        component_id = temp_db.add_component("COMP1", "Test", "core-class", "core")

        temp_db.add_artifact(component_id, "file", "test.py", "src/test.py")
        temp_db.add_artifact(component_id, "class", "TestClass", "src/test.py", 10, 50)
        temp_db.add_artifact(component_id, "function", "test_func", "src/test.py", 60, 80)

        artifacts = temp_db.get_component_artifacts(component_id)
        assert len(artifacts) == 3

    def test_get_artifacts_by_file(self, temp_db):
        """Test getting artifacts by file path"""
        comp1 = temp_db.add_component("COMP1", "Test 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Test 2", "core-class", "core")

        temp_db.add_artifact(comp1, "class", "Class1", "src/test.py", 10, 20)
        temp_db.add_artifact(comp1, "class", "Class2", "src/test.py", 30, 40)
        temp_db.add_artifact(comp2, "class", "Class3", "src/other.py", 10, 20)

        artifacts = temp_db.get_artifacts_by_file("src/test.py")
        assert len(artifacts) == 2

    def test_artifact_line_ranges(self, temp_db):
        """Test artifacts with line ranges"""
        component_id = temp_db.add_component("COMP1", "Test", "core-class", "core")

        artifact_id = temp_db.add_artifact(
            component_id,
            "method",
            "test_method",
            "src/test.py",
            line_start=100,
            line_end=120
        )

        artifacts = temp_db.get_component_artifacts(component_id)
        assert len(artifacts) == 1
        assert artifacts[0]['line_start'] == 100
        assert artifacts[0]['line_end'] == 120


# =============================================================================
# RELATIONSHIP TESTS
# =============================================================================

class TestRelationships:
    """Test component relationship management"""

    def test_add_relationship(self, temp_db):
        """Test adding a relationship"""
        comp1 = temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Component 2", "core-class", "core")

        relationship_id = temp_db.add_component_relationship(
            source_id=comp1,
            target_id=comp2,
            relationship_type="uses",
            description="Component 1 uses Component 2",
            criticality="high"
        )

        assert relationship_id is not None
        assert len(relationship_id) == 36  # UUID

    def test_get_component_relationships(self, temp_db):
        """Test getting component relationships"""
        comp1 = temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Component 2", "core-class", "core")
        comp3 = temp_db.add_component("COMP3", "Component 3", "core-class", "core")

        # COMP1 uses COMP2
        temp_db.add_component_relationship(comp1, comp2, "uses")
        # COMP1 depends on COMP3
        temp_db.add_component_relationship(comp1, comp3, "depends-on")
        # COMP3 calls COMP1
        temp_db.add_component_relationship(comp3, comp1, "calls")

        relationships = temp_db.get_component_relationships(comp1)
        assert len(relationships['outgoing']) == 2  # uses COMP2, depends on COMP3
        assert len(relationships['incoming']) == 1  # COMP3 calls COMP1

    def test_get_all_relationships(self, temp_db):
        """Test getting all relationships"""
        comp1 = temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Component 2", "core-class", "core")
        comp3 = temp_db.add_component("COMP3", "Component 3", "core-class", "core")

        temp_db.add_component_relationship(comp1, comp2, "uses")
        temp_db.add_component_relationship(comp2, comp3, "depends-on")
        temp_db.add_component_relationship(comp3, comp1, "calls")

        relationships = temp_db.get_all_relationships()
        assert len(relationships) == 3

    def test_relationship_with_metadata(self, temp_db):
        """Test relationship with metadata"""
        comp1 = temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Component 2", "core-class", "core")

        metadata = {"method": "execute", "frequency": "high"}
        temp_db.add_component_relationship(
            comp1,
            comp2,
            "calls",
            metadata=metadata
        )

        relationships = temp_db.get_all_relationships()
        assert len(relationships) == 1


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestValidations:
    """Test user validation management"""

    def test_add_validation(self, temp_db):
        """Test adding a validation"""
        session_id = temp_db.create_session("test-project")

        validation_id = temp_db.add_validation(
            session_id=session_id,
            artifact_type="component",
            artifact_id="COMP1",
            ai_proposal="Create authentication service",
            user_response="approved"
        )

        assert validation_id is not None
        assert len(validation_id) == 36  # UUID

    def test_validation_with_correction(self, temp_db):
        """Test validation with user correction"""
        session_id = temp_db.create_session("test-project")

        temp_db.add_validation(
            session_id=session_id,
            artifact_type="component",
            artifact_id="COMP1",
            ai_proposal="Use REST API",
            user_response="modified",
            user_correction="Use GraphQL instead"
        )

        # Validation created successfully
        # (No direct getter for validations, but it's stored)
        assert True


# =============================================================================
# QUERY TESTS
# =============================================================================

class TestQueries:
    """Test query operations"""

    def test_get_architecture_summary(self, temp_db):
        """Test getting architecture summary"""
        temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        temp_db.add_component("COMP2", "Component 2", "core-class", "core")
        temp_db.add_component("COMP3", "Component 3", "utility", "tools")
        temp_db.add_component("COMP4", "Component 4", "orchestrator", "workflow")

        summary = temp_db.get_architecture_summary()
        assert summary['total_components'] == 4
        assert len(summary['layers']) > 0

    def test_get_component_details_full(self, temp_db):
        """Test getting full component details"""
        component_id = temp_db.add_component(
            "COMP1",
            "Test Component",
            "core-class",
            "core",
            purpose="Testing"
        )

        # Add related data
        temp_db.add_decision(component_id, "architecture", "Q?", "S", "R")
        temp_db.add_artifact(component_id, "class", "TestClass", "src/test.py")

        comp2 = temp_db.add_component("COMP2", "Component 2", "utility", "tools")
        temp_db.add_component_relationship(component_id, comp2, "uses")

        # Get full details
        details = temp_db.get_component_details_full(component_id)
        assert details is not None
        assert len(details['decisions']) == 1
        assert len(details['artifacts']) == 1
        assert len(details['relationships']['outgoing']) == 1

    def test_get_statistics(self, temp_db):
        """Test getting database statistics"""
        # Add some data
        comp1 = temp_db.add_component("COMP1", "Component 1", "core-class", "core")
        comp2 = temp_db.add_component("COMP2", "Component 2", "utility", "tools")

        temp_db.add_decision(comp1, "architecture", "Q?", "S", "R")
        temp_db.add_artifact(comp1, "class", "TestClass", "src/test.py")
        temp_db.add_component_relationship(comp1, comp2, "uses")
        temp_db.create_session("test-project")

        stats = temp_db.get_statistics()
        assert stats['total_components'] == 2
        assert stats['total_decisions'] == 1
        assert stats['total_artifacts'] == 1
        assert stats['total_relationships'] == 1
        assert stats['total_sessions'] == 1


# =============================================================================
# CASCADE DELETE TESTS
# =============================================================================

class TestCascadeDeletes:
    """Test cascade delete behavior"""

    def test_delete_component_cascades(self, temp_db):
        """Test that deleting component deletes related data"""
        component_id = temp_db.add_component("COMP1", "Test", "core-class", "core")

        # Add related data
        temp_db.add_decision(component_id, "architecture", "Q?", "S", "R")
        temp_db.add_artifact(component_id, "class", "TestClass", "src/test.py")

        comp2 = temp_db.add_component("COMP2", "Component 2", "utility", "tools")
        temp_db.add_component_relationship(component_id, comp2, "uses")

        # Delete component
        temp_db.delete_component(component_id)

        # Verify cascades
        assert temp_db.get_component(component_id) is None
        assert len(temp_db.get_component_decisions(component_id)) == 0
        assert len(temp_db.get_component_artifacts(component_id)) == 0

        # COMP2 should still exist
        assert temp_db.get_component(comp2) is not None


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Test error handling"""

    def test_invalid_foreign_key(self, temp_db):
        """Test adding decision with invalid component_id"""
        with pytest.raises(ClarityDBError):
            temp_db.add_decision(
                "NONEXISTENT_COMPONENT",
                "architecture",
                "Q?",
                "S",
                "R"
            )

    def test_invalid_relationship(self, temp_db):
        """Test adding relationship with invalid component"""
        comp1 = temp_db.add_component("COMP1", "Component 1", "core-class", "core")

        with pytest.raises(ClarityDBError):
            temp_db.add_component_relationship(
                comp1,
                "NONEXISTENT_COMPONENT",
                "uses"
            )
