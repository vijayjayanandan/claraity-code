"""Tests for MemoryManager + ObservationStore integration (Phase 2)."""

import os
import tempfile
import pytest

from src.memory import MemoryManager, Importance


class TestMemoryManagerObservationIntegration:
    """Tests for ObservationStore integration in MemoryManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def memory_manager(self, temp_dir):
        """Create MemoryManager with temporary storage."""
        return MemoryManager(
            total_context_tokens=100000,
            working_memory_tokens=50000,
            episodic_memory_tokens=20000,
            persist_directory=temp_dir,
            load_file_memories=False,
        )

    def test_turn_id_increments_on_user_message(self, memory_manager):
        """Test that turn_id increments with each user message."""
        assert memory_manager.current_turn_id == 0

        memory_manager.add_user_message("First message")
        assert memory_manager.current_turn_id == 1

        memory_manager.add_user_message("Second message")
        assert memory_manager.current_turn_id == 2

        # Assistant messages don't increment turn_id
        memory_manager.add_assistant_message("Response")
        assert memory_manager.current_turn_id == 2

    def test_add_tool_observation_small_inline(self, memory_manager):
        """Test that small tool outputs stay inline."""
        memory_manager.add_user_message("Read file")

        content, is_pointer = memory_manager.add_tool_observation(
            tool_name="read_file",
            args={"path": "/test.py"},
            content="print('hello')",  # Small content
            inline_threshold_tokens=500,
        )

        assert not is_pointer
        assert content == "print('hello')"

    def test_add_tool_observation_large_pointer(self, memory_manager):
        """Test that large tool outputs become pointers."""
        memory_manager.add_user_message("Read file")

        large_content = "x " * 1000  # Large content (~1300 tokens)
        content, is_pointer = memory_manager.add_tool_observation(
            tool_name="read_file",
            args={"path": "/large.py"},
            content=large_content,
            inline_threshold_tokens=500,
        )

        assert is_pointer
        assert "[[OBS#" in content
        assert "tool=read_file" in content

    def test_rehydrate_observation(self, memory_manager):
        """Test rehydrating a pointer back to content."""
        memory_manager.add_user_message("Read file")

        original_content = "def important_function(): pass"
        pointer, is_pointer = memory_manager.add_tool_observation(
            tool_name="read_file",
            args={"path": "/important.py"},
            content=original_content,
            inline_threshold_tokens=10,  # Force pointer
        )

        assert is_pointer

        # Rehydrate
        recovered = memory_manager.rehydrate_observation(pointer)
        assert recovered == original_content

    def test_auto_importance_classification_critical(self, memory_manager):
        """Test auto-classification of critical content."""
        memory_manager.add_user_message("Run tests")

        error_content = "FAILED test_app.py - AssertionError: expected 1 got 2"
        content, is_pointer = memory_manager.add_tool_observation(
            tool_name="run_tests",
            args={},
            content=error_content,
        )

        # Critical content should stay inline (if small)
        assert not is_pointer

        # Verify it was classified as critical
        stats = memory_manager.get_observation_stats()
        assert "critical" in stats["by_importance"]

    def test_auto_importance_classification_low(self, memory_manager):
        """Test auto-classification of low importance content."""
        memory_manager.add_user_message("List files")

        dir_content = "total 100\ndrwxr-xr-x 2 user group 4096 file1\n" * 50
        content, is_pointer = memory_manager.add_tool_observation(
            tool_name="list_directory",
            args={"path": "/"},
            content=dir_content,
            inline_threshold_tokens=100,
        )

        # Large low-importance content becomes pointer
        assert is_pointer

    def test_observation_stats(self, memory_manager):
        """Test observation statistics."""
        memory_manager.add_user_message("Multiple operations")

        # Add several observations
        memory_manager.add_tool_observation(
            "read_file", {"path": "/a.py"}, "content a", inline_threshold_tokens=1000
        )
        memory_manager.add_tool_observation(
            "read_file", {"path": "/b.py"}, "content b", inline_threshold_tokens=1000
        )
        memory_manager.add_tool_observation(
            "run_command", {"cmd": "ls"}, "output", inline_threshold_tokens=1000
        )

        stats = memory_manager.get_observation_stats()

        assert stats["total_count"] == 3
        assert "read_file" in stats["by_tool"]
        assert stats["by_tool"]["read_file"]["count"] == 2

    def test_mask_old_observations_count(self, memory_manager):
        """Test finding maskable observations."""
        # Create observations across multiple turns
        for i in range(20):
            memory_manager.add_user_message(f"Message {i}")
            memory_manager.add_tool_observation(
                f"tool_{i}", {}, f"content {i}", inline_threshold_tokens=1000
            )

        # Find maskable (older than 15 turns)
        maskable_count = memory_manager.mask_old_observations(mask_age=15)

        # Turns 1-5 should be maskable (current turn is 20)
        assert maskable_count >= 4


class TestObservationStoreFeatureFlag:
    """Tests for ObservationStore feature flag behavior."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_observation_store_initialized(self, temp_dir):
        """Test that ObservationStore is initialized with MemoryManager."""
        mm = MemoryManager(
            persist_directory=temp_dir,
            load_file_memories=False,
        )

        assert mm.observation_store is not None
        assert hasattr(mm, 'add_tool_observation')
        assert hasattr(mm, 'rehydrate_observation')


class TestTurnIdPersistence:
    """Tests for turn_id behavior across operations."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_turn_id_preserved_in_observation(self, temp_dir):
        """Test that observations record the correct turn_id."""
        mm = MemoryManager(
            persist_directory=temp_dir,
            load_file_memories=False,
        )

        # Turn 1
        mm.add_user_message("First turn")
        mm.add_tool_observation("tool1", {}, "content 1", inline_threshold_tokens=1000)

        # Turn 2
        mm.add_user_message("Second turn")
        mm.add_tool_observation("tool2", {}, "content 2", inline_threshold_tokens=1000)

        # Verify turn IDs
        turn_1_obs = mm.observation_store.find(turn_id=1)
        turn_2_obs = mm.observation_store.find(turn_id=2)

        assert len(turn_1_obs) == 1
        assert turn_1_obs[0].tool_name == "tool1"
        assert len(turn_2_obs) == 1
        assert turn_2_obs[0].tool_name == "tool2"
