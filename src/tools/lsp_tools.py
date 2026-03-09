"""
Production-grade LSP tools for semantic code intelligence.

Provides:
- GetFileOutlineTool: Get file structure (classes, functions, methods) using LSP
- GetSymbolContextTool: Get complete symbol details (definition, signature, references) using LSP

These tools provide semantic precision that grep/glob cannot achieve.
Design principle: LLM provides symbol NAME, tool finds LOCATION internally.

ARCHITECTURE:
    Uses lsp_runtime.py for persistent event loop - LSP servers are reused
    across calls, avoiding ~2.5s cold start penalty. DO NOT use asyncio.run()
    in execute() methods - use lsp_run() instead.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

from src.code_intelligence.config import CodeIntelligenceConfig
from src.code_intelligence.lsp_client_manager import LSPClientManager
from src.code_intelligence.lsp_runtime import get_manager_async, lsp_run

from .base import Tool, ToolResult, ToolStatus
from .search_tools import validate_path_security


class GetFileOutlineTool(Tool):
    """
    Get file structure using LSP document symbols.

    Returns all classes, functions, and methods with line numbers.
    This is semantically accurate (uses language server, not regex).

    Features:
    - Returns hierarchical structure (classes with their methods)
    - Includes line numbers for each symbol
    - Distinguishes async/sync, method/function, etc.
    - Language-aware (works for Python, TypeScript, Go, etc.)

    Use Case:
    - "What's in this file?" without reading entire file
    - "What methods does this class have?"
    - "Show me file structure"

    Example:
        >>> tool = GetFileOutlineTool()
        >>> result = tool.execute("src/core/agent.py")
        >>> # Returns: {classes: [...], functions: [...], imports: [...]}
    """

    def __init__(self):
        super().__init__(
            name="get_file_outline",
            description="Get file structure (classes, functions, methods) using LSP semantic analysis",
        )
        # Manager is obtained from lsp_runtime (singleton, reused across calls)
        self.lsp_manager: LSPClientManager | None = None
        self.config: CodeIntelligenceConfig | None = None

    async def _ensure_lsp_initialized(self):
        """Initialize LSP manager from persistent runtime."""
        if self.lsp_manager is None:
            # NOTE: config is pre-detected in execute() to avoid blocking async loop
            # Get manager from persistent LSP runtime
            # IMPORTANT: Use async getter since we're running ON the LSP loop
            # DO NOT use get_manager_sync() here - it will DEADLOCK!
            self.lsp_manager = await get_manager_async()

    def execute(self, file_path: str, **kwargs: Any) -> ToolResult:
        """
        Get file outline using LSP.

        Args:
            file_path: Path to file to analyze

        Returns:
            ToolResult with structured file outline
        """
        # Pre-detect config in sync context (contains blocking rglob)
        # This MUST happen before lsp_run() to avoid blocking the async loop
        if self.config is None:
            self.config = CodeIntelligenceConfig.auto_detect()

        # Use persistent LSP runtime instead of asyncio.run()
        # DO NOT call asyncio.run() - it creates new loop each time!
        # DO NOT reset self.lsp_manager - runtime manages lifecycle
        # Timeout: 60s allows for cold start (server startup + first query on large files)
        return lsp_run(self._execute_async(file_path), timeout=60.0)

    async def _execute_async(self, file_path: str) -> ToolResult:
        """Async implementation of execute."""
        try:
            # Validate file exists
            path = Path(file_path)
            if not path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}",
                )

            # Initialize LSP if needed
            await self._ensure_lsp_initialized()

            # Get document symbols from LSP
            symbols = await self.lsp_manager.request_document_symbols(str(path.resolve()))

            if not symbols:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="No symbols found in file (empty or not indexed)",
                    metadata={"file": file_path, "symbols": []},
                )

            # Parse symbols into structured format
            outline = self._parse_symbols(symbols, file_path)

            # Format output
            output = self._format_outline(outline)

            return ToolResult(
                tool_name=self.name, status=ToolStatus.SUCCESS, output=output, metadata=outline
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to get file outline: {str(e)}",
            )

    def _parse_symbols(self, symbols: list[dict[str, Any]], file_path: str) -> dict[str, Any]:
        """
        Parse LSP symbols into structured outline.

        LSP returns flat or nested symbol lists. We normalize to:
        {
            "file": "path/to/file.py",
            "classes": [
                {
                    "name": "User",
                    "line": 10,
                    "kind": "class",
                    "methods": [
                        {"name": "save", "line": 15, "kind": "async method"}
                    ]
                }
            ],
            "functions": [
                {"name": "authenticate", "line": 45, "kind": "async function"}
            ],
            "imports": [...]
        }
        """
        outline = {"file": file_path, "classes": [], "functions": [], "imports": [], "other": []}

        for symbol in symbols:
            symbol_type = self._get_symbol_type(symbol)
            parsed = self._parse_single_symbol(symbol)

            if symbol_type == "class":
                outline["classes"].append(parsed)
            elif symbol_type == "function":
                outline["functions"].append(parsed)
            elif symbol_type == "import":
                outline["imports"].append(parsed)
            else:
                outline["other"].append(parsed)

        return outline

    def _get_symbol_type(self, symbol: dict[str, Any]) -> str:
        """Determine symbol type from LSP kind."""
        # LSP SymbolKind mapping
        kind = symbol.get("kind", 0)

        # Common LSP kinds:
        # 1: File, 2: Module, 3: Namespace, 4: Package, 5: Class
        # 6: Method, 7: Property, 8: Field, 9: Constructor, 10: Enum
        # 11: Interface, 12: Function, 13: Variable, 14: Constant

        if kind == 5:  # Class
            return "class"
        elif kind in (6, 9):  # Method, Constructor
            return "method"
        elif kind == 12:  # Function
            return "function"
        elif kind in (2, 3):  # Module, Namespace (imports)
            return "import"
        else:
            return "other"

    def _parse_single_symbol(self, symbol: dict[str, Any]) -> dict[str, Any]:
        """Parse a single LSP symbol."""
        name = symbol.get("name", "unknown")
        kind = symbol.get("kind", 0)

        # Get location (line number)
        location = symbol.get("location", {})
        range_info = location.get("range", {})
        start = range_info.get("start", {})
        line = start.get("line", 0) + 1  # LSP uses 0-indexed lines

        # Check if symbol has children (e.g., class with methods)
        children = symbol.get("children", [])

        parsed = {"name": name, "line": line, "kind": self._kind_to_string(kind)}

        # If symbol has children, parse them recursively
        if children:
            parsed["children"] = [self._parse_single_symbol(child) for child in children]

        return parsed

    def _kind_to_string(self, kind: int) -> str:
        """Convert LSP SymbolKind number to string."""
        kind_map = {
            1: "file",
            2: "module",
            3: "namespace",
            4: "package",
            5: "class",
            6: "method",
            7: "property",
            8: "field",
            9: "constructor",
            10: "enum",
            11: "interface",
            12: "function",
            13: "variable",
            14: "constant",
            15: "string",
            16: "number",
            17: "boolean",
            18: "array",
        }
        return kind_map.get(kind, f"kind_{kind}")

    def _format_outline(self, outline: dict[str, Any]) -> str:
        """Format outline as human-readable string."""
        lines = [f"File Outline: {outline['file']}", ""]

        # Classes
        if outline["classes"]:
            lines.append("Classes:")
            for cls in outline["classes"]:
                lines.append(f"  - {cls['name']} (line {cls['line']})")
                if "children" in cls:
                    for method in cls["children"]:
                        lines.append(
                            f"    - {method['name']} (line {method['line']}, {method['kind']})"
                        )
            lines.append("")

        # Functions
        if outline["functions"]:
            lines.append("Functions:")
            for func in outline["functions"]:
                lines.append(f"  - {func['name']} (line {func['line']}, {func['kind']})")
            lines.append("")

        # Imports
        if outline["imports"]:
            lines.append(f"Imports: {len(outline['imports'])} import(s)")
            lines.append("")

        return "\n".join(lines)

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to analyze (relative or absolute)",
                }
            },
            "required": ["file_path"],
        }

    def cleanup(self):
        """Cleanup handled by lsp_runtime.shutdown() at process exit."""
        # Do not close shared servers - runtime owns lifecycle
        pass


class GetSymbolContextTool(Tool):
    """
    Get complete symbol details using LSP workspace search.

    Key Feature: LLM provides symbol NAME, tool finds LOCATION internally.

    Workflow:
    1. Search workspace for symbol using LSP
    2. Get definition location
    3. Get signature/docstring (hover)
    4. Get references/callers
    5. Read implementation code
    6. Return everything in one call

    Features:
    - No line numbers needed (workspace search by name)
    - Handles multiple matches (returns all)
    - Handles ambiguity (file_hint parameter)
    - Returns complete context (signature, code, callers, deps)
    - Size-aware (truncates >200 line functions)

    Use Case:
    - "What is authenticate()?" → Get complete details
    - "Show me User class" → Get class definition + methods
    - "Find all callers of parse_config" → Get references

    Example:
        >>> tool = GetSymbolContextTool()
        >>> result = tool.execute("authenticate")
        >>> # Returns: {signature, implementation, callers, references}
    """

    def __init__(self):
        super().__init__(
            name="get_symbol_context",
            description="Get complete symbol details (definition, signature, callers) by name using LSP",
        )
        # Manager is obtained from lsp_runtime (singleton, reused across calls)
        self.lsp_manager: LSPClientManager | None = None
        self.config: CodeIntelligenceConfig | None = None

    async def _ensure_lsp_initialized(self):
        """Initialize LSP manager from persistent runtime."""
        if self.lsp_manager is None:
            # NOTE: config is pre-detected in execute() to avoid blocking async loop
            # Get manager from persistent LSP runtime
            # IMPORTANT: Use async getter since we're running ON the LSP loop
            # DO NOT use get_manager_sync() here - it will DEADLOCK!
            self.lsp_manager = await get_manager_async()

    def execute(
        self,
        symbol_name: str,
        file_hint: str | None = None,
        include_references: bool = True,
        include_implementation: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Get symbol context by name.

        Args:
            symbol_name: Name of symbol (e.g., "authenticate", "User", "parse_config")
            file_hint: Optional file path to narrow search (e.g., "auth.py")
            include_references: Include where symbol is used (default: True)
            include_implementation: Include actual code (default: True)

        Returns:
            ToolResult with complete symbol context
        """
        # Pre-detect config in sync context (contains blocking rglob)
        # This MUST happen before lsp_run() to avoid blocking the async loop
        if self.config is None:
            self.config = CodeIntelligenceConfig.auto_detect()

        # Use persistent LSP runtime instead of asyncio.run()
        # DO NOT call asyncio.run() - it creates new loop each time!
        # DO NOT reset self.lsp_manager - runtime manages lifecycle
        # Timeout: 90s allows for cold start + workspace search + multiple LSP calls
        return lsp_run(
            self._execute_async(symbol_name, file_hint, include_references, include_implementation),
            timeout=90.0,
        )

    async def _execute_async(
        self,
        symbol_name: str,
        file_hint: str | None,
        include_references: bool,
        include_implementation: bool,
    ) -> ToolResult:
        """Async implementation of execute."""
        try:
            # Initialize LSP if needed
            await self._ensure_lsp_initialized()

            # Step 1: Search workspace for symbol
            workspace_symbols = await self.lsp_manager.request_workspace_symbols(symbol_name)

            if not workspace_symbols:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=f"No symbol found matching '{symbol_name}'",
                    metadata={"symbol": symbol_name, "matches": 0, "suggestions": []},
                )

            # Step 2: Filter by file hint if provided
            if file_hint:
                workspace_symbols = self._filter_by_file(workspace_symbols, file_hint)

            # Step 3: Load context for each match
            matches = []
            for symbol_info in workspace_symbols:
                context = await self._load_symbol_context(
                    symbol_info, include_references, include_implementation
                )
                matches.append(context)

            # Format output
            output = self._format_symbol_context(symbol_name, matches)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata={"symbol": symbol_name, "matches": matches, "match_count": len(matches)},
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to get symbol context: {str(e)}",
            )

    def _filter_by_file(
        self, symbols: list[dict[str, Any]], file_hint: str
    ) -> list[dict[str, Any]]:
        """Filter symbols by file path hint."""
        normalized_hint = Path(file_hint).as_posix().lower()

        filtered = []
        for symbol in symbols:
            location = symbol.get("location", {})
            uri = location.get("uri", "")
            file_path = uri.replace("file://", "").lower()

            if normalized_hint in file_path:
                filtered.append(symbol)

        return filtered if filtered else symbols  # Return all if no matches

    async def _load_symbol_context(
        self, symbol_info: dict[str, Any], include_references: bool, include_implementation: bool
    ) -> dict[str, Any]:
        """Load complete context for a symbol."""
        # Extract location from workspace symbol
        location = symbol_info.get("location", {})
        uri = location.get("uri", "")
        file_path = uri.replace("file://", "")

        range_info = location.get("range", {})
        start = range_info.get("start", {})
        line = start.get("line", 0)
        column = start.get("character", 0)

        # Query LSP for detailed information (in parallel)
        tasks = [
            self.lsp_manager.request_definition(file_path, line, column),
            self.lsp_manager.request_hover(file_path, line, column),
        ]

        if include_references:
            tasks.append(self.lsp_manager.request_references(file_path, line, column))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        definition = results[0] if not isinstance(results[0], Exception) else {}
        hover = results[1] if not isinstance(results[1], Exception) else {}
        references = (
            results[2] if len(results) > 2 and not isinstance(results[2], Exception) else []
        )

        # Extract information
        symbol_name = symbol_info.get("name", "unknown")
        kind = symbol_info.get("kind", 0)

        # Build context
        context = {
            "name": symbol_name,
            "location": {
                "file": file_path,
                "line": line + 1,  # Convert to 1-indexed
                "column": column,
            },
            "kind": self._kind_to_string(kind),
            "signature": self._extract_signature(hover, definition),
            "docstring": self._extract_docstring(hover),
            "references_count": len(references),
            "references": self._format_references(references)[:10],  # Top 10
        }

        # Read implementation if requested
        if include_implementation:
            implementation = await self._read_implementation(file_path, line)
            context["implementation"] = implementation["code"]
            context["implementation_length"] = implementation["length"]

        return context

    def _extract_signature(self, hover: dict[str, Any], definition: dict[str, Any]) -> str:
        """Extract function/class signature from hover info."""
        # Try to get from hover first (usually has type info)
        if hover and "contents" in hover:
            contents = hover["contents"]
            if isinstance(contents, str):
                return contents.split("\n")[0]  # First line usually has signature
            elif isinstance(contents, dict):
                value = contents.get("value", "")
                return value.split("\n")[0]

        # Fallback: get from definition
        if definition:
            return definition.get("signature", "No signature available")

        return "Signature not available"

    def _extract_docstring(self, hover: dict[str, Any]) -> str:
        """Extract docstring from hover info."""
        if not hover or "contents" not in hover:
            return ""

        contents = hover["contents"]
        if isinstance(contents, str):
            lines = contents.split("\n")
            return "\n".join(lines[1:]) if len(lines) > 1 else ""
        elif isinstance(contents, dict):
            value = contents.get("value", "")
            lines = value.split("\n")
            return "\n".join(lines[1:]) if len(lines) > 1 else ""

        return ""

    def _format_references(self, references: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Format references for output."""
        formatted = []
        for ref in references:
            uri = ref.get("uri", "")
            file_path = uri.replace("file://", "")
            range_info = ref.get("range", {})
            start = range_info.get("start", {})
            line = start.get("line", 0) + 1

            formatted.append({"file": file_path, "line": line})

        return formatted

    async def _read_implementation(self, file_path: str, start_line: int) -> dict[str, Any]:
        """Read function/class implementation."""
        try:
            # Validate path for security (prevent path traversal)
            # Note: LSP symbols may reference installed packages, but we enforce
            # workspace boundary for safety. If users need cross-workspace LSP,
            # they should use read_file directly with appropriate approval.
            validated_path = validate_path_security(file_path, allow_files_outside_workspace=False)

            with open(validated_path, encoding="utf-8") as f:
                lines = f.readlines()

            # Simple heuristic: read until next function/class or end of file
            # TODO: Use document symbols to get exact bounds
            end_line = start_line + 200  # Safety limit

            code_lines = lines[start_line:end_line]
            code = "".join(code_lines)

            return {
                "code": code
                if len(code_lines) < 200
                else f"[Code is >200 lines, use read_file('{file_path}', {start_line})]",
                "length": len(code_lines),
            }

        except Exception:
            return {"code": "[Failed to read implementation]", "length": 0}

    def _kind_to_string(self, kind: int) -> str:
        """Convert LSP SymbolKind to string."""
        kind_map = {
            5: "class",
            6: "method",
            9: "constructor",
            12: "function",
            13: "variable",
            14: "constant",
        }
        return kind_map.get(kind, f"kind_{kind}")

    def _format_symbol_context(self, symbol_name: str, matches: list[dict[str, Any]]) -> str:
        """Format symbol context as human-readable string."""
        if not matches:
            return f"No matches found for '{symbol_name}'"

        lines = [f"Symbol Context: {symbol_name}", f"Found {len(matches)} match(es)", ""]

        for i, match in enumerate(matches, 1):
            lines.append(f"Match {i}:")
            lines.append(f"  Location: {match['location']['file']}:{match['location']['line']}")
            lines.append(f"  Kind: {match['kind']}")
            lines.append(f"  Signature: {match['signature']}")

            if match.get("docstring"):
                lines.append(f"  Docstring: {match['docstring'][:100]}...")

            lines.append(f"  References: {match['references_count']} usage(s)")

            if "implementation" in match:
                impl = match["implementation"]
                if len(impl) < 500:
                    lines.append(f"  Implementation:\n{impl}")
                else:
                    lines.append(
                        f"  Implementation: {match['implementation_length']} lines (truncated)"
                    )

            lines.append("")

        return "\n".join(lines)

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Name of symbol to search for (e.g., 'authenticate', 'User', 'parse_config')",
                },
                "file_hint": {
                    "type": "string",
                    "description": "Optional file path to narrow search (e.g., 'auth.py', 'src/core/agent.py')",
                },
                "include_references": {
                    "type": "boolean",
                    "description": "Include where symbol is used (default: true)",
                },
                "include_implementation": {
                    "type": "boolean",
                    "description": "Include actual code implementation (default: true)",
                },
            },
            "required": ["symbol_name"],
        }

    def cleanup(self):
        """Cleanup handled by lsp_runtime.shutdown() at process exit."""
        # Do not close shared servers - runtime owns lifecycle
        pass
