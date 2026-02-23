"""Tests for TaskState file persistence and TaskUpdateTool schema completeness.

Coverage:
- TaskState persistence: round-trip, auto-load, save-on-create, save-on-update,
  save-on-delete, graceful failures, no-op when path not set
- TaskState auto-cleanup: completed tasks removed on create
- TaskUpdateTool schema: new fields (owner, metadata, addBlocks, addBlockedBy)
- TaskUpdateTool execute: new fields applied correctly via TaskState
"""

import json
import pytest
from pathlib import Path

from src.tools.task_state import TaskState
from src.tools.planning_tool import TaskUpdateTool, TaskCreateTool
from src.tools.base import ToolStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_tasks_from_file(path: Path):
    """Read and parse the JSON tasks file."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


# ===========================================================================
# TaskState File Persistence Tests
# ===========================================================================

class TestTaskStatePersistence:
    """Tests for TaskState JSON file persistence."""

    @pytest.fixture
    def state(self):
        """Create a fresh TaskState instance (no persistence)."""
        return TaskState()

    @pytest.fixture
    def todos_path(self, tmp_path):
        """Return a path for todos.json inside a temp directory."""
        return tmp_path / "sessions" / "test-session" / "todos.json"

    # -- Test 1: Persistence round-trip --

    def test_persistence_round_trip(self, state, todos_path):
        """Create tasks, verify JSON written, then load into a new TaskState
        and confirm identical data."""
        state.set_persistence_path(todos_path)
        state.create(subject="Task A", description="Do A", active_form="Doing A")
        state.create(subject="Task B", description="Do B")

        # Verify file was written with correct content
        assert todos_path.exists()
        saved = _read_tasks_from_file(todos_path)
        assert len(saved) == 2
        assert saved[0]["subject"] == "Task A"
        assert saved[0]["description"] == "Do A"
        assert saved[0]["activeForm"] == "Doing A"
        assert saved[1]["subject"] == "Task B"

        # Load into a brand-new TaskState
        state2 = TaskState()
        state2.set_persistence_path(todos_path)
        loaded = state2.list_all()

        assert len(loaded) == 2
        assert loaded[0]["subject"] == "Task A"
        assert loaded[0]["description"] == "Do A"
        assert loaded[1]["subject"] == "Task B"

    # -- Test 2: Auto-load on set_persistence_path --

    def test_auto_load_on_set_persistence_path(self, tmp_path):
        """Pre-create a JSON file, then call set_persistence_path and verify
        tasks are loaded into memory."""
        todos_path = tmp_path / "todos.json"
        seed_data = [
            {"id": "10", "subject": "Preloaded task", "status": "in_progress",
             "description": "", "activeForm": "Working", "blocks": [],
             "blockedBy": [], "metadata": {}},
        ]
        todos_path.write_text(json.dumps(seed_data), encoding="utf-8")

        state = TaskState()
        assert state.list_all() == []

        state.set_persistence_path(todos_path)
        tasks = state.list_all()

        assert len(tasks) == 1
        assert tasks[0]["id"] == "10"
        assert tasks[0]["subject"] == "Preloaded task"
        assert tasks[0]["status"] == "in_progress"

    # -- Test 3: Save on create --

    def test_save_on_create(self, state, todos_path):
        """Calling create() should write the file."""
        state.set_persistence_path(todos_path)
        assert not todos_path.exists()

        state.create(subject="First task")
        assert todos_path.exists()

        saved = _read_tasks_from_file(todos_path)
        assert len(saved) == 1
        assert saved[0]["subject"] == "First task"

    # -- Test 4: Save on update --

    def test_save_on_update(self, state, todos_path):
        """Calling update() should re-write the file with changes."""
        state.set_persistence_path(todos_path)
        task = state.create(subject="Updateable")

        # Update the task
        state.update(task["id"], status="in_progress", subject="Updated subject")

        saved = _read_tasks_from_file(todos_path)
        assert len(saved) == 1
        assert saved[0]["status"] == "in_progress"
        assert saved[0]["subject"] == "Updated subject"

    # -- Test 5: Save on delete --

    def test_save_on_delete(self, state, todos_path):
        """Deleting a task (status='deleted') should remove it from the file."""
        state.set_persistence_path(todos_path)
        t1 = state.create(subject="Keep me")
        t2 = state.create(subject="Delete me")

        # Verify both exist
        saved = _read_tasks_from_file(todos_path)
        assert len(saved) == 2

        # Delete one
        state.update(t2["id"], status="deleted")

        saved = _read_tasks_from_file(todos_path)
        assert len(saved) == 1
        assert saved[0]["subject"] == "Keep me"

    # -- Test 6: Graceful failure - bad JSON --

    def test_graceful_failure_bad_json(self, tmp_path):
        """Writing garbage to the file should not crash set_persistence_path;
        TaskState should remain empty."""
        todos_path = tmp_path / "todos.json"
        todos_path.write_text("{{{{ not valid json !!!!", encoding="utf-8")

        state = TaskState()
        # Should not raise
        state.set_persistence_path(todos_path)

        # State should be empty (failed load is silently logged)
        assert state.list_all() == []

    # -- Test 7: Graceful failure - missing parent directory --

    def test_missing_parent_dir_created_on_save(self, tmp_path):
        """If the parent directory does not exist, create() should create it
        and save successfully (via _save's mkdir)."""
        deep_path = tmp_path / "a" / "b" / "c" / "todos.json"
        assert not deep_path.parent.exists()

        state = TaskState()
        state.set_persistence_path(deep_path)
        state.create(subject="Deep task")

        assert deep_path.exists()
        saved = _read_tasks_from_file(deep_path)
        assert len(saved) == 1
        assert saved[0]["subject"] == "Deep task"

    # -- Test 8: No persistence when path not set --

    def test_no_persistence_when_path_not_set(self, state, tmp_path):
        """Creating tasks without set_persistence_path should not write any file."""
        state.create(subject="Ephemeral task")

        # No todos.json anywhere in tmp_path
        json_files = list(tmp_path.rglob("*.json"))
        assert json_files == []

    # -- Additional edge cases --

    def test_next_id_continues_after_load(self, tmp_path):
        """After loading from file, _next_id should be set correctly so new
        tasks get non-colliding IDs."""
        todos_path = tmp_path / "todos.json"
        seed_data = [
            {"id": "5", "subject": "Task five", "status": "pending",
             "description": "", "activeForm": "Task five", "blocks": [],
             "blockedBy": [], "metadata": {}},
        ]
        todos_path.write_text(json.dumps(seed_data), encoding="utf-8")

        state = TaskState()
        state.set_persistence_path(todos_path)
        new_task = state.create(subject="Next task")

        # New task ID should be > 5
        assert int(new_task["id"]) > 5

    def test_empty_list_in_file_loads_without_error(self, tmp_path):
        """An empty JSON array should load gracefully (no tasks restored)."""
        todos_path = tmp_path / "todos.json"
        todos_path.write_text("[]", encoding="utf-8")

        state = TaskState()
        state.set_persistence_path(todos_path)

        assert state.list_all() == []

    def test_completed_task_unblocks_dependents_and_saves(self, state, todos_path):
        """Completing a task should remove it from dependents' blockedBy lists,
        and persist the updated state."""
        state.set_persistence_path(todos_path)
        t1 = state.create(subject="Blocker")
        t2 = state.create(subject="Blocked")
        state.update(t2["id"], addBlockedBy=[t1["id"]])

        # Verify blocked
        saved = _read_tasks_from_file(todos_path)
        blocked_task = [t for t in saved if t["id"] == t2["id"]][0]
        assert t1["id"] in blocked_task["blockedBy"]

        # Complete the blocker
        state.update(t1["id"], status="completed")

        # Verify unblocked in file
        saved = _read_tasks_from_file(todos_path)
        blocked_task = [t for t in saved if t["id"] == t2["id"]][0]
        assert t1["id"] not in blocked_task["blockedBy"]


# ===========================================================================
# TaskState Auto-Cleanup on Create Tests
# ===========================================================================

class TestTaskStateAutoCleanup:
    """Tests for auto-cleanup of completed tasks when create() is called."""

    @pytest.fixture
    def state(self):
        return TaskState()

    @pytest.fixture
    def todos_path(self, tmp_path):
        return tmp_path / "sessions" / "test-session" / "todos.json"

    def test_create_cleans_completed_tasks(self, state):
        """Creating a new task should remove all completed tasks."""
        t1 = state.create(subject="Old task A")
        t2 = state.create(subject="Old task B")
        state.update(t1["id"], status="completed")
        state.update(t2["id"], status="completed")

        # Create a new task - should clean up the two completed ones
        t3 = state.create(subject="New task")

        tasks = state.list_all()
        assert len(tasks) == 1
        assert tasks[0]["id"] == t3["id"]
        assert tasks[0]["subject"] == "New task"

    def test_create_preserves_non_completed_tasks(self, state):
        """Only completed tasks are removed; pending and in_progress survive."""
        t1 = state.create(subject="Completed")
        t2 = state.create(subject="In progress")
        t3 = state.create(subject="Pending")
        state.update(t1["id"], status="completed")
        state.update(t2["id"], status="in_progress")

        # Create a new task
        t4 = state.create(subject="Brand new")

        tasks = state.list_all()
        task_ids = {t["id"] for t in tasks}

        # Completed task removed, others preserved
        assert t1["id"] not in task_ids
        assert t2["id"] in task_ids
        assert t3["id"] in task_ids
        assert t4["id"] in task_ids
        assert len(tasks) == 3

    def test_create_with_no_completed_tasks(self, state):
        """When nothing is completed, create should not remove anything."""
        t1 = state.create(subject="Pending task")
        t2 = state.create(subject="Another pending")

        assert len(state.list_all()) == 2

        t3 = state.create(subject="Third task")

        tasks = state.list_all()
        assert len(tasks) == 3
        task_ids = {t["id"] for t in tasks}
        assert t1["id"] in task_ids
        assert t2["id"] in task_ids
        assert t3["id"] in task_ids

    def test_cleanup_persists_to_file(self, state, todos_path):
        """After auto-cleanup, the JSON file should reflect the cleaned state."""
        state.set_persistence_path(todos_path)
        t1 = state.create(subject="Will complete")
        state.update(t1["id"], status="completed")

        # Create new task - triggers cleanup + save
        t2 = state.create(subject="Fresh task")

        saved = _read_tasks_from_file(todos_path)
        assert len(saved) == 1
        assert saved[0]["id"] == t2["id"]
        assert saved[0]["subject"] == "Fresh task"

    def test_next_id_not_reset_after_cleanup(self, state):
        """Task IDs should keep incrementing even after completed tasks are
        cleaned up -- no ID collisions with removed tasks."""
        t1 = state.create(subject="Task 1")  # id=1
        t2 = state.create(subject="Task 2")  # id=2
        state.update(t1["id"], status="completed")
        state.update(t2["id"], status="completed")

        # Both cleaned up on next create
        t3 = state.create(subject="Task 3")

        # ID should be 3 (not 1 or 2)
        assert int(t3["id"]) > int(t2["id"])


# ===========================================================================
# TaskUpdateTool Schema Completeness Tests
# ===========================================================================

class TestTaskUpdateToolSchema:
    """Tests for TaskUpdateTool._get_parameters() schema."""

    @pytest.fixture
    def task_state(self):
        return TaskState()

    @pytest.fixture
    def update_tool(self, task_state):
        return TaskUpdateTool(task_state)

    # -- Test 9: Schema includes all expected fields --

    def test_schema_includes_addBlocks(self, update_tool):
        """Schema must expose addBlocks as an array of strings."""
        params = update_tool._get_parameters()
        props = params["properties"]
        assert "addBlocks" in props
        assert props["addBlocks"]["type"] == "array"
        assert props["addBlocks"]["items"]["type"] == "string"

    def test_schema_includes_addBlockedBy(self, update_tool):
        """Schema must expose addBlockedBy as an array of strings."""
        params = update_tool._get_parameters()
        props = params["properties"]
        assert "addBlockedBy" in props
        assert props["addBlockedBy"]["type"] == "array"
        assert props["addBlockedBy"]["items"]["type"] == "string"

    def test_schema_includes_owner(self, update_tool):
        """Schema must expose owner as a string."""
        params = update_tool._get_parameters()
        props = params["properties"]
        assert "owner" in props
        assert props["owner"]["type"] == "string"

    def test_schema_includes_metadata(self, update_tool):
        """Schema must expose metadata as an object with additionalProperties."""
        params = update_tool._get_parameters()
        props = params["properties"]
        assert "metadata" in props
        assert props["metadata"]["type"] == "object"
        assert props["metadata"]["additionalProperties"] is True

    def test_schema_requires_only_taskId(self, update_tool):
        """Only taskId should be required; all other fields are optional."""
        params = update_tool._get_parameters()
        assert params["required"] == ["taskId"]

    def test_schema_includes_all_original_fields(self, update_tool):
        """Schema should also include the original fields: status, subject,
        description, activeForm."""
        params = update_tool._get_parameters()
        props = params["properties"]
        for field in ("taskId", "status", "subject", "description", "activeForm"):
            assert field in props, f"Missing field: {field}"


# ===========================================================================
# TaskUpdateTool Execute with New Fields
# ===========================================================================

class TestTaskUpdateToolExecute:
    """Tests for TaskUpdateTool.execute() with owner, metadata, addBlocks,
    addBlockedBy fields."""

    @pytest.fixture
    def task_state(self):
        return TaskState()

    @pytest.fixture
    def update_tool(self, task_state):
        return TaskUpdateTool(task_state)

    @pytest.fixture
    def sample_task(self, task_state):
        """Create a sample task to update."""
        return task_state.create(subject="Sample task", description="For testing")

    # -- Test 10: Execute with new fields --

    def test_execute_with_owner(self, update_tool, task_state, sample_task):
        """Setting owner via execute should apply it to the task."""
        result = update_tool.execute(taskId=sample_task["id"], owner="agent-1")

        assert result.status == ToolStatus.SUCCESS
        task = task_state.get(sample_task["id"])
        assert task["owner"] == "agent-1"

    def test_execute_with_metadata(self, update_tool, task_state, sample_task):
        """Setting metadata via execute should merge it into the task."""
        result = update_tool.execute(
            taskId=sample_task["id"],
            metadata={"priority": "high", "sprint": 5}
        )

        assert result.status == ToolStatus.SUCCESS
        task = task_state.get(sample_task["id"])
        assert task["metadata"]["priority"] == "high"
        assert task["metadata"]["sprint"] == 5

    def test_execute_with_metadata_delete_key(self, update_tool, task_state, sample_task):
        """Setting a metadata key to None should remove it."""
        # First add metadata
        task_state.update(sample_task["id"], metadata={"keep": "yes", "remove": "me"})

        # Then delete one key
        result = update_tool.execute(
            taskId=sample_task["id"],
            metadata={"remove": None}
        )

        assert result.status == ToolStatus.SUCCESS
        task = task_state.get(sample_task["id"])
        assert "remove" not in task["metadata"]
        assert task["metadata"]["keep"] == "yes"

    def test_execute_with_addBlocks(self, update_tool, task_state, sample_task):
        """addBlocks should add task IDs to the blocks list."""
        t2 = task_state.create(subject="Dependent task")

        result = update_tool.execute(
            taskId=sample_task["id"],
            addBlocks=[t2["id"]]
        )

        assert result.status == ToolStatus.SUCCESS
        task = task_state.get(sample_task["id"])
        assert t2["id"] in task["blocks"]

    def test_execute_with_addBlockedBy(self, update_tool, task_state, sample_task):
        """addBlockedBy should add task IDs to the blockedBy list."""
        t2 = task_state.create(subject="Prerequisite task")

        result = update_tool.execute(
            taskId=sample_task["id"],
            addBlockedBy=[t2["id"]]
        )

        assert result.status == ToolStatus.SUCCESS
        task = task_state.get(sample_task["id"])
        assert t2["id"] in task["blockedBy"]

    def test_execute_addBlocks_no_duplicates(self, update_tool, task_state, sample_task):
        """Adding the same block ID twice should not create duplicates."""
        t2 = task_state.create(subject="Other task")

        update_tool.execute(taskId=sample_task["id"], addBlocks=[t2["id"]])
        update_tool.execute(taskId=sample_task["id"], addBlocks=[t2["id"]])

        task = task_state.get(sample_task["id"])
        assert task["blocks"].count(t2["id"]) == 1

    def test_execute_nonexistent_task_returns_error(self, update_tool):
        """Updating a task that does not exist should return an error."""
        result = update_tool.execute(taskId="999", status="completed")

        assert result.status == ToolStatus.ERROR
        assert "not found" in result.error

    def test_execute_with_all_new_fields_combined(self, update_tool, task_state, sample_task):
        """Applying owner, metadata, addBlocks, and addBlockedBy in a single
        call should all take effect."""
        t2 = task_state.create(subject="Blocker")
        t3 = task_state.create(subject="Dependent")

        result = update_tool.execute(
            taskId=sample_task["id"],
            owner="test-agent",
            metadata={"label": "important"},
            addBlocks=[t3["id"]],
            addBlockedBy=[t2["id"]],
        )

        assert result.status == ToolStatus.SUCCESS
        task = task_state.get(sample_task["id"])
        assert task["owner"] == "test-agent"
        assert task["metadata"]["label"] == "important"
        assert t3["id"] in task["blocks"]
        assert t2["id"] in task["blockedBy"]
