import { Box, Typography } from '@mui/material';

export default function FilesTab() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" sx={{ color: '#333', mb: 2, fontWeight: 'bold' }}>
        📁 File Explorer
      </Typography>
      <Typography variant="body1" sx={{ color: '#666' }}>
        File tree explorer with component mapping coming soon...
      </Typography>
      <Typography variant="body2" sx={{ color: '#999', mt: 2 }}>
        This will display file tree (left) + details panel (right) showing file→component→layer mapping
      </Typography>
    </Box>
  );
}
