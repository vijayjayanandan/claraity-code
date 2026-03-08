"""Tests for PlanPhaseHandler.

Slice 4: Quality inspector at checkpoint 2 — validates context input,
transforms raw slice data into a DirectorPlan.
"""

import pytest

from src.director.models import (
    DirectorPhase, ContextDocument, DirectorPlan, VerticalSlice, SliceStatus,
)


class TestPhaseProperty:
    """Inspector knows which checkpoint it guards."""

    def test_phase_is_plan(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        assert handler.phase == DirectorPhase.PLAN


class TestValidateInput:
    """Gate check: is there a valid ContextDocument to plan from?"""

    def test_valid_context_returns_none(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        ctx = ContextDocument(task_description="Add health endpoint")
        assert handler.validate_input(ctx) is None

    def test_wrong_type_returns_error(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        result = handler.validate_input("not a context doc")
        assert result is not None
        assert isinstance(result, str)

    def test_empty_task_description_returns_error(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        ctx = ContextDocument(task_description="")
        result = handler.validate_input(ctx)
        assert result is not None


class TestFormatOutput:
    """Shape raw planning data into a DirectorPlan."""

    def test_passthrough_director_plan(self):
        """Already structured — return as-is."""
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        plan = DirectorPlan(summary="plan")
        result = handler.format_output(plan)
        assert result is plan

    def test_dict_to_director_plan(self):
        """Raw dict with slices -> structured DirectorPlan."""
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        raw = {
            "summary": "Two-slice plan",
            "slices": [
                {
                    "id": 1,
                    "title": "Basic endpoint",
                    "description": "Add GET /health",
                    "files_to_create": [],
                    "files_to_modify": ["routes.py"],
                    "test_criteria": ["GET /health returns 200"],
                    "depends_on": [],
                },
                {
                    "id": 2,
                    "title": "DB check",
                    "description": "Add DB connectivity check",
                    "files_to_create": ["health_checks.py"],
                    "files_to_modify": ["routes.py"],
                    "test_criteria": ["returns db status"],
                    "depends_on": [1],
                },
            ],
        }
        result = handler.format_output(raw)
        assert isinstance(result, DirectorPlan)
        assert result.summary == "Two-slice plan"
        assert len(result.slices) == 2
        assert result.slices[0].title == "Basic endpoint"
        assert result.slices[1].depends_on == [1]

    def test_slices_default_to_pending(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        raw = {
            "summary": "plan",
            "slices": [{"id": 1, "title": "s1"}],
        }
        result = handler.format_output(raw)
        assert result.slices[0].status == SliceStatus.PENDING

    def test_auto_numbers_slices_if_id_missing(self):
        """If slices don't have explicit IDs, number them 1, 2, 3..."""
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        raw = {
            "summary": "plan",
            "slices": [
                {"title": "first"},
                {"title": "second"},
                {"title": "third"},
            ],
        }
        result = handler.format_output(raw)
        assert result.slices[0].id == 1
        assert result.slices[1].id == 2
        assert result.slices[2].id == 3

    def test_dict_with_missing_optional_slice_fields(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        raw = {
            "summary": "plan",
            "slices": [{"id": 1, "title": "minimal slice"}],
        }
        result = handler.format_output(raw)
        s = result.slices[0]
        assert s.description == ""
        assert s.files_to_create == []
        assert s.files_to_modify == []
        assert s.test_criteria == []
        assert s.depends_on == []

    def test_sets_created_at(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        raw = {"summary": "plan", "slices": []}
        result = handler.format_output(raw)
        assert result.created_at is not None

    def test_invalid_type_raises(self):
        from src.director.phases.plan import PlanPhaseHandler
        handler = PlanPhaseHandler()
        with pytest.raises(ValueError):
            handler.format_output(42)
