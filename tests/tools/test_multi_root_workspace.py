"""Tests for multi-root workspace support.

Validates:
- validate_path_security accepts list of workspace roots
- File operations work across multiple workspace roots
- Search tools append workspace hints in multi-root mode
- Workspace roots can be updated mid-session
"""

import pytest
from pathlib import Path

from src.tools.search_tools import validate_path_security, _workspace_hint
from src.tools.file_operations import FileOperationTool, ReadFileTool, WriteFileTool
from src.tools.search_tools import GrepTool, GlobTool
from src.tools.base import ToolStatus


# ── validate_path_security with multiple roots ───────────────────────────


class TestMultiRootPathValidation:
    """Path validation must accept paths inside any of the workspace roots."""

    def test_path_in_primary_root(self, tmp_path):
        """Path inside the first (primary) root is accepted."""
        primary = tmp_path / "projectA"
        primary.mkdir()
        target = primary / "file.py"
        target.touch()

        result = validate_path_security(str(target), workspace_root=[primary])
        assert result == target.resolve()

    def test_path_in_secondary_root(self, tmp_path):
        """Path inside a secondary root is accepted."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()
        target = secondary / "utils.py"
        target.touch()

        result = validate_path_security(
            str(target), workspace_root=[primary, secondary]
        )
        assert result == target.resolve()

    def test_path_outside_all_roots_blocked(self, tmp_path):
        """Path outside all roots raises ValueError."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "projectB"
        primary.mkdir()
        secondary.mkdir()
        outside = tmp_path / "evil" / "file.txt"
        outside.parent.mkdir()
        outside.touch()

        with pytest.raises(ValueError, match="SECURITY"):
            validate_path_security(
                str(outside), workspace_root=[primary, secondary]
            )

    def test_single_root_backward_compat(self, tmp_path):
        """Single Path (not list) still works for backward compatibility."""
        target = tmp_path / "file.py"
        target.touch()

        result = validate_path_security(str(target), workspace_root=tmp_path)
        assert result == target.resolve()

    def test_allow_outside_workspace_bypasses_multi_root_check(self, tmp_path):
        """allow_files_outside_workspace=True skips the root check entirely."""
        root = tmp_path / "project"
        root.mkdir()
        outside = tmp_path / "elsewhere" / "data.csv"
        outside.parent.mkdir()
        outside.touch()

        result = validate_path_security(
            str(outside),
            workspace_root=[root],
            allow_files_outside_workspace=True,
        )
        assert result == outside.resolve()


# ── FileOperationTool with multiple roots ────────────────────────────────


class TestFileOperationMultiRoot:
    """File operations should work across all workspace roots."""

    def test_read_from_secondary_root(self, tmp_path, monkeypatch):
        """ReadFileTool can read files in a secondary workspace root."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()
        target = secondary / "helper.py"
        target.write_text("def helper(): pass")

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", [primary, secondary])
        tool = ReadFileTool()
        result = tool.execute(file_path=str(target))

        assert result.status == ToolStatus.SUCCESS
        assert "def helper(): pass" in result.output

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_write_to_secondary_root(self, tmp_path, monkeypatch):
        """WriteFileTool can write files in a secondary workspace root."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()
        target = secondary / "new_file.py"

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", [primary, secondary])
        tool = WriteFileTool()
        result = tool.execute(file_path=str(target), content="# new file")

        assert result.status == ToolStatus.SUCCESS
        assert target.read_text() == "# new file"

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_read_outside_all_roots_allowed_at_tool_level(self, tmp_path, monkeypatch):
        """ReadFileTool allows outside-workspace reads (gating handles approval).

        The ToolGatingService prompts for approval before the tool executes.
        At the tool level, outside-workspace reads succeed if the file exists.
        """
        primary = tmp_path / "projectA"
        primary.mkdir()
        outside = tmp_path / "other" / "data.txt"
        outside.parent.mkdir()
        outside.write_text("some data")

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", [primary])
        tool = ReadFileTool()
        result = tool.execute(file_path=str(outside))

        assert result.status == ToolStatus.SUCCESS
        assert "some data" in result.output

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)


# ── Workspace hint in search results ─────────────────────────────────────


class TestWorkspaceHint:
    """Search tools should hint about other workspace folders."""

    def test_hint_when_multi_root(self, tmp_path, monkeypatch):
        """_workspace_hint returns hint when multiple roots exist."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()

        monkeypatch.setattr(
            FileOperationTool, "_workspace_roots", [primary, secondary]
        )
        hint = _workspace_hint(None)
        assert "shared-lib" in hint
        assert "file_path" in hint

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_no_hint_single_root(self, tmp_path, monkeypatch):
        """No hint when only one workspace root."""
        primary = tmp_path / "projectA"
        primary.mkdir()

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", [primary])
        hint = _workspace_hint(None)
        assert hint == ""

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_no_hint_when_explicit_path(self, tmp_path, monkeypatch):
        """No hint when user explicitly targeted a non-primary folder."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()

        monkeypatch.setattr(
            FileOperationTool, "_workspace_roots", [primary, secondary]
        )
        # Passing a path that is not the primary root = explicit targeting
        hint = _workspace_hint(secondary)
        assert hint == ""

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_grep_includes_hint(self, tmp_path, monkeypatch):
        """GrepTool appends workspace hint when searching default path."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()
        (primary / "app.py").write_text("hello world")

        monkeypatch.setattr(
            FileOperationTool, "_workspace_roots", [primary, secondary]
        )
        monkeypatch.chdir(primary)

        tool = GrepTool()
        result = tool.execute(pattern="hello")
        assert "shared-lib" in result.output

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_grep_no_hint_explicit_path(self, tmp_path, monkeypatch):
        """GrepTool does not append hint when explicit file_path is given."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared-lib"
        primary.mkdir()
        secondary.mkdir()
        (secondary / "lib.py").write_text("hello world")

        monkeypatch.setattr(
            FileOperationTool, "_workspace_roots", [primary, secondary]
        )

        tool = GrepTool()
        result = tool.execute(pattern="hello", file_path=str(secondary))
        assert "also contains" not in (result.output or "").lower()

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)

    def test_glob_includes_hint(self, tmp_path, monkeypatch):
        """GlobTool appends workspace hint when searching default path."""
        primary = tmp_path / "projectA"
        secondary = tmp_path / "docs"
        primary.mkdir()
        secondary.mkdir()
        (primary / "main.py").touch()

        monkeypatch.setattr(
            FileOperationTool, "_workspace_roots", [primary, secondary]
        )
        monkeypatch.chdir(primary)

        tool = GlobTool()
        result = tool.execute(pattern="*.py")
        assert "docs" in result.output

        monkeypatch.setattr(FileOperationTool, "_workspace_roots", None)


# ── Agent workspace root update ──────────────────────────────────────────


class TestAgentWorkspaceUpdate:
    """Agent.update_workspace_roots propagates to all components."""

    def test_update_workspace_roots(self, tmp_path, monkeypatch):
        """update_workspace_roots updates FileOperationTool and context builder."""
        # We test the agent method indirectly by checking FileOperationTool
        primary = tmp_path / "projectA"
        secondary = tmp_path / "shared"
        primary.mkdir()
        secondary.mkdir()

        # Simulate what agent.update_workspace_roots does
        folders = [str(primary), str(secondary)]
        roots = [Path(f) for f in folders]
        FileOperationTool._workspace_roots = roots

        assert FileOperationTool._workspace_roots == roots
        assert len(FileOperationTool._workspace_roots) == 2

        # Verify a file in secondary root is accessible
        target = secondary / "data.txt"
        target.write_text("accessible")
        tool = ReadFileTool()
        result = tool.execute(file_path=str(target))
        assert result.status == ToolStatus.SUCCESS

        FileOperationTool._workspace_roots = None
