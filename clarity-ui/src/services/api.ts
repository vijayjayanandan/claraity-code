import axios from 'axios';
import type {
  Component,
  ComponentDetail,
  ArchitectureSummary,
  DesignDecision,
  Relationship,
  Statistics,
  Capability
} from '../types';

const API_BASE_URL = 'http://localhost:8766/api/clarity';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Architecture endpoints
export const getArchitectureSummary = async (): Promise<ArchitectureSummary> => {
  const response = await api.get<ArchitectureSummary>('/architecture');
  return response.data;
};

export const getStatistics = async (): Promise<Statistics> => {
  const response = await api.get<Statistics>('/statistics');
  return response.data;
};

// Component endpoints
export const getAllComponents = async (params?: {
  layer?: string;
  type?: string;
  status?: string;
  limit?: number;
}): Promise<Component[]> => {
  const response = await api.get<Component[]>('/components', { params });
  return response.data;
};

export const searchComponents = async (query: string, limit: number = 20): Promise<Component[]> => {
  const response = await api.get<Component[]>('/components/search', {
    params: { q: query, limit }
  });
  return response.data;
};

export const getComponent = async (componentId: string): Promise<ComponentDetail> => {
  const response = await api.get<ComponentDetail>(`/components/${componentId}`);
  return response.data;
};

export const getComponentRelationships = async (componentId: string): Promise<{
  outgoing: Relationship[];
  incoming: Relationship[];
}> => {
  const response = await api.get(`/components/${componentId}/relationships`);
  return response.data;
};

export const getComponentDecisions = async (componentId: string): Promise<DesignDecision[]> => {
  const response = await api.get<DesignDecision[]>(`/components/${componentId}/decisions`);
  return response.data;
};

// Decision endpoints
export const getAllDecisions = async (params?: {
  decision_type?: string;
  limit?: number;
}): Promise<DesignDecision[]> => {
  const response = await api.get<DesignDecision[]>('/decisions', { params });
  return response.data;
};

// Relationship endpoints
export const getAllRelationships = async (params?: {
  relationship_type?: string;
  limit?: number;
}): Promise<Relationship[]> => {
  const response = await api.get<{ relationships: Relationship[]; count: number }>('/relationships', { params });
  return response.data.relationships;
};

// Health check (uses root-level endpoint, not /api/clarity prefix)
export const healthCheck = async (): Promise<{ status: string; database: string; statistics: Statistics }> => {
  const response = await axios.get('http://localhost:8766/health');
  return response.data;
};

// Unified Interface endpoints
export const getCapabilities = async (): Promise<Capability[]> => {
  const response = await api.get<{ capabilities: Capability[]; count: number }>('/capabilities');
  return response.data.capabilities;
};

// Multi-level architecture endpoints
export interface Layer {
  id: string;
  name: string;
  count: number;
}

export interface LayerConnection {
  source: string;
  target: string;
  count: number;
  types: string[];
}

export interface LayerArchitecture {
  layers: Layer[];
  connections: LayerConnection[];
}

export const getLayerArchitecture = async (): Promise<LayerArchitecture> => {
  const response = await api.get<LayerArchitecture>('/architecture/layers');
  return response.data;
};

export interface LayerDetail {
  layer: string;
  components: Component[];
  relationships: {
    id: string;
    from_component_id: string;
    to_component_id: string;
    relationship_type: string;
  }[];
  external_connections: {
    outgoing: Record<string, number>;
    incoming: Record<string, number>;
  };
}

export const getLayerComponents = async (layerName: string): Promise<LayerDetail> => {
  const response = await api.get<LayerDetail>(`/layers/${layerName}/components`);
  return response.data;
};

export default api;
