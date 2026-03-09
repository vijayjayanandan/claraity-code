"""Knowledge base manifest tools for change detection and tracking.

Provides:
- KBDetectChangesTool: Reads manifest, compares file stats, reports changes
- KBUpdateManifestTool: Writes manifest with current file stats and coverage map

These tools are internal to the knowledge-builder subagent and handle
the bookkeeping that enables incremental knowledge base updates.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Optional

from .base import Tool, ToolResult, ToolStatus

MANIFEST_PATH = ".clarity/knowledge/.manifest.json"

# File extensions to skip (binary/non-source) — applied as post-filter
_SKIP_EXTENSIONS = {
    '.pyc', '.pyo', '.so', '.dll', '.dylib', '.exe', '.bin',
    '.db', '.sqlite', '.sqlite3',
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp',
    '.woff', '.woff2', '.ttf', '.eot',
    '.zip', '.tar', '.gz', '.bz2', '.7z',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.lock',
}


SCAN_CONFIG_PATH = ".clarity/knowledge/scan_config.yaml"

_SCAN_CONFIG_TEMPLATE = """\
# Controls which source files the knowledge-builder scans.
# By default all git-tracked files are scanned (minus binary extensions).
# Only edit the include/exclude lists below. Do NOT add other keys.

# Glob whitelist — if non-empty, ONLY matching source files are scanned.
include:
  # - "src/**"
  # - "app/**"

# Glob blacklist — matching source files are always skipped.
exclude:
  # - "tests/fixtures/**"
  # - "migrations/**"
"""


def _ensure_scan_config(root: Path) -> None:
    """Create scan_config.yaml template if it doesn't exist."""
    config_path = root / SCAN_CONFIG_PATH
    if config_path.exists():
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_SCAN_CONFIG_TEMPLATE, encoding="utf-8")


def _read_kb_config(root: Path) -> dict[str, list[str]]:
    """Read knowledge include/exclude patterns from scan_config.yaml.

    Returns:
        dict with 'include' and 'exclude' lists of glob patterns.
        Defaults to include=[] (all files), exclude=[].
    """
    config_path = root / SCAN_CONFIG_PATH
    result = {"include": [], "exclude": []}
    if not config_path.exists():
        return result
    try:
        import yaml
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        include = config.get("include")
        exclude = config.get("exclude")
        if isinstance(include, list):
            result["include"] = include
        if isinstance(exclude, list):
            result["exclude"] = exclude
    except Exception:
        pass
    return result


def _git_ls_files(root: Path) -> list[str] | None:
    """Get list of git-tracked files. Returns None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return [
                f.replace('\\', '/')
                for f in result.stdout.strip().splitlines()
                if f.strip()
            ]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _apply_filters(
    file_paths: list[str],
    include: list[str],
    exclude: list[str],
) -> list[str]:
    """Apply include/exclude glob patterns to a file list.

    Args:
        file_paths: list of relative file paths (forward slashes)
        include: If non-empty, only files matching at least one pattern are kept
        exclude: Files matching any pattern are removed

    Returns:
        Filtered file list
    """
    result = file_paths

    # Include filter (whitelist) — if set, only keep matches
    if include:
        result = [f for f in result if any(fnmatch(f, p) for p in include)]

    # Exclude filter (blacklist) — always remove matches
    if exclude:
        result = [f for f in result if not any(fnmatch(f, p) for p in exclude)]

    return result


def _scan_project_files(root: Path) -> dict[str, dict[str, Any]]:
    """Scan project for source files and collect stats.

    Uses git ls-files when available (filters untracked files automatically).
    Falls back to os.walk if not in a git repo. Applies binary extension
    filter and user-configured include/exclude patterns from config.yaml.

    Args:
        root: Project root directory

    Returns:
        dict mapping relative file paths (forward slashes) to {size, mtime}
    """
    # Read user config for include/exclude patterns
    kb_config = _read_kb_config(root)

    # Try git ls-files first (filters untracked files automatically)
    git_files = _git_ls_files(root)

    if git_files is not None:
        file_paths = git_files
    else:
        # Fallback: os.walk (non-git projects)
        _skip_dirs = {
            '.git', '.hg', '.svn', '.clarity',
            '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
            'node_modules', '.next', 'dist', 'build', 'out',
            '.venv', 'venv', '.env', 'env',
            '.tox', '.nox', '.eggs',
            '.idea', '.vscode',
            '.benchmarks', '.checkpoints',
        }
        file_paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in _skip_dirs and not d.startswith('.')
            ]
            rel_dir = Path(dirpath).relative_to(root)
            for filename in filenames:
                if filename.startswith('.'):
                    continue
                rel_path = str(rel_dir / filename).replace('\\', '/')
                file_paths.append(rel_path)

    # Filter binary extensions
    file_paths = [
        f for f in file_paths
        if Path(f).suffix.lower() not in _SKIP_EXTENSIONS
    ]

    # Apply user include/exclude patterns
    file_paths = _apply_filters(
        file_paths, kb_config["include"], kb_config["exclude"]
    )

    # Stat each file
    files = {}
    for rel_path in file_paths:
        filepath = root / rel_path
        try:
            stat = filepath.stat()
            mtime_iso = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
            files[rel_path] = {
                "size": stat.st_size,
                "mtime": mtime_iso,
            }
        except (OSError, PermissionError):
            continue

    return files


def _read_manifest(manifest_path: Path) -> dict | None:
    """Read manifest file, return None if missing or invalid."""
    try:
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _match_coverage(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any coverage pattern.

    Supports glob-like patterns via fnmatch:
    - "src/api/*" matches "src/api/main.py"
    - "src/**" matches anything under "src/"
    """
    for pattern in patterns:
        if fnmatch(file_path, pattern):
            return True
    return False


class KBDetectChangesTool(Tool):
    """Detect changes in source files since last knowledge base update.

    Reads .manifest.json, scans the project for current file stats,
    compares against stored values, and returns a structured change report.
    """

    def __init__(self):
        super().__init__(
            name="kb_detect_changes",
            description=(
                "Detect source file changes since last knowledge base update. "
                "Returns FULL mode if no manifest exists, or INCREMENTAL mode "
                "with a list of changed/new/deleted files and affected knowledge files."
            )
        )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            root = Path.cwd()
            manifest_path = root / MANIFEST_PATH

            # Create scan_config.yaml template if missing (first run)
            _ensure_scan_config(root)

            manifest = _read_manifest(manifest_path)

            if manifest is None:
                current_files = _scan_project_files(root)
                file_list = sorted(current_files.keys())
                lines = [
                    "Mode: FULL (no manifest found)",
                    f"Scanned {len(file_list)} source files.",
                    "",
                    "Files to analyze:",
                ]
                for f in file_list:
                    lines.append(f"  {f}")
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="\n".join(lines),
                    metadata={
                        "mode": "full",
                        "total_files": len(file_list),
                        "files": file_list,
                    }
                )

            # Read manifest and compare
            stored_files = manifest.get("source_files", {})
            knowledge_coverage = manifest.get("knowledge_coverage", {})
            last_run = manifest.get("last_run", "unknown")

            current_files = _scan_project_files(root)

            changed = []
            new_files = []
            deleted = []
            unchanged = 0

            # Check stored files for changes/deletions
            for path, stored_stat in stored_files.items():
                if path not in current_files:
                    deleted.append(path)
                else:
                    current = current_files[path]
                    if (current["size"] != stored_stat["size"]
                            or current["mtime"] != stored_stat["mtime"]):
                        changed.append({
                            "path": path,
                            "old_size": stored_stat["size"],
                            "new_size": current["size"],
                        })
                    else:
                        unchanged += 1

            # Check for new files (in current but not in manifest)
            for path in current_files:
                if path not in stored_files:
                    new_files.append({
                        "path": path,
                        "size": current_files[path]["size"],
                    })

            # Determine affected knowledge files
            affected = set()
            all_changed_paths = (
                [c["path"] for c in changed]
                + [n["path"] for n in new_files]
                + deleted
            )
            for kf_name, patterns in knowledge_coverage.items():
                for changed_path in all_changed_paths:
                    if _match_coverage(changed_path, patterns):
                        affected.add(kf_name)
                        break

            # No changes
            if not changed and not new_files and not deleted:
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output=(
                        f"Mode: INCREMENTAL (no changes detected)\n"
                        f"Last run: {last_run}\n"
                        f"All {unchanged} tracked source files are unchanged.\n"
                        f"Knowledge base is up to date."
                    ),
                    metadata={"mode": "incremental", "changes": False}
                )

            # Build human-readable report
            lines = [
                "Mode: INCREMENTAL",
                f"Last run: {last_run}",
                "",
                f"Changes: {len(changed)} changed, {len(new_files)} new, "
                f"{len(deleted)} deleted, {unchanged} unchanged",
                "",
            ]

            if changed:
                lines.append("Changed files:")
                for c in changed:
                    lines.append(
                        f"  {c['path']} (size: {c['old_size']} -> {c['new_size']})"
                    )
                lines.append("")

            if new_files:
                lines.append("New files:")
                for n in new_files:
                    lines.append(f"  {n['path']} (size: {n['size']})")
                lines.append("")

            if deleted:
                lines.append("Deleted files:")
                for d in deleted:
                    lines.append(f"  {d}")
                lines.append("")

            if affected:
                lines.append("Affected knowledge files:")
                for kf_name in sorted(affected):
                    patterns = knowledge_coverage.get(kf_name, [])
                    lines.append(f"  {kf_name} (covers: {', '.join(patterns)})")
            else:
                lines.append(
                    "No existing knowledge files affected "
                    "(changes may be in uncovered areas)."
                )

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(lines),
                metadata={
                    "mode": "incremental",
                    "changes": True,
                    "changed_count": len(changed),
                    "new_count": len(new_files),
                    "deleted_count": len(deleted),
                    "unchanged_count": unchanged,
                    "affected_knowledge_files": sorted(affected),
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to detect changes: {str(e)}"
            )


class KBUpdateManifestTool(Tool):
    """Write or update the knowledge base manifest.

    Records which source files were analyzed and which knowledge files
    cover which source patterns, enabling incremental updates on next run.
    The tool stats each file for accurate size/mtime -- the caller only
    needs to pass file paths, not raw numbers.
    """

    def __init__(self):
        super().__init__(
            name="kb_update_manifest",
            description=(
                "Write the knowledge base manifest after documenting files. "
                "Pass the list of source files you analyzed and which knowledge "
                "files cover which source patterns. The tool stats each file "
                "for accurate size/mtime automatically."
            )
        )

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "analyzed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "list of source file paths analyzed in this run "
                        "(relative to project root, e.g. 'src/api/main.py')"
                    )
                },
                "knowledge_coverage": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "description": (
                        "Map of knowledge file name to source path patterns "
                        "it covers, e.g. {\"architecture.md\": [\"src/api/*\", \"src/chat/*\"]}"
                    )
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "incremental"],
                    "description": "Whether this was a full or incremental run"
                }
            },
            "required": ["analyzed_files", "knowledge_coverage", "mode"]
        }

    def execute(
        self,
        analyzed_files: list[str],
        knowledge_coverage: dict[str, list[str]],
        mode: str = "full",
        **kwargs: Any
    ) -> ToolResult:
        try:
            root = Path.cwd()
            manifest_path = root / MANIFEST_PATH
            now = datetime.now(timezone.utc).isoformat()

            # Stat analyzed files for accurate size/mtime
            source_files = {}
            stat_errors = []
            for filepath in analyzed_files:
                full_path = root / filepath
                try:
                    stat = full_path.stat()
                    mtime_iso = datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat()
                    normalized = filepath.replace('\\', '/')
                    source_files[normalized] = {
                        "size": stat.st_size,
                        "mtime": mtime_iso,
                    }
                except (OSError, PermissionError) as e:
                    stat_errors.append(f"{filepath}: {e}")

            # Merge with existing manifest on incremental runs
            if mode == "incremental":
                existing = _read_manifest(manifest_path)
                if existing:
                    merged_files = dict(existing.get("source_files", {}))
                    merged_files.update(source_files)
                    # Remove entries for files that no longer exist
                    merged_files = {
                        k: v for k, v in merged_files.items()
                        if (root / k).exists()
                    }
                    source_files = merged_files

                    merged_coverage = dict(
                        existing.get("knowledge_coverage", {})
                    )
                    merged_coverage.update(knowledge_coverage)
                    knowledge_coverage = merged_coverage

            # Build manifest
            manifest = {
                "last_run": now,
                "mode": mode,
                "source_files": source_files,
                "knowledge_coverage": knowledge_coverage,
            }

            # Write
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            # Confirmation
            lines = [
                f"Manifest written to {MANIFEST_PATH}",
                f"Mode: {mode}",
                f"Source files tracked: {len(source_files)}",
                f"Knowledge files mapped: {len(knowledge_coverage)}",
            ]
            if stat_errors:
                lines.append(
                    f"Warnings ({len(stat_errors)} files could not be statted):"
                )
                for err in stat_errors[:5]:
                    lines.append(f"  {err}")

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(lines),
                metadata={
                    "manifest_path": str(manifest_path),
                    "source_files_count": len(source_files),
                    "knowledge_files_count": len(knowledge_coverage),
                    "stat_errors": len(stat_errors),
                }
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to write manifest: {str(e)}"
            )
