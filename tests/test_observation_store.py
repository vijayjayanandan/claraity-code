"""Tests for ObservationStore - Phase 2 of Context Management."""

import os
import shutil
import tempfile
import pytest
from pathlib import Path

from src.memory.observation_store import (
    ObservationStore,
    Observation,
    ObservationPointer,
    Importance,
    classify_importance,
)


class TestObservationPointer:
    """Tests for pointer format utilities."""

    def test_format_pointer(self):
        """Test pointer string generation."""
        pointer = ObservationPointer.format(
            observation_id="abc123def456",
            tool_name="read_file",
            token_count=1500,
            importance="normal"
        )
        assert pointer == "[[OBS#abc123def456 tool=read_file tokens=1500 importance=normal]]"

    def test_parse_pointer_valid(self):
        """Test parsing a valid pointer."""
        pointer = "[[OBS#abc123def456 tool=read_file tokens=1500 importance=normal]]"
        parsed = ObservationPointer.parse(pointer)

        assert parsed is not None
        assert parsed["observation_id"] == "abc123def456"
        assert parsed["tool_name"] == "read_file"
        assert parsed["token_count"] == 1500
        assert parsed["importance"] == "normal"

    def test_parse_pointer_invalid(self):
        """Test parsing invalid pointer formats."""
        assert ObservationPointer.parse("not a pointer") is None
        assert ObservationPointer.parse("[[OBS# incomplete]]") is None
        assert ObservationPointer.parse("") is None

    def test_is_pointer(self):
        """Test pointer detection."""
        assert ObservationPointer.is_pointer(
            "[[OBS#abc123 tool=read_file tokens=100 importance=normal]]"
        )
        assert not ObservationPointer.is_pointer("regular text")
        assert not ObservationPointer.is_pointer("[not a pointer]")

    def test_extract_all(self):
        """Test extracting multiple pointers from text."""
        text = """
        Here is the first observation:
        [[OBS#abc123 tool=read_file tokens=100 importance=normal]]

        And here is another:
        [[OBS#def456 tool=run_command tokens=200 importance=critical]]

        Some more text here.
        """
        pointers = ObservationPointer.extract_all(text)

        assert len(pointers) == 2
        assert pointers[0]["observation_id"] == "abc123"
        assert pointers[1]["observation_id"] == "def456"
        assert pointers[1]["importance"] == "critical"


class TestObservationStore:
    """Tests for ObservationStore CRUD operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test_observations.db")
        yield db_path
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def store(self, temp_db):
        """Create an ObservationStore with temporary database."""
        return ObservationStore(db_path=temp_db)

    def test_save_and_get(self, store):
        """Test saving and retrieving an observation."""
        obs = store.save(
            tool_name="read_file",
            args={"path": "/src/app.py"},
            content="def main():\n    print('Hello')",
            turn_id=5,
            importance=Importance.NORMAL,
        )

        assert obs.observation_id is not None
        assert obs.tool_name == "read_file"
        assert obs.turn_id == 5
        assert obs.importance == Importance.NORMAL
        assert obs.token_count > 0

        # Retrieve
        retrieved = store.get(obs.observation_id)
        assert retrieved is not None
        assert retrieved.content == obs.content
        assert retrieved.tool_name == obs.tool_name

    def test_get_nonexistent(self, store):
        """Test retrieving a non-existent observation."""
        result = store.get("nonexistent123")
        assert result is None

    def test_get_content(self, store):
        """Test retrieving just content."""
        obs = store.save(
            tool_name="run_command",
            args={"command": "ls -la"},
            content="total 100\ndrwxr-xr-x...",
            turn_id=1,
        )

        content = store.get_content(obs.observation_id)
        assert content == "total 100\ndrwxr-xr-x..."

    def test_rehydrate_pointer(self, store):
        """Test rehydrating a pointer to full content."""
        obs = store.save(
            tool_name="read_file",
            args={"path": "/test.py"},
            content="print('test content')",
            turn_id=3,
        )

        pointer = obs.to_pointer()
        content = store.rehydrate(pointer)

        assert content == "print('test content')"

    def test_rehydrate_invalid_pointer(self, store):
        """Test rehydrating an invalid pointer."""
        result = store.rehydrate("not a pointer")
        assert result is None

    def test_find_by_tool_name(self, store):
        """Test finding observations by tool name."""
        store.save("read_file", {"path": "/a.py"}, "content a", turn_id=1)
        store.save("run_command", {"cmd": "ls"}, "content b", turn_id=2)
        store.save("read_file", {"path": "/b.py"}, "content c", turn_id=3)

        results = store.find(tool_name="read_file")
        assert len(results) == 2
        assert all(r.tool_name == "read_file" for r in results)

    def test_find_by_turn_id(self, store):
        """Test finding observations by turn ID."""
        store.save("tool1", {}, "content 1", turn_id=5)
        store.save("tool2", {}, "content 2", turn_id=5)
        store.save("tool3", {}, "content 3", turn_id=6)

        results = store.find(turn_id=5)
        assert len(results) == 2
        assert all(r.turn_id == 5 for r in results)

    def test_find_by_importance(self, store):
        """Test finding observations by importance."""
        store.save("tool1", {}, "content", turn_id=1, importance=Importance.CRITICAL)
        store.save("tool2", {}, "content", turn_id=2, importance=Importance.NORMAL)
        store.save("tool3", {}, "content", turn_id=3, importance=Importance.CRITICAL)

        results = store.find(importance=Importance.CRITICAL)
        assert len(results) == 2
        assert all(r.importance == Importance.CRITICAL for r in results)

    def test_find_by_turn_range(self, store):
        """Test finding observations by turn range."""
        for turn in range(1, 11):
            store.save(f"tool{turn}", {}, f"content {turn}", turn_id=turn)

        results = store.find(min_turn_id=3, max_turn_id=7)
        assert len(results) == 5
        assert all(3 <= r.turn_id <= 7 for r in results)

    def test_find_for_masking(self, store):
        """Test finding observations eligible for masking."""
        # Old observations (turn 1-5)
        for turn in range(1, 6):
            store.save(f"tool{turn}", {}, f"content {turn}", turn_id=turn)

        # Recent observations (turn 16-20)
        for turn in range(16, 21):
            store.save(f"tool{turn}", {}, f"content {turn}", turn_id=turn)

        # Critical observation at turn 3 (should be excluded)
        store.save("critical_tool", {}, "critical content", turn_id=3,
                   importance=Importance.CRITICAL)

        # Current turn is 20, mask_age is 15 (mask turns <= 5)
        results = store.find_for_masking(current_turn_id=20, mask_age=15)

        # Should get 5 old observations, but NOT the critical one
        assert len(results) == 5
        assert all(r.importance != Importance.CRITICAL for r in results)
        assert all(r.turn_id <= 5 for r in results)

    def test_delete(self, store):
        """Test deleting an observation."""
        obs = store.save("tool", {}, "content", turn_id=1)

        # Delete
        deleted = store.delete(obs.observation_id)
        assert deleted is True

        # Verify deleted
        result = store.get(obs.observation_id)
        assert result is None

        # Delete again should return False
        deleted_again = store.delete(obs.observation_id)
        assert deleted_again is False

    def test_delete_before_turn(self, store):
        """Test bulk deletion before a turn."""
        for turn in range(1, 11):
            store.save(f"tool{turn}", {}, f"content {turn}", turn_id=turn)

        # Delete all before turn 5
        deleted = store.delete_before_turn(5)
        assert deleted == 4

        # Verify remaining
        remaining = store.find()
        assert len(remaining) == 6
        assert all(r.turn_id >= 5 for r in remaining)

    def test_get_stats(self, store):
        """Test getting store statistics."""
        store.save("read_file", {}, "content " * 100, turn_id=1,
                   importance=Importance.NORMAL)
        store.save("run_command", {}, "output " * 50, turn_id=2,
                   importance=Importance.CRITICAL)
        store.save("read_file", {}, "more content", turn_id=3,
                   importance=Importance.LOW)

        stats = store.get_stats()

        assert stats["total_count"] == 3
        assert stats["total_tokens"] > 0
        assert "by_importance" in stats
        assert "by_tool" in stats
        assert "read_file" in stats["by_tool"]
        assert stats["by_tool"]["read_file"]["count"] == 2

    def test_clear(self, store):
        """Test clearing all observations."""
        for i in range(5):
            store.save(f"tool{i}", {}, f"content {i}", turn_id=i)

        cleared = store.clear()
        assert cleared == 5

        # Verify empty
        stats = store.get_stats()
        assert stats["total_count"] == 0


class TestObservation:
    """Tests for Observation dataclass."""

    def test_to_pointer(self):
        """Test generating pointer from observation."""
        obs = Observation(
            observation_id="test123",
            tool_name="read_file",
            args_hash="abc",
            content="test content",
            turn_id=5,
            importance=Importance.NORMAL,
            token_count=100,
            created_at=1234567890.0,
        )

        pointer = obs.to_pointer()
        assert "OBS#test123" in pointer
        assert "tool=read_file" in pointer
        assert "tokens=100" in pointer
        assert "importance=normal" in pointer

    def test_to_dict(self):
        """Test serialization to dictionary."""
        obs = Observation(
            observation_id="test123",
            tool_name="read_file",
            args_hash="abc",
            content="test content",
            turn_id=5,
            importance=Importance.CRITICAL,
            token_count=100,
            created_at=1234567890.0,
            metadata={"path": "/test.py"},
        )

        data = obs.to_dict()
        assert data["observation_id"] == "test123"
        assert data["importance"] == "critical"
        assert data["metadata"] == {"path": "/test.py"}


class TestClassifyImportance:
    """Tests for automatic importance classification."""

    def test_critical_error_content(self):
        """Test critical classification for error content."""
        content = "Error: Module not found\nTraceback (most recent call last):\n..."
        assert classify_importance("run_command", content) == Importance.CRITICAL

    def test_critical_test_failure(self):
        """Test critical classification for test failures."""
        content = "FAILED tests/test_app.py::test_main - AssertionError"
        assert classify_importance("run_tests", content) == Importance.CRITICAL

    def test_critical_diff_content(self):
        """Test critical classification for diff content."""
        content = "diff --git a/src/app.py b/src/app.py\n@@...\n+new line"
        assert classify_importance("git_diff", content) == Importance.CRITICAL

    def test_low_directory_listing(self):
        """Test low classification for directory listings."""
        content = "total 100\ndrwxr-xr-x 2 user group 4096 Jan 1 12:00 dir"
        assert classify_importance("run_command", content) == Importance.LOW

    def test_low_tool_name(self):
        """Test low classification based on tool name."""
        content = "some file listing"
        assert classify_importance("list_directory", content) == Importance.LOW
        assert classify_importance("list_files", content) == Importance.LOW

    def test_normal_default(self):
        """Test normal classification for regular content."""
        content = "def hello():\n    return 'world'"
        assert classify_importance("read_file", content) == Importance.NORMAL


class TestTokenCounting:
    """Tests for token counting behavior."""

    @pytest.fixture
    def temp_db(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        yield db_path
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_default_token_counter(self, temp_db):
        """Test default word-based token estimation."""
        store = ObservationStore(db_path=temp_db)

        # 10 words * 1.3 = 13 tokens
        obs = store.save(
            tool_name="test",
            args={},
            content="one two three four five six seven eight nine ten",
            turn_id=1,
        )
        assert obs.token_count == 13

    def test_custom_token_counter(self, temp_db):
        """Test custom token counter function."""
        def custom_counter(text: str) -> int:
            return len(text)  # 1 token per character

        store = ObservationStore(db_path=temp_db, token_counter=custom_counter)

        obs = store.save(
            tool_name="test",
            args={},
            content="hello",  # 5 characters
            turn_id=1,
        )
        assert obs.token_count == 5
