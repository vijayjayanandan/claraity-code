-- ClarAIty Database Schema
-- Purpose: Store architecture components, design decisions, and code artifacts
-- for real-time visualization during AI code generation and documentation

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- Components: Represents architectural components (classes, modules, services)
CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,                    -- Unique identifier (e.g., "CODING_AGENT", "MEMORY_MANAGER")
    name TEXT NOT NULL,                     -- Human-readable name (e.g., "CodingAgent", "Memory Manager")
    type TEXT NOT NULL,                     -- Component type: microservice|ui-component|database|api|core-class|orchestrator|utility
    layer TEXT NOT NULL,                    -- Architectural layer: frontend|backend|database|infrastructure|core|memory|rag|workflow|tools
    status TEXT DEFAULT 'planned',          -- Status: planned|in_progress|completed|verified
    purpose TEXT,                           -- What this component does
    business_value TEXT,                    -- Why this component exists (business justification)
    design_rationale TEXT,                  -- Why it was designed this way
    responsibilities TEXT,                  -- JSON array of responsibilities
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Design Decisions: Captures architectural and implementation decisions
CREATE TABLE IF NOT EXISTS design_decisions (
    id TEXT PRIMARY KEY,                    -- Unique identifier
    component_id TEXT NOT NULL,             -- Component this decision applies to
    decision_type TEXT NOT NULL,            -- Type: architecture|implementation|technology|pattern
    question TEXT NOT NULL,                 -- The question/problem being addressed
    chosen_solution TEXT NOT NULL,          -- The solution that was chosen
    rationale TEXT NOT NULL,                -- Why this solution was chosen
    alternatives_considered TEXT,           -- JSON array of alternatives that were considered
    trade_offs TEXT,                        -- Trade-offs of the chosen solution
    decided_by TEXT DEFAULT 'AI',           -- Who made the decision: AI|Human|Collaborative
    confidence REAL DEFAULT 1.0,            -- Confidence level (0.0-1.0)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE
);

-- Code Artifacts: Represents actual code files, classes, functions
CREATE TABLE IF NOT EXISTS code_artifacts (
    id TEXT PRIMARY KEY,                    -- Unique identifier
    component_id TEXT NOT NULL,             -- Component this artifact belongs to
    type TEXT NOT NULL,                     -- Type: file|class|function|method|module
    name TEXT NOT NULL,                     -- Name of the artifact (e.g., "CodingAgent", "execute_task")
    file_path TEXT NOT NULL,                -- Relative path to the file
    line_start INTEGER,                     -- Starting line number (optional)
    line_end INTEGER,                       -- Ending line number (optional)
    description TEXT,                       -- Brief description of what this artifact does
    language TEXT DEFAULT 'python',         -- Programming language
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE
);

-- Component Relationships: Defines how components interact
CREATE TABLE IF NOT EXISTS component_relationships (
    id TEXT PRIMARY KEY,                    -- Unique identifier
    source_id TEXT NOT NULL,                -- Source component
    target_id TEXT NOT NULL,                -- Target component
    relationship_type TEXT NOT NULL,        -- Type: calls|depends-on|triggers|uses|extends|implements
    description TEXT,                       -- Description of the relationship
    criticality TEXT DEFAULT 'medium',      -- Criticality: low|medium|high
    metadata TEXT,                          -- JSON object for additional data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES components(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES components(id) ON DELETE CASCADE
);

-- Generation Sessions: Tracks code generation or analysis sessions
CREATE TABLE IF NOT EXISTS generation_sessions (
    id TEXT PRIMARY KEY,                    -- Unique session identifier (UUID)
    project_name TEXT NOT NULL,             -- Name of the project
    session_type TEXT NOT NULL,             -- Type: generation|documentation|analysis
    mode TEXT DEFAULT 'document',           -- Mode: document|generate
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'in_progress',      -- Status: in_progress|completed|failed
    metadata TEXT                           -- JSON object for session-specific data
);

-- User Validations: Records user approvals/corrections during generation
CREATE TABLE IF NOT EXISTS user_validations (
    id TEXT PRIMARY KEY,                    -- Unique identifier
    session_id TEXT NOT NULL,               -- Session this validation belongs to
    artifact_type TEXT NOT NULL,            -- What was validated: architecture|component|code|decision
    artifact_id TEXT NOT NULL,              -- ID of the artifact being validated
    ai_proposal TEXT NOT NULL,              -- What the AI proposed
    user_response TEXT NOT NULL,            -- User response: approved|rejected|modified
    user_correction TEXT,                   -- If modified, what changes were made
    validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES generation_sessions(id) ON DELETE CASCADE
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_components_layer ON components(layer);
CREATE INDEX IF NOT EXISTS idx_components_type ON components(type);
CREATE INDEX IF NOT EXISTS idx_components_status ON components(status);

CREATE INDEX IF NOT EXISTS idx_decisions_component ON design_decisions(component_id);
CREATE INDEX IF NOT EXISTS idx_decisions_type ON design_decisions(decision_type);

CREATE INDEX IF NOT EXISTS idx_artifacts_component ON code_artifacts(component_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_file ON code_artifacts(file_path);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON code_artifacts(type);

CREATE INDEX IF NOT EXISTS idx_relationships_source ON component_relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON component_relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON component_relationships(relationship_type);

CREATE INDEX IF NOT EXISTS idx_sessions_status ON generation_sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_type ON generation_sessions(session_type);

CREATE INDEX IF NOT EXISTS idx_validations_session ON user_validations(session_id);
CREATE INDEX IF NOT EXISTS idx_validations_artifact ON user_validations(artifact_id);

-- =============================================================================
-- VIEWS FOR COMMON QUERIES
-- =============================================================================

-- Architecture Summary: Quick overview of all components by layer
CREATE VIEW IF NOT EXISTS architecture_summary AS
SELECT
    layer,
    COUNT(*) as component_count,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
    COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress_count,
    COUNT(CASE WHEN status = 'planned' THEN 1 END) as planned_count
FROM components
GROUP BY layer;

-- Component Details: Full component information with relationships
CREATE VIEW IF NOT EXISTS component_details AS
SELECT
    c.id,
    c.name,
    c.type,
    c.layer,
    c.status,
    c.purpose,
    c.business_value,
    COUNT(DISTINCT ca.id) as artifact_count,
    COUNT(DISTINCT dd.id) as decision_count,
    COUNT(DISTINCT cr_out.id) as outgoing_relationships,
    COUNT(DISTINCT cr_in.id) as incoming_relationships
FROM components c
LEFT JOIN code_artifacts ca ON c.id = ca.component_id
LEFT JOIN design_decisions dd ON c.id = dd.component_id
LEFT JOIN component_relationships cr_out ON c.id = cr_out.source_id
LEFT JOIN component_relationships cr_in ON c.id = cr_in.target_id
GROUP BY c.id;

-- Session Statistics: Overview of generation/documentation sessions
CREATE VIEW IF NOT EXISTS session_statistics AS
SELECT
    session_type,
    mode,
    status,
    COUNT(*) as session_count,
    AVG(CAST((julianday(completed_at) - julianday(started_at)) * 24 * 60 AS INTEGER)) as avg_duration_minutes
FROM generation_sessions
WHERE completed_at IS NOT NULL
GROUP BY session_type, mode, status;
