# ClarAIty Quick Start Guide

Get the ClarAIty visualization running in 2 minutes!

## Prerequisites

- Python 3.11+
- Node.js 18+
- ClarAIty database populated (`.clarity/ai-coding-agent.db`)

## Step 1: Start the Backend API

```bash
cd /workspaces/ai-coding-agent

# Activate Python virtual environment (if needed)
source venv/bin/activate

# Start FastAPI server
uvicorn src.clarity.api.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## Step 2: Start the React UI

In a new terminal:

```bash
cd /workspaces/ai-coding-agent/clarity-ui

# Start Vite dev server
npm run dev
```

You should see:
```
  VITE v5.0.x  ready in 500 ms

  ➜  Local:   http://localhost:3000/
  ➜  press h to show help
```

## Step 3: Open in Browser

Navigate to: **http://localhost:3000**

You should see:
- App bar with project statistics
- Interactive architecture diagram
- 116 components organized by layer
- Colorful nodes representing components

## Step 4: Explore!

### View Architecture
- **Zoom:** Mouse wheel or pinch gesture
- **Pan:** Click and drag on canvas
- **Reset View:** Use controls (bottom-left corner)
- **Mini Map:** Bottom-right corner shows overview

### Explore Components
- **Click any node** to view details
- Drawer opens from right side
- See:
  - Purpose and business value
  - Design rationale
  - Responsibilities
  - Code artifacts with line numbers
  - Design decisions
  - Relationships

### Layer Colors
- **Blue** (core) - Core agent functionality
- **Green** (memory) - Memory management
- **Orange** (rag) - RAG system
- **Purple** (workflow) - Workflow engine
- **Light Blue** (tools) - Tool implementations
- **Red** (llm) - LLM backends
- **Cyan** (prompts) - Prompt management
- **Yellow** (hooks) - Event hooks
- **Brown** (subagents) - Subagent system
- **Grey** (utils, other) - Utilities

## Troubleshooting

### API Not Running
**Error:** "Failed to connect to ClarAIty API"

**Solution:** Make sure FastAPI server is running on port 8000
```bash
curl http://localhost:8000/health
```

### Database Not Found
**Error:** "Database not found at .clarity/ai-coding-agent.db"

**Solution:** Populate the database first
```bash
python src/clarity/populate_from_codebase.py --query
```

### React Dependencies Missing
**Error:** Module not found errors

**Solution:** Install dependencies
```bash
cd clarity-ui
npm install
```

### Port Already in Use
**Error:** "Port 3000 is already in use"

**Solution:** Kill the process or use a different port
```bash
# Find and kill process on port 3000
lsof -ti:3000 | xargs kill -9

# Or use a different port
npm run dev -- --port 3001
```

## API Endpoints

Test the API directly:

```bash
# Health check
curl http://localhost:8000/health

# Get architecture summary
curl http://localhost:8000/architecture

# List all components
curl http://localhost:8000/components

# Search for components
curl "http://localhost:8000/components/search?q=memory"

# Get component details
curl http://localhost:8000/components/CODINGAGENT

# Get statistics
curl http://localhost:8000/statistics
```

## Next Steps

- 🔍 **Search** - Add search bar to filter components
- 🎛️ **Filters** - Toggle layers and status
- 🔄 **WebSocket** - Real-time generation updates
- ✅ **Validation** - Approve/reject UI
- 🎨 **Export** - Save diagram as image
- 🌓 **Theme Toggle** - Light/dark mode

## Documentation

- **Day 1:** `SESSION_CLARAITY_DAY1_COMPLETE.md` - Database + Analyzer
- **Day 2:** `SESSION_CLARAITY_DAY2_COMPLETE.md` - FastAPI + WebSocket
- **Day 3:** `SESSION_CLARAITY_DAY3_COMPLETE.md` - React UI + Visualization
- **UI README:** `clarity-ui/README.md`

## Get Help

- Check console for errors (F12 in browser)
- View API logs in terminal running uvicorn
- Check React logs in terminal running npm run dev
- See OpenAPI docs: http://localhost:8000/docs

---

**Happy Exploring! 🎯**
