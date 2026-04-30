"""Tests for search tools (GrepTool, GlobTool)."""

import os
import pytest
from pathlib import Path
from src.tools import GrepTool, GlobTool
from src.tools.base import ToolStatus
from src.tools.search_tools import validate_path_security, validate_regex_safety


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def allow_test_workspace(tmp_path, monkeypatch):
    """Set CWD to tmp_path so validate_path_security allows test file access."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def sample_project(tmp_path):
    """Create a small project tree for search tests."""
    # Python files
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "import os\nimport sys\n\ndef main():\n    print('hello')\n\ndef helper():\n    return 42\n"
    )
    (src / "utils.py").write_text(
        "import os\n\ndef parse(data):\n    return data.strip()\n\ndef parse_int(data):\n    return int(data)\n"
    )

    # JS file
    (src / "app.js").write_text(
        "const express = require('express');\nconst app = express();\napp.listen(3000);\n"
    )

    # Nested directory
    deep = src / "sub"
    deep.mkdir()
    (deep / "nested.py").write_text("# nested\nvalue = 'nested_value'\n")

    # Config file at root
    (tmp_path / "config.yaml").write_text("key: value\nport: 8080\n")

    return tmp_path


@pytest.fixture
def grep():
    return GrepTool()


@pytest.fixture
def glob_tool():
    return GlobTool()


# ===========================================================================
# GrepTool Tests
# ===========================================================================

class TestGrepToolBasic:
    """Basic grep functionality."""

    def test_search_single_file(self, grep, sample_project):
        result = grep.execute(
            pattern="def main",
            file_path=str(sample_project / "src" / "main.py"),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "def main" in result.output

    def test_search_directory(self, grep, sample_project):
        result = grep.execute(
            pattern="import os",
            file_path=str(sample_project / "src"),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "main.py" in result.output
        assert "utils.py" in result.output

    def test_no_matches(self, grep, sample_project):
        result = grep.execute(
            pattern="nonexistent_string_xyz",
            file_path=str(sample_project / "src"),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "No matches found" in result.output

    def test_nonexistent_path(self, grep, tmp_path):
        result = grep.execute(
            pattern="test",
            file_path=str(tmp_path / "does_not_exist"),
        )
        assert result.status == ToolStatus.ERROR

    def test_invalid_regex(self, grep, sample_project):
        result = grep.execute(
            pattern="[invalid",
            file_path=str(sample_project / "src" / "main.py"),
        )
        assert result.status == ToolStatus.ERROR
        assert "Invalid regex" in result.error

    def test_empty_directory(self, grep, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = grep.execute(pattern="test", file_path=str(empty))
        assert result.status == ToolStatus.SUCCESS
        assert "No files found" in result.output

    def test_rejects_old_path_parameter(self, grep, sample_project):
        """The 'path' kwarg was renamed to 'file_path'. Passing 'path' should error."""
        result = grep.execute(
            pattern="import",
            path=str(sample_project / "src"),
        )
        assert result.status == ToolStatus.ERROR
        assert "file_path" in result.error


class TestGrepToolOutputModes:
    """Test all three output modes."""

    def test_content_mode_shows_lines(self, grep, sample_project):
        result = grep.execute(
            pattern="def ",
            file_path=str(sample_project / "src" / "main.py"),
            output_mode="content",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "def main" in result.output
        assert "def helper" in result.output

    def test_files_with_matches_mode(self, grep, sample_project):
        result = grep.execute(
            pattern="import os",
            file_path=str(sample_project / "src"),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        lines = result.output.strip().split("\n")
        # Should list file paths, not content
        assert any("main.py" in l for l in lines)
        assert any("utils.py" in l for l in lines)
        # Should NOT contain the actual line content
        assert "import" not in result.output or all("import" not in l or ".py" in l for l in lines)

    def test_count_mode_returns_actual_count(self, grep, sample_project):
        """COUNT mode returns actual match count per file."""
        result = grep.execute(
            pattern="import",
            file_path=str(sample_project / "src" / "main.py"),
            output_mode="count",
        )
        assert result.status == ToolStatus.SUCCESS
        # main.py has 2 'import' lines
        assert result.metadata["matches"] == 2

    def test_count_mode_multiple_files(self, grep, sample_project):
        """COUNT mode across directory - each file reports 1."""
        result = grep.execute(
            pattern="import os",
            file_path=str(sample_project / "src"),
            output_mode="count",
        )
        assert result.status == ToolStatus.SUCCESS
        # Both main.py and utils.py have "import os"
        assert result.metadata["matches"] >= 2  # sum of per-file counts (all 1s)

    def test_invalid_output_mode(self, grep, sample_project):
        result = grep.execute(
            pattern="test",
            file_path=str(sample_project / "src"),
            output_mode="invalid_mode",
        )
        assert result.status == ToolStatus.ERROR

    def test_auto_detect_file_content_mode(self, grep, sample_project):
        """When targeting a single file with no output_mode, should default to content."""
        result = grep.execute(
            pattern="def main",
            file_path=str(sample_project / "src" / "main.py"),
        )
        assert result.status == ToolStatus.SUCCESS
        # Content mode includes line content
        assert "def main" in result.output

    def test_auto_detect_broad_dir_files_mode(self, grep, sample_project):
        """Broad directory search (no glob/file_type) defaults to files_with_matches."""
        result = grep.execute(
            pattern="import os",
            file_path=str(sample_project / "src"),
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["output_mode"] == "files_with_matches"
        # Hint should be appended to guide the LLM
        assert "output_mode='content'" in result.output

    def test_auto_detect_narrowed_dir_content_mode(self, grep, sample_project):
        """Directory search narrowed by file_type defaults to content mode."""
        result = grep.execute(
            pattern="import os",
            file_path=str(sample_project / "src"),
            file_type="py",
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["output_mode"] == "content"
        assert "import os" in result.output

    def test_auto_detect_narrowed_dir_glob_content_mode(self, grep, sample_project):
        """Directory search narrowed by glob defaults to content mode."""
        result = grep.execute(
            pattern="import os",
            file_path=str(sample_project / "src"),
            glob="*.py",
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["output_mode"] == "content"
        assert "import os" in result.output


class TestGrepToolFilters:
    """File type and glob filtering."""

    def test_file_type_python(self, grep, sample_project):
        result = grep.execute(
            pattern="import",
            file_path=str(sample_project / "src"),
            file_type="py",
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "main.py" in result.output
        assert "app.js" not in result.output

    def test_file_type_js(self, grep, sample_project):
        result = grep.execute(
            pattern="express",
            file_path=str(sample_project / "src"),
            file_type="js",
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "app.js" in result.output

    def test_glob_filter(self, grep, sample_project):
        result = grep.execute(
            pattern="import",
            file_path=str(sample_project / "src"),
            glob="*.py",
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "app.js" not in result.output


class TestGrepToolContextLines:
    """Context lines (-A, -B, -C)."""

    def test_context_after(self, grep, sample_project):
        result = grep.execute(
            pattern="def main",
            file_path=str(sample_project / "src" / "main.py"),
            output_mode="content",
            context_after=1,
        )
        assert result.status == ToolStatus.SUCCESS
        # Should include the line after "def main():"
        assert "print" in result.output

    def test_context_before(self, grep, sample_project):
        result = grep.execute(
            pattern="def helper",
            file_path=str(sample_project / "src" / "main.py"),
            output_mode="content",
            context_before=1,
        )
        assert result.status == ToolStatus.SUCCESS
        # Line before "def helper" is empty line after print('hello')
        lines = result.output.strip().split("\n")
        assert len(lines) >= 2  # At least the match + 1 context line

    def test_context_symmetric(self, grep, sample_project):
        result = grep.execute(
            pattern="def main",
            file_path=str(sample_project / "src" / "main.py"),
            output_mode="content",
            context=1,
        )
        assert result.status == ToolStatus.SUCCESS
        lines = result.output.strip().split("\n")
        assert len(lines) >= 2  # match + at least 1 context line


class TestGrepToolOptions:
    """Case sensitivity, line numbers, head_limit, offset."""

    def test_case_insensitive(self, grep, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello\nhello\nHELLO\n")
        result = grep.execute(
            pattern="hello",
            file_path=str(f),
            output_mode="content",
            case_insensitive=True,
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["matches"] == 3

    def test_case_sensitive_default(self, grep, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello\nhello\nHELLO\n")
        result = grep.execute(
            pattern="hello",
            file_path=str(f),
            output_mode="content",
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["matches"] == 1

    def test_line_numbers_in_output(self, grep, sample_project):
        result = grep.execute(
            pattern="def main",
            file_path=str(sample_project / "src" / "main.py"),
            output_mode="content",
            line_numbers=True,
        )
        assert result.status == ToolStatus.SUCCESS
        # Format: file:line_num: content
        assert ":4:" in result.output  # "def main" is line 4

    def test_head_limit(self, grep, tmp_path):
        f = tmp_path / "many.txt"
        f.write_text("\n".join(f"match_{i}" for i in range(100)))
        result = grep.execute(
            pattern="match_",
            file_path=str(f),
            output_mode="content",
            head_limit=5,
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["matches"] == 5

    def test_offset(self, grep, tmp_path):
        f = tmp_path / "many.txt"
        f.write_text("\n".join(f"match_{i}" for i in range(10)))
        result = grep.execute(
            pattern="match_",
            file_path=str(f),
            output_mode="content",
            offset=5,
        )
        assert result.status == ToolStatus.SUCCESS
        assert "match_0" not in result.output
        assert "match_5" in result.output

    def test_default_head_limit_caps_results(self, grep, tmp_path):
        """Default head_limit=250 prevents context window flooding."""
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line_{i}" for i in range(500)))
        result = grep.execute(
            pattern="line_",
            file_path=str(f),
            output_mode="content",
        )
        assert result.status == ToolStatus.SUCCESS
        # Default cap of 250 applied
        assert result.metadata["matches"] == 250

    def test_explicit_head_limit_overrides_default(self, grep, tmp_path):
        """Explicit head_limit=0 disables the default cap."""
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line_{i}" for i in range(500)))
        result = grep.execute(
            pattern="line_",
            file_path=str(f),
            output_mode="content",
            head_limit=0,
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["matches"] == 500


class TestGrepToolMultiline:
    """Multiline mode tests."""

    def test_multiline_single_line_pattern_works(self, grep, tmp_path):
        """Multiline with a pattern that doesn't span lines should still work."""
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    return 42\n")
        result = grep.execute(
            pattern="def foo",
            file_path=str(f),
            output_mode="content",
            multiline=True,
        )
        assert result.status == ToolStatus.SUCCESS
        assert "def foo" in result.output

    def test_multiline_cross_line_pattern_works(self, grep, tmp_path):
        """Cross-line patterns match when multiline=True."""
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    return 42\n\ndef bar():\n    return 99\n")
        result = grep.execute(
            pattern=r"def foo.*return",
            file_path=str(f),
            output_mode="content",
            multiline=True,
        )
        assert result.status == ToolStatus.SUCCESS
        assert "def foo" in result.output
        assert "return 42" in result.output

    def test_multiline_count_mode(self, grep, tmp_path):
        """COUNT mode with multiline should count matched lines."""
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    return 42\n\ndef bar():\n    return 99\n")
        result = grep.execute(
            pattern=r"def foo.*return",
            file_path=str(f),
            output_mode="count",
            multiline=True,
        )
        assert result.status == ToolStatus.SUCCESS
        # Match spans lines 1-2 (def foo, return 42)
        assert result.metadata["matches"] >= 2

    def test_multiline_with_context(self, grep, tmp_path):
        """Multiline match with context lines."""
        f = tmp_path / "test.py"
        f.write_text("# header\ndef foo():\n    return 42\n# footer\n")
        result = grep.execute(
            pattern=r"def foo.*return",
            file_path=str(f),
            output_mode="content",
            multiline=True,
            context=1,
        )
        assert result.status == ToolStatus.SUCCESS
        # Should include context: header before, footer after
        assert "header" in result.output
        assert "footer" in result.output


class TestGrepToolSkipping:
    """File skipping behavior."""

    def test_skips_oversized_files(self, grep, tmp_path):
        """Files over MAX_FILE_SIZE_BYTES should be skipped."""
        from src.tools.search_tools import GrepTool
        original = GrepTool.MAX_FILE_SIZE_BYTES
        try:
            # Set a tiny limit for testing
            GrepTool.MAX_FILE_SIZE_BYTES = 100
            big = tmp_path / "big.txt"
            big.write_text("findme\n" * 50)  # > 100 bytes
            small = tmp_path / "small.txt"
            small.write_text("findme\n")
            result = grep.execute(
                pattern="findme",
                file_path=str(tmp_path),
                output_mode="files_with_matches",
            )
            assert result.status == ToolStatus.SUCCESS
            assert "small.txt" in result.output
            assert "big.txt" not in result.output
            assert result.metadata["files_skipped"] == 1
        finally:
            GrepTool.MAX_FILE_SIZE_BYTES = original

    def test_skips_binary_extensions(self, grep, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"match_this")
        (tmp_path / "text.txt").write_text("match_this")
        result = grep.execute(
            pattern="match_this",
            file_path=str(tmp_path),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "text.txt" in result.output
        assert "data.bin" not in result.output

    def test_skips_node_modules(self, grep, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("findme")
        (tmp_path / "app.js").write_text("findme")
        result = grep.execute(
            pattern="findme",
            file_path=str(tmp_path),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "app.js" in result.output
        # Check no file from node_modules directory appears
        result_lines = result.output.strip().split("\n")
        assert not any("index.js" in line for line in result_lines)

    def test_skips_explicit_skip_dirs(self, grep, tmp_path):
        """Only explicit skip_dirs are excluded; generic dot-dirs are searchable."""
        # .git IS in skip_dirs -- files inside should be excluded
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("findme")
        # .claraity is NOT in skip_dirs -- should be searchable
        claraity_dir = tmp_path / ".claraity"
        claraity_dir.mkdir()
        (claraity_dir / "notes.txt").write_text("findme")
        (tmp_path / "visible.txt").write_text("findme")
        result = grep.execute(
            pattern="findme",
            file_path=str(tmp_path),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "visible.txt" in result.output
        assert "notes.txt" in result.output
        assert "config" not in result.output

    def test_files_with_matches_includes_count(self, grep, tmp_path):
        """files_with_matches output includes per-file match count."""
        (tmp_path / "a.txt").write_text("findme\nfindme\n")
        (tmp_path / "b.txt").write_text("findme\n")
        result = grep.execute(
            pattern="findme",
            file_path=str(tmp_path),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        lines = result.output.strip().split("\n")
        assert any("a.txt" in l and "2 matches" in l for l in lines)
        assert any("b.txt" in l and "1 match" in l for l in lines)

    def test_skips_binary_file_with_text_extension(self, grep, tmp_path):
        """A .txt file containing null bytes is detected as binary and skipped."""
        (tmp_path / "output.txt").write_bytes(b"some text\x00more text")
        (tmp_path / "clean.txt").write_text("some text more text")
        result = grep.execute(
            pattern="some text",
            file_path=str(tmp_path),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "clean.txt" in result.output
        assert "output.txt" not in result.output
        assert result.metadata["files_skipped"] == 1

    def test_dotfiles_are_searchable(self, grep, tmp_path):
        """.env and .gitignore should be searchable — only files INSIDE hidden dirs are skipped."""
        (tmp_path / ".env").write_text("SECRET=findme")
        (tmp_path / ".gitignore").write_text("*.pyc\nfindme")
        result = grep.execute(
            pattern="findme",
            file_path=str(tmp_path),
            output_mode="files_with_matches",
        )
        assert result.status == ToolStatus.SUCCESS
        assert ".env" in result.output
        assert ".gitignore" in result.output


# ===========================================================================
# Output Guard Tests
# ===========================================================================

class TestGrepToolOutputGuards:
    """Per-line character cap and total output character budget."""

    def test_long_line_is_truncated(self, grep, tmp_path):
        """Lines exceeding MAX_LINE_CHARS are truncated with a [...+N chars] marker."""
        long_line = "x" * 3000
        (tmp_path / "wide.txt").write_text(f"before\n{long_line}\nafter\n")
        result = grep.execute(
            pattern="x",
            file_path=str(tmp_path / "wide.txt"),
            output_mode="content",
        )
        assert result.status == ToolStatus.SUCCESS
        assert "[...+" in result.output
        # The matching line must be well under the original 3000 chars
        matching_line = next(l for l in result.output.splitlines() if "x" * 10 in l)
        assert len(matching_line) < 2200  # 2000 cap + filepath + line num overhead

    def test_output_budget_triggers_truncation(self, grep, tmp_path):
        """When MAX_OUTPUT_CHARS is exceeded with head_limit=0, output_truncated=True."""
        from src.tools.search_tools import GrepTool
        original = GrepTool.MAX_OUTPUT_CHARS
        try:
            GrepTool.MAX_OUTPUT_CHARS = 500
            for i in range(20):
                (tmp_path / f"file_{i}.txt").write_text("findme " * 50)
            result = grep.execute(
                pattern="findme",
                file_path=str(tmp_path),
                output_mode="content",
                head_limit=0,
            )
            assert result.status == ToolStatus.SUCCESS
            assert result.metadata["output_truncated"] is True
            assert "Stopped" in result.output
        finally:
            GrepTool.MAX_OUTPUT_CHARS = original

    def test_output_within_budget_not_truncated(self, grep, tmp_path):
        """Small results set output_truncated=False."""
        (tmp_path / "small.txt").write_text("findme\n" * 5)
        result = grep.execute(
            pattern="findme",
            file_path=str(tmp_path / "small.txt"),
            output_mode="content",
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata.get("output_truncated") is False


# ===========================================================================
# GlobTool Tests
# ===========================================================================

class TestGlobToolBasic:
    """Basic glob functionality."""

    def test_glob_py_files(self, glob_tool, sample_project):
        result = glob_tool.execute(
            pattern="**/*.py",
            file_path=str(sample_project),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "main.py" in result.output
        assert "utils.py" in result.output
        assert "nested.py" in result.output

    def test_glob_js_files(self, glob_tool, sample_project):
        result = glob_tool.execute(
            pattern="**/*.js",
            file_path=str(sample_project),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "app.js" in result.output
        assert "main.py" not in result.output

    def test_glob_no_matches(self, glob_tool, sample_project):
        result = glob_tool.execute(
            pattern="**/*.rs",
            file_path=str(sample_project),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "No files found" in result.output

    def test_glob_nonexistent_path(self, glob_tool, tmp_path):
        result = glob_tool.execute(
            pattern="*.py",
            file_path=str(tmp_path / "nonexistent"),
        )
        assert result.status == ToolStatus.ERROR

    def test_rejects_old_path_parameter(self, glob_tool, sample_project):
        result = glob_tool.execute(
            pattern="*.py",
            path=str(sample_project),
        )
        assert result.status == ToolStatus.ERROR
        assert "file_path" in result.error


class TestGlobToolBraceExpansion:
    """Brace expansion: *.{py,js}"""

    def test_brace_expansion_two(self, glob_tool, sample_project):
        result = glob_tool.execute(
            pattern="**/*.{py,js}",
            file_path=str(sample_project),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "main.py" in result.output
        assert "app.js" in result.output

    def test_brace_expansion_no_braces(self, glob_tool, sample_project):
        result = glob_tool.execute(
            pattern="**/*.py",
            file_path=str(sample_project),
        )
        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["matches"] >= 3  # main.py, utils.py, nested.py

    def test_brace_expansion_single(self, glob_tool, sample_project):
        """Single item in braces should still work."""
        result = glob_tool.execute(
            pattern="**/*.{yaml}",
            file_path=str(sample_project),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "config.yaml" in result.output


class TestGlobToolSorting:
    """Sorting behavior."""

    def test_sort_by_mtime(self, glob_tool, tmp_path):
        import time
        (tmp_path / "old.txt").write_text("old")
        time.sleep(0.1)
        (tmp_path / "new.txt").write_text("new")
        result = glob_tool.execute(
            pattern="*.txt",
            file_path=str(tmp_path),
            sort_by_mtime=True,
        )
        assert result.status == ToolStatus.SUCCESS
        lines = result.output.strip().split("\n")
        # Newest first
        assert "new.txt" in lines[0]
        assert "old.txt" in lines[1]

    def test_sort_alphabetical(self, glob_tool, tmp_path):
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "a.txt").write_text("a")
        result = glob_tool.execute(
            pattern="*.txt",
            file_path=str(tmp_path),
            sort_by_mtime=False,
        )
        assert result.status == ToolStatus.SUCCESS
        lines = result.output.strip().split("\n")
        assert "a.txt" in lines[0]
        assert "b.txt" in lines[1]


class TestGlobToolSkipping:
    """File skipping - same rules as GrepTool."""

    def test_skips_hidden_directories(self, glob_tool, tmp_path):
        hidden = tmp_path / ".git"
        hidden.mkdir()
        (hidden / "config").write_text("gitconfig")
        (tmp_path / "readme.txt").write_text("hello")
        result = glob_tool.execute(pattern="**/*", file_path=str(tmp_path))
        assert result.status == ToolStatus.SUCCESS
        assert ".git" not in result.output

    def test_skips_pycache(self, glob_tool, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-311.pyc").write_bytes(b"\x00")
        (tmp_path / "mod.py").write_text("code")
        result = glob_tool.execute(pattern="**/*", file_path=str(tmp_path))
        assert result.status == ToolStatus.SUCCESS
        assert "__pycache__" not in result.output

    def test_does_not_filter_binary_extensions(self, glob_tool, tmp_path):
        """GlobTool matches by name only — binary extensions are NOT filtered.
        Use a specific pattern (e.g. **/*.py) to exclude unwanted types."""
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "code.py").write_text("code")
        result = glob_tool.execute(pattern="**/*", file_path=str(tmp_path))
        assert result.status == ToolStatus.SUCCESS
        assert "image.png" in result.output
        assert "code.py" in result.output


# ===========================================================================
# Security Tests
# ===========================================================================

class TestPathSecurity:
    """Path traversal protection."""

    def test_blocks_path_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="SECURITY"):
            validate_path_security("../../../etc/passwd", workspace_root=tmp_path)

    def test_allows_workspace_path(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("ok")
        result = validate_path_security(str(f), workspace_root=tmp_path)
        assert result == f.resolve()

    def test_allows_outside_when_flag_set(self, tmp_path):
        # Should not raise even though path is outside workspace
        result = validate_path_security(
            str(tmp_path.parent / "other"),
            workspace_root=tmp_path,
            allow_files_outside_workspace=True,
        )
        assert result is not None


class TestRegexSafety:
    """ReDoS protection."""

    def test_blocks_consecutive_quantifiers(self):
        with pytest.raises(ValueError, match="SECURITY"):
            validate_regex_safety("a++")

    def test_blocks_dot_star_plus(self):
        with pytest.raises(ValueError, match="SECURITY"):
            validate_regex_safety("(.*)+")

    def test_blocks_dot_plus_plus(self):
        with pytest.raises(ValueError, match="SECURITY"):
            validate_regex_safety("(.+)+")

    def test_allows_normal_patterns(self):
        # Should not raise
        validate_regex_safety(r"def \w+\(")
        validate_regex_safety(r"import\s+os")
        validate_regex_safety(r"TODO|FIXME|HACK")

    def test_blocks_long_patterns(self):
        with pytest.raises(ValueError, match="SECURITY"):
            validate_regex_safety("a" * 501)

    def test_catches_single_char_nested_quantifier(self):
        """(a+)+ IS caught by the (.+)+ check since . matches 'a'."""
        with pytest.raises(ValueError, match="SECURITY"):
            validate_regex_safety("(a+)+")

    def test_false_negative_multi_char_nested_quantifier(self):
        r"""BUG: (\d+)+ is a ReDoS pattern but passes validation.

        The check regex \(.\+\)\+ requires exactly 1 char before +
        inside the group. \d is 2 chars, so it doesn't match.
        Same issue for ([a-z]+)+, (\w+\s+)+, etc.
        """
        # These SHOULD raise but currently don't
        try:
            validate_regex_safety(r"(\d+)+")
            caught = False
        except ValueError:
            caught = True
        # BUG: not caught. When fixed, change to: assert caught is True
        assert caught is False


# ===========================================================================
# EditFileTool multi-replace test (supplements test_file_operations.py)
# ===========================================================================

class TestEditFileToolUniqueness:
    """EditFileTool requires unique match unless replace_all=True."""

    def _make_tool(self, tmp_path):
        from src.tools import EditFileTool
        from src.tools.file_operations import FileOperationTool
        FileOperationTool._workspace_roots = [tmp_path]
        return EditFileTool()

    def _cleanup(self):
        from src.tools.file_operations import FileOperationTool
        FileOperationTool._workspace_roots = None

    def test_rejects_non_unique_match(self, tmp_path):
        """Multiple occurrences without replace_all should error."""
        tool = self._make_tool(tmp_path)
        try:
            f = tmp_path / "multi.py"
            f.write_text("x = 1\ny = 1\nz = 1\n")

            result = tool.execute(file_path=str(f), old_text="1", new_text="2")
            assert result.status == ToolStatus.ERROR
            assert "3 locations" in result.error
            # File should be unchanged
            assert f.read_text() == "x = 1\ny = 1\nz = 1\n"
        finally:
            self._cleanup()

    def test_replace_all_replaces_all(self, tmp_path):
        """replace_all=True should replace every occurrence."""
        tool = self._make_tool(tmp_path)
        try:
            f = tmp_path / "multi.py"
            f.write_text("x = 1\ny = 1\nz = 1\n")

            result = tool.execute(
                file_path=str(f), old_text="1", new_text="2", replace_all=True,
            )
            assert result.status == ToolStatus.SUCCESS
            assert f.read_text() == "x = 2\ny = 2\nz = 2\n"
            assert result.metadata["replacements"] == 3
        finally:
            self._cleanup()

    def test_single_occurrence_works(self, tmp_path):
        """Single occurrence replacement should always work."""
        tool = self._make_tool(tmp_path)
        try:
            f = tmp_path / "single.py"
            f.write_text("x = 1\ny = 2\nz = 3\n")

            result = tool.execute(file_path=str(f), old_text="y = 2", new_text="y = 99")
            assert result.status == ToolStatus.SUCCESS
            assert f.read_text() == "x = 1\ny = 99\nz = 3\n"
            assert result.metadata["replacements"] == 1
        finally:
            self._cleanup()
