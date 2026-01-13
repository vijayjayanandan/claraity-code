# Code Intelligence: System Overview

**Status**: Ready for implementation
**Total Estimated Time**: 7-10 hours
**Total Lines of Code**: ~1,750 LOC

---

## Table of Contents

1. [What We're Building](#what-were-building)
2. [System Architecture](#system-architecture)
3. [Component Interaction](#component-interaction)
4. [Data Flow](#data-flow)
5. [Token Budget Strategy](#token-budget-strategy)
6. [Implementation Order](#implementation-order)
7. [Success Criteria](#success-criteria)

---

## What We're Building

### Vision

Transform our AI Coding Agent into a **state-of-the-art system** by integrating:
- **LSP (Language Server Protocol)** - Symbol-level code intelligence
- **MCP (Model Context Protocol)** - Industry-standard tool integration
- **Multi-tier context loading** - ClarAIty (architecture) + RAG (semantic) + LSP (symbolic)

### Problem We're Solving

**Current limitation**: Agent loads full code chunks (400+ tokens each) even when only symbol definitions are needed.

**Example**:
```
User asks: "What type does authenticate() return?"

Current approach (RAG only):
  Loads entire function (100 lines, 400 tokens)

  def authenticate(username: str, password: str) -> bool:
      # 100 lines of implementation...
      return result

Improved approach (with LSP):
  Loads just the signature (5 tokens)

  authenticate(username: str, password: str) -> bool
```

**Result**: 50%+ token efficiency improvement for symbol queries.

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AI CODING AGENT                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              CONTEXT BUILDER (Enhanced)                  │  │
│  │                                                          │  │
│  │  Token Budget Allocation:                               │  │
│  │  - System Prompt: 15%                                    │  │
│  │  - Task: 10%                                             │  │
│  │  - ClarAIty: 10% (architectural)  ← NEW                 │  │
│  │  - RAG: 20% (semantic)            ← REDUCED             │  │
│  │  - LSP: 20% (symbolic)            ← NEW                 │  │
│  │  - Memory: 25% (conversation)     ← REDUCED             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         CODE INTELLIGENCE ORCHESTRATOR                   │  │
│  │                                                          │  │
│  │  Query Classification → Layer Weight Allocation          │  │
│  │  Multi-tier Loading → Context Assembly                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│         │                    │                    │             │
│         ▼                    ▼                    ▼             │
│  ┌──────────┐        ┌──────────┐        ┌──────────┐         │
│  │ ClarAIty │        │   RAG    │        │   LSP    │         │
│  │ Database │        │ Retriever│        │ Manager  │         │
│  └──────────┘        └──────────┘        └──────────┘         │
│       │                    │                    │               │
│       │                    │                    │               │
│       ▼                    ▼                    ▼               │
│  Components           CodeChunks          LanguageServers      │
│  Architecture         Embeddings          (Python, TS, Rust)   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Component Architecture

```
src/code_intelligence/
├── lsp_manager.py          (01) LSP Client Manager
│   ├── LSPClientManager
│   ├── Language detection
│   ├── Server lifecycle
│   └── Query routing
│
├── cache.py                (02) LSP Cache
│   ├── LSPCache
│   ├── LRU eviction
│   └── File invalidation
│
├── orchestrator.py         (03) Orchestrator
│   ├── CodeIntelligenceOrchestrator
│   ├── Query classification
│   ├── Multi-tier loading
│   └── Context assembly
│
├── config.py               (04) Configuration
│   ├── CodeIntelligenceConfig
│   ├── Hierarchical loading
│   └── Auto-detection
│
└── __init__.py

src/tools/
└── code_intelligence_tools.py  (05) Tools
    ├── GetSymbolDefinitionTool
    ├── GetSymbolReferencesTool
    ├── GetSymbolHoverTool
    ├── GetDocumentSymbolsTool
    ├── AnalyzeSymbolTool
    ├── SearchCodeWithLSPTool
    └── LoadSmartContextTool

src/core/
├── context_builder.py      (06) ContextBuilder (Enhanced)
│   └── Multi-tier context assembly
│
└── agent.py                (07) Agent (Integration)
    └── Tool registration
```

---

## Component Interaction

### 1. Initialization Sequence

```
Agent.__init__()
    │
    ├─> Initialize existing components (LLM, Memory, RAG)
    │
    ├─> Create LSPClientManager (lazy)
    │   └─> Config loaded
    │       └─> Servers NOT started yet (wait for first query)
    │
    ├─> Create CodeIntelligenceOrchestrator
    │   └─> Wires together: LSPManager + ClarityDB + RAG
    │
    ├─> Enhanced ContextBuilder
    │   └─> Now has access to: orchestrator, lsp_manager, clarity_db
    │
    └─> Register Code Intelligence Tools
        └─> 7 tools added to ToolExecutor
```

### 2. Query Execution Flow

```
User Query: "What type does authenticate() return?"
    │
    ▼
Agent.chat(message)
    │
    ▼
ContextBuilder.build_context()
    │
    ├─> System Prompt (15%)
    │
    ├─> Orchestrator.load_smart_context()
    │   │
    │   ├─> Classify Query: SYMBOLIC
    │   │   (keywords: "type", "return")
    │   │
    │   ├─> Allocate Weights:
    │   │   ClarAIty: 10%, RAG: 20%, LSP: 70%
    │   │
    │   ├─> Load Layers (PARALLEL):
    │   │   │
    │   │   ├─> ClarAIty Layer (10%)
    │   │   │   └─> Search components for "authenticate"
    │   │   │       └─> Returns: AUTHENTICATION component context
    │   │   │
    │   │   ├─> RAG Layer (20%)
    │   │   │   └─> Semantic search for "authenticate"
    │   │   │       └─> Returns: 1 relevant code chunk
    │   │   │
    │   │   └─> LSP Layer (70%)
    │   │       │
    │   │       ├─> Detect language: Python
    │   │       │
    │   │       ├─> Get LSP server (lazy init if needed)
    │   │       │   └─> jedi-language-server started (5s first time)
    │   │       │
    │   │       ├─> Request hover info
    │   │       │   └─> authenticate(username: str, password: str) -> bool
    │   │       │
    │   │       └─> Cache result
    │   │
    │   └─> Assemble Context
    │       └─> Returns: Combined multi-tier context
    │
    └─> Memory Context (25%)

    ▼
Agent._execute_with_tools()
    │
    └─> LLM sees optimized context
        └─> Answers: "authenticate() returns bool"
```

### 3. Tool Execution Flow

```
LLM decides: "I need symbol definition"
    │
    ▼
Tool Call: get_symbol_definition(file="auth.py", line=45, column=10)
    │
    ▼
GetSymbolDefinitionTool.execute()
    │
    ├─> Detect language: Python (from .py extension)
    │
    ├─> LSPClientManager.request_definition()
    │   │
    │   ├─> Check cache
    │   │   └─> Cache miss
    │   │
    │   ├─> Get LSP server
    │   │   └─> Server already running (from previous query)
    │   │
    │   ├─> Query server
    │   │   └─> multilspy.request_definition()
    │   │       └─> Returns: location + signature
    │   │
    │   └─> Cache result
    │
    └─> Return to LLM
        └─> LLM uses definition info
```

---

## Data Flow

### Context Assembly Pipeline

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1: QUERY CLASSIFICATION                              │
├─────────────────────────────────────────────────────────────┤
│ Input: "What does authenticate() do?"                      │
│ Output: QueryType.ARCHITECTURAL                            │
│ Weights: ClarAIty 50%, RAG 30%, LSP 20%                    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2: MULTI-TIER LOADING (Parallel)                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│ │  ClarAIty   │  │     RAG     │  │     LSP     │         │
│ │  Layer      │  │    Layer    │  │    Layer    │         │
│ └─────────────┘  └─────────────┘  └─────────────┘         │
│       │                │                │                   │
│       ▼                ▼                ▼                   │
│  Components       CodeChunks        Symbols                │
│  (200 tokens)     (400 tokens)      (200 tokens)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STAGE 3: CONTEXT ASSEMBLY                                  │
├─────────────────────────────────────────────────────────────┤
│ <architectural_context>                                    │
│   [COMPONENT] Authentication                               │
│   Purpose: User authentication and authorization           │
│   Key Files: auth.py, login.py                             │
│ </architectural_context>                                   │
│                                                             │
│ <relevant_code>                                            │
│   [RELEVANT CODE 1] (score: 0.85)                          │
│   File: auth.py:45                                         │
│   ```python                                                │
│   def authenticate(username, password):                    │
│       ...                                                  │
│   ```                                                      │
│ </relevant_code>                                           │
│                                                             │
│ <symbol_definitions>                                       │
│   [SYMBOL] authenticate (function)                         │
│   Signature: (username: str, password: str) -> bool        │
│   Location: auth.py:45                                     │
│ </symbol_definitions>                                      │
│                                                             │
│ Total: 800 tokens (50% reduction vs RAG-only)              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
LLM Context
```

---

## Token Budget Strategy

### Before (RAG-Only)

```
Total: 4096 tokens

System Prompt:    615 tokens (15%)
Task Description: 819 tokens (20%)
RAG Context:     1229 tokens (30%)  ← 3 full code chunks
Memory:          1433 tokens (35%)
```

**Problem**: RAG loads full chunks even for simple queries

### After (Multi-Tier)

```
Total: 4096 tokens

System Prompt:    615 tokens (15%)
Task Description: 410 tokens (10%)  ← Reduced
ClarAIty Context: 410 tokens (10%)  ← NEW
RAG Context:      819 tokens (20%)  ← Reduced, 2 chunks
LSP Context:      819 tokens (20%)  ← NEW, symbol precision
Memory:          1023 tokens (25%)  ← Reduced
```

**Benefit**: Same total budget, 50%+ better quality (targeted context)

### Adaptive Allocation by Query Type

| Query Type | ClarAIty | RAG | LSP | Use Case |
|------------|----------|-----|-----|----------|
| **Architectural** | 50% | 30% | 20% | "How does auth work?" |
| **Semantic** | 10% | 70% | 20% | "Find similar code" |
| **Symbolic** | 10% | 20% | 70% | "What type is X?" |
| **Complex** | 33% | 33% | 34% | "Refactor module" |

---

## Implementation Order

### Phase 1: Foundation (Days 1-2)

**Components**:
1. **LSPClientManager** (01) - 1.5 hours
2. **LSPCache** (02) - 0.5 hours
3. **CodeIntelligenceConfig** (04) - 0.5 hours

**Milestone**: LSP queries working with Python language server

**Validation**:
```python
# Test script
lsp_manager = LSPClientManager(working_directory=Path.cwd())
result = await lsp_manager.request_definition("src/auth.py", 45, 10)
assert result["uri"] == "file:///.../auth.py"
```

### Phase 2: Orchestration (Days 2-3)

**Components**:
3. **CodeIntelligenceOrchestrator** (03) - 1.5 hours

**Milestone**: Multi-tier context loading working

**Validation**:
```python
# Test script
orchestrator = CodeIntelligenceOrchestrator(lsp_manager, clarity_db, retriever)
context = await orchestrator.load_smart_context("What does authenticate do?")
assert "architectural_context" in context["context"]
assert "relevant_code" in context["context"]
assert "symbol_definitions" in context["context"]
```

### Phase 3: Integration (Days 3-4)

**Components**:
5. **Code Intelligence Tools** (05) - 1 hour
6. **ContextBuilder Enhancements** (06) - 0.5 hours
7. **Agent Integration** (07) - 0.5 hours

**Milestone**: End-to-end agent queries using Code Intelligence

**Validation**:
```python
# Test script
agent = CodingAgent(...)
response = agent.chat("What type does authenticate() return?")
# Should use LSP for precise type info
```

### Phase 4: Testing & Validation (Days 4-5)

**Activities**:
- Performance benchmarks (token efficiency, latency)
- Integration tests (agent + tools + LSP)
- Code review (code-reviewer subagent)
- Bug fixes and polish

---

## Success Criteria

### Functional Requirements

- [ ] **LSP queries work** for Python, TypeScript, Rust
- [ ] **Multi-tier context loading** combines ClarAIty + RAG + LSP
- [ ] **Query classification** routes to appropriate layers
- [ ] **7 tools registered** and callable by agent
- [ ] **Graceful degradation** (fall back to RAG if LSP fails)
- [ ] **Windows compatibility** (no emojis, path normalization)

### Performance Targets

- [ ] **Token efficiency**: 50%+ reduction for symbol queries
- [ ] **First LSP query**: <10 seconds (including server init)
- [ ] **Subsequent queries**: <100ms (cached server)
- [ ] **Memory usage**: <900MB for 3 LSP servers
- [ ] **Context assembly**: <2 seconds total

### Quality Metrics

- [ ] **Test coverage**: 95%+ for all components
- [ ] **Integration tests**: Pass with real LSP servers
- [ ] **Code review**: APPROVE from code-reviewer subagent
- [ ] **Backward compatibility**: All existing tests pass

### User Experience

- [ ] **Progress indicators**: Show LSP initialization status
- [ ] **Clear errors**: Helpful messages if server fails
- [ ] **Zero config**: Works out-of-box for Python/TypeScript/Rust
- [ ] **Resource limits**: Prompt user if >3 servers

---

## Dependencies

### External Libraries

```bash
# Required
pip install multilspy        # LSP client (Microsoft)
pip install "mcp[cli]"       # MCP SDK (Phase 2, optional)

# Already installed
# openai, anthropic, rich, etc.
```

### Language Servers (Auto-downloaded by multilspy)

- **Python**: jedi-language-server (~50MB)
- **TypeScript**: typescript-language-server (~80MB)
- **Rust**: rust-analyzer (~150MB)

### Internal Dependencies

- **Existing**: ClarityDB, HybridRetriever, ContextBuilder, Agent
- **New**: All Code Intelligence components build on these

---

## Testing Strategy

### Unit Tests

```python
# tests/test_lsp_manager.py
def test_request_definition():
    """Test LSP definition query."""

# tests/test_lsp_cache.py
def test_cache_invalidation():
    """Test file-change invalidation."""

# tests/test_orchestrator.py
def test_query_classification():
    """Test query type detection."""
```

### Integration Tests

```python
# tests/test_lsp_integration_python.py
async def test_python_lsp_server():
    """Test with real Python LSP server."""

# tests/test_smart_context_loading.py
async def test_multi_tier_context():
    """Test end-to-end context loading."""
```

### Performance Tests

```python
# tests/test_lsp_performance.py
def test_token_efficiency():
    """Validate 50%+ token reduction."""

def test_query_latency():
    """Validate <100ms query time."""
```

---

## Configuration

### Environment Variables (.env)

```bash
# Feature flag
ENABLE_CODE_INTELLIGENCE=true

# Resource limits
LSP_MAX_SERVERS=3
LSP_SERVER_TIMEOUT=30

# Cache settings
LSP_CACHE_ENABLED=true
LSP_CACHE_SIZE_MB=10
LSP_CACHE_TTL_SECONDS=300

# Debug mode
LSP_DEBUG=false
LSP_LOG_FILE=.lsp_debug.log
```

### Configuration File (.code-intelligence.json)

```json
{
  "lsp_servers": {
    "python": {
      "server": "jedi-language-server",
      "command": "jedi-language-server",
      "args": []
    }
  },
  "language_mappings": {
    ".ipynb": "python"
  },
  "cache": {
    "enabled": true,
    "max_size_mb": 10,
    "ttl_seconds": 300
  },
  "resource_limits": {
    "max_concurrent_servers": 3
  }
}
```

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| LSP server crashes | High | Auto-restart, fall back to RAG |
| Token misallocation | Medium | Adaptive weights, validation metrics |
| Windows incompatibility | High | No emojis, CI/CD testing |
| Performance degradation | Medium | Caching, benchmarks |

---

## Next Steps

1. **Read specs in order**: 01 → 02 → 03 → ... → 07
2. **Implement components**: Follow implementation order
3. **Write tests**: Unit + integration + performance
4. **Validate**: Check acceptance criteria
5. **Code review**: Use code-reviewer subagent
6. **Deploy**: Feature flag rollout

---

**Status**: ✅ Ready for implementation
**First Task**: Read [01_LSP_CLIENT_MANAGER.md](01_LSP_CLIENT_MANAGER.md)
