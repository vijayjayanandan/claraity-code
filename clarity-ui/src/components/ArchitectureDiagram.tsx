import { useState, useEffect, useCallback } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  Connection,
  addEdge,
  BackgroundVariant,
  NodeTypes,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Box, CircularProgress, Alert } from '@mui/material';
import { getAllComponents, getAllRelationships, getComponent } from '../services/api';
import type { Component, Relationship, ComponentDetail } from '../types';
import ComponentNode from './ComponentNode';
import LayerLegend from './LayerLegend';

// Layer colors for visualization
const LAYER_COLORS: Record<string, string> = {
  core: '#646cff',
  memory: '#4CAF50',
  rag: '#FF9800',
  workflow: '#9C27B0',
  tools: '#2196F3',
  llm: '#F44336',
  prompts: '#00BCD4',
  hooks: '#FFEB3B',
  subagents: '#795548',
  utils: '#607D8B',
  other: '#9E9E9E',
};

// Component type for React Flow
const nodeTypes: NodeTypes = {
  component: ComponentNode,
};

interface ArchitectureDiagramProps {
  onComponentSelect: (component: ComponentDetail | null) => void;
  selectedComponentId?: string;
}

const ArchitectureDiagram: React.FC<ArchitectureDiagramProps> = ({
  onComponentSelect,
  selectedComponentId,
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [componentsByLayer, setComponentsByLayer] = useState<Record<string, number>>({});

  useEffect(() => {
    loadArchitecture();
  }, []);

  const loadArchitecture = async () => {
    try {
      setLoading(true);
      setError(null);

      // Load all components
      const components = await getAllComponents();

      // Load all relationships
      const relationships = await getAllRelationships();

      // Calculate layer counts for legend
      const layerCounts: Record<string, number> = {};
      components.forEach((comp) => {
        layerCounts[comp.layer] = (layerCounts[comp.layer] || 0) + 1;
      });
      setComponentsByLayer(layerCounts);

      // Create nodes from components
      const flowNodes = createNodes(components);

      // Create edges from relationships
      const flowEdges = createEdges(relationships);

      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch (err) {
      console.error('Failed to load architecture:', err);
      setError(err instanceof Error ? err.message : 'Failed to load architecture');
    } finally {
      setLoading(false);
    }
  };

  const createNodes = (components: Component[]): Node[] => {
    // Group components by layer
    const componentsByLayer: Record<string, Component[]> = {};
    components.forEach((comp) => {
      if (!componentsByLayer[comp.layer]) {
        componentsByLayer[comp.layer] = [];
      }
      componentsByLayer[comp.layer].push(comp);
    });

    // Layout nodes by layer with proper spacing
    const nodes: Node[] = [];
    const layers = Object.keys(componentsByLayer).sort();

    // Increased spacing to prevent overlaps
    const layerSpacing = 400;  // Increased vertical spacing between layers
    const nodeSpacing = 300;    // Increased horizontal spacing (ComponentNode maxWidth=250 + margin)
    const nodeWidth = 250;      // Match ComponentNode maxWidth

    layers.forEach((layer, layerIndex) => {
      const layerComponents = componentsByLayer[layer];
      const startY = layerIndex * layerSpacing;

      // Center components in each layer
      const layerWidth = (layerComponents.length - 1) * nodeSpacing + nodeWidth;
      const startX = -layerWidth / 2;

      layerComponents.forEach((comp, compIndex) => {
        nodes.push({
          id: comp.id,
          type: 'component',
          position: {
            x: startX + (compIndex * nodeSpacing),
            y: startY,
          },
          data: {
            component: comp,
            color: LAYER_COLORS[comp.layer] || LAYER_COLORS.other,
            selected: comp.id === selectedComponentId,
          },
        });
      });
    });

    return nodes;
  };

  const createEdges = (relationships: Relationship[]): Edge[] => {
    return relationships.map((rel, index) => ({
      id: rel.id || `edge-${index}`,
      source: rel.source_id,
      target: rel.target_id,
      label: rel.relationship_type,
      type: 'smoothstep',
      animated: rel.criticality === 'high',
      style: {
        stroke: rel.criticality === 'high' ? '#ff0000' : '#999',
        strokeWidth: rel.criticality === 'high' ? 2 : 1,
      },
    }));
  };

  const onNodeClick = useCallback(
    async (_event: React.MouseEvent, node: Node) => {
      try {
        const componentDetail = await getComponent(node.id);
        onComponentSelect(componentDetail);
      } catch (err) {
        console.error('Failed to load component details:', err);
      }
    },
    [onComponentSelect]
  );

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  if (loading) {
    return (
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
      <LayerLegend componentsByLayer={componentsByLayer} />
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
      >
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            const component = node.data.component as Component;
            return LAYER_COLORS[component?.layer] || LAYER_COLORS.other;
          }}
          nodeBorderRadius={2}
        />

        {/* Layer Labels Panel */}
        <Panel position="top-center" style={{ pointerEvents: 'none' }}>
          <Box sx={{
            display: 'flex',
            gap: 2,
            p: 2,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            borderRadius: 2,
            backdropFilter: 'blur(10px)',
          }}>
            {Object.keys(componentsByLayer).sort().map((layer) => {
              const color = LAYER_COLORS[layer] || LAYER_COLORS.other;
              const count = componentsByLayer[layer];
              return (
                <Box
                  key={layer}
                  sx={{
                    px: 2,
                    py: 1,
                    borderRadius: 1,
                    border: `2px solid ${color}`,
                    backgroundColor: `${color}20`,
                  }}
                >
                  <Box sx={{ fontSize: '12px', color: color, fontWeight: 'bold', textTransform: 'uppercase' }}>
                    {layer}
                  </Box>
                  <Box sx={{ fontSize: '10px', color: 'rgba(255, 255, 255, 0.6)', textAlign: 'center' }}>
                    {count}
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Panel>
      </ReactFlow>
    </Box>
  );
};

export default ArchitectureDiagram;
