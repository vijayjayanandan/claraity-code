"""Tests for rollback system integration."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock

from src.workflow.file_state_tracker import FileStateTracker, FileState
from src.workflow.rollback_engine import RollbackEngine, RollbackResult
from src.workflow.execution_engine import ExecutionEngine, StepResult
from src.workflow.task_planner import ExecutionPlan, PlanStep
from src.tools import ToolExecutor


class TestFileStateTracker:
    """Test FileStateTracker functionality."""

    def test_initialization(self):
        """Test FileStateTracker initialization."""
        tracker = FileStateTracker()
        assert tracker.current_step_id == 0
        assert len(tracker.states) == 0

    def test_set_step(self):
        """Test setting current step ID."""
        tracker = FileStateTracker()
        tracker.set_step(5)
        assert tracker.current_step_id == 5

    def test_capture_state_existing_file(self, tmp_path):
        """Test capturing state of an existing file."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        # Capture state
        tracker = FileStateTracker()
        tracker.set_step(1)
        state = tracker.capture_state(str(test_file))

        assert state.file_path == str(test_file.absolute())
        assert state.content == test_content
        assert state.exists is True
        assert state.step_id == 1

    def test_capture_state_new_file(self, tmp_path):
        """Test capturing state of a non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        tracker = FileStateTracker()
        tracker.set_step(2)
        state = tracker.capture_state(str(test_file))

        assert state.file_path == str(test_file.absolute())
        assert state.content is None
        assert state.exists is False
        assert state.step_id == 2

    def test_get_state_most_recent(self, tmp_path):
        """Test retrieving most recent state."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Version 1")

        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(test_file))

        # Modify and capture again
        test_file.write_text("Version 2")
        tracker.set_step(2)
        state2 = tracker.capture_state(str(test_file))

        # Get most recent state
        recent = tracker.get_state(str(test_file))
        assert recent.step_id == 2
        assert recent.content == "Version 2"

    def test_get_state_for_specific_step(self, tmp_path):
        """Test retrieving state for specific step."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Version 1")

        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(test_file))

        test_file.write_text("Version 2")
        tracker.set_step(2)
        tracker.capture_state(str(test_file))

        # Get state for step 1
        state1 = tracker.get_state(str(test_file), step_id=1)
        assert state1.step_id == 1
        assert state1.content == "Version 1"

    def test_get_modified_files(self, tmp_path):
        """Test getting list of tracked files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        tracker = FileStateTracker()
        tracker.capture_state(str(file1))
        tracker.capture_state(str(file2))

        modified = tracker.get_modified_files()
        assert len(modified) == 2
        assert str(file1.absolute()) in modified
        assert str(file2.absolute()) in modified

    def test_get_states_for_step(self, tmp_path):
        """Test getting all states for a specific step."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(file1))
        tracker.capture_state(str(file2))

        states = tracker.get_states_for_step(1)
        assert len(states) == 2

    def test_clear(self, tmp_path):
        """Test clearing all states."""
        test_file = tmp_path / "test.txt"

        tracker = FileStateTracker()
        tracker.set_step(5)
        tracker.capture_state(str(test_file))

        tracker.clear()
        assert len(tracker.states) == 0
        assert tracker.current_step_id == 0

    def test_clear_step(self, tmp_path):
        """Test clearing states for specific step."""
        file1 = tmp_path / "file1.txt"

        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(file1))

        tracker.set_step(2)
        tracker.capture_state(str(file1))

        # Clear step 1
        tracker.clear_step(1)

        # Step 2 should still exist
        state = tracker.get_state(str(file1), step_id=2)
        assert state is not None
        assert state.step_id == 2

        # Step 1 should be gone
        state = tracker.get_state(str(file1), step_id=1)
        assert state is None


class TestRollbackEngine:
    """Test RollbackEngine functionality."""

    def test_initialization(self):
        """Test RollbackEngine initialization."""
        tracker = FileStateTracker()
        engine = RollbackEngine(tracker, use_git=False)

        assert engine.tracker is tracker
        assert engine.use_git is False

    def test_rollback_step_no_states(self):
        """Test rollback when no states exist."""
        tracker = FileStateTracker()
        engine = RollbackEngine(tracker, use_git=False)

        result = engine.rollback_step(1)

        assert result.success is False
        assert "No states found" in result.errors[0]

    def test_rollback_step_restore_file(self, tmp_path):
        """Test rolling back a modified file."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        # Capture original state
        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(test_file))

        # Modify file
        modified_content = "Modified content"
        test_file.write_text(modified_content)

        # Rollback
        engine = RollbackEngine(tracker, use_git=False)
        result = engine.rollback_step(1)

        assert result.success is True
        assert result.method == "file"
        assert len(result.files_restored) == 1
        assert test_file.read_text() == original_content

    def test_rollback_step_delete_new_file(self, tmp_path):
        """Test rolling back a newly created file."""
        test_file = tmp_path / "new_file.txt"

        # Capture state before file exists
        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(test_file))

        # Create file
        test_file.write_text("New content")
        assert test_file.exists()

        # Rollback
        engine = RollbackEngine(tracker, use_git=False)
        result = engine.rollback_step(1)

        assert result.success is True
        assert len(result.files_deleted) == 1
        assert not test_file.exists()

    def test_rollback_all(self, tmp_path):
        """Test rolling back all changes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        file1.write_text("Original 1")
        file2.write_text("Original 2")

        # Capture states
        tracker = FileStateTracker()
        tracker.set_step(1)
        tracker.capture_state(str(file1))

        tracker.set_step(2)
        tracker.capture_state(str(file2))

        # Modify files
        file1.write_text("Modified 1")
        file2.write_text("Modified 2")

        # Rollback all
        engine = RollbackEngine(tracker, use_git=False)
        result = engine.rollback_all()

        assert result.success is True
        assert len(result.files_restored) == 2
        assert file1.read_text() == "Original 1"
        assert file2.read_text() == "Original 2"

    def test_rollback_handles_missing_content(self, tmp_path):
        """Test rollback handles case where content wasn't saved."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content")

        tracker = FileStateTracker()
        tracker.set_step(1)

        # Manually create state without content
        state = FileState(
            file_path=str(test_file.absolute()),
            content=None,  # No content saved
            exists=True,
            timestamp=tracker.state_tracker.datetime.now() if hasattr(tracker, 'state_tracker') else None,
            step_id=1
        )
        tracker.states[str(test_file.absolute())] = [state]

        # Try to rollback
        engine = RollbackEngine(tracker, use_git=False)
        result = engine.rollback_step(1)

        # Should fail with error about no content
        assert result.success is False
        assert any("No content saved" in err for err in result.errors)


class TestExecutionEngineRollbackIntegration:
    """Test ExecutionEngine integration with rollback system."""

    @pytest.fixture
    def mock_tool_executor(self):
        """Create a mock ToolExecutor."""
        executor = Mock(spec=ToolExecutor)
        executor.tools = {
            'write_file': Mock(),
            'read_file': Mock(),
        }
        return executor

    def test_execution_engine_rollback_disabled(self, mock_tool_executor):
        """Test ExecutionEngine with rollback disabled."""
        engine = ExecutionEngine(
            tool_executor=mock_tool_executor,
            enable_rollback=False
        )

        assert engine.enable_rollback is False
        assert engine.state_tracker is None
        assert engine.rollback_engine is None

    def test_execution_engine_rollback_enabled(self, mock_tool_executor):
        """Test ExecutionEngine with rollback enabled."""
        engine = ExecutionEngine(
            tool_executor=mock_tool_executor,
            enable_rollback=True
        )

        assert engine.enable_rollback is True
        assert engine.state_tracker is not None
        assert engine.rollback_engine is not None

    def test_is_file_modifying_step(self, mock_tool_executor):
        """Test identification of file-modifying steps."""
        engine = ExecutionEngine(
            tool_executor=mock_tool_executor,
            enable_rollback=True
        )

        # File modifying actions
        write_step = PlanStep(
            id=1,
            description="Write file",
            action_type="write",
            arguments={"file_path": "test.txt"},
            dependencies=[],
            risk="low"
        )
        assert engine._is_file_modifying_step(write_step) is True

        edit_step = PlanStep(
            id=2,
            description="Edit file",
            action_type="edit",
            arguments={"file_path": "test.txt"},
            dependencies=[],
            risk="low"
        )
        assert engine._is_file_modifying_step(edit_step) is True

        # Non-modifying action
        read_step = PlanStep(
            id=3,
            description="Read file",
            action_type="read",
            arguments={"file_path": "test.txt"},
            dependencies=[],
            risk="low"
        )
        assert engine._is_file_modifying_step(read_step) is False

    def test_state_capture_during_execution(self, mock_tool_executor, tmp_path):
        """Test that file states are captured during step execution."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original")

        # Mock tool execution
        mock_result = Mock()
        mock_result.is_success.return_value = True
        mock_result.output = "File written"
        mock_result.metadata = {}
        mock_tool_executor.execute_tool.return_value = mock_result

        # Create engine
        engine = ExecutionEngine(
            tool_executor=mock_tool_executor,
            enable_rollback=True,
            enable_verification=False  # Disable verification for simplicity
        )

        # Create step
        step = PlanStep(
            id=1,
            description="Write file",
            action_type="write",
            arguments={"file_path": str(test_file)},
            dependencies=[],
            risk="low",
            tool="write_file"
        )

        # Execute step
        result = engine._execute_step(step)

        # Verify state was captured
        assert result.success is True
        state = engine.state_tracker.get_state(str(test_file))
        assert state is not None
        assert state.step_id == 1
        assert state.content == "Original"


class TestRollbackWithVerification:
    """Test rollback integration with verification layer."""

    @pytest.fixture
    def mock_tool_executor(self):
        """Create a mock ToolExecutor."""
        executor = Mock(spec=ToolExecutor)
        executor.tools = {
            'write_file': Mock(),
        }
        return executor

    @pytest.fixture
    def mock_verifier(self):
        """Create a mock VerificationLayer."""
        verifier = Mock()
        return verifier

    def test_rollback_on_verification_failure(self, mock_tool_executor, mock_verifier, tmp_path):
        """Test that rollback is triggered when verification fails."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("print('original')")

        # Mock successful tool execution
        mock_result = Mock()
        mock_result.is_success.return_value = True
        mock_result.output = "File written"
        mock_result.metadata = {}
        mock_tool_executor.execute_tool.return_value = mock_result

        # Mock verification failure
        mock_verification_result = Mock()
        mock_verification_result.passed = False
        mock_verification_result.errors = ["Syntax error"]
        mock_verification_result.warnings = []
        mock_verifier.verify_file.return_value = mock_verification_result

        # Create engine
        engine = ExecutionEngine(
            tool_executor=mock_tool_executor,
            enable_rollback=True,
            enable_verification=True
        )
        engine.verifier = mock_verifier

        # Create plan with one step
        step = PlanStep(
            id=1,
            description="Write file",
            action_type="write",
            arguments={"file_path": str(test_file)},
            dependencies=[],
            risk="low",
            tool="write_file"
        )

        from src.workflow.task_analyzer import TaskType

        plan = ExecutionPlan(
            task_description="Test task",
            task_type=TaskType.FEATURE,
            steps=[step],
            total_estimated_time="1 minute",
            overall_risk="low",
            requires_approval=False,
            success_criteria=[],
            rollback_strategy="Automatic rollback on failure"
        )

        # Execute plan (with mocked progress callback to suppress output)
        def mock_progress(step_id, status, msg):
            pass

        engine.progress_callback = mock_progress

        # Execute plan
        result = engine.execute_plan(plan)

        # Verify rollback was attempted
        assert len(result.step_results) == 1
        step_result = result.step_results[0]
        assert 'rollback' in step_result.metadata
        rollback_result = step_result.metadata['rollback']
        assert isinstance(rollback_result, RollbackResult)
