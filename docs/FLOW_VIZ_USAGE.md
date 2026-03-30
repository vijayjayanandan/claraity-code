# ClarAIty Flow Visualization - Quick Start Guide

## 🚀 What is This?

**ClarAIty Flow Visualization** shows how code flows through components in the AI Coding Agent. Unlike the component diagram (claraity-viz.html) which shows static architecture, this shows **dynamic execution paths**.

## 📊 What's Inside?

- **1 Primary Flow:** Workflow Execution Flow (most complex path)
- **5 High-Level Steps:** User Input → Routing → Decision → Execute → Response
- **14 Total Steps:** Including 6 detailed substeps + 3 deeper substeps
- **Interactive Timeline:** Hybrid timeline+flowchart visualization
- **Decision Points:** Diamond markers showing branching logic
- **Code Traceability:** Every step links to exact file:line

## 🎯 How to Use

### 1. Open the Visualization

```bash
# Windows
start flow-viz-embedded.html

# Or just double-click flow-viz-embedded.html in File Explorer
```

### 2. Navigate the Flow

#### **Timeline View (Main)**
- **Purple gradient line** on the left shows the execution sequence
- **Numbered circles** mark each step in order
- **Diamond shapes** mark decision points (branching logic)
- **Red circles with glow** mark critical steps

#### **Click to Expand**
- Steps with substeps show a **"Show N substeps"** button
- Click to reveal detailed substeps
- Substeps can have their own sub-substeps (3 levels deep)
- Click again to collapse

#### **Step Cards**
Each step card shows:
- **Title:** What happens in this step
- **Description:** Detailed explanation
- **File Reference:** 📁 `src/core/agent.py:467-514` (file and line numbers)
- **Function:** ⚙️ Function/method name
- **Component:** Color-coded component badge (Core/Workflow/Memory/Tools)

#### **Decision Points (Yellow/Orange)**
- **Question:** What decision is being made?
- **Logic:** How the decision is made
- **Branches:** Possible paths (Yes/No, Workflow/Direct, etc.)

#### **Notes (Green boxes)**
- 💡 Additional context or important details

### 3. Understanding the Colors

**Step Types:**
- **Blue border:** Normal execution step
- **Orange border:** Decision point
- **Red border:** Critical step (failure here stops execution)

**Component Layers:**
- 🔴 **Red/Pink badge:** Core layer (CodingAgent)
- 🟢 **Green badge:** Workflow layer (TaskAnalyzer, Planner, etc.)
- 🔵 **Teal badge:** Memory layer (MemoryManager)
- 🟡 **Orange badge:** Tools layer (ToolExecutor)

## 💡 Use Cases

### For Developers:

**Q: What happens when I type a complex task?**
A: Follow the timeline from Step 1 → Step 5

**Q: Where does the workflow vs direct decision happen?**
A: Step 3 - shows exact file (`agent.py:467-514`) and decision logic

**Q: How does execution work?**
A: Expand Step 4 "Execute with Workflow" → see 6 substeps (Analyze, Plan, Approve, Execute, Verify, Response)

**Q: What tools get called?**
A: Expand Step 4 → Expand "Execute Plan Steps" → see substep "For Each Step: Execute Tools"

### For AI Agents:

When an AI agent needs to modify the workflow:
1. Load flow-viz-embedded.html
2. Find the relevant step in the flow
3. See exact file:line reference
4. Understand context (what happens before/after)
5. Make informed changes

## 📁 Files Generated

```
.claraity/ai-coding-agent.db      ← Database with flow data
flow-data.json                    ← Exported JSON (14KB)
flow-viz-embedded.html            ← Standalone visualization (46KB)
```

## 🔄 Updating the Visualization

When codebase changes, regenerate:

```bash
# 1. Re-populate flow data (if flow logic changed)
python3 src/claraity/populate_workflow_flow.py

# 2. Export to JSON
python3 export_flow_data.py

# 3. Regenerate HTML
python3 create_flow_viz.py

# 4. Refresh flow-viz-embedded.html in browser
```

## 📈 Statistics

**Current Data:**
- **Flow Complexity:** Complex (highest level)
- **Trigger:** User requests complex task (implement/refactor/debug/test keywords)
- **Type:** User-facing
- **Total Steps:** 14 across 3 hierarchy levels
- **Decision Points:** 3 (Workflow vs Direct, Approval, Error handling)
- **Critical Steps:** 7
- **Components Involved:** 8 (CodingAgent, TaskAnalyzer, TaskPlanner, PermissionManager, ExecutionEngine, VerificationLayer, ToolExecutor, MemoryManager)

## 🎓 Understanding Execution Flows

### Key Insight

This visualization answers the question you asked:

> "When user types in a query in the CLI, what is the execution flow?"

**Answer (High-Level):**
1. **CLI receives input** (`cli.py:131`)
2. **Agent routes** (`agent.py:916-934`)
3. **Decision: Workflow or Direct?** (`agent.py:467-514`)
4. **Execute with Workflow** (6 substeps)
5. **Return response to user**

**Answer (Detailed - Expand Step 4):**
1. Analyze task complexity
2. Create execution plan
3. Get user approval (if risky)
4. Execute plan steps
5. Verify results
6. Generate success/failure response

**Answer (Deep Dive - Expand "Execute Plan Steps"):**
1. For each step: Execute tools
2. Update memory context
3. Handle errors (retry/skip/abort)

### Difference from Component Diagram

**Component Diagram (claraity-viz.html):**
- Shows WHAT components exist
- Shows HOW they relate (static relationships)
- Good for: Understanding architecture structure

**Flow Diagram (flow-viz-embedded.html):**
- Shows HOW code flows through components
- Shows WHEN components are invoked
- Shows DECISIONS that route execution
- Good for: Understanding runtime behavior

## 🐛 Troubleshooting

**Visualization not loading?**
- Make sure you're opening `flow-viz-embedded.html` (not `flow-data.json`)
- Check browser console for errors
- Try Chrome/Edge/Firefox (latest versions)

**Steps not expanding?**
- Click the "Show N substeps" button
- JavaScript must be enabled
- Try refreshing the page

**Missing code references?**
- Some steps don't have file references (e.g., Step 1 CLI entry point)
- This is expected - not all steps map to specific code locations

## 🚀 Next Steps

This is the **POC/Prototype** for ClarAIty flow visualization. It demonstrates:
- ✅ Hierarchical flow representation
- ✅ Hybrid timeline+flowchart design
- ✅ Code-level traceability
- ✅ Interactive expand/collapse
- ✅ Decision point visualization
- ✅ Standalone HTML (no dependencies)

**Future Enhancements:**
- Add more flows (Direct Execution, Tool Execution, Memory Flow, RAG Flow)
- Real-time flow generation during code execution
- Integration with React UI
- Flow comparison (before/after code changes)
- Interactive code navigation (click file:line to open in editor)

---

**Created**: 2025-10-27
**Data Source**: `.claraity/ai-coding-agent.db` (flow_steps table)
**Export Script**: `export_flow_data.py`
**Generator Script**: `create_flow_viz.py`
**Visualization**: `flow-viz-embedded.html` (46KB standalone file)
