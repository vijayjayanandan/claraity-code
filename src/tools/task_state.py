"""Task state with CRUD operations and optional file persistence."""

import json
from pathlib import Path
from typing import Any, Optional

from src.observability import get_logger

logger = get_logger(__name__)


class TaskState:
    """
    Manages tasks (todos) with CRUD operations and optional JSON persistence.

    When a persistence path is set via `set_persistence_path()`, every mutation
    auto-saves the full task list to a JSON file (one file per session), similar
    to how Claude Code persists todos to ~/.claude/todos/.

    Used by TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool
    and by CodingAgent for pause/resume state tracking.
    """

    def __init__(self):
        self._tasks: dict[str, dict[str, Any]] = {}  # id -> task dict
        self._next_id: int = 1
        self.current_task_id: str | None = None
        self.last_stop_reason: str | None = None
        self.error_budget_resume_count: int = 0
        self.successful_tools_since_resume: int = 0
        self._persistence_path: Path | None = None

    # -- CRUD operations --

    def create(
        self,
        subject: str,
        description: str = "",
        active_form: str = "",
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Create a new task and return it.

        Automatically clears completed tasks before creating the new one,
        keeping the todo list tidy without needing a separate clear tool.
        """
        # Auto-cleanup: remove completed tasks before adding new work
        completed_ids = [tid for tid, t in self._tasks.items() if t.get("status") == "completed"]
        if completed_ids:
            logger.debug(
                "Auto-cleanup: removing %d completed task(s): %s", len(completed_ids), completed_ids
            )
        for tid in completed_ids:
            del self._tasks[tid]

        task_id = str(self._next_id)
        self._next_id += 1
        task = {
            "id": task_id,
            "subject": subject,
            "description": description,
            "activeForm": active_form or subject,
            "status": "pending",
            "blocks": [],
            "blockedBy": [],
            "metadata": metadata or {},
        }
        self._tasks[task_id] = task
        self._save()
        return dict(task)

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Get a task by ID, or None if not found."""
        task = self._tasks.get(task_id)
        return dict(task) if task else None

    def update(self, task_id: str, **fields) -> dict[str, Any] | None:
        """
        Update fields on an existing task. Returns updated task or None.

        Supported fields: subject, description, activeForm, status, metadata,
                          addBlocks, addBlockedBy, owner.
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        for key in ("subject", "description", "activeForm", "status", "owner"):
            if key in fields and fields[key] is not None:
                task[key] = fields[key]

        if "metadata" in fields and fields["metadata"]:
            for k, v in fields["metadata"].items():
                if v is None:
                    task.setdefault("metadata", {}).pop(k, None)
                else:
                    task.setdefault("metadata", {})[k] = v

        if "addBlocks" in fields:
            for bid in fields["addBlocks"]:
                if bid not in task.get("blocks", []):
                    task.setdefault("blocks", []).append(bid)

        if "addBlockedBy" in fields:
            for bid in fields["addBlockedBy"]:
                if bid not in task.get("blockedBy", []):
                    task.setdefault("blockedBy", []).append(bid)

        # Handle deletion
        if task.get("status") == "deleted":
            del self._tasks[task_id]
            self._save()
            return {"id": task_id, "status": "deleted"}

        # When a task completes, remove it from other tasks' blockedBy lists
        if task.get("status") == "completed":
            for other in self._tasks.values():
                if task_id in other.get("blockedBy", []):
                    other["blockedBy"].remove(task_id)

        self._save()
        return dict(task)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all non-deleted tasks."""
        return [dict(t) for t in self._tasks.values()]

    # -- Convenience methods used by CodingAgent --

    def get_todos_list(self) -> list[dict[str, Any]]:
        """Return tasks formatted for serialization (session persistence)."""
        return self.list_all()

    def get_pending_summary(self) -> str:
        """Return a human-readable summary of pending/in-progress tasks."""
        tasks = self.list_all()
        if not tasks:
            return ""

        lines = []
        for t in tasks:
            status = t.get("status", "pending")
            subject = t.get("subject", "")
            if status == "in_progress":
                lines.append(f"  [IN PROGRESS] {t.get('activeForm', subject)}")
            elif status == "pending":
                lines.append(f"  [TODO] {subject}")
            elif status == "completed":
                lines.append(f"  [DONE] {subject}")

        if not lines:
            return ""
        return "\n".join(lines)

    def restore(
        self,
        todos: list[dict[str, Any]],
        current_id: str | None = None,
        stop_reason: str | None = None,
    ):
        """Restore state from a previous session (deserialized from JSONL)."""
        self._tasks.clear()
        max_id = 0
        for t in todos:
            tid = t.get("id", str(self._next_id))
            self._tasks[tid] = dict(t)
            try:
                num = int(tid)
                if num > max_id:
                    max_id = num
            except (ValueError, TypeError):
                pass
        self._next_id = max_id + 1
        self.current_task_id = current_id
        self.last_stop_reason = stop_reason

    # -- File persistence --

    def set_persistence_path(self, path: Path) -> None:
        """
        Set the JSON file path for auto-saving.

        Called by agent.set_session_id() once the session directory is known.
        If the file already exists, loads tasks from it.

        Args:
            path: Full path to the todos.json file
                  e.g. .clarity/sessions/{session_id}/todos.json
        """
        self._persistence_path = path
        if path.exists():
            self._load()

    def _save(self) -> None:
        """Write the full task list to the JSON file (if persistence is enabled)."""
        if self._persistence_path is None:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data = self.list_all()
            self._persistence_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save todos to {self._persistence_path}: {e}")

    def _load(self) -> None:
        """Load tasks from the JSON file into memory."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            text = self._persistence_path.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, list) and data:
                self.restore(
                    data, current_id=self.current_task_id, stop_reason=self.last_stop_reason
                )
                logger.info(f"Loaded {len(data)} tasks from {self._persistence_path}")
        except Exception as e:
            logger.warning(f"Failed to load todos from {self._persistence_path}: {e}")
