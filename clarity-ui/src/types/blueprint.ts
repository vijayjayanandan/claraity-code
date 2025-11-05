/**
 * Blueprint Types for ClarAIty
 * Mirrors the Python backend Blueprint data structures
 */

export type ComponentType =
  | 'class'
  | 'function'
  | 'module'
  | 'api'
  | 'database'
  | 'ui'
  | 'service'
  | 'component'
  | 'hook'
  | 'store'
  | 'util'
  | 'config'
  | 'type'
  | 'types';

export type RelationType =
  | 'calls'
  | 'imports'
  | 'inherits'
  | 'uses'
  | 'depends_on'
  | 'renders'
  | 'provides'
  | 'consumes'
  | 'subscribes'
  | 'manages'
  | 'routes_to'
  | 'updates';

export type FileActionType = 'create' | 'modify' | 'delete';

export interface Component {
  name: string;
  type: ComponentType;
  purpose: string;
  responsibilities: string[];
  file_path: string;
  layer?: string;
  key_methods: string[];
  dependencies: string[];
}

export interface DesignDecision {
  decision: string;
  rationale: string;
  alternatives_considered: string[];
  trade_offs?: string;
  category?: string;
}

export interface FileAction {
  file_path: string;
  action: FileActionType;
  description: string;
  estimated_lines?: number;
  components_affected: string[];
}

export interface Relationship {
  source: string;
  target: string;
  type: RelationType;
  description?: string;
}

export interface Blueprint {
  task_description: string;
  components: Component[];
  design_decisions: DesignDecision[];
  file_actions: FileAction[];
  relationships: Relationship[];
  estimated_complexity?: string;
  estimated_time?: string;
  prerequisites: string[];
  risks: string[];
}

export interface ApprovalDecision {
  approved: boolean;
  feedback?: string;
  timestamp: Date;
}
