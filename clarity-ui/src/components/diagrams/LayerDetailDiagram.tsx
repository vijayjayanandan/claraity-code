import { useCallback, useEffect, useState, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  NodeMouseHandler,
  Handle,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import { Box, CircularProgress, Alert, IconButton, Typography, Chip } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { getLayerComponents } from '../../services/api';
import type { LayerDetail } from '../../services/api';
import type { Component } from '../../types';

// Component type icons
import ClassIcon from '@mui/icons-material/Class';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ErrorIcon from '@mui/icons-material/Error';
import HelpIcon from '@mui/icons-material/Help';

// Component type icon mapping
const COMPONENT_TYPE_ICONS: Record<string, React.ComponentType<any>> = {
  'core-class': ClassIcon,
  'orchestrator': AccountTreeIcon,
  'exception': ErrorIcon,
};

// Layer colors (from LayerOverviewDiagram)
const LAYER_COLORS: Record<string, string> = {
  core: '#6B7FFF',
  memory: '#4CAF50',
  rag: '#FF9800',
  workflow: '#BA68C8',
  tools: '#00ACC1',
  llm: '#EF5350',
  prompts: '#26C6DA',
  hooks: '#FFEE58',
  subagents: '#A1887F',
  utils: '#78909C',
  other: '#BDBDBD',
};

interface LayerDetailDiagramProps {
  layerName: string;
  onBack: () => void;
  onComponentClick?: (componentId: string) => void;
}

const nodeWidth = 280;
const nodeHeight = 140;

// Smart layout: Grid for flat hierarchies, Dagre for deep trees
const getLayoutedElements = (nodes: Node[], edges: Edge[]) => {
  const cols = 4;
  const horizontalSpacing = nodeWidth + 80;
  const verticalSpacing = nodeHeight + 100;

  // Strategy 1: If no/few relationships, use simple grid layout for all nodes
  if (edges.length < 3) {
    const layoutedNodes = nodes.map((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      return {
        ...node,
        position: {
          x: col * horizontalSpacing,
          y: row * verticalSpacing,
        },
        style: {
          width: nodeWidth,
          height: nodeHeight,
          zIndex: 10,
        },
      };
    });
    return { nodes: layoutedNodes, edges };
  }

  // Analyze the graph structure
  const targetCounts = new Map<string, number>();
  edges.forEach((edge) => {
    targetCounts.set(edge.target, (targetCounts.get(edge.target) || 0) + 1);
  });

  // Find nodes with many children (base classes)
  const baseClasses = Array.from(targetCounts.entries())
    .filter(([_, count]) => count >= 5)
    .map(([id, _]) => id);

  // Strategy 2: If we have a flat hierarchy (many children → one parent), use grid layout
  if (baseClasses.length === 1 && edges.length >= 5) {
    const baseClassId = baseClasses[0];
    const children = edges
      .filter((e) => e.target === baseClassId)
      .map((e) => nodes.find((n) => n.id === e.source))
      .filter((n): n is Node => n !== undefined);
    const baseClassNode = nodes.find((n) => n.id === baseClassId);

    // Grid layout with base class at bottom
    const layoutedNodes = children.map((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      return {
        ...node,
        position: {
          x: col * horizontalSpacing,
          y: row * verticalSpacing,
        },
        style: {
          width: nodeWidth,
          height: nodeHeight,
          zIndex: 10,
        },
      };
    });

    // Position base class centered below all children
    if (baseClassNode) {
      const totalRows = Math.ceil(children.length / cols);
      const centerX = ((cols - 1) * horizontalSpacing) / 2;
      layoutedNodes.push({
        ...baseClassNode,
        position: {
          x: centerX,
          y: totalRows * verticalSpacing + 100,
        },
        style: {
          width: nodeWidth,
          height: nodeHeight,
          zIndex: 10,
        },
      });
    }

    return { nodes: layoutedNodes, edges };
  }

  // Strategy 3: Otherwise, use dagre hierarchical layout for complex relationships
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'TB', ranksep: 150, nodesep: 100 });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
      style: {
        width: nodeWidth,
        height: nodeHeight,
        zIndex: 10,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
};

// Custom node component
interface ComponentNodeData {
  component: Component;
  layerColor: string;
  externalCount: number;
  externalDetails: { outgoing: Record<string, number>; incoming: Record<string, number> };
  onComponentClick?: (componentId: string) => void;
}

const ComponentNode = ({ data }: { data: ComponentNodeData }) => {
  const { component, layerColor, externalCount, externalDetails } = data;

  // Get icon for component type
  const IconComponent = COMPONENT_TYPE_ICONS[component.type] || HelpIcon;

  // Calculate external connections tooltip
  const externalTooltip = useMemo(() => {
    const parts: string[] = [];
    if (Object.keys(externalDetails.outgoing).length > 0) {
      parts.push(`Outgoing: ${Object.entries(externalDetails.outgoing).map(([layer, count]) => `${layer} (${count})`).join(', ')}`);
    }
    if (Object.keys(externalDetails.incoming).length > 0) {
      parts.push(`Incoming: ${Object.entries(externalDetails.incoming).map(([layer, count]) => `${layer} (${count})`).join(', ')}`);
    }
    return parts.join(' | ');
  }, [externalDetails]);

  return (
    <>
      {/* Connection handles - required for edges to work */}
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />

      <Box
        sx={{
          width: nodeWidth,
          height: nodeHeight,
          backgroundColor: '#1e293b', // slate-800
          border: `2px solid ${layerColor}`,
          borderRadius: '8px',
          padding: '12px',
          cursor: 'pointer',
          transition: 'all 0.2s ease',
          '&:hover': {
            transform: 'scale(1.02)',
            boxShadow: `0 0 20px ${layerColor}40`,
            borderColor: layerColor,
          },
        }}
      >
      {/* Header with icon and name */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <IconComponent sx={{ color: layerColor, fontSize: 28 }} />
        <Typography
          variant="subtitle1"
          sx={{
            color: '#f1f5f9', // slate-100
            fontWeight: 600,
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {component.name}
        </Typography>
        {externalCount > 0 && (
          <Chip
            label={`↗ ${externalCount}`}
            size="small"
            title={externalTooltip}
            sx={{
              backgroundColor: `${layerColor}40`,
              color: '#f1f5f9',
              fontSize: '0.75rem',
              height: '20px',
            }}
          />
        )}
      </Box>

      {/* Metadata */}
      <Typography
        variant="caption"
        sx={{
          color: '#94a3b8', // slate-400
          display: 'block',
          mb: 0.5,
        }}
      >
        Type: {component.type}
      </Typography>

      {/* Purpose (truncated) */}
      {component.purpose && (
        <Typography
          variant="caption"
          sx={{
            color: '#cbd5e1', // slate-300
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            lineHeight: 1.4,
          }}
        >
          {component.purpose}
        </Typography>
      )}
    </Box>
    </>
  );
};

const LayerDetailDiagram: React.FC<LayerDetailDiagramProps> = ({
  layerName,
  onBack,
  onComponentClick,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [layerData, setLayerData] = useState<LayerDetail | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Fetch layer data
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await getLayerComponents(layerName);
        setLayerData(data);
      } catch (err) {
        console.error('Error fetching layer components:', err);
        setError(err instanceof Error ? err.message : 'Failed to load layer components');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [layerName]);

  // Transform data to React Flow nodes and edges
  useEffect(() => {
    if (!layerData) return;

    const layerColor = LAYER_COLORS[layerName] || '#BDBDBD';

    // Calculate external connections per component
    const componentExternalCounts = new Map<string, number>();
    const componentExternalDetails = new Map<string, { outgoing: Record<string, number>; incoming: Record<string, number> }>();

    layerData.components.forEach((comp) => {
      const outgoingCount = Object.values(layerData.external_connections.outgoing).reduce((sum, count) => sum + count, 0);
      const incomingCount = Object.values(layerData.external_connections.incoming).reduce((sum, count) => sum + count, 0);
      // Note: This is simplified - in reality we'd need per-component external connections
      // For now, showing layer-level external connections on all nodes
      componentExternalCounts.set(comp.id, 0); // Will be calculated properly later
      componentExternalDetails.set(comp.id, {
        outgoing: layerData.external_connections.outgoing,
        incoming: layerData.external_connections.incoming,
      });
    });

    // Create nodes
    const reactFlowNodes: Node<ComponentNodeData>[] = layerData.components.map((comp) => ({
      id: comp.id,
      type: 'custom',
      position: { x: 0, y: 0 }, // Will be set by dagre
      data: {
        component: comp,
        layerColor,
        externalCount: componentExternalCounts.get(comp.id) || 0,
        externalDetails: componentExternalDetails.get(comp.id) || { outgoing: {}, incoming: {} },
        onComponentClick,
      },
    }));

    // Create edges - smooth bezier curves like Level 1
    const reactFlowEdges: Edge[] = layerData.relationships.map((rel, idx) => {
      const isExtends = rel.relationship_type === 'extends';

      return {
        id: `${rel.from_component_id}-${rel.to_component_id}-${idx}`,
        source: rel.from_component_id,
        target: rel.to_component_id,
        type: 'default', // Smooth bezier curves (professional look)
        animated: false,
        style: {
          stroke: layerColor,
          strokeWidth: 2.5,
          strokeDasharray: isExtends ? undefined : '10 5', // Solid for extends, dashed for uses
          strokeOpacity: 0.9,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: layerColor,
          width: 18,
          height: 18,
        },
        // No labels - cleaner look like Level 1
      };
    });

    // Apply dagre layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      reactFlowNodes,
      reactFlowEdges
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layerData, layerName, onComponentClick, setNodes, setEdges]);

  // Node click handler - toggle selection on click
  const handleNodeClick: NodeMouseHandler = useCallback(
    (event, node) => {
      // Toggle: if clicking same node, deselect; otherwise select
      setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
      if (onComponentClick) {
        onComponentClick(node.id);
      }
    },
    [onComponentClick]
  );

  // Click empty space to deselect
  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // Update selected node styling and animate outgoing edges
  useEffect(() => {
    // Update node opacity
    setNodes((nds) =>
      nds.map((node) => ({
        ...node,
        style: {
          ...node.style,
          opacity: selectedNodeId && selectedNodeId !== node.id ? 0.6 : 1,
        },
      }))
    );

    // Animate edges from selected node
    setEdges((eds) =>
      eds.map((edge) => {
        const isFromSelected = selectedNodeId === edge.source;
        return {
          ...edge,
          animated: isFromSelected,
          style: {
            ...edge.style,
            strokeWidth: isFromSelected ? 3.5 : 2.5,
            strokeOpacity: isFromSelected ? 1 : 0.7,
            zIndex: isFromSelected ? 5 : 1, // Selected edges slightly higher but still below nodes
          },
        };
      })
    );
  }, [selectedNodeId, setNodes, setEdges]);

  // Custom node types
  const nodeTypes = useMemo(
    () => ({
      custom: ComponentNode,
    }),
    []
  );

  if (loading) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          backgroundColor: '#0f172a', // slate-900
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          backgroundColor: '#0f172a',
          padding: 2,
        }}
      >
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
        <IconButton onClick={onBack} sx={{ color: '#f1f5f9' }}>
          <ArrowBackIcon />
        </IconButton>
      </Box>
    );
  }

  if (!layerData || layerData.components.length === 0) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          backgroundColor: '#0f172a',
          padding: 2,
        }}
      >
        <Alert severity="info" sx={{ mb: 2 }}>
          Layer "{layerName}" has no components
        </Alert>
        <IconButton onClick={onBack} sx={{ color: '#f1f5f9' }}>
          <ArrowBackIcon />
        </IconButton>
      </Box>
    );
  }

  const layerColor = LAYER_COLORS[layerName] || '#BDBDBD';

  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
      {/* Back button and breadcrumb */}
      <Box
        sx={{
          position: 'absolute',
          top: 16,
          left: 16,
          zIndex: 10,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          backgroundColor: '#1e293b',
          padding: '8px 16px',
          borderRadius: '8px',
          border: `1px solid ${layerColor}`,
        }}
      >
        <IconButton
          onClick={onBack}
          size="small"
          sx={{
            color: '#f1f5f9',
            '&:hover': {
              backgroundColor: `${layerColor}20`,
            },
          }}
        >
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="body2" sx={{ color: '#94a3b8' }}>
          Layer Overview
        </Typography>
        <Typography variant="body2" sx={{ color: '#94a3b8' }}>
          →
        </Typography>
        <Typography variant="body2" sx={{ color: layerColor, fontWeight: 600 }}>
          {layerName} Layer
        </Typography>
      </Box>

      {/* Legend */}
      <Box
        sx={{
          position: 'absolute',
          top: 16,
          right: 16,
          zIndex: 10,
          backgroundColor: '#1e293b',
          padding: '12px',
          borderRadius: '8px',
          border: '1px solid #334155',
          maxWidth: '300px',
        }}
      >
        <Typography variant="caption" sx={{ color: '#f1f5f9', fontWeight: 600, display: 'block', mb: 1 }}>
          {layerData.components.length} Components
        </Typography>
        {layerData.relationships.length > 0 && (
          <Typography variant="caption" sx={{ color: '#cbd5e1', display: 'block', mb: 0.5 }}>
            {layerData.relationships.length} internal relationships
          </Typography>
        )}
        {Object.keys(layerData.external_connections.outgoing).length > 0 && (
          <Typography variant="caption" sx={{ color: '#cbd5e1', display: 'block', mb: 0.5 }}>
            External: {Object.entries(layerData.external_connections.outgoing)
              .map(([layer, count]) => `${layer} (${count})`)
              .join(', ')}
          </Typography>
        )}
        <Typography variant="caption" sx={{ color: '#64748b', display: 'block', mt: 1 }}>
          💡 Click to view details
        </Typography>
      </Box>

      {/* React Flow diagram */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{
          padding: 0.15,
          minZoom: 0.5,
          maxZoom: 1.2,
        }}
        minZoom={0.5}
        maxZoom={2}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }}
        style={{ backgroundColor: '#0f172a' }}
        elevateEdgesOnSelect={false}
      >
        <Background color="#334155" gap={16} />
        <Controls
          style={{
            button: {
              backgroundColor: '#1e293b',
              color: '#f1f5f9',
              borderBottom: '1px solid #334155',
            },
          }}
        />
      </ReactFlow>
    </Box>
  );
};

export default LayerDetailDiagram;
