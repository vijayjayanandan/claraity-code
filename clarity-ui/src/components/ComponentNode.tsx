import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Box, Typography, Chip } from '@mui/material';
import type { Component } from '../types';

interface ComponentNodeData {
  component: Component;
  color: string;
  selected: boolean;
}

const ComponentNode: React.FC<NodeProps<ComponentNodeData>> = ({ data }) => {
  const { component, color, selected } = data;

  return (
    <Box
      sx={{
        padding: 2,
        borderRadius: 2,
        border: selected ? `3px solid ${color}` : `2px solid ${color}`,
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        minWidth: 180,
        maxWidth: 250,
        boxShadow: selected ? `0 0 20px ${color}` : '0 4px 6px rgba(0, 0, 0, 0.3)',
        cursor: 'pointer',
        transition: 'all 0.3s ease',
        '&:hover': {
          boxShadow: `0 0 15px ${color}`,
          transform: 'scale(1.05)',
        },
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />

      <Typography
        variant="subtitle2"
        sx={{
          fontWeight: 'bold',
          color: color,
          marginBottom: 0.5,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {component.name}
      </Typography>

      <Typography
        variant="caption"
        sx={{
          color: 'rgba(255, 255, 255, 0.7)',
          display: 'block',
          marginBottom: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {component.purpose || 'No description'}
      </Typography>

      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        <Chip
          label={component.type}
          size="small"
          sx={{
            height: 20,
            fontSize: '0.7rem',
            backgroundColor: 'rgba(255, 255, 255, 0.1)',
          }}
        />
        <Chip
          label={component.status}
          size="small"
          sx={{
            height: 20,
            fontSize: '0.7rem',
            backgroundColor:
              component.status === 'completed'
                ? 'rgba(76, 175, 80, 0.3)'
                : component.status === 'in_progress'
                ? 'rgba(255, 152, 0, 0.3)'
                : 'rgba(158, 158, 158, 0.3)',
          }}
        />
      </Box>

      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </Box>
  );
};

export default memo(ComponentNode);
