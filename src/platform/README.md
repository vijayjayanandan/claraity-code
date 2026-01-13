# Platform Compatibility Layer

Cross-platform utilities for handling OS-specific differences, with focus on Windows compatibility.

## Overview

This module provides production-grade utilities to handle Windows vs Unix differences:

- **Path normalization** - Windows backslash vs Unix forward slash
- **Subprocess wrapper** - cmd.exe vs bash
- **Encoding safety** - Windows cp1252 vs UTF-8 (prevents emoji crashes)
- **Virtual environment** - Scripts/ vs bin/, .bat vs .sh

## Quick Start

```python
from src.platform import (
    is_windows,
    normalize_path,
    safe_print,
    run_command,
    safe_read_file,
    safe_write_file,
)

# Platform detection
if is_windows():
    print("Running on Windows")

# Path normalization (critical for cross-platform code)
path = normalize_path("src/platform/windows.py")  # Absolute, platform-specific

# Safe printing (no emoji crashes on Windows)
safe_print("Task completed [OK]")  # Use text markers, not emojis

# Safe command execution
result = run_command(["git", "status"])
print(result.stdout)  # Emoji-free output

# Safe file operations
content = safe_read_file("data/config.json")  # Handles encoding
safe_write_file("output/result.txt", "Result [OK]", ensure_parent=True)
```

## Critical: NO EMOJIS on Windows

**Windows console uses cp1252 encoding, which crashes on emoji characters.**

### DON'T DO THIS:
```python
print("Task completed ✅")  # CRASHES on Windows cp1252
logger.info("Error ❌ in processing")  # CRASHES
subprocess.run(["echo", "Done 🎉"])  # CRASHES
```

### DO THIS INSTEAD:
```python
safe_print("Task completed [OK]")  # Works everywhere
logger.info("Error [FAIL] in processing")  # Works everywhere
result = run_command(["echo", "Done"])  # Emoji-free output
```

### Text Markers (use instead of emojis):
- `[OK]` - Success (replaces ✅)
- `[FAIL]` - Failure (replaces ❌)
- `[WARN]` - Warning (replaces ⚠️)
- `[INFO]` - Information (replaces ℹ️)
- `[TEST]` - Test status (replaces 🧪)

## Integration Guide

### 1. File Operations

**Before:**
```python
with open(path, 'r') as f:
    content = f.read()
```

**After (Windows-safe):**
```python
from src.platform import safe_read_file, safe_write_file

content = safe_read_file(path)  # Handles encoding fallback
safe_write_file(path, content, ensure_parent=True)  # Creates parent dirs
```

### 2. Path Operations

**Before:**
```python
path = os.path.join("src", "tools", "file.py")
```

**After (cross-platform):**
```python
from src.platform import normalize_path, safe_path_join

path = safe_path_join("src", "tools", "file.py")  # Absolute, normalized
posix_path = to_posix_path(path)  # For git operations
```

### 3. Subprocess Execution

**Before:**
```python
result = subprocess.run(["git", "status"], capture_output=True)
print(result.stdout.decode('utf-8'))
```

**After (encoding-safe):**
```python
from src.platform import run_command

result = run_command(["git", "status"])
print(result.stdout)  # Already decoded, emoji-free
```

### 4. Console Output

**Before:**
```python
print(f"Status: {status} ✅")
logger.info(f"Error: {error} ❌")
```

**After (Windows-safe):**
```python
from src.platform import safe_print, remove_emojis

safe_print(f"Status: {status} [OK]")
logger.info(remove_emojis(f"Error: {error} [FAIL]"))
```

### 5. Virtual Environment Detection

```python
from src.platform import (
    is_in_virtualenv,
    get_virtualenv_path,
    get_activation_script,
)

if is_in_virtualenv():
    venv_path = get_virtualenv_path()
    activate_script = get_activation_script()
    print(f"Virtual env: {venv_path}")
    print(f"Activate: {activate_script}")
```

## API Reference

### Platform Detection

- `is_windows()` - Returns True if running on Windows
- `is_unix()` - Returns True if running on Unix-like system
- `get_platform_name()` - Returns 'win32', 'linux', or 'darwin'
- `get_shell_type()` - Returns 'cmd', 'powershell', 'bash', 'zsh', or 'fish'

### Path Normalization

- `normalize_path(path)` - Normalize to absolute platform-specific path
- `to_posix_path(path)` - Convert to POSIX (forward slashes) - for git
- `to_windows_path(path)` - Convert to Windows (backslashes) - for cmd.exe
- `safe_path_join(*parts)` - Join path components with normalization
- `get_relative_path(path, base)` - Get relative path from base to path

### Encoding Safety

- `get_console_encoding()` - Get console encoding (cp1252, utf-8, etc.)
- `is_utf8_encoding()` - Check if console uses UTF-8
- `safe_encode_output(text)` - Safely encode for console (replaces emojis)
- `remove_emojis(text)` - Remove emoji characters from text
- `safe_print(text, **kwargs)` - Print without emoji crashes

### Subprocess Wrapper

- `run_command(command, cwd=None, env=None, ...)` - Run command with safe encoding
- `get_python_executable()` - Get path to Python executable
- `get_pip_executable()` - Get path to pip executable

### Virtual Environment

- `is_in_virtualenv()` - Check if running in virtualenv
- `get_virtualenv_path()` - Get path to current virtualenv
- `get_activation_script()` - Get path to activation script
- `create_virtualenv_command(venv_path)` - Create activation command

### File Operations

- `safe_read_file(path, encoding='utf-8')` - Read file with encoding fallback
- `safe_write_file(path, content, encoding='utf-8', ensure_parent=True)` - Write file safely

### Utilities

- `get_line_ending()` - Get platform line ending ('\\r\\n' or '\\n')
- `normalize_line_endings(text, target=None)` - Normalize line endings
- `get_max_path_length()` - Get max path length (260 on Windows, 4096 on Unix)
- `is_path_too_long(path)` - Check if path exceeds platform maximum

## Testing

Run the test suite:

```bash
pytest tests/test_platform_windows.py -v
```

All tests pass on both Windows and Unix platforms with 64% code coverage.

## Engineering Principles

This module follows the project's engineering principles:

1. **Accuracy > Speed** - Correct cross-platform behavior over performance
2. **No Technical Debt** - Production-grade from Day 1
3. **Quality Sets Culture** - Comprehensive test coverage
4. **Trust Through Rigor** - No emoji crashes, safe encoding
5. **Long-Term Thinking** - Foundation for all platform-specific code

## Migration Path

To migrate existing code:

1. **Search for emojis** - Replace with text markers
2. **Search for `os.path.join`** - Replace with `safe_path_join`
3. **Search for `open()`** - Replace with `safe_read_file` / `safe_write_file`
4. **Search for `subprocess.run`** - Replace with `run_command`
5. **Search for `print()`** - Replace with `safe_print` for user-facing output

## Future Enhancements

Potential improvements (not yet implemented):

- Windows long path support (>260 characters)
- PowerShell command generation
- Environment variable normalization
- File permissions handling (chmod on Unix, icacls on Windows)
- Symlink detection and handling
- Case-sensitivity differences (NTFS vs ext4)

## Support

For issues or questions:
- See test file: `tests/test_platform_windows.py`
- Component ID: `WINDOWS_COMPATIBILITY` in ClarAIty DB
- Architecture doc: `STATE_OF_THE_ART_AGENT_ARCHITECTURE.md`
