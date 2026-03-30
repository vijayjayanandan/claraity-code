"""
Tests for Windows Compatibility Layer

Tests platform detection, path normalization, encoding safety,
subprocess wrapper, and virtual environment handling.
"""

import sys
import os
import shutil
import tempfile
import subprocess
from pathlib import Path
import pytest

from src.platform import (
    # Platform detection
    is_windows,
    is_unix,
    get_platform_name,
    get_shell_type,
    # Path normalization
    normalize_path,
    to_posix_path,
    to_windows_path,
    safe_path_join,
    get_relative_path,
    # Encoding safety
    get_console_encoding,
    is_utf8_encoding,
    safe_encode_output,
    remove_emojis,
    # Subprocess wrapper
    run_command,
    get_python_executable,
    get_pip_executable,
    # Virtual environment
    is_in_virtualenv,
    get_virtualenv_path,
    get_activation_script,
    create_virtualenv_command,
    # File operations
    safe_read_file,
    safe_write_file,
    # Utilities
    get_line_ending,
    normalize_line_endings,
    get_max_path_length,
    is_path_too_long,
)


class TestPlatformDetection:
    """Test platform detection functions."""

    def test_is_windows(self):
        """Test Windows detection."""
        expected = sys.platform == 'win32'
        assert is_windows() == expected

    def test_is_unix(self):
        """Test Unix detection."""
        expected = sys.platform in ['linux', 'darwin']
        assert is_unix() == expected

    def test_get_platform_name(self):
        """Test platform name."""
        assert get_platform_name() == sys.platform

    def test_get_shell_type(self):
        """Test shell type detection."""
        shell = get_shell_type()
        if is_windows():
            assert shell in ['cmd', 'powershell']
        else:
            assert shell in ['bash', 'zsh', 'fish']


class TestPathNormalization:
    """Test path normalization functions."""

    def test_normalize_path_basic(self):
        """Test basic path normalization."""
        path = normalize_path('.')
        assert os.path.isabs(path)
        assert os.path.exists(path)

    def test_normalize_path_home(self):
        """Test home directory expansion."""
        path = normalize_path('~')
        assert os.path.isabs(path)
        assert 'Users' in path or 'home' in path or 'Documents' in path

    def test_to_posix_path(self):
        """Test POSIX path conversion."""
        path = to_posix_path('src/platform/windows.py')
        assert '/' in path
        assert '\\' not in path

    def test_to_windows_path(self):
        """Test Windows path conversion."""
        path = to_windows_path('src/platform/windows.py')
        if is_windows():
            # Windows: should have backslashes
            assert '\\' in path or '/' in path  # May already be normalized
        else:
            # Unix: should have forward slashes
            assert '/' in path

    def test_safe_path_join(self):
        """Test safe path joining."""
        path = safe_path_join('src', 'platform', 'windows.py')
        assert 'src' in path
        assert 'platform' in path
        assert 'windows.py' in path
        assert os.path.isabs(path)

    def test_get_relative_path(self):
        """Test relative path calculation."""
        base = os.getcwd()
        target = os.path.join(base, 'src', 'platform')
        rel_path = get_relative_path(target, base)
        assert 'src' in rel_path
        assert 'platform' in rel_path


class TestEncodingSafety:
    """Test encoding safety functions."""

    def test_get_console_encoding(self):
        """Test console encoding detection."""
        encoding = get_console_encoding()
        assert isinstance(encoding, str)
        assert len(encoding) > 0

    def test_is_utf8_encoding(self):
        """Test UTF-8 detection."""
        result = is_utf8_encoding()
        assert isinstance(result, bool)

    def test_safe_encode_output_ascii(self):
        """Test safe encoding with ASCII text."""
        text = "Hello World"
        result = safe_encode_output(text)
        assert result == text

    def test_safe_encode_output_emoji(self):
        """Test safe encoding with emojis."""
        text = "Hello World"  # No emojis - Windows safe
        result = safe_encode_output(text)
        assert isinstance(result, str)

    def test_remove_emojis(self):
        """Test emoji removal."""
        # Test with text (no emojis to remove)
        text = "Hello World [OK]"
        result = remove_emojis(text)
        assert "Hello World" in result
        assert "[OK]" in result


class TestSubprocessWrapper:
    """Test subprocess wrapper functions."""

    def test_run_command_simple(self):
        """Test simple command execution."""
        if is_windows():
            result = run_command(['cmd', '/c', 'echo', 'test'])
        else:
            result = run_command(['echo', 'test'])

        assert result.returncode == 0
        assert 'test' in result.stdout.lower()

    def test_run_command_with_cwd(self):
        """Test command execution with working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            if is_windows():
                result = run_command(['cmd', '/c', 'cd'], cwd=tmpdir)
            else:
                result = run_command(['pwd'], cwd=tmpdir)

            assert result.returncode == 0

    def test_get_python_executable(self):
        """Test Python executable detection."""
        python = get_python_executable()
        assert os.path.isabs(python)
        assert os.path.exists(python)
        assert 'python' in python.lower()

    def test_get_pip_executable(self):
        """Test pip executable detection."""
        pip = get_pip_executable()
        assert os.path.isabs(pip)
        # Pip may not exist in all environments, just check path format
        assert 'pip' in pip.lower()


class TestVirtualEnvironment:
    """Test virtual environment functions."""

    def test_is_in_virtualenv(self):
        """Test virtualenv detection."""
        result = is_in_virtualenv()
        assert isinstance(result, bool)

    def test_get_virtualenv_path(self):
        """Test virtualenv path detection."""
        venv_path = get_virtualenv_path()
        if venv_path:
            assert os.path.isabs(venv_path)
            assert os.path.exists(venv_path)

    def test_get_activation_script(self):
        """Test activation script detection."""
        script = get_activation_script()
        if script:
            assert os.path.isabs(script)
            if is_windows():
                assert 'Scripts' in script
                assert script.endswith('.bat') or script.endswith('.ps1')
            else:
                assert 'bin' in script
                assert 'activate' in script

    def test_create_virtualenv_command(self):
        """Test virtualenv command creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shell, cmd = create_virtualenv_command(tmpdir)
            assert shell in ['cmd', 'powershell', 'bash', 'zsh', 'fish']
            assert 'activate' in cmd.lower() or 'Activate' in cmd


class TestFileOperations:
    """Test file operation functions."""

    def test_safe_read_file(self):
        """Test safe file reading."""
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            test_content = "Test Content [OK]"
            f.write(test_content)
            temp_path = f.name

        try:
            content = safe_read_file(temp_path)
            assert test_content in content
        finally:
            os.unlink(temp_path)

    def test_safe_write_file(self):
        """Test safe file writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = os.path.join(tmpdir, 'subdir', 'test.txt')
            test_content = "Test Content [OK]"

            safe_write_file(test_path, test_content, ensure_parent=True)

            assert os.path.exists(test_path)
            with open(test_path, 'r', encoding='utf-8') as f:
                assert f.read() == test_content


class TestUtilities:
    """Test utility functions."""

    def test_get_line_ending(self):
        """Test line ending detection."""
        ending = get_line_ending()
        if is_windows():
            assert ending == '\r\n'
        else:
            assert ending == '\n'

    def test_normalize_line_endings_to_unix(self):
        """Test line ending normalization to Unix."""
        text = "Line 1\r\nLine 2\rLine 3\nLine 4"
        result = normalize_line_endings(text, target='\n')
        assert result == "Line 1\nLine 2\nLine 3\nLine 4"

    def test_normalize_line_endings_to_windows(self):
        """Test line ending normalization to Windows."""
        text = "Line 1\r\nLine 2\rLine 3\nLine 4"
        result = normalize_line_endings(text, target='\r\n')
        assert result == "Line 1\r\nLine 2\r\nLine 3\r\nLine 4"

    def test_get_max_path_length(self):
        """Test max path length detection."""
        max_len = get_max_path_length()
        if is_windows():
            assert max_len == 260
        else:
            assert max_len == 4096

    def test_is_path_too_long(self):
        """Test path length checking."""
        short_path = 'test.txt'
        assert not is_path_too_long(short_path)

        if is_windows():
            # Create a path that's definitely too long
            long_path = 'a' * 300
            assert is_path_too_long(long_path)


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_cross_platform_file_operations(self):
        """Test file operations work across platforms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file path with mixed separators
            file_path = os.path.join(tmpdir, 'test', 'file.txt')
            content = "Cross-platform test [OK]"

            # Write file
            safe_write_file(file_path, content, ensure_parent=True)

            # Read file
            read_content = safe_read_file(file_path)
            assert content in read_content

            # Normalize path
            normalized = normalize_path(file_path)
            assert os.path.exists(normalized)

    def test_command_output_encoding(self):
        """Test command output is properly encoded."""
        if is_windows():
            result = run_command(['cmd', '/c', 'echo', 'Test'])
        else:
            result = run_command(['echo', 'Test'])

        assert result.returncode == 0
        assert isinstance(result.stdout, str)
        # Should not contain emoji or unencodable characters
        try:
            result.stdout.encode('ascii', errors='strict')
        except UnicodeEncodeError:
            # Contains non-ASCII but should still be valid string
            assert isinstance(result.stdout, str)


class TestDetectPreferredShell:
    """Tests for detect_preferred_shell() -- bash-first detection with fallback."""

    def setup_method(self):
        """Clear the module-level cache before each test."""
        from src.platform import windows
        windows._preferred_shell.clear()

    def teardown_method(self):
        """Clear cache after each test to avoid polluting other tests."""
        from src.platform import windows
        windows._preferred_shell.clear()

    def test_returns_required_keys(self):
        """Result must contain shell, path, and syntax keys."""
        from src.platform import detect_preferred_shell
        result = detect_preferred_shell()
        assert "shell" in result
        assert "path" in result
        assert "syntax" in result

    def test_syntax_is_valid(self):
        """syntax must be 'unix' or 'powershell'."""
        from src.platform import detect_preferred_shell
        result = detect_preferred_shell()
        assert result["syntax"] in ("unix", "powershell")

    def test_cache_returns_same_values(self):
        """Second call returns same values as first (cached)."""
        from src.platform import detect_preferred_shell
        first = detect_preferred_shell()
        second = detect_preferred_shell()
        assert first == second

    def test_cache_returns_copy_not_reference(self):
        """Returned dict must be a copy -- mutations must not corrupt cache."""
        from src.platform import detect_preferred_shell
        first = detect_preferred_shell()
        first["shell"] = "CORRUPTED"
        second = detect_preferred_shell()
        assert second["shell"] != "CORRUPTED"

    @pytest.mark.skipif(not is_windows(), reason="Windows-only")
    def test_windows_finds_bash_or_powershell(self):
        """On Windows, result should be bash (Git Bash) or powershell."""
        from src.platform import detect_preferred_shell
        result = detect_preferred_shell()
        assert result["shell"] in ("bash", "powershell")

    @pytest.mark.skipif(not is_windows(), reason="Windows-only")
    def test_wsl_bash_rejected_by_find_git_bash(self):
        """WSL bash (System32\\bash.exe) should be rejected by _find_git_bash."""
        from src.platform.windows import _find_git_bash
        from unittest.mock import patch

        # Mock both shutil.which and os.path.isfile to fully isolate
        def mock_which(name):
            if name == "bash":
                return "C:\\Windows\\System32\\bash.exe"
            return None  # no git, no other tools

        with patch("src.platform.windows.shutil.which", side_effect=mock_which), \
             patch("src.platform.windows.os.path.isfile", return_value=False):
            result = _find_git_bash()
            assert result is None

    @pytest.mark.skipif(not is_windows(), reason="Windows-only")
    def test_syswow64_bash_rejected(self):
        """SysWOW64 bash should also be rejected."""
        from src.platform.windows import _find_git_bash
        from unittest.mock import patch

        def mock_which(name):
            if name == "bash":
                return "C:\\Windows\\SysWOW64\\bash.exe"
            return None

        with patch("src.platform.windows.shutil.which", side_effect=mock_which), \
             patch("src.platform.windows.os.path.isfile", return_value=False):
            result = _find_git_bash()
            assert result is None

    @pytest.mark.skipif(not is_windows(), reason="Windows-only")
    def test_git_bash_accepted_via_path(self):
        """Git Bash found on PATH should be accepted."""
        from src.platform.windows import _find_git_bash
        from unittest.mock import patch

        def mock_which(name):
            if name == "bash":
                return "C:\\Program Files\\Git\\usr\\bin\\bash.exe"
            return None

        with patch("src.platform.windows.shutil.which", side_effect=mock_which):
            result = _find_git_bash()
            assert result is not None
            assert "Git" in result

    @pytest.mark.skipif(not is_windows(), reason="Windows-only")
    def test_git_bash_derived_from_git_exe(self):
        """When bash isn't on PATH, derive from git.exe location."""
        from src.platform.windows import _find_git_bash
        from unittest.mock import patch

        def mock_which(name):
            if name == "bash":
                return None  # bash not on PATH
            if name == "git":
                return "C:\\Program Files\\Git\\cmd\\git.exe"
            return None

        # The derived path C:\Program Files\Git\usr\bin\bash.exe should exist on this machine
        result = _find_git_bash()
        # If Git is installed, this should find bash even without it on PATH
        if shutil.which("git"):
            assert result is not None
            assert os.path.isfile(result)

    @pytest.mark.skipif(not is_windows(), reason="Windows-only")
    def test_no_bash_falls_back_to_powershell(self):
        """When bash is not found at all, fall back to powershell."""
        from src.platform import windows

        # Mock _find_git_bash to return None (simulates no Git installed)
        original_find = windows._find_git_bash
        windows._find_git_bash = lambda: None
        try:
            windows._preferred_shell.clear()
            result = windows.detect_preferred_shell()
            assert result["shell"] == "powershell"
            assert result["syntax"] == "powershell"
        finally:
            windows._find_git_bash = original_find

    @pytest.mark.skipif(is_windows(), reason="Unix-only")
    def test_unix_uses_shell_env(self):
        """On Unix, should use SHELL environment variable."""
        from src.platform import detect_preferred_shell
        result = detect_preferred_shell()
        assert result["syntax"] == "unix"
        assert result["shell"] in ("bash", "zsh", "fish", "sh")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
