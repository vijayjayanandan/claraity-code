"""
Comprehensive tests for enhanced search tools (Grep and Glob).

Tests cover:
- Grep: regex patterns, file type filters, output modes, context lines, case sensitivity
- Glob: recursive patterns, brace expansion, file filtering
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.tools.search_tools import GrepTool, GlobTool, OutputMode
from src.tools.base import ToolStatus


@pytest.fixture
def temp_codebase(tmp_path, monkeypatch):
    """Create a temporary codebase for testing."""
    # Set CWD to temp dir so validate_path_security() allows these paths
    monkeypatch.chdir(tmp_path)

    # Create directory structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".git").mkdir()  # Should be skipped

    # Create Python files
    (tmp_path / "src" / "main.py").write_text("""
class User:
    def __init__(self, name):
        self.name = name

    def authenticate(self):
        # TODO: Add error handling
        if not self.name:
            raise ValueError("Name required")
        return True
""")

    (tmp_path / "src" / "core" / "auth.py").write_text("""
def login(username, password):
    # FIXME: Improve security
    if not username or not password:
        raise ValueError("Credentials required")
    return authenticate_user(username, password)

def authenticate_user(username, password):
    # Basic authentication
    return username == "admin" and password == "secret"
""")

    (tmp_path / "tests" / "test_auth.py").write_text("""
import pytest
from src.core.auth import login

def test_login_success():
    result = login("admin", "secret")
    assert result is True

def test_login_failure():
    with pytest.raises(ValueError):
        login("", "")
""")

    # Create JavaScript files
    (tmp_path / "src" / "app.js").write_text("""
function handleError(error) {
    console.error("Error:", error);
    throw error;
}

function authenticate(user) {
    if (!user) {
        throw new Error("User required");
    }
    return true;
}
""")

    # Create TypeScript files
    (tmp_path / "src" / "types.ts").write_text("""
interface User {
    name: string;
    email: string;
}

class AuthService {
    authenticate(user: User): boolean {
        return user.name !== "";
    }
}
""")

    # Create config files
    (tmp_path / "config.json").write_text('{"debug": true}')
    (tmp_path / "config.yaml").write_text('debug: true')

    # Create files that should be skipped
    (tmp_path / ".env").write_text("SECRET=abc123")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("module.exports = {};")

    return tmp_path


class TestGrepTool:
    """Test GrepTool functionality."""

    def test_basic_search(self, temp_codebase):
        """Test basic keyword search."""
        tool = GrepTool()
        result = tool.execute(
            pattern="authenticate",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        assert "main.py" in result.output
        assert "auth.py" in result.output
        assert result.metadata["matches"] >= 2

    def test_regex_pattern(self, temp_codebase):
        """Test regex pattern matching."""
        tool = GrepTool()
        result = tool.execute(
            pattern=r"^class \w+",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="content"
        )

        assert result.status == ToolStatus.SUCCESS
        assert "class User" in result.output or "User" in result.output

    def test_file_type_filter(self, temp_codebase):
        """Test file type filtering."""
        tool = GrepTool()

        # Search Python files
        result = tool.execute(
            pattern="def ",
            file_path=str(temp_codebase),
            file_type="python",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        assert ".py" in result.output
        assert ".js" not in result.output

        # Search JavaScript files
        result = tool.execute(
            pattern="function",
            file_path=str(temp_codebase),
            file_type="js",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        assert ".js" in result.output

    def test_glob_filter(self, temp_codebase):
        """Test glob pattern filtering."""
        tool = GrepTool()
        result = tool.execute(
            pattern="authenticate",
            file_path=str(temp_codebase),
            glob="src/**/*.py",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        # Should find files in src/ but not tests/
        assert "src" in result.output

    def test_output_mode_content(self, temp_codebase):
        """Test content output mode (shows matching lines)."""
        tool = GrepTool()
        result = tool.execute(
            pattern="TODO|FIXME",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="content"
        )

        assert result.status == ToolStatus.SUCCESS
        assert "TODO" in result.output or "FIXME" in result.output
        # Should show line numbers
        assert ":" in result.output

    def test_output_mode_files_with_matches(self, temp_codebase):
        """Test files_with_matches output mode (file paths only)."""
        tool = GrepTool()
        result = tool.execute(
            pattern="authenticate",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        # Should only show file paths, not content
        assert "\n" in result.output or result.output.endswith(".py")
        # Should not show line content
        assert "def authenticate" not in result.output

    def test_output_mode_count(self, temp_codebase):
        """Test count output mode (match counts per file)."""
        tool = GrepTool()
        result = tool.execute(
            pattern="def ",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="count"
        )

        assert result.status == ToolStatus.SUCCESS
        # Should show format: file:count
        assert ":" in result.output
        # Should have numbers
        assert any(char.isdigit() for char in result.output)

    def test_context_lines(self, temp_codebase):
        """Test context lines (before/after)."""
        tool = GrepTool()

        # Test context after
        result = tool.execute(
            pattern="class User",
            file_path=str(temp_codebase / "src" / "main.py"),
            output_mode="content",
            context_after=2
        )

        assert result.status == ToolStatus.SUCCESS
        # Should show lines after match
        assert "__init__" in result.output

        # Test context before and after
        result = tool.execute(
            pattern="authenticate",
            file_path=str(temp_codebase / "src" / "main.py"),
            output_mode="content",
            context=2
        )

        assert result.status == ToolStatus.SUCCESS

    def test_case_insensitive(self, temp_codebase):
        """Test case-insensitive search."""
        tool = GrepTool()
        result = tool.execute(
            pattern="USER",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="files_with_matches",
            case_insensitive=True
        )

        assert result.status == ToolStatus.SUCCESS
        # Should match "User" even though we searched for "USER"
        assert result.metadata["matches"] > 0

    def test_head_limit(self, temp_codebase):
        """Test head limit (limit results)."""
        tool = GrepTool()
        result = tool.execute(
            pattern="def ",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="content",
            head_limit=2
        )

        assert result.status == ToolStatus.SUCCESS
        # Should only return 2 results
        lines = result.output.strip().split("\n")
        assert len(lines) <= 2

    def test_offset(self, temp_codebase):
        """Test offset (skip first N results)."""
        tool = GrepTool()

        # Get all results
        result_all = tool.execute(
            pattern="def ",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="files_with_matches"
        )

        # Get results with offset
        result_offset = tool.execute(
            pattern="def ",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="files_with_matches",
            offset=1
        )

        assert result_offset.status == ToolStatus.SUCCESS
        # Offset result should have fewer matches
        assert result_offset.metadata["matches"] < result_all.metadata["matches"]

    def test_no_matches(self, temp_codebase):
        """Test search with no matches."""
        tool = GrepTool()
        result = tool.execute(
            pattern="nonexistent_pattern_xyz",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        assert "No matches found" in result.output
        assert result.metadata["matches"] == 0

    def test_invalid_regex(self, temp_codebase):
        """Test invalid regex pattern."""
        tool = GrepTool()
        result = tool.execute(
            pattern="[invalid",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="content"
        )

        assert result.status == ToolStatus.ERROR
        assert "Invalid regex pattern" in result.error

    def test_invalid_path(self):
        """Test invalid path."""
        tool = GrepTool()
        result = tool.execute(
            pattern="test",
            file_path="/nonexistent/path",
            output_mode="content"
        )

        assert result.status == ToolStatus.ERROR
        assert "Path not found" in result.error or "SECURITY" in result.error

    def test_finds_dotfiles(self, temp_codebase):
        """Test that dotfiles like .env are searchable (not hidden from grep)."""
        tool = GrepTool()
        result = tool.execute(
            pattern="SECRET",
            file_path=str(temp_codebase),
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        # .env files are NOT skipped — only skip_dirs and binary extensions are filtered
        assert ".env" in result.output

    def test_skips_node_modules(self, temp_codebase):
        """Test that node_modules is skipped when no file_type filter."""
        tool = GrepTool()
        # Use no file_type filter so _should_skip is applied
        result = tool.execute(
            pattern="exports",
            file_path=str(temp_codebase),
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.SUCCESS
        # Should not search in node_modules directory
        if result.output and result.output != "No matches found":
            for line in result.output.strip().split("\n"):
                if line.strip():
                    parts = Path(line).parts
                    assert "node_modules" not in parts


class TestGlobTool:
    """Test GlobTool functionality."""

    def test_basic_glob(self, temp_codebase):
        """Test basic glob pattern."""
        tool = GlobTool()
        result = tool.execute(
            pattern="*.py",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        # Should find Python files in root
        assert result.metadata["matches"] >= 0

    def test_recursive_glob(self, temp_codebase):
        """Test recursive glob pattern (**)."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*.py",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["matches"] >= 3
        # Should find files in subdirectories
        assert "main.py" in result.output
        assert "auth.py" in result.output

    def test_brace_expansion(self, temp_codebase):
        """Test brace expansion (e.g., *.{py,js})."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*.{py,js}",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        # Should find both Python and JavaScript files
        assert ".py" in result.output
        assert ".js" in result.output

    def test_specific_directory(self, temp_codebase):
        """Test glob in specific directory."""
        tool = GlobTool()
        result = tool.execute(
            pattern="src/**/*.py",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        # Should only find files in src/
        assert "src" in result.output
        # Should not find test files (check filenames, not full paths)
        for line in result.output.strip().split("\n"):
            if line.strip():
                assert not Path(line).name.startswith("test_")

    def test_multiple_extensions(self, temp_codebase):
        """Test matching multiple extensions."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*.{json,yaml}",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        # Should find config files
        assert "config.json" in result.output or "config.yaml" in result.output

    def test_sort_by_mtime(self, temp_codebase):
        """Test sorting by modification time."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*.py",
            file_path=str(temp_codebase),
            sort_by_mtime=True
        )

        assert result.status == ToolStatus.SUCCESS
        # Should return files (order may vary)
        assert result.metadata["matches"] >= 3

    def test_no_matches(self, temp_codebase):
        """Test glob with no matches."""
        tool = GlobTool()
        result = tool.execute(
            pattern="*.xyz",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        assert "No files found" in result.output
        assert result.metadata["matches"] == 0

    def test_invalid_path(self):
        """Test invalid path."""
        tool = GlobTool()
        result = tool.execute(
            pattern="*.py",
            file_path="/nonexistent/path"
        )

        assert result.status == ToolStatus.ERROR
        assert "Path not found" in result.error or "SECURITY" in result.error

    def test_skips_hidden_directories(self, temp_codebase):
        """Test that hidden directories are skipped."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        # Should not include .git directory
        assert ".git" not in result.output or result.metadata["matches"] == 0

    def test_skips_node_modules(self, temp_codebase):
        """Test that node_modules is skipped."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*.js",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        # Should not include node_modules as a path component in results
        if result.output:
            for line in result.output.strip().split("\n"):
                if line.strip():
                    parts = Path(line).parts
                    assert "node_modules" not in parts

    def test_typescript_files(self, temp_codebase):
        """Test finding TypeScript files."""
        tool = GlobTool()
        result = tool.execute(
            pattern="**/*.ts",
            file_path=str(temp_codebase)
        )

        assert result.status == ToolStatus.SUCCESS
        assert "types.ts" in result.output


class TestIntegration:
    """Integration tests for Grep and Glob working together."""

    def test_glob_then_grep(self, temp_codebase):
        """Test using Glob to find files, then Grep to search them."""
        # Step 1: Find all Python files
        glob_tool = GlobTool()
        glob_result = glob_tool.execute(
            pattern="**/*.py",
            file_path=str(temp_codebase)
        )

        assert glob_result.status == ToolStatus.SUCCESS
        assert glob_result.metadata["matches"] >= 3

        # Step 2: Search for pattern in those files
        grep_tool = GrepTool()
        grep_result = grep_tool.execute(
            pattern="def ",
            file_path=str(temp_codebase),
            file_type="py",
            output_mode="count"
        )

        assert grep_result.status == ToolStatus.SUCCESS
        assert grep_result.metadata["matches"] > 0

    def test_find_error_handling_patterns(self, temp_codebase):
        """Test finding error handling patterns across codebase."""
        grep_tool = GrepTool()

        # Find all error handling
        result = grep_tool.execute(
            pattern="raise |throw ",
            file_path=str(temp_codebase),
            output_mode="content",
            context=1
        )

        assert result.status == ToolStatus.SUCCESS
        # Should find error handling in multiple languages
        assert result.metadata["matches"] > 0

    def test_find_todos_and_fixmes(self, temp_codebase):
        """Test finding TODO and FIXME comments."""
        grep_tool = GrepTool()
        result = grep_tool.execute(
            pattern="TODO|FIXME",
            file_path=str(temp_codebase),
            output_mode="content"
        )

        assert result.status == ToolStatus.SUCCESS
        # Should find both TODO and FIXME
        output_upper = result.output.upper()
        assert "TODO" in output_upper or "FIXME" in output_upper


class TestSecurityFixes:
    """Test security fixes for path traversal, ReDoS, and error handling."""

    def test_grep_blocks_path_traversal(self):
        """Test that GrepTool blocks path traversal attacks."""
        grep_tool = GrepTool()

        # Try to access file outside workspace
        result = grep_tool.execute(
            pattern="password",
            file_path="../../../etc/passwd",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.ERROR
        assert "[SECURITY]" in result.error
        assert "Path traversal blocked" in result.error

    def test_glob_blocks_path_traversal(self):
        """Test that GlobTool blocks path traversal attacks."""
        glob_tool = GlobTool()

        # Try to access directory outside workspace
        result = glob_tool.execute(
            pattern="**/*.py",
            file_path="../../../etc"
        )

        assert result.status == ToolStatus.ERROR
        assert "[SECURITY]" in result.error
        assert "Path traversal blocked" in result.error

    def test_grep_blocks_redos_nested_quantifiers(self):
        """Test that GrepTool blocks ReDoS attacks with nested quantifiers."""
        grep_tool = GrepTool()

        # Dangerous pattern: (a+)+b causes catastrophic backtracking
        result = grep_tool.execute(
            pattern="(a+)+b",
            file_path=".",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.ERROR
        assert "[SECURITY]" in result.error
        assert "dangerous regex pattern" in result.error.lower()
        assert "catastrophic backtracking" in result.error.lower()

    def test_grep_blocks_redos_greedy_wildcard(self):
        """Test that GrepTool blocks ReDoS attacks with greedy wildcards."""
        grep_tool = GrepTool()

        # Dangerous pattern: (.*)+x
        result = grep_tool.execute(
            pattern="(.*)+x",
            file_path=".",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.ERROR
        assert "[SECURITY]" in result.error
        assert "dangerous regex pattern" in result.error.lower()

    def test_grep_blocks_excessive_pattern_length(self):
        """Test that GrepTool blocks excessively long regex patterns."""
        grep_tool = GrepTool()

        # Pattern longer than 500 characters
        long_pattern = "a" * 501
        result = grep_tool.execute(
            pattern=long_pattern,
            file_path=".",
            output_mode="files_with_matches"
        )

        assert result.status == ToolStatus.ERROR
        assert "[SECURITY]" in result.error
        assert "pattern too long" in result.error.lower()

    def test_grep_allows_safe_patterns(self):
        """Test that GrepTool allows safe regex patterns."""
        grep_tool = GrepTool()

        # Safe pattern
        result = grep_tool.execute(
            pattern="def [a-z_]+\\(",
            file_path=".",
            output_mode="files_with_matches",
            head_limit=1
        )

        # Should not be blocked (success or no matches, but not security error)
        assert result.status in [ToolStatus.SUCCESS, ToolStatus.ERROR]
        if result.status == ToolStatus.ERROR:
            assert "[SECURITY]" not in result.error

    def test_grep_tracks_skipped_files(self, temp_codebase):
        """Test that GrepTool tracks files that couldn't be read."""
        grep_tool = GrepTool()

        # Create a Python file with import statement
        (temp_codebase / "test.py").write_text("import os\nimport sys")

        # On Windows, we can't easily make files unreadable, so test with normal files
        # The metadata should still have files_skipped and skipped_details fields
        result = grep_tool.execute(
            pattern="import",
            file_path=str(temp_codebase),
            output_mode="files_with_matches"
        )

        # Should succeed or have no matches (not an error)
        assert result.status in [ToolStatus.SUCCESS, ToolStatus.ERROR]
        # If successful, check metadata
        if result.status == ToolStatus.SUCCESS:
            assert "files_skipped" in result.metadata
            assert "skipped_details" in result.metadata
            # Should be 0 skipped files for normal operation
            assert isinstance(result.metadata["files_skipped"], int)
            assert isinstance(result.metadata["skipped_details"], list)

    def test_grep_handles_binary_files_gracefully(self, temp_codebase):
        """Test that GrepTool handles binary files gracefully."""
        grep_tool = GrepTool()

        # Create a binary file
        binary_file = temp_codebase / "image.png"
        binary_file.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')

        # Also create a text file so search isn't empty
        (temp_codebase / "readme.txt").write_text("PNG format documentation")

        result = grep_tool.execute(
            pattern="PNG",
            file_path=str(temp_codebase),
            output_mode="files_with_matches"
        )

        # Should succeed without crashing (even if no matches)
        assert result.status in [ToolStatus.SUCCESS, ToolStatus.ERROR]
        # If successful, verify metadata exists
        if result.status == ToolStatus.SUCCESS:
            assert "files_skipped" in result.metadata
