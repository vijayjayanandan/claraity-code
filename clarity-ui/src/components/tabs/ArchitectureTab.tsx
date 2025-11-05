import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Paper,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Chip,
  Drawer,
  IconButton,
  Divider,
  ToggleButtonGroup,
  ToggleButton,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CloseIcon from '@mui/icons-material/Close';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ViewListIcon from '@mui/icons-material/ViewList';
import { getAllComponents } from '../../services/api';
import type { Component } from '../../types';
import LayerOverviewDiagram from '../diagrams/LayerOverviewDiagram';
import LayerDetailDiagram from '../diagrams/LayerDetailDiagram';

// Layer color mapping matching HTML POC
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

// Layer display order (top to bottom)
const LAYER_ORDER = [
  'core',
  'workflow',
  'memory',
  'rag',
  'tools',
  'llm',
  'prompts',
  'hooks',
  'subagents',
  'utils',
  'other',
];

// Layer descriptions
const LAYER_DESCRIPTIONS: Record<string, string> = {
  core: 'Entry points - CLI and main orchestration',
  workflow: 'Task planning and orchestration',
  memory: 'Working, episodic, and semantic memory',
  rag: 'Retrieval-augmented generation and indexing',
  tools: 'Executable tools for file, git, code operations',
  llm: 'Language model integration and backends',
  prompts: 'System and tool prompts',
  hooks: 'Event-driven extensibility system',
  subagents: 'Specialized autonomous agents',
  utils: 'Shared utilities and helpers',
  other: 'Miscellaneous components',
};

type ViewMode = 'diagram' | 'list';

export default function ArchitectureTab() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [componentsByLayer, setComponentsByLayer] = useState<Record<string, Component[]>>({});
  const [selectedComponent, setSelectedComponent] = useState<Component | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('diagram');
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      const components = await getAllComponents();

      // Group components by layer
      const grouped: Record<string, Component[]> = {};
      components.forEach((comp) => {
        if (!grouped[comp.layer]) {
          grouped[comp.layer] = [];
        }
        grouped[comp.layer].push(comp);
      });

      // Sort components within each layer by name
      Object.keys(grouped).forEach((layer) => {
        grouped[layer].sort((a, b) => a.name.localeCompare(b.name));
      });

      setComponentsByLayer(grouped);
    } catch (err) {
      console.error('Failed to load architecture:', err);
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to load architecture data. Make sure the server is running.'
      );
    } finally {
      setLoading(false);
    }
  };

  const handleComponentClick = (component: Component) => {
    setSelectedComponent(component);
    setDrawerOpen(true);
  };

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
  };

  const getTotalComponents = () => {
    return Object.values(componentsByLayer).reduce((sum, comps) => sum + comps.length, 0);
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '600px' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      </Box>
    );
  }

  const handleViewModeChange = (_event: React.MouseEvent<HTMLElement>, newMode: ViewMode | null) => {
    if (newMode !== null) {
      setViewMode(newMode);
    }
  };

  const handleLayerClick = (layerName: string) => {
    setSelectedLayer(layerName);
  };

  const handleBackToOverview = () => {
    setSelectedLayer(null);
  };

  const handleComponentClickFromDiagram = (componentId: string) => {
    // Find the component by ID
    const component = Object.values(componentsByLayer)
      .flat()
      .find((c) => c.id === componentId);

    if (component) {
      handleComponentClick(component);
    }
  };

  const renderDiagramView = () => {
    if (selectedLayer) {
      // Level 2: Layer Detail view - taller for better component visibility
      return (
        <Box sx={{ height: '900px', width: '100%' }}>
          <LayerDetailDiagram
            layerName={selectedLayer}
            onBack={handleBackToOverview}
            onComponentClick={handleComponentClickFromDiagram}
          />
        </Box>
      );
    }

    // Level 1: Layer Overview
    return (
      <Box sx={{ height: '700px', width: '100%', display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" sx={{ color: '#94a3b8', fontStyle: 'italic' }}>
            Double-click any layer to view its components and relationships
          </Typography>
        </Box>
        <Box sx={{ flex: 1, minHeight: 0 }}>
          <LayerOverviewDiagram onLayerClick={handleLayerClick} />
        </Box>
      </Box>
    );
  };

  const renderListView = () => {
    return (
      <>
        {/* Legend */}
        <Paper sx={{ p: 2, mb: 2, backgroundColor: '#f5f5f5' }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
            Layer Legend:
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
            {Object.entries(LAYER_COLORS).map(([layer, color]) => (
              <Box key={layer} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box
                  sx={{
                    width: 16,
                    height: 16,
                    backgroundColor: color,
                    border: '1px solid #333',
                    borderRadius: '2px',
                  }}
                />
                <Typography variant="caption" sx={{ textTransform: 'capitalize' }}>
                  {layer}
                </Typography>
              </Box>
            ))}
          </Box>
        </Paper>

        {/* Layer Accordions */}
        <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
          {LAYER_ORDER.filter((layer) => componentsByLayer[layer]).map((layer) => {
            const components = componentsByLayer[layer];
            const layerColor = LAYER_COLORS[layer] || LAYER_COLORS.other;

            return (
              <Accordion
                key={layer}
                sx={{
                  mb: 1,
                  '&:before': { display: 'none' },
                  boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
                }}
              >
                <AccordionSummary
                  expandIcon={<ExpandMoreIcon />}
                  sx={{
                    backgroundColor: layerColor,
                    color: '#fff',
                    '&:hover': {
                      backgroundColor: layerColor,
                      filter: 'brightness(1.1)',
                    },
                    '& .MuiAccordionSummary-content': {
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    },
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', textTransform: 'capitalize' }}>
                      {layer}
                    </Typography>
                    <Chip
                      label={`${components.length} component${components.length !== 1 ? 's' : ''}`}
                      size="small"
                      sx={{
                        backgroundColor: 'rgba(255,255,255,0.2)',
                        color: '#fff',
                        fontWeight: 'bold',
                      }}
                    />
                  </Box>
                  <Typography variant="body2" sx={{ fontStyle: 'italic', opacity: 0.9 }}>
                    {LAYER_DESCRIPTIONS[layer]}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0 }}>
                  <List sx={{ width: '100%' }}>
                    {components.map((component, index) => (
                      <ListItem
                        key={component.id}
                        disablePadding
                        sx={{
                          borderBottom: index < components.length - 1 ? '1px solid #eee' : 'none',
                        }}
                      >
                        <ListItemButton onClick={() => handleComponentClick(component)}>
                          <ListItemText
                            primary={
                              <Typography variant="body1" sx={{ fontWeight: 500 }}>
                                {component.name}
                              </Typography>
                            }
                            secondary={
                              <Typography variant="body2" sx={{ color: '#666' }}>
                                {component.description || 'No description available'}
                              </Typography>
                            }
                          />
                        </ListItemButton>
                      </ListItem>
                    ))}
                  </List>
                </AccordionDetails>
              </Accordion>
            );
          })}
        </Box>
      </>
    );
  };

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h4" sx={{ color: '#f1f5f9', mb: 1, fontWeight: 'bold' }}>
            🏗️ Architecture Layers
          </Typography>
          <Typography variant="body2" sx={{ color: '#cbd5e1' }}>
            {getTotalComponents()} components organized in {Object.keys(componentsByLayer).length} layers
            {viewMode === 'list' && ' • Click any layer to expand • Click component for details'}
          </Typography>
        </Box>
        <ToggleButtonGroup
          value={viewMode}
          exclusive
          onChange={handleViewModeChange}
          aria-label="view mode"
          size="small"
          sx={{ height: '40px' }}
        >
          <ToggleButton value="diagram" aria-label="diagram view">
            <AccountTreeIcon sx={{ mr: 1 }} /> Diagram
          </ToggleButton>
          <ToggleButton value="list" aria-label="list view">
            <ViewListIcon sx={{ mr: 1 }} /> List
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {/* Conditional View Rendering */}
      {viewMode === 'diagram' ? renderDiagramView() : renderListView()}

      {/* Component Details Drawer */}
      <Drawer anchor="right" open={drawerOpen} onClose={handleCloseDrawer}>
        <Box sx={{ width: 400, p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h5" sx={{ fontWeight: 'bold' }}>
              Component Details
            </Typography>
            <IconButton onClick={handleCloseDrawer}>
              <CloseIcon />
            </IconButton>
          </Box>

          <Divider sx={{ mb: 2 }} />

          {selectedComponent && (
            <Box>
              <Box sx={{ mb: 3 }}>
                <Typography variant="overline" sx={{ color: '#666' }}>
                  Name
                </Typography>
                <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
                  {selectedComponent.name}
                </Typography>
              </Box>

              <Box sx={{ mb: 3 }}>
                <Typography variant="overline" sx={{ color: '#666' }}>
                  Layer
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                  <Box
                    sx={{
                      width: 16,
                      height: 16,
                      backgroundColor: LAYER_COLORS[selectedComponent.layer] || LAYER_COLORS.other,
                      border: '1px solid #333',
                      borderRadius: '2px',
                    }}
                  />
                  <Typography variant="body1" sx={{ textTransform: 'capitalize' }}>
                    {selectedComponent.layer}
                  </Typography>
                </Box>
              </Box>

              <Box sx={{ mb: 3 }}>
                <Typography variant="overline" sx={{ color: '#666' }}>
                  Description
                </Typography>
                <Typography variant="body1">
                  {selectedComponent.description || 'No description available'}
                </Typography>
              </Box>

              {selectedComponent.file_path && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="overline" sx={{ color: '#666' }}>
                    File Path
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{
                      fontFamily: 'monospace',
                      backgroundColor: '#f5f5f5',
                      p: 1,
                      borderRadius: 1,
                      wordBreak: 'break-all',
                    }}
                  >
                    {selectedComponent.file_path}
                  </Typography>
                </Box>
              )}

              <Box>
                <Typography variant="overline" sx={{ color: '#666' }}>
                  Component ID
                </Typography>
                <Typography variant="caption" sx={{ color: '#999', fontFamily: 'monospace' }}>
                  {selectedComponent.id}
                </Typography>
              </Box>
            </Box>
          )}
        </Box>
      </Drawer>
    </Box>
  );
}
