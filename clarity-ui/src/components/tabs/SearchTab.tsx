import { Box, Typography } from '@mui/material';

export default function SearchTab() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" sx={{ color: '#333', mb: 2, fontWeight: 'bold' }}>
        🔍 Universal Search
      </Typography>
      <Typography variant="body1" sx={{ color: '#666' }}>
        Search across components, files, artifacts, and flow steps coming soon...
      </Typography>
      <Typography variant="body2" sx={{ color: '#999', mt: 2 }}>
        This will provide universal search with navigation context to all tabs
      </Typography>
    </Box>
  );
}
