import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  CardActionArea,
  LinearProgress,
  Chip,
  CircularProgress,
  Alert,
} from '@mui/material';
import { getCapabilities } from '../../services/api';
import type { Capability } from '../../types';

interface DashboardTabProps {
  onNavigateToArchitecture?: (layer: string) => void;
}

export default function DashboardTab({ onNavigateToArchitecture }: DashboardTabProps) {
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadCapabilities();
  }, []);

  const loadCapabilities = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getCapabilities();
      setCapabilities(data);
    } catch (err) {
      console.error('Failed to load capabilities:', err);
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to load capabilities. Make sure the server is running.'
      );
    } finally {
      setLoading(false);
    }
  };

  const getReadinessColor = (readiness: number) => {
    if (readiness >= 90) return 'success';
    if (readiness >= 70) return 'warning';
    return 'error';
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
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

  return (
    <Box sx={{ animation: 'fadeIn 0.3s ease-in' }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ color: '#f1f5f9', mb: 1, fontWeight: 'bold' }}>
          🎯 System Capabilities
        </Typography>
        <Typography variant="body1" sx={{ color: '#cbd5e1' }}>
          Overview of the AI Coding Agent's core capabilities and their readiness status
        </Typography>
      </Box>

      {/* Capability Cards Grid */}
      <Grid container spacing={3}>
        {capabilities.map((capability) => (
          <Grid item xs={12} sm={6} md={4} key={capability.name}>
            <Card
              sx={{
                height: '100%',
                background: 'linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)',
                borderLeft: '5px solid #667eea',
                transition: 'all 0.3s ease',
                '&:hover': {
                  transform: 'translateY(-5px)',
                  boxShadow: '0 10px 30px rgba(0,0,0,0.15)',
                },
              }}
            >
              <CardActionArea
                onClick={() => onNavigateToArchitecture?.(capability.layer)}
                sx={{ height: '100%' }}
              >
                <CardContent>
                  {/* Capability Name */}
                  <Typography variant="h6" sx={{ color: '#333', mb: 1, fontWeight: 'bold' }}>
                    {capability.name}
                  </Typography>

                  {/* Description */}
                  <Typography variant="body2" sx={{ color: '#666', mb: 2 }}>
                    {capability.description}
                  </Typography>

                  {/* Readiness Bar */}
                  <Box sx={{ mb: 1 }}>
                    <LinearProgress
                      variant="determinate"
                      value={capability.readiness}
                      color={getReadinessColor(capability.readiness)}
                      sx={{
                        height: 8,
                        borderRadius: 10,
                        backgroundColor: '#e9ecef',
                        '& .MuiLinearProgress-bar': {
                          background: 'linear-gradient(90deg, #667eea 0%, #764ba2 100%)',
                          borderRadius: 10,
                        },
                      }}
                    />
                    <Typography variant="caption" sx={{ color: '#666', mt: 0.5, display: 'block' }}>
                      {capability.readiness}% Ready
                    </Typography>
                  </Box>

                  {/* Component Pills */}
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 2 }}>
                    {capability.components.map((component) => (
                      <Chip
                        key={component}
                        label={component}
                        size="small"
                        sx={{
                          backgroundColor: 'white',
                          color: '#667eea',
                          fontWeight: 500,
                          fontSize: '0.75rem',
                        }}
                      />
                    ))}
                  </Box>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Entry Points Section */}
      <Box
        sx={{
          mt: 4,
          p: 3,
          background: '#e8f5e9',
          borderLeft: '5px solid #4caf50',
          borderRadius: '8px',
        }}
      >
        <Typography variant="h6" sx={{ color: '#333', mb: 2, fontWeight: 'bold' }}>
          📍 Main Entry Points
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Box sx={{ p: 1.5, background: 'white', borderRadius: '5px' }}>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
              CLI Interface
            </Typography>
            <Typography
              variant="body2"
              sx={{ fontFamily: 'Courier New, monospace', color: '#667eea', fontSize: '0.9em' }}
            >
              src/cli.py:45
            </Typography>
          </Box>
          <Box sx={{ p: 1.5, background: 'white', borderRadius: '5px' }}>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
              Main Agent
            </Typography>
            <Typography
              variant="body2"
              sx={{ fontFamily: 'Courier New, monospace', color: '#667eea', fontSize: '0.9em' }}
            >
              src/core/agent.py:156
            </Typography>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
