"""
Cross-platform path normalization for Windows/MSYS/WSL/Cygwin.

Handles path formats:
- MSYS/Git Bash: /c:/Users/... -> C:/Users/...
- Cygwin: /cygdrive/c/Users/... -> C:/Users/...
- WSL: /mnt/c/Users/... -> C:/Users/...
- Standard Windows: C:\\Users\\... (unchanged)
- Unix: /home/user/... (unchanged)
"""

import os
import re
from pathlib import Path


def normalize_path(p: str) -> Path:
    """
    Normalize path across Windows/MSYS/WSL/Cygwin formats.

    Args:
        p: Path string in any format

    Returns:
        Resolved, normalized Path object
    """
    s = (p or "").strip()

    # MSYS / Git-Bash: /c:/Users/... -> C:/Users/...
    m = re.match(r"^/([a-zA-Z]):/(.*)$", s)
    if m:
        s = f"{m.group(1).upper()}:/{m.group(2)}"

    # Cygwin: /cygdrive/c/Users/... -> C:/Users/...
    m = re.match(r"^/cygdrive/([a-zA-Z])/(.*)$", s)
    if m:
        s = f"{m.group(1).upper()}:/{m.group(2)}"

    # WSL: /mnt/c/Users/... -> C:/Users/...
    m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", s)
    if m:
        s = f"{m.group(1).upper()}:/{m.group(2)}"

    # Resolve without requiring existence
    return Path(s).expanduser().resolve(strict=False)


def is_within_repo(file_path: str, repo_root: str) -> bool:
    """
    Check if file_path is within repo_root (cross-platform, case-insensitive on Windows).

    Uses os.path.commonpath() for robust containment check (avoids startswith() security bug).

    Args:
        file_path: Path to check
        repo_root: Repository root path

    Returns:
        True if file_path is within repo_root, False if repo_root is None/empty (security: reject by default)
    """
    # Security: If no repo_root configured, reject (don't allow arbitrary paths)
    if not repo_root:
        return False

    repo = normalize_path(repo_root)
    target = normalize_path(file_path)

    repo_s = os.path.normcase(os.path.normpath(str(repo)))
    targ_s = os.path.normcase(os.path.normpath(str(target)))

    # Robust containment (avoids startswith security bug)
    try:
        return os.path.commonpath([targ_s, repo_s]) == repo_s
    except ValueError:
        # Different drives on Windows
        return False
