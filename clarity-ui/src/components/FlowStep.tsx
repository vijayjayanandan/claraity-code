import { Box, Typography, Paper } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';

interface FlowStepProps {
  stepNumber: number;
  stepName: string;
  description: string;
  activeLayers: string[];
  color: string;
  isCheckpoint?: boolean;
  isLast?: boolean;
}

const FlowStep: React.FC<FlowStepProps> = ({
  stepNumber,
  stepName,
  description,
  activeLayers,
  color,
  isCheckpoint = false,
  isLast = false,
}) => {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mb: 2 }}>
      {/* Step Card */}
      <Paper
        elevation={isCheckpoint ? 8 : 3}
        sx={{
          width: '100%',
          maxWidth: 600,
          p: 3,
          backgroundColor: isCheckpoint ? `${color}20` : 'rgba(0, 0, 0, 0.6)',
          border: `3px solid ${color}`,
          borderRadius: 2,
          position: 'relative',
          transition: 'all 0.3s ease',
          '&:hover': {
            transform: 'translateY(-4px)',
            boxShadow: `0 8px 24px ${color}40`,
          },
        }}
      >
        {/* Checkpoint Badge */}
        {isCheckpoint && (
          <Box
            sx={{
              position: 'absolute',
              top: -12,
              right: 20,
              backgroundColor: '#FFC107',
              color: '#000',
              px: 2,
              py: 0.5,
              borderRadius: 2,
              fontWeight: 'bold',
              fontSize: '0.75rem',
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              animation: 'pulse 2s infinite',
              '@keyframes pulse': {
                '0%, 100%': { transform: 'scale(1)' },
                '50%': { transform: 'scale(1.05)' },
              },
            }}
          >
            <CheckCircleIcon sx={{ fontSize: 16 }} />
            USER APPROVAL
          </Box>
        )}

        {/* Step Number Circle */}
        <Box
          sx={{
            position: 'absolute',
            top: -20,
            left: 20,
            width: 40,
            height: 40,
            borderRadius: '50%',
            backgroundColor: color,
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 'bold',
            fontSize: '1.2rem',
            boxShadow: `0 4px 12px ${color}60`,
          }}
        >
          {stepNumber}
        </Box>

        {/* Step Content */}
        <Box sx={{ mt: 1 }}>
          <Typography
            variant="h6"
            sx={{
              color: color,
              fontWeight: 'bold',
              mb: 1,
              textTransform: 'uppercase',
            }}
          >
            {stepName}
          </Typography>

          <Typography variant="body2" sx={{ color: 'rgba(255, 255, 255, 0.8)', mb: 2 }}>
            {description}
          </Typography>

          {/* Active Layers */}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
            <Typography variant="caption" sx={{ color: 'rgba(255, 255, 255, 0.5)', mr: 1 }}>
              Uses:
            </Typography>
            {activeLayers.map((layer) => (
              <Box
                key={layer}
                sx={{
                  px: 1,
                  py: 0.25,
                  borderRadius: 1,
                  backgroundColor: `${color}30`,
                  border: `1px solid ${color}`,
                  fontSize: '0.7rem',
                  color: color,
                  fontWeight: 'bold',
                }}
              >
                {layer}
              </Box>
            ))}
          </Box>
        </Box>
      </Paper>

      {/* Arrow to Next Step */}
      {!isLast && (
        <Box
          sx={{
            my: 2,
            animation: 'bounce 2s infinite',
            '@keyframes bounce': {
              '0%, 100%': { transform: 'translateY(0)' },
              '50%': { transform: 'translateY(8px)' },
            },
          }}
        >
          <ArrowDownwardIcon
            sx={{
              fontSize: 40,
              color: color,
              opacity: 0.6,
            }}
          />
        </Box>
      )}
    </Box>
  );
};

export default FlowStep;
