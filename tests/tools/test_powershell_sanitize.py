"""Tests for PowerShell command sanitization."""

import platform
import pytest
from unittest.mock import patch

from src.tools.powershell_sanitize import sanitize_for_powershell, _replace_outside_quotes


class TestReplaceOutsideQuotes:
    """Test the quote-aware replacement helper."""

    def test_simple_replacement(self):
        # Raw helper replaces exact match; spaces around && stay
        assert _replace_outside_quotes("a && b", "&&", "; ") == "a ;  b"

    def test_with_spaces_pattern(self):
        # When matching ' && ' (with spaces) we get clean output
        assert _replace_outside_quotes("a && b", " && ", "; ") == "a; b"

    def test_no_replacement_inside_double_quotes(self):
        assert _replace_outside_quotes('echo "a && b"', "&&", "; ") == 'echo "a && b"'

    def test_no_replacement_inside_single_quotes(self):
        assert _replace_outside_quotes("echo 'a && b'", "&&", "; ") == "echo 'a && b'"

    def test_mixed_quoted_and_unquoted(self):
        result = _replace_outside_quotes('echo "hello && world" && echo done', " && ", "; ")
        assert result == 'echo "hello && world"; echo done'

    def test_no_match(self):
        assert _replace_outside_quotes("echo hello", "&&", "; ") == "echo hello"

    def test_multiple_replacements(self):
        result = _replace_outside_quotes("a && b && c", " && ", "; ")
        assert result == "a; b; c"

    def test_empty_string(self):
        assert _replace_outside_quotes("", "&&", "; ") == ""


class TestSanitizeForPowershell:
    """Test the main sanitizer function."""

    @patch("src.tools.powershell_sanitize.platform")
    def test_noop_on_unix(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        assert sanitize_for_powershell("echo a && echo b") == "echo a && echo b"

    @patch("src.tools.powershell_sanitize.platform")
    def test_noop_on_macos(self, mock_platform):
        mock_platform.system.return_value = "Darwin"
        assert sanitize_for_powershell("echo a && echo b") == "echo a && echo b"

    @patch("src.tools.powershell_sanitize.platform")
    def test_converts_ampersand_chain(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        result = sanitize_for_powershell("echo hello && echo world")
        assert result == "echo hello; echo world"

    @patch("src.tools.powershell_sanitize.platform")
    def test_converts_2_nul(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        result = sanitize_for_powershell("dir /s 2>nul")
        assert result == "dir /s 2>$null"

    @patch("src.tools.powershell_sanitize.platform")
    def test_converts_2_NUL_uppercase(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        result = sanitize_for_powershell("dir /s 2>NUL")
        assert result == "dir /s 2>$null"

    @patch("src.tools.powershell_sanitize.platform")
    def test_preserves_ampersand_in_quotes(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        result = sanitize_for_powershell('echo "Task 1: System info" && systeminfo')
        assert result == 'echo "Task 1: System info"; systeminfo'
        # The && inside the quotes (if any) should be preserved
        result2 = sanitize_for_powershell('echo "a && b" && echo done')
        assert result2 == 'echo "a && b"; echo done'

    @patch("src.tools.powershell_sanitize.platform")
    def test_complex_screenshot_command(self, mock_platform):
        """Reproduce the exact commands from the user's screenshot."""
        mock_platform.system.return_value = "Windows"

        cmd = 'echo "Task 1: System info" && systeminfo | findstr /C:"OS Name" /C:"Total Physical Memory"'
        result = sanitize_for_powershell(cmd)
        # All && outside quotes should be replaced
        assert " && " not in result
        assert ";" in result

        cmd2 = 'echo "Python version" && python --version 2>&1'
        result2 = sanitize_for_powershell(cmd2)
        assert ";" in result2

    @patch("src.tools.powershell_sanitize.platform")
    def test_no_change_when_already_powershell(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        cmd = "Get-ChildItem -Recurse -Filter *.py | Select-String 'import'"
        assert sanitize_for_powershell(cmd) == cmd
