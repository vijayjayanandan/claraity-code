# ClarAIty Visualization - Quick Start Guide

## 🚀 What is This?

**ClarAIty Visualization** is an interactive web-based tool to explore and understand the AI Coding Agent codebase architecture.

## 📊 What's Inside?

- **116 Components** across 10 architectural layers
- **22 Relationships** showing how components interact
- **531 Code Artifacts** (files, classes, functions)
- **Interactive Graph** with real-time exploration

## 🎯 How to Use

### 1. Open the Visualization

Simply open `clarity-viz.html` in your web browser:

```bash
# Windows
start clarity-viz.html

# Or just double-click clarity-viz.html in File Explorer
```

### 2. Explore the Architecture

#### **Interactive Graph (Center Panel)**
- **Zoom**: Mouse wheel or pinch gesture
- **Pan**: Click and drag the background
- **Click Node**: View detailed component information
- **Hover**: See quick info tooltip
- **Navigation Buttons**: Use built-in zoom controls

#### **Search (Top-Left)**
- Type to search components by name or purpose
- Matching components are highlighted
- Graph auto-focuses on first match

#### **Filter by Layer (Left Sidebar)**
- Click any layer button to filter
- See only components in that layer
- Shows relationship count per layer
- Click "All Layers" to reset

#### **Component Details (Right Panel)**
- Appears when you click a component
- Shows: Purpose, Business Value, Design Rationale
- Lists: Responsibilities, Code Artifacts
- Click × to close

### 3. Understanding the Colors

Each layer has a unique color:

| Layer | Color | Purpose |
|-------|-------|---------|
| **Core** | 🔴 Red | Core orchestration (CodingAgent, etc.) |
| **Memory** | 🟢 Teal | Memory systems (Working, Episodic, Semantic) |
| **RAG** | 🔵 Blue | Retrieval & embeddings |
| **Workflow** | 🟢 Green | Task analysis & planning |
| **Tools** | 🟡 Yellow | File ops, git, code search |
| **LLM** | 💜 Purple | LLM backends & configs |
| **Prompts** | 🟣 Violet | System prompts & templates |
| **Hooks** | 💗 Pink | Event-driven hooks system |
| **Subagents** | 🔷 Light Blue | Specialized sub-agents |

### 4. Node Shapes

- **Circles** → Regular components (classes, modules)
- **Boxes** → Orchestrators (main entry points)
- **Larger nodes** → More important/central components

### 5. Edge Styles

- **Thicker lines** → High criticality relationships
- **Medium lines** → Medium criticality
- **Thin lines** → Low criticality
- **Arrows** → Direction of dependency

## 💡 Pro Tips

### Find Entry Points
1. Look for **box-shaped nodes** (orchestrators)
2. Common entry points: `CodingAgent`, `WorkflowOrchestrator`

### Understand Data Flow
1. Filter by layer to see components in isolation
2. Look at relationships (arrows) to understand flow
3. Click components to see their responsibilities

### Navigate Large Codebases
1. Use search to find specific components
2. Filter by layer to reduce noise
3. Click component to see all its code artifacts
4. Use file paths to jump to actual code

### Explore by Feature
1. **Memory System**: Filter by "memory" layer
2. **Code Search**: Filter by "rag" layer
3. **Task Planning**: Filter by "workflow" layer
4. **File Operations**: Filter by "tools" layer

## 📈 Statistics Dashboard (Top-Right)

Shows real-time counts:
- **Components**: Total architectural components
- **Relationships**: Component connections
- **Artifacts**: Actual code files/classes/functions

## 🔄 Updating the Visualization

When codebase changes, regenerate:

```bash
# Re-export database
python3 export_clarity_data.py

# Refresh clarity-viz.html in browser
```

## 🎓 Understanding Your Codebase

### Quick Wins

**Q: Where do I start reading code?**
A: Look for box-shaped nodes (orchestrators) like `CodingAgent`

**Q: How does memory work?**
A: Filter by "memory" layer, see 12 components and their relationships

**Q: What tools are available?**
A: Filter by "tools" layer, shows all 18 tool components

**Q: How are tasks planned?**
A: Filter by "workflow" layer, trace from TaskAnalyzer → TaskPlanner → ExecutionEngine

**Q: Where's the LLM integration?**
A: Filter by "llm" layer, see all backend implementations

### Deep Dives

1. **Click any component** → See its responsibilities
2. **View code artifacts** → Jump to actual files
3. **Follow relationships** → Understand dependencies
4. **Check design rationale** → Learn why decisions were made

## 🐛 Troubleshooting

**Visualization not loading?**
- Make sure `clarity-data.json` is in the same directory
- Check browser console for errors
- Try Chrome/Edge/Firefox (latest versions)

**Graph too crowded?**
- Use layer filters to reduce noise
- Zoom in on specific areas
- Use search to find and focus components

**Slow performance?**
- Disable physics: Edit `options.physics.enabled = false` in HTML
- Reduce visible nodes using filters

## 🚀 Next Steps

This is a **prototype** to validate the concept. Future enhancements:

- **Week 1-2**: Full React UI with better UX
- **Week 2-3**: Real-time generation mode
- **Week 3+**: Agent integration for live updates

---

**Created**: 2025-10-24
**Data Source**: `.clarity/ai-coding-agent.db`
**Export Script**: `export_clarity_data.py`
**Visualization**: `clarity-viz.html`
