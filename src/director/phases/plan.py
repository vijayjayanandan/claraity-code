"""
PlanPhaseHandler - checkpoint 2.

Validates that a ContextDocument exists,
and transforms raw slice data into a DirectorPlan.
"""

from datetime import datetime
from typing import Any, Optional

from ..models import (
    ContextDocument,
    DirectorPhase,
    DirectorPlan,
    SliceStatus,
    VerticalSlice,
)
from .base import PhaseHandler


class PlanPhaseHandler(PhaseHandler):
    """Quality inspector for the PLAN phase."""

    @property
    def phase(self) -> DirectorPhase:
        return DirectorPhase.PLAN

    def validate_input(self, input_data: Any) -> str | None:
        """Must have a ContextDocument with a task description."""
        if not isinstance(input_data, ContextDocument):
            return "PLAN phase requires a ContextDocument from UNDERSTAND phase"
        if not input_data.task_description:
            return "ContextDocument must have a task description"
        return None

    def format_output(self, raw_output: Any) -> DirectorPlan:
        """Transform raw planning data into a DirectorPlan."""
        if isinstance(raw_output, DirectorPlan):
            return raw_output

        if not isinstance(raw_output, dict):
            raise ValueError("PLAN output must be a DirectorPlan or dict")

        slices = []
        for i, s in enumerate(raw_output.get("slices", []), start=1):
            slices.append(VerticalSlice(
                id=s.get("id", i),
                title=s["title"],
                description=s.get("description", ""),
                files_to_create=s.get("files_to_create", []),
                files_to_modify=s.get("files_to_modify", []),
                test_criteria=s.get("test_criteria", []),
                depends_on=s.get("depends_on", []),
                status=SliceStatus.PENDING,
            ))

        return DirectorPlan(
            slices=slices,
            summary=raw_output.get("summary", ""),
            created_at=datetime.now(),
        )
