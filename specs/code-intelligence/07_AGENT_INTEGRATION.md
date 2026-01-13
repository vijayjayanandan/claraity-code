# Agent Integration

**Status**: Ready for implementation
**Estimated Time**: 0.5 hours
**Lines of Code**: ~100 LOC (modifications to agent.py)
**Dependencies**: All Code Intelligence components

---

## Overview

The **Agent Integration** connects all Code Intelligence components to the agent:

### Changes Required

1. **Import statements** - Add Code Intelligence imports
2. **Constructor changes** - Initialize LSP manager, orchestrator
3. **Tool registration** - Register 7 Code Intelligence tools
4. **Context builder integration** - Pass orchestrator to ContextBuilder
5. **Shutdown lifecycle** - Cleanup LSP servers on agent shutdown

### Integration Points

```
CodingAgent
    │
    ├─> lsp_manager: LSPClientManager  # NEW
    ├─> orchestrator: CodeIntelligenceOrchestrator  # NEW
    ├─> context_builder: ContextBuilder (enhanced)
    │
    └─> Lifecycle:
        ├─> __init__() - Initialize Code Intelligence
        ├─> _register_tools() - Register 7 tools
        └─> shutdown() - Cleanup LSP servers
```

---

## Implementation Changes

### 1. Import Statements

```python
# In src/core/agent.py (top of file)

# Existing imports
from src.core.context_builder import ContextBuilder
from src.tools.base import BaseTool, ToolExecutor
from src.llm.openai_backend import OpenAIBackend
# ... other imports

# NEW: Code Intelligence imports
from src.code_intelligence.config import CodeIntelligenceConfig
from src.code_intelligence.lsp_client_manager import LSPClientManager
from src.code_intelligence.cache import LSPCache
from src.code_intelligence.orchestrator import CodeIntelligenceOrchestrator
from src.code_intelligence.tools import (
    GetSymbolDefinitionTool,
    GetSymbolReferencesTool,
    GetSymbolHoverTool,
    GetDocumentSymbolsTool,
    AnalyzeSymbolTool,
    SearchCodeWithLSPTool,
    LoadSmartContextTool,
)
```

---

### 2. Constructor Modifications

```python
class CodingAgent:
    """AI Coding Agent (ENHANCED with Code Intelligence)."""

    def __init__(
        self,
        model: str = "gpt-4",
        max_context_tokens: int = 8000,
        enable_code_intelligence: bool = True,  # NEW
        repo_root: Optional[str] = None  # NEW
    ):
        """
        Initialize Coding Agent.

        Args:
            model: LLM model name
            max_context_tokens: Maximum context tokens
            enable_code_intelligence: Enable LSP + MCP integration (NEW)
            repo_root: Repository root (auto-detected if None) (NEW)
        """
        self.model = model
        self.max_context_tokens = max_context_tokens

        # Initialize LLM backend
        self.llm = OpenAIBackend(model=model)

        # Initialize tool executor
        self.tool_executor = ToolExecutor()

        # Initialize RAG components (existing)
        from src.rag.embedder import Embedder
        from src.rag.retriever import HybridRetriever

        self.embedder = Embedder()
        self.retriever = HybridRetriever(embedder=self.embedder)

        # Initialize memory manager (existing)
        from src.memory.memory_manager import MemoryManager
        self.memory_manager = MemoryManager()

        # NEW: Initialize Code Intelligence (if enabled)
        self.lsp_manager = None
        self.orchestrator = None

        if enable_code_intelligence:
            self._initialize_code_intelligence(repo_root)

        # Initialize context builder (enhanced)
        self.context_builder = ContextBuilder(
            max_context_tokens=max_context_tokens,
            memory_manager=self.memory_manager,
            rag_retriever=self.retriever,
            orchestrator=self.orchestrator  # NEW
        )

        # Register all tools
        self._register_tools()

        import logging
        self.logger = logging.getLogger("agent")

    def _initialize_code_intelligence(self, repo_root: Optional[str]) -> None:
        """
        Initialize Code Intelligence components.

        Args:
            repo_root: Repository root (auto-detected if None)
        """
        try:
            # Auto-detect configuration
            config = CodeIntelligenceConfig.auto_detect(repo_root=repo_root)

            if not config.enabled:
                self.logger.info("Code Intelligence disabled by config")
                return

            self.logger.info(
                f"Initializing Code Intelligence for languages: {config.languages}"
            )

            # Initialize LSP cache
            cache = LSPCache(
                max_size_mb=config.cache_size_mb,
                ttl_seconds=config.cache_ttl_seconds
            )

            # Initialize LSP client manager
            self.lsp_manager = LSPClientManager(
                config=config,
                cache=cache
            )

            # Initialize orchestrator
            # (Pass clarity_db if available)
            clarity_db = getattr(self, 'clarity_db', None)

            self.orchestrator = CodeIntelligenceOrchestrator(
                lsp_manager=self.lsp_manager,
                rag_retriever=self.retriever,
                clarity_db=clarity_db,
                config=config
            )

            self.logger.info("Code Intelligence initialized successfully")

        except Exception as e:
            self.logger.warning(
                f"Failed to initialize Code Intelligence: {e}. "
                f"Falling back to RAG-only mode."
            )
            self.lsp_manager = None
            self.orchestrator = None
```

---

### 3. Tool Registration

```python
def _register_tools(self) -> None:
    """Register all agent tools."""
    # Existing file operation tools
    from src.tools.file_operations import (
        ReadFileTool,
        WriteFileTool,
        EditFileTool,
        # ... other tools
    )

    self.tool_executor.register_tool(ReadFileTool())
    self.tool_executor.register_tool(WriteFileTool())
    # ... register other existing tools

    # Existing ClarAIty tools
    from src.tools.clarity_tools import (
        QueryComponentTool,
        GetNextTaskTool,
        # ... other ClarAIty tools
    )

    self.tool_executor.register_tool(QueryComponentTool())
    self.tool_executor.register_tool(GetNextTaskTool())
    # ... register other ClarAIty tools

    # NEW: Register Code Intelligence tools (if enabled)
    if self.lsp_manager and self.orchestrator:
        self._register_code_intelligence_tools()

def _register_code_intelligence_tools(self) -> None:
    """Register Code Intelligence tools."""
    # Fine-grained tools
    self.tool_executor.register_tool(
        GetSymbolDefinitionTool(self.lsp_manager)
    )
    self.tool_executor.register_tool(
        GetSymbolReferencesTool(self.lsp_manager)
    )
    self.tool_executor.register_tool(
        GetSymbolHoverTool(self.lsp_manager)
    )
    self.tool_executor.register_tool(
        GetDocumentSymbolsTool(self.lsp_manager)
    )

    # Coarse-grained tools
    self.tool_executor.register_tool(
        AnalyzeSymbolTool(self.lsp_manager)
    )
    self.tool_executor.register_tool(
        SearchCodeWithLSPTool(self.lsp_manager)
    )
    self.tool_executor.register_tool(
        LoadSmartContextTool(self.orchestrator)
    )

    self.logger.info("Registered 7 Code Intelligence tools")
```

---

### 4. Shutdown Lifecycle

```python
async def shutdown(self) -> None:
    """
    Shutdown agent and cleanup resources.

    NEW: Closes all LSP servers gracefully.
    """
    self.logger.info("Shutting down agent...")

    # NEW: Close LSP servers
    if self.lsp_manager:
        await self.lsp_manager.close_all_servers()
        self.logger.info("Closed all LSP servers")

    # Existing cleanup (if any)
    # ...

    self.logger.info("Agent shutdown complete")
```

---

## Configuration Options

### Option 1: Enable Code Intelligence (Default)

```python
agent = CodingAgent(
    model="gpt-4",
    enable_code_intelligence=True,  # Default
    repo_root="/path/to/repo"  # Optional, auto-detected if None
)
# Uses multi-tier context (ClarAIty + RAG + LSP)
```

### Option 2: Disable Code Intelligence

```python
agent = CodingAgent(
    model="gpt-4",
    enable_code_intelligence=False
)
# Uses legacy RAG-only mode
```

### Option 3: Auto-Detect from Environment

```bash
# Disable via environment variable
export CODE_INTEL_ENABLED=false

# Or via config file
echo '{"enabled": false}' > .code-intelligence.json
```

```python
agent = CodingAgent(model="gpt-4")
# Reads CODE_INTEL_ENABLED and config file
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **Code Intelligence initializes** when enabled
- [ ] **7 tools registered** correctly
- [ ] **Graceful fallback** to RAG-only if initialization fails
- [ ] **Shutdown cleanup** closes LSP servers
- [ ] **Backward compatible** - existing agents work without changes

### Quality Metrics

- [ ] **Test coverage**: 90%+
- [ ] **Integration tests** with real LSP servers
- [ ] **Fallback tests** (Code Intelligence disabled)

---

## Testing Strategy

### Unit Tests (tests/test_agent_integration.py)

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

def test_agent_with_code_intelligence():
    """Test agent initialization with Code Intelligence."""
    with patch('src.core.agent.CodeIntelligenceConfig.auto_detect') as mock_config:
        mock_config.return_value = MagicMock(
            enabled=True,
            languages=["python"],
            cache_size_mb=10
        )

        agent = CodingAgent(
            enable_code_intelligence=True,
            repo_root="/tmp/test_repo"
        )

        # Should initialize LSP manager and orchestrator
        assert agent.lsp_manager is not None
        assert agent.orchestrator is not None

        # Should register 7 Code Intelligence tools
        # (Check tool_executor.tools contains 7 new tools)
        tool_names = [tool.name for tool in agent.tool_executor.tools]
        assert "get_symbol_definition" in tool_names
        assert "analyze_symbol" in tool_names
        assert "load_smart_context" in tool_names

def test_agent_without_code_intelligence():
    """Test agent initialization without Code Intelligence."""
    agent = CodingAgent(enable_code_intelligence=False)

    # Should NOT initialize LSP manager
    assert agent.lsp_manager is None
    assert agent.orchestrator is None

    # Should still work (legacy RAG-only)
    assert agent.retriever is not None
    assert agent.context_builder is not None

@pytest.mark.asyncio
async def test_agent_shutdown():
    """Test agent shutdown closes LSP servers."""
    agent = CodingAgent(enable_code_intelligence=False)
    agent.lsp_manager = MagicMock()
    agent.lsp_manager.close_all_servers = AsyncMock()

    await agent.shutdown()

    # Should call close_all_servers
    agent.lsp_manager.close_all_servers.assert_called_once()

def test_agent_graceful_fallback():
    """Test graceful fallback when Code Intelligence fails."""
    with patch('src.core.agent.CodeIntelligenceConfig.auto_detect') as mock_config:
        mock_config.side_effect = Exception("Config failed")

        agent = CodingAgent(enable_code_intelligence=True)

        # Should fall back to RAG-only (no crash)
        assert agent.lsp_manager is None
        assert agent.orchestrator is None
        assert agent.retriever is not None  # RAG still works
```

---

## Implementation Patterns

### Pattern: Lazy Initialization

```python
# Code Intelligence initializes only when enabled
if enable_code_intelligence:
    self._initialize_code_intelligence(repo_root)
# No overhead if disabled
```

### Pattern: Graceful Degradation

```python
# If Code Intelligence fails, fall back to RAG
try:
    self._initialize_code_intelligence(repo_root)
except Exception as e:
    self.logger.warning(f"Falling back to RAG-only: {e}")
    self.lsp_manager = None
    self.orchestrator = None
# Agent still works, just without LSP features
```

### Pattern: Conditional Tool Registration

```python
# Register Code Intelligence tools only if available
if self.lsp_manager and self.orchestrator:
    self._register_code_intelligence_tools()
# Avoids registering broken tools
```

### Antipattern: Hardcoding repo_root

```python
# BAD: Hardcoded path won't work across machines
agent = CodingAgent(repo_root="/Users/alice/projects/my-app")

# GOOD: Auto-detect or use environment variable
agent = CodingAgent()  # Auto-detects git root
```

---

## Migration Guide

### Existing Agents (No Changes Required)

```python
# Before (still works)
agent = CodingAgent(model="gpt-4")
# Code Intelligence auto-enabled by default
```

### New Agents (Explicitly Enable/Disable)

```python
# Enable Code Intelligence
agent = CodingAgent(
    model="gpt-4",
    enable_code_intelligence=True,
    repo_root="/path/to/repo"
)

# Disable Code Intelligence
agent = CodingAgent(
    model="gpt-4",
    enable_code_intelligence=False
)
```

---

## File Location

**Path**: `src/core/agent.py` (modifications to existing file)

**Lines to modify**: ~30 lines
**Lines to add**: ~70 lines
**Total changes**: ~100 LOC

---

## Example Usage

### Complete Agent with Code Intelligence

```python
from src.core.agent import CodingAgent

# Initialize agent with Code Intelligence
agent = CodingAgent(
    model="gpt-4",
    max_context_tokens=8000,
    enable_code_intelligence=True,
    repo_root="/path/to/my-project"
)

# Agent now has:
# - 7 Code Intelligence tools (LSP queries)
# - Multi-tier context loading (ClarAIty + RAG + LSP)
# - Smart token budget allocation
# - LSP cache (10MB, 5min TTL)

# Run task with enhanced context
result = await agent.run(
    task="Fix the authentication bug in src/auth.py line 45"
)

# Shutdown gracefully
await agent.shutdown()
```

---

**Status**: ✅ Ready for implementation
**Next**: Begin implementation starting with [01_LSP_CLIENT_MANAGER.md](01_LSP_CLIENT_MANAGER.md)

---

## Implementation Order

**Recommended sequence:**

1. **LSPCache** (02) - No dependencies, simple to test
2. **LSPClientManager** (01) - Depends on cache
3. **CodeIntelligenceConfig** (04) - Standalone, no dependencies
4. **CodeIntelligenceOrchestrator** (03) - Depends on LSPClientManager
5. **Code Intelligence Tools** (05) - Depends on LSPClientManager + Orchestrator
6. **ContextBuilder** (06) - Depends on Orchestrator
7. **Agent Integration** (07) - Depends on all components

**Total estimated time:** 7-10 hours

**Testing approach:**
- Unit tests for each component (90%+ coverage)
- Integration tests after Tool registration (05)
- End-to-end tests after Agent integration (07)
