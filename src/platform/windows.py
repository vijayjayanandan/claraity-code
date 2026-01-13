"""
Windows Compatibility Layer

Handles Windows vs Unix differences:
- Path normalization (backslash vs forward slash)
- Subprocess execution (cmd.exe vs bash)
- Encoding safety (cp1252 vs UTF-8)
- Virtual environment activation

CRITICAL: NO EMOJIS in this file. Windows console uses cp1252 encoding.
Use text markers: [OK], [FAIL], [WARN], [INFO], [TEST]
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple


# =============================================================================
# PLATFORM DETECTION
# =============================================================================

def is_windows() -> bool:
    """Check if running on Windows."""
    return sys.platform == 'win32'


def is_unix() -> bool:
    """Check if running on Unix-like system (Linux, macOS)."""
    return sys.platform in ['linux', 'darwin']


def get_platform_name() -> str:
    """Get platform name: 'windows', 'linux', 'darwin' (macOS)."""
    return sys.platform


def get_shell_type() -> str:
    """Get shell type: 'cmd', 'powershell', 'bash', 'zsh'."""
    if is_windows():
        # Check if PowerShell is available
        try:
            subprocess.run(['powershell', '-Command', 'echo test'],
                          capture_output=True, timeout=1)
            return 'powershell'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return 'cmd'
    else:
        # Unix-like: check SHELL environment variable
        shell = os.environ.get('SHELL', '/bin/bash')
        if 'zsh' in shell:
            return 'zsh'
        elif 'bash' in shell:
            return 'bash'
        elif 'fish' in shell:
            return 'fish'
        else:
            return 'bash'  # Default to bash


# =============================================================================
# PATH NORMALIZATION
# =============================================================================

def normalize_path(path: Union[str, Path]) -> str:
    """
    Normalize path for current platform.

    - Converts Windows backslashes to forward slashes on Unix
    - Converts forward slashes to backslashes on Windows
    - Resolves relative paths to absolute paths
    - Handles ~/ (home directory) expansion

    Args:
        path: Path to normalize (string or Path object)

    Returns:
        Normalized absolute path string
    """
    # Convert to Path object
    p = Path(path).expanduser().resolve()

    # Convert to string with platform-appropriate separators
    return str(p)


def to_posix_path(path: Union[str, Path]) -> str:
    """
    Convert path to POSIX format (forward slashes).

    Useful for:
    - Git operations (expects forward slashes)
    - URLs
    - Cross-platform configuration files

    Args:
        path: Path to convert

    Returns:
        Path with forward slashes
    """
    return Path(path).as_posix()


def to_windows_path(path: Union[str, Path]) -> str:
    """
    Convert path to Windows format (backslashes).

    Only use when Windows-specific behavior is required
    (e.g., cmd.exe scripts, Windows API calls).

    Args:
        path: Path to convert

    Returns:
        Path with backslashes (on Windows) or forward slashes (on Unix)
    """
    if is_windows():
        return str(Path(path)).replace('/', '\\')
    else:
        return str(Path(path))


def safe_path_join(*parts: str) -> str:
    """
    Join path components with platform-appropriate separator.

    Better than os.path.join because it normalizes the result.

    Args:
        *parts: Path components to join

    Returns:
        Normalized joined path
    """
    return normalize_path(Path(*parts))


def get_relative_path(path: Union[str, Path], base: Union[str, Path]) -> str:
    """
    Get relative path from base to path.

    Args:
        path: Target path
        base: Base path

    Returns:
        Relative path string
    """
    try:
        return str(Path(path).relative_to(Path(base)))
    except ValueError:
        # Paths are not relative, return absolute path
        return normalize_path(path)


# =============================================================================
# ENCODING SAFETY (Critical for Windows cp1252)
# =============================================================================

def get_console_encoding() -> str:
    """
    Get console encoding.

    Returns:
        Encoding name (e.g., 'cp1252', 'utf-8')
    """
    # Try stdout encoding first
    if hasattr(sys.stdout, 'encoding') and sys.stdout.encoding:
        return sys.stdout.encoding

    # Fall back to default encoding
    return sys.getdefaultencoding()


def is_utf8_encoding() -> bool:
    """Check if console uses UTF-8 encoding."""
    encoding = get_console_encoding().lower()
    return 'utf' in encoding or 'utf8' in encoding


def safe_encode_output(text: str) -> str:
    """
    Safely encode text for console output.

    Replaces characters that can't be encoded with safe alternatives.
    CRITICAL: Prevents emoji crashes on Windows cp1252.

    Args:
        text: Text to encode

    Returns:
        Safely encoded text
    """
    if not text:
        return ""

    if is_utf8_encoding():
        return text

    # Windows cp1252: replace emojis and special characters
    encoding = get_console_encoding()

    try:
        # Try encoding, replace unencodable characters
        return text.encode(encoding, errors='replace').decode(encoding)
    except Exception:
        # Fallback: ASCII only
        return text.encode('ascii', errors='replace').decode('ascii')


def remove_emojis(text: str) -> str:
    """
    Remove ALL emoji characters from text.

    CRITICAL: Windows cp1252 crashes on emoji characters.
    Use this for log output, print statements, subprocess output.

    This pattern covers comprehensive Unicode emoji ranges including:
    - Common emojis (faces, objects, flags)
    - Symbols (checkmarks, warnings, arrows)
    - Extended emoji sets

    Args:
        text: Text potentially containing emojis

    Returns:
        Text with emojis removed
    """
    if not text:
        return ""

    import re

    # Comprehensive emoji pattern covering all Unicode emoji ranges
    # Based on Unicode TR51 (Emoji specification)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U0001F900-\U0001F9FF"  # supplemental symbols (includes fire emoji)
        "\U00002600-\U000026FF"  # miscellaneous symbols (includes checkmark, cross, warning)
        "\U00002700-\U000027BF"  # dingbats
        "\U00002B00-\U00002BFF"  # miscellaneous symbols and arrows
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols and pictographs extended
        "\U000024C2-\U0001F251"  # enclosed characters
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0001F200-\U0001F2FF"  # enclosed ideographic supplement
        "]+",
        flags=re.UNICODE
    )

    return emoji_pattern.sub('', text)


def safe_print(text: str, **kwargs) -> None:
    """
    Safely print text to console (emoji-safe on Windows).

    Args:
        text: Text to print (None will be converted to empty string)
        **kwargs: Additional arguments for print()
    """
    if text is None:
        text = ""

    if is_windows():
        # Windows: remove emojis and encode safely
        safe_text = safe_encode_output(remove_emojis(text))
        print(safe_text, **kwargs)
    else:
        # Unix: UTF-8 supported
        print(text, **kwargs)


# =============================================================================
# SUBPROCESS WRAPPER (cmd.exe vs bash)
# =============================================================================

def run_command(
    command: Union[str, List[str]],
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    capture_output: bool = True,
    timeout: Optional[float] = None,
    shell: bool = False,
    _allow_shell: bool = False
) -> subprocess.CompletedProcess:
    """
    Run command with platform-appropriate shell.

    Handles:
    - Windows cmd.exe vs Unix bash
    - Encoding differences (cp1252 vs UTF-8)
    - Shell quoting differences

    SECURITY WARNING: shell=True is disabled by default to prevent
    command injection attacks. Only use shell=True with fully trusted
    input, and set _allow_shell=True explicitly.

    Args:
        command: Command to run (string or list)
        cwd: Working directory
        env: Environment variables
        capture_output: Capture stdout/stderr
        timeout: Command timeout in seconds
        shell: Use shell (True) or direct execution (False)
        _allow_shell: Internal flag to explicitly enable shell=True (security)

    Returns:
        CompletedProcess with stdout/stderr as strings

    Raises:
        ValueError: If shell=True without _allow_shell=True

    Examples:
        # Safe: List format with shell=False
        run_command(['python', '-m', 'pytest'])

        # Unsafe (blocked): shell=True without permission
        run_command('echo test', shell=True)  # Raises ValueError

        # Allowed: Explicit permission for trusted input
        run_command('echo test', shell=True, _allow_shell=True)
    """
    # Security check: Prevent shell injection
    if shell and not _allow_shell:
        raise ValueError(
            "shell=True is disabled for security. "
            "Use command as list (e.g., ['python', '-m', 'pytest']) "
            "or set _allow_shell=True if input is fully trusted."
        )
    # Normalize working directory
    if cwd:
        cwd = normalize_path(cwd)

    # Set encoding based on platform
    encoding = get_console_encoding()

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=capture_output,
            timeout=timeout,
            shell=shell,
            encoding=encoding,
            errors='replace'  # Replace unencodable characters
        )

        # Remove emojis from output on Windows
        if is_windows() and capture_output:
            if result.stdout:
                result.stdout = remove_emojis(result.stdout)
            if result.stderr:
                result.stderr = remove_emojis(result.stderr)

        return result

    except subprocess.TimeoutExpired as e:
        # Handle timeout with safe encoding
        raise subprocess.TimeoutExpired(
            cmd=e.cmd,
            timeout=e.timeout,
            output=remove_emojis(e.output.decode(encoding, errors='replace')) if e.output else None,
            stderr=remove_emojis(e.stderr.decode(encoding, errors='replace')) if e.stderr else None
        )


def get_python_executable() -> str:
    """
    Get path to Python executable.

    Returns:
        Absolute path to python executable
    """
    return normalize_path(sys.executable)


def get_pip_executable() -> str:
    """
    Get path to pip executable.

    Returns:
        Absolute path to pip executable
    """
    python_dir = Path(sys.executable).parent

    if is_windows():
        # Windows: pip.exe in Scripts/ directory
        pip_path = python_dir / 'Scripts' / 'pip.exe'
        if not pip_path.exists():
            pip_path = python_dir / 'Scripts' / 'pip3.exe'
    else:
        # Unix: pip in bin/ directory
        pip_path = python_dir / 'pip'
        if not pip_path.exists():
            pip_path = python_dir / 'pip3'

    return normalize_path(pip_path)


# =============================================================================
# VIRTUAL ENVIRONMENT HANDLING
# =============================================================================

def is_in_virtualenv() -> bool:
    """Check if running inside a virtual environment."""
    return hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )


def get_virtualenv_path() -> Optional[str]:
    """
    Get path to current virtual environment.

    Returns:
        Path to virtualenv or None if not in a virtualenv
    """
    if not is_in_virtualenv():
        return None

    return normalize_path(sys.prefix)


def get_activation_script() -> Optional[str]:
    """
    Get path to virtual environment activation script.

    Returns:
        Path to activation script or None if not in a virtualenv
    """
    venv_path = get_virtualenv_path()
    if not venv_path:
        return None

    venv = Path(venv_path)

    if is_windows():
        # Windows: Scripts/activate.bat or Scripts/Activate.ps1
        activate_bat = venv / 'Scripts' / 'activate.bat'
        activate_ps1 = venv / 'Scripts' / 'Activate.ps1'

        if activate_ps1.exists():
            return normalize_path(activate_ps1)
        elif activate_bat.exists():
            return normalize_path(activate_bat)
    else:
        # Unix: bin/activate
        activate = venv / 'bin' / 'activate'
        if activate.exists():
            return normalize_path(activate)

    return None


def create_virtualenv_command(venv_path: str) -> Tuple[str, str]:
    """
    Create command to activate virtual environment.

    Args:
        venv_path: Path to virtual environment

    Returns:
        Tuple of (shell_type, activation_command)
    """
    venv = Path(venv_path)
    shell = get_shell_type()

    if is_windows():
        if shell == 'powershell':
            script = venv / 'Scripts' / 'Activate.ps1'
            return ('powershell', f'& "{script}"')
        else:  # cmd
            script = venv / 'Scripts' / 'activate.bat'
            return ('cmd', f'"{script}"')
    else:
        # Unix: source bin/activate
        script = venv / 'bin' / 'activate'
        return (shell, f'source "{script}"')


# =============================================================================
# FILE OPERATIONS (Windows-safe)
# =============================================================================

def safe_read_file(file_path: Union[str, Path], encoding: str = 'utf-8') -> str:
    """
    Safely read file with encoding fallback.

    Args:
        file_path: Path to file
        encoding: Preferred encoding (default: utf-8)

    Returns:
        File contents as string
    """
    path = normalize_path(file_path)

    try:
        # Try preferred encoding
        with open(path, 'r', encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError:
        # Fallback to platform encoding
        platform_encoding = get_console_encoding()
        try:
            with open(path, 'r', encoding=platform_encoding, errors='replace') as f:
                return f.read()
        except Exception:
            # Last resort: binary mode
            with open(path, 'rb') as f:
                return f.read().decode('utf-8', errors='replace')


def safe_write_file(
    file_path: Union[str, Path],
    content: str,
    encoding: str = 'utf-8',
    ensure_parent: bool = True
) -> None:
    """
    Safely write file with encoding.

    Args:
        file_path: Path to file
        content: Content to write
        encoding: Encoding (default: utf-8)
        ensure_parent: Create parent directory if it doesn't exist
    """
    path = Path(normalize_path(file_path))

    if ensure_parent:
        path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w', encoding=encoding) as f:
        f.write(content)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_line_ending() -> str:
    """
    Get platform line ending.

    Returns:
        '\\r\\n' on Windows, '\\n' on Unix
    """
    return '\r\n' if is_windows() else '\n'


def normalize_line_endings(text: str, target: Optional[str] = None) -> str:
    """
    Normalize line endings in text.

    Args:
        text: Text to normalize
        target: Target line ending ('\\n', '\\r\\n', or None for platform default)

    Returns:
        Text with normalized line endings
    """
    if target is None:
        target = get_line_ending()

    # Replace all line endings with target
    text = text.replace('\r\n', '\n')  # Windows -> Unix
    text = text.replace('\r', '\n')    # Old Mac -> Unix

    if target == '\r\n':
        text = text.replace('\n', '\r\n')  # Unix -> Windows

    return text


def get_max_path_length() -> int:
    """
    Get maximum path length for platform.

    Returns:
        Maximum path length (260 on Windows, 4096 on Unix)
    """
    if is_windows():
        # Windows MAX_PATH (unless long path support enabled)
        return 260
    else:
        # Unix PATH_MAX
        return 4096


def is_path_too_long(path: Union[str, Path]) -> bool:
    """
    Check if path exceeds platform maximum.

    Args:
        path: Path to check

    Returns:
        True if path is too long
    """
    return len(str(path)) > get_max_path_length()
