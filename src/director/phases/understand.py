"""
UnderstandPhaseHandler - checkpoint 1.

Validates that the task description is usable,
and transforms raw exploration data into a ContextDocument.
"""

from datetime import datetime
from typing import Any, Optional

from ..models import ContextDocument, DirectorPhase, FileMapping
from .base import PhaseHandler


class UnderstandPhaseHandler(PhaseHandler):
    """Quality inspector for the UNDERSTAND phase."""

    @property
    def phase(self) -> DirectorPhase:
        return DirectorPhase.UNDERSTAND

    def validate_input(self, input_data: Any) -> str | None:
        """Task description must be a non-empty string."""
        if not isinstance(input_data, str):
            return "UNDERSTAND phase requires a task description string"
        if not input_data.strip():
            return "Task description cannot be empty"
        return None

    def format_output(self, raw_output: Any) -> ContextDocument:
        """Transform raw exploration data into a ContextDocument."""
        if isinstance(raw_output, ContextDocument):
            return raw_output

        if not isinstance(raw_output, dict):
            raise ValueError("UNDERSTAND output must be a ContextDocument or dict")

        files = [
            FileMapping(
                path=f["path"],
                role=f.get("role", "reference"),
                description=f.get("description", ""),
                patterns=f.get("patterns", []),
            )
            for f in raw_output.get("affected_files", [])
        ]

        return ContextDocument(
            task_description=raw_output.get("task_description", ""),
            affected_files=files,
            existing_patterns=raw_output.get("existing_patterns", []),
            dependencies=raw_output.get("dependencies", []),
            constraints=raw_output.get("constraints", []),
            risks=raw_output.get("risks", []),
            created_at=datetime.now(),
        )
