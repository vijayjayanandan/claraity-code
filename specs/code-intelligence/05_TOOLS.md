# Code Intelligence Tools

**Status**: Ready for implementation
**Estimated Time**: 1 hour
**Lines of Code**: ~400 LOC
**Dependencies**: LSPClientManager, CodeIntelligenceOrchestrator, tool_schemas.py

---

## Overview

The **Code Intelligence Tools** provide 7 tools for the LLM agent:

### Fine-Grained Tools (4)
- **GetSymbolDefinitionTool** - Get definition location of a symbol
- **GetSymbolReferencesTool** - Get all references to a symbol
- **GetSymbolHoverTool** - Get type info and documentation
- **GetDocumentSymbolsTool** - Get outline/symbols in a file

### Coarse-Grained Tools (3)
- **AnalyzeSymbolTool** - Comprehensive symbol analysis (definition + references + type)
- **SearchCodeWithLSPTool** - Find symbols by name across project
- **LoadSmartContextTool** - Load multi-tier context (ClarAIty + RAG + LSP)

### Why 7 Tools?

**Hybrid granularity** gives LLM flexibility:
- **Fine-grained** for precision ("Get definition only")
- **Coarse-grained** for convenience ("Analyze this symbol completely")

**Expected Impact:**
- **2x faster symbol lookup** vs grep/RAG
- **100% accurate symbol resolution** (LSP knows the AST)
- **Better context quality** (type-aware, not text-based)

---

## Architecture

```
Code Intelligence Tools (7)
    │
    ├─> Fine-Grained (4)
    │   ├─> GetSymbolDefinitionTool
    │   ├─> GetSymbolReferencesTool
    │   ├─> GetSymbolHoverTool
    │   └─> GetDocumentSymbolsTool
    │
    └─> Coarse-Grained (3)
        ├─> AnalyzeSymbolTool (combines definition + references + hover)
        ├─> SearchCodeWithLSPTool (workspace symbols)
        └─> LoadSmartContextTool (multi-tier context)

All tools:
    - Registered in tool_schemas.py (OpenAI function calling)
    - Inherit from BaseTool
    - Return ToolResult (success, output, error)
```

---

## Fine-Grained Tools

### Tool 1: GetSymbolDefinitionTool

```python
from src.tools.base import BaseTool, ToolResult
from typing import Optional

class GetSymbolDefinitionTool(BaseTool):
    """
    Get definition location of a symbol.

    Use case: "Where is authenticate() defined?"

    Returns: File path, line number, column number
    """

    name = "get_symbol_definition"
    description = "Get the definition location of a symbol (function, class, variable)"

    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to file containing the symbol"
            },
            "line": {
                "type": "integer",
                "description": "Line number (0-indexed) where symbol appears"
            },
            "column": {
                "type": "integer",
                "description": "Column number (0-indexed) where symbol appears"
            }
        },
        "required": ["file_path", "line", "column"]
    }

    def __init__(self, lsp_manager: LSPClientManager):
        self.lsp_manager = lsp_manager

    async def execute(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> ToolResult:
        """
        Execute get_symbol_definition.

        Args:
            file_path: Path to file
            line: Line number (0-indexed)
            column: Column number (0-indexed)

        Returns:
            ToolResult with definition location

        Example:
            >>> result = await tool.execute("src/auth.py", 45, 10)
            >>> print(result.output)
            Definition: src/auth/user.py:23:4
            Symbol: authenticate(username: str, password: str) -> Token
        """
        try:
            # Query LSP
            definition = await self.lsp_manager.request_definition(
                file_path, line, column
            )

            if not definition:
                return ToolResult(
                    success=False,
                    output="",
                    error="Definition not found (symbol may be builtin or external)"
                )

            # Format output
            uri = definition.get("uri", "unknown")
            def_range = definition.get("range", {})
            def_line = def_range.get("start", {}).get("line", "?")
            def_col = def_range.get("start", {}).get("character", "?")

            output = f"Definition: {uri}:{def_line}:{def_col}\n"

            # Get hover info for type signature (if available)
            hover = await self.lsp_manager.request_hover(file_path, line, column)
            if hover and "contents" in hover:
                output += f"Symbol: {hover['contents']}\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"LSP query failed: {str(e)}"
            )
```

**OpenAI Function Schema**:
```python
# In tool_schemas.py
GET_SYMBOL_DEFINITION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_symbol_definition",
        "description": "Get the definition location of a symbol (function, class, variable). Use this when you need to find where a symbol is defined.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file containing the symbol"
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-indexed) where symbol appears"
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (0-indexed) where symbol starts"
                }
            },
            "required": ["file_path", "line", "column"]
        }
    }
}
```

---

### Tool 2: GetSymbolReferencesTool

```python
class GetSymbolReferencesTool(BaseTool):
    """
    Get all references to a symbol.

    Use case: "Where is authenticate() called?"

    Returns: List of file paths and line numbers
    """

    name = "get_symbol_references"
    description = "Get all references (usages) of a symbol across the codebase"

    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "column": {"type": "integer"}
        },
        "required": ["file_path", "line", "column"]
    }

    def __init__(self, lsp_manager: LSPClientManager):
        self.lsp_manager = lsp_manager

    async def execute(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> ToolResult:
        """
        Execute get_symbol_references.

        Example output:
            References (5):
            1. src/api.py:78:12
            2. src/cli.py:123:8
            3. src/web.py:45:20
            ...
        """
        try:
            references = await self.lsp_manager.request_references(
                file_path, line, column
            )

            if not references:
                return ToolResult(
                    success=True,
                    output="No references found (symbol may be unused)"
                )

            # Format output
            output = f"References ({len(references)}):\n"
            for i, ref in enumerate(references[:50], 1):  # Limit to 50
                uri = ref.get("uri", "unknown")
                ref_range = ref.get("range", {})
                ref_line = ref_range.get("start", {}).get("line", "?")
                ref_col = ref_range.get("start", {}).get("character", "?")
                output += f"{i}. {uri}:{ref_line}:{ref_col}\n"

            if len(references) > 50:
                output += f"... and {len(references) - 50} more\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"LSP query failed: {str(e)}"
            )
```

---

### Tool 3: GetSymbolHoverTool

```python
class GetSymbolHoverTool(BaseTool):
    """
    Get type information and documentation for a symbol.

    Use case: "What type does authenticate() return?"

    Returns: Type signature, docstring, parameter types
    """

    name = "get_symbol_hover"
    description = "Get type information and documentation for a symbol"

    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "column": {"type": "integer"}
        },
        "required": ["file_path", "line", "column"]
    }

    def __init__(self, lsp_manager: LSPClientManager):
        self.lsp_manager = lsp_manager

    async def execute(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> ToolResult:
        """
        Execute get_symbol_hover.

        Example output:
            Type: (username: str, password: str) -> Token
            Documentation:
            Authenticate user with credentials.
            Returns JWT token on success, raises AuthError on failure.
        """
        try:
            hover = await self.lsp_manager.request_hover(file_path, line, column)

            if not hover or "contents" not in hover:
                return ToolResult(
                    success=False,
                    output="",
                    error="No hover information available"
                )

            # Format output
            contents = hover["contents"]
            output = f"Type: {contents}\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"LSP query failed: {str(e)}"
            )
```

---

### Tool 4: GetDocumentSymbolsTool

```python
class GetDocumentSymbolsTool(BaseTool):
    """
    Get outline/symbols in a file.

    Use case: "What classes and functions are in auth.py?"

    Returns: List of symbols with types (class, function, variable)
    """

    name = "get_document_symbols"
    description = "Get outline/symbols (classes, functions, variables) in a file"

    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to file"
            }
        },
        "required": ["file_path"]
    }

    def __init__(self, lsp_manager: LSPClientManager):
        self.lsp_manager = lsp_manager

    async def execute(self, file_path: str) -> ToolResult:
        """
        Execute get_document_symbols.

        Example output:
            Document Symbols (12):
            1. User (class) - line 10
            2. authenticate (function) - line 45
            3. hash_password (function) - line 78
            ...
        """
        try:
            symbols = await self.lsp_manager.request_document_symbols(file_path)

            if not symbols:
                return ToolResult(
                    success=True,
                    output="No symbols found (empty file or parsing error)"
                )

            # Format output
            output = f"Document Symbols ({len(symbols)}):\n"
            for i, symbol in enumerate(symbols[:100], 1):  # Limit to 100
                name = symbol.get("name", "unknown")
                kind = symbol.get("kind", "unknown")
                symbol_range = symbol.get("range", {})
                symbol_line = symbol_range.get("start", {}).get("line", "?")

                output += f"{i}. {name} ({kind}) - line {symbol_line}\n"

            if len(symbols) > 100:
                output += f"... and {len(symbols) - 100} more\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"LSP query failed: {str(e)}"
            )
```

---

## Coarse-Grained Tools

### Tool 5: AnalyzeSymbolTool

```python
class AnalyzeSymbolTool(BaseTool):
    """
    Comprehensive symbol analysis (definition + references + type).

    Use case: "Tell me everything about authenticate()"

    Combines: get_symbol_definition + get_symbol_references + get_symbol_hover
    """

    name = "analyze_symbol"
    description = "Get comprehensive analysis of a symbol (definition, references, type info)"

    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "column": {"type": "integer"}
        },
        "required": ["file_path", "line", "column"]
    }

    def __init__(self, lsp_manager: LSPClientManager):
        self.lsp_manager = lsp_manager

    async def execute(
        self,
        file_path: str,
        line: int,
        column: int
    ) -> ToolResult:
        """
        Execute comprehensive symbol analysis.

        Example output:
            [SYMBOL ANALYSIS]

            Definition: src/auth/user.py:45:4
            Type: (username: str, password: str) -> Token

            References (5):
            1. src/api.py:78:12
            2. src/cli.py:123:8
            ...

            Documentation:
            Authenticate user with credentials...
        """
        try:
            import asyncio

            # Query all info in parallel
            definition_task = self.lsp_manager.request_definition(file_path, line, column)
            references_task = self.lsp_manager.request_references(file_path, line, column)
            hover_task = self.lsp_manager.request_hover(file_path, line, column)

            definition, references, hover = await asyncio.gather(
                definition_task, references_task, hover_task
            )

            # Format output
            output_parts = ["[SYMBOL ANALYSIS]\n"]

            # Definition
            if definition:
                uri = definition.get("uri", "unknown")
                def_line = definition.get("range", {}).get("start", {}).get("line", "?")
                output_parts.append(f"\nDefinition: {uri}:{def_line}")

            # Type info
            if hover and "contents" in hover:
                output_parts.append(f"Type: {hover['contents']}")

            # References
            if references:
                output_parts.append(f"\nReferences ({len(references)}):")
                for i, ref in enumerate(references[:10], 1):
                    uri = ref.get("uri", "unknown")
                    ref_line = ref.get("range", {}).get("start", {}).get("line", "?")
                    output_parts.append(f"{i}. {uri}:{ref_line}")

                if len(references) > 10:
                    output_parts.append(f"... and {len(references) - 10} more")

            return ToolResult(success=True, output="\n".join(output_parts))

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Symbol analysis failed: {str(e)}"
            )
```

---

### Tool 6: SearchCodeWithLSPTool

```python
class SearchCodeWithLSPTool(BaseTool):
    """
    Find symbols by name across project (workspace symbols).

    Use case: "Find all classes named 'User'"

    Uses LSP workspace/symbol to search entire codebase
    """

    name = "search_code_with_lsp"
    description = "Find symbols by name across the entire project (classes, functions, variables)"

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Symbol name to search for (e.g., 'User', 'authenticate')"
            }
        },
        "required": ["query"]
    }

    def __init__(self, lsp_manager: LSPClientManager):
        self.lsp_manager = lsp_manager

    async def execute(self, query: str) -> ToolResult:
        """
        Execute workspace symbol search.

        Example output:
            Search Results for "User" (8):
            1. User (class) - src/models/user.py:10
            2. UserSchema (class) - src/schemas.py:45
            3. get_user (function) - src/api.py:78
            ...
        """
        try:
            # Get active LSP server (assumes repo root detection)
            # This is simplified - real implementation needs repo context
            symbols = await self.lsp_manager.request_workspace_symbols(query)

            if not symbols:
                return ToolResult(
                    success=True,
                    output=f"No symbols found for query: {query}"
                )

            # Format output
            output = f"Search Results for \"{query}\" ({len(symbols)}):\n"
            for i, symbol in enumerate(symbols[:20], 1):
                name = symbol.get("name", "unknown")
                kind = symbol.get("kind", "unknown")
                location = symbol.get("location", {})
                uri = location.get("uri", "unknown")
                symbol_line = location.get("range", {}).get("start", {}).get("line", "?")

                output += f"{i}. {name} ({kind}) - {uri}:{symbol_line}\n"

            if len(symbols) > 20:
                output += f"... and {len(symbols) - 20} more\n"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Workspace symbol search failed: {str(e)}"
            )
```

---

### Tool 7: LoadSmartContextTool

```python
class LoadSmartContextTool(BaseTool):
    """
    Load multi-tier context (ClarAIty + RAG + LSP).

    Use case: "Load context for 'How does authentication work?'"

    Uses CodeIntelligenceOrchestrator for smart context loading
    """

    name = "load_smart_context"
    description = "Load intelligent multi-tier context combining architecture, semantic search, and symbol information"

    parameters = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "User's task or query"
            },
            "file_path": {
                "type": "string",
                "description": "Optional file path for LSP context"
            },
            "line": {
                "type": "integer",
                "description": "Optional line number for LSP context"
            },
            "column": {
                "type": "integer",
                "description": "Optional column number for LSP context"
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum tokens for context (default: 2000)"
            }
        },
        "required": ["task_description"]
    }

    def __init__(self, orchestrator: CodeIntelligenceOrchestrator):
        self.orchestrator = orchestrator

    async def execute(
        self,
        task_description: str,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
        max_tokens: int = 2000
    ) -> ToolResult:
        """
        Execute smart context loading.

        Example output:
            [SMART CONTEXT]
            Query Type: SYMBOLIC
            Tokens: 1847 / 2000

            [CLARAITY ARCHITECTURE]
            Component: Authentication System...

            [LSP CONTEXT]
            Definition: src/auth.py:45...

            [RAG CONTEXT]
            File: src/auth.py...
        """
        try:
            context = await self.orchestrator.load_smart_context(
                task_description=task_description,
                file_path=file_path,
                line=line,
                column=column,
                max_tokens=max_tokens
            )

            # Format output with metadata
            output = f"[SMART CONTEXT]\n"
            output += f"Query Type: {context.query_type}\n"
            output += f"Tokens: {context.token_count} / {max_tokens}\n"
            output += f"Sources: ClarAIty={context.sources['claraity']}, "
            output += f"RAG={context.sources['rag']}, LSP={context.sources['lsp']}\n\n"
            output += context.full_context

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Smart context loading failed: {str(e)}"
            )
```

---

## Tool Registration

### In tool_schemas.py

```python
# Add 7 new schemas
CODE_INTELLIGENCE_SCHEMAS = [
    GET_SYMBOL_DEFINITION_SCHEMA,
    GET_SYMBOL_REFERENCES_SCHEMA,
    GET_SYMBOL_HOVER_SCHEMA,
    GET_DOCUMENT_SYMBOLS_SCHEMA,
    ANALYZE_SYMBOL_SCHEMA,
    SEARCH_CODE_WITH_LSP_SCHEMA,
    LOAD_SMART_CONTEXT_SCHEMA,
]

# Update ALL_TOOLS
ALL_TOOLS = [
    *FILE_OPERATION_SCHEMAS,
    *CLARAITY_SCHEMAS,
    *CODE_INTELLIGENCE_SCHEMAS,  # NEW
    # ... other tools
]
```

### In agent.py

```python
def _register_code_intelligence_tools(self):
    """Register Code Intelligence tools."""
    # Fine-grained
    self.tool_executor.register_tool(GetSymbolDefinitionTool(self.lsp_manager))
    self.tool_executor.register_tool(GetSymbolReferencesTool(self.lsp_manager))
    self.tool_executor.register_tool(GetSymbolHoverTool(self.lsp_manager))
    self.tool_executor.register_tool(GetDocumentSymbolsTool(self.lsp_manager))

    # Coarse-grained
    self.tool_executor.register_tool(AnalyzeSymbolTool(self.lsp_manager))
    self.tool_executor.register_tool(SearchCodeWithLSPTool(self.lsp_manager))
    self.tool_executor.register_tool(LoadSmartContextTool(self.orchestrator))
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **All 7 tools** work correctly
- [ ] **Fine-grained tools** return precise LSP data
- [ ] **Coarse-grained tools** combine multiple LSP queries
- [ ] **Error handling** graceful (LSP failures don't crash agent)
- [ ] **OpenAI schemas** registered correctly

### Performance Targets

- [ ] **Tool execution**: <2 seconds (per tool call)
- [ ] **Parallel queries**: AnalyzeSymbolTool uses asyncio.gather

### Quality Metrics

- [ ] **Test coverage**: 90%+
- [ ] **All tools tested** with mock LSP responses
- [ ] **Integration tests** with real LSP servers

---

## Testing Strategy

### Unit Tests (tests/test_code_intelligence_tools.py)

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_get_symbol_definition():
    """Test GetSymbolDefinitionTool."""
    lsp_manager = MagicMock()
    lsp_manager.request_definition = AsyncMock(return_value={
        "uri": "src/auth.py",
        "range": {"start": {"line": 45, "character": 4}}
    })

    tool = GetSymbolDefinitionTool(lsp_manager)
    result = await tool.execute("src/api.py", 10, 5)

    assert result.success
    assert "src/auth.py:45:4" in result.output

@pytest.mark.asyncio
async def test_analyze_symbol_comprehensive():
    """Test AnalyzeSymbolTool combines all info."""
    lsp_manager = MagicMock()
    lsp_manager.request_definition = AsyncMock(return_value={"uri": "src/auth.py"})
    lsp_manager.request_references = AsyncMock(return_value=[{}, {}])  # 2 refs
    lsp_manager.request_hover = AsyncMock(return_value={"contents": "def auth() -> Token"})

    tool = AnalyzeSymbolTool(lsp_manager)
    result = await tool.execute("src/api.py", 10, 5)

    assert result.success
    assert "Definition:" in result.output
    assert "References (2)" in result.output
    assert "Type:" in result.output
```

---

## File Location

**Path**: `src/code_intelligence/tools.py`

---

**Status**: ✅ Ready for implementation
**Next**: Read [06_CONTEXT_BUILDER.md](06_CONTEXT_BUILDER.md)
