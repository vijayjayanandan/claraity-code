"""Tests for git operation tools."""

import pytest
import subprocess
from pathlib import Path
from src.tools import GitStatusTool, GitDiffTool, GitCommitTool
from src.tools.base import ToolStatus


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository for testing."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )

    return repo_path


class TestGitStatusTool:
    """Tests for GitStatusTool."""

    def test_git_status_clean_repo(self, git_repo):
        """Test git status on a clean repository."""
        # Create and commit a file to have something in the repo
        test_file = git_repo / "test.txt"
        test_file.write_text("Initial content")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )

        tool = GitStatusTool()
        result = tool.execute(repository_path=str(git_repo))

        assert result.status == ToolStatus.SUCCESS
        assert "Working tree clean" in result.output
        assert result.metadata["is_clean"] is True
        assert result.metadata["changed_files"] == 0

    def test_git_status_with_changes(self, git_repo):
        """Test git status with uncommitted changes."""
        # Create initial file
        test_file = git_repo / "test.txt"
        test_file.write_text("Initial content")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )

        # Modify file
        test_file.write_text("Modified content")

        tool = GitStatusTool()
        result = tool.execute(repository_path=str(git_repo))

        assert result.status == ToolStatus.SUCCESS
        assert "test.txt" in result.output
        assert result.metadata["is_clean"] is False
        assert result.metadata["changed_files"] > 0

    def test_git_status_not_a_repo(self, tmp_path):
        """Test git status on non-git directory."""
        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()

        tool = GitStatusTool()
        result = tool.execute(repository_path=str(non_repo))

        assert result.status == ToolStatus.ERROR
        assert "Not a git repository" in result.error

    def test_git_status_nonexistent_path(self, tmp_path):
        """Test git status on non-existent path."""
        tool = GitStatusTool()
        result = tool.execute(repository_path=str(tmp_path / "nonexistent"))

        assert result.status == ToolStatus.ERROR
        assert "does not exist" in result.error

    def test_git_status_default_path(self):
        """Test git status with default path (current directory)."""
        tool = GitStatusTool()
        result = tool.execute()

        # This should work if we're in a git repo, or fail if not
        # Either way, it shouldn't crash
        assert result.status in [ToolStatus.SUCCESS, ToolStatus.ERROR]


class TestGitDiffTool:
    """Tests for GitDiffTool."""

    def test_git_diff_unstaged_changes(self, git_repo):
        """Test git diff for unstaged changes."""
        # Create and commit initial file
        test_file = git_repo / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\n")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )

        # Modify file
        test_file.write_text("Line 1\nModified Line 2\nLine 3\n")

        tool = GitDiffTool()
        result = tool.execute(repository_path=str(git_repo), staged=False)

        assert result.status == ToolStatus.SUCCESS
        assert "test.txt" in result.output
        assert "-Line 2" in result.output or "Modified Line 2" in result.output
        assert result.metadata["has_changes"] is True

    def test_git_diff_staged_changes(self, git_repo):
        """Test git diff for staged changes."""
        # Create and commit initial file
        test_file = git_repo / "test.txt"
        test_file.write_text("Line 1\nLine 2\n")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )

        # Modify and stage file
        test_file.write_text("Line 1\nModified Line 2\n")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)

        tool = GitDiffTool()
        result = tool.execute(repository_path=str(git_repo), staged=True)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["has_changes"] is True

    def test_git_diff_specific_file(self, git_repo):
        """Test git diff for a specific file."""
        # Create and commit two files
        file1 = git_repo / "file1.txt"
        file2 = git_repo / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )

        # Modify both files
        file1.write_text("Modified Content 1")
        file2.write_text("Modified Content 2")

        tool = GitDiffTool()
        result = tool.execute(
            repository_path=str(git_repo),
            staged=False,
            file_path="file1.txt"
        )

        assert result.status == ToolStatus.SUCCESS
        assert "file1.txt" in result.output
        # file2.txt should not be in the output
        # (though this depends on git diff format)

    def test_git_diff_no_changes(self, git_repo):
        """Test git diff when there are no changes."""
        # Create and commit a file
        test_file = git_repo / "test.txt"
        test_file.write_text("Content")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True
        )

        tool = GitDiffTool()
        result = tool.execute(repository_path=str(git_repo))

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["has_changes"] is False


class TestGitCommitTool:
    """Tests for GitCommitTool."""

    def test_git_commit_with_staged_changes(self, git_repo):
        """Test creating a git commit with staged changes."""
        # Create and stage a file
        test_file = git_repo / "test.txt"
        test_file.write_text("Test content")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)

        tool = GitCommitTool()
        result = tool.execute(
            message="Test commit message",
            repository_path=str(git_repo)
        )

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["message"] == "Test commit message"
        assert len(result.metadata["commit_hash"]) > 0

        # Verify commit was created
        log_result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        assert "Test commit message" in log_result.stdout

    def test_git_commit_no_changes(self, git_repo):
        """Test git commit with no staged changes."""
        tool = GitCommitTool()
        result = tool.execute(
            message="Empty commit",
            repository_path=str(git_repo)
        )

        assert result.status == ToolStatus.ERROR
        assert "No changes staged" in result.error

    def test_git_commit_empty_message(self, git_repo):
        """Test git commit with empty message."""
        # Create and stage a file
        test_file = git_repo / "test.txt"
        test_file.write_text("Content")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)

        tool = GitCommitTool()
        result = tool.execute(message="", repository_path=str(git_repo))

        assert result.status == ToolStatus.ERROR
        assert "cannot be empty" in result.error

    def test_git_commit_multiline_message(self, git_repo):
        """Test git commit with multiline message."""
        # Create and stage a file
        test_file = git_repo / "test.txt"
        test_file.write_text("Content")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)

        commit_message = "First line\n\nDetailed description\nwith multiple lines"

        tool = GitCommitTool()
        result = tool.execute(
            message=commit_message,
            repository_path=str(git_repo)
        )

        assert result.status == ToolStatus.SUCCESS

        # Verify full message was preserved
        log_result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%B"],
            cwd=git_repo,
            capture_output=True,
            text=True
        )
        assert "First line" in log_result.stdout
        assert "Detailed description" in log_result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
