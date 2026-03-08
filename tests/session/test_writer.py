"""Tests for JSONL session writer (Schema v2.1)."""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path

from src.session.persistence.writer import (
    SessionWriter,
    WriteResult,
    create_session_file,
    append_to_session,
)
from src.session.models import Message, FileHistorySnapshot
from src.session.store import MessageStore


class TestWriteResult:
    """Tests for WriteResult dataclass."""

    def test_write_result_success(self):
        result = WriteResult(success=True, bytes_written=100)
        assert result.success == True
        assert result.bytes_written == 100
        assert result.error is None

    def test_write_result_failure(self):
        result = WriteResult(success=False, error="File not found")
        assert result.success == False
        assert result.error == "File not found"
        assert result.bytes_written == 0


class TestSessionWriterLifecycle:
    """Tests for SessionWriter lifecycle."""

    @pytest.mark.asyncio
    async def test_open_does_not_create_file(self):
        """Test that open() does NOT create file (lazy creation on first write)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()
            # File should NOT exist yet (lazy creation)
            assert not file_path.exists()
            assert not writer.is_open  # File not opened yet

            await writer.close()
            assert not writer.is_open

    @pytest.mark.asyncio
    async def test_first_write_creates_parent_directories(self):
        """Test that parent directories are created on first write, not on open()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "nested" / "path" / "session.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()
            # Parent directory should NOT exist yet (lazy creation)
            assert not file_path.parent.exists()

            # Write a message - this should create parent directories
            msg = Message.create_user("Test", "sess-1", None, 1)
            await writer.write_message(msg)
            
            # Now parent directory should exist
            assert file_path.parent.exists()
            assert file_path.exists()

            await writer.close()

    @pytest.mark.asyncio
    async def test_close_without_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            # Should not raise
            await writer.close()

    @pytest.mark.asyncio
    async def test_file_path_property(self):
        file_path = Path("/some/path/session.jsonl")
        writer = SessionWriter(file_path)
        assert writer.file_path == file_path


class TestSessionWriterWrite:
    """Tests for SessionWriter write operations."""

    @pytest.mark.asyncio
    async def test_write_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()

            msg = Message.create_user("Hello", "sess-1", None, 1)
            result = await writer.write_message(msg)

            assert result.success == True
            assert result.bytes_written > 0

            await writer.close()

            # Verify file content
            with open(file_path, 'r') as f:
                content = f.read()
            data = json.loads(content.strip())
            assert data["role"] == "user"
            assert data["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_write_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()

            snapshot = FileHistorySnapshot.create("sess-1")
            result = await writer.write_snapshot(snapshot)

            assert result.success == True

            await writer.close()

            # Verify file content
            with open(file_path, 'r') as f:
                content = f.read()
            data = json.loads(content.strip())
            assert data["type"] == "file_snapshot"

    @pytest.mark.asyncio
    async def test_write_raw(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()

            result = await writer.write_raw({"custom": "data", "key": 123})

            assert result.success == True

            await writer.close()

            # Verify file content
            with open(file_path, 'r') as f:
                content = f.read()
            data = json.loads(content.strip())
            assert data["custom"] == "data"
            assert data["key"] == 123

    @pytest.mark.asyncio
    async def test_write_without_open_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            # Don't open
            msg = Message.create_user("Hello", "sess-1", None, 1)
            result = await writer.write_message(msg)

            assert result.success == False
            assert "not open" in result.error.lower()

    @pytest.mark.asyncio
    async def test_multiple_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()

            for i in range(5):
                msg = Message.create_user(f"Message {i}", "sess-1", None, i+1)
                await writer.write_message(msg)

            await writer.close()

            # Verify file content
            with open(file_path, 'r') as f:
                lines = f.readlines()
            assert len(lines) == 5


class TestSessionWriterStats:
    """Tests for SessionWriter statistics."""

    @pytest.mark.asyncio
    async def test_total_writes_counter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()
            assert writer.total_writes == 0

            for i in range(3):
                msg = Message.create_user(f"Message {i}", "sess-1", None, i+1)
                await writer.write_message(msg)

            assert writer.total_writes == 3

            await writer.close()

    @pytest.mark.asyncio
    async def test_total_bytes_counter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()
            assert writer.total_bytes == 0

            msg = Message.create_user("Hello", "sess-1", None, 1)
            result = await writer.write_message(msg)

            assert writer.total_bytes == result.bytes_written

            await writer.close()


class TestSessionWriterFlush:
    """Tests for SessionWriter flush."""

    @pytest.mark.asyncio
    async def test_flush_persists_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()

            msg = Message.create_user("Hello", "sess-1", None, 1)
            await writer.write_message(msg)
            await writer.flush()

            # Read the file before close
            with open(file_path, 'r') as f:
                content = f.read()
            assert "Hello" in content

            await writer.close()


class TestSessionWriterStoreBinding:
    """Tests for binding writer to MessageStore."""

    @pytest.mark.asyncio
    async def test_bind_to_store_writes_on_add(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)
            store = MessageStore()

            await writer.open()
            writer.bind_to_store(store)

            # Add message to store
            msg = Message.create_user("Store message", "sess-1", None, 1)
            store.add_message(msg)

            # Wait a bit for async write
            await asyncio.sleep(0.1)
            await writer.close()

            # Verify file content
            with open(file_path, 'r') as f:
                content = f.read()
            assert "Store message" in content

    @pytest.mark.asyncio
    async def test_bind_without_open_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)
            store = MessageStore()

            with pytest.raises(RuntimeError) as exc_info:
                writer.bind_to_store(store)

            assert "must be opened" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unbind_stops_writing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)
            store = MessageStore()

            await writer.open()
            writer.bind_to_store(store)

            # Add first message
            msg1 = Message.create_user("First", "sess-1", None, 1)
            store.add_message(msg1)
            await asyncio.sleep(0.1)

            # Unbind
            writer.unbind()

            # Add second message after unbind
            msg2 = Message.create_user("Second", "sess-1", None, 2)
            store.add_message(msg2)
            await asyncio.sleep(0.1)

            await writer.close()

            # Only first message should be in file
            with open(file_path, 'r') as f:
                content = f.read()
            assert "First" in content
            assert "Second" not in content


class TestSessionWriterDrain:
    """Tests for drain-on-close feature (v3.1 Patch 3)."""

    @pytest.mark.asyncio
    async def test_pending_writes_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()
            assert writer.pending_writes == 0

            await writer.close()

    @pytest.mark.asyncio
    async def test_drain_on_close_completes_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path)
            store = MessageStore()

            await writer.open()
            writer.bind_to_store(store)

            # Add multiple messages quickly
            for i in range(10):
                msg = Message.create_user(f"Drain test {i}", "sess-1", None, i+1)
                store.add_message(msg)

            # Close should wait for drain
            await writer.close()

            # All messages should be written
            with open(file_path, 'r') as f:
                lines = f.readlines()

            assert len(lines) == 10


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_session_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "new_session.jsonl"

            result = create_session_file(file_path)

            assert result == file_path
            assert file_path.exists()

    def test_create_session_file_with_nested_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "nested" / "deep" / "session.jsonl"

            result = create_session_file(file_path)

            assert file_path.exists()
            assert file_path.parent.exists()

    @pytest.mark.asyncio
    async def test_append_to_session_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "append_test.jsonl"

            msg = Message.create_user("Appended", "sess-1", None, 1)
            result = await append_to_session(file_path, msg)

            assert result.success == True

            with open(file_path, 'r') as f:
                data = json.loads(f.read().strip())
            assert data["content"] == "Appended"

    @pytest.mark.asyncio
    async def test_append_to_session_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "append_dict.jsonl"

            result = await append_to_session(file_path, {"raw": "dict", "value": 42})

            assert result.success == True

            with open(file_path, 'r') as f:
                data = json.loads(f.read().strip())
            assert data["raw"] == "dict"
            assert data["value"] == 42

    @pytest.mark.asyncio
    async def test_append_to_session_creates_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "new" / "dir" / "session.jsonl"

            msg = Message.create_user("Test", "sess-1", None, 1)
            result = await append_to_session(file_path, msg)

            assert result.success == True
            assert file_path.exists()

    @pytest.mark.asyncio
    async def test_append_to_session_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "multi_append.jsonl"

            for i in range(5):
                msg = Message.create_user(f"Msg {i}", "sess-1", None, i+1)
                await append_to_session(file_path, msg)

            with open(file_path, 'r') as f:
                lines = f.readlines()
            assert len(lines) == 5


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_on_error_callback(self):
        errors = []

        def capture_error(e):
            errors.append(e)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"
            writer = SessionWriter(file_path, on_error=capture_error)

            # Write without calling open() should fail (writer not initialized)
            result = await writer.write_raw({"test": "data"})
            assert result.success == False
            assert "not open" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unicode_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "unicode.jsonl"
            writer = SessionWriter(file_path)

            await writer.open()

            msg = Message.create_user("Hello 你好 مرحبا", "sess-1", None, 1)
            result = await writer.write_message(msg)

            assert result.success == True

            await writer.close()

            # Verify content preserved
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            assert "你好" in content
            assert "مرحبا" in content
