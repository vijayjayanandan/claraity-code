"""Git operation tools."""

import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from .base import Tool, ToolResult, ToolStatus


class GitStatusTool(Tool):
    """Tool for checking git repository status."""

    def __init__(self):
        super().__init__(
            name="git_status",
            description="Check the status of a git repository"
        )

    def execute(
        self,
        repository_path: Optional[str] = None,
        **kwargs: Any
    ) -> ToolResult:
        """Get git status.

        Args:
            repository_path: Optional path to git repository (defaults to current directory)

        Returns:
            ToolResult with git status output
        """
        try:
            # Validate repository path
            cwd = None
            if repository_path:
                repo_path = Path(repository_path)
                if not repo_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Repository path does not exist: {repository_path}"
                    )
                if not repo_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Repository path is not a directory: {repository_path}"
                    )
                cwd = str(repo_path.absolute())

            # Check if it's a git repository
            git_check = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
                encoding='utf-8',
                errors='replace'
            )

            if git_check.returncode != 0:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error=f"Not a git repository: {repository_path or 'current directory'}"
                )

            # Get git status
            result = subprocess.run(
                ["git", "status", "--porcelain", "-b"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )

            if result.returncode == 0:
                # Parse status output
                lines = result.stdout.strip().split("\n") if result.stdout else []
                branch_info = lines[0] if lines else "## (no branch info)"
                file_changes = lines[1:] if len(lines) > 1 else []

                output = f"Branch: {branch_info[3:] if branch_info.startswith('## ') else branch_info}\n\n"
                if file_changes:
                    output += f"Changed files ({len(file_changes)}):\n"
                    output += "\n".join(file_changes)
                else:
                    output += "Working tree clean"

                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=output,
                    metadata={
                        "repository_path": cwd or "current",
                        "branch": branch_info,
                        "changed_files": len(file_changes),
                        "is_clean": len(file_changes) == 0
                    }
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=result.stdout,
                    error=f"Git status failed: {result.stderr}"
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Git status command timed out"
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to get git status: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repository_path": {
                    "type": "string",
                    "description": "Optional path to git repository (defaults to current directory)"
                }
            },
            "required": []
        }


class GitDiffTool(Tool):
    """Tool for viewing git diffs."""

    def __init__(self):
        super().__init__(
            name="git_diff",
            description="View changes in a git repository (staged or unstaged)"
        )

    def execute(
        self,
        repository_path: Optional[str] = None,
        staged: bool = False,
        file_path: Optional[str] = None,
        **kwargs: Any
    ) -> ToolResult:
        """Get git diff.

        Args:
            repository_path: Optional path to git repository
            staged: If True, show staged changes; if False, show unstaged changes
            file_path: Optional specific file to diff

        Returns:
            ToolResult with git diff output
        """
        try:
            # Validate repository path
            cwd = None
            if repository_path:
                repo_path = Path(repository_path)
                if not repo_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Repository path does not exist: {repository_path}"
                    )
                cwd = str(repo_path.absolute())

            # Build git diff command
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--cached")
            if file_path:
                cmd.append(file_path)

            # Execute git diff
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )

            if result.returncode == 0:
                diff_output = result.stdout if result.stdout else "(no changes)"

                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=diff_output,
                    metadata={
                        "repository_path": cwd or "current",
                        "staged": staged,
                        "file_path": file_path or "all files",
                        "has_changes": bool(result.stdout)
                    }
                )
            else:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=result.stdout,
                    error=f"Git diff failed: {result.stderr}"
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Git diff command timed out"
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to get git diff: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repository_path": {
                    "type": "string",
                    "description": "Optional path to git repository"
                },
                "staged": {
                    "type": "boolean",
                    "description": "If true, show staged changes; if false, show unstaged changes",
                    "default": False
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional specific file to diff"
                }
            },
            "required": []
        }


class GitCommitTool(Tool):
    """Tool for creating git commits."""

    def __init__(self):
        super().__init__(
            name="git_commit",
            description="Create a git commit with staged changes"
        )

    def execute(
        self,
        message: str,
        repository_path: Optional[str] = None,
        **kwargs: Any
    ) -> ToolResult:
        """Create a git commit.

        Args:
            message: Commit message
            repository_path: Optional path to git repository

        Returns:
            ToolResult with commit status
        """
        try:
            # Validate inputs
            if not message or not message.strip():
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.ERROR,
                    output=None,
                    error="Commit message cannot be empty"
                )

            # Validate repository path
            cwd = None
            if repository_path:
                repo_path = Path(repository_path)
                if not repo_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error=f"Repository path does not exist: {repository_path}"
                    )
                cwd = str(repo_path.absolute())

            # Create commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )

            if result.returncode == 0:
                output = result.stdout if result.stdout else "Commit created successfully"

                # Get commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else "unknown"

                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=output,
                    metadata={
                        "repository_path": cwd or "current",
                        "message": message,
                        "commit_hash": commit_hash
                    }
                )
            else:
                # Check if no changes staged
                if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=None,
                        error="No changes staged for commit"
                    )
                else:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.ERROR,
                        output=result.stdout,
                        error=f"Git commit failed: {result.stderr}"
                    )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error="Git commit command timed out"
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to create git commit: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message"
                },
                "repository_path": {
                    "type": "string",
                    "description": "Optional path to git repository"
                }
            },
            "required": ["message"]
        }
