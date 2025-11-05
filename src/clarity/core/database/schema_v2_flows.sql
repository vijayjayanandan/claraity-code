-- ClarAIty Schema v2 - Execution Flows Extension
-- Purpose: Capture execution flows to show how code flows through components
-- Supports hierarchical flows (high-level → detailed steps) with code traceability

-- =============================================================================
-- EXECUTION FLOW TABLES
-- =============================================================================

-- Execution Flows: Named flows representing code execution paths
CREATE TABLE IF NOT EXISTS execution_flows (
    id TEXT PRIMARY KEY,                    -- Unique identifier (e.g., "WORKFLOW_EXECUTION_FLOW")
    name TEXT NOT NULL,                     -- Human-readable name (e.g., "Workflow Execution Flow")
    description TEXT,                       -- What this flow represents
    trigger TEXT NOT NULL,                  -- What triggers this flow (e.g., "User types complex task")
    flow_type TEXT NOT NULL,                -- Type: user-facing|internal|background
    complexity TEXT DEFAULT 'medium',       -- Complexity: simple|medium|complex
    is_primary BOOLEAN DEFAULT 0,           -- Is this a primary/main flow?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Flow Steps: Individual steps in an execution flow (hierarchical)
CREATE TABLE IF NOT EXISTS flow_steps (
    id TEXT PRIMARY KEY,                    -- Unique identifier
    flow_id TEXT NOT NULL,                  -- Flow this step belongs to
    parent_step_id TEXT,                    -- Parent step (for hierarchical/substeps)
    sequence INTEGER NOT NULL,              -- Order within parent (0, 1, 2...)
    level INTEGER DEFAULT 0,                -- Hierarchy level: 0=top, 1=substep, 2=sub-substep

    -- Step Details
    step_type TEXT NOT NULL,                -- Type: normal|decision|loop|parallel|end
    title TEXT NOT NULL,                    -- Short step title (e.g., "Agent Routes Request")
    description TEXT,                       -- Detailed description of what happens

    -- Code Traceability
    component_id TEXT,                      -- Component involved (FK to components)
    file_path TEXT,                         -- File where this step happens
    line_start INTEGER,                     -- Starting line number
    line_end INTEGER,                       -- Ending line number
    function_name TEXT,                     -- Function/method name (e.g., "_should_use_workflow")

    -- Decision Steps (for branching)
    decision_question TEXT,                 -- Question being decided (e.g., "Use workflow?")
    decision_logic TEXT,                    -- How decision is made

    -- Branches (for decision/parallel steps)
    branches TEXT,                          -- JSON array of branch info: [{"label": "Yes", "target_step_id": "..."}, ...]

    -- Metadata
    execution_time_ms INTEGER,              -- Estimated execution time
    is_critical BOOLEAN DEFAULT 0,          -- Is this a critical step?
    notes TEXT,                             -- Additional notes/context

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (flow_id) REFERENCES execution_flows(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_step_id) REFERENCES flow_steps(id) ON DELETE CASCADE,
    FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE SET NULL
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_flows_type ON execution_flows(flow_type);
CREATE INDEX IF NOT EXISTS idx_flows_primary ON execution_flows(is_primary);

CREATE INDEX IF NOT EXISTS idx_steps_flow ON flow_steps(flow_id);
CREATE INDEX IF NOT EXISTS idx_steps_parent ON flow_steps(parent_step_id);
CREATE INDEX IF NOT EXISTS idx_steps_sequence ON flow_steps(flow_id, parent_step_id, sequence);
CREATE INDEX IF NOT EXISTS idx_steps_level ON flow_steps(level);
CREATE INDEX IF NOT EXISTS idx_steps_component ON flow_steps(component_id);
CREATE INDEX IF NOT EXISTS idx_steps_file ON flow_steps(file_path);

-- =============================================================================
-- VIEWS FOR COMMON QUERIES
-- =============================================================================

-- Flow Summary: Overview of all flows with step counts
CREATE VIEW IF NOT EXISTS flow_summary AS
SELECT
    f.id,
    f.name,
    f.description,
    f.flow_type,
    f.complexity,
    f.is_primary,
    COUNT(DISTINCT fs.id) as total_steps,
    COUNT(DISTINCT CASE WHEN fs.level = 0 THEN fs.id END) as top_level_steps,
    COUNT(DISTINCT CASE WHEN fs.step_type = 'decision' THEN fs.id END) as decision_points
FROM execution_flows f
LEFT JOIN flow_steps fs ON f.id = fs.flow_id
GROUP BY f.id;

-- Step Details with Component Info: Full step information
CREATE VIEW IF NOT EXISTS step_details AS
SELECT
    fs.id,
    fs.flow_id,
    fs.parent_step_id,
    fs.sequence,
    fs.level,
    fs.step_type,
    fs.title,
    fs.description,
    fs.file_path,
    fs.line_start,
    fs.line_end,
    fs.function_name,
    fs.decision_question,
    c.name as component_name,
    c.layer as component_layer
FROM flow_steps fs
LEFT JOIN components c ON fs.component_id = c.id;
