"""
Platform Compatibility Layer

Cross-platform utilities for handling OS-specific differences.
Currently focused on Windows compatibility.

IMPORTANT: This module overrides the built-in print() function globally
to use safe_print(), preventing Windows encoding crashes throughout the codebase.
"""

import builtins

from .windows import (
    create_virtualenv_command,
    get_activation_script,
    # Encoding safety
    get_console_encoding,
    # Utilities
    get_line_ending,
    get_max_path_length,
    get_pip_executable,
    get_platform_name,
    get_python_executable,
    get_relative_path,
    get_shell_type,
    get_virtualenv_path,
    # Virtual environment
    is_in_virtualenv,
    is_path_too_long,
    is_unix,
    is_utf8_encoding,
    # Platform detection
    is_windows,
    normalize_line_endings,
    # Path normalization
    normalize_path,
    remove_emojis,
    # Subprocess wrapper
    run_command,
    safe_encode_output,
    safe_path_join,
    safe_print,
    # File operations
    safe_read_file,
    safe_write_file,
    to_posix_path,
    to_windows_path,
)

__all__ = [
    # Platform detection
    'is_windows',
    'is_unix',
    'get_platform_name',
    'get_shell_type',
    # Path normalization
    'normalize_path',
    'to_posix_path',
    'to_windows_path',
    'safe_path_join',
    'get_relative_path',
    # Encoding safety
    'get_console_encoding',
    'is_utf8_encoding',
    'safe_encode_output',
    'remove_emojis',
    'safe_print',
    # Subprocess wrapper
    'run_command',
    'get_python_executable',
    'get_pip_executable',
    # Virtual environment
    'is_in_virtualenv',
    'get_virtualenv_path',
    'get_activation_script',
    'create_virtualenv_command',
    # File operations
    'safe_read_file',
    'safe_write_file',
    # Utilities
    'get_line_ending',
    'normalize_line_endings',
    'get_max_path_length',
    'is_path_too_long',
]

# GLOBAL FIX: Override built-in print() to prevent Windows encoding crashes
# NOTE: Disabled due to recursion issues - use safe_print() directly instead
# builtins.print = safe_print
