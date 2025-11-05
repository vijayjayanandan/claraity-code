/**
 * BlueprintModal - 3-panel blueprint approval interface
 * Left: Component tree | Center: Selected component details | Right: Design decisions
 */

import {
  Dialog,
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Grid,
  Paper,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Chip,
  Divider,
  Button,
  TextField,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Alert,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import { useState } from 'react';
import { useBlueprintStore } from '../../stores/blueprintStore';
import type { Component } from '../../types/blueprint';

export default function BlueprintModal() {
  const {
    currentBlueprint,
    selectedComponent,
    isModalOpen,
    closeBlueprint,
    selectComponent,
    approve,
    reject,
  } = useBlueprintStore();

  const [showRejectForm, setShowRejectForm] = useState(false);
  const [feedback, setFeedback] = useState('');

  if (!currentBlueprint) return null;

  const handleApprove = () => {
    approve();
    setShowRejectForm(false);
    setFeedback('');
  };

  const handleRejectClick = () => {
    setShowRejectForm(true);
  };

  const handleRejectSubmit = () => {
    if (feedback.trim()) {
      reject(feedback);
      setShowRejectForm(false);
      setFeedback('');
    }
  };

  const handleClose = () => {
    closeBlueprint();
    setShowRejectForm(false);
    setFeedback('');
  };

  return (
    <Dialog fullScreen open={isModalOpen} onClose={handleClose}>
      {/* App Bar */}
      <AppBar sx={{ position: 'relative' }}>
        <Toolbar>
          <Typography sx={{ flex: 1 }} variant="h6" component="div">
            Blueprint Approval
          </Typography>
          <IconButton edge="end" color="inherit" onClick={handleClose}>
            <CloseIcon />
          </IconButton>
        </Toolbar>
      </AppBar>

      {/* Task Description */}
      <Box sx={{ p: 2, backgroundColor: 'background.paper', borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="h6" gutterBottom>
          Task: {currentBlueprint.task_description}
        </Typography>
        {currentBlueprint.estimated_complexity && (
          <Chip
            label={`Complexity: ${currentBlueprint.estimated_complexity}`}
            size="small"
            sx={{ mr: 1 }}
          />
        )}
        {currentBlueprint.estimated_time && (
          <Chip label={`Est. Time: ${currentBlueprint.estimated_time}`} size="small" />
        )}
      </Box>

      {/* 3-Panel Layout */}
      <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <Grid container sx={{ flex: 1, overflow: 'hidden' }}>
          {/* Left Panel: Component Tree */}
          <Grid item xs={3} sx={{ borderRight: 1, borderColor: 'divider', overflow: 'auto' }}>
            <Paper elevation={0} sx={{ height: '100%', borderRadius: 0 }}>
              <Box sx={{ p: 2, backgroundColor: 'primary.main', color: 'primary.contrastText' }}>
                <Typography variant="subtitle1" fontWeight="bold">
                  Components ({currentBlueprint.components.length})
                </Typography>
              </Box>
              <List>
                {currentBlueprint.components.map((component) => (
                  <ListItem key={component.name} disablePadding>
                    <ListItemButton
                      selected={selectedComponent?.name === component.name}
                      onClick={() => selectComponent(component)}
                    >
                      <ListItemText
                        primary={component.name}
                        secondary={
                          <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                            <Chip label={component.type} size="small" variant="outlined" />
                            {component.layer && (
                              <Chip label={component.layer} size="small" color="primary" />
                            )}
                          </Box>
                        }
                      />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>

              <Divider />

              {/* Summary Section */}
              <Box sx={{ p: 2 }}>
                <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
                  Summary
                </Typography>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  File Actions: {currentBlueprint.file_actions.length}
                </Typography>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Relationships: {currentBlueprint.relationships.length}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Design Decisions: {currentBlueprint.design_decisions.length}
                </Typography>
              </Box>
            </Paper>
          </Grid>

          {/* Center Panel: Component Details */}
          <Grid item xs={5} sx={{ borderRight: 1, borderColor: 'divider', overflow: 'auto' }}>
            <Paper elevation={0} sx={{ height: '100%', borderRadius: 0 }}>
              {selectedComponent ? (
                <Box sx={{ p: 3 }}>
                  <Box sx={{ mb: 3 }}>
                    <Typography variant="h5" gutterBottom>
                      {selectedComponent.name}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                      <Chip label={selectedComponent.type} color="primary" />
                      {selectedComponent.layer && (
                        <Chip label={selectedComponent.layer} variant="outlined" />
                      )}
                    </Box>
                  </Box>

                  <Divider sx={{ mb: 2 }} />

                  {/* Purpose */}
                  <Box sx={{ mb: 3 }}>
                    <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                      Purpose
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedComponent.purpose}
                    </Typography>
                  </Box>

                  {/* File Path */}
                  <Box sx={{ mb: 3 }}>
                    <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                      File Path
                    </Typography>
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ fontFamily: 'monospace', backgroundColor: 'grey.900', p: 1, borderRadius: 1 }}
                    >
                      {selectedComponent.file_path}
                    </Typography>
                  </Box>

                  {/* Responsibilities */}
                  {selectedComponent.responsibilities.length > 0 && (
                    <Box sx={{ mb: 3 }}>
                      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                        Responsibilities
                      </Typography>
                      <List dense>
                        {selectedComponent.responsibilities.map((resp, idx) => (
                          <ListItem key={idx}>
                            <ListItemText
                              primary={`• ${resp}`}
                              primaryTypographyProps={{ variant: 'body2', color: 'text.secondary' }}
                            />
                          </ListItem>
                        ))}
                      </List>
                    </Box>
                  )}

                  {/* Key Methods */}
                  {selectedComponent.key_methods.length > 0 && (
                    <Box sx={{ mb: 3 }}>
                      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                        Key Methods
                      </Typography>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                        {selectedComponent.key_methods.map((method, idx) => (
                          <Chip key={idx} label={method} variant="outlined" size="small" />
                        ))}
                      </Box>
                    </Box>
                  )}

                  {/* Dependencies */}
                  {selectedComponent.dependencies.length > 0 && (
                    <Box>
                      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                        Dependencies
                      </Typography>
                      <List dense>
                        {selectedComponent.dependencies.map((dep, idx) => (
                          <ListItem key={idx}>
                            <ListItemText
                              primary={dep}
                              primaryTypographyProps={{ variant: 'body2', color: 'text.secondary' }}
                            />
                          </ListItem>
                        ))}
                      </List>
                    </Box>
                  )}
                </Box>
              ) : (
                <Box
                  sx={{
                    height: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Typography variant="body1" color="text.secondary">
                    Select a component to view details
                  </Typography>
                </Box>
              )}
            </Paper>
          </Grid>

          {/* Right Panel: Design Decisions, Prerequisites, Risks */}
          <Grid item xs={4} sx={{ overflow: 'auto' }}>
            <Paper elevation={0} sx={{ height: '100%', borderRadius: 0 }}>
              <Box sx={{ p: 3 }}>
                {/* Design Decisions */}
                <Box sx={{ mb: 3 }}>
                  <Typography variant="h6" gutterBottom>
                    Design Decisions
                  </Typography>
                  {currentBlueprint.design_decisions.map((decision, idx) => (
                    <Accordion key={idx} defaultExpanded={idx === 0}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2">{decision.decision}</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Box>
                          <Typography variant="body2" fontWeight="bold" gutterBottom>
                            Rationale:
                          </Typography>
                          <Typography variant="body2" color="text.secondary" paragraph>
                            {decision.rationale}
                          </Typography>

                          {decision.alternatives_considered.length > 0 && (
                            <>
                              <Typography variant="body2" fontWeight="bold" gutterBottom>
                                Alternatives Considered:
                              </Typography>
                              <List dense>
                                {decision.alternatives_considered.map((alt, altIdx) => (
                                  <ListItem key={altIdx}>
                                    <ListItemText
                                      primary={`• ${alt}`}
                                      primaryTypographyProps={{ variant: 'body2', color: 'text.secondary' }}
                                    />
                                  </ListItem>
                                ))}
                              </List>
                            </>
                          )}

                          {decision.trade_offs && (
                            <>
                              <Typography variant="body2" fontWeight="bold" gutterBottom>
                                Trade-offs:
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                {decision.trade_offs}
                              </Typography>
                            </>
                          )}
                        </Box>
                      </AccordionDetails>
                    </Accordion>
                  ))}
                </Box>

                <Divider sx={{ my: 3 }} />

                {/* Prerequisites */}
                {currentBlueprint.prerequisites.length > 0 && (
                  <Box sx={{ mb: 3 }}>
                    <Typography variant="h6" gutterBottom>
                      Prerequisites
                    </Typography>
                    <List dense>
                      {currentBlueprint.prerequisites.map((prereq, idx) => (
                        <ListItem key={idx}>
                          <ListItemText
                            primary={`${idx + 1}. ${prereq}`}
                            primaryTypographyProps={{ variant: 'body2' }}
                          />
                        </ListItem>
                      ))}
                    </List>
                  </Box>
                )}

                {/* Risks */}
                {currentBlueprint.risks.length > 0 && (
                  <Box>
                    <Typography variant="h6" gutterBottom>
                      Risks & Considerations
                    </Typography>
                    {currentBlueprint.risks.map((risk, idx) => (
                      <Alert key={idx} severity="warning" sx={{ mb: 1 }}>
                        {risk}
                      </Alert>
                    ))}
                  </Box>
                )}
              </Box>
            </Paper>
          </Grid>
        </Grid>

        {/* Bottom Action Bar */}
        <Box
          sx={{
            p: 2,
            borderTop: 1,
            borderColor: 'divider',
            backgroundColor: 'background.paper',
          }}
        >
          {showRejectForm ? (
            <Box>
              <TextField
                fullWidth
                multiline
                rows={3}
                placeholder="Please provide feedback on why you're rejecting this blueprint..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                sx={{ mb: 2 }}
              />
              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button variant="outlined" onClick={() => setShowRejectForm(false)}>
                  Cancel
                </Button>
                <Button
                  variant="contained"
                  color="error"
                  onClick={handleRejectSubmit}
                  disabled={!feedback.trim()}
                  startIcon={<CancelIcon />}
                >
                  Submit Rejection
                </Button>
              </Box>
            </Box>
          ) : (
            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
              <Button variant="outlined" onClick={handleClose}>
                Close
              </Button>
              <Button
                variant="outlined"
                color="error"
                onClick={handleRejectClick}
                startIcon={<CancelIcon />}
              >
                Reject
              </Button>
              <Button
                variant="contained"
                color="success"
                onClick={handleApprove}
                startIcon={<CheckCircleIcon />}
              >
                Approve & Generate Code
              </Button>
            </Box>
          )}
        </Box>
      </Box>
    </Dialog>
  );
}
