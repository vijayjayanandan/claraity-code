"""Tests for .claraityignore file blocking feature."""

import os
from pathlib import Path

import pytest

from src.tools.claraityignore import check_command, filter_paths, is_blocked


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Set up a temp workspace with CWD pointed at it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_ignore(workspace: Path, content: str) -> None:
    (workspace / ".claraityignore").write_text(content, encoding="utf-8")


# ---------- Parsing ----------


class TestParsing:
    def test_no_file_returns_not_blocked(self, workspace):
        assert is_blocked("anything.py") == (False, None)

    def test_empty_file_returns_not_blocked(self, workspace):
        _write_ignore(workspace, "")
        assert is_blocked("anything.py") == (False, None)

    def test_comments_and_blanks_ignored(self, workspace):
        _write_ignore(workspace, "# this is a comment\n\n  \n# another comment\n")
        assert is_blocked("anything.py") == (False, None)

    def test_whitespace_only_lines_ignored(self, workspace):
        _write_ignore(workspace, "   \n\t\n")
        assert is_blocked("anything.py") == (False, None)


# ---------- Pattern Matching ----------


class TestPatternMatching:
    def test_wildcard_extension(self, workspace):
        _write_ignore(workspace, "*.env")
        assert is_blocked("foo.env") == (True, "*.env")
        assert is_blocked("deep/bar.env") == (True, "*.env")
        assert is_blocked("foo.py") == (False, None)

    def test_specific_filename(self, workspace):
        _write_ignore(workspace, "secrets.json")
        assert is_blocked("secrets.json") == (True, "secrets.json")
        assert is_blocked("other.json") == (False, None)

    def test_directory_pattern(self, workspace):
        _write_ignore(workspace, "secrets/")
        # Create the directory structure so resolve works
        (workspace / "secrets").mkdir()
        (workspace / "secrets" / "key.txt").write_text("x")
        assert is_blocked("secrets/key.txt") == (True, "secrets/")

    def test_double_star_glob(self, workspace):
        _write_ignore(workspace, "**/*.log")
        assert is_blocked("debug.log") == (True, "**/*.log")
        assert is_blocked("a/b/c/debug.log") == (True, "**/*.log")
        assert is_blocked("app.py") == (False, None)

    def test_negation_pattern(self, workspace):
        _write_ignore(workspace, "*.py\n!public.py")
        assert is_blocked("app.py") == (True, "*.py")
        assert is_blocked("public.py") == (False, None)

    def test_multiple_patterns(self, workspace):
        _write_ignore(workspace, "*.env\n*.key\nsecrets/")
        assert is_blocked("prod.env")[0] is True
        assert is_blocked("private.key")[0] is True
        assert is_blocked("app.py") == (False, None)

    def test_absolute_path_resolved_to_relative(self, workspace):
        _write_ignore(workspace, "*.env")
        abs_path = workspace / "prod.env"
        assert is_blocked(str(abs_path)) == (True, "*.env")

    def test_matching_pattern_returned_in_result(self, workspace):
        _write_ignore(workspace, "*.env\n*.key")
        blocked, pattern = is_blocked("server.key")
        assert blocked is True
        assert pattern == "*.key"


# ---------- filter_paths ----------


class TestFilterPaths:
    def test_no_file_returns_all(self, workspace):
        paths = [workspace / "a.py", workspace / "b.py"]
        assert filter_paths(paths) == paths

    def test_filters_blocked_files(self, workspace):
        _write_ignore(workspace, "*.env")
        paths = [workspace / "a.py", workspace / "b.env", workspace / "c.py"]
        result = filter_paths(paths)
        assert len(result) == 2
        assert all(not str(p).endswith(".env") for p in result)

    def test_empty_patterns_returns_all(self, workspace):
        _write_ignore(workspace, "")
        paths = [workspace / "a.py", workspace / "b.env"]
        assert filter_paths(paths) == paths

    def test_mixed_matches(self, workspace):
        _write_ignore(workspace, "*.env\n*.key")
        paths = [
            workspace / "a.py",
            workspace / "b.env",
            workspace / "c.key",
            workspace / "d.txt",
        ]
        result = filter_paths(paths)
        names = [p.name for p in result]
        assert names == ["a.py", "d.txt"]


# ---------- File Tool Integration ----------


class TestFileToolIntegration:
    """Test that file tools respect .claraityignore via _validate_path."""

    @pytest.fixture(autouse=True)
    def _setup_tools(self, workspace):
        from src.tools.file_operations import (
            AppendToFileTool,
            EditFileTool,
            FileOperationTool,
            ReadFileTool,
            WriteFileTool,
        )

        FileOperationTool._workspace_root = workspace
        self.workspace = workspace
        self.read_tool = ReadFileTool()
        self.write_tool = WriteFileTool()
        self.edit_tool = EditFileTool()
        self.append_tool = AppendToFileTool()
        yield
        FileOperationTool._workspace_root = None

    def _create_file(self, name: str, content: str = "hello") -> Path:
        p = self.workspace / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_read_file_blocked(self, workspace):
        self._create_file("secret.env", "API_KEY=xxx")
        _write_ignore(workspace, "*.env")
        result = self.read_tool.execute(file_path="secret.env")
        assert result.status.value == "error"
        assert "Access denied" in result.error
        assert "user policy" in result.error

    def test_write_file_blocked(self, workspace):
        _write_ignore(workspace, "*.env")
        result = self.write_tool.execute(file_path="secret.env", content="bad")
        assert result.status.value == "error"
        assert "Access denied" in result.error

    def test_edit_file_blocked(self, workspace):
        self._create_file("secret.env", "old content")
        _write_ignore(workspace, "*.env")
        result = self.edit_tool.execute(
            file_path="secret.env", old_text="old", new_text="new"
        )
        assert result.status.value == "error"
        assert "Access denied" in result.error

    def test_append_file_blocked(self, workspace):
        self._create_file("secret.env", "line1")
        _write_ignore(workspace, "*.env")
        result = self.append_tool.execute(file_path="secret.env", content="line2")
        assert result.status.value == "error"
        assert "user policy" in result.error

    def test_read_file_allowed(self, workspace):
        self._create_file("app.py", "print('hi')")
        _write_ignore(workspace, "*.env")
        result = self.read_tool.execute(file_path="app.py")
        assert result.status.value == "success"

    def test_error_message_is_opaque(self, workspace):
        self._create_file("creds.key", "secret")
        _write_ignore(workspace, "*.key")
        result = self.read_tool.execute(file_path="creds.key")
        assert "user policy" in result.error
        # Must NOT leak the pattern or filename mechanism
        assert "*.key" not in result.error
        assert ".claraityignore" not in result.error


# ---------- Search Tool Integration ----------


class TestSearchToolIntegration:
    @pytest.fixture(autouse=True)
    def _setup(self, workspace):
        self.workspace = workspace

    def _create_file(self, name: str, content: str = "hello") -> Path:
        p = self.workspace / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_grep_excludes_blocked_files(self, workspace):
        from src.tools.search_tools import GrepTool

        self._create_file("app.py", "TODO: fix this")
        self._create_file("secret.env", "TODO: rotate key")
        _write_ignore(workspace, "*.env")

        tool = GrepTool()
        result = tool.execute(pattern="TODO", file_path=str(workspace))
        assert result.status.value == "success"
        assert "secret.env" not in (result.output or "")

    def test_glob_excludes_blocked_files(self, workspace):
        from src.tools.search_tools import GlobTool

        self._create_file("app.py", "code")
        self._create_file("secret.env", "key")
        _write_ignore(workspace, "*.env")

        tool = GlobTool()
        result = tool.execute(pattern="*", file_path=str(workspace))
        assert result.status.value == "success"
        assert "secret.env" not in (result.output or "")
        assert "app.py" in (result.output or "")

    def test_grep_returns_success_even_with_blocked(self, workspace):
        from src.tools.search_tools import GrepTool

        self._create_file("secret.env", "TODO: something")
        _write_ignore(workspace, "*.env")

        tool = GrepTool()
        result = tool.execute(pattern="TODO", file_path=str(workspace))
        # Should succeed (not error), just no results from blocked files
        assert result.status.value == "success"

    def test_glob_returns_success_even_with_blocked(self, workspace):
        from src.tools.search_tools import GlobTool

        self._create_file("secret.env", "key")
        _write_ignore(workspace, "*.env")

        tool = GlobTool()
        result = tool.execute(pattern="*.env", file_path=str(workspace))
        # All matches blocked, so "no files found" but still SUCCESS
        assert result.status.value == "success"


# ---------- Gitignore Integration ----------


def _write_gitignore(workspace: Path, content: str) -> None:
    (workspace / ".gitignore").write_text(content, encoding="utf-8")


class TestGitignoreIntegration:
    """filter_paths() respects .gitignore in addition to .claraityignore."""

    @pytest.fixture(autouse=True)
    def _setup(self, workspace):
        self.workspace = workspace

    def _create_file(self, name: str, content: str = "findme") -> Path:
        p = self.workspace / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_grep_excludes_gitignored_files(self, workspace):
        """Files matched by .gitignore are silently excluded from grep results."""
        from src.tools.search_tools import GrepTool

        self._create_file("app.py", "findme")
        self._create_file("data.db", "findme")
        _write_gitignore(workspace, "*.db")

        result = GrepTool().execute(
            pattern="findme",
            file_path=str(workspace),
            output_mode="files_with_matches",
        )
        assert result.status.value == "success"
        assert "app.py" in result.output
        assert "data.db" not in result.output

    def test_glob_excludes_gitignored_files(self, workspace):
        """Files matched by .gitignore are silently excluded from glob results."""
        from src.tools.search_tools import GlobTool

        self._create_file("app.py")
        self._create_file("data.db")
        _write_gitignore(workspace, "*.db")

        result = GlobTool().execute(pattern="*", file_path=str(workspace))
        assert result.status.value == "success"
        assert "app.py" in result.output
        assert "data.db" not in result.output

    def test_gitignore_directory_excluded(self, workspace):
        """Directories matched by .gitignore have their contents excluded."""
        from src.tools.search_tools import GrepTool

        self._create_file("src/main.py", "findme")
        self._create_file("dist/bundle.js", "findme")
        _write_gitignore(workspace, "dist/")

        result = GrepTool().execute(
            pattern="findme",
            file_path=str(workspace),
            output_mode="files_with_matches",
        )
        assert result.status.value == "success"
        assert "main.py" in result.output
        assert "bundle.js" not in result.output

    def test_gitignore_negation_pattern_allows_file(self, workspace):
        """Negation patterns in .gitignore re-include specific files."""
        from src.tools.search_tools import GrepTool

        self._create_file("logs/app.log", "findme")
        self._create_file("logs/important.log", "findme")
        _write_gitignore(workspace, "*.log\n!important.log")

        result = GrepTool().execute(
            pattern="findme",
            file_path=str(workspace),
            output_mode="files_with_matches",
        )
        assert result.status.value == "success"
        assert "important.log" in result.output
        assert "app.log" not in result.output

    def test_claraityignore_and_gitignore_both_applied(self, workspace):
        """Both .claraityignore and .gitignore exclusions are applied together."""
        from src.tools.search_tools import GrepTool

        self._create_file("app.py", "findme")
        self._create_file("secret.env", "findme")
        self._create_file("data.db", "findme")
        _write_gitignore(workspace, "*.db")
        _write_ignore(workspace, "*.env")

        result = GrepTool().execute(
            pattern="findme",
            file_path=str(workspace),
            output_mode="files_with_matches",
        )
        assert result.status.value == "success"
        assert "app.py" in result.output
        assert "secret.env" not in result.output
        assert "data.db" not in result.output

    def test_no_gitignore_file_still_works(self, workspace):
        """Absence of .gitignore does not cause errors — only .claraityignore applies."""
        from src.tools.search_tools import GrepTool

        self._create_file("app.py", "findme")
        _write_ignore(workspace, "*.env")

        result = GrepTool().execute(
            pattern="findme",
            file_path=str(workspace),
            output_mode="files_with_matches",
        )
        assert result.status.value == "success"
        assert "app.py" in result.output


# ---------- List Directory Integration ----------


class TestListDirectoryIntegration:
    def test_list_directory_excludes_blocked(self, workspace):
        from src.tools.file_operations import FileOperationTool, ListDirectoryTool

        FileOperationTool._workspace_root = workspace

        (workspace / "app.py").write_text("code")
        (workspace / "secret.env").write_text("key")
        _write_ignore(workspace, "*.env")

        tool = ListDirectoryTool()
        result = tool.execute(directory_path=str(workspace))
        assert result.status.value == "success"
        assert "secret.env" not in result.output
        assert "app.py" in result.output

        FileOperationTool._workspace_root = None


# ---------- Knowledge Tool Integration ----------


class TestKnowledgeToolIntegration:
    def test_query_file_blocked(self, workspace):
        from src.tools.knowledge_tools import KnowledgeQueryTool

        _write_ignore(workspace, "*.env")
        tool = KnowledgeQueryTool()
        result = tool.execute(file_path="secrets.env")
        assert result.status.value == "error"
        assert "user policy" in result.error

    def test_query_file_allowed(self, workspace):
        from src.tools.knowledge_tools import KnowledgeQueryTool

        _write_ignore(workspace, "*.env")
        tool = KnowledgeQueryTool()
        result = tool.execute(file_path="src/core/agent.py")
        # May fail (no DB) but should NOT be "user policy" error
        assert "user policy" not in (result.error or "")


# ---------- check_command ----------


class TestCheckCommand:
    def test_no_file_allows_all(self, workspace):
        assert check_command("cat anything.env") == (False, None)

    def test_blocks_cat_blocked_file(self, workspace):
        _write_ignore(workspace, "*.env")
        blocked, reason = check_command("cat .env")
        assert blocked is True
        assert "user policy" in reason

    def test_blocks_type_blocked_file(self, workspace):
        _write_ignore(workspace, "*.env")
        blocked, _reason = check_command("type secrets.env")
        assert blocked is True

    def test_blocks_head_blocked_file(self, workspace):
        _write_ignore(workspace, "credentials.json")
        blocked, _reason = check_command("head -n 10 credentials.json")
        assert blocked is True

    def test_allows_unblocked_file(self, workspace):
        _write_ignore(workspace, "*.env")
        assert check_command("cat app.py") == (False, None)

    def test_blocks_quoted_path(self, workspace):
        _write_ignore(workspace, "*.env")
        blocked, _reason = check_command('cat "my secrets.env"')
        assert blocked is True

    def test_allows_empty_patterns(self, workspace):
        _write_ignore(workspace, "")
        assert check_command("cat .env") == (False, None)

    def test_malformed_quoting_allows(self, workspace):
        _write_ignore(workspace, "*.env")
        # Malformed quoting -- shlex.split fails, should allow (not crash)
        assert check_command("echo 'unterminated") == (False, None)

    def test_opaque_error_message(self, workspace):
        _write_ignore(workspace, "*.env")
        _blocked, reason = check_command("cat .env")
        assert ".claraityignore" not in reason
        assert "*.env" not in reason
        assert ".env" not in reason


# ---------- Live Update (no cache) ----------


class TestLiveUpdate:
    def test_removing_pattern_unblocks_immediately(self, workspace):
        self._create_file(workspace, "secret.env", "key")
        _write_ignore(workspace, "*.env")
        assert is_blocked(str(workspace / "secret.env"))[0] is True

        # Remove the pattern
        _write_ignore(workspace, "# nothing blocked")
        assert is_blocked(str(workspace / "secret.env"))[0] is False

    def test_adding_pattern_blocks_immediately(self, workspace):
        self._create_file(workspace, "secret.env", "key")
        assert is_blocked(str(workspace / "secret.env"))[0] is False

        _write_ignore(workspace, "*.env")
        assert is_blocked(str(workspace / "secret.env"))[0] is True

    @staticmethod
    def _create_file(workspace: Path, name: str, content: str = "hello") -> Path:
        p = workspace / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p
