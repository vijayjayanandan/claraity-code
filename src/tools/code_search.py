"""Code search and analysis tools."""

from pathlib import Path
from typing import Dict, Any, List
import re

from .base import Tool, ToolResult, ToolStatus


class SearchCodeTool(Tool):
    """Tool for searching code."""

    def __init__(self):
        super().__init__(
            name="search_code",
            description="Search for text/pattern in code files"
        )

    def execute(
        self,
        query: str,
        directory: str = ".",
        file_pattern: str = "*.py",
        **kwargs: Any
    ) -> ToolResult:
        """Search for text in files."""
        try:
            path = Path(directory)

            if not path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Directory not found: {directory}"
                )

            # Find matching files
            files = list(path.rglob(file_pattern))

            matches = []
            for file in files:
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        lines = f.readlines()

                    for line_num, line in enumerate(lines, 1):
                        if query.lower() in line.lower():
                            matches.append({
                                "file": str(file),
                                "line": line_num,
                                "content": line.strip()
                            })
                except:
                    continue

            if not matches:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="No matches found",
                    metadata={"query": query, "matches": 0}
                )

            # Format output
            output_lines = []
            for match in matches[:20]:  # Limit to 20 results
                output_lines.append(
                    f"{match['file']}:{match['line']} - {match['content']}"
                )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(output_lines),
                metadata={"query": query, "matches": len(matches)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Search failed: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text or pattern to search for"
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search in (default: current)"
                },
                "file_pattern": {
                    "type": "string",
                    "description": "File pattern to match (default: *.py)"
                }
            },
            "required": ["query"]
        }


class AnalyzeCodeTool(Tool):
    """Tool for basic code analysis."""

    def __init__(self):
        super().__init__(
            name="analyze_code",
            description="Analyze code structure (functions, classes, imports)"
        )

    def execute(self, file_path: str, **kwargs: Any) -> ToolResult:
        """Analyze code structure."""
        try:
            path = Path(file_path)

            if not path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}"
                )

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract basic info (simple regex-based)
            analysis = {
                "functions": self._extract_functions(content),
                "classes": self._extract_classes(content),
                "imports": self._extract_imports(content),
                "lines": len(content.split("\n")),
                "characters": len(content)
            }

            # Format output
            output = f"Code Analysis for {file_path}:\n"
            output += f"- Lines: {analysis['lines']}\n"
            output += f"- Functions: {', '.join(analysis['functions']) if analysis['functions'] else 'None'}\n"
            output += f"- Classes: {', '.join(analysis['classes']) if analysis['classes'] else 'None'}\n"
            output += f"- Imports: {len(analysis['imports'])} import(s)\n"

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=output,
                metadata=analysis
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Analysis failed: {str(e)}"
            )

    def _extract_functions(self, content: str) -> List[str]:
        """Extract function names."""
        pattern = r'^\s*def\s+(\w+)\s*\('
        return re.findall(pattern, content, re.MULTILINE)

    def _extract_classes(self, content: str) -> List[str]:
        """Extract class names."""
        pattern = r'^\s*class\s+(\w+)\s*[:\(]'
        return re.findall(pattern, content, re.MULTILINE)

    def _extract_imports(self, content: str) -> List[str]:
        """Extract import statements."""
        pattern = r'^\s*(import\s+\S+|from\s+\S+\s+import\s+.+)$'
        return re.findall(pattern, content, re.MULTILINE)

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to analyze"
                }
            },
            "required": ["file_path"]
        }
