"""Secure file and directory permission utilities.

Sets restrictive permissions on sensitive files (sessions, config, logs)
to prevent unauthorized access on shared systems.
"""

import os
import platform
import stat
from pathlib import Path
from typing import Optional

from src.observability import get_logger

logger = get_logger("security.file_permissions")

# Whether we're on a POSIX system (Linux/macOS) where chmod works
IS_POSIX = platform.system() != "Windows"


def secure_directory(dir_path: Path) -> None:
    """Set restrictive permissions on a directory (700 on POSIX).

    Args:
        dir_path: Directory to secure.
    """
    if not IS_POSIX:
        return  # Windows uses ACLs, handled separately

    try:
        dir_path.chmod(stat.S_IRWXU)  # 700: owner rwx only
    except OSError as e:
        logger.warning(f"[SECURITY] Could not set permissions on {dir_path}: {e}")


def secure_file(file_path: Path) -> None:
    """Set restrictive permissions on a file (600 on POSIX).

    Args:
        file_path: File to secure.
    """
    if not IS_POSIX:
        return  # Windows uses ACLs, handled separately

    try:
        file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600: owner rw only
    except OSError as e:
        logger.warning(f"[SECURITY] Could not set permissions on {file_path}: {e}")


def secure_create_directory(dir_path: Path) -> None:
    """Create a directory with restrictive permissions.

    Creates the directory and all parents, then sets 700 permissions.

    Args:
        dir_path: Directory to create and secure.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    secure_directory(dir_path)


def secure_open_for_write(file_path: Path, mode: str = "w", encoding: str = "utf-8"):
    """Open a file for writing with restrictive permissions.

    Sets 600 permissions on the file after creation.

    Args:
        file_path: Path to the file.
        mode: File open mode (default: "w").
        encoding: File encoding (default: "utf-8").

    Returns:
        File handle.
    """
    # Ensure parent directory exists with secure permissions
    file_path.parent.mkdir(parents=True, exist_ok=True)

    handle = open(file_path, mode, encoding=encoding)
    secure_file(file_path)
    return handle


def secure_claraity_workspace(claraity_dir: Path) -> None:
    """Apply restrictive permissions to the entire .claraity workspace.

    Called once at startup to ensure the workspace directory tree
    has proper permissions.

    Args:
        claraity_dir: Path to the .claraity directory.
    """
    if not claraity_dir.exists():
        return

    if not IS_POSIX:
        return

    # Secure the root .claraity directory
    secure_directory(claraity_dir)

    # Secure sensitive subdirectories
    sensitive_dirs = ["sessions", "logs", "transcripts"]
    for subdir_name in sensitive_dirs:
        subdir = claraity_dir / subdir_name
        if subdir.exists():
            secure_directory(subdir)

    # Secure config file if it exists
    config_file = claraity_dir / "config.yaml"
    if config_file.exists():
        secure_file(config_file)

    logger.info("[SECURITY] Applied restrictive permissions to .claraity/ workspace")
