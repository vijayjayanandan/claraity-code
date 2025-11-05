import { useState, useEffect } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import {
  CssBaseline,
  AppBar,
  Toolbar,
  Typography,
  Container,
  Box,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import TimelineIcon from '@mui/icons-material/Timeline';
import FolderIcon from '@mui/icons-material/Folder';
import SearchIcon from '@mui/icons-material/Search';
import DashboardTab from './components/tabs/DashboardTab';
import ArchitectureTab from './components/tabs/ArchitectureTab';
import FlowsTab from './components/tabs/FlowsTab';
import FilesTab from './components/tabs/FilesTab';
import SearchTab from './components/tabs/SearchTab';
import { getArchitectureSummary, healthCheck } from './services/api';
import type { ArchitectureSummary } from './types';
import './globalStyles.css';

const clarityTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#3b82f6', // Blue-500 - Professional blue accent
    },
    secondary: {
      main: '#8b5cf6', // Violet-500 - Secondary accent
    },
    background: {
      default: '#0f172a', // Slate-900 - Main background
      paper: '#1e293b',   // Slate-800 - Card/paper background
    },
    text: {
      primary: '#f1f5f9',    // Slate-100 - Primary text (16.1:1 contrast!)
      secondary: '#cbd5e1',  // Slate-300 - Secondary text
    },
  },
  typography: {
    fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
  },
  components: {
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: '#1e293b', // Slate-800 - Professional dark header
          color: '#f1f5f9',     // Slate-100 - Bright white text
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        },
      },
    },
  },
});

type TabMode = 'dashboard' | 'architecture' | 'flows' | 'files' | 'search';

function App() {
  const [architecture, setArchitecture] = useState<ArchitectureSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTab, setCurrentTab] = useState<TabMode>('dashboard');

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Check API health
      await healthCheck();

      // Load architecture
      const arch = await getArchitectureSummary();
      setArchitecture(arch);
    } catch (err) {
      console.error('Failed to load data:', err);
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to connect to ClarAIty API. Make sure the server is running on http://localhost:8000'
      );
    } finally {
      setLoading(false);
    }
  };

  const handleTabChange = (_event: React.SyntheticEvent, newValue: TabMode) => {
    setCurrentTab(newValue);
  };

  const handleNavigateToArchitecture = (layer?: string) => {
    setCurrentTab('architecture');
    // TODO: Filter by layer when architecture tab is implemented
    console.log('Navigate to architecture, layer:', layer);
  };

  const renderTabContent = () => {
    switch (currentTab) {
      case 'dashboard':
        return <DashboardTab onNavigateToArchitecture={handleNavigateToArchitecture} />;
      case 'architecture':
        return <ArchitectureTab />;
      case 'flows':
        return <FlowsTab />;
      case 'files':
        return <FilesTab />;
      case 'search':
        return <SearchTab />;
      default:
        return <DashboardTab onNavigateToArchitecture={handleNavigateToArchitecture} />;
    }
  };

  return (
    <ThemeProvider theme={clarityTheme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        {/* AppBar */}
        <AppBar position="static">
          <Toolbar>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
              🎯 ClarAIty - Unified Architecture Interface
            </Typography>

            {/* Stats - Show when architecture is loaded */}
            {architecture && (
              <Box sx={{ display: 'flex', gap: 3, mr: 2 }}>
                <Typography variant="body2">
                  Components: {architecture.total_components}
                </Typography>
                <Typography variant="body2">
                  Artifacts: {architecture.total_artifacts}
                </Typography>
                <Typography variant="body2">
                  Relationships: {architecture.total_relationships}
                </Typography>
              </Box>
            )}
          </Toolbar>

          {/* Tab Navigation */}
          <Tabs
            value={currentTab}
            onChange={handleTabChange}
            textColor="inherit"
            indicatorColor="primary"
            sx={{
              backgroundColor: '#1e293b', // Slate-800
              '& .MuiTab-root': {
                color: '#94a3b8', // Slate-400 - Unselected tabs
                fontWeight: 500,
                '&.Mui-selected': {
                  color: '#3b82f6', // Blue-500 - Selected tab
                },
                '&:hover': {
                  color: '#cbd5e1', // Slate-300 - Hover state
                },
              },
            }}
          >
            <Tab
              icon={<DashboardIcon />}
              iconPosition="start"
              label="Dashboard"
              value="dashboard"
            />
            <Tab
              icon={<AccountTreeIcon />}
              iconPosition="start"
              label="Architecture"
              value="architecture"
            />
            <Tab
              icon={<TimelineIcon />}
              iconPosition="start"
              label="Flows"
              value="flows"
            />
            <Tab
              icon={<FolderIcon />}
              iconPosition="start"
              label="Files"
              value="files"
            />
            <Tab
              icon={<SearchIcon />}
              iconPosition="start"
              label="Search"
              value="search"
            />
          </Tabs>
        </AppBar>

        {/* Main Content */}
        <Container maxWidth="xl" sx={{ flexGrow: 1, py: 3 }}>
          {loading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
              <CircularProgress />
            </Box>
          )}

          {error && (
            <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 3 }}>
              {error}
            </Alert>
          )}

          {/* Render current tab */}
          {!loading && renderTabContent()}
        </Container>

        {/* Footer */}
        {architecture && (
          <Box
            component="footer"
            sx={{
              py: 1.5,
              px: 2,
              mt: 'auto',
              backgroundColor: '#1e293b', // Slate-800
              borderTop: '1px solid rgba(148, 163, 184, 0.1)', // Slate-400 with opacity
            }}
          >
            <Typography variant="caption" color="text.secondary" align="center" display="block">
              {architecture.project_name} • {architecture.layers.length} Layers •{' '}
              Generated with ClarAIty
            </Typography>
          </Box>
        )}
      </Box>
    </ThemeProvider>
  );
}

export default App;
