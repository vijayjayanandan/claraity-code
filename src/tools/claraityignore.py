"""
.claraityignore support -- gitignore-style file blocking.

Reads `.claraityignore` from the current working directory on every call (no caching).
Public functions:
- is_blocked(file_path) -> (bool, pattern|None) for file tools (hard error)
- filter_paths(paths) -> list[Path] for search/list tools (silent omit)
- check_command(command) -> (bool, reason|None) for run_command (token scanning)
"""

import shlex
from pathlib import Path
from typing import Optional

import pathspec

from src.observability import get_logger

logger = get_logger("tools.claraityignore")

CLARAITYIGNORE_FILENAME = ".claraityignore"


def _load_patterns() -> tuple[list[str], Optional[pathspec.PathSpec]]:
    """Read .claraityignore and return (raw_lines, compiled_spec).

    Returns ([], None) if file doesn't exist or is empty.
    """
    ignore_path = Path.cwd() / CLARAITYIGNORE_FILENAME
    if not ignore_path.is_file():
        return [], None

    try:
        text = ignore_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("claraityignore_read_error", error=str(e))
        return [], None

    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)

    if not lines:
        return [], None

    spec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
    return lines, spec


def _normalize_path(file_path: str | Path) -> str:
    """Convert a file path to a CWD-relative forward-slash string for matching."""
    p = Path(file_path).resolve()
    try:
        rel = p.relative_to(Path.cwd().resolve())
    except ValueError:
        # Path is outside CWD -- use absolute with forward slashes
        return str(p).replace("\\", "/")
    return str(rel).replace("\\", "/")


def is_blocked(file_path: str | Path) -> tuple[bool, Optional[str]]:
    """Check if a file path is blocked by .claraityignore.

    Args:
        file_path: Absolute or relative file path to check.

    Returns:
        (True, matching_pattern) if blocked.
        (False, None) if allowed.
    """
    lines, spec = _load_patterns()
    if spec is None:
        return False, None

    normalized = _normalize_path(file_path)

    if not spec.match_file(normalized):
        return False, None

    # Find which pattern matched (for the error message)
    for line in lines:
        single_spec = pathspec.PathSpec.from_lines("gitwildmatch", [line])
        if single_spec.match_file(normalized):
            logger.info("claraityignore_blocked", path=normalized, pattern=line)
            return True, line

    # Shouldn't reach here, but defensive
    return True, lines[0]


def filter_paths(paths: list[Path]) -> list[Path]:
    """Filter out paths that match .claraityignore patterns.

    Silent filtering for search/list tools -- returns only unblocked paths.
    """
    _lines, spec = _load_patterns()
    if spec is None:
        return paths

    result = []
    for p in paths:
        normalized = _normalize_path(p)
        if not spec.match_file(normalized):
            result.append(p)
    return result


def check_command(command: str) -> tuple[bool, Optional[str]]:
    """Check if a shell command references any blocked files.

    Tokenizes the command via shlex.split and checks each token against
    .claraityignore patterns. Catches straightforward commands like
    ``cat .env`` or ``type secrets/key.txt``.

    Args:
        command: Shell command string.

    Returns:
        (True, opaque_reason) if a blocked file is referenced.
        (False, None) if allowed.
    """
    _lines, spec = _load_patterns()
    if spec is None:
        return False, None

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # Malformed quoting -- don't break existing commands over a parse error
        return False, None

    for token in tokens:
        normalized = _normalize_path(token)
        if spec.match_file(normalized):
            logger.info("claraityignore_command_blocked", command=command, token=token)
            return True, "Access denied: command references a file blocked by user policy"

    return False, None
