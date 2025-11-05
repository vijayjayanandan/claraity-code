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
)
from src.tools.base import ToolStatus


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
        assert result.output == test_content
        assert result.metadata["file_path"] == str(test_file)
        assert result.metadata["size"] == len(test_content)

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
        assert isinstance(result.output, list)
        assert len(result.output) == 3  # 2 files + 1 directory

        # Check that directories come first
        entries = result.output
        assert entries[0]["type"] == "directory"
        assert entries[0]["name"] == "subdir"

    def test_list_empty_directory(self, tmp_path):
        """Test listing an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(empty_dir))

        assert result.status == ToolStatus.SUCCESS
        assert result.output == []

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
        assert str(tmp_path) in result.output

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
        result = tool.execute(
            command="sleep 10",
            timeout=1
        )

        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.error

    def test_run_command_creates_file(self, tmp_path):
        """Test running command that creates a file."""
        test_file = tmp_path / "created.txt"

        tool = RunCommandTool()
        result = tool.execute(
            command=f"echo 'Test content' > {test_file}",
            working_directory=str(tmp_path)
        )

        assert result.status == ToolStatus.SUCCESS
        assert test_file.exists()
        assert "Test content" in test_file.read_text()

    def test_run_command_with_stderr(self):
        """Test command that outputs to stderr."""
        tool = RunCommandTool()
        result = tool.execute(command="echo 'Error message' >&2")

        assert result.status == ToolStatus.SUCCESS
        assert "STDERR" in result.output
        assert "Error message" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
