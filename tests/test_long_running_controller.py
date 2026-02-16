"""
Unit Tests for LongRunningController

Tests the simple checkpoint CRUD API for long-running sessions.

Coverage targets:
- Controller initialization
- create_checkpoint: Save current state
- restore_checkpoint: Load previous state
- list_checkpoints: Show available checkpoints
- clear_all_checkpoints: Delete all checkpoints
- get_status: Status information
"""

import pytest
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from src.execution.controller import LongRunningController
from src.execution.checkpoint import CheckpointManager, CheckpointMetadata


class TestLongRunningController:
    """Test suite for LongRunningController"""

    @pytest.fixture
    def temp_project_dir(self):
        """Create temporary project directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_agent(self):
        """Create mock CodingAgent"""
        agent = Mock()

        # Mock memory structure
        agent.memory = Mock()
        agent.memory.working_memory = Mock()
        agent.memory.working_memory.messages = []
        agent.memory.episodic_memory = Mock()
        agent.memory.episodic_memory.compressed_history = []
        agent.memory.task_context = Mock()
        agent.memory.task_context.project_type = "Test Project"
        agent.memory.task_context.key_files = []
        agent.memory.task_context.key_concepts = []

        # Mock tool history and todos
        agent.tool_execution_history = []
        agent.current_todos = None
        agent.working_directory = "/tmp/test_project"

        return agent

    @pytest.fixture
    def controller(self, mock_agent, temp_project_dir):
        """Create LongRunningController with temporary directory"""
        return LongRunningController(
            agent=mock_agent,
            project_dir=temp_project_dir,
            max_checkpoints=3
        )

    def test_initialization(self, mock_agent, temp_project_dir):
        """Test LongRunningController initialization"""
        controller = LongRunningController(
            agent=mock_agent,
            project_dir=temp_project_dir,
            max_checkpoints=5
        )

        assert controller.agent == mock_agent
        assert controller.project_dir == Path(temp_project_dir).resolve()
        assert controller.last_checkpoint_time is None
        assert controller.current_checkpoint_id is None

        # Verify checkpoint directory created
        checkpoint_dir = Path(temp_project_dir) / ".checkpoints"
        assert checkpoint_dir.exists()

    def test_initialization_default_max_checkpoints(self, mock_agent, temp_project_dir):
        """Test that default max_checkpoints is 10"""
        controller = LongRunningController(
            agent=mock_agent,
            project_dir=temp_project_dir
        )

        assert controller.checkpoint_manager.max_checkpoints == 10

    def test_create_checkpoint_success(self, controller, mock_agent):
        """Test successful checkpoint creation"""
        checkpoint_id = controller.create_checkpoint(
            description="Test task",
            current_phase="Phase 1",
            pending_tasks=["Task 1", "Task 2"]
        )

        # Verify checkpoint created
        assert checkpoint_id is not None
        assert len(checkpoint_id) == 8

        # Verify state updated
        assert controller.last_checkpoint_time is not None
        assert controller.current_checkpoint_id == checkpoint_id

        # Verify checkpoint file exists
        checkpoint_file = controller.checkpoint_manager.checkpoint_dir / f"checkpoint_{checkpoint_id}.json"
        assert checkpoint_file.exists()

    def test_create_checkpoint_default_description(self, controller):
        """Test checkpoint creation with default description"""
        checkpoint_id = controller.create_checkpoint()

        assert checkpoint_id is not None
        assert len(checkpoint_id) == 8

    def test_restore_checkpoint_success(self, controller, mock_agent):
        """Test successful checkpoint restore"""
        # Create a checkpoint first
        checkpoint_id = controller.create_checkpoint(description="Test")

        # Restore it
        success = controller.restore_checkpoint(checkpoint_id)

        assert success is True
        assert controller.current_checkpoint_id == checkpoint_id

    def test_restore_checkpoint_not_found(self, controller):
        """Test restoring non-existent checkpoint"""
        success = controller.restore_checkpoint("nonexist")

        assert success is False

    def test_list_checkpoints(self, controller, mock_agent):
        """Test listing checkpoints"""
        # Initially empty
        assert controller.list_checkpoints() == []

        # Create checkpoints
        controller.create_checkpoint(description="First")
        time.sleep(0.01)
        controller.create_checkpoint(description="Second")

        checkpoints = controller.list_checkpoints()
        assert len(checkpoints) == 2

    def test_clear_all_checkpoints(self, controller, mock_agent):
        """Test clearing all checkpoints"""
        # Create 3 checkpoints
        for i in range(3):
            controller.create_checkpoint(description=f"Checkpoint {i}")

        # Verify checkpoints exist
        assert len(controller.list_checkpoints()) == 3

        # Clear all
        count = controller.clear_all_checkpoints()

        # Verify all deleted
        assert count == 3
        assert len(controller.list_checkpoints()) == 0

    def test_clear_all_checkpoints_empty(self, controller):
        """Test clearing when no checkpoints exist"""
        count = controller.clear_all_checkpoints()
        assert count == 0

    def test_get_status(self, controller):
        """Test getting controller status"""
        status = controller.get_status()

        assert status["project_dir"] == str(controller.project_dir)
        assert status["last_checkpoint"] is None
        assert status["last_checkpoint_time"] is None
        assert status["total_checkpoints"] == 0

    def test_get_status_after_checkpoint(self, controller):
        """Test status after creating a checkpoint"""
        checkpoint_id = controller.create_checkpoint(description="Test")

        status = controller.get_status()

        assert status["last_checkpoint"] == checkpoint_id
        assert status["last_checkpoint_time"] is not None
        assert status["total_checkpoints"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
