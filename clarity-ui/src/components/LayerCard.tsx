import { useState } from 'react';
import { Box, Typography, Paper, Chip, Collapse, IconButton } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import MemoryIcon from '@mui/icons-material/Memory';
import SearchIcon from '@mui/icons-material/Search';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import BuildIcon from '@mui/icons-material/Build';
import PsychologyIcon from '@mui/icons-material/Psychology';
import ChatIcon from '@mui/icons-material/Chat';
import WebhookIcon from '@mui/icons-material/Webhook';
import GroupsIcon from '@mui/icons-material/Groups';
import SettingsIcon from '@mui/icons-material/Settings';

const LAYER_ICONS: Record<string, React.ReactNode> = {
  core: <AccountTreeIcon sx={{ fontSize: 40 }} />,
  memory: <MemoryIcon sx={{ fontSize: 40 }} />,
  rag: <SearchIcon sx={{ fontSize: 40 }} />,
  workflow: <AccountBalanceWalletIcon sx={{ fontSize: 40 }} />,
  tools: <BuildIcon sx={{ fontSize: 40 }} />,
  llm: <PsychologyIcon sx={{ fontSize: 40 }} />,
  prompts: <ChatIcon sx={{ fontSize: 40 }} />,
  hooks: <WebhookIcon sx={{ fontSize: 40 }} />,
  subagents: <GroupsIcon sx={{ fontSize: 40 }} />,
  utils: <SettingsIcon sx={{ fontSize: 40 }} />,
};

interface LayerCardProps {
  layer: string;
  description: string;
  purpose: string;
  componentCount: number;
  color: string;
  onViewDetails?: () => void;
}

const LayerCard: React.FC<LayerCardProps> = ({
  layer,
  description,
  purpose,
  componentCount,
  color,
  onViewDetails,
}) => {
  const [expanded, setExpanded] = useState(false);

  const icon = LAYER_ICONS[layer] || LAYER_ICONS.utils;

  return (
    <Paper
      elevation={4}
      sx={{
        p: 2.5,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        border: `2px solid ${color}`,
        borderRadius: 2,
        transition: 'all 0.3s ease',
        cursor: 'pointer',
        '&:hover': {
          transform: 'translateY(-4px)',
          boxShadow: `0 12px 32px ${color}40`,
          backgroundColor: `${color}15`,
        },
      }}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 1.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flex: 1 }}>
          {/* Icon */}
          <Box
            sx={{
              color: color,
              opacity: 0.9,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {icon}
          </Box>

          {/* Layer Name */}
          <Box sx={{ flex: 1 }}>
            <Typography
              variant="h6"
              sx={{
                color: color,
                fontWeight: 'bold',
                textTransform: 'uppercase',
                mb: 0.5,
              }}
            >
              {description}
            </Typography>
            <Chip
              label={`${componentCount} ${componentCount === 1 ? 'Component' : 'Components'}`}
              size="small"
              sx={{
                height: 20,
                fontSize: '0.7rem',
                backgroundColor: `${color}40`,
                color: color,
                fontWeight: 'bold',
              }}
            />
          </Box>
        </Box>

        {/* Expand Button */}
        <IconButton
          size="small"
          sx={{ color: color }}
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
        >
          {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
        </IconButton>
      </Box>

      {/* Purpose */}
      <Typography
        variant="body2"
        sx={{
          color: 'rgba(255, 255, 255, 0.7)',
          mb: 1,
        }}
      >
        {purpose}
      </Typography>

      {/* Expanded Content */}
      <Collapse in={expanded}>
        <Box sx={{ mt: 2, pt: 2, borderTop: `1px solid ${color}40` }}>
          <Typography variant="caption" sx={{ color: 'rgba(255, 255, 255, 0.5)', display: 'block', mb: 1 }}>
            This layer provides:
          </Typography>

          {/* Layer-specific details */}
          {layer === 'core' && (
            <Box component="ul" sx={{ pl: 2, my: 0, color: 'rgba(255, 255, 255, 0.7)' }}>
              <Typography component="li" variant="caption">Main orchestrator (CodingAgent)</Typography>
              <Typography component="li" variant="caption">Workflow vs Direct decision logic</Typography>
              <Typography component="li" variant="caption">Tool execution loop management</Typography>
            </Box>
          )}

          {layer === 'memory' && (
            <Box component="ul" sx={{ pl: 2, my: 0, color: 'rgba(255, 255, 255, 0.7)' }}>
              <Typography component="li" variant="caption">Working Memory (40% of context)</Typography>
              <Typography component="li" variant="caption">Episodic Memory (conversation history)</Typography>
              <Typography component="li" variant="caption">Semantic Memory (long-term knowledge)</Typography>
            </Box>
          )}

          {layer === 'workflow' && (
            <Box component="ul" sx={{ pl: 2, my: 0, color: 'rgba(255, 255, 255, 0.7)' }}>
              <Typography component="li" variant="caption">TaskAnalyzer (classify & estimate)</Typography>
              <Typography component="li" variant="caption">TaskPlanner (create execution plan)</Typography>
              <Typography component="li" variant="caption">ExecutionEngine (run steps)</Typography>
              <Typography component="li" variant="caption">VerificationLayer (test changes)</Typography>
            </Box>
          )}

          {layer === 'rag' && (
            <Box component="ul" sx={{ pl: 2, my: 0, color: 'rgba(255, 255, 255, 0.7)' }}>
              <Typography component="li" variant="caption">AST-based code parsing</Typography>
              <Typography component="li" variant="caption">Hybrid semantic + keyword search</Typography>
              <Typography component="li" variant="caption">ChromaDB vector storage</Typography>
            </Box>
          )}

          {layer === 'tools' && (
            <Box component="ul" sx={{ pl: 2, my: 0, color: 'rgba(255, 255, 255, 0.7)' }}>
              <Typography component="li" variant="caption">File operations (read, write, edit)</Typography>
              <Typography component="li" variant="caption">Git operations (commit, diff, log)</Typography>
              <Typography component="li" variant="caption">Code analysis & system commands</Typography>
            </Box>
          )}

          {onViewDetails && (
            <Box
              sx={{
                mt: 2,
                pt: 1.5,
                textAlign: 'center',
                borderTop: `1px solid ${color}40`,
              }}
            >
              <Typography
                variant="caption"
                sx={{
                  color: color,
                  fontWeight: 'bold',
                  cursor: 'pointer',
                  '&:hover': {
                    textDecoration: 'underline',
                  },
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  onViewDetails();
                }}
              >
                → View all {componentCount} components in detailed view
              </Typography>
            </Box>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
};

export default LayerCard;
