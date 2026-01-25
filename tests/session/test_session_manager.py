"""Tests for SessionManager (Schema v2.1)."""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from datetime import datetime

from src.session.manager import SessionManager, SessionInfo
from src.session.models import Message


class TestSessionInfo:
    """Tests for SessionInfo dataclass."""

    def test_session_info_creation(self):
        info = SessionInfo(
            session_id="sess-123",
            file_path=Path("/test/session.jsonl"),
            created_at=datetime(2024, 1, 1),
            message_count=10,
            is_new=True
        )
        assert info.session_id == "sess-123"
        assert info.message_count == 10
        assert info.is_new == True


class TestSessionManagerCreation:
    """Tests for creating new sessions."""

    def test_create_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session()

            assert info.is_new == True
            assert info.message_count == 0
            assert info.file_path.exists()
            assert manager.is_active == True

    def test_create_session_with_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session(cwd="/custom/path")

            assert manager.context.cwd == "/custom/path"

    def test_create_session_with_git_branch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session(git_branch="feature/test")

            assert manager.context.git_branch == "feature/test"

    def test_create_session_with_slug(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session(slug="test-slug-123")

            assert manager.context.slug == "test-slug-123"

    def test_create_session_generates_slug(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session()

            assert manager.context.slug is not None
            assert "-" in manager.context.slug

    def test_create_session_returns_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session()

            assert manager.store is not None
            assert manager.store.message_count == 0

    def test_create_session_sets_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session()

            assert manager.context is not None
            assert manager.context.session_id == info.session_id


class TestSessionManagerResume:
    """Tests for resuming sessions."""

    def test_resume_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create and populate session
            info = manager.create_session()
            session_id = info.session_id

            msg = Message.create_user("Test message", session_id, None, 1)
            manager.store.add_message(msg)

            # Write to file
            with open(info.file_path, 'w') as f:
                f.write(json.dumps(msg.to_dict()) + "\n")

            # Close and resume
            manager._store = None
            manager._context = None

            resumed_info = manager.resume_session(session_id)

            assert resumed_info.is_new == False
            assert resumed_info.message_count == 1
            assert manager.store.message_count == 1

    def test_resume_nonexistent_session_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Use valid UUID format but nonexistent session
            with pytest.raises(FileNotFoundError):
                manager.resume_session("00000000-0000-0000-0000-000000000000")

    def test_resume_invalid_session_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Invalid session ID format should raise ValueError
            with pytest.raises(ValueError) as exc_info:
                manager.resume_session("../../../etc/passwd")

            assert "Invalid session ID format" in str(exc_info.value)

    def test_resume_with_progress_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create and populate session
            info = manager.create_session()
            session_id = info.session_id

            with open(info.file_path, 'w') as f:
                for i in range(5):
                    msg = Message.create_user(f"Msg {i}", session_id, None, i+1)
                    f.write(json.dumps(msg.to_dict()) + "\n")

            # Track progress
            progress_calls = []

            def on_progress(current, total):
                progress_calls.append((current, total))

            # Close and resume
            manager._store = None
            manager._context = None

            manager.resume_session(session_id, on_progress=on_progress)

            assert len(progress_calls) == 5


class TestSessionManagerLifecycle:
    """Tests for session lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)
            manager.create_session()

            await manager.start_writer()

            # Writer should be bound and ready
            assert manager._writer.is_open == True

            await manager.close()

    @pytest.mark.asyncio
    async def test_close_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)
            manager.create_session()

            await manager.start_writer()
            await manager.close()

            assert manager.is_active == False
            assert manager.store is None
            assert manager.context is None


class TestSessionManagerDiscovery:
    """Tests for session discovery."""

    def test_list_sessions_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            sessions = manager.list_sessions()

            assert sessions == []

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create multiple sessions
            info1 = manager.create_session()
            info2 = manager.create_session()
            info3 = manager.create_session()

            sessions = manager.list_sessions()

            assert len(sessions) == 3

    def test_list_sessions_with_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            for _ in range(5):
                manager.create_session()

            sessions = manager.list_sessions(limit=2)

            assert len(sessions) == 2

    def test_list_sessions_sorted_by_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create sessions with different timestamps
            info1 = manager.create_session()
            info2 = manager.create_session()
            info3 = manager.create_session()

            sessions = manager.list_sessions()

            # Most recent first
            assert sessions[0].session_id == info3.session_id

    def test_get_recent_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            manager.create_session()
            info = manager.create_session()

            recent = manager.get_recent_session()

            assert recent == info.session_id

    def test_get_recent_session_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            recent = manager.get_recent_session()

            assert recent is None

    def test_session_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session()

            assert manager.session_exists(info.session_id) == True
            # Use valid UUID format for nonexistent check
            assert manager.session_exists("00000000-0000-0000-0000-000000000000") == False

    def test_session_exists_invalid_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            with pytest.raises(ValueError):
                manager.session_exists("invalid-id")

    def test_get_session_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Use valid UUID format
            path = manager.get_session_file_path("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

            assert path == Path(tmpdir) / "a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl"

    def test_get_session_file_path_invalid_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            with pytest.raises(ValueError):
                manager.get_session_file_path("test-session")


class TestSessionManagerDelete:
    """Tests for session deletion."""

    def test_delete_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            info = manager.create_session()
            session_id = info.session_id

            # Clear manager state
            manager._store = None

            result = manager.delete_session(session_id)

            assert result == True
            assert not info.file_path.exists()

    def test_delete_nonexistent_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Use valid UUID format for nonexistent session
            result = manager.delete_session("00000000-0000-0000-0000-000000000000")

            assert result == False

    def test_delete_invalid_session_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            with pytest.raises(ValueError):
                manager.delete_session("nonexistent")


class TestSessionManagerAccessors:
    """Tests for accessor properties."""

    def test_store_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            assert manager.store is None

            manager.create_session()

            assert manager.store is not None

    def test_context_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            assert manager.context is None

            manager.create_session()

            assert manager.context is not None

    def test_info_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            assert manager.info is None

            manager.create_session()

            assert manager.info is not None

    def test_is_active_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            assert manager.is_active == False

            manager.create_session()

            assert manager.is_active == True

    def test_sessions_dir_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            assert manager.sessions_dir == Path(tmpdir)


class TestSessionManagerHelpers:
    """Tests for helper functions."""

    def test_generate_slug_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Test multiple slugs
            slugs = [manager._generate_slug() for _ in range(10)]

            for slug in slugs:
                parts = slug.split("-")
                assert len(parts) == 3
                assert parts[2].isdigit()

    def test_sessions_dir_created_on_init(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_path = Path(tmpdir) / "nested" / "sessions"

            manager = SessionManager(sessions_dir=str(sessions_path))

            assert sessions_path.exists()


class TestSessionManagerIntegration:
    """Integration tests for full workflow."""

    @pytest.mark.asyncio
    async def test_full_session_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create session
            info = manager.create_session(slug="test-workflow")
            session_id = info.session_id

            # Start writer
            await manager.start_writer()

            # Add messages
            msg1 = Message.create_user("Hello", session_id, None, manager.store.next_seq())
            manager.store.add_message(msg1)

            msg2 = Message.create_assistant("Hi!", session_id, msg1.uuid, manager.store.next_seq())
            manager.store.add_message(msg2)

            # Wait for writes
            await asyncio.sleep(0.1)

            # Close
            await manager.close()

            # Verify file content
            with open(info.file_path, 'r') as f:
                lines = f.readlines()
            assert len(lines) == 2

            # Resume session
            resumed = manager.resume_session(session_id)
            assert resumed.message_count == 2

    @pytest.mark.asyncio
    async def test_multiple_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create first session
            info1 = manager.create_session()
            await manager.start_writer()

            msg1 = Message.create_user("Session 1", info1.session_id, None, 1)
            manager.store.add_message(msg1)

            await asyncio.sleep(0.1)
            await manager.close()

            # Create second session
            info2 = manager.create_session()
            await manager.start_writer()

            msg2 = Message.create_user("Session 2", info2.session_id, None, 1)
            manager.store.add_message(msg2)

            await asyncio.sleep(0.1)
            await manager.close()

            # Both sessions should exist
            assert manager.session_exists(info1.session_id)
            assert manager.session_exists(info2.session_id)

            # List should show both
            sessions = manager.list_sessions()
            assert len(sessions) == 2
