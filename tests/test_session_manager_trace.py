"""
Test suite for SessionManager.delete_session trace file cleanup.

Coverage:
- delete_session removes trace file alongside session directory
- delete_session succeeds when no trace file exists (optional cleanup)

Total: 2 tests
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.session_manager import SessionManager


class TestDeleteSessionTraceCleanup:
    """Verify delete_session cleans up .trace.jsonl files."""

    @staticmethod
    def _create_session_dir(
        sessions_dir: Path,
        session_id: str,
        *,
        with_trace: bool = False,
    ) -> Path:
        """Create a minimal session directory with metadata and session.jsonl.

        Args:
            sessions_dir: Parent sessions directory.
            session_id: Session ID (session-YYYYMMDD-HHMMSS-xxxxxxxx format).
            with_trace: If True, also create <session_id>.trace.jsonl alongside the dir.

        Returns:
            Path to the session directory.
        """
        session_dir = sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Minimal session.jsonl (one user message)
        session_jsonl = session_dir / "session.jsonl"
        session_jsonl.write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n",
            encoding="utf-8",
        )

        # Minimal metadata.json (required by load flow)
        metadata = {
            "session_id": session_id,
            "name": "test",
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
            "task_description": "test",
            "model_name": "test-model",
            "message_count": 1,
            "tags": [],
            "duration_minutes": 0.0,
        }
        (session_dir / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8",
        )

        if with_trace:
            trace_file = sessions_dir / f"{session_id}.trace.jsonl"
            trace_file.write_text(
                json.dumps({"type": "trace", "data": "test"}) + "\n",
                encoding="utf-8",
            )

        return session_dir

    def test_delete_session_removes_trace_file(self, tmp_path):
        """Create a session dir + a .trace.jsonl file. Delete the session.
        Verify both the dir and the trace file are gone."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "session-20250101-000000-abcd1234"

        # Create the session directory and trace file
        session_dir = self._create_session_dir(
            sessions_dir, session_id, with_trace=True,
        )
        trace_file = sessions_dir / f"{session_id}.trace.jsonl"

        # Verify both exist before deletion
        assert session_dir.exists()
        assert trace_file.exists()

        # Create manifest (required by SessionManager)
        manifest_path = sessions_dir / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")

        manager = SessionManager(sessions_dir=sessions_dir)
        result = manager.delete_session(session_id)

        assert result is True
        assert not session_dir.exists(), "Session directory should be deleted"
        assert not trace_file.exists(), "Trace file should be deleted"

    def test_delete_session_no_trace_file_ok(self, tmp_path):
        """Create a session dir without a trace file. Delete the session.
        Verify no error (trace file deletion is optional)."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_id = "session-20250101-000000-abcd1234"

        # Create session directory without trace file
        session_dir = self._create_session_dir(
            sessions_dir, session_id, with_trace=False,
        )
        trace_file = sessions_dir / f"{session_id}.trace.jsonl"

        # Verify setup
        assert session_dir.exists()
        assert not trace_file.exists()

        # Create manifest
        manifest_path = sessions_dir / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")

        manager = SessionManager(sessions_dir=sessions_dir)
        result = manager.delete_session(session_id)

        assert result is True
        assert not session_dir.exists(), "Session directory should be deleted"
