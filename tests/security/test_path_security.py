"""Tests for path validation security fixes (S10, S11, S12, S15, S35, S38).

Verifies that path traversal is blocked across all tools that accept paths.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.tools.file_operations import FileOperationTool
from src.tools.base import ToolStatus
from src.tools.search_tools import validate_path_security


@pytest.fixture(autouse=True)
def set_workspace(tmp_path, monkeypatch):
    """Set workspace root to a controlled temp directory."""
    monkeypatch.setattr(FileOperationTool, '_workspace_root', tmp_path)
    yield
    monkeypatch.setattr(FileOperationTool, '_workspace_root', None)


class TestValidatePathSecurity:
    """S10: validate_path_security must block path traversal."""

    def test_blocks_path_traversal(self, tmp_path):
        """Rejects paths that traverse outside workspace."""
        with pytest.raises(ValueError, match="SECURITY|outside"):
            validate_path_security("../../../etc", workspace_root=tmp_path)

    def test_allows_workspace_directory(self, tmp_path):
        """Allows paths within the workspace."""
        subdir = tmp_path / "src"
        subdir.mkdir()
        result = validate_path_security(str(subdir), workspace_root=tmp_path)
        assert result == subdir.resolve()

    def test_blocks_absolute_path_outside_workspace(self, tmp_path):
        """Rejects absolute paths outside workspace."""
        with pytest.raises(ValueError, match="SECURITY|outside"):
            validate_path_security("/etc/passwd", workspace_root=tmp_path)

    def test_allows_relative_path_within_workspace(self, tmp_path, monkeypatch):
        """Allows relative paths that resolve within workspace."""
        monkeypatch.chdir(tmp_path)
        subdir = tmp_path / "sub"
        subdir.mkdir()
        result = validate_path_security("sub", workspace_root=tmp_path)
        assert result == subdir.resolve()


class TestGrepToolPathSecurity:
    """S10: GrepTool must use validate_path_security."""

    def test_grep_blocks_traversal(self, tmp_path):
        """GrepTool rejects paths outside workspace via validate_path_security."""
        from src.tools.search_tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern="test", path="../../../etc")
        assert result.status == ToolStatus.ERROR
        assert "security" in result.error.lower() or "outside" in result.error.lower()

    def test_grep_allows_workspace_path(self, tmp_path, monkeypatch):
        """GrepTool allows paths within workspace."""
        (tmp_path / "test.py").write_text("hello = True")
        monkeypatch.chdir(tmp_path)
        from src.tools.search_tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern="hello", path=str(tmp_path))
        assert result.status == ToolStatus.SUCCESS


class TestAgentInternalWriteSecurity:
    """S12: is_agent_internal_write must use resolved paths."""

    def test_rejects_traversal_with_claraity_substring(self):
        """Path containing .claraity/ but traversing out must be rejected."""
        from src.core.plan_mode import is_agent_internal_write
        # This path contains "/.claraity/" but traverses OUT of .claraity
        result = is_agent_internal_write(
            "write_file",
            {"file_path": ".claraity/../../etc/crontab"}
        )
        assert result is False, "Should reject path that traverses out of .claraity"

    def test_rejects_config_yaml(self):
        """Writes to .claraity/config.yaml must require approval."""
        from src.core.plan_mode import is_agent_internal_write
        result = is_agent_internal_write(
            "write_file",
            {"file_path": ".claraity/config.yaml"}
        )
        assert result is False, "config.yaml should NOT bypass approval"

    def test_allows_sessions_subdir(self):
        """Writes to .claraity/sessions/ are legitimate agent-internal writes."""
        from src.core.plan_mode import is_agent_internal_write
        result = is_agent_internal_write(
            "write_file",
            {"file_path": ".claraity/sessions/test-session.jsonl"}
        )
        assert result is True

    def test_allows_plans_subdir(self):
        """Writes to .claraity/plans/ are legitimate agent-internal writes."""
        from src.core.plan_mode import is_agent_internal_write
        result = is_agent_internal_write(
            "write_file",
            {"file_path": ".claraity/plans/plan-001.md"}
        )
        assert result is True

    def test_rejects_non_write_tools(self):
        """Non-write tools should never bypass approval via this check."""
        from src.core.plan_mode import is_agent_internal_write
        assert is_agent_internal_write("read_file", {"file_path": ".claraity/sessions/x"}) is False
        assert is_agent_internal_write("run_command", {"command": "ls"}) is False

    def test_rejects_empty_path(self):
        """Empty file path should not bypass approval."""
        from src.core.plan_mode import is_agent_internal_write
        assert is_agent_internal_write("write_file", {"file_path": ""}) is False
        assert is_agent_internal_write("write_file", {}) is False


class TestSessionManagerPathSecurity:
    """S15: Old SessionManager must validate session IDs."""

    def test_rejects_path_traversal_session_id(self):
        """Session ID with path traversal characters must be rejected."""
        from src.core.session_manager import SessionManager
        mgr = SessionManager.__new__(SessionManager)
        mgr.sessions_dir = Path("/tmp/fake-sessions")

        # These should all return None (rejected)
        assert mgr._find_session_dir("../../etc") is None
        assert mgr._find_session_dir("..\\..\\etc") is None
        assert mgr._find_session_dir("/etc/passwd") is None

    def test_rejects_non_hex_session_id(self):
        """Session IDs with non-hex characters must be rejected."""
        from src.core.session_manager import SessionManager
        mgr = SessionManager.__new__(SessionManager)
        mgr.sessions_dir = Path("/tmp/fake-sessions")

        assert mgr._find_session_dir("rm -rf /") is None
        assert mgr._find_session_dir("subagent") is None
        assert mgr._find_session_dir("<script>") is None

    def test_accepts_valid_uuid_format(self, tmp_path):
        """Valid UUID session IDs should be accepted."""
        from src.core.session_manager import SessionManager
        mgr = SessionManager.__new__(SessionManager)
        mgr.sessions_dir = tmp_path

        # Create a valid session directory
        session_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        session_dir = tmp_path / session_id
        session_dir.mkdir()

        result = mgr._find_session_dir(session_id)
        assert result is not None
        assert result == session_dir


class TestTranscriptLoggerSessionIdSecurity:
    """S35: TranscriptLogger must validate session IDs."""

    def test_rejects_path_traversal(self, tmp_path):
        """Session ID with path traversal must be rejected."""
        from src.observability.transcript_logger import TranscriptLogger

        with pytest.raises(ValueError, match="Invalid session ID"):
            TranscriptLogger(
                session_id="../../etc/cron.d/backdoor",
                base_dir=str(tmp_path),
            )

    def test_rejects_special_characters(self, tmp_path):
        """Session ID with special characters must be rejected."""
        from src.observability.transcript_logger import TranscriptLogger

        with pytest.raises(ValueError, match="Invalid session ID"):
            TranscriptLogger(
                session_id="<script>alert(1)</script>",
                base_dir=str(tmp_path),
            )

    def test_accepts_valid_uuid(self, tmp_path):
        """Valid UUID session ID should be accepted."""
        from src.observability.transcript_logger import TranscriptLogger

        # Should not raise
        logger = TranscriptLogger(
            session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            base_dir=str(tmp_path),
        )
        assert logger.session_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
