"""Tests for knowledge base manifest tools (kb_detect_changes, kb_update_manifest)."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from src.tools.knowledge_tools import (
    KBDetectChangesTool,
    KBUpdateManifestTool,
    MANIFEST_PATH,
    SCAN_CONFIG_PATH,
    _scan_project_files,
    _match_coverage,
    _apply_filters,
    _read_kb_config,
    _ensure_scan_config,
)
from src.tools.base import ToolStatus


# ===== Helper =====

def _write_manifest(root, manifest_data):
    """Write a manifest file to the given project root."""
    manifest_path = root / MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest_data, indent=2),
        encoding="utf-8",
    )


def _create_source_tree(root):
    """Create a minimal project source tree and return file paths."""
    src = root / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "main.py").write_text("print('hello')\n")

    api = src / "api"
    api.mkdir()
    (api / "__init__.py").write_text("")
    (api / "routes.py").write_text("# routes\n")

    readme = root / "README.md"
    readme.write_text("# Test Project\n")

    return {
        "src/__init__.py",
        "src/main.py",
        "src/api/__init__.py",
        "src/api/routes.py",
        "README.md",
    }


# ===== _scan_project_files tests =====

class TestScanProjectFiles:
    """Tests for the internal file scanning function."""

    def test_scans_source_files(self, tmp_path):
        _create_source_tree(tmp_path)
        files = _scan_project_files(tmp_path)

        assert "src/main.py" in files
        assert "src/api/routes.py" in files
        assert "README.md" in files

    def test_skips_hidden_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / "src.py").write_text("code")

        files = _scan_project_files(tmp_path)
        assert "src.py" in files
        assert not any(".git" in path for path in files)

    def test_skips_pycache(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-310.pyc").write_text("bytes")
        (tmp_path / "module.py").write_text("code")

        files = _scan_project_files(tmp_path)
        assert "module.py" in files
        assert not any("__pycache__" in path for path in files)

    def test_skips_binary_extensions(self, tmp_path):
        (tmp_path / "data.db").write_text("db")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "code.py").write_text("code")

        files = _scan_project_files(tmp_path)
        assert "code.py" in files
        assert "data.db" not in files
        assert "image.png" not in files

    def test_returns_size_and_mtime(self, tmp_path):
        (tmp_path / "file.py").write_text("content")
        files = _scan_project_files(tmp_path)

        assert "file.py" in files
        entry = files["file.py"]
        assert "size" in entry
        assert "mtime" in entry
        assert isinstance(entry["size"], int)
        assert "T" in entry["mtime"]  # ISO format


# ===== _apply_filters tests =====

class TestApplyFilters:
    """Tests for include/exclude pattern filtering."""

    def test_no_filters_returns_all(self):
        files = ["src/a.py", "src/b.py", "README.md"]
        assert _apply_filters(files, [], []) == files

    def test_include_whitelist(self):
        files = ["src/a.py", "src/b.py", "docs/readme.md", "tests/test_a.py"]
        result = _apply_filters(files, ["src/*"], [])
        assert result == ["src/a.py", "src/b.py"]

    def test_include_multiple_patterns(self):
        files = ["src/a.py", "docs/readme.md", "tests/test_a.py"]
        result = _apply_filters(files, ["src/*", "tests/*"], [])
        assert set(result) == {"src/a.py", "tests/test_a.py"}

    def test_exclude_blacklist(self):
        files = ["src/a.py", "src/b.py", "package-lock.json"]
        result = _apply_filters(files, [], ["*.json"])
        assert result == ["src/a.py", "src/b.py"]

    def test_include_and_exclude_combined(self):
        files = ["src/a.py", "src/config.yaml", "docs/readme.md"]
        result = _apply_filters(files, ["src/*"], ["*.yaml"])
        assert result == ["src/a.py"]

    def test_double_star_pattern(self):
        files = ["src/api/routes.py", "src/api/models.py", "lib/utils.py"]
        result = _apply_filters(files, ["src/**"], [])
        assert set(result) == {"src/api/routes.py", "src/api/models.py"}


# ===== _ensure_scan_config tests =====

class TestEnsureScanConfig:
    """Tests for scan_config.yaml auto-creation."""

    def test_creates_template_when_missing(self, tmp_path):
        config_path = tmp_path / SCAN_CONFIG_PATH
        assert not config_path.exists()

        _ensure_scan_config(tmp_path)

        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "include:" in content
        assert "exclude:" in content

    def test_does_not_overwrite_existing(self, tmp_path):
        config_path = tmp_path / SCAN_CONFIG_PATH
        config_path.parent.mkdir(parents=True)
        config_path.write_text("include:\n  - 'src/**'\n", encoding="utf-8")

        _ensure_scan_config(tmp_path)

        content = config_path.read_text(encoding="utf-8")
        assert "src/**" in content  # User content preserved

    def test_kb_detect_creates_on_first_run(self, tmp_path, monkeypatch):
        """kb_detect_changes creates scan_config.yaml on first run."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        config_path = tmp_path / SCAN_CONFIG_PATH
        assert not config_path.exists()

        tool = KBDetectChangesTool()
        tool.execute()

        assert config_path.exists()


# ===== _read_kb_config tests =====

class TestReadKBConfig:
    """Tests for reading scan_config.yaml."""

    def test_no_config_file(self, tmp_path):
        result = _read_kb_config(tmp_path)
        assert result == {"include": [], "exclude": []}

    def test_empty_config(self, tmp_path):
        config_path = tmp_path / ".clarity" / "knowledge" / "scan_config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("# empty config\n", encoding="utf-8")

        result = _read_kb_config(tmp_path)
        assert result == {"include": [], "exclude": []}

    def test_config_with_include_exclude(self, tmp_path):
        config_path = tmp_path / ".clarity" / "knowledge" / "scan_config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "include:\n"
            "  - 'src/**'\n"
            "  - '*.md'\n"
            "exclude:\n"
            "  - 'tests/fixtures/**'\n",
            encoding="utf-8",
        )

        result = _read_kb_config(tmp_path)
        assert result["include"] == ["src/**", "*.md"]
        assert result["exclude"] == ["tests/fixtures/**"]

    def test_config_with_only_exclude(self, tmp_path):
        config_path = tmp_path / ".clarity" / "knowledge" / "scan_config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "exclude:\n"
            "  - '*.lock'\n",
            encoding="utf-8",
        )

        result = _read_kb_config(tmp_path)
        assert result["include"] == []
        assert result["exclude"] == ["*.lock"]


# ===== Git ls-files integration =====

class TestGitLsFilesIntegration:
    """Tests for git ls-files based scanning."""

    def test_uses_git_when_available(self, tmp_path, monkeypatch):
        """When git ls-files returns files, os.walk is not used."""
        _create_source_tree(tmp_path)
        # Also create an untracked file
        (tmp_path / "temp_notes.txt").write_text("untracked junk")

        mock_files = ["src/main.py", "src/api/routes.py", "README.md"]
        with patch("src.tools.knowledge_tools._git_ls_files", return_value=mock_files):
            files = _scan_project_files(tmp_path)

        assert "src/main.py" in files
        assert "README.md" in files
        # Untracked file should NOT appear (git ls-files doesn't list it)
        assert "temp_notes.txt" not in files

    def test_falls_back_to_walk_when_no_git(self, tmp_path):
        """When git ls-files returns None, os.walk is used."""
        _create_source_tree(tmp_path)

        with patch("src.tools.knowledge_tools._git_ls_files", return_value=None):
            files = _scan_project_files(tmp_path)

        # os.walk fallback should still find files
        assert "src/main.py" in files
        assert "README.md" in files

    def test_git_binary_extensions_still_filtered(self, tmp_path):
        """Binary extensions are filtered even from git ls-files results."""
        mock_files = ["src/main.py", "data.db", "image.png"]
        with patch("src.tools.knowledge_tools._git_ls_files", return_value=mock_files):
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "main.py").write_text("code")
            files = _scan_project_files(tmp_path)

        assert "src/main.py" in files
        assert "data.db" not in files
        assert "image.png" not in files

    def test_config_exclude_applied_with_git(self, tmp_path):
        """Config exclude patterns filter git ls-files results."""
        _create_source_tree(tmp_path)
        # Write scan config with exclude
        config_path = tmp_path / ".clarity" / "knowledge" / "scan_config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "exclude:\n  - 'src/api/*'\n",
            encoding="utf-8",
        )

        mock_files = ["src/main.py", "src/api/routes.py", "README.md"]
        with patch("src.tools.knowledge_tools._git_ls_files", return_value=mock_files):
            files = _scan_project_files(tmp_path)

        assert "src/main.py" in files
        assert "README.md" in files
        assert "src/api/routes.py" not in files

    def test_config_include_applied_with_git(self, tmp_path):
        """Config include patterns whitelist git ls-files results."""
        _create_source_tree(tmp_path)
        config_path = tmp_path / ".clarity" / "knowledge" / "scan_config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "include:\n  - 'src/**'\n",
            encoding="utf-8",
        )

        mock_files = ["src/main.py", "src/api/routes.py", "README.md"]
        with patch("src.tools.knowledge_tools._git_ls_files", return_value=mock_files):
            files = _scan_project_files(tmp_path)

        assert "src/main.py" in files
        assert "src/api/routes.py" in files
        assert "README.md" not in files


# ===== _match_coverage tests =====

class TestMatchCoverage:

    def test_exact_match(self):
        assert _match_coverage("src/api/main.py", ["src/api/main.py"])

    def test_wildcard_match(self):
        assert _match_coverage("src/api/main.py", ["src/api/*"])

    def test_double_star_match(self):
        assert _match_coverage("src/api/routes/chat.py", ["src/**"])

    def test_no_match(self):
        assert not _match_coverage("ui/app.tsx", ["src/*"])

    def test_multiple_patterns(self):
        assert _match_coverage("ui/app.tsx", ["src/*", "ui/*"])


# ===== KBDetectChangesTool tests =====

class TestKBDetectChanges:

    def test_full_mode_when_no_manifest(self, tmp_path, monkeypatch):
        """No manifest -> FULL mode with file list."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        tool = KBDetectChangesTool()
        result = tool.execute()

        assert result.status == ToolStatus.SUCCESS
        assert "FULL" in result.output
        assert result.metadata["mode"] == "full"
        assert result.metadata["total_files"] > 0
        # File list should be in output and metadata
        assert "src/main.py" in result.output
        assert "src/main.py" in result.metadata["files"]

    def test_incremental_no_changes(self, tmp_path, monkeypatch):
        """Manifest matches current files -> no changes."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        # Scan current state and write as manifest
        current = _scan_project_files(tmp_path)
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": current,
            "knowledge_coverage": {
                "architecture.md": ["src/*"],
            },
        })

        tool = KBDetectChangesTool()
        result = tool.execute()

        assert result.status == ToolStatus.SUCCESS
        assert "no changes" in result.output.lower()
        assert result.metadata["mode"] == "incremental"
        assert result.metadata["changes"] is False

    def test_incremental_detects_changed_file(self, tmp_path, monkeypatch):
        """File modified after manifest -> detected as changed."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        current = _scan_project_files(tmp_path)
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": current,
            "knowledge_coverage": {
                "architecture.md": ["src/api/*"],
            },
        })

        # Modify a file (change size to guarantee detection)
        time.sleep(0.05)
        (tmp_path / "src" / "api" / "routes.py").write_text(
            "# routes\n# added more content here\n"
        )

        tool = KBDetectChangesTool()
        result = tool.execute()

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["mode"] == "incremental"
        assert result.metadata["changes"] is True
        assert result.metadata["changed_count"] >= 1
        assert "src/api/routes.py" in result.output

    def test_incremental_detects_new_file(self, tmp_path, monkeypatch):
        """File added after manifest -> detected as new."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        current = _scan_project_files(tmp_path)
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": current,
            "knowledge_coverage": {},
        })

        # Add a new file
        (tmp_path / "src" / "new_module.py").write_text("# new\n")

        tool = KBDetectChangesTool()
        result = tool.execute()

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["new_count"] >= 1
        assert "new_module.py" in result.output

    def test_incremental_detects_deleted_file(self, tmp_path, monkeypatch):
        """File removed after manifest -> detected as deleted."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        current = _scan_project_files(tmp_path)
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": current,
            "knowledge_coverage": {},
        })

        # Delete a file
        (tmp_path / "src" / "api" / "routes.py").unlink()

        tool = KBDetectChangesTool()
        result = tool.execute()

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["deleted_count"] >= 1
        assert "src/api/routes.py" in result.output

    def test_affected_knowledge_files_reported(self, tmp_path, monkeypatch):
        """Changed files map to affected knowledge files via coverage."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        current = _scan_project_files(tmp_path)
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": current,
            "knowledge_coverage": {
                "architecture.md": ["src/api/*"],
                "file-guide.md": ["src/**"],
                "conventions.md": ["src/config/*"],
            },
        })

        # Modify a file covered by architecture.md and file-guide.md
        time.sleep(0.05)
        (tmp_path / "src" / "api" / "routes.py").write_text("# changed content\n")

        tool = KBDetectChangesTool()
        result = tool.execute()

        affected = result.metadata["affected_knowledge_files"]
        assert "architecture.md" in affected
        assert "file-guide.md" in affected
        # conventions.md covers src/config/* which didn't change
        assert "conventions.md" not in affected


# ===== KBUpdateManifestTool tests =====

class TestKBUpdateManifest:

    def test_full_mode_writes_manifest(self, tmp_path, monkeypatch):
        """Full mode creates manifest from scratch."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        tool = KBUpdateManifestTool()
        result = tool.execute(
            analyzed_files=["src/main.py", "src/api/routes.py"],
            knowledge_coverage={
                "architecture.md": ["src/*"],
            },
            mode="full",
        )

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["source_files_count"] == 2
        assert result.metadata["knowledge_files_count"] == 1

        # Verify manifest was written
        manifest_path = tmp_path / MANIFEST_PATH
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["mode"] == "full"
        assert "src/main.py" in manifest["source_files"]
        assert "src/api/routes.py" in manifest["source_files"]
        assert "architecture.md" in manifest["knowledge_coverage"]

    def test_full_mode_stats_files_accurately(self, tmp_path, monkeypatch):
        """Tool stats files itself — caller doesn't pass sizes/mtimes."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        tool = KBUpdateManifestTool()
        tool.execute(
            analyzed_files=["src/main.py"],
            knowledge_coverage={},
            mode="full",
        )

        manifest = json.loads(
            (tmp_path / MANIFEST_PATH).read_text(encoding="utf-8")
        )
        entry = manifest["source_files"]["src/main.py"]

        # Verify the tool computed real stats
        actual_stat = (tmp_path / "src" / "main.py").stat()
        assert entry["size"] == actual_stat.st_size
        assert "T" in entry["mtime"]  # ISO format

    def test_incremental_mode_merges(self, tmp_path, monkeypatch):
        """Incremental mode merges with existing manifest."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        # Write initial manifest with one file
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": {
                "src/main.py": {"size": 100, "mtime": "2026-01-01T00:00:00+00:00"},
            },
            "knowledge_coverage": {
                "architecture.md": ["src/*"],
            },
        })

        # Incremental update with a different file
        tool = KBUpdateManifestTool()
        result = tool.execute(
            analyzed_files=["src/api/routes.py"],
            knowledge_coverage={
                "file-guide.md": ["src/api/*"],
            },
            mode="incremental",
        )

        assert result.status == ToolStatus.SUCCESS

        manifest = json.loads(
            (tmp_path / MANIFEST_PATH).read_text(encoding="utf-8")
        )

        # Both files should be tracked (merged)
        assert "src/main.py" in manifest["source_files"]
        assert "src/api/routes.py" in manifest["source_files"]

        # Both knowledge files should be in coverage (merged)
        assert "architecture.md" in manifest["knowledge_coverage"]
        assert "file-guide.md" in manifest["knowledge_coverage"]

    def test_incremental_removes_deleted_files(self, tmp_path, monkeypatch):
        """Incremental mode removes entries for files that no longer exist."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        # Write manifest with a file that doesn't exist
        _write_manifest(tmp_path, {
            "last_run": "2026-01-01T00:00:00+00:00",
            "mode": "full",
            "source_files": {
                "src/deleted.py": {"size": 50, "mtime": "2026-01-01T00:00:00+00:00"},
                "src/main.py": {"size": 100, "mtime": "2026-01-01T00:00:00+00:00"},
            },
            "knowledge_coverage": {},
        })

        tool = KBUpdateManifestTool()
        tool.execute(
            analyzed_files=["src/main.py"],
            knowledge_coverage={},
            mode="incremental",
        )

        manifest = json.loads(
            (tmp_path / MANIFEST_PATH).read_text(encoding="utf-8")
        )

        # Deleted file should be removed
        assert "src/deleted.py" not in manifest["source_files"]
        assert "src/main.py" in manifest["source_files"]

    def test_handles_stat_errors(self, tmp_path, monkeypatch):
        """Files that can't be statted are reported but don't crash."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        tool = KBUpdateManifestTool()
        result = tool.execute(
            analyzed_files=["src/main.py", "nonexistent/file.py"],
            knowledge_coverage={},
            mode="full",
        )

        assert result.status == ToolStatus.SUCCESS
        assert result.metadata["stat_errors"] == 1
        assert result.metadata["source_files_count"] == 1

    def test_creates_directory_if_missing(self, tmp_path, monkeypatch):
        """Manifest directory is created if it doesn't exist."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        # Ensure .clarity/knowledge/ doesn't exist
        manifest_dir = tmp_path / ".clarity" / "knowledge"
        assert not manifest_dir.exists()

        tool = KBUpdateManifestTool()
        tool.execute(
            analyzed_files=["src/main.py"],
            knowledge_coverage={},
            mode="full",
        )

        assert (tmp_path / MANIFEST_PATH).exists()

    def test_normalizes_path_separators(self, tmp_path, monkeypatch):
        """Backslashes in file paths are normalized to forward slashes."""
        _create_source_tree(tmp_path)
        monkeypatch.chdir(tmp_path)

        tool = KBUpdateManifestTool()
        tool.execute(
            analyzed_files=["src\\api\\routes.py"],
            knowledge_coverage={},
            mode="full",
        )

        manifest = json.loads(
            (tmp_path / MANIFEST_PATH).read_text(encoding="utf-8")
        )
        # Should be normalized to forward slashes
        assert "src/api/routes.py" in manifest["source_files"]
