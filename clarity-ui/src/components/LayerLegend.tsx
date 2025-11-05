import { Box, Typography, Paper, Chip } from '@mui/material';

const LAYER_INFO: Record<string, { color: string; description: string; purpose: string }> = {
  core: {
    color: '#646cff',
    description: 'Core Agent',
    purpose: 'Main orchestration and coordination logic'
  },
  memory: {
    color: '#4CAF50',
    description: 'Memory System',
    purpose: 'Working, episodic, and semantic memory management'
  },
  rag: {
    color: '#FF9800',
    description: 'RAG System',
    purpose: 'Retrieval-Augmented Generation with AST indexing'
  },
  workflow: {
    color: '#9C27B0',
    description: 'Workflow Engine',
    purpose: 'Task analysis, planning, execution, and verification'
  },
  tools: {
    color: '#2196F3',
    description: 'Tools',
    purpose: 'File operations, git, code analysis, system tools'
  },
  llm: {
    color: '#F44336',
    description: 'LLM Backends',
    purpose: 'AI model integrations (OpenAI, Alibaba, etc.)'
  },
  prompts: {
    color: '#00BCD4',
    description: 'Prompts',
    purpose: 'System prompts and prompt management'
  },
  hooks: {
    color: '#FFEB3B',
    description: 'Event Hooks',
    purpose: 'Event-driven extensibility and callbacks'
  },
  subagents: {
    color: '#795548',
    description: 'Subagents',
    purpose: 'Specialized agents for specific tasks'
  },
  utils: {
    color: '#607D8B',
    description: 'Utilities',
    purpose: 'Helper functions and common utilities'
  },
};

interface LayerLegendProps {
  componentsByLayer: Record<string, number>;
  onLayerClick?: (layer: string) => void;
}

const LayerLegend: React.FC<LayerLegendProps> = ({ componentsByLayer, onLayerClick }) => {
  const layers = Object.keys(LAYER_INFO).filter((layer) => componentsByLayer[layer] > 0);

  return (
    <Paper
      elevation={3}
      sx={{
        position: 'absolute',
        top: 80,
        left: 20,
        width: 340,
        maxHeight: '80vh',
        overflow: 'auto',
        p: 2,
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        backdropFilter: 'blur(10px)',
        zIndex: 1000,
      }}
    >
      <Typography variant="h6" gutterBottom sx={{ color: '#fff', mb: 2 }}>
        Architecture Layers
      </Typography>

      <Typography variant="caption" sx={{ color: 'rgba(255, 255, 255, 0.6)', display: 'block', mb: 2 }}>
        Click a layer to highlight its components
      </Typography>

      {layers.map((layer) => {
        const info = LAYER_INFO[layer];
        const count = componentsByLayer[layer] || 0;

        return (
          <Box
            key={layer}
            onClick={() => onLayerClick?.(layer)}
            sx={{
              mb: 1.5,
              p: 1.5,
              borderRadius: 1,
              border: `2px solid ${info.color}`,
              backgroundColor: 'rgba(0, 0, 0, 0.3)',
              cursor: onLayerClick ? 'pointer' : 'default',
              transition: 'all 0.2s',
              '&:hover': onLayerClick
                ? {
                    backgroundColor: `${info.color}20`,
                    transform: 'translateX(5px)',
                  }
                : {},
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography
                variant="subtitle2"
                sx={{
                  color: info.color,
                  fontWeight: 'bold',
                  textTransform: 'uppercase',
                }}
              >
                {info.description}
              </Typography>
              <Chip
                label={`${count} components`}
                size="small"
                sx={{
                  height: 20,
                  fontSize: '0.7rem',
                  backgroundColor: `${info.color}40`,
                  color: info.color,
                }}
              />
            </Box>
            <Typography variant="caption" sx={{ color: 'rgba(255, 255, 255, 0.7)' }}>
              {info.purpose}
            </Typography>
          </Box>
        );
      })}

      <Box sx={{ mt: 2, pt: 2, borderTop: '1px solid rgba(255, 255, 255, 0.1)' }}>
        <Typography variant="caption" sx={{ color: 'rgba(255, 255, 255, 0.5)' }}>
          💡 Tip: Zoom in/out with mouse wheel, pan by dragging canvas
        </Typography>
      </Box>
    </Paper>
  );
};

export default LayerLegend;
