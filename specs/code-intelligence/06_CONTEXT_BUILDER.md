# ContextBuilder Enhancements

**Status**: Ready for implementation
**Estimated Time**: 0.5 hours
**Lines of Code**: ~150 LOC (modifications to existing class)
**Dependencies**: CodeIntelligenceOrchestrator

---

## Overview

The **ContextBuilder** enhancements integrate Code Intelligence with existing context assembly:

### Changes Required

1. **Token Budget Reallocation** - Reduce RAG/memory, add ClarAIty/LSP layers
2. **Orchestrator Integration** - Use CodeIntelligenceOrchestrator for smart context loading
3. **Multi-Tier Assembly** - Combine system + task + ClarAIty + RAG + LSP + memory

### Current vs Enhanced

**Before:**
```python
# Old token allocation
system_prompt: 15%  (unchanged)
task: 20%
rag: 30%           # Wasteful full-chunk loading
memory: 35%
```

**After:**
```python
# New token allocation
system_prompt: 15%  (unchanged)
task: 10%          # Reduced (less task description needed)
claraity: 10%       # NEW - Component architecture
rag: 20%           # Reduced (precision from LSP reduces need)
lsp: 20%           # NEW - Symbol-level precision
memory: 25%        # Reduced (smarter context = less memory needed)
```

**Expected Impact:**
- **50%+ token efficiency** - Multi-tier loading vs full-chunk RAG
- **Better context quality** - Precision (LSP) + breadth (RAG) + architecture (ClarAIty)
- **Backward compatible** - Works with/without Code Intelligence enabled

---

## Architecture

```
ContextBuilder (Enhanced)
    │
    ├─> orchestrator: Optional[CodeIntelligenceOrchestrator]  # NEW
    ├─> max_context_tokens: int (unchanged)
    │
    └─> build_context() -> str  # MODIFIED
        │
        ├─> 1. System Prompt (15%) - unchanged
        ├─> 2. Task Description (10%) - reduced
        ├─> 3. Multi-Tier Context (50%) - NEW
        │   ├─> ClarAIty Layer (10%)
        │   ├─> RAG Layer (20%)
        │   └─> LSP Layer (20%)
        └─> 4. Memory (25%) - reduced
```

---

## Public Interface Changes

### Modified Constructor

```python
class ContextBuilder:
    """Build context for agent prompts (ENHANCED with Code Intelligence)."""

    def __init__(
        self,
        max_context_tokens: int = 8000,
        memory_manager: Optional[MemoryManager] = None,
        rag_retriever: Optional[HybridRetriever] = None,
        orchestrator: Optional[CodeIntelligenceOrchestrator] = None  # NEW
    ):
        """
        Initialize ContextBuilder.

        Args:
            max_context_tokens: Maximum total context tokens
            memory_manager: Optional memory manager
            rag_retriever: Optional RAG retriever (legacy fallback)
            orchestrator: Optional Code Intelligence orchestrator (NEW)
        """
        self.max_context_tokens = max_context_tokens
        self.memory_manager = memory_manager
        self.rag_retriever = rag_retriever
        self.orchestrator = orchestrator  # NEW

        import logging
        self.logger = logging.getLogger("context_builder")
```

---

### Modified build_context Method

```python
async def build_context(
    self,
    task_description: str,
    file_path: Optional[str] = None,  # NEW - for LSP queries
    line: Optional[int] = None,       # NEW - for LSP queries
    column: Optional[int] = None      # NEW - for LSP queries
) -> str:
    """
    Build complete context for agent prompt.

    ENHANCED: Uses Code Intelligence orchestrator for multi-tier context loading.

    Args:
        task_description: User's task
        file_path: Optional file path for LSP context (NEW)
        line: Optional line number for LSP context (NEW)
        column: Optional column number for LSP context (NEW)

    Returns:
        Assembled context string

    Example:
        >>> context = await builder.build_context(
        ...     task_description="Fix the authentication bug",
        ...     file_path="src/auth.py",
        ...     line=45,
        ...     column=10
        ... )
        >>> print(len(context.split()))  # Optimized token usage
    """
    context_parts = []

    # Token budget allocation (NEW)
    system_tokens = int(self.max_context_tokens * 0.15)  # 15%
    task_tokens = int(self.max_context_tokens * 0.10)    # 10% (reduced from 20%)
    smart_tokens = int(self.max_context_tokens * 0.50)   # 50% (ClarAIty + RAG + LSP)
    memory_tokens = int(self.max_context_tokens * 0.25)  # 25% (reduced from 35%)

    # 1. System Prompt (unchanged)
    system_prompt = self._get_system_prompt()
    context_parts.append(self._truncate(system_prompt, system_tokens))

    # 2. Task Description (reduced)
    context_parts.append(f"[TASK]\n{self._truncate(task_description, task_tokens)}")

    # 3. Multi-Tier Context (NEW)
    if self.orchestrator:
        # Use Code Intelligence orchestrator
        smart_context = await self.orchestrator.load_smart_context(
            task_description=task_description,
            file_path=file_path,
            line=line,
            column=column,
            max_tokens=smart_tokens
        )

        self.logger.info(
            f"Loaded {smart_context.token_count} tokens from "
            f"{smart_context.query_type} query"
        )
        self.logger.debug(
            f"Sources: ClarAIty={smart_context.sources['claraity']}, "
            f"RAG={smart_context.sources['rag']}, "
            f"LSP={smart_context.sources['lsp']}"
        )

        context_parts.append(smart_context.full_context)

    elif self.rag_retriever:
        # Fallback to legacy RAG-only (if orchestrator not available)
        rag_results = self.rag_retriever.retrieve(
            query=task_description,
            top_k=5
        )
        rag_context = self._format_rag_results(rag_results)
        context_parts.append(self._truncate(rag_context, smart_tokens))

    # 4. Memory (reduced budget)
    if self.memory_manager:
        memory_context = self.memory_manager.get_relevant_memories(
            query=task_description,
            max_tokens=memory_tokens
        )
        if memory_context:
            context_parts.append(f"[MEMORY]\n{memory_context}")

    return "\n\n".join(context_parts)
```

---

## Implementation Details

### Helper Method: _truncate (unchanged)

```python
def _truncate(self, text: str, max_tokens: int) -> str:
    """
    Truncate text to max tokens.

    Uses tiktoken to count tokens accurately.

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens

    Returns:
        Truncated text
    """
    from tiktoken import encoding_for_model

    enc = encoding_for_model("gpt-4")
    tokens = enc.encode(text)

    if len(tokens) <= max_tokens:
        return text

    # Truncate and decode
    truncated_tokens = tokens[:max_tokens]
    return enc.decode(truncated_tokens)
```

---

### Helper Method: _format_rag_results (unchanged)

```python
def _format_rag_results(self, results: List[Dict]) -> str:
    """
    Format RAG results for context.

    Args:
        results: RAG retrieval results

    Returns:
        Formatted context string
    """
    if not results:
        return ""

    context_parts = ["[RAG CONTEXT]\n"]

    for result in results:
        file_path = result.get("file_path", "unknown")
        score = result.get("score", 0)
        content = result.get("content", "")

        context_parts.append(f"File: {file_path} (score: {score:.2f})")
        context_parts.append(content)
        context_parts.append("---")

    return "\n".join(context_parts)
```

---

## Migration Path

### Phase 1: Add Orchestrator (Optional)

```python
# Existing agents work without changes
builder = ContextBuilder(
    max_context_tokens=8000,
    memory_manager=memory_mgr,
    rag_retriever=retriever
)
# Uses legacy RAG-only path
```

### Phase 2: Enable Code Intelligence

```python
# New agents enable Code Intelligence
orchestrator = CodeIntelligenceOrchestrator(lsp_manager, rag_retriever)

builder = ContextBuilder(
    max_context_tokens=8000,
    memory_manager=memory_mgr,
    rag_retriever=retriever,
    orchestrator=orchestrator  # NEW
)
# Uses multi-tier smart context loading
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **Backward compatible** - Works with/without orchestrator
- [ ] **Token allocation** respects new budget (15-10-50-25)
- [ ] **Multi-tier loading** combines all layers correctly
- [ ] **Graceful degradation** falls back to RAG if orchestrator unavailable

### Performance Targets

- [ ] **Context building**: <3 seconds (including LSP queries)
- [ ] **Token efficiency**: 50%+ improvement vs legacy RAG-only

### Quality Metrics

- [ ] **Test coverage**: 90%+
- [ ] **Integration tests** with real orchestrator
- [ ] **Backward compatibility tests** (orchestrator=None)

---

## Testing Strategy

### Unit Tests (tests/test_context_builder_enhanced.py)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_build_context_with_orchestrator():
    """Test context building with Code Intelligence."""
    orchestrator = MagicMock()
    orchestrator.load_smart_context = AsyncMock(return_value=SmartContext(
        full_context="[CLARAITY] ...\n[LSP] ...\n[RAG] ...",
        token_count=1500,
        sources={"claraity": 300, "rag": 500, "lsp": 700},
        query_type="SYMBOLIC",
        metadata={}
    ))

    builder = ContextBuilder(
        max_context_tokens=8000,
        orchestrator=orchestrator
    )

    context = await builder.build_context(
        task_description="Fix auth bug",
        file_path="src/auth.py",
        line=45,
        column=10
    )

    # Assertions
    assert "[TASK]" in context
    assert "[CLARAITY]" in context
    assert "[LSP]" in context
    orchestrator.load_smart_context.assert_called_once()

@pytest.mark.asyncio
async def test_build_context_without_orchestrator():
    """Test backward compatibility (legacy RAG-only)."""
    rag_retriever = MagicMock()
    rag_retriever.retrieve = MagicMock(return_value=[
        {"file_path": "src/auth.py", "content": "def auth()...", "score": 0.9}
    ])

    builder = ContextBuilder(
        max_context_tokens=8000,
        rag_retriever=rag_retriever,
        orchestrator=None  # No Code Intelligence
    )

    context = await builder.build_context(task_description="Fix bug")

    # Should use legacy RAG path
    assert "[RAG CONTEXT]" in context
    rag_retriever.retrieve.assert_called_once()

@pytest.mark.asyncio
async def test_token_budget_allocation():
    """Test token budgets are respected."""
    orchestrator = MagicMock()
    orchestrator.load_smart_context = AsyncMock(return_value=SmartContext(
        full_context="x" * 10000,  # Exceeds budget
        token_count=10000,
        sources={},
        query_type="COMPLEX",
        metadata={}
    ))

    builder = ContextBuilder(
        max_context_tokens=8000,
        orchestrator=orchestrator
    )

    context = await builder.build_context(task_description="Test")

    # Context should be truncated to fit budget
    from tiktoken import encoding_for_model
    enc = encoding_for_model("gpt-4")
    total_tokens = len(enc.encode(context))

    assert total_tokens <= 8000  # Within budget
```

---

## Implementation Patterns

### Pattern: Graceful Degradation

```python
# Use Code Intelligence if available, fallback to RAG otherwise
if self.orchestrator:
    smart_context = await self.orchestrator.load_smart_context(...)
    context_parts.append(smart_context.full_context)
elif self.rag_retriever:
    # Legacy RAG-only path
    rag_results = self.rag_retriever.retrieve(...)
    context_parts.append(self._format_rag_results(rag_results))
```

### Pattern: Token Budget Management

```python
# Allocate tokens based on priority
system_tokens = int(max_tokens * 0.15)   # System prompt (highest priority)
smart_tokens = int(max_tokens * 0.50)    # Multi-tier context (largest share)
memory_tokens = int(max_tokens * 0.25)   # Memory (lowest priority)

# Truncate each section to fit budget
context_parts.append(self._truncate(system_prompt, system_tokens))
```

### Antipattern: Hardcoded Token Counts

```python
# BAD: Hardcoded tokens don't scale with max_context_tokens
smart_context = await orchestrator.load_smart_context(max_tokens=2000)

# GOOD: Proportional allocation
smart_tokens = int(self.max_context_tokens * 0.50)
smart_context = await orchestrator.load_smart_context(max_tokens=smart_tokens)
```

---

## File Location

**Path**: `src/core/context_builder.py` (modifications to existing file)

**Lines to modify**: ~50 lines
**Lines to add**: ~100 lines
**Total changes**: ~150 LOC

---

## Example Usage

### Before (Legacy)

```python
builder = ContextBuilder(max_context_tokens=8000, rag_retriever=retriever)
context = await builder.build_context("Fix authentication bug")
# Uses RAG only, loads full chunks
```

### After (Code Intelligence Enabled)

```python
orchestrator = CodeIntelligenceOrchestrator(lsp_manager, rag_retriever)
builder = ContextBuilder(
    max_context_tokens=8000,
    orchestrator=orchestrator
)

context = await builder.build_context(
    task_description="Fix authentication bug",
    file_path="src/auth.py",
    line=45,
    column=10
)
# Uses ClarAIty + RAG + LSP, multi-tier loading, 50% more efficient
```

---

**Status**: ✅ Ready for implementation
**Next**: Read [07_AGENT_INTEGRATION.md](07_AGENT_INTEGRATION.md)
