import {
  Box,
  Typography,
  IconButton,
  Chip,
  List,
  ListItem,
  ListItemText,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Paper,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CodeIcon from '@mui/icons-material/Code';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import LightbulbIcon from '@mui/icons-material/Lightbulb';
import type { ComponentDetail } from '../types';

interface ComponentDetailsProps {
  component: ComponentDetail;
  onClose: () => void;
}

const ComponentDetails: React.FC<ComponentDetailsProps> = ({ component, onClose }) => {
  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box
        sx={{
          p: 2,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'start',
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="h6" gutterBottom>
            {component.name}
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 1 }}>
            <Chip label={component.layer} size="small" color="primary" />
            <Chip label={component.type} size="small" variant="outlined" />
            <Chip
              label={component.status}
              size="small"
              color={
                component.status === 'completed'
                  ? 'success'
                  : component.status === 'in_progress'
                  ? 'warning'
                  : 'default'
              }
            />
          </Box>
        </Box>
        <IconButton onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </Box>

      {/* Content */}
      <Box sx={{ flexGrow: 1, overflow: 'auto', p: 2 }}>
        {/* Purpose */}
        {component.purpose && (
          <Paper elevation={1} sx={{ p: 2, mb: 2, backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
            <Typography variant="subtitle2" gutterBottom color="primary">
              Purpose
            </Typography>
            <Typography variant="body2">{component.purpose}</Typography>
          </Paper>
        )}

        {/* Business Value */}
        {component.business_value && (
          <Paper elevation={1} sx={{ p: 2, mb: 2, backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
            <Typography variant="subtitle2" gutterBottom color="primary">
              Business Value
            </Typography>
            <Typography variant="body2">{component.business_value}</Typography>
          </Paper>
        )}

        {/* Design Rationale */}
        {component.design_rationale && (
          <Paper elevation={1} sx={{ p: 2, mb: 2, backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
            <Typography variant="subtitle2" gutterBottom color="primary">
              Design Rationale
            </Typography>
            <Typography variant="body2">{component.design_rationale}</Typography>
          </Paper>
        )}

        {/* Responsibilities */}
        {component.responsibilities && component.responsibilities.length > 0 && (
          <Accordion defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">
                Responsibilities ({component.responsibilities.length})
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <List dense>
                {component.responsibilities.map((resp, index) => (
                  <ListItem key={index}>
                    <ListItemText primary={resp} />
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Code Artifacts */}
        {component.artifacts && component.artifacts.length > 0 && (
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <CodeIcon sx={{ mr: 1 }} fontSize="small" />
              <Typography variant="subtitle2">
                Code Artifacts ({component.artifacts.length})
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <List dense>
                {component.artifacts.map((artifact) => (
                  <ListItem key={artifact.id}>
                    <ListItemText
                      primary={artifact.name}
                      secondary={
                        <>
                          <Typography component="span" variant="caption" display="block">
                            {artifact.file_path}
                            {artifact.line_start &&
                              ` (lines ${artifact.line_start}-${artifact.line_end})`}
                          </Typography>
                          {artifact.description && (
                            <Typography component="span" variant="caption" color="text.secondary">
                              {artifact.description}
                            </Typography>
                          )}
                        </>
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </AccordionDetails>
          </Accordion>
        )}

        {/* Design Decisions */}
        {component.decisions && component.decisions.length > 0 && (
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <LightbulbIcon sx={{ mr: 1 }} fontSize="small" />
              <Typography variant="subtitle2">
                Design Decisions ({component.decisions.length})
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              {component.decisions.map((decision) => (
                <Paper
                  key={decision.id}
                  elevation={1}
                  sx={{ p: 2, mb: 1, backgroundColor: 'rgba(255, 255, 255, 0.03)' }}
                >
                  <Chip label={decision.decision_type} size="small" sx={{ mb: 1 }} />
                  <Typography variant="subtitle2" gutterBottom>
                    {decision.question}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    <strong>Solution:</strong> {decision.chosen_solution}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    <strong>Rationale:</strong> {decision.rationale}
                  </Typography>
                  {decision.alternatives_considered &&
                    decision.alternatives_considered.length > 0 && (
                      <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                        <strong>Alternatives:</strong>{' '}
                        {decision.alternatives_considered.join(', ')}
                      </Typography>
                    )}
                  {decision.trade_offs && (
                    <Typography variant="caption" display="block" color="warning.main">
                      <strong>Trade-offs:</strong> {decision.trade_offs}
                    </Typography>
                  )}
                </Paper>
              ))}
            </AccordionDetails>
          </Accordion>
        )}

        {/* Relationships */}
        {component.relationships &&
          (component.relationships.outgoing.length > 0 ||
            component.relationships.incoming.length > 0) && (
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <AccountTreeIcon sx={{ mr: 1 }} fontSize="small" />
                <Typography variant="subtitle2">
                  Relationships (
                  {component.relationships.outgoing.length +
                    component.relationships.incoming.length}
                  )
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                {component.relationships.outgoing.length > 0 && (
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="caption" color="primary" display="block" gutterBottom>
                      Outgoing ({component.relationships.outgoing.length})
                    </Typography>
                    <List dense>
                      {component.relationships.outgoing.map((rel) => (
                        <ListItem key={rel.id}>
                          <ListItemText
                            primary={`→ ${rel.target_name || rel.target_id}`}
                            secondary={`${rel.relationship_type}${
                              rel.description ? ` - ${rel.description}` : ''
                            }`}
                          />
                        </ListItem>
                      ))}
                    </List>
                  </Box>
                )}
                {component.relationships.incoming.length > 0 && (
                  <Box>
                    <Typography variant="caption" color="secondary" display="block" gutterBottom>
                      Incoming ({component.relationships.incoming.length})
                    </Typography>
                    <List dense>
                      {component.relationships.incoming.map((rel) => (
                        <ListItem key={rel.id}>
                          <ListItemText
                            primary={`← ${rel.source_name || rel.source_id}`}
                            secondary={`${rel.relationship_type}${
                              rel.description ? ` - ${rel.description}` : ''
                            }`}
                          />
                        </ListItem>
                      ))}
                    </List>
                  </Box>
                )}
              </AccordionDetails>
            </Accordion>
          )}
      </Box>
    </Box>
  );
};

export default ComponentDetails;
