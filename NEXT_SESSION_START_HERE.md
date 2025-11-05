# 🚀 START HERE - Next ClarAIty Session

**Date Created:** 2025-10-21
**Current Status:** Day 3 Complete - Vision Clarified
**Next Priority:** Database Schema v2 + Code-Level Analysis

---

## ⚡ Quick Context (30 seconds)

### **What is ClarAIty?**
A **persistent knowledge base** that creates a **shared mental model** between humans and AI agents for understanding codebases.

### **Problem It Solves:**
AI agents lose context between sessions. ClarAIty preserves their understanding so they can:
- Start where they left off
- Answer "Where is X implemented?" (exact files, functions, lines)
- Learn from human corrections
- Build deeper knowledge over time

### **Current State:**
- ✅ Day 1-2: Database + FastAPI + WebSocket (116 components analyzed)
- ✅ Day 3: React UI + Vision breakthrough
- ⏳ Next: Database schema v2 + Deep code analysis

---

## 🎯 Critical Vision (Must Understand)

**Read this file:** `SESSION_CLARAITY_DAY3_VISION_COMPLETE.md`

**TL;DR:**
- ClarAIty is NOT just a visualization tool
- It's a KNOWLEDGE PLATFORM for human-AI collaboration
- Must provide code-level traceability: Concept → File → Function → Lines
- Current DB schema is too shallow, needs redesign

---

## 📋 Immediate Next Steps

### **Priority 1: Database Schema v2** (2-3 hours)

**Why:** Current schema can't answer "Where is X implemented at the code level?"

**Tasks:**
1. Create `schema_v2.sql` with new tables:
   - `capabilities` - High-level capabilities (Planning, Execution, etc.)
   - `code_artifacts` - Files, classes, functions with line numbers
   - `code_semantics` - Reads/writes/calls relationships
   - `code_locations` - Specific line ranges with purpose
   - `concept_to_code_mapping` - Concept → Code traceability

2. Write `migrate_v1_to_v2.py`
   - Convert existing data
   - Preserve current 116 components

3. Test migration
   - Verify all data preserved
   - New queries work

### **Priority 2: Deep Code Analyzer** (2-3 hours)

**Why:** Need to extract function-level details from source code

**Tasks:**
1. Create `src/clarity/core/deep_analyzer.py`
   - Parse Python files with AST
   - Extract classes, methods, functions
   - Identify function calls, variable reads/writes
   - Calculate line ranges
   - Determine purpose from docstrings/comments

2. Run on AI Coding Agent codebase
   - Populate new tables
   - Build semantic graph

### **Priority 3: High-Level View Redesign** (2-3 hours)

**Why:** Current view shows workflow timeline (wrong), need capability map

**Tasks:**
1. Create new components:
   - `SystemOverview.tsx` - Project summary card
   - `CapabilityCard.tsx` - Clickable capability cards
   - `CodeDrillDown.tsx` - Navigate: Capability → Component → File → Function
   - `ArchitectureDecisions.tsx` - Show design decisions
   - `ExplorationProgress.tsx` - Coverage by capability

2. Replace `HighLevelView.tsx`

3. Add API endpoints:
   - GET /capabilities
   - GET /capabilities/{id}/components
   - GET /components/{id}/code
   - GET /code/{id}/semantics

---

## 🗄️ New Database Schema Reference

```sql
-- Capabilities: What the system CAN DO
capabilities (id, name, purpose, confidence_level, coverage_percentage)

-- Code Artifacts: Files, classes, functions
code_artifacts (id, component_id, parent_id, type, name, file_path,
                line_start, line_end, purpose, complexity)

-- Code Semantics: What code does
code_semantics (id, artifact_id, semantic_type, target_artifact_id,
                description, line_number)

-- Code Locations: Specific line ranges with meaning
code_locations (id, artifact_id, purpose, line_start, line_end,
                code_snippet, keywords)

-- Concept Mapping: Concept → Code traceability
concept_to_code_mapping (id, concept, artifact_id, relevance_score, evidence)
```

**Example Query:**
```sql
-- "Where is task routing implemented?"
SELECT ca.file_path, ca.line_start, ca.line_end, ca.purpose
FROM concept_to_code_mapping cm
JOIN code_artifacts ca ON cm.artifact_id = ca.id
WHERE cm.concept = 'task routing'
ORDER BY cm.relevance_score DESC;
```

---

## 📁 Current Files

### **Working:**
- `src/clarity/core/database.py` - Current DB (v1 schema)
- `src/clarity/api/main.py` - FastAPI server (28 endpoints)
- `clarity-ui/src/App.tsx` - React app with view toggle
- `.clarity/ai-coding-agent.db` - 116 components analyzed

### **Needs Update:**
- `clarity-ui/src/components/HighLevelView.tsx` - Replace completely
- `src/clarity/core/analyzer.py` - Enhance for deep analysis

### **To Create:**
- `src/clarity/core/schema_v2.sql` - New schema
- `src/clarity/core/migrate_v1_to_v2.py` - Migration script
- `src/clarity/core/deep_analyzer.py` - Function-level parser
- `clarity-ui/src/components/SystemOverview.tsx`
- `clarity-ui/src/components/CapabilityCard.tsx`
- `clarity-ui/src/components/CodeDrillDown.tsx`

---

## 🚀 Quick Start Commands

```bash
# Backend (already running)
cd /workspaces/ai-coding-agent
uvicorn src.clarity.api.main:app --reload --port 8000

# Frontend (already running)
cd clarity-ui
npm run dev
# → http://localhost:3000

# Test current state
curl http://localhost:8000/architecture
```

---

## 💡 Key Design Decisions Made

1. **Generic Architecture** - Works for any codebase
2. **Code-Level Traceability** - Down to function and line level
3. **Capability-Centric View** - Shows what system CAN DO, not how it executes
4. **Auto-Detection** - Different views for web apps vs libraries vs agents
5. **Bidirectional Learning** - Human corrects AI, AI learns from corrections

---

## 🎯 Success Criteria

**For this session to be successful:**
- ✅ Schema v2 designed and migrated
- ✅ Deep code analysis extracts function-level details
- ✅ High-level view shows capabilities (not workflow timeline)
- ✅ Can answer: "Where is concept X implemented?" → Get exact file + function + lines
- ✅ Can drill down: Capability → Component → File → Function

---

## 📚 Documentation to Read

**Must Read (Priority Order):**
1. `SESSION_CLARAITY_DAY3_VISION_COMPLETE.md` ⭐⭐⭐ (This session's insights)
2. `SESSION_CLARAITY_DAY2_COMPLETE.md` (FastAPI + WebSocket)
3. `SESSION_CLARAITY_DAY1_COMPLETE.md` (Database + Analyzer)
4. `CLARAITY_IMPLEMENTATION_PLAN.md` (Original 21-day plan)

**Reference:**
- `CODEBASE_CONTEXT.md` - AI Coding Agent architecture
- `clarity-ui/README.md` - UI setup

---

## ⚠️ Important Notes

- **Context Management:** Only 2% context left at end of Day 3 session
- **Vision Clarity:** Had 3 major pivots before final vision emerged
- **Database:** Current schema works but is too shallow for vision
- **UI State:** Toggle works, but High-Level view needs complete rewrite
- **Testing:** UI has no tests yet, backend has 674 passing tests

---

**Ready to build the future of human-AI collaboration!** 🚀
