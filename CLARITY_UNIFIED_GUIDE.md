# ClarAIty Unified Interface - Complete Guide

## 🚀 What is This?

**ClarAIty Unified** is a single-page application that provides **5 interconnected views** for understanding any codebase:

1. **🏠 Dashboard** - Overview, capabilities, entry points
2. **🏗️ Architecture** - Component diagram with relationships
3. **🔄 Flows** - Execution flows showing runtime behavior
4. **📁 Files** - File tree explorer with code mapping
5. **🔍 Search** - Unified search across everything

**Key Feature:** All views are **interconnected**. Click something in one view → navigate to it in other views.

---

## 📊 Quick Start

### **Open the Interface:**

```bash
# Windows
start clarity-unified.html

# Or just double-click clarity-unified.html
```

### **First Visit - Start Here:**

1. **Dashboard Tab** (opens by default)
   - See system capabilities
   - Check readiness percentages
   - View entry points
   - Click any capability → jumps to Architecture filtered by that layer

2. **Try Search Tab**
   - Type "task routing"
   - Click a result → jumps to relevant view
   - Search finds: components, files, functions, flow steps

3. **Explore Architecture**
   - Interactive graph of all components
   - Click nodes to see details
   - Zoom/pan with mouse
   - Components color-coded by layer

4. **Browse Files**
   - File tree on left
   - Click a file → see details on right
   - Shows components, layers, artifacts
   - Navigate folder structure

5. **Study Flows**
   - Timeline view of execution
   - Expand steps to see substeps (3 levels deep)
   - Decision points marked with diamonds
   - Every step links to code

---

## 🏠 Tab 1: Dashboard

**Purpose:** High-level overview and quick navigation

### **What You See:**

**Capabilities Grid:**
- 5 capability cards (Planning, Execution, Verification, Memory, Code Understanding)
- Each shows:
  - Readiness percentage (visual bar)
  - Components involved
  - Description
- **Click any card** → jumps to Architecture tab filtered by that capability's layer

**Entry Points Section:**
- Shows where to start exploring code
- Lists main entry functions with file:line references
- Example: "User Input via CLI" → `src/cli.py:131`

**Top Stats Bar:**
- Components, Files, Relationships, Flows, Layers counts

### **Use Cases:**

**Q: What can this system do?**
A: Look at the 5 capability cards - these are the main features

**Q: Where do I start reading code?**
A: Check the Entry Points section - shows main functions

**Q: What's the overall state?**
A: See readiness percentages - green (90%+) is production-ready

---

## 🏗️ Tab 2: Architecture

**Purpose:** Understand component structure and relationships

### **What You See:**

**Interactive Network Graph:**
- Nodes = Components (116 total)
- Edges = Relationships (calls, depends-on, uses)
- Colors = Layers:
  - 🔴 Red = Core
  - 🟢 Green = Workflow
  - 🔵 Teal = Memory
  - 🟡 Orange = Tools
  - 💙 Blue = RAG
- Shapes:
  - **Boxes** = Orchestrators (main entry points)
  - **Circles** = Regular components

**Navigation:**
- **Mouse wheel** = Zoom
- **Click & drag** = Pan
- **Click node** = See component details
- **Navigation buttons** = Built-in zoom controls

**Legend:**
- Shows color mapping to layers

### **Use Cases:**

**Q: How are components organized?**
A: See the hierarchical layout - Core at top, Tools at bottom

**Q: What does component X depend on?**
A: Click the component, follow the arrows

**Q: Show me all Memory components:**
A: Click a teal (memory) component → connected memory components highlighted

**From Dashboard:**
- Click "Memory Management" capability → jumps here with Memory layer highlighted

---

## 🔄 Tab 3: Flows

**Purpose:** Understand how code executes at runtime

### **What You See:**

**Timeline Visualization:**
- Vertical purple gradient line = execution sequence
- Numbered circles = steps in order
- Diamond shapes = decision points
- Red circles with glow = critical steps

**For Each Step:**
- Title (what happens)
- Description (detailed explanation)
- File reference (📁 `src/core/agent.py:467-514`)
- Function name (e.g., `_should_use_workflow()`)
- Component badge (color-coded by layer)

**Expandable Substeps:**
- Steps with "Show N substeps" button
- Click to reveal detailed substeps (up to 3 levels deep)
- Example: "Execute with Workflow" → expands to 6 substeps

**Decision Points:**
- Yellow/orange highlighting
- Shows decision question
- Lists branch options (Yes/No, Workflow/Direct, etc.)

### **Use Cases:**

**Q: What happens when user types a complex task?**
A: Follow the Workflow Execution Flow from Step 1 → Step 5

**Q: Where does the workflow vs direct decision happen?**
A: Look for the diamond marker at Step 3 - shows exact file and logic

**Q: How does execution work in detail?**
A: Expand Step 4 "Execute with Workflow" → see Analyze, Plan, Approve, Execute, Verify, Response

**Q: What happens if there's an error?**
A: Expand "Execute Plan Steps" → see error handling decision (retry/skip/abort)

---

## 📁 Tab 4: Files

**Purpose:** Navigate file structure and understand code organization

### **Layout:**

```
┌────────────────────┬─────────────────────────────┐
│  File Tree         │  File Details               │
│  (Left Panel)      │  (Right Panel)              │
│                    │                             │
│  📦 src/           │  [Select a file to          │
│   ├─ 📁 core/      │   view details]             │
│   │  ├─ 📄 agent   │                             │
│   │  └─ 📄 context │                             │
│   ├─ 📁 workflow/  │                             │
│   └─ 📁 memory/    │                             │
└────────────────────┴─────────────────────────────┘
```

### **File Tree (Left):**

- **📁 Folders**
  - Click to expand/collapse
  - Shows file count
  - Hierarchical navigation
- **📄 Files**
  - Click to view details

### **File Details (Right):**

When you click a file, shows:
- **File name and path**
- **Stats:** Line count, artifact count
- **Components:** Which components this file implements
- **Layers:** Which architectural layers
- **Artifacts List:**
  - Classes, functions, methods
  - Line ranges for each
  - Descriptions
  - First 10 shown, with count of remaining

### **Use Cases:**

**Q: Where is the workflow code?**
A: Expand `src/workflow/` folder → see all workflow files

**Q: What's in agent.py?**
A: Click `src/core/agent.py` → right panel shows classes/functions

**Q: Which component does this file belong to?**
A: File details show component badges

**Q: How big is this file?**
A: See line count in file details

**Q: Show me all Core layer files:**
A: Browse `src/core/` folder

**From Search:**
- Search for a function → click result → jumps to this view with file selected

---

## 🔍 Tab 5: Search

**Purpose:** Find anything quickly and navigate to it

### **Search Box:**

Type to search (min 2 characters):
- Component names
- Component purposes
- File names
- Function/class names
- Artifact descriptions
- Flow step titles
- Flow step descriptions

### **Search Results:**

Each result shows:
- **Type badge:** Component, Artifact, or Flow Step
- **Title:** Name of the thing found
- **Description:** What it does
- **File reference:** Where it lives (if applicable)
- **Layer badge:** Which layer (for components)

**Click any result:**
- **Component result** → jumps to Architecture tab with component selected
- **Artifact result** → jumps to Files tab with file selected
- **Flow result** → jumps to Flows tab

### **Use Cases:**

**Q: Where is task routing implemented?**
A: Search "task routing" → shows:
- Component: CodingAgent
- Artifact: function `_should_use_workflow()`
- Flow Step: "Decision: Workflow or Direct?"
- Click any result → navigate there

**Q: Find all memory-related code:**
A: Search "memory" → shows all memory components, files, artifacts

**Q: Where is the approval logic?**
A: Search "approval" → shows PermissionManager component, approval flow step

**Q: What files deal with verification?**
A: Search "verification" → shows VerificationLayer and related artifacts

---

## 🔗 Interconnected Navigation

**Key Feature:** Everything links to everything

### **Navigation Paths:**

**1. Dashboard → Architecture:**
- Click capability card → Architecture filtered by layer
- Example: Click "Execution" → shows Workflow layer components

**2. Architecture → Files:**
- Click component → (future: will filter files to show component's files)

**3. Search → Any View:**
- Search component → Architecture
- Search file/function → Files
- Search flow step → Flows

**4. Files → Architecture:**
- File details show component badges
- (Future: click badge → jump to Architecture)

**5. Flows → Files:**
- Flow steps show file:line references
- (Future: click reference → jump to Files)

### **Planned Cross-Links:**

- Click file:line in Flows → opens Files view at that file
- Click component in Files → opens Architecture with component selected
- Click layer badge anywhere → filters Architecture by layer

---

## 💡 Common Workflows

### **Workflow 1: Understanding a New Codebase**

```
1. Open Dashboard
   → See capabilities & entry points
   → Get high-level understanding

2. Click capability → Architecture
   → See components involved
   → Understand relationships

3. Search for specific feature
   → Find relevant components/files
   → Navigate to details

4. Browse Files
   → Explore folder structure
   → See code organization

5. Study Flows
   → Understand runtime behavior
   → See how components interact
```

### **Workflow 2: Finding Where Something is Implemented**

```
1. Open Search tab
2. Type the concept (e.g., "task routing")
3. See results across components, files, flows
4. Click relevant result
5. Navigate to that view (Architecture/Files/Flows)
6. Drill down for details
```

### **Workflow 3: Understanding a Specific Component**

```
1. Search for component name
2. Click component result → Architecture view
3. Click node → see component details
4. Note file references
5. Switch to Files tab
6. Navigate to component's files
7. See classes/functions in that component
```

### **Workflow 4: Understanding Execution Flow**

```
1. Dashboard → see entry points
2. Flows tab → see execution timeline
3. Expand steps for detail
4. Click file references in steps
5. (Future: auto-navigate to Files view)
6. See exact code that implements each step
```

---

## 🎨 Color Coding Guide

### **Layers:**

| Color | Layer | Components |
|-------|-------|------------|
| 🔴 Red | Core | CodingAgent, ContextBuilder |
| 🟢 Green | Workflow | TaskAnalyzer, TaskPlanner, ExecutionEngine |
| 🔵 Teal | Memory | MemoryManager, Working/Episodic/Semantic |
| 🟡 Orange | Tools | File operations, Git tools, ToolExecutor |
| 💙 Blue | RAG | CodeIndexer, Embedder, HybridRetriever |
| 💜 Purple | LLM | LLM backends, configs |
| 🟣 Violet | Prompts | System prompts, templates |
| 💗 Pink | Hooks | Event-driven hooks |
| 🔷 Light Blue | Subagents | Specialized agents |
| 🟦 Blue | ClarAIty | This system! |

### **Flow Step Markers:**

| Marker | Meaning |
|--------|---------|
| ⭕ Blue circle | Normal execution step |
| 🔶 Diamond | Decision point (branching) |
| 🔴 Red circle (glow) | Critical step (failure = abort) |
| 🔁 Loop icon | Iterative step (repeats) |

### **Badges:**

- **Capability cards:** Gradient background = ready for use
- **Readiness bars:** Purple gradient fill = completion level
- **Component pills:** White on various backgrounds = component tags
- **Layer badges:** Colored backgrounds matching layer colors

---

## 📊 Statistics

### **Current Data:**

- **Components:** 116 architectural components
- **Files:** 531 code artifacts
- **Relationships:** 22 component relationships
- **Flows:** 1 primary flow (Workflow Execution)
- **Flow Steps:** 14 steps across 3 levels
- **Layers:** 10 architectural layers
- **Capabilities:** 5 main capabilities

### **File Size:**

- **clarity-unified.html:** 676 KB
- **clarity-unified-data.json:** 638 KB
- **Total:** ~1.3 MB (single standalone file)

---

## 🔄 Updating the Visualization

When codebase changes:

```bash
# 1. Re-analyze codebase (if components changed)
cd src/clarity
python3 populate_from_codebase.py

# 2. Update flows (if execution logic changed)
python3 populate_workflow_flow.py

# 3. Export data
python3 export_clarity_data.py
python3 export_flow_data.py

# 4. Prepare unified data
python3 prepare_unified_data.py

# 5. Regenerate HTML
python3 create_unified_clarity.py

# 6. Refresh clarity-unified.html in browser
```

---

## 🐛 Troubleshooting

**Interface not loading?**
- Check browser console for errors
- Try Chrome/Edge/Firefox (latest versions)
- File size is 676KB - may take a few seconds to load

**Tabs not switching?**
- Click the tab button (not just anywhere)
- JavaScript must be enabled
- Try refreshing the page

**Architecture graph not showing?**
- Graph uses vis.js from CDN
- Requires internet connection
- Check if vis.js script loaded (browser console)

**Search not working?**
- Type at least 2 characters
- Results appear as you type
- Try simpler search terms

**File tree not expanding?**
- Click the ▶ arrow (not the folder name)
- Try clicking again to toggle

**Cross-linking not working?**
- Some links planned for future (marked as "Future:")
- Click results in Search work now
- Dashboard → Architecture works now

---

## 🚀 Future Enhancements

### **Planned Features:**

**1. Enhanced Cross-Linking:**
- Click file:line → jump to Files view
- Click component badge → jump to Architecture
- Click layer anywhere → filter Architecture

**2. More Flows:**
- Direct Execution Flow
- Tool Execution Flow
- Memory Flow
- RAG Flow

**3. Interactive Code View:**
- Syntax highlighting
- Click function → see implementation
- Click call → jump to definition

**4. Advanced Search:**
- Filter by type (components only, files only)
- Search history
- Saved searches

**5. Annotations:**
- Add notes to components
- Highlight important flows
- Mark areas for improvement

**6. Comparison Views:**
- Before/after code changes
- Flow differences
- Component evolution

**7. Export Features:**
- Export diagram as image
- Export data as CSV
- Generate PDF report

---

## 📚 Documentation Links

**Related Docs:**
- `CLARITY_VIZ_USAGE.md` - Component diagram standalone
- `FLOW_VIZ_USAGE.md` - Flow diagram standalone
- `SESSION_FLOW_VIZ_COMPLETE.md` - How flows were built
- `SESSION_CLARAITY_DAY3_VISION_COMPLETE.md` - Vision and philosophy

**Implementation Guides:**
- `prepare_unified_data.py` - Data preparation script
- `create_unified_clarity.py` - HTML generator
- `src/clarity/populate_from_codebase.py` - Component analysis
- `src/clarity/populate_workflow_flow.py` - Flow documentation

---

## 🎯 Key Takeaways

**ClarAIty Unified answers 5 key questions:**

1. **What can this system do?** → Dashboard (capabilities)
2. **How is it structured?** → Architecture (components & relationships)
3. **How does it execute?** → Flows (runtime behavior)
4. **Where is the code?** → Files (folder structure & mapping)
5. **Where is X implemented?** → Search (find anything)

**The Power of Interconnection:**

Unlike separate diagrams, ClarAIty Unified lets you:
- Start anywhere (dashboard, search, architecture)
- Navigate seamlessly between views
- Follow your curiosity
- Build mental model naturally

**For AI Agents:**

This unified interface provides:
- Complete codebase understanding in one place
- Code-level traceability (concept → file → function → lines)
- Execution context (what happens when)
- Persistent knowledge (survives session end)

---

**Created:** 2025-10-27
**File:** `clarity-unified.html` (676 KB standalone)
**Data:** `clarity-unified-data.json` (638 KB)
**Status:** ✅ Production-ready POC

## 🚀 **Open clarity-unified.html now!** 🚀
