"""Tests for file operation tools."""

import pytest
import tempfile
import os
from pathlib import Path
from src.tools import (
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    ListDirectoryTool,
    RunCommandTool,
    AppendToFileTool,
)
from src.tools.file_operations import FileOperationTool
from src.tools.base import ToolStatus


@pytest.fixture(autouse=True)
def allow_test_workspace(tmp_path, monkeypatch):
    """
    Fixture to allow file operations in test tmp_path.

    This sets the workspace root to tmp_path for all FileOperationTool
    subclasses, allowing tests to operate on temporary files without
    triggering security violations.
    """
    # Set workspace root to tmp_path for all file operation tools
    monkeypatch.setattr(FileOperationTool, '_workspace_root', tmp_path)
    yield
    # Reset after test
    monkeypatch.setattr(FileOperationTool, '_workspace_root', None)


class TestReadFileTool:
    """Tests for ReadFileTool."""

    def test_read_existing_file(self, tmp_path):
        """Test reading an existing file."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        # Read file
        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file))

        assert result.status == ToolStatus.SUCCESS
        # Output now includes line numbers
        assert "Hello, World!" in result.output
        assert result.metadata["file_path"] == str(test_file)
        assert result.metadata["lines_returned"] == 1

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading a non-existent file."""
        tool = ReadFileTool()
        result = tool.execute(file_path=str(tmp_path / "nonexistent.txt"))

        assert result.status == ToolStatus.ERROR
        assert "File not found" in result.error

    def test_read_directory(self, tmp_path):
        """Test reading a directory (should fail)."""
        tool = ReadFileTool()
        result = tool.execute(file_path=str(tmp_path))

        assert result.status == ToolStatus.ERROR
        assert "not a file" in result.error


class TestReadFileToolLineRange:
    """Tests for ReadFileTool line range support."""

    def test_read_with_start_line(self, tmp_path):
        """Test reading from specific start line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file), start_line=3)

        assert result.status == ToolStatus.SUCCESS
        assert "line3" in result.output
        assert "line1" not in result.output
        assert result.metadata["start_line"] == 3
        assert result.metadata["lines_returned"] == 3  # lines 3, 4, 5

    def test_read_with_end_line(self, tmp_path):
        """Test reading up to specific end line (exclusive)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file), start_line=1, end_line=3)

        assert result.status == ToolStatus.SUCCESS
        assert "line1" in result.output
        assert "line2" in result.output
        assert "line3" not in result.output  # end_line is EXCLUSIVE
        assert result.metadata["lines_returned"] == 2  # lines 1, 2

    def test_read_with_max_lines(self, tmp_path):
        """Test reading with max lines limit."""
        test_file = tmp_path / "test.txt"
        lines = "\n".join([f"line{i}" for i in range(100)])
        test_file.write_text(lines)

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file), max_lines=10)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["lines_returned"] == 10
        assert result.metadata["has_more"] == True

    def test_has_more_hint(self, tmp_path):
        """Test that hint is shown when more content exists."""
        test_file = tmp_path / "test.txt"
        lines = "\n".join([f"line{i}" for i in range(100)])
        test_file.write_text(lines)

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file), max_lines=10)

        # Check new hint format: [Lines X-Y of Z | Continue: start_line=N, max_lines=M]
        assert "Lines 1-10 of" in result.output
        assert "Continue: start_line=11" in result.output
        assert "max_lines=2000" in result.output

    def test_line_numbers_included(self, tmp_path):
        """Test that line numbers are in output (cat -n format)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello\nworld")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file))

        assert result.status == ToolStatus.SUCCESS
        # Line numbers in format: "     1\thello"
        assert "\t" in result.output  # Tab separator
        assert "hello" in result.output
        assert "world" in result.output

    def test_long_line_truncation(self, tmp_path):
        """Test that very long lines are truncated."""
        test_file = tmp_path / "test.txt"
        long_line = "x" * 3000  # Longer than MAX_LINE_LENGTH (2000)
        test_file.write_text(long_line)

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file))

        assert result.status == ToolStatus.SUCCESS
        assert "[truncated]" in result.output
        # Output should be shorter than original
        assert len(result.output) < 3000

    def test_streaming_not_loading_entire_file(self, tmp_path):
        """Test that streaming read doesn't load entire file for first N lines."""
        # Create a file with many lines
        test_file = tmp_path / "large.txt"
        lines = "\n".join([f"line{i}" for i in range(10000)])
        test_file.write_text(lines)

        tool = ReadFileTool()
        # Read only first 10 lines
        result = tool.execute(file_path=str(test_file), max_lines=10)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["lines_returned"] == 10
        # Key streaming benefit: has_more indicates more content exists
        assert result.metadata["has_more"] == True
        # Total lines count is provided (may do second pass to count)
        assert result.metadata["total_lines"] >= 10  # At minimum, we know we read 10

    def test_start_line_beyond_file_length(self, tmp_path):
        """Test reading with start_line beyond file length."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file), start_line=100)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["lines_returned"] == 0
        assert result.output == ""  # No lines to return

    def test_exact_line_range(self, tmp_path):
        """Test reading exact line range (start=100, end=200 returns lines 100-199)."""
        test_file = tmp_path / "test.txt"
        lines = "\n".join([f"line{i}" for i in range(1, 251)])  # lines 1-250
        test_file.write_text(lines)

        tool = ReadFileTool()
        result = tool.execute(file_path=str(test_file), start_line=100, end_line=200)

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["lines_returned"] == 100  # 100 lines (100-199)
        assert result.metadata["start_line"] == 100
        assert result.metadata["end_line"] == 200  # Exclusive
        assert "line100" in result.output
        assert "line199" in result.output
        assert "line200" not in result.output  # Exclusive


class TestReadFileToolSecurity:
    """Tests for ReadFileTool path security."""

    def test_read_file_blocks_path_traversal(self, tmp_path, monkeypatch):
        """Test that ReadFileTool blocks path traversal."""
        # Reset workspace to current directory (not tmp_path)
        monkeypatch.setattr(FileOperationTool, '_workspace_root', Path.cwd())

        tool = ReadFileTool()
        # Try to read outside workspace
        result = tool.execute(file_path="../../../etc/passwd")

        assert result.status == ToolStatus.ERROR
        assert "SECURITY" in result.error or "outside" in result.error.lower()


class TestWriteFileTool:
    """Tests for WriteFileTool."""

    def test_write_new_file(self, tmp_path):
        """Test writing a new file."""
        test_file = tmp_path / "new.txt"
        test_content = "New content"

        tool = WriteFileTool()
        result = tool.execute(file_path=str(test_file), content=test_content)

        assert result.status == ToolStatus.SUCCESS
        assert test_file.exists()
        assert test_file.read_text() == test_content

    def test_write_creates_parent_directories(self, tmp_path):
        """Test that writing creates parent directories."""
        test_file = tmp_path / "subdir" / "nested" / "file.txt"
        test_content = "Nested content"

        tool = WriteFileTool()
        result = tool.execute(file_path=str(test_file), content=test_content)

        assert result.status == ToolStatus.SUCCESS
        assert test_file.exists()
        assert test_file.read_text() == test_content

    def test_write_overwrites_existing(self, tmp_path):
        """Test that writing overwrites existing files."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("Old content")

        new_content = "New content"
        tool = WriteFileTool()
        result = tool.execute(file_path=str(test_file), content=new_content)

        assert result.status == ToolStatus.SUCCESS
        assert test_file.read_text() == new_content


class TestWriteFileToolSecurity:
    """Tests for WriteFileTool path security."""

    def test_write_file_blocks_path_traversal(self, tmp_path, monkeypatch):
        """Test that WriteFileTool blocks path traversal."""
        monkeypatch.setattr(FileOperationTool, '_workspace_root', Path.cwd())

        tool = WriteFileTool()
        result = tool.execute(
            file_path="../../../tmp/evil.txt",
            content="malicious"
        )

        assert result.status == ToolStatus.ERROR
        assert "SECURITY" in result.error or "outside" in result.error.lower()


class TestEditFileTool:
    """Tests for EditFileTool."""

    def test_edit_existing_text(self, tmp_path):
        """Test editing existing text in a file."""
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello, World!")

        tool = EditFileTool()
        result = tool.execute(
            file_path=str(test_file),
            old_text="World",
            new_text="Python"
        )

        assert result.status == ToolStatus.SUCCESS
        assert test_file.read_text() == "Hello, Python!"
        assert result.metadata["replacements"] == 1

    def test_edit_text_not_found(self, tmp_path):
        """Test editing when old text doesn't exist."""
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello, World!")

        tool = EditFileTool()
        result = tool.execute(
            file_path=str(test_file),
            old_text="NotFound",
            new_text="Python"
        )

        assert result.status == ToolStatus.ERROR
        assert "not found" in result.error

    def test_edit_nonexistent_file(self, tmp_path):
        """Test editing a non-existent file."""
        tool = EditFileTool()
        result = tool.execute(
            file_path=str(tmp_path / "nonexistent.txt"),
            old_text="old",
            new_text="new"
        )

        assert result.status == ToolStatus.ERROR
        assert "File not found" in result.error


class TestEditFileToolSecurity:
    """Tests for EditFileTool path security."""

    def test_edit_file_blocks_path_traversal(self, tmp_path, monkeypatch):
        """Test that EditFileTool blocks path traversal."""
        monkeypatch.setattr(FileOperationTool, '_workspace_root', Path.cwd())

        tool = EditFileTool()
        result = tool.execute(
            file_path="../../../etc/passwd",
            old_text="root",
            new_text="hacked"
        )

        assert result.status == ToolStatus.ERROR
        assert "SECURITY" in result.error or "outside" in result.error.lower()


class TestAppendToFileTool:
    """Tests for AppendToFileTool."""

    def test_append_to_existing_file(self, tmp_path):
        """Test appending to existing file."""
        test_file = tmp_path / "append.txt"
        test_file.write_text("First line")

        tool = AppendToFileTool()
        result = tool.execute(file_path=str(test_file), content="Second line")

        assert result.status == ToolStatus.SUCCESS
        content = test_file.read_text()
        assert "First line" in content
        assert "Second line" in content

    def test_append_to_new_file(self, tmp_path):
        """Test appending creates file if doesn't exist."""
        test_file = tmp_path / "new_append.txt"

        tool = AppendToFileTool()
        result = tool.execute(file_path=str(test_file), content="New content")

        assert result.status == ToolStatus.SUCCESS
        assert test_file.exists()
        assert test_file.read_text() == "New content"

    def test_append_adds_newline_if_needed(self, tmp_path):
        """Test that append adds newline if file doesn't end with one."""
        test_file = tmp_path / "no_newline.txt"
        test_file.write_text("Line without newline")

        tool = AppendToFileTool()
        result = tool.execute(file_path=str(test_file), content="New line")

        assert result.status == ToolStatus.SUCCESS
        content = test_file.read_text()
        assert content == "Line without newline\nNew line"


class TestListDirectoryTool:
    """Tests for ListDirectoryTool."""

    def test_list_directory(self, tmp_path):
        """Test listing directory contents."""
        # Create test structure
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("content2")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("content3")

        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(tmp_path))

        assert result.status == ToolStatus.SUCCESS
        assert isinstance(result.output, str)

        # Directories listed first in formatted output
        assert "[dir]  subdir/" in result.output
        assert "[file] file1.txt" in result.output
        assert "[file] file2.py" in result.output

        # Structured data preserved in metadata
        entries = result.metadata["entries"]
        assert len(entries) == 3  # 2 files + 1 directory
        assert entries[0]["type"] == "directory"
        assert entries[0]["name"] == "subdir"

        # Every entry should have an mtime field (ISO 8601 with timezone)
        for entry in entries:
            assert "mtime" in entry, f"Entry {entry['name']} missing mtime"
            assert "T" in entry["mtime"], f"mtime should be ISO format: {entry['mtime']}"

    def test_list_empty_directory(self, tmp_path):
        """Test listing an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(empty_dir))

        assert result.status == ToolStatus.SUCCESS
        assert result.output == ""

    def test_list_nonexistent_directory(self, tmp_path):
        """Test listing a non-existent directory."""
        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(tmp_path / "nonexistent"))

        assert result.status == ToolStatus.ERROR
        assert "Directory not found" in result.error

    def test_list_file_not_directory(self, tmp_path):
        """Test listing a file (should fail)."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(test_file))

        assert result.status == ToolStatus.ERROR
        assert "not a directory" in result.error

    def test_shows_gitignore_hidden_entries(self, tmp_path, monkeypatch):
        """list_directory ignores .gitignore -- user explicitly chose this path."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".gitignore").write_text("secret/\n")
        subdir = tmp_path / "secret"
        subdir.mkdir()
        (subdir / "data.txt").write_text("hello")
        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(subdir))
        assert result.status == ToolStatus.SUCCESS
        assert "data.txt" in result.output

    def test_hides_claraityignore_blocked_entries(self, tmp_path, monkeypatch):
        """.claraityignore-blocked entries are omitted from list_directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".claraityignore").write_text("secret.txt\n")
        (tmp_path / "secret.txt").write_text("blocked")
        (tmp_path / "visible.txt").write_text("allowed")
        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(tmp_path))
        assert result.status == ToolStatus.SUCCESS
        assert "visible.txt" in result.output
        assert "secret.txt" not in result.output


class TestRunCommandTool:
    """Tests for RunCommandTool."""

    def test_run_simple_command(self):
        """Test running a simple command."""
        tool = RunCommandTool()
        result = tool.execute(command="echo 'Hello, World!'")

        assert result.status == ToolStatus.SUCCESS
        assert "Hello, World!" in result.output
        assert result.metadata["exit_code"] == 0

    def test_run_command_with_working_directory(self, tmp_path):
        """Test running command in a specific directory."""
        tool = RunCommandTool()
        result = tool.execute(
            command="pwd",
            working_directory=str(tmp_path)
        )

        assert result.status == ToolStatus.SUCCESS
        # Bash on Windows (Git Bash/MSYS) translates paths (e.g. C:\...\Temp -> /tmp/...),
        # so compare the directory basename which is preserved across all shells.
        assert tmp_path.name in result.output

    def test_run_command_failure(self):
        """Test running a command that fails."""
        tool = RunCommandTool()
        result = tool.execute(command="exit 1")

        assert result.status == ToolStatus.ERROR
        assert result.metadata["exit_code"] == 1

    def test_run_command_nonexistent_directory(self):
        """Test running command in non-existent directory."""
        tool = RunCommandTool()
        result = tool.execute(
            command="echo test",
            working_directory="/nonexistent/directory"
        )

        assert result.status == ToolStatus.ERROR
        assert "does not exist" in result.error

    def test_run_command_empty_command(self):
        """Test running empty command."""
        tool = RunCommandTool()
        result = tool.execute(command="")

        assert result.status == ToolStatus.ERROR
        assert "cannot be empty" in result.error

    def test_run_command_with_timeout(self):
        """Test command timeout."""
        tool = RunCommandTool()
        # Use a command that takes time
        result = tool.execute(
            command="ping -n 10 127.0.0.1" if os.name == 'nt' else "sleep 10",
            timeout=1
        )

        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.error

    def test_run_command_with_stderr(self):
        """Test command that outputs to stderr."""
        tool = RunCommandTool()
        # Use a command that writes to stderr
        if os.name == 'nt':
            # PowerShell stderr
            result = tool.execute(command="Write-Error 'Error message'")
        else:
            result = tool.execute(command="echo 'Error message' >&2")

        # Command may succeed or fail, but should have stderr
        assert "STDERR" in result.output or "Error message" in str(result.output)


class TestRunCommandBashExecution:
    """Tests for bash execution path on Windows (shell detection integration)."""

    def test_and_chaining_works(self):
        """'&&' chaining should work and return exit code 0."""
        tool = RunCommandTool()
        result = tool.execute(command="echo first && echo second")
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["exit_code"] == 0
        assert "first" in result.output
        assert "second" in result.output

    def test_and_chaining_fails_on_first(self):
        """'&&' should short-circuit: if first command fails, second doesn't run."""
        tool = RunCommandTool()
        result = tool.execute(command="exit 1 && echo should-not-appear")
        assert result.status == ToolStatus.ERROR
        assert "should-not-appear" not in (result.output or "")

    def test_pipe_exit_code_is_reliable(self):
        """Pipes should return exit code 0 when the pipeline succeeds.

        This is the original bug: PowerShell pipes (Select-Object) return exit code 1
        even on success. With bash, this should be clean.
        """
        tool = RunCommandTool()
        result = tool.execute(command="echo line1 | tail -1")
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["exit_code"] == 0

    def test_unix_tools_available(self):
        """Standard Unix tools (grep, tail, head) should be available via bash."""
        tool = RunCommandTool()
        result = tool.execute(command="echo hello world | grep hello")
        assert result.status == ToolStatus.SUCCESS
        assert "hello" in result.output

    def test_powershell_sanitize_skipped_for_bash(self):
        """When using bash, '&&' should NOT be sanitized to '; '."""
        tool = RunCommandTool()
        # If sanitization happened, 'exit 1 ; echo appeared' would print 'appeared'
        # because ';' runs regardless of exit code. With &&, it should not.
        result = tool.execute(command="exit 1 && echo appeared")
        assert "appeared" not in (result.output or "")

    def test_semicolon_runs_regardless(self):
        """';' should run second command even if first fails (bash semantics).

        Note: 'exit 1' terminates the bash process, so we use 'false' instead
        (which sets exit code 1 without terminating the shell).
        """
        tool = RunCommandTool()
        result = tool.execute(command="false ; echo still-ran")
        assert "still-ran" in result.output

    def test_stderr_captured(self):
        """stderr should be captured in bash mode."""
        tool = RunCommandTool()
        result = tool.execute(command="echo error-msg >&2")
        assert "STDERR" in result.output
        assert "error-msg" in result.output

    def test_environment_variables(self):
        """Environment variable expansion should work in bash."""
        tool = RunCommandTool()
        result = tool.execute(command="echo $HOME")
        assert result.status == ToolStatus.SUCCESS
        # $HOME should expand to something (not the literal string)
        assert "$HOME" not in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
