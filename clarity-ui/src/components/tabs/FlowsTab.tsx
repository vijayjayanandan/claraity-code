import { Box, Typography } from '@mui/material';

export default function FlowsTab() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" sx={{ color: '#333', mb: 2, fontWeight: 'bold' }}>
        🔄 Execution Flows
      </Typography>
      <Typography variant="body1" sx={{ color: '#666' }}>
        Hybrid timeline + flowchart visualization coming soon...
      </Typography>
      <Typography variant="body2" sx={{ color: '#999', mt: 2 }}>
        This will display workflow execution flow with 3-level hierarchy
      </Typography>
    </Box>
  );
}
