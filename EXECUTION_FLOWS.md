# AI Coding Agent - Complete Execution Flows

**Last Updated:** 2025-10-24
**Purpose:** Document all execution paths discovered from code analysis

---

## 🎯 System Overview

**Product:** AI Coding Agent (like Claude Code + Visualization)
**User Interaction:** Chat mode in CLI
**Architecture:** Intelligent routing between Direct Execution and Workflow Execution

---

## 📊 Main Execution Paths

### **Path 1: User Input → Agent** (Entry Point)

```
User types message in CLI
  ↓
src/cli.py:131 → agent.chat(user_input, stream=True)
  ↓
src/core/agent.py:916 → chat() method
  ↓
src/core/agent.py:928 → _infer_task_type(message)
  ↓
src/core/agent.py:930 → execute_task(task_description, task_type)
```

**File References:**
- `src/cli.py:131` - CLI receives user input
- `src/core/agent.py:916-934` - Chat method

---

### **Path 2A: Workflow Execution** (Complex Tasks)

Used for: `implement`, `refactor`, `debug`, `test`, `fix`, `create`

```
execute_task()
  |
  ├─→ [HOOK] user_prompt_submit (optional)
  |     src/core/agent.py:827-860
  |     • Can block or modify prompt
  |
  ├─→ Create TaskContext
  |     src/core/agent.py:862-869
  |     • Generate UUID
  |     • Set task description, type
  |
  ├─→ Add to memory
  |     src/core/agent.py:872
  |     • Store in working memory
  |
  ├─→ DECISION: _should_use_workflow()
  |     src/core/agent.py:881, 467-514
  |     • Check task type
  |     • Check keywords
  |     • Returns: True (Workflow)
  |
  ├─→ _execute_with_workflow()
  |     src/core/agent.py:885, 555-641
  |
  |     STEP 1: Analyze Task
  |     ├─→ TaskAnalyzer.analyze()
  |     |     src/workflow/task_analyzer.py
  |     |     • Determine complexity
  |     |     • Risk level
  |     |     • Affected systems
  |     |
  |     STEP 2: Create Plan
  |     ├─→ TaskPlanner.create_plan()
  |     |     src/workflow/task_planner.py
  |     |     • Generate steps
  |     |     • Estimate time
  |     |     • Define success criteria
  |     |
  |     STEP 3: Get Approval
  |     ├─→ PermissionManager.get_approval()
  |     |     src/workflow/permission_manager.py
  |     |     • Check permission mode (plan/normal/auto)
  |     |     • Ask user if needed
  |     |
  |     STEP 4: Execute Plan
  |     ├─→ ExecutionEngine.execute_plan()
  |     |     src/workflow/execution_engine.py
  |     |     • Execute steps sequentially
  |     |     • Call tools as needed
  |     |     • Track progress
  |     |
  |     STEP 5: Verify (Optional)
  |     ├─→ VerificationLayer.verify()
  |     |     src/workflow/verification_layer.py
  |     |     • Check success criteria
  |     |     • Validate output
  |     |
  |     STEP 6: Generate Response
  |     └─→ _generate_success_response() or _generate_failure_response()
  |           src/core/agent.py:643-698
  |
  └─→ Return AgentResponse
```

**Components Involved:**
- `TaskAnalyzer` - Analyze task complexity and requirements
- `TaskPlanner` - Generate execution plan with steps
- `PermissionManager` - Handle user approvals
- `ExecutionEngine` - Execute plan steps
- `VerificationLayer` - Verify execution results
- `ToolExecutor` - Execute individual tools

---

### **Path 2B: Direct Execution** (Simple Tasks)

Used for: `explain`, `what`, `how`, `search`, `find`, `show`

```
execute_task()
  |
  ├─→ [HOOK] user_prompt_submit (optional)
  |     src/core/agent.py:827-860
  |
  ├─→ Create TaskContext
  |     src/core/agent.py:862-869
  |
  ├─→ Add to memory
  |     src/core/agent.py:872
  |
  ├─→ DECISION: _should_use_workflow()
  |     src/core/agent.py:881, 467-514
  |     • Check task type
  |     • Check keywords
  |     • Returns: False (Direct)
  |
  ├─→ _execute_direct()
  |     src/core/agent.py:894, 700-748
  |
  |     STEP 1: Parse File References
  |     ├─→ FileReferenceParser.parse_and_load()
  |     |     src/core/file_reference_parser.py
  |     |     • Find @file.py references
  |     |     • Load file contents
  |     |
  |     STEP 2: Build Context
  |     ├─→ ContextBuilder.build_context()
  |     |     src/core/context_builder.py
  |     |     • Gather relevant code
  |     |     • Use RAG if available
  |     |     • Include file references
  |     |     • Add memory context
  |     |
  |     STEP 3: Execute with Tools
  |     └─→ _execute_with_tools()
  |           src/core/agent.py:742
  |           • Call LLM with context
  |           • LLM may call tools
  |           • Iterate up to 3 times
  |
  └─→ Return response
```

**Components Involved:**
- `FileReferenceParser` - Parse and load @file references
- `ContextBuilder` - Build LLM context with RAG
- `HybridRetriever` - Semantic + keyword search
- `ToolExecutor` - Execute tools as needed
- `LLM Backend` - Generate responses

---

## 🤔 Decision Logic: Workflow vs Direct

**Location:** `src/core/agent.py:467-514`

```python
def _should_use_workflow(task_description, task_type):
    # Priority 1: Task type
    if task_type in ["implement", "refactor", "debug", "test"]:
        return True  # → WORKFLOW

    # Priority 2: Workflow keywords
    workflow_keywords = [
        "implement", "create", "add", "build", "refactor",
        "fix", "debug", "modify", "change", "update",
        "test", "migrate", "restructure"
    ]
    if any(keyword in task_description):
        return True  # → WORKFLOW

    # Priority 3: Direct keywords
    direct_keywords = [
        "explain", "what", "how", "why", "show", "find",
        "search", "display", "read"
    ]
    if any(keyword in task_description):
        return False  # → DIRECT

    # Default
    return False  # → DIRECT
```

---

## 🎨 Use Case Examples

### Use Case 1: "Explain how memory works"

```
Path: DIRECT EXECUTION

User: "Explain how memory works"
  ↓
CLI → agent.chat()
  ↓
_infer_task_type() → "explain"
  ↓
execute_task(type="explain")
  ↓
_should_use_workflow() → False (keyword "explain")
  ↓
_execute_direct()
  ↓
ContextBuilder.build_context()
  ├─→ RAGRetriever finds memory-related code
  ├─→ Adds working memory context
  └─→ Builds comprehensive context
  ↓
LLM generates explanation
  ↓
Return response to user
```

**Components Used:**
- CLI, CodingAgent, ContextBuilder, RAGRetriever, LLM

---

### Use Case 2: "Create a new file test.py with hello world"

```
Path: WORKFLOW EXECUTION

User: "Create a new file test.py with hello world"
  ↓
CLI → agent.chat()
  ↓
_infer_task_type() → "implement"
  ↓
execute_task(type="implement")
  ↓
_should_use_workflow() → True (keyword "create", type "implement")
  ↓
_execute_with_workflow()
  ↓
TaskAnalyzer.analyze()
  • Complexity: LOW
  • Risk: LOW
  • Estimated files: 1
  ↓
TaskPlanner.create_plan()
  • Step 1: Create test.py file
  • Step 2: Write hello world function
  • Tool: write_file
  ↓
PermissionManager.get_approval()
  • Mode: normal → No approval needed (low risk)
  ↓
ExecutionEngine.execute_plan()
  ├─→ Step 1: write_file(path="test.py", content="def hello():\n    return 'world'")
  └─→ Success!
  ↓
VerificationLayer.verify()
  • File exists: ✓
  • Syntax valid: ✓
  ↓
Generate success response
  ↓
Return to user
```

**Components Used:**
- CLI, CodingAgent, TaskAnalyzer, TaskPlanner, PermissionManager, ExecutionEngine, ToolExecutor (write_file), VerificationLayer

---

### Use Case 3: "Refactor the memory system to use async"

```
Path: WORKFLOW EXECUTION (Complex)

User: "Refactor the memory system to use async"
  ↓
CLI → agent.chat()
  ↓
_infer_task_type() → "refactor"
  ↓
execute_task(type="refactor")
  ↓
_should_use_workflow() → True (type "refactor")
  ↓
_execute_with_workflow()
  ↓
TaskAnalyzer.analyze()
  • Complexity: HIGH
  • Risk: HIGH
  • Estimated files: 5+
  • Requires tests: Yes
  ↓
TaskPlanner.create_plan()
  • Step 1: Analyze current memory implementation
  • Step 2: Identify async conversion points
  • Step 3: Update MemoryManager to async
  • Step 4: Update EpisodicMemory to async
  • Step 5: Update SemanticMemory to async
  • Step 6: Update all callers
  • Step 7: Add async tests
  • Step 8: Run tests
  • Tools: read_file, edit_file, search_code, run_tests
  ↓
PermissionManager.get_approval()
  • Mode: normal → ASKS USER (high risk!)
  • User: Approve / Reject
  ↓
ExecutionEngine.execute_plan()
  ├─→ Step 1-8: Execute sequentially
  ├─→ Each step may call multiple tools
  └─→ Track progress
  ↓
VerificationLayer.verify()
  • Tests pass: Check
  • No syntax errors: Check
  • Success criteria met: Check
  ↓
Generate success response
  ↓
Return to user
```

**Components Used:**
- All workflow components + Multiple tools (read_file, edit_file, search_code, run_tests)

---

### Use Case 4: "Search for all files using RAG"

```
Path: DIRECT EXECUTION

User: "Search for all files using RAG"
  ↓
CLI → agent.chat()
  ↓
_infer_task_type() → "explain" (keyword "search")
  ↓
execute_task(type="explain")
  ↓
_should_use_workflow() → False (keyword "search")
  ↓
_execute_direct()
  ↓
ContextBuilder.build_context()
  ├─→ RAGRetriever.search("RAG files")
  ├─→ Semantic search in code
  └─→ Returns relevant chunks
  ↓
LLM analyzes and formats results
  ↓
Return response to user
```

**Components Used:**
- CLI, CodingAgent, ContextBuilder, RAGRetriever, HybridRetriever, LLM

---

## 🔧 Tool Execution

**Location:** Happens in both paths via `ToolExecutor`

```
ToolExecutor.execute_tool(tool_name, **params)
  |
  ├─→ [HOOK] pre_tool_execute (optional)
  |
  ├─→ Find tool by name
  |     src/tools/*.py
  |
  ├─→ Validate parameters
  |
  ├─→ Execute tool
  |     • read_file
  |     • write_file
  |     • edit_file
  |     • search_code
  |     • analyze_code
  |     • git_* operations
  |     • etc.
  |
  ├─→ [HOOK] post_tool_execute (optional)
  |
  └─→ Return ToolResult
        • success: bool
        • output: Any
        • error: Optional[str]
```

---

## 💾 Memory Flow

**Memory is used throughout all paths:**

```
WorkingMemory (Short-term - 40% budget)
  • Current conversation
  • Task context
  • Recent tool outputs

EpisodicMemory (Medium-term - 20% budget)
  • Conversation turns
  • Experience summaries
  • Learning from past

SemanticMemory (Long-term - 40% budget)
  • Code contexts
  • Solutions database
  • Design patterns

MemoryManager
  • Allocates budget (40/20/40)
  • Retrieves relevant context
  • Stores new experiences
```

**Used at these points:**
1. Before execution: Retrieve relevant past experiences
2. During execution: Store tool results, track progress
3. After execution: Store conversation turn, update learning

---

## 🔍 RAG Flow

**RAG is used in Direct Execution:**

```
User query
  ↓
ContextBuilder.build_context(use_rag=True)
  ↓
HybridRetriever.retrieve(query)
  |
  ├─→ Semantic Search (70%)
  |     • Generate query embedding
  |     • Search vector store
  |     • Return similar code chunks
  |
  └─→ Keyword Search (30%)
        • BM25 algorithm
        • Exact keyword matching
        • Return matching chunks
  ↓
Combine results
  ↓
Return top K relevant code chunks
  ↓
Include in LLM context
```

**Components:**
- `CodeIndexer` - Index codebase into chunks
- `Embedder` - Generate embeddings via Alibaba API
- `VectorStore` - Store and search embeddings
- `HybridRetriever` - Combine semantic + keyword

---

## 📁 Component File Map

| Component | File Path | Purpose |
|-----------|-----------|---------|
| CLI | `src/cli.py` | User interface |
| CodingAgent | `src/core/agent.py` | Main orchestrator |
| TaskAnalyzer | `src/workflow/task_analyzer.py` | Analyze complexity |
| TaskPlanner | `src/workflow/task_planner.py` | Create execution plans |
| ExecutionEngine | `src/workflow/execution_engine.py` | Execute plans |
| VerificationLayer | `src/workflow/verification_layer.py` | Verify results |
| PermissionManager | `src/workflow/permission_manager.py` | Handle approvals |
| ContextBuilder | `src/core/context_builder.py` | Build LLM context |
| FileReferenceParser | `src/core/file_reference_parser.py` | Parse @file refs |
| ToolExecutor | `src/tools/base.py` | Execute tools |
| MemoryManager | `src/memory/memory_manager.py` | Manage all memory |
| WorkingMemory | `src/memory/working_memory.py` | Short-term memory |
| EpisodicMemory | `src/memory/episodic_memory.py` | Medium-term memory |
| SemanticMemory | `src/memory/semantic_memory.py` | Long-term memory |
| CodeIndexer | `src/rag/code_indexer.py` | Index codebase |
| Embedder | `src/rag/embedder.py` | Generate embeddings |
| HybridRetriever | `src/rag/retriever.py` | Retrieve code |
| LLM Backend | `src/llm/*` | LLM interface |

---

## 🎯 Summary

**2 Main Execution Paths:**
1. **Workflow** - Complex, multi-step, code modification tasks
2. **Direct** - Simple queries, explanations, searches

**Decision based on:**
- Task type (implement, refactor, debug → Workflow)
- Keywords in query
- Complexity inference

**Key Components:**
- 7 Workflow components (Analyzer, Planner, Engine, Verifier, etc.)
- 3 Memory systems (Working, Episodic, Semantic)
- RAG system (Indexer, Embedder, Retriever)
- 10+ Tools (file ops, git, search, etc.)

**Data Flow:**
- User input → Agent → Decision → Path → Tools → Response
- Memory used throughout
- RAG used in Direct path
- Hooks can intercept at multiple points

---

**This document captures the complete execution flows as discovered from code analysis.**
