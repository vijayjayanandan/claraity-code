"""
Test suite for scan_sessions trace file exclusion.

Coverage:
- scan_sessions excludes .trace.jsonl files from results
- scan_sessions returns empty when only trace files exist

Total: 2 tests
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.session.scanner import scan_sessions


class TestScanSessionsTraceExclusion:
    """Verify scan_sessions filters out .trace.jsonl files."""

    @staticmethod
    def _write_session_jsonl(path: Path) -> None:
        """Write a minimal valid session JSONL file."""
        path.write_text(
            json.dumps({"role": "user", "content": "hello"}) + "\n",
            encoding="utf-8",
        )

    def test_scan_excludes_trace_jsonl(self, tmp_path):
        """Create both session-xxx.jsonl and session-xxx.trace.jsonl.
        Verify only the session file appears, not the trace file."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        session_file = sessions_dir / "session-20250101-120000-aabbccdd.jsonl"
        trace_file = sessions_dir / "session-20250101-120000-aabbccdd.trace.jsonl"

        self._write_session_jsonl(session_file)
        self._write_session_jsonl(trace_file)

        results = scan_sessions(sessions_dir)

        assert len(results) == 1
        assert results[0].session_id == "session-20250101-120000-aabbccdd"
        # Verify the trace file was not included
        result_paths = [r.file_path for r in results]
        assert trace_file not in result_paths

    def test_scan_trace_only_returns_empty(self, tmp_path):
        """Create only a .trace.jsonl file. Verify scan_sessions returns empty list."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        trace_file = sessions_dir / "session-20250101-120000-aabbccdd.trace.jsonl"
        self._write_session_jsonl(trace_file)

        results = scan_sessions(sessions_dir)

        assert results == []
