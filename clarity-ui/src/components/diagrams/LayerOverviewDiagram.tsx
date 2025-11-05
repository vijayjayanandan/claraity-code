import { useCallback, useEffect, useState } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import { Box, CircularProgress, Alert } from '@mui/material';
import { getLayerArchitecture } from '../../services/api';
import type { LayerArchitecture } from '../../services/api';
// Icons for each layer type
import ViewInArIcon from '@mui/icons-material/ViewInAr';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import MemoryIcon from '@mui/icons-material/Memory';
import LocalLibraryIcon from '@mui/icons-material/LocalLibrary';
import BuildIcon from '@mui/icons-material/Build';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ChatBubbleIcon from '@mui/icons-material/ChatBubble';
import ExtensionIcon from '@mui/icons-material/Extension';
import GroupsIcon from '@mui/icons-material/Groups';
import SettingsIcon from '@mui/icons-material/Settings';
import HelpIcon from '@mui/icons-material/Help';

// Layer color mapping - enhanced brightness for dark background
const LAYER_COLORS: Record<string, string> = {
  core: '#6B7FFF',      // Brighter blue
  memory: '#4CAF50',    // Green
  rag: '#FF9800',       // Orange
  workflow: '#BA68C8',  // Lighter purple
  tools: '#00ACC1',     // Teal/Aqua (distinct from blue)
  llm: '#EF5350',       // Lighter red
  prompts: '#26C6DA',   // Lighter cyan
  hooks: '#FFEE58',     // Brighter yellow
  subagents: '#A1887F', // Lighter brown
  utils: '#78909C',     // Lighter blue-gray
  other: '#BDBDBD',     // Lighter gray
};

// Layer icon mapping - meaningful visual symbols for each layer
const LAYER_ICONS: Record<string, React.ComponentType<any>> = {
  core: ViewInArIcon,           // 3D box/foundation
  workflow: AccountTreeIcon,    // Process tree/flow
  memory: MemoryIcon,           // Memory chip/storage
  rag: LocalLibraryIcon,        // Books/knowledge base
  tools: BuildIcon,             // Wrench/build tools
  llm: SmartToyIcon,            // Robot/AI
  prompts: ChatBubbleIcon,      // Speech bubble/conversation
  hooks: ExtensionIcon,         // Puzzle piece/plugin
  subagents: GroupsIcon,        // People/team delegation
  utils: SettingsIcon,          // Gear/utilities
  other: HelpIcon,              // Question mark/unknown
};

// Stroke patterns for color-blind accessibility
// Different dash patterns help distinguish connections even without color
const LAYER_STROKE_PATTERNS: Record<string, string> = {
  core: '',                     // Solid line (primary connections)
  workflow: '8 4',              // Medium dashes
  memory: '4 2',                // Short dashes
  rag: '12 4 2 4',              // Dash-dot pattern
  tools: '2 2',                 // Dotted line
  llm: '8 2 2 2',               // Dash-dot-dot pattern
  prompts: '6 3',               // Medium-short dashes
  hooks: '10 2',                // Long dash-short gap
  subagents: '4 4',             // Equal dash-gap
  utils: '12 2',                // Long dash-short gap
  other: '1 3',                 // Very short dots
};

interface LayerOverviewDiagramProps {
  onLayerClick: (layerName: string) => void;
}

const nodeWidth = 200;
const nodeHeight = 100; // Increased to accommodate icon + text

const getLayoutedElements = (nodes: Node[], edges: Edge[]) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'TB', ranksep: 180, nodesep: 150 });

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
    };
  });

  return { nodes: layoutedNodes, edges };
};

export default function LayerOverviewDiagram({ onLayerClick }: LayerOverviewDiagramProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [focusedNodeIndex, setFocusedNodeIndex] = useState<number>(-1); // For keyboard navigation
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  // Detect prefers-reduced-motion preference
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReducedMotion(mediaQuery.matches);

    // Listen for changes to the preference
    const handleChange = (e: MediaQueryListEvent) => {
      setPrefersReducedMotion(e.matches);
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    loadArchitecture();
  }, []);

  // Keyboard navigation handler
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (nodes.length === 0) return;

      switch (event.key) {
        case 'ArrowRight':
        case 'ArrowDown':
          event.preventDefault();
          setFocusedNodeIndex((prev) => {
            const next = prev + 1;
            return next >= nodes.length ? 0 : next;
          });
          break;

        case 'ArrowLeft':
        case 'ArrowUp':
          event.preventDefault();
          setFocusedNodeIndex((prev) => {
            const next = prev - 1;
            return next < 0 ? nodes.length - 1 : next;
          });
          break;

        case 'Enter':
        case ' ':
          event.preventDefault();
          if (focusedNodeIndex >= 0 && focusedNodeIndex < nodes.length) {
            const focusedNode = nodes[focusedNodeIndex];
            // Single Enter/Space = select (highlight)
            if (event.key === 'Enter' && event.shiftKey) {
              // Shift+Enter = navigate to detail view
              onLayerClick(focusedNode.id);
            } else {
              // Regular Enter/Space = select/toggle
              setSelectedNode((prev) => (prev === focusedNode.id ? null : focusedNode.id));
            }
          }
          break;

        case 'Escape':
          event.preventDefault();
          setSelectedNode(null);
          setFocusedNodeIndex(-1);
          break;

        case 'Tab':
          // Allow default Tab behavior but update focus tracking
          if (!event.shiftKey) {
            setFocusedNodeIndex((prev) => {
              const next = prev + 1;
              return next >= nodes.length ? 0 : next;
            });
          } else {
            setFocusedNodeIndex((prev) => {
              const next = prev - 1;
              return next < 0 ? nodes.length - 1 : next;
            });
          }
          break;

        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [nodes, focusedNodeIndex, onLayerClick]);

  // Smoothly update edges when selected node changes
  useEffect(() => {
    if (edges.length === 0) return;

    const updatedEdges = edges.map((edge) => {
      const isFromSelected = selectedNode === edge.source;
      const sourceColor = edge.data?.color || '#888';

      return {
        ...edge,
        // Respect prefers-reduced-motion: disable animation if user prefers reduced motion
        animated: !prefersReducedMotion && isFromSelected,
        style: {
          ...edge.style,
          strokeWidth: isFromSelected ? 3.5 : 2.5,
          strokeOpacity: isFromSelected ? 1 : 0.8,
          // Preserve stroke pattern for color-blind accessibility
          strokeDasharray: edge.data?.pattern || '',
          // Instant transition if reduced motion is preferred
          transition: prefersReducedMotion ? 'none' : 'all 0.3s ease',
        },
      };
    });

    setEdges(updatedEdges);
  }, [selectedNode, prefersReducedMotion]);

  // Smoothly update nodes when selected node or focused node changes
  useEffect(() => {
    if (nodes.length === 0) return;

    const updatedNodes = nodes.map((node, index) => {
      const isSelected = selectedNode === node.id;
      const isFocused = focusedNodeIndex === index;
      const nodeColor = LAYER_COLORS[node.id] || LAYER_COLORS.other;

      // Count outgoing connections for ARIA label
      const outgoingConnections = edges.filter(e => e.source === node.id).length;
      const incomingConnections = edges.filter(e => e.target === node.id).length;

      return {
        ...node,
        style: {
          ...node.style,
          border: isSelected
            ? `3px solid #fff`
            : isFocused
            ? `3px solid #3b82f6`  // Blue focus indicator
            : '2px solid rgba(255,255,255,0.15)',
          boxShadow: isSelected
            ? `0 4px 16px rgba(0,0,0,0.5), 0 0 20px ${nodeColor}`
            : isFocused
            ? `0 4px 16px rgba(0,0,0,0.5), 0 0 20px #3b82f6`  // Blue glow when focused
            : '0 2px 8px rgba(0,0,0,0.3)',
          outline: isFocused ? '2px solid #3b82f6' : 'none',  // Additional focus ring
          outlineOffset: '2px',
          // Respect prefers-reduced-motion for node transitions
          transition: prefersReducedMotion ? 'none' : 'all 0.3s ease',
        },
        // Add ARIA attributes
        ariaLabel: `${node.id} layer, ${node.data.label?.props?.children?.[1]?.props?.children || 'components'}, ${outgoingConnections} outgoing connections, ${incomingConnections} incoming connections. ${isSelected ? 'Selected. ' : ''}Press Enter to select, Shift+Enter to explore details.`,
        role: 'button',
        tabIndex: isFocused ? 0 : -1,
      };
    });

    setNodes(updatedNodes);
  }, [selectedNode, focusedNodeIndex, edges, prefersReducedMotion]);

  const loadArchitecture = async () => {
    try {
      setLoading(true);
      setError(null);

      const data: LayerArchitecture = await getLayerArchitecture();

      // Create nodes for each layer
      const layerNodes: Node[] = data.layers.map((layer) => {
        const isSelected = selectedNode === layer.id;
        const layerColor = LAYER_COLORS[layer.id] || LAYER_COLORS.other;
        const LayerIcon = LAYER_ICONS[layer.id] || LAYER_ICONS.other;

        return {
          id: layer.id,
          type: 'default',
          data: {
            label: (
              <Box
                sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '100%',
                  cursor: 'pointer',
                }}
              >
                {/* Icon */}
                <LayerIcon
                  sx={{
                    fontSize: '28px',
                    color: '#fff',
                    mb: 0.5,
                    opacity: 0.95,
                  }}
                />
                {/* Layer Name */}
                <Box
                  sx={{
                    fontSize: '16px',
                    fontWeight: 'bold',
                    textTransform: 'capitalize',
                    color: '#fff',
                    mb: 0.5,
                  }}
                >
                  {layer.name}
                </Box>
                {/* Component Count Badge */}
                <Box
                  sx={{
                    fontSize: '12px',
                    color: 'rgba(255,255,255,0.9)',
                    backgroundColor: 'rgba(0,0,0,0.2)',
                    padding: '2px 8px',
                    borderRadius: '10px',
                  }}
                >
                  {layer.count} component{layer.count !== 1 ? 's' : ''}
                </Box>
              </Box>
            ),
          },
          position: { x: 0, y: 0 }, // Will be set by dagre
          style: {
            backgroundColor: layerColor,
            color: '#fff',
            border: isSelected ? `3px solid #fff` : '2px solid rgba(255,255,255,0.15)',
            borderRadius: '8px',
            width: nodeWidth,
            height: nodeHeight,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: isSelected
              ? `0 4px 16px rgba(0,0,0,0.5), 0 0 20px ${layerColor}`
              : '0 2px 8px rgba(0,0,0,0.3)',
            cursor: 'pointer',
          },
        };
      });

      // Create edges for layer connections with enhanced contrast
      const layerEdges: Edge[] = data.connections.map((conn, index) => {
        // Use the source layer's color for intuitive visual connection
        const sourceColor = LAYER_COLORS[conn.source] || LAYER_COLORS.other;
        // Get stroke pattern for color-blind accessibility
        const strokePattern = LAYER_STROKE_PATTERNS[conn.source] || LAYER_STROKE_PATTERNS.other;
        // Animate only edges from the selected node
        const isFromSelected = selectedNode === conn.source;

        return {
          id: `e-${conn.source}-${conn.target}-${index}`,
          source: conn.source,
          target: conn.target,
          type: 'default', // Smooth bezier curves like professional diagram
          animated: isFromSelected, // Animate if from selected node
          // No label by default - shown in legend instead
          style: {
            stroke: sourceColor,
            strokeWidth: isFromSelected ? 3.5 : 2.5, // Thicker when selected
            strokeOpacity: isFromSelected ? 1 : 0.8, // More opaque when selected
            strokeDasharray: strokePattern, // Pattern for color-blind accessibility
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: sourceColor,
            width: 16,
            height: 16,
          },
          data: {
            label: `${conn.source} → ${conn.target}`,
            count: conn.count,
            types: conn.types.join(', '),
            color: sourceColor,
            pattern: strokePattern, // Store pattern for legend
          }
        };
      });

      // Apply dagre layout
      const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
        layerNodes,
        layerEdges
      );

      setNodes(layoutedNodes);
      setEdges(layoutedEdges);
    } catch (err) {
      console.error('Failed to load layer architecture:', err);
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to load architecture data. Make sure the server is running.'
      );
    } finally {
      setLoading(false);
    }
  };

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setSelectedNode(node.id);
    },
    []
  );

  const onNodeDoubleClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onLayerClick(node.id);
    },
    [onLayerClick]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  return (
    <Box
      sx={{ width: '100%', height: '600px', position: 'relative' }}
      role="region"
      aria-label="Architecture Layer Diagram - Interactive visualization of system layers and their connections"
    >
      <Box sx={{
        width: '100%',
        height: '100%',
        border: '1px solid #333',
        borderRadius: '8px',
        backgroundColor: '#1a1a1a', // Dark background
      }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onNodeDoubleClick={onNodeDoubleClick}
          onPaneClick={onPaneClick}
          fitView
          minZoom={0.5}
          maxZoom={1.5}
          aria-label="Layer architecture diagram"
        >
          <Background color="#444" gap={16} />
          <Controls />
        </ReactFlow>
      </Box>

      {/* Legend showing connections */}
      {edges.length > 0 && (
        <Box
          sx={{
            position: 'absolute',
            bottom: 16,
            right: 16,
            backgroundColor: 'rgba(30, 30, 30, 0.95)',
            padding: 2.5,
            borderRadius: 2,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            maxWidth: '280px',
            border: '2px solid rgba(255, 255, 255, 0.2)',
            zIndex: 1000,
          }}
        >
          <Box sx={{ fontWeight: 'bold', mb: 1.5, fontSize: '14px', color: '#fff' }}>
            🔗 Layer Connections
          </Box>
          <Box sx={{ fontSize: '11px', color: 'rgba(255, 255, 255, 0.6)', mb: 1.5, fontStyle: 'italic' }}>
            💡 Click to highlight • Double-click to explore
          </Box>
          <Box sx={{ fontSize: '10px', color: 'rgba(255, 255, 255, 0.5)', mb: 1.5, fontStyle: 'italic', borderTop: '1px solid rgba(255,255,255,0.1)', pt: 1 }}>
            ⌨️ Keyboard: Arrow keys to navigate • Enter to select • Shift+Enter to explore • Esc to deselect
          </Box>
          {edges.map((edge) => (
            <Box
              key={edge.id}
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                mb: 1,
                fontSize: '12px',
              }}
            >
              {/* SVG line showing actual pattern */}
              <svg width="32" height="8" style={{ flexShrink: 0 }}>
                <line
                  x1="0"
                  y1="4"
                  x2="32"
                  y2="4"
                  stroke={edge.data?.color || edge.style?.stroke || '#fff'}
                  strokeWidth="3"
                  strokeDasharray={edge.data?.pattern || ''}
                  strokeLinecap="round"
                  style={{
                    filter: `drop-shadow(0 0 4px ${edge.data?.color || edge.style?.stroke})`,
                  }}
                />
              </svg>
              <Box sx={{ color: '#fff', fontWeight: 500 }}>
                {edge.data?.label} ({edge.data?.count})
              </Box>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
