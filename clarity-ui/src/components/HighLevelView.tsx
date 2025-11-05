import { Box, Typography, Container } from '@mui/material';
import Person from '@mui/icons-material/Person';
import DoneAllIcon from '@mui/icons-material/DoneAll';
import FlowStep from './FlowStep';

const HighLevelView: React.FC = () => {
  const workflowSteps = [
    {
      stepNumber: 1,
      stepName: 'ANALYZING',
      description: 'TaskAnalyzer understands what needs to be done - classifies task type, estimates complexity, and identifies affected systems.',
      activeLayers: ['Core', 'Memory'],
      color: '#9C27B0', // Purple
      isCheckpoint: false,
    },
    {
      stepNumber: 2,
      stepName: 'PLANNING',
      description: 'TaskPlanner creates a detailed execution plan - breaks down task into steps, selects tools, and estimates effort.',
      activeLayers: ['Core', 'Workflow', 'Memory', 'RAG'],
      color: '#2196F3', // Blue
      isCheckpoint: false,
    },
    {
      stepNumber: 3,
      stepName: 'APPROVAL',
      description: 'User reviews the plan and decides whether to proceed. This is your control point!',
      activeLayers: ['Core'],
      color: '#FFC107', // Amber
      isCheckpoint: true,
    },
    {
      stepNumber: 4,
      stepName: 'EXECUTING',
      description: 'ExecutionEngine runs the plan - uses tools to read files, make changes, run commands, and interact with git.',
      activeLayers: ['Core', 'Workflow', 'Tools', 'RAG', 'Memory', 'LLM'],
      color: '#4CAF50', // Green
      isCheckpoint: false,
    },
    {
      stepNumber: 5,
      stepName: 'VERIFYING',
      description: 'VerificationLayer checks all changes - runs syntax checks, linters, and tests to ensure quality.',
      activeLayers: ['Workflow', 'Tools'],
      color: '#FF9800', // Orange
      isCheckpoint: false,
    },
    {
      stepNumber: 6,
      stepName: 'REPORTING',
      description: 'Summarizes what was accomplished - lists changes, test results, and any issues encountered.',
      activeLayers: ['Core', 'Memory'],
      color: '#00BCD4', // Cyan
      isCheckpoint: false,
    },
  ];

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ textAlign: 'center', mb: 6 }}>
        <Typography variant="h3" sx={{ color: '#646cff', fontWeight: 'bold', mb: 2 }}>
          The Journey
        </Typography>
        <Typography variant="h5" sx={{ color: 'rgba(255, 255, 255, 0.7)', mb: 3 }}>
          From User Request to Code Changes
        </Typography>
        <Typography variant="body1" sx={{ color: 'rgba(255, 255, 255, 0.6)', maxWidth: 600, mx: 'auto' }}>
          Our AI Coding Agent follows a carefully designed workflow with checkpoints to ensure you
          stay in control while maximizing automation.
        </Typography>
      </Box>

      {/* User Input */}
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mb: 4 }}>
        <Box
          sx={{
            width: 80,
            height: 80,
            borderRadius: '50%',
            backgroundColor: '#646cff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            mb: 2,
            boxShadow: '0 8px 24px rgba(100, 108, 255, 0.4)',
          }}
        >
          <Person sx={{ fontSize: 48, color: '#fff' }} />
        </Box>
        <Typography variant="h6" sx={{ color: '#fff', fontWeight: 'bold', mb: 1 }}>
          USER REQUEST
        </Typography>
        <Typography variant="body2" sx={{ color: 'rgba(255, 255, 255, 0.6)', textAlign: 'center', maxWidth: 400 }}>
          "Add user authentication" | "Fix bug in payment" | "Refactor database layer"
        </Typography>
      </Box>

      {/* Workflow Steps */}
      {workflowSteps.map((step, index) => (
        <FlowStep
          key={step.stepNumber}
          {...step}
          isLast={index === workflowSteps.length - 1}
        />
      ))}

      {/* Done State */}
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mt: 4, mb: 6 }}>
        <Box
          sx={{
            width: 80,
            height: 80,
            borderRadius: '50%',
            backgroundColor: '#4CAF50',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            mb: 2,
            boxShadow: '0 8px 24px rgba(76, 175, 80, 0.4)',
            animation: 'success 1s ease-in-out',
            '@keyframes success': {
              '0%': { transform: 'scale(0.8)', opacity: 0.5 },
              '50%': { transform: 'scale(1.1)' },
              '100%': { transform: 'scale(1)', opacity: 1 },
            },
          }}
        >
          <DoneAllIcon sx={{ fontSize: 48, color: '#fff' }} />
        </Box>
        <Typography variant="h6" sx={{ color: '#4CAF50', fontWeight: 'bold', mb: 1 }}>
          ✅ DONE
        </Typography>
        <Typography variant="body2" sx={{ color: 'rgba(255, 255, 255, 0.6)', textAlign: 'center', maxWidth: 400 }}>
          Code changes completed, tested, and ready for review!
        </Typography>
      </Box>

      {/* Key Benefits */}
      <Box
        sx={{
          mt: 6,
          p: 3,
          backgroundColor: 'rgba(100, 108, 255, 0.1)',
          border: '2px solid rgba(100, 108, 255, 0.3)',
          borderRadius: 2,
        }}
      >
        <Typography variant="h6" sx={{ color: '#646cff', mb: 2, fontWeight: 'bold' }}>
          🎯 Why This Workflow?
        </Typography>
        <Box component="ul" sx={{ color: 'rgba(255, 255, 255, 0.7)', pl: 3 }}>
          <Typography component="li" variant="body2" sx={{ mb: 1 }}>
            <strong>Transparency:</strong> You see exactly what the agent plans to do
          </Typography>
          <Typography component="li" variant="body2" sx={{ mb: 1 }}>
            <strong>Control:</strong> Approval checkpoint before any changes
          </Typography>
          <Typography component="li" variant="body2" sx={{ mb: 1 }}>
            <strong>Quality:</strong> Automatic verification catches issues early
          </Typography>
          <Typography component="li" variant="body2">
            <strong>Trust:</strong> Clear reporting of what was done and why
          </Typography>
        </Box>
      </Box>

      {/* Footer */}
      <Box sx={{ textAlign: 'center', mt: 6, opacity: 0.5 }}>
        <Typography variant="caption" sx={{ color: 'rgba(255, 255, 255, 0.5)' }}>
          💡 Scroll down to see the architectural layers that power this workflow
        </Typography>
      </Box>
    </Container>
  );
};

export default HighLevelView;
