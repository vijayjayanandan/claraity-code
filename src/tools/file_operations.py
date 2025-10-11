"""File operation tools."""

from pathlib import Path
from typing import Dict, Any
from .base import Tool, ToolResult, ToolStatus


class ReadFileTool(Tool):
    """Tool for reading files."""

    def __init__(self):
        super().__init__(
            name="read_file",
            description="Read contents of a file"
        )

    def execute(self, file_path: str, **kwargs: Any) -> ToolResult:
        """Read file contents."""
        try:
            path = Path(file_path)

            if not path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}"
                )

            if not path.is_file():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a file: {file_path}"
                )

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=content,
                metadata={"file_path": str(path), "size": len(content)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to read file: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read"
                }
            },
            "required": ["file_path"]
        }


class WriteFileTool(Tool):
    """Tool for writing files."""

    def __init__(self):
        super().__init__(
            name="write_file",
            description="Write content to a file (creates or overwrites)"
        )

    def execute(self, file_path: str, content: str, **kwargs: Any) -> ToolResult:
        """Write content to file."""
        try:
            path = Path(file_path)

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={"file_path": str(path), "size": len(content)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to write file: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }


class EditFileTool(Tool):
    """Tool for editing files with find/replace."""

    def __init__(self):
        super().__init__(
            name="edit_file",
            description="Edit a file by replacing old text with new text"
        )

    def execute(
        self,
        file_path: str,
        old_text: str,
        new_text: str,
        **kwargs: Any
    ) -> ToolResult:
        """Edit file with find/replace."""
        try:
            path = Path(file_path)

            if not path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"File not found: {file_path}"
                )

            # Read current content
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check if old_text exists
            if old_text not in content:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Text to replace not found in file"
                )

            # Replace
            new_content = content.replace(old_text, new_text)

            # Write back
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=f"Successfully edited {file_path}",
                metadata={
                    "file_path": str(path),
                    "replacements": content.count(old_text)
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to edit file: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "Text to find and replace"
                },
                "new_text": {
                    "type": "string",
                    "description": "New text to replace with"
                }
            },
            "required": ["file_path", "old_text", "new_text"]
        }
