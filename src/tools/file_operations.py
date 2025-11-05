"""File operation tools."""

import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
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


class ListDirectoryTool(Tool):
    """Tool for listing directory contents."""

    def __init__(self):
        super().__init__(
            name="list_directory",
            description="List contents of a directory with file details"
        )

    def execute(self, directory_path: str, **kwargs: Any) -> ToolResult:
        """List directory contents."""
        try:
            path = Path(directory_path)

            if not path.exists():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Directory not found: {directory_path}"
                )

            if not path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Path is not a directory: {directory_path}"
                )

            entries = []
            for entry in path.iterdir():
                entry_info = {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else None
                }
                entries.append(entry_info)

            # Sort entries: directories first, then files, both alphabetically
            entries.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output=entries,
                metadata={"directory_path": str(path), "entry_count": len(entries)}
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to list directory: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directory_path": {
                    "type": "string",
                    "description": "Path to the directory to list"
                }
            },
            "required": ["directory_path"]
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


class RunCommandTool(Tool):
    """Tool for running shell commands safely."""

    def __init__(self):
        super().__init__(
            name="run_command",
            description="Execute a shell command and return its output"
        )

    def execute(
        self,
        command: str,
        working_directory: Optional[str] = None,
        timeout: int = 30,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a shell command.

        Args:
            command: The shell command to execute
            working_directory: Optional working directory (defaults to current directory)
            timeout: Command timeout in seconds (default: 30)

        Returns:
            ToolResult with command output
        """
        try:
            # Validate inputs
            if not command or not command.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Command cannot be empty"
                )

            # Validate working directory if provided
            cwd = None
            if working_directory:
                cwd_path = Path(working_directory)
                if not cwd_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory does not exist: {working_directory}"
                    )
                if not cwd_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Working directory path is not a directory: {working_directory}"
                    )
                cwd = str(cwd_path.absolute())

            # Execute command
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Prepare output
            output_parts = []
            if result.stdout:
                output_parts.append(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"

            # Determine success based on exit code
            if result.returncode == 0:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=output,
                    metadata={
                        "command": command,
                        "exit_code": result.returncode,
                        "working_directory": cwd or "current",
                        "has_stdout": bool(result.stdout),
                        "has_stderr": bool(result.stderr)
                    }
                )
            else:
                # Non-zero exit code - treat as error but include output
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=output,
                    error=f"Command failed with exit code {result.returncode}",
                    metadata={
                        "command": command,
                        "exit_code": result.returncode,
                        "working_directory": cwd or "current"
                    }
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Command timed out after {timeout} seconds"
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to execute command: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_directory": {
                    "type": "string",
                    "description": "Optional working directory for command execution"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds (default: 30)",
                    "default": 30
                }
            },
            "required": ["command"]
        }
