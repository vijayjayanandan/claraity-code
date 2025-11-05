"""File State Tracker for Rollback System.

Captures file states before modifications to enable rollback on failure.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class FileState:
    """Represents a captured file state."""
    file_path: str
    content: Optional[str]
    exists: bool
    timestamp: datetime
    step_id: int

    def __str__(self):
        status = "exists" if self.exists else "new"
        return f"FileState({self.file_path}, {status}, step={self.step_id})"


class FileStateTracker:
    """Tracks file states before modifications for rollback capability."""

    def __init__(self):
        """Initialize the file state tracker."""
        self.states: Dict[str, List[FileState]] = {}
        self.current_step_id: int = 0

    def set_step(self, step_id: int):
        """Set the current step ID for tracking."""
        self.current_step_id = step_id
        logger.debug(f"FileStateTracker: Set current step to {step_id}")

    def capture_state(self, file_path: str) -> FileState:
        """Capture the current state of a file.

        Args:
            file_path: Path to the file to track

        Returns:
            FileState object representing the captured state
        """
        path = Path(file_path)

        # Check if file exists
        exists = path.exists()
        content = None

        if exists:
            try:
                content = path.read_text()
                logger.debug(f"Captured state for existing file: {file_path} ({len(content)} chars)")
            except Exception as e:
                logger.warning(f"Failed to read file {file_path}: {e}")
                content = None
        else:
            logger.debug(f"Captured state for new file: {file_path}")

        # Create state object
        state = FileState(
            file_path=str(path.absolute()),
            content=content,
            exists=exists,
            timestamp=datetime.now(),
            step_id=self.current_step_id
        )

        # Store state (keep history for each file)
        if state.file_path not in self.states:
            self.states[state.file_path] = []
        self.states[state.file_path].append(state)

        return state

    def get_state(self, file_path: str, step_id: Optional[int] = None) -> Optional[FileState]:
        """Get the captured state for a file.

        Args:
            file_path: Path to the file
            step_id: Optional step ID to get state from. If None, gets most recent.

        Returns:
            FileState object if found, None otherwise
        """
        path = str(Path(file_path).absolute())

        if path not in self.states:
            return None

        states = self.states[path]

        if step_id is None:
            # Return most recent state
            return states[-1] if states else None

        # Find state for specific step
        for state in reversed(states):
            if state.step_id == step_id:
                return state

        return None

    def get_modified_files(self) -> List[str]:
        """Get list of all tracked file paths.

        Returns:
            List of file paths that have been tracked
        """
        return list(self.states.keys())

    def get_states_for_step(self, step_id: int) -> List[FileState]:
        """Get all file states captured for a specific step.

        Args:
            step_id: Step ID to get states for

        Returns:
            List of FileState objects for the step
        """
        result = []
        for file_path, states in self.states.items():
            for state in states:
                if state.step_id == step_id:
                    result.append(state)
        return result

    def clear(self):
        """Clear all tracked states."""
        self.states.clear()
        self.current_step_id = 0
        logger.debug("FileStateTracker: Cleared all states")

    def clear_step(self, step_id: int):
        """Clear states for a specific step.

        Args:
            step_id: Step ID to clear states for
        """
        for file_path in list(self.states.keys()):
            self.states[file_path] = [
                state for state in self.states[file_path]
                if state.step_id != step_id
            ]
            # Remove empty lists
            if not self.states[file_path]:
                del self.states[file_path]

        logger.debug(f"FileStateTracker: Cleared states for step {step_id}")

    def get_summary(self) -> str:
        """Get a summary of tracked states.

        Returns:
            Human-readable summary string
        """
        if not self.states:
            return "No files tracked"

        lines = [f"Tracked {len(self.states)} file(s):"]
        for file_path, states in self.states.items():
            lines.append(f"  - {file_path} ({len(states)} state(s))")

        return "\n".join(lines)
