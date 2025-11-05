// Type definitions for ClarAIty

export interface Component {
  id: string;
  name: string;
  type: string;
  layer: string;
  status: string;
  purpose?: string;
  business_value?: string;
  design_rationale?: string;
  responsibilities?: string[];
  created_at?: string;
}

export interface ComponentDetail extends Component {
  artifacts: Artifact[];
  decisions: DesignDecision[];
  relationships: {
    outgoing: Relationship[];
    incoming: Relationship[];
  };
}

export interface Artifact {
  id: string;
  component_id: string;
  type: string;
  name: string;
  file_path: string;
  line_start?: number;
  line_end?: number;
  description?: string;
}

export interface DesignDecision {
  id: string;
  component_id: string;
  decision_type: string;
  question: string;
  chosen_solution: string;
  rationale: string;
  alternatives_considered?: string[];
  trade_offs?: string;
  decided_by: string;
  confidence: number;
  created_at?: string;
}

export interface Relationship {
  id: string;
  source_id: string;
  source_name?: string;
  target_id: string;
  target_name?: string;
  relationship_type: string;
  description?: string;
  criticality: string;
}

export interface ArchitectureSummary {
  project_name: string;
  total_components: number;
  total_artifacts: number;
  total_relationships: number;
  total_decisions: number;
  layers: LayerInfo[];
}

export interface LayerInfo {
  layer: string;
  component_count: number;
  completed_count: number;
  in_progress_count: number;
  planned_count: number;
}

export interface Statistics {
  total_components: number;
  total_artifacts: number;
  total_relationships: number;
  total_decisions: number;
  total_sessions: number;
  total_validations: number;
}

// ========== Unified Interface Types ==========

// Dashboard Tab
export interface Capability {
  name: string;
  description: string;
  components: string[];
  readiness: number; // Percentage (0-100)
  layer: string;
}

export interface EntryPoint {
  name: string;
  file_path: string;
  line_number: number;
  description: string;
}

// Flows Tab
export interface Flow {
  id: string;
  name: string;
  description: string;
  trigger: string;
  components_involved: number;
  created_at?: string;
}

export interface FlowStep {
  id: string;
  parent_step_id: string | null;
  sequence: number;
  level: number; // 0 = top-level, 1-2 = substeps
  step_type: string; // start, process, decision, end
  title: string;
  description: string;
  component_id: string;
  component_name: string;
  component_layer: string;
  file_path: string;
  line_start?: number;
  line_end?: number;
  function_name?: string;
  decision_question?: string;
  decision_logic?: string;
  branches?: string[];
  is_critical: boolean;
  notes?: string;
  substeps?: FlowStep[]; // Recursive for 3-level hierarchy
}

export interface FlowDetail {
  flow: Flow;
  steps: FlowStep[];
}

// Files Tab
export interface FileTreeNode {
  _type: 'file' | 'dir';
  name?: string; // Only for display purposes
  path?: string; // Full path for files
  components?: string[];
  layers?: string[];
  artifact_count?: number;
  line_count?: number;
  artifacts?: Artifact[];
  _children?: { [key: string]: FileTreeNode }; // For directories
}

export interface FileDetail {
  path: string;
  line_count: number;
  artifact_count: number;
  components: string[];
  layers: string[];
  artifacts: Artifact[];
}

// Search Tab
export interface SearchResult {
  type: 'component' | 'artifact' | 'flow_step' | 'file';
  title: string;
  description: string;
  file_reference?: string; // file:line format
  layer?: string;
  component_id?: string; // For navigation to Architecture tab
  file_path?: string; // For navigation to Files tab
  flow_id?: string; // For navigation to Flows tab
}
