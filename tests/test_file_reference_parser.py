"""Tests for file reference parser."""

import pytest
from pathlib import Path
import tempfile
import sys

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.file_reference_parser import FileReferenceParser, FileReference


class TestFileReferenceParser:
    """Test the FileReferenceParser class."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test files
            (tmpdir / "test.py").write_text("print('hello world')\n")
            (tmpdir / "main.py").write_text("def main():\n    pass\n")

            # Create subdirectory with file
            subdir = tmpdir / "utils"
            subdir.mkdir()
            (subdir / "helpers.py").write_text("def helper():\n    return 42\n")

            # Create larger file
            large_content = "\n".join([f"line {i}" for i in range(1, 101)])
            (tmpdir / "large.txt").write_text(large_content)

            yield tmpdir

    @pytest.fixture
    def parser(self, temp_dir):
        """Create FileReferenceParser with temp directory as base."""
        return FileReferenceParser(base_dir=temp_dir, max_file_size=10000)

    # ==================== Parsing Tests ====================

    def test_parse_single_reference(self, parser):
        """Test parsing a single file reference."""
        message = "Review @test.py for bugs"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@test.py"
        assert refs[0].path.name == "test.py"

    def test_parse_multiple_references(self, parser):
        """Test parsing multiple file references."""
        message = "Compare @test.py and @main.py for differences"
        refs = parser.parse_references(message)

        assert len(refs) == 2
        assert refs[0].original == "@test.py"
        assert refs[1].original == "@main.py"

    def test_parse_path_reference(self, parser):
        """Test parsing file with path."""
        message = "Check @utils/helpers.py"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@utils/helpers.py"
        assert "helpers.py" in str(refs[0].path)

    def test_parse_with_line_number(self, parser):
        """Test parsing file with single line number."""
        message = "Check @test.py:5"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@test.py:5"
        assert refs[0].line_start == 5
        assert refs[0].line_end == 5

    def test_parse_with_line_range(self, parser):
        """Test parsing file with line range."""
        message = "Review @test.py:10-20"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@test.py:10-20"
        assert refs[0].line_start == 10
        assert refs[0].line_end == 20

    def test_parse_no_references(self, parser):
        """Test message with no file references."""
        message = "This is a message without any references"
        refs = parser.parse_references(message)

        assert len(refs) == 0

    def test_parse_mixed_content(self, parser):
        """Test parsing with references mixed in text."""
        message = "I want to optimize @test.py and also check @main.py before deployment"
        refs = parser.parse_references(message)

        assert len(refs) == 2
        assert refs[0].original == "@test.py"
        assert refs[1].original == "@main.py"

    # ==================== File Loading Tests ====================

    def test_load_existing_file(self, parser, temp_dir):
        """Test loading an existing file."""
        message = "Review @test.py"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        assert refs[0].is_loaded
        assert refs[0].content == "print('hello world')\n"
        assert refs[0].error is None

    def test_load_multiple_files(self, parser, temp_dir):
        """Test loading multiple files."""
        message = "Compare @test.py and @main.py"
        refs = parser.parse_and_load(message)

        assert len(refs) == 2
        assert all(ref.is_loaded for ref in refs)
        assert refs[0].content == "print('hello world')\n"
        assert "def main()" in refs[1].content

    def test_load_nonexistent_file(self, parser):
        """Test loading a file that doesn't exist."""
        message = "Review @nonexistent.py"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        assert not refs[0].is_loaded
        assert refs[0].error is not None
        assert "not found" in refs[0].error.lower()

    def test_load_file_with_line_range(self, parser, temp_dir):
        """Test loading specific line range from file."""
        message = "Check @large.txt:5-7"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        assert refs[0].is_loaded
        lines = refs[0].content.splitlines()
        assert len(lines) == 3
        assert "line 5" in lines[0]
        assert "line 7" in lines[2]

    def test_load_file_with_single_line(self, parser, temp_dir):
        """Test loading single line from file."""
        message = "Check @large.txt:10"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        assert refs[0].is_loaded
        assert refs[0].content == "line 10"

    def test_load_file_too_large(self, temp_dir):
        """Test loading file that exceeds size limit."""
        # Create parser with very small size limit
        parser = FileReferenceParser(base_dir=temp_dir, max_file_size=10)

        message = "@large.txt"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        assert not refs[0].is_loaded
        assert "too large" in refs[0].error.lower()

    # ==================== Path Resolution Tests ====================

    def test_resolve_relative_path(self, parser, temp_dir):
        """Test resolving relative path."""
        message = "@utils/helpers.py"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].path.is_absolute()
        assert refs[0].path.name == "helpers.py"

    def test_resolve_absolute_path(self, parser, temp_dir):
        """Test resolving absolute path."""
        absolute_path = temp_dir / "test.py"
        message = f"@{absolute_path}"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        # Resolve both sides to handle Windows 8.3 short names (e.g. RUNNER~1 vs runneradmin)
        assert refs[0].path.resolve() == absolute_path.resolve()

    def test_display_path_relative(self, parser, temp_dir):
        """Test display_path returns relative path when possible."""
        message = "@test.py"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        # Display path should be relative to current working directory
        assert not refs[0].display_path.startswith("/") or "/" in refs[0].display_path

    # ==================== Context Injection Tests ====================

    def test_inject_into_empty_context(self, parser, temp_dir):
        """Test injecting files into empty context."""
        message = "@test.py"
        refs = parser.parse_and_load(message)

        context = []
        new_context = parser.inject_into_context(refs, context)

        assert len(new_context) == 1
        assert new_context[0]["role"] == "system"
        assert "test.py" in new_context[0]["content"]
        assert "print('hello world')" in new_context[0]["content"]

    def test_inject_into_existing_context(self, parser, temp_dir):
        """Test injecting files into context with existing messages."""
        message = "@test.py"
        refs = parser.parse_and_load(message)

        context = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"}
        ]
        new_context = parser.inject_into_context(refs, context)

        # Should insert after first system message
        assert len(new_context) == 3
        assert new_context[0]["role"] == "system"
        assert "helpful assistant" in new_context[0]["content"]
        assert new_context[1]["role"] == "system"
        assert "test.py" in new_context[1]["content"]
        assert new_context[2]["role"] == "user"

    def test_inject_multiple_files(self, parser, temp_dir):
        """Test injecting multiple files into context."""
        message = "@test.py and @main.py"
        refs = parser.parse_and_load(message)

        context = []
        new_context = parser.inject_into_context(refs, context)

        assert len(new_context) == 1
        content = new_context[0]["content"]
        assert "test.py" in content
        assert "main.py" in content
        assert "print('hello world')" in content
        assert "def main()" in content

    def test_inject_file_with_line_range(self, parser, temp_dir):
        """Test injecting file with line range annotation."""
        message = "@large.txt:5-7"
        refs = parser.parse_and_load(message)

        context = []
        new_context = parser.inject_into_context(refs, context)

        assert len(new_context) == 1
        content = new_context[0]["content"]
        assert "Lines: 5-7" in content
        assert "line 5" in content

    def test_inject_skips_failed_loads(self, parser):
        """Test that failed file loads are not injected."""
        message = "@nonexistent.py and @also_missing.py"
        refs = parser.parse_and_load(message)

        context = []
        new_context = parser.inject_into_context(refs, context)

        # No files should be injected since all failed
        assert len(new_context) == 0

    # ==================== Helper Method Tests ====================

    def test_remove_references_from_message(self, parser):
        """Test removing file references from message."""
        message = "Review @test.py and @main.py for bugs"
        cleaned = parser.remove_references_from_message(message)

        assert "@test.py" not in cleaned
        assert "@main.py" not in cleaned
        assert "Review" in cleaned
        assert "for bugs" in cleaned
        assert cleaned == "Review and for bugs"

    def test_remove_references_cleans_whitespace(self, parser):
        """Test that removing references cleans up extra whitespace."""
        message = "Review    @test.py    and    @main.py    for bugs"
        cleaned = parser.remove_references_from_message(message)

        # Should collapse multiple spaces to single space
        assert "  " not in cleaned
        assert cleaned == "Review and for bugs"

    def test_format_summary_success(self, parser, temp_dir):
        """Test formatting summary for successfully loaded files."""
        message = "@test.py and @main.py"
        refs = parser.parse_and_load(message)

        summary = parser.format_summary(refs)

        assert "Referenced files:" in summary
        assert "test.py" in summary
        assert "main.py" in summary
        assert "✓" in summary  # Success indicator

    def test_format_summary_with_errors(self, parser):
        """Test formatting summary with failed loads."""
        message = "@test.py and @nonexistent.py"
        refs = parser.parse_and_load(message)

        summary = parser.format_summary(refs)

        assert "Referenced files:" in summary
        assert "test.py" in summary
        assert "nonexistent.py" in summary
        assert "✓" in summary  # For successful load
        assert "✗" in summary  # For failed load

    def test_format_summary_empty(self, parser):
        """Test formatting summary with no references."""
        refs = []
        summary = parser.format_summary(refs)

        assert summary == ""

    # ==================== FileReference Tests ====================

    def test_file_reference_is_loaded(self):
        """Test is_loaded property."""
        ref1 = FileReference(original="@test.py", path=Path("test.py"), content="content")
        assert ref1.is_loaded

        ref2 = FileReference(original="@test.py", path=Path("test.py"), error="Not found")
        assert not ref2.is_loaded

        ref3 = FileReference(original="@test.py", path=Path("test.py"))
        assert not ref3.is_loaded

    def test_file_reference_str(self):
        """Test string representation of FileReference."""
        ref1 = FileReference(original="@test.py", path=Path("test.py"), content="hello\nworld\n")
        str_repr = str(ref1)
        assert "test.py" in str_repr
        assert "2 lines" in str_repr

        ref2 = FileReference(original="@test.py", path=Path("test.py"), error="Not found")
        str_repr = str(ref2)
        assert "ERROR" in str_repr
        assert "Not found" in str_repr

    def test_file_reference_with_line_range_str(self):
        """Test string representation with line range."""
        ref = FileReference(
            original="@test.py:10-20",
            path=Path("test.py"),
            content="content",
            line_start=10,
            line_end=20
        )
        # Just verify it doesn't crash
        str(ref)

    # ==================== Edge Cases ====================

    def test_parse_file_without_extension(self, parser):
        """Test parsing file without extension."""
        message = "@Makefile"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@Makefile"

    def test_parse_hidden_file(self, parser):
        """Test parsing hidden file (starts with dot)."""
        message = "@.gitignore"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@.gitignore"

    def test_parse_file_with_dashes(self, parser):
        """Test parsing file with dashes in name."""
        message = "@my-config-file.yaml"
        refs = parser.parse_references(message)

        assert len(refs) == 1
        assert refs[0].original == "@my-config-file.yaml"

    def test_load_empty_file(self, parser, temp_dir):
        """Test loading an empty file."""
        empty_file = temp_dir / "empty.txt"
        empty_file.write_text("")

        message = "@empty.txt"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        assert refs[0].is_loaded
        assert refs[0].content == ""

    def test_line_range_beyond_file_end(self, parser, temp_dir):
        """Test line range that goes beyond file end."""
        message = "@test.py:5-100"
        refs = parser.parse_and_load(message)

        assert len(refs) == 1
        # Should load what's available without error
        assert refs[0].is_loaded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
