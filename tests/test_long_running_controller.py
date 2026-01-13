"""
Unit Tests for LongRunningController

Tests long-running session orchestration with comprehensive coverage.

Coverage targets:
- Session initialization with checkpoint detection
- Resume flow: Load checkpoint, present understanding, wait for approval
- Auto-checkpoint: Smart timing at turn boundaries with activity detection
- Manual checkpoint: /checkpoint command handler
- Graceful exit: Ctrl+C handling with save prompt
- Status tracking: Activity recording and checkpoint status
"""

import json
import os
import pytest
import signal
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

from src.execution.controller import LongRunningController
from src.execution.checkpoint import CheckpointManager, ExecutionCheckpoint, CheckpointMetadata


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
            checkpoint_interval_minutes=10,
            max_checkpoints=3
        )

    def test_initialization(self, mock_agent, temp_project_dir):
        """Test LongRunningController initialization"""
        controller = LongRunningController(
            agent=mock_agent,
            project_dir=temp_project_dir,
            checkpoint_interval_minutes=15,
            max_checkpoints=5
        )

        assert controller.agent == mock_agent
        assert controller.project_dir == Path(temp_project_dir).resolve()
        assert controller.checkpoint_interval_minutes == 15
        assert controller.last_checkpoint_time is None
        assert controller.activity_since_checkpoint is False
        assert controller.checkpoint_requested is False

        # Verify checkpoint directory created
        checkpoint_dir = Path(temp_project_dir) / ".checkpoints"
        assert checkpoint_dir.exists()

    def test_should_checkpoint_no_activity(self, controller):
        """Test that should_checkpoint returns False when no activity"""
        controller.last_checkpoint_time = datetime.now() - timedelta(minutes=15)
        controller.activity_since_checkpoint = False

        assert controller.should_checkpoint() is False

    def test_should_checkpoint_too_soon(self, controller):
        """Test that should_checkpoint returns False when interval not elapsed"""
        controller.last_checkpoint_time = datetime.now() - timedelta(minutes=5)
        controller.activity_since_checkpoint = True

        assert controller.should_checkpoint() is False

    def test_should_checkpoint_ready(self, controller):
        """Test that should_checkpoint returns True when conditions met"""
        controller.last_checkpoint_time = datetime.now() - timedelta(minutes=15)
        controller.activity_since_checkpoint = True

        assert controller.should_checkpoint() is True

    def test_should_checkpoint_manual_request(self, controller):
        """Test that should_checkpoint returns True when manually requested"""
        controller.checkpoint_requested = True
        controller.last_checkpoint_time = datetime.now()  # Just checkpointed
        controller.activity_since_checkpoint = False  # No activity

        # Should still checkpoint because manually requested
        assert controller.should_checkpoint() is True

    def test_should_checkpoint_first_checkpoint_too_soon(self, controller):
        """Test that first checkpoint waits for interval"""
        # No last_checkpoint_time (first checkpoint)
        controller.last_checkpoint_time = None
        controller.activity_since_checkpoint = True
        controller.session_start_time = datetime.now() - timedelta(minutes=5)

        # Too soon since session start
        assert controller.should_checkpoint() is False

    def test_should_checkpoint_first_checkpoint_ready(self, controller):
        """Test that first checkpoint triggers after interval"""
        controller.last_checkpoint_time = None
        controller.activity_since_checkpoint = True
        controller.session_start_time = datetime.now() - timedelta(minutes=15)

        assert controller.should_checkpoint() is True

    def test_record_activity(self, controller):
        """Test recording activity"""
        assert controller.activity_since_checkpoint is False

        controller.record_activity("message")
        assert controller.activity_since_checkpoint is True

        controller.record_activity("tool_call")
        assert controller.activity_since_checkpoint is True

    def test_request_checkpoint(self, controller, capsys):
        """Test manual checkpoint request"""
        assert controller.checkpoint_requested is False

        controller.request_checkpoint()

        assert controller.checkpoint_requested is True

        # Verify message printed
        captured = capsys.readouterr()
        assert "Checkpoint will be created" in captured.out

    def test_create_checkpoint_success(self, controller, mock_agent):
        """Test successful checkpoint creation"""
        checkpoint_id = controller.create_checkpoint(
            task_description="Test task",
            current_phase="Phase 1",
            pending_tasks=["Task 1", "Task 2"]
        )

        # Verify checkpoint created
        assert checkpoint_id is not None
        assert len(checkpoint_id) == 8

        # Verify state updated
        assert controller.last_checkpoint_time is not None
        assert controller.activity_since_checkpoint is False
        assert controller.checkpoint_requested is False
        assert controller.current_checkpoint_id == checkpoint_id

        # Verify checkpoint file exists
        checkpoint_file = controller.checkpoint_manager.checkpoint_dir / f"checkpoint_{checkpoint_id}.json"
        assert checkpoint_file.exists()

    def test_create_checkpoint_resets_activity(self, controller, mock_agent):
        """Test that creating checkpoint resets activity flag"""
        controller.activity_since_checkpoint = True
        controller.checkpoint_requested = True

        controller.create_checkpoint("Test")

        assert controller.activity_since_checkpoint is False
        assert controller.checkpoint_requested is False

    def test_get_checkpoint_status(self, controller):
        """Test getting checkpoint status"""
        # Initial status
        status = controller.get_checkpoint_status()

        assert status["current_checkpoint_id"] is None
        assert status["last_checkpoint_time"] is None
        assert status["time_since_checkpoint"] is None
        assert status["activity_since_checkpoint"] is False
        assert status["checkpoint_due"] is False

        # After recording activity and some time
        controller.record_activity("test")
        controller.last_checkpoint_time = datetime.now() - timedelta(minutes=15)
        controller.current_checkpoint_id = "abc12345"

        status = controller.get_checkpoint_status()

        assert status["current_checkpoint_id"] == "abc12345"
        assert status["last_checkpoint_time"] is not None
        assert status["time_since_checkpoint"] is not None
        assert status["activity_since_checkpoint"] is True
        assert status["checkpoint_due"] is True

    @patch('builtins.input', return_value="S")
    def test_prompt_user_for_checkpoint_action_fresh(self, mock_input, controller):
        """Test user choosing to start fresh"""
        checkpoints = [
            CheckpointMetadata(
                checkpoint_id="test123",
                timestamp=datetime.now().isoformat(),
                task_description="Test task",
                working_directory="/tmp/test",
                files_modified_count=5,
                tool_calls_count=10,
                conversation_turns=3
            )
        ]

        action = controller._prompt_user_for_checkpoint_action(checkpoints)
        assert action == "fresh"

    @patch('builtins.input', return_value="R")
    def test_prompt_user_for_checkpoint_action_resume(self, mock_input, controller):
        """Test user choosing to resume"""
        checkpoints = [
            CheckpointMetadata(
                checkpoint_id="test123",
                timestamp=datetime.now().isoformat(),
                task_description="Test task",
                working_directory="/tmp/test",
                files_modified_count=5,
                tool_calls_count=10,
                conversation_turns=3
            )
        ]

        action = controller._prompt_user_for_checkpoint_action(checkpoints)
        assert action == "resume"

    @patch('builtins.input', return_value="C")
    def test_prompt_user_for_checkpoint_action_clear(self, mock_input, controller):
        """Test user choosing to clear checkpoints"""
        checkpoints = [
            CheckpointMetadata(
                checkpoint_id="test123",
                timestamp=datetime.now().isoformat(),
                task_description="Test task",
                working_directory="/tmp/test",
                files_modified_count=5,
                tool_calls_count=10,
                conversation_turns=3
            )
        ]

        action = controller._prompt_user_for_checkpoint_action(checkpoints)
        assert action == "clear"

    @patch('builtins.input', side_effect=["invalid", "X", "R"])
    def test_prompt_user_for_checkpoint_action_invalid_then_valid(self, mock_input, controller, capsys):
        """Test invalid input handling"""
        checkpoints = [
            CheckpointMetadata(
                checkpoint_id="test123",
                timestamp=datetime.now().isoformat(),
                task_description="Test task",
                working_directory="/tmp/test",
                files_modified_count=5,
                tool_calls_count=10,
                conversation_turns=3
            )
        ]

        action = controller._prompt_user_for_checkpoint_action(checkpoints)

        assert action == "resume"

        # Verify warning messages
        captured = capsys.readouterr()
        assert "Invalid choice" in captured.out

    @patch('builtins.input', return_value="1")
    def test_select_checkpoint_to_resume_first(self, mock_input, controller, mock_agent):
        """Test selecting first checkpoint"""
        # Create a real checkpoint
        checkpoint_id = controller.checkpoint_manager.save_checkpoint(
            agent=mock_agent,
            execution_progress="Test",
            task_description="Test task"
        )

        checkpoints = controller.checkpoint_manager.list_checkpoints()

        selected = controller._select_checkpoint_to_resume(checkpoints)

        assert selected is not None
        assert isinstance(selected, ExecutionCheckpoint)
        assert selected.metadata.checkpoint_id == checkpoint_id

    @patch('builtins.input', return_value="2")
    def test_select_checkpoint_to_resume_cancel(self, mock_input, controller, mock_agent):
        """Test cancelling checkpoint selection"""
        # Create a checkpoint
        controller.checkpoint_manager.save_checkpoint(
            agent=mock_agent,
            execution_progress="Test",
            task_description="Test task"
        )

        checkpoints = controller.checkpoint_manager.list_checkpoints()

        # Input "2" should be cancel (option 1 is checkpoint, option 2 is cancel)
        selected = controller._select_checkpoint_to_resume(checkpoints)

        assert selected is None

    @patch('builtins.input', side_effect=["99", "invalid", "1"])
    def test_select_checkpoint_to_resume_invalid_input(self, mock_input, controller, mock_agent, capsys):
        """Test invalid input handling in checkpoint selection"""
        # Create a checkpoint
        controller.checkpoint_manager.save_checkpoint(
            agent=mock_agent,
            execution_progress="Test",
            task_description="Test task"
        )

        checkpoints = controller.checkpoint_manager.list_checkpoints()
        selected = controller._select_checkpoint_to_resume(checkpoints)

        assert selected is not None

        # Verify warning messages
        captured = capsys.readouterr()
        assert "Invalid" in captured.out or "Please enter" in captured.out

    @patch('src.tools.clarity_tools.GetNextTaskTool')
    @patch('builtins.input', return_value="")
    def test_resume_from_checkpoint_success(self, mock_input, mock_tool_class, controller, mock_agent):
        """Test successful resume from checkpoint"""
        # Setup mock for ClarAIty query
        mock_tool = Mock()
        mock_tool.execute.return_value = "[NEXT TASK] Some task from ClarAIty"
        mock_tool_class.return_value = mock_tool

        # Create a checkpoint
        checkpoint_id = controller.checkpoint_manager.save_checkpoint(
            agent=mock_agent,
            execution_progress="Test progress",
            task_description="Test task",
            current_phase="Phase 1",
            pending_tasks=["Task 1"]
        )

        checkpoint = controller.checkpoint_manager.load_checkpoint(checkpoint_id)

        # Resume from checkpoint
        controller._resume_from_checkpoint(checkpoint)

        # Verify checkpoint tracking updated
        assert controller.current_checkpoint_id == checkpoint_id
        assert controller.last_checkpoint_time is not None

        # Verify ClarAIty queried
        mock_tool.execute.assert_called_once()

    @patch('src.tools.clarity_tools.GetNextTaskTool')
    @patch('builtins.input', return_value="")
    def test_resume_from_checkpoint_clarity_error(self, mock_input, mock_tool_class, controller, mock_agent, capsys):
        """Test resume handles ClarAIty query errors gracefully"""
        # Setup mock to raise exception
        mock_tool = Mock()
        mock_tool.execute.side_effect = Exception("ClarAIty error")
        mock_tool_class.return_value = mock_tool
        # Create a checkpoint
        checkpoint_id = controller.checkpoint_manager.save_checkpoint(
            agent=mock_agent,
            execution_progress="Test",
            task_description="Test task"
        )

        checkpoint = controller.checkpoint_manager.load_checkpoint(checkpoint_id)

        # Resume should handle error gracefully
        controller._resume_from_checkpoint(checkpoint)

        # Verify warning printed
        captured = capsys.readouterr()
        assert "Could not query ClarAIty" in captured.out

    def test_start_fresh_session(self, controller, capsys):
        """Test starting fresh session"""
        controller._start_fresh_session()

        # Verify state initialized
        assert controller.last_checkpoint_time is not None
        assert controller.activity_since_checkpoint is False

        # Verify message printed
        captured = capsys.readouterr()
        assert "Fresh session initialized" in captured.out

    @patch('builtins.input', return_value="y")
    def test_clear_all_checkpoints_confirmed(self, mock_input, controller, mock_agent, capsys):
        """Test clearing all checkpoints with confirmation"""
        # Create 3 checkpoints
        for i in range(3):
            controller.checkpoint_manager.save_checkpoint(
                mock_agent,
                f"Progress {i}",
                f"Task {i}"
            )

        # Verify checkpoints exist
        checkpoints_before = controller.checkpoint_manager.list_checkpoints()
        assert len(checkpoints_before) == 3

        # Clear all
        controller._clear_all_checkpoints()

        # Verify all deleted
        checkpoints_after = controller.checkpoint_manager.list_checkpoints()
        assert len(checkpoints_after) == 0

        # Verify message
        captured = capsys.readouterr()
        assert "Deleted 3 checkpoint(s)" in captured.out

    @patch('builtins.input', return_value="n")
    def test_clear_all_checkpoints_cancelled(self, mock_input, controller, mock_agent, capsys):
        """Test cancelling checkpoint deletion"""
        # Create a checkpoint
        controller.checkpoint_manager.save_checkpoint(
            mock_agent,
            "Progress",
            "Task"
        )

        checkpoints_before = controller.checkpoint_manager.list_checkpoints()
        assert len(checkpoints_before) == 1

        # Try to clear but cancel
        controller._clear_all_checkpoints()

        # Verify still exists
        checkpoints_after = controller.checkpoint_manager.list_checkpoints()
        assert len(checkpoints_after) == 1

        # Verify cancellation message
        captured = capsys.readouterr()
        assert "cancelled" in captured.out

    def test_list_all_checkpoints(self, controller, mock_agent, capsys):
        """Test listing all checkpoints"""
        # Create 2 checkpoints
        controller.checkpoint_manager.save_checkpoint(
            mock_agent,
            "Progress 1",
            "Task 1"
        )
        time.sleep(0.01)
        controller.checkpoint_manager.save_checkpoint(
            mock_agent,
            "Progress 2",
            "Task 2"
        )

        checkpoints = controller.checkpoint_manager.list_checkpoints()

        controller._list_all_checkpoints(checkpoints)

        # Verify output
        captured = capsys.readouterr()
        assert "ALL CHECKPOINTS (2)" in captured.out
        assert "Task 1" in captured.out
        assert "Task 2" in captured.out

    def test_handle_exit_no_activity(self, controller, capsys):
        """Test exit handling when no activity"""
        controller.activity_since_checkpoint = False

        result = controller.handle_exit_request()

        assert result is True  # Should proceed with exit
        captured = capsys.readouterr()
        assert "No unsaved work" in captured.out
        assert "Goodbye" in captured.out

    @patch('builtins.input', side_effect=["y", "y"])
    def test_handle_exit_save_checkpoint(self, mock_input, controller, temp_project_dir, capsys):
        """Test exit with checkpoint save attempt"""
        # Create agent (note: Mock will cause serialization to fail, but that's OK for this test)
        agent = Mock()
        agent.memory = Mock()
        agent.memory.working_memory = Mock()
        agent.memory.working_memory.messages = []
        agent.memory.episodic_memory = Mock()
        agent.memory.episodic_memory.compressed_history = []
        agent.memory.task_context = Mock()
        agent.tool_execution_history = []
        agent.current_todos = None
        agent.working_directory = temp_project_dir

        # Replace controller's agent
        controller.agent = agent

        controller.activity_since_checkpoint = True
        controller.last_checkpoint_time = datetime.now() - timedelta(minutes=5)

        result = controller.handle_exit_request()

        # Input sequence: "y" to save, then "y" to exit anyway when save fails
        assert result is True  # Should proceed with exit
        captured = capsys.readouterr()
        assert "unsaved work" in captured.out
        # Checkpoint creation was attempted
        assert "Creating checkpoint" in captured.out

    @patch('builtins.input', side_effect=["n", "y"])
    def test_handle_exit_dont_save(self, mock_input, controller, capsys):
        """Test exit without saving"""
        controller.activity_since_checkpoint = True

        result = controller.handle_exit_request()

        assert result is True  # Should proceed with exit
        captured = capsys.readouterr()
        assert "Goodbye" in captured.out

    @patch('builtins.input', side_effect=["INVALID", "n", "n"])
    def test_handle_exit_cancel_on_save_failure(self, mock_input, controller, temp_project_dir, capsys):
        """Test cancelling exit when checkpoint save fails"""
        # Create agent that will cause serialization error
        agent = Mock()
        agent.memory = Mock()
        agent.memory.working_memory = Mock()
        agent.memory.working_memory.messages = []
        agent.memory.episodic_memory = Mock()
        agent.memory.episodic_memory.compressed_history = []
        agent.memory.task_context = Mock()
        agent.tool_execution_history = []
        agent.current_todos = None
        agent.working_directory = temp_project_dir

        controller.agent = agent
        controller.activity_since_checkpoint = True

        result = controller.handle_exit_request()

        # First input "INVALID" triggers validation warning, defaults to "y" (save)
        # Save fails due to Mock object
        # Then asks "Exit anyway?" -> answer "n" -> cancels exit
        assert result is False  # Should cancel exit
        captured = capsys.readouterr()
        assert "Exit cancelled" in captured.out

    @patch('builtins.input', side_effect=["S"])
    def test_run_no_checkpoints_starts_fresh(self, mock_input, controller, capsys):
        """Test run() with no existing checkpoints"""
        # Run should detect no checkpoints and start fresh
        controller.run()

        captured = capsys.readouterr()
        assert "No existing checkpoints found" in captured.out
        assert "Fresh session initialized" in captured.out

    @patch('builtins.input', side_effect=["S"])
    @patch.object(LongRunningController, '_start_fresh_session')
    def test_run_with_checkpoints_user_chooses_fresh(self, mock_start_fresh, mock_input, controller, mock_agent):
        """Test run() with existing checkpoints, user chooses fresh"""
        # Create a checkpoint
        controller.checkpoint_manager.save_checkpoint(
            mock_agent,
            "Progress",
            "Task"
        )

        controller.run()

        # Verify fresh session started
        mock_start_fresh.assert_called()


class TestLongRunningControllerIntegration:
    """Integration tests with real checkpoint manager"""

    def test_full_checkpoint_cycle(self):
        """Test complete checkpoint creation and resume cycle"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup agent
            agent = Mock()
            agent.memory = Mock()
            agent.memory.working_memory = Mock()
            agent.memory.working_memory.messages = []
            agent.memory.episodic_memory = Mock()
            agent.memory.episodic_memory.compressed_history = []
            agent.memory.task_context = Mock()
            agent.memory.task_context.project_type = "Integration Test"
            agent.memory.task_context.key_files = []
            agent.memory.task_context.key_concepts = []
            agent.tool_execution_history = []
            agent.current_todos = [
                {"content": "Task 1", "status": "in_progress", "activeForm": "Working on task 1"},
                {"content": "Task 2", "status": "pending", "activeForm": "Task 2"}
            ]
            agent.working_directory = tmpdir

            # Create controller
            controller = LongRunningController(
                agent=agent,
                project_dir=tmpdir,
                checkpoint_interval_minutes=1
            )

            # Simulate activity
            controller.record_activity("message")
            controller.session_start_time = datetime.now() - timedelta(minutes=2)

            # Verify checkpoint needed
            assert controller.should_checkpoint() is True

            # Create checkpoint
            checkpoint_id = controller.create_checkpoint(
                task_description="Integration test checkpoint",
                current_phase="Testing"
            )

            assert checkpoint_id is not None

            # Load checkpoint
            checkpoint = controller.checkpoint_manager.load_checkpoint(checkpoint_id)

            # Verify todos saved
            assert checkpoint.current_todos is not None
            assert len(checkpoint.current_todos) == 2
            assert checkpoint.current_todos[0]["content"] == "Task 1"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
