# Code Intelligence Orchestrator

**Status**: Ready for implementation
**Estimated Time**: 1.5 hours
**Lines of Code**: ~500 LOC
**Dependencies**: LSPClientManager, LSPCache, RAG components, ClarAIty tools

---

## Overview

The **CodeIntelligenceOrchestrator** is the "Smart Context Loader" that intelligently combines three context layers:

- **ClarAIty Layer** (10% tokens) - High-level component architecture
- **RAG Layer** (20% tokens) - Semantic search over documentation/code
- **LSP Layer** (20% tokens) - Symbol-level precision (definitions, references, types)

### Why Multi-Tier Loading?

Traditional RAG loads full chunks wastefully. Our orchestrator:
- **Classifies queries** - Routes to appropriate layers (ARCHITECTURAL, SEMANTIC, SYMBOLIC, COMPLEX)
- **Allocates adaptively** - Adjusts token budgets based on query type
- **Combines intelligently** - Merges results from multiple layers
- **Falls back gracefully** - Uses RAG when LSP unavailable

**Expected Impact:**
- **50%+ token efficiency** - Load only what's needed
- **2x context quality** - Precision (LSP) + breadth (RAG)
- **Faster responses** - Less context = faster LLM processing

---

## Architecture

```
CodeIntelligenceOrchestrator
    │
    ├─> lsp_manager: LSPClientManager
    ├─> rag_retriever: HybridRetriever
    ├─> clarity_db: ClarityDB (optional)
    ├─> config: CodeIntelligenceConfig
    │
    └─> Methods:
        ├─> load_smart_context(task_description, file_path, line, column, max_tokens) -> SmartContext
        ├─> classify_query(task_description) -> QueryType
        ├─> load_clarity_context(task_description, max_tokens) -> str
        ├─> load_rag_context(task_description, max_tokens) -> str
        ├─> load_lsp_context(file_path, line, column, max_tokens) -> str
        └─> merge_contexts(clarity, rag, lsp) -> str

QueryType = Literal["ARCHITECTURAL", "SEMANTIC", "SYMBOLIC", "COMPLEX"]

SmartContext:
    - full_context: str
    - token_count: int
    - sources: Dict[str, int]  # {"clarity": 150, "rag": 300, "lsp": 400}
    - query_type: QueryType
```

---

## Public Interface

### Class: CodeIntelligenceOrchestrator

```python
from typing import Optional, Dict, Any, Literal
from dataclasses import dataclass

QueryType = Literal["ARCHITECTURAL", "SEMANTIC", "SYMBOLIC", "COMPLEX"]

@dataclass
class SmartContext:
    """Multi-tier context result."""
    full_context: str
    token_count: int
    sources: Dict[str, int]  # Token count per layer
    query_type: QueryType
    metadata: Dict[str, Any]

class CodeIntelligenceOrchestrator:
    """
    Smart context loader combining ClarAIty, RAG, and LSP.

    Features:
    - Query classification (routes to appropriate layers)
    - Adaptive token allocation (based on query type)
    - Multi-tier loading (combines 3 layers intelligently)
    - Graceful degradation (falls back to RAG on LSP failure)
    """

    def __init__(
        self,
        lsp_manager: LSPClientManager,
        rag_retriever: HybridRetriever,
        clarity_db: Optional[ClarityDB] = None,
        config: Optional[CodeIntelligenceConfig] = None
    ):
        """Initialize orchestrator."""

    async def load_smart_context(
        self,
        task_description: str,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
        max_tokens: int = 2000
    ) -> SmartContext:
        """Load multi-tier context adaptively."""

    def classify_query(self, task_description: str) -> QueryType:
        """Classify query into ARCHITECTURAL, SEMANTIC, SYMBOLIC, or COMPLEX."""

    async def load_clarity_context(
        self,
        task_description: str,
        max_tokens: int
    ) -> str:
        """Load ClarAIty context (component architecture)."""

    async def load_rag_context(
        self,
        task_description: str,
        max_tokens: int
    ) -> str:
        """Load RAG context (semantic search)."""

    async def load_lsp_context(
        self,
        file_path: str,
        line: int,
        column: int,
        max_tokens: int
    ) -> str:
        """Load LSP context (symbol definitions, references)."""
```

---

## Implementation Details

### Method: __init__

```python
def __init__(
    self,
    lsp_manager: LSPClientManager,
    rag_retriever: HybridRetriever,
    clarity_db: Optional[ClarityDB] = None,
    config: Optional[CodeIntelligenceConfig] = None
):
    """
    Initialize Code Intelligence Orchestrator.

    Args:
        lsp_manager: LSP client manager for symbol queries
        rag_retriever: Hybrid retriever for semantic search
        clarity_db: Optional ClarAIty DB for architecture queries
        config: Optional configuration (auto-detects if None)
    """
    self.lsp_manager = lsp_manager
    self.rag_retriever = rag_retriever
    self.clarity_db = clarity_db
    self.config = config or CodeIntelligenceConfig.auto_detect()

    import logging
    self.logger = logging.getLogger("code_intelligence.orchestrator")

    # Token allocation weights by query type
    self.allocation_weights = {
        "ARCHITECTURAL": {"clarity": 0.70, "rag": 0.20, "lsp": 0.10},
        "SEMANTIC": {"clarity": 0.10, "rag": 0.70, "lsp": 0.20},
        "SYMBOLIC": {"clarity": 0.05, "rag": 0.15, "lsp": 0.80},
        "COMPLEX": {"clarity": 0.20, "rag": 0.40, "lsp": 0.40},
    }
```

---

### Method: load_smart_context

```python
async def load_smart_context(
    self,
    task_description: str,
    file_path: Optional[str] = None,
    line: Optional[int] = None,
    column: Optional[int] = None,
    max_tokens: int = 2000
) -> SmartContext:
    """
    Load multi-tier context adaptively.

    Pipeline:
    1. Classify query type
    2. Allocate token budgets per layer
    3. Load contexts in parallel
    4. Merge and format results

    Args:
        task_description: User's task/query
        file_path: Optional file path (for LSP queries)
        line: Optional line number (for LSP queries)
        column: Optional column number (for LSP queries)
        max_tokens: Maximum total tokens for context

    Returns:
        SmartContext with merged results

    Example:
        >>> context = await orchestrator.load_smart_context(
        ...     task_description="What does authenticate() do?",
        ...     file_path="src/auth.py",
        ...     line=45,
        ...     column=10,
        ...     max_tokens=2000
        ... )
        >>> print(context.query_type)  # "SYMBOLIC"
        >>> print(context.sources)  # {"clarity": 100, "rag": 300, "lsp": 1600}
    """
    # Step 1: Classify query
    query_type = self.classify_query(task_description)
    self.logger.info(f"Query classified as: {query_type}")

    # Step 2: Allocate token budgets
    weights = self.allocation_weights[query_type]
    clarity_tokens = int(max_tokens * weights["clarity"])
    rag_tokens = int(max_tokens * weights["rag"])
    lsp_tokens = int(max_tokens * weights["lsp"])

    self.logger.debug(
        f"Token allocation: clarity={clarity_tokens}, "
        f"rag={rag_tokens}, lsp={lsp_tokens}"
    )

    # Step 3: Load contexts in parallel
    import asyncio

    tasks = []

    # ClarAIty (if available)
    if self.clarity_db and clarity_tokens > 0:
        tasks.append(self.load_clarity_context(task_description, clarity_tokens))
    else:
        tasks.append(asyncio.sleep(0, result=""))

    # RAG (always available)
    if rag_tokens > 0:
        tasks.append(self.load_rag_context(task_description, rag_tokens))
    else:
        tasks.append(asyncio.sleep(0, result=""))

    # LSP (if file/line/column provided)
    if file_path and line is not None and column is not None and lsp_tokens > 0:
        tasks.append(self.load_lsp_context(file_path, line, column, lsp_tokens))
    else:
        tasks.append(asyncio.sleep(0, result=""))

    clarity_ctx, rag_ctx, lsp_ctx = await asyncio.gather(*tasks)

    # Step 4: Merge contexts
    full_context = self.merge_contexts(clarity_ctx, rag_ctx, lsp_ctx)

    # Calculate actual token counts
    from tiktoken import encoding_for_model
    enc = encoding_for_model("gpt-4")
    actual_tokens = len(enc.encode(full_context))

    sources = {
        "clarity": len(enc.encode(clarity_ctx)) if clarity_ctx else 0,
        "rag": len(enc.encode(rag_ctx)) if rag_ctx else 0,
        "lsp": len(enc.encode(lsp_ctx)) if lsp_ctx else 0,
    }

    return SmartContext(
        full_context=full_context,
        token_count=actual_tokens,
        sources=sources,
        query_type=query_type,
        metadata={
            "file_path": file_path,
            "line": line,
            "column": column,
        }
    )
```

**Example**:
```python
orchestrator = CodeIntelligenceOrchestrator(lsp_manager, rag_retriever)

# SYMBOLIC query - 80% LSP, 15% RAG, 5% ClarAIty
context = await orchestrator.load_smart_context(
    task_description="What does authenticate() return?",
    file_path="src/auth.py",
    line=45,
    column=10,
    max_tokens=2000
)
# Result: Loads definition + type signature (LSP), related docs (RAG), component info (ClarAIty)

# ARCHITECTURAL query - 70% ClarAIty, 20% RAG, 10% LSP
context = await orchestrator.load_smart_context(
    task_description="How does authentication flow work?",
    max_tokens=2000
)
# Result: Loads component relationships (ClarAIty), implementation docs (RAG), key symbols (LSP)
```

---

### Method: classify_query

```python
def classify_query(self, task_description: str) -> QueryType:
    """
    Classify query into one of four types.

    Classification Logic:
    - ARCHITECTURAL: "how does X work", "what is architecture", "components"
    - SEMANTIC: "explain", "why", "when to use", "best practices"
    - SYMBOLIC: "what does X do", "where is X defined", "type of X"
    - COMPLEX: Multiple question types combined

    Args:
        task_description: User's task/query

    Returns:
        Query type (ARCHITECTURAL, SEMANTIC, SYMBOLIC, COMPLEX)

    Example:
        >>> orchestrator.classify_query("How does auth flow work?")
        "ARCHITECTURAL"
        >>> orchestrator.classify_query("What does authenticate() return?")
        "SYMBOLIC"
        >>> orchestrator.classify_query("Why do we use JWT tokens?")
        "SEMANTIC"
    """
    task_lower = task_description.lower()

    # Keyword patterns for each type
    architectural_keywords = [
        "how does", "architecture", "flow", "components", "system",
        "workflow", "process", "pipeline", "overall"
    ]

    semantic_keywords = [
        "why", "explain", "when to use", "best practice", "reason",
        "purpose", "benefits", "tradeoffs", "should i"
    ]

    symbolic_keywords = [
        "what does", "where is", "type of", "definition", "signature",
        "return", "parameter", "class", "function", "method"
    ]

    # Count matches
    arch_score = sum(1 for kw in architectural_keywords if kw in task_lower)
    sem_score = sum(1 for kw in semantic_keywords if kw in task_lower)
    sym_score = sum(1 for kw in symbolic_keywords if kw in task_lower)

    # Classify
    scores = {"ARCHITECTURAL": arch_score, "SEMANTIC": sem_score, "SYMBOLIC": sym_score}
    max_score = max(scores.values())

    # COMPLEX if multiple types have high scores
    high_scorers = [k for k, v in scores.items() if v >= max_score - 1 and v > 0]
    if len(high_scorers) >= 2:
        return "COMPLEX"

    # Otherwise return highest scorer
    if max_score == 0:
        return "SEMANTIC"  # Default

    return max(scores, key=scores.get)
```

---

### Method: load_clarity_context

```python
async def load_clarity_context(
    self,
    task_description: str,
    max_tokens: int
) -> str:
    """
    Load ClarAIty context (component architecture).

    Queries ClarAIty DB for:
    - Component purposes
    - Dependencies
    - Design decisions

    Args:
        task_description: User's task
        max_tokens: Maximum tokens for this layer

    Returns:
        Formatted ClarAIty context string

    Example:
        >>> ctx = await orchestrator.load_clarity_context(
        ...     "How does auth work?", max_tokens=500
        ... )
        >>> print(ctx)
        [CLARAITY ARCHITECTURE]
        Component: Authentication System
        Purpose: Handle user login/logout...
        Dependencies: UserDB, TokenManager...
    """
    if not self.clarity_db:
        return ""

    try:
        # Query ClarAIty for relevant components
        # (This assumes ClarAIty tools/API exist)
        from src.tools.clarity_tools import search_components

        results = search_components(query=task_description, max_results=3)

        if not results:
            return ""

        # Format results
        context_parts = ["[CLARAITY ARCHITECTURE]\n"]

        from tiktoken import encoding_for_model
        enc = encoding_for_model("gpt-4")

        for component in results:
            component_text = f"""
Component: {component['name']}
Purpose: {component['purpose']}
Dependencies: {', '.join(component.get('dependencies', []))}
Status: {component.get('status', 'unknown')}
---
"""
            # Check token limit
            current_tokens = len(enc.encode(''.join(context_parts)))
            new_tokens = len(enc.encode(component_text))

            if current_tokens + new_tokens > max_tokens:
                break

            context_parts.append(component_text)

        return ''.join(context_parts)

    except Exception as e:
        self.logger.warning(f"ClarAIty context loading failed: {e}")
        return ""
```

---

### Method: load_rag_context

```python
async def load_rag_context(
    self,
    task_description: str,
    max_tokens: int
) -> str:
    """
    Load RAG context (semantic search over docs/code).

    Uses existing HybridRetriever (70% semantic, 30% keyword BM25).

    Args:
        task_description: User's task
        max_tokens: Maximum tokens for this layer

    Returns:
        Formatted RAG context string

    Example:
        >>> ctx = await orchestrator.load_rag_context(
        ...     "How to hash passwords?", max_tokens=800
        ... )
        >>> print(ctx)
        [RAG CONTEXT]
        File: src/auth.py
        Content: def hash_password(password: str) -> str:
            Uses bcrypt with salt rounds=12...
    """
    try:
        # Query RAG retriever
        results = self.rag_retriever.retrieve(
            query=task_description,
            top_k=5  # Start with top 5, trim to fit tokens
        )

        if not results:
            return ""

        # Format results
        context_parts = ["[RAG CONTEXT]\n"]

        from tiktoken import encoding_for_model
        enc = encoding_for_model("gpt-4")

        for result in results:
            chunk_text = f"""
File: {result.get('file_path', 'unknown')}
Score: {result.get('score', 0):.2f}
Content:
{result.get('content', '')}
---
"""
            # Check token limit
            current_tokens = len(enc.encode(''.join(context_parts)))
            new_tokens = len(enc.encode(chunk_text))

            if current_tokens + new_tokens > max_tokens:
                break

            context_parts.append(chunk_text)

        return ''.join(context_parts)

    except Exception as e:
        self.logger.warning(f"RAG context loading failed: {e}")
        return ""
```

---

### Method: load_lsp_context

```python
async def load_lsp_context(
    self,
    file_path: str,
    line: int,
    column: int,
    max_tokens: int
) -> str:
    """
    Load LSP context (symbol definitions, references, types).

    Queries LSP for:
    - Definition (where symbol is defined)
    - References (where symbol is used)
    - Hover info (type signature, docstring)
    - Document symbols (outline)

    Args:
        file_path: Path to file
        line: Line number (0-indexed)
        column: Column number (0-indexed)
        max_tokens: Maximum tokens for this layer

    Returns:
        Formatted LSP context string

    Example:
        >>> ctx = await orchestrator.load_lsp_context(
        ...     "src/auth.py", line=45, column=10, max_tokens=1000
        ... )
        >>> print(ctx)
        [LSP CONTEXT]
        Symbol: authenticate()
        Definition: src/auth.py:45:10
        Type: (username: str, password: str) -> Token
        References (3):
        - src/api.py:78
        - src/cli.py:123
        ...
    """
    try:
        context_parts = ["[LSP CONTEXT]\n"]

        # Query definition
        definition = await self.lsp_manager.request_definition(file_path, line, column)
        if definition:
            context_parts.append(f"Definition: {definition.get('uri', 'unknown')}:{definition.get('range', {}).get('start', {}).get('line', '?')}\n")

        # Query hover (type info)
        hover = await self.lsp_manager.request_hover(file_path, line, column)
        if hover and 'contents' in hover:
            context_parts.append(f"Type Info:\n{hover['contents']}\n")

        # Query references
        references = await self.lsp_manager.request_references(file_path, line, column)
        if references:
            context_parts.append(f"\nReferences ({len(references)}):\n")
            for ref in references[:10]:  # Limit to 10 references
                ref_location = f"{ref.get('uri', 'unknown')}:{ref.get('range', {}).get('start', {}).get('line', '?')}"
                context_parts.append(f"- {ref_location}\n")

        # Query document symbols (if tokens remaining)
        from tiktoken import encoding_for_model
        enc = encoding_for_model("gpt-4")
        current_tokens = len(enc.encode(''.join(context_parts)))

        if current_tokens < max_tokens * 0.7:  # Use at most 70% for symbols
            symbols = await self.lsp_manager.request_document_symbols(file_path)
            if symbols:
                context_parts.append("\nDocument Symbols:\n")
                for symbol in symbols[:20]:  # Limit to 20 symbols
                    symbol_text = f"- {symbol.get('name', 'unknown')} ({symbol.get('kind', 'unknown')})\n"
                    new_tokens = len(enc.encode(symbol_text))
                    if current_tokens + new_tokens > max_tokens:
                        break
                    context_parts.append(symbol_text)
                    current_tokens += new_tokens

        return ''.join(context_parts)

    except Exception as e:
        self.logger.warning(f"LSP context loading failed: {e}")
        return ""
```

---

### Method: merge_contexts

```python
def merge_contexts(
    self,
    clarity_ctx: str,
    rag_ctx: str,
    lsp_ctx: str
) -> str:
    """
    Merge contexts from all layers into final context.

    Order: ClarAIty -> LSP -> RAG
    (Architectural overview first, then precision, then breadth)

    Args:
        clarity_ctx: ClarAIty context
        rag_ctx: RAG context
        lsp_ctx: LSP context

    Returns:
        Merged context string
    """
    parts = []

    if clarity_ctx:
        parts.append(clarity_ctx)

    if lsp_ctx:
        parts.append(lsp_ctx)

    if rag_ctx:
        parts.append(rag_ctx)

    return "\n\n".join(parts)
```

---

## Error Handling

### Pattern: Graceful Degradation

```python
# If LSP fails, fall back to RAG
async def load_smart_context(self, ...):
    try:
        lsp_ctx = await self.load_lsp_context(...)
    except LSPServerNotFoundError:
        self.logger.warning("LSP unavailable, using RAG only")
        # Reallocate LSP tokens to RAG
        rag_tokens += lsp_tokens
        lsp_tokens = 0
        lsp_ctx = ""
```

### Pattern: Timeout Handling

```python
import asyncio

# Timeout individual layers to prevent blocking
async def load_smart_context(self, ...):
    try:
        lsp_ctx = await asyncio.wait_for(
            self.load_lsp_context(...),
            timeout=5.0  # 5 second timeout
        )
    except asyncio.TimeoutError:
        self.logger.warning("LSP query timeout, skipping")
        lsp_ctx = ""
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **Query classification** works correctly (4 types identified)
- [ ] **Token allocation** respects max_tokens limit
- [ ] **Multi-tier loading** combines all 3 layers
- [ ] **Graceful degradation** works when LSP unavailable
- [ ] **Parallel loading** reduces latency (asyncio.gather)

### Performance Targets

- [ ] **Total loading time**: <3 seconds (all layers combined)
- [ ] **Token efficiency**: 50%+ improvement vs full-chunk RAG
- [ ] **Classification accuracy**: >85% on test queries

### Quality Metrics

- [ ] **Test coverage**: 90%+
- [ ] **All query types tested**: ARCHITECTURAL, SEMANTIC, SYMBOLIC, COMPLEX
- [ ] **Error handling tested**: LSP failure, timeout, empty results

---

## Testing Strategy

### Unit Tests (tests/test_orchestrator.py)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_load_smart_context_symbolic():
    """Test SYMBOLIC query loads LSP-heavy context."""
    # Mock dependencies
    lsp_manager = MagicMock()
    lsp_manager.request_definition = AsyncMock(return_value={"uri": "src/auth.py"})
    lsp_manager.request_hover = AsyncMock(return_value={"contents": "def auth() -> Token"})
    lsp_manager.request_references = AsyncMock(return_value=[])

    rag_retriever = MagicMock()
    rag_retriever.retrieve = MagicMock(return_value=[])

    orchestrator = CodeIntelligenceOrchestrator(lsp_manager, rag_retriever)

    # Load context
    context = await orchestrator.load_smart_context(
        task_description="What does authenticate() return?",
        file_path="src/auth.py",
        line=45,
        column=10,
        max_tokens=2000
    )

    # Assertions
    assert context.query_type == "SYMBOLIC"
    assert context.sources["lsp"] > context.sources["rag"]  # LSP dominates
    assert "[LSP CONTEXT]" in context.full_context

def test_classify_query_architectural():
    """Test query classification for ARCHITECTURAL type."""
    orchestrator = CodeIntelligenceOrchestrator(MagicMock(), MagicMock())

    assert orchestrator.classify_query("How does authentication flow work?") == "ARCHITECTURAL"
    assert orchestrator.classify_query("What is the architecture?") == "ARCHITECTURAL"

def test_classify_query_symbolic():
    """Test query classification for SYMBOLIC type."""
    orchestrator = CodeIntelligenceOrchestrator(MagicMock(), MagicMock())

    assert orchestrator.classify_query("What does authenticate() return?") == "SYMBOLIC"
    assert orchestrator.classify_query("Where is User class defined?") == "SYMBOLIC"

@pytest.mark.asyncio
async def test_graceful_degradation_lsp_failure():
    """Test fallback to RAG when LSP fails."""
    lsp_manager = MagicMock()
    lsp_manager.request_definition = AsyncMock(side_effect=LSPServerNotFoundError())

    rag_retriever = MagicMock()
    rag_retriever.retrieve = MagicMock(return_value=[{"content": "auth code"}])

    orchestrator = CodeIntelligenceOrchestrator(lsp_manager, rag_retriever)

    context = await orchestrator.load_smart_context(
        task_description="What does auth() do?",
        file_path="src/auth.py",
        line=45,
        column=10,
        max_tokens=2000
    )

    # Should still return context (from RAG)
    assert context.sources["lsp"] == 0
    assert context.sources["rag"] > 0
```

---

## Implementation Patterns

### Pattern: Adaptive Token Allocation

```python
# Allocate more tokens to LSP for SYMBOLIC queries
allocation_weights = {
    "SYMBOLIC": {"clarity": 0.05, "rag": 0.15, "lsp": 0.80},
    # 80% of budget goes to LSP for precision
}
```

### Pattern: Parallel Loading with asyncio.gather

```python
# Load all layers concurrently (reduces latency)
clarity_ctx, rag_ctx, lsp_ctx = await asyncio.gather(
    self.load_clarity_context(...),
    self.load_rag_context(...),
    self.load_lsp_context(...)
)
```

### Antipattern: Sequential Loading

```python
# BAD: Loads layers sequentially (3x slower)
clarity_ctx = await self.load_clarity_context(...)
rag_ctx = await self.load_rag_context(...)  # Waits for clarity to finish
lsp_ctx = await self.load_lsp_context(...)  # Waits for rag to finish

# GOOD: Load in parallel
clarity_ctx, rag_ctx, lsp_ctx = await asyncio.gather(...)
```

---

## Integration Example

```python
# In ContextBuilder.build_context()
async def build_context(self, task_description: str, file_path: str = None, line: int = None):
    # Existing memory/RAG/system prompt loading...

    # NEW: Use orchestrator for smart context loading
    if self.orchestrator:
        smart_context = await self.orchestrator.load_smart_context(
            task_description=task_description,
            file_path=file_path,
            line=line,
            max_tokens=int(self.max_context_tokens * 0.50)  # 50% of budget
        )

        self.logger.info(
            f"Loaded {smart_context.token_count} tokens from "
            f"{smart_context.query_type} query"
        )
        self.logger.debug(f"Sources: {smart_context.sources}")

        # Add to context
        context_parts.append(smart_context.full_context)
```

---

## File Location

**Path**: `src/code_intelligence/orchestrator.py`

---

**Status**: ✅ Ready for implementation
**Next**: Read [04_CONFIG.md](04_CONFIG.md)
