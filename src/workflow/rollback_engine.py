"""Rollback Engine for reverting failed changes.

Coordinates rollback operations using FileStateTracker and optional git integration.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import subprocess
import logging

from src.workflow.file_state_tracker import FileStateTracker, FileState

logger = logging.getLogger(__name__)


@dataclass
class RollbackResult:
    """Result of a rollback operation."""
    success: bool
    files_restored: List[str]
    files_deleted: List[str]
    errors: List[str]
    method: str  # 'file' or 'git'

    def __str__(self):
        if self.success:
            msg = f"✓ Rollback successful via {self.method}"
            if self.files_restored:
                msg += f"\n  Restored {len(self.files_restored)} file(s)"
            if self.files_deleted:
                msg += f"\n  Deleted {len(self.files_deleted)} file(s)"
        else:
            msg = f"✗ Rollback failed"
            if self.errors:
                msg += f"\n  Errors: {', '.join(self.errors)}"
        return msg


class RollbackEngine:
    """Executes rollback operations to revert failed changes."""

    def __init__(self, tracker: FileStateTracker, use_git: bool = True):
        """Initialize the rollback engine.

        Args:
            tracker: FileStateTracker instance with captured states
            use_git: Whether to attempt git-based rollback
        """
        self.tracker = tracker
        self.use_git = use_git

    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def rollback_step(self, step_id: int) -> RollbackResult:
        """Rollback changes from a specific step.

        Args:
            step_id: ID of the step to rollback

        Returns:
            RollbackResult with rollback details
        """
        logger.info(f"Rolling back step {step_id}")

        # Get states for this step
        states = self.tracker.get_states_for_step(step_id)

        if not states:
            logger.warning(f"No states found for step {step_id}")
            return RollbackResult(
                success=False,
                files_restored=[],
                files_deleted=[],
                errors=[f"No states found for step {step_id}"],
                method="none"
            )

        # Attempt file-based rollback
        return self._rollback_files(states)

    def rollback_all(self) -> RollbackResult:
        """Rollback all tracked changes.

        Returns:
            RollbackResult with rollback details
        """
        logger.info("Rolling back all changes")

        # Try git-based rollback first if available
        if self.use_git and self.is_git_repo():
            git_result = self._rollback_with_git()
            if git_result.success:
                return git_result

        # Fallback to file-based rollback
        all_files = self.tracker.get_modified_files()

        if not all_files:
            return RollbackResult(
                success=True,
                files_restored=[],
                files_deleted=[],
                errors=[],
                method="none"
            )

        # Get most recent state for each file
        states = []
        for file_path in all_files:
            state = self.tracker.get_state(file_path)
            if state:
                states.append(state)

        return self._rollback_files(states)

    def _rollback_files(self, states: List[FileState]) -> RollbackResult:
        """Rollback files to their captured states.

        Args:
            states: List of FileState objects to restore

        Returns:
            RollbackResult with rollback details
        """
        files_restored = []
        files_deleted = []
        errors = []

        for state in states:
            try:
                path = Path(state.file_path)

                if state.exists:
                    # File existed before - restore it
                    if state.content is not None:
                        path.write_text(state.content)
                        files_restored.append(state.file_path)
                        logger.debug(f"Restored file: {state.file_path}")
                    else:
                        errors.append(f"No content saved for {state.file_path}")
                else:
                    # File was created by step - delete it
                    if path.exists():
                        path.unlink()
                        files_deleted.append(state.file_path)
                        logger.debug(f"Deleted file: {state.file_path}")

            except Exception as e:
                error_msg = f"Failed to rollback {state.file_path}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)

        success = len(errors) == 0

        return RollbackResult(
            success=success,
            files_restored=files_restored,
            files_deleted=files_deleted,
            errors=errors,
            method="file"
        )

    def _rollback_with_git(self) -> RollbackResult:
        """Rollback using git reset.

        Returns:
            RollbackResult with rollback details
        """
        try:
            # Get list of modified files
            result = subprocess.run(
                ['git', 'diff', '--name-only', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return RollbackResult(
                    success=False,
                    files_restored=[],
                    files_deleted=[],
                    errors=[f"Git diff failed: {result.stderr}"],
                    method="git"
                )

            modified_files = result.stdout.strip().split('\n') if result.stdout.strip() else []

            # Reset to HEAD
            result = subprocess.run(
                ['git', 'reset', '--hard', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return RollbackResult(
                    success=False,
                    files_restored=[],
                    files_deleted=[],
                    errors=[f"Git reset failed: {result.stderr}"],
                    method="git"
                )

            # Clean untracked files
            subprocess.run(
                ['git', 'clean', '-fd'],
                capture_output=True,
                timeout=10
            )

            logger.info(f"Git rollback successful: {len(modified_files)} files")

            return RollbackResult(
                success=True,
                files_restored=modified_files,
                files_deleted=[],
                errors=[],
                method="git"
            )

        except subprocess.TimeoutExpired:
            return RollbackResult(
                success=False,
                files_restored=[],
                files_deleted=[],
                errors=["Git command timed out"],
                method="git"
            )
        except Exception as e:
            return RollbackResult(
                success=False,
                files_restored=[],
                files_deleted=[],
                errors=[f"Git rollback error: {e}"],
                method="git"
            )
