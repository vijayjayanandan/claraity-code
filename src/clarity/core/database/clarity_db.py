"""
ClarAIty Database - Core database operations for ClarAIty system

Provides CRUD operations for components, design decisions, code artifacts,
relationships, sessions, and validations.
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from contextlib import contextmanager


class ClarityDBError(Exception):
    """Base exception for ClarityDB errors"""
    pass


class ClarityDB:
    """
    ClarAIty Database Manager

    Manages SQLite database for storing architectural components, design decisions,
    code artifacts, and relationships. Supports both code generation and documentation modes.

    Attributes:
        db_path: Path to SQLite database file
        conn: Database connection (lazy-loaded)
    """

    def __init__(self, db_path: str = ".clarity/clarity.db"):
        """
        Initialize ClarityDB

        Args:
            db_path: Path to SQLite database (default: .clarity/clarity.db)
        """
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database schema
        self._initialize_schema()

    @contextmanager
    def _get_cursor(self):
        """Context manager for database cursor"""
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row
            # Enable foreign key constraints
            self.conn.execute("PRAGMA foreign_keys = ON")

        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise ClarityDBError(f"Database error: {e}") from e
        finally:
            cursor.close()

    def _initialize_schema(self):
        """Initialize database schema from schema.sql and v2 extensions"""
        # Load base schema
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            raise ClarityDBError(f"Schema file not found: {schema_path}")

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        with self._get_cursor() as cursor:
            cursor.executescript(schema_sql)

        # Load v2 flows extension
        schema_v2_path = Path(__file__).parent / "schema_v2_flows.sql"
        if schema_v2_path.exists():
            with open(schema_v2_path, 'r') as f:
                schema_v2_sql = f.read()
            with self._get_cursor() as cursor:
                cursor.executescript(schema_v2_sql)

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    # =============================================================================
    # SESSION MANAGEMENT
    # =============================================================================

    def create_session(
        self,
        project_name: str,
        session_type: str = "documentation",
        mode: str = "document",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new generation/documentation session

        Args:
            project_name: Name of the project
            session_type: Type of session (generation|documentation|analysis)
            mode: Mode (document|generate)
            metadata: Optional session metadata

        Returns:
            Session ID (UUID)
        """
        session_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata) if metadata else None

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO generation_sessions (id, project_name, session_type, mode, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, project_name, session_type, mode, metadata_json))

        return session_id

    def complete_session(self, session_id: str, status: str = "completed") -> None:
        """
        Mark a session as complete

        Args:
            session_id: Session ID
            status: Final status (completed|failed)
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                UPDATE generation_sessions
                SET completed_at = CURRENT_TIMESTAMP, status = ?
                WHERE id = ?
            """, (status, session_id))

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session details

        Args:
            session_id: Session ID

        Returns:
            Session dict or None if not found
        """
        with self._get_cursor() as cursor:
            cursor.execute("SELECT * FROM generation_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # =============================================================================
    # COMPONENT MANAGEMENT
    # =============================================================================

    def add_component(
        self,
        component_id: str,
        name: str,
        type_: str,
        layer: str,
        purpose: Optional[str] = None,
        business_value: Optional[str] = None,
        design_rationale: Optional[str] = None,
        responsibilities: Optional[List[str]] = None,
        status: str = "planned"
    ) -> str:
        """
        Add a new component to the database

        Args:
            component_id: Unique component identifier (e.g., "CODING_AGENT")
            name: Human-readable name
            type_: Component type (microservice|core-class|orchestrator|etc.)
            layer: Architectural layer (core|memory|rag|workflow|tools|etc.)
            purpose: What this component does
            business_value: Why this component exists
            design_rationale: Why designed this way
            responsibilities: List of responsibilities
            status: Component status (planned|in_progress|completed)

        Returns:
            Component ID
        """
        responsibilities_json = json.dumps(responsibilities) if responsibilities else None

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO components (
                    id, name, type, layer, purpose, business_value,
                    design_rationale, responsibilities, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                component_id, name, type_, layer, purpose, business_value,
                design_rationale, responsibilities_json, status
            ))

        return component_id

    def update_component_status(self, component_id: str, status: str) -> None:
        """
        Update component status

        Args:
            component_id: Component ID
            status: New status (planned|in_progress|completed|verified)
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                UPDATE components
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (status, component_id))

    def get_component(self, component_id: str) -> Optional[Dict[str, Any]]:
        """
        Get component details

        Args:
            component_id: Component ID

        Returns:
            Component dict or None if not found
        """
        with self._get_cursor() as cursor:
            cursor.execute("SELECT * FROM components WHERE id = ?", (component_id,))
            row = cursor.fetchone()

            if not row:
                return None

            component = dict(row)

            # Parse JSON fields
            if component.get('responsibilities'):
                component['responsibilities'] = json.loads(component['responsibilities'])

            return component

    def get_all_components(self, layer: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all components, optionally filtered by layer

        Args:
            layer: Optional layer filter

        Returns:
            List of component dicts
        """
        with self._get_cursor() as cursor:
            if layer:
                cursor.execute("SELECT * FROM components WHERE layer = ? ORDER BY name", (layer,))
            else:
                cursor.execute("SELECT * FROM components ORDER BY layer, name")

            components = []
            for row in cursor.fetchall():
                component = dict(row)
                if component.get('responsibilities'):
                    component['responsibilities'] = json.loads(component['responsibilities'])
                components.append(component)

            return components

    def delete_component(self, component_id: str) -> None:
        """
        Delete a component (cascade deletes artifacts, decisions, relationships)

        Args:
            component_id: Component ID
        """
        with self._get_cursor() as cursor:
            cursor.execute("DELETE FROM components WHERE id = ?", (component_id,))

    # =============================================================================
    # DESIGN DECISIONS
    # =============================================================================

    def add_decision(
        self,
        component_id: str,
        decision_type: str,
        question: str,
        chosen_solution: str,
        rationale: str,
        alternatives_considered: Optional[List[str]] = None,
        trade_offs: Optional[str] = None,
        decided_by: str = "AI",
        confidence: float = 1.0
    ) -> str:
        """
        Add a design decision

        Args:
            component_id: Component this decision applies to
            decision_type: Type (architecture|implementation|technology|pattern)
            question: The question/problem being addressed
            chosen_solution: The solution that was chosen
            rationale: Why this solution was chosen
            alternatives_considered: List of alternatives considered
            trade_offs: Trade-offs of the chosen solution
            decided_by: Who made the decision (AI|Human|Collaborative)
            confidence: Confidence level (0.0-1.0)

        Returns:
            Decision ID
        """
        decision_id = str(uuid.uuid4())
        alternatives_json = json.dumps(alternatives_considered) if alternatives_considered else None

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO design_decisions (
                    id, component_id, decision_type, question, chosen_solution,
                    rationale, alternatives_considered, trade_offs, decided_by, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision_id, component_id, decision_type, question, chosen_solution,
                rationale, alternatives_json, trade_offs, decided_by, confidence
            ))

        return decision_id

    def get_component_decisions(self, component_id: str) -> List[Dict[str, Any]]:
        """
        Get all design decisions for a component

        Args:
            component_id: Component ID

        Returns:
            List of decision dicts
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM design_decisions
                WHERE component_id = ?
                ORDER BY created_at
            """, (component_id,))

            decisions = []
            for row in cursor.fetchall():
                decision = dict(row)
                if decision.get('alternatives_considered'):
                    decision['alternatives_considered'] = json.loads(decision['alternatives_considered'])
                decisions.append(decision)

            return decisions

    def get_all_decisions(self) -> List[Dict[str, Any]]:
        """
        Get all design decisions

        Returns:
            List of decision dicts
        """
        with self._get_cursor() as cursor:
            cursor.execute("SELECT * FROM design_decisions ORDER BY created_at")

            decisions = []
            for row in cursor.fetchall():
                decision = dict(row)
                if decision.get('alternatives_considered'):
                    decision['alternatives_considered'] = json.loads(decision['alternatives_considered'])
                decisions.append(decision)

            return decisions

    # =============================================================================
    # CODE ARTIFACTS
    # =============================================================================

    def add_artifact(
        self,
        component_id: str,
        type_: str,
        name: str,
        file_path: str,
        line_start: Optional[int] = None,
        line_end: Optional[int] = None,
        description: Optional[str] = None,
        language: str = "python"
    ) -> str:
        """
        Add a code artifact

        Args:
            component_id: Component this artifact belongs to
            type_: Artifact type (file|class|function|method|module)
            name: Name of the artifact
            file_path: Relative path to the file
            line_start: Starting line number
            line_end: Ending line number
            description: Brief description
            language: Programming language

        Returns:
            Artifact ID
        """
        artifact_id = str(uuid.uuid4())

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO code_artifacts (
                    id, component_id, type, name, file_path,
                    line_start, line_end, description, language
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                artifact_id, component_id, type_, name, file_path,
                line_start, line_end, description, language
            ))

        return artifact_id

    def get_component_artifacts(self, component_id: str) -> List[Dict[str, Any]]:
        """
        Get all code artifacts for a component

        Args:
            component_id: Component ID

        Returns:
            List of artifact dicts
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM code_artifacts
                WHERE component_id = ?
                ORDER BY file_path, line_start
            """, (component_id,))

            return [dict(row) for row in cursor.fetchall()]

    def get_artifacts_by_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Get all artifacts in a specific file

        Args:
            file_path: File path

        Returns:
            List of artifact dicts
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM code_artifacts
                WHERE file_path = ?
                ORDER BY line_start
            """, (file_path,))

            return [dict(row) for row in cursor.fetchall()]

    # =============================================================================
    # COMPONENT RELATIONSHIPS
    # =============================================================================

    def add_component_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        description: Optional[str] = None,
        criticality: str = "medium",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add a relationship between two components

        Args:
            source_id: Source component ID
            target_id: Target component ID
            relationship_type: Type (calls|depends-on|triggers|uses|extends|implements)
            description: Description of the relationship
            criticality: Criticality level (low|medium|high)
            metadata: Optional metadata

        Returns:
            Relationship ID
        """
        relationship_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata) if metadata else None

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO component_relationships (
                    id, source_id, target_id, relationship_type,
                    description, criticality, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                relationship_id, source_id, target_id, relationship_type,
                description, criticality, metadata_json
            ))

        return relationship_id

    def get_component_relationships(self, component_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all relationships for a component (both incoming and outgoing)

        Args:
            component_id: Component ID

        Returns:
            Dict with 'outgoing' and 'incoming' lists
        """
        with self._get_cursor() as cursor:
            # Outgoing relationships
            cursor.execute("""
                SELECT cr.*, c.name as target_name
                FROM component_relationships cr
                JOIN components c ON cr.target_id = c.id
                WHERE cr.source_id = ?
                ORDER BY cr.relationship_type
            """, (component_id,))
            outgoing = [dict(row) for row in cursor.fetchall()]

            # Incoming relationships
            cursor.execute("""
                SELECT cr.*, c.name as source_name
                FROM component_relationships cr
                JOIN components c ON cr.source_id = c.id
                WHERE cr.target_id = ?
                ORDER BY cr.relationship_type
            """, (component_id,))
            incoming = [dict(row) for row in cursor.fetchall()]

            return {
                'outgoing': outgoing,
                'incoming': incoming
            }

    def get_all_relationships(self) -> List[Dict[str, Any]]:
        """
        Get all component relationships

        Returns:
            List of relationship dicts
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                SELECT cr.*,
                       c1.name as source_name,
                       c2.name as target_name
                FROM component_relationships cr
                JOIN components c1 ON cr.source_id = c1.id
                JOIN components c2 ON cr.target_id = c2.id
                ORDER BY cr.relationship_type, c1.name
            """)

            return [dict(row) for row in cursor.fetchall()]

    # =============================================================================
    # VALIDATION
    # =============================================================================

    def add_validation(
        self,
        session_id: str,
        artifact_type: str,
        artifact_id: str,
        ai_proposal: str,
        user_response: str,
        user_correction: Optional[str] = None
    ) -> str:
        """
        Record user validation

        Args:
            session_id: Session ID
            artifact_type: Type (architecture|component|code|decision)
            artifact_id: ID of artifact being validated
            ai_proposal: What the AI proposed
            user_response: User response (approved|rejected|modified)
            user_correction: If modified, what changes were made

        Returns:
            Validation ID
        """
        validation_id = str(uuid.uuid4())

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO user_validations (
                    id, session_id, artifact_type, artifact_id,
                    ai_proposal, user_response, user_correction
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                validation_id, session_id, artifact_type, artifact_id,
                ai_proposal, user_response, user_correction
            ))

        return validation_id

    # =============================================================================
    # QUERIES
    # =============================================================================

    def get_architecture_summary(self) -> Dict[str, Any]:
        """
        Get architecture summary (components by layer)

        Returns:
            Dict with layer statistics
        """
        with self._get_cursor() as cursor:
            cursor.execute("SELECT * FROM architecture_summary")
            layers = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) as total FROM components")
            total = cursor.fetchone()['total']

            return {
                'total_components': total,
                'layers': layers
            }

    def get_component_details_full(self, component_id: str) -> Optional[Dict[str, Any]]:
        """
        Get complete component details with relationships, decisions, and artifacts

        Args:
            component_id: Component ID

        Returns:
            Complete component dict or None
        """
        component = self.get_component(component_id)
        if not component:
            return None

        component['relationships'] = self.get_component_relationships(component_id)
        component['decisions'] = self.get_component_decisions(component_id)
        component['artifacts'] = self.get_component_artifacts(component_id)

        return component

    def search_components(self, query: str) -> List[Dict[str, Any]]:
        """
        Search components by name, purpose, or business value

        Args:
            query: Search query

        Returns:
            List of matching components
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM components
                WHERE name LIKE ? OR purpose LIKE ? OR business_value LIKE ?
                ORDER BY name
            """, (f"%{query}%", f"%{query}%", f"%{query}%"))

            components = []
            for row in cursor.fetchall():
                component = dict(row)
                # Parse JSON fields
                if component.get('responsibilities'):
                    component['responsibilities'] = json.loads(component['responsibilities'])
                components.append(component)
            return components

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get overall database statistics

        Returns:
            Dict with counts and statistics
        """
        with self._get_cursor() as cursor:
            stats = {}

            cursor.execute("SELECT COUNT(*) as count FROM components")
            stats['total_components'] = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM design_decisions")
            stats['total_decisions'] = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM code_artifacts")
            stats['total_artifacts'] = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM component_relationships")
            stats['total_relationships'] = cursor.fetchone()['count']

            cursor.execute("SELECT COUNT(*) as count FROM generation_sessions")
            stats['total_sessions'] = cursor.fetchone()['count']

            return stats

    # =============================================================================
    # EXECUTION FLOW MANAGEMENT (v2)
    # =============================================================================

    def add_flow(
        self,
        flow_id: str,
        name: str,
        trigger: str,
        flow_type: str = "user-facing",
        description: Optional[str] = None,
        complexity: str = "medium",
        is_primary: bool = False
    ) -> str:
        """
        Add a new execution flow

        Args:
            flow_id: Unique flow identifier (e.g., "WORKFLOW_EXECUTION_FLOW")
            name: Human-readable name
            trigger: What triggers this flow
            flow_type: Type (user-facing|internal|background)
            description: Flow description
            complexity: Complexity level (simple|medium|complex)
            is_primary: Is this a primary flow?

        Returns:
            Flow ID
        """
        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO execution_flows
                (id, name, description, trigger, flow_type, complexity, is_primary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (flow_id, name, description, trigger, flow_type, complexity, int(is_primary)))

        return flow_id

    def add_flow_step(
        self,
        step_id: str,
        flow_id: str,
        sequence: int,
        step_type: str,
        title: str,
        level: int = 0,
        parent_step_id: Optional[str] = None,
        description: Optional[str] = None,
        component_id: Optional[str] = None,
        file_path: Optional[str] = None,
        line_start: Optional[int] = None,
        line_end: Optional[int] = None,
        function_name: Optional[str] = None,
        decision_question: Optional[str] = None,
        decision_logic: Optional[str] = None,
        branches: Optional[List[Dict[str, str]]] = None,
        is_critical: bool = False,
        notes: Optional[str] = None
    ) -> str:
        """
        Add a new flow step

        Args:
            step_id: Unique step identifier
            flow_id: Flow this step belongs to
            sequence: Order within parent
            step_type: Type (normal|decision|loop|parallel|end)
            title: Short step title
            level: Hierarchy level (0=top, 1=substep)
            parent_step_id: Parent step (for substeps)
            description: Detailed description
            component_id: Component involved
            file_path: File where step happens
            line_start: Starting line number
            line_end: Ending line number
            function_name: Function/method name
            decision_question: Question for decision steps
            decision_logic: How decision is made
            branches: Branch information for decision steps
            is_critical: Is this critical?
            notes: Additional notes

        Returns:
            Step ID
        """
        branches_json = json.dumps(branches) if branches else None

        with self._get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO flow_steps
                (id, flow_id, parent_step_id, sequence, level, step_type, title, description,
                 component_id, file_path, line_start, line_end, function_name,
                 decision_question, decision_logic, branches, is_critical, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (step_id, flow_id, parent_step_id, sequence, level, step_type, title, description,
                  component_id, file_path, line_start, line_end, function_name,
                  decision_question, decision_logic, branches_json, int(is_critical), notes))

        return step_id

    def get_flow(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get flow details

        Args:
            flow_id: Flow ID

        Returns:
            Flow dict or None
        """
        with self._get_cursor() as cursor:
            cursor.execute("SELECT * FROM execution_flows WHERE id = ?", (flow_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_flows(self) -> List[Dict[str, Any]]:
        """
        Get all execution flows

        Returns:
            List of flow dicts
        """
        with self._get_cursor() as cursor:
            cursor.execute("SELECT * FROM execution_flows ORDER BY is_primary DESC, name")
            return [dict(row) for row in cursor.fetchall()]

    def get_flow_steps(self, flow_id: str, parent_step_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get steps for a flow, optionally filtered by parent

        Args:
            flow_id: Flow ID
            parent_step_id: Parent step ID (None for top-level steps)

        Returns:
            List of step dicts ordered by sequence
        """
        with self._get_cursor() as cursor:
            if parent_step_id is None:
                cursor.execute("""
                    SELECT * FROM step_details
                    WHERE flow_id = ? AND parent_step_id IS NULL
                    ORDER BY sequence
                """, (flow_id,))
            else:
                cursor.execute("""
                    SELECT * FROM step_details
                    WHERE flow_id = ? AND parent_step_id = ?
                    ORDER BY sequence
                """, (flow_id, parent_step_id))

            steps = [dict(row) for row in cursor.fetchall()]

            # Parse branches JSON
            for step in steps:
                if step.get('branches'):
                    step['branches'] = json.loads(step['branches'])

            return steps

    def get_flow_with_steps(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get complete flow with all steps (hierarchical)

        Args:
            flow_id: Flow ID

        Returns:
            Flow dict with nested steps
        """
        flow = self.get_flow(flow_id)
        if not flow:
            return None

        # Get all steps for this flow
        with self._get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM step_details
                WHERE flow_id = ?
                ORDER BY level, sequence
            """, (flow_id,))
            all_steps = [dict(row) for row in cursor.fetchall()]

        # Parse branches JSON
        for step in all_steps:
            if step.get('branches'):
                step['branches'] = json.loads(step['branches'])

        # Build hierarchical structure
        steps_by_id = {step['id']: {**step, 'substeps': []} for step in all_steps}

        # Organize into hierarchy
        top_level_steps = []
        for step in all_steps:
            if step['parent_step_id']:
                parent = steps_by_id.get(step['parent_step_id'])
                if parent:
                    parent['substeps'].append(steps_by_id[step['id']])
            else:
                top_level_steps.append(steps_by_id[step['id']])

        flow['steps'] = top_level_steps
        return flow
