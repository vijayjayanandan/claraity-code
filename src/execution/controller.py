"""
Long-Running Controller - Simple Checkpoint API

Provides simple checkpoint CRUD operations for long-running sessions.
All user interaction and decision logic handled by CLI.

Design Philosophy:
- Controller = Pure checkpoint API (save/load/list/clear)
- CLI = User interaction (prompts, commands)
- LLM = Smart checkpoint timing (via tool call)

Author: AI Coding Agent Team
Phase: 1 - Self-Testing & Long-Running Execution
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.execution.checkpoint import CheckpointManager, CheckpointMetadata


class LongRunningController:
    """
    Simple checkpoint API for long-running agent sessions.

    Provides 4 core operations:
    - create_checkpoint: Save current state
    - restore_checkpoint: Load previous state
    - list_checkpoints: Show available checkpoints
    - clear_all_checkpoints: Delete all checkpoints

    Usage:
        controller = LongRunningController(agent=coding_agent)

        # User or LLM decides to checkpoint
        checkpoint_id = controller.create_checkpoint("Completed auth module")

        # Later, restore
        controller.restore_checkpoint(checkpoint_id)

    Attributes:
        agent: CodingAgent instance
        checkpoint_manager: CheckpointManager for persistence
        project_dir: Project root directory
    """

    def __init__(
        self,
        agent: Any,  # CodingAgent instance
        project_dir: str = ".",
        max_checkpoints: int = 10,
    ):
        """
        Initialize controller with agent.

        Args:
            agent: CodingAgent instance
            project_dir: Project root directory (default: current directory)
            max_checkpoints: Maximum checkpoints to keep (default: 10)
        """
        self.agent = agent
        self.project_dir = Path(project_dir).resolve()

        # Initialize checkpoint manager
        checkpoint_dir = self.project_dir / ".checkpoints"
        self.checkpoint_manager = CheckpointManager(
            checkpoint_dir=str(checkpoint_dir), max_checkpoints=max_checkpoints
        )

        # Track last checkpoint for metadata
        self.last_checkpoint_time: datetime | None = None
        self.current_checkpoint_id: str | None = None

    def create_checkpoint(
        self,
        description: str = "Ongoing work",
        current_phase: str | None = None,
        pending_tasks: list[str] | None = None,
    ) -> str | None:
        """
        Create checkpoint of current agent state.

        This saves everything needed to resume work later:
        - Conversation history
        - Memory state
        - Tool execution history
        - Files modified

        Args:
            description: What was accomplished (e.g., "Completed auth module")
            current_phase: Current development phase (e.g., "Phase 1")
            pending_tasks: Tasks remaining to complete

        Returns:
            Checkpoint ID if successful, None if failed

        Example:
            >>> checkpoint_id = controller.create_checkpoint("Added user login")
            >>> print(f"Saved: {checkpoint_id}")
            Saved: a1b2c3d4
        """
        try:
            print("\n[INFO] Creating checkpoint...")

            checkpoint_id = self.checkpoint_manager.save_checkpoint(
                agent=self.agent,
                execution_progress=description,
                task_description=description,
                current_phase=current_phase,
                pending_tasks=pending_tasks,
            )

            # Update tracking
            self.last_checkpoint_time = datetime.now()
            self.current_checkpoint_id = checkpoint_id

            print(f"[OK] Checkpoint created: {checkpoint_id}")
            return checkpoint_id

        except Exception as e:
            print(f"[ERROR] Failed to create checkpoint: {e}")
            return None

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Load checkpoint and restore agent state.

        This restores:
        - Conversation history
        - Memory state
        - Task context
        - Tool execution history

        Args:
            checkpoint_id: ID of checkpoint to restore (e.g., "a1b2c3d4")

        Returns:
            True if successful, False if failed

        Example:
            >>> success = controller.restore_checkpoint("a1b2c3d4")
            >>> if success:
            ...     print("Work resumed!")
        """
        try:
            print(f"\n[INFO] Restoring checkpoint: {checkpoint_id}")

            # Load checkpoint
            checkpoint = self.checkpoint_manager.load_checkpoint(checkpoint_id)

            # Restore to agent
            self.checkpoint_manager.restore_to_agent(checkpoint, self.agent)

            # Update tracking
            self.last_checkpoint_time = datetime.fromisoformat(checkpoint.metadata.timestamp)
            self.current_checkpoint_id = checkpoint_id

            print(f"[OK] Checkpoint restored: {checkpoint_id}")
            print(f"[INFO] Restored {len(checkpoint.working_memory)} messages")
            print(f"[INFO] Restored {len(checkpoint.tool_execution_history)} tool calls")

            return True

        except FileNotFoundError:
            print(f"[ERROR] Checkpoint not found: {checkpoint_id}")
            return False
        except Exception as e:
            print(f"[ERROR] Failed to restore checkpoint: {e}")
            return False

    def list_checkpoints(self) -> list[CheckpointMetadata]:
        """
        list all available checkpoints (newest first).

        Returns:
            list of checkpoint metadata (sorted by timestamp, newest first)

        Example:
            >>> checkpoints = controller.list_checkpoints()
            >>> for cp in checkpoints:
            ...     print(f"{cp.checkpoint_id}: {cp.task_description}")
            a1b2c3d4: Completed auth module
            b2c3d4e5: Added user login
        """
        return self.checkpoint_manager.list_checkpoints()

    def clear_all_checkpoints(self) -> int:
        """
        Delete all checkpoints.

        Warning: This is irreversible!

        Returns:
            Number of checkpoints deleted

        Example:
            >>> count = controller.clear_all_checkpoints()
            >>> print(f"Deleted {count} checkpoint(s)")
            Deleted 5 checkpoint(s)
        """
        checkpoints = self.checkpoint_manager.list_checkpoints()
        count = 0

        for checkpoint_meta in checkpoints:
            # Security: Validate checkpoint ID
            if not self._is_valid_checkpoint_id(checkpoint_meta.checkpoint_id):
                continue

            checkpoint_file = (
                self.checkpoint_manager.checkpoint_dir
                / f"checkpoint_{checkpoint_meta.checkpoint_id}.json"
            )

            # Security: Verify file is inside checkpoint directory
            try:
                resolved_path = checkpoint_file.resolve()
                checkpoint_dir_resolved = self.checkpoint_manager.checkpoint_dir.resolve()

                if not str(resolved_path).startswith(str(checkpoint_dir_resolved)):
                    continue

                checkpoint_file.unlink()
                count += 1
            except (OSError, ValueError):
                continue

        print(f"[OK] Deleted {count} checkpoint(s)")
        return count

    def _is_valid_checkpoint_id(self, checkpoint_id: str) -> bool:
        """
        Validate checkpoint ID to prevent path traversal attacks.

        Args:
            checkpoint_id: Checkpoint ID to validate

        Returns:
            True if checkpoint_id is safe (8-char hex), False otherwise
        """
        import re

        return bool(re.match(r"^[a-f0-9]{8}$", checkpoint_id))

    def get_status(self) -> dict:
        """
        Get controller status information.

        Returns:
            Dictionary with current status

        Example:
            >>> status = controller.get_status()
            >>> print(status)
            {
                'project_dir': '/path/to/project',
                'checkpoint_dir': '/path/to/project/.checkpoints',
                'last_checkpoint': 'a1b2c3d4',
                'last_checkpoint_time': '2025-11-17T10:30:00',
                'total_checkpoints': 5
            }
        """
        return {
            "project_dir": str(self.project_dir),
            "checkpoint_dir": str(self.checkpoint_manager.checkpoint_dir),
            "last_checkpoint": self.current_checkpoint_id,
            "last_checkpoint_time": (
                self.last_checkpoint_time.isoformat() if self.last_checkpoint_time else None
            ),
            "total_checkpoints": len(self.list_checkpoints()),
        }
