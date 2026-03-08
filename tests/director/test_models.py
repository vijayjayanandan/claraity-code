"""Tests for Director Protocol data models.

Slice 1 — RED phase: These tests define the contract for all data structures.
"""

import pytest
from datetime import datetime


class TestDirectorPhase:
    """DirectorPhase enum must have all 8 protocol states."""

    def test_has_idle(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.IDLE is not None

    def test_has_understand(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.UNDERSTAND is not None

    def test_has_plan(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.PLAN is not None

    def test_has_awaiting_approval(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.AWAITING_APPROVAL is not None

    def test_has_execute(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.EXECUTE is not None

    def test_has_integrate(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.INTEGRATE is not None

    def test_has_complete(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.COMPLETE is not None

    def test_has_failed(self):
        from src.director.models import DirectorPhase
        assert DirectorPhase.FAILED is not None

    def test_total_count(self):
        from src.director.models import DirectorPhase
        assert len(DirectorPhase) == 8

    def test_all_values_unique(self):
        from src.director.models import DirectorPhase
        values = [p.value for p in DirectorPhase]
        assert len(values) == len(set(values))


class TestSliceStatus:
    """SliceStatus enum must have 4 states."""

    def test_has_pending(self):
        from src.director.models import SliceStatus
        assert SliceStatus.PENDING is not None

    def test_has_in_progress(self):
        from src.director.models import SliceStatus
        assert SliceStatus.IN_PROGRESS is not None

    def test_has_completed(self):
        from src.director.models import SliceStatus
        assert SliceStatus.COMPLETED is not None

    def test_has_failed(self):
        from src.director.models import SliceStatus
        assert SliceStatus.FAILED is not None

    def test_total_count(self):
        from src.director.models import SliceStatus
        assert len(SliceStatus) == 4


class TestFileMapping:
    """FileMapping stores file metadata from the UNDERSTAND phase."""

    def test_create_with_required_fields(self):
        from src.director.models import FileMapping
        fm = FileMapping(path="src/api/routes.py", role="modify", description="API routes")
        assert fm.path == "src/api/routes.py"
        assert fm.role == "modify"
        assert fm.description == "API routes"

    def test_patterns_defaults_to_empty_list(self):
        from src.director.models import FileMapping
        fm = FileMapping(path="x.py", role="reference", description="ref")
        assert fm.patterns == []

    def test_patterns_stores_values(self):
        from src.director.models import FileMapping
        fm = FileMapping(
            path="x.py", role="modify", description="d",
            patterns=["blueprint pattern", "decorator routes"]
        )
        assert len(fm.patterns) == 2
        assert "blueprint pattern" in fm.patterns


class TestContextDocument:
    """ContextDocument is the output of the UNDERSTAND phase."""

    def test_create_with_task_description(self):
        from src.director.models import ContextDocument
        ctx = ContextDocument(task_description="Add health endpoint")
        assert ctx.task_description == "Add health endpoint"

    def test_defaults_are_empty_lists(self):
        from src.director.models import ContextDocument
        ctx = ContextDocument(task_description="task")
        assert ctx.affected_files == []
        assert ctx.existing_patterns == []
        assert ctx.dependencies == []
        assert ctx.constraints == []
        assert ctx.risks == []

    def test_created_at_defaults_to_none(self):
        from src.director.models import ContextDocument
        ctx = ContextDocument(task_description="task")
        assert ctx.created_at is None

    def test_to_dict_roundtrip(self):
        from src.director.models import ContextDocument, FileMapping
        now = datetime(2026, 2, 13, 10, 0, 0)
        ctx = ContextDocument(
            task_description="Add health endpoint",
            affected_files=[
                FileMapping(path="routes.py", role="modify", description="API routes")
            ],
            existing_patterns=["blueprint pattern"],
            dependencies=["flask"],
            constraints=["no emojis"],
            risks=["breaking existing routes"],
            created_at=now,
        )
        d = ctx.to_dict()
        assert d["task_description"] == "Add health endpoint"
        assert len(d["affected_files"]) == 1
        assert d["affected_files"][0]["path"] == "routes.py"
        assert d["affected_files"][0]["role"] == "modify"
        assert d["existing_patterns"] == ["blueprint pattern"]
        assert d["dependencies"] == ["flask"]
        assert d["constraints"] == ["no emojis"]
        assert d["risks"] == ["breaking existing routes"]
        assert d["created_at"] == "2026-02-13T10:00:00"

    def test_to_dict_with_none_created_at(self):
        from src.director.models import ContextDocument
        ctx = ContextDocument(task_description="task")
        d = ctx.to_dict()
        assert d["created_at"] is None


class TestVerticalSlice:
    """VerticalSlice is the fundamental unit of work."""

    def test_create_with_required_fields(self):
        from src.director.models import VerticalSlice
        vs = VerticalSlice(id=1, title="Basic health endpoint")
        assert vs.id == 1
        assert vs.title == "Basic health endpoint"

    def test_defaults(self):
        from src.director.models import VerticalSlice, SliceStatus
        vs = VerticalSlice(id=1, title="test")
        assert vs.description == ""
        assert vs.files_to_create == []
        assert vs.files_to_modify == []
        assert vs.test_criteria == []
        assert vs.depends_on == []
        assert vs.status == SliceStatus.PENDING

    def test_to_dict_roundtrip(self):
        from src.director.models import VerticalSlice, SliceStatus
        vs = VerticalSlice(
            id=1,
            title="Basic health endpoint",
            description="Add GET /health returning status ok",
            files_to_create=["health_checks.py"],
            files_to_modify=["routes.py"],
            test_criteria=["GET /health returns 200"],
            depends_on=[],
        )
        d = vs.to_dict()
        assert d["id"] == 1
        assert d["title"] == "Basic health endpoint"
        assert d["description"] == "Add GET /health returning status ok"
        assert d["files_to_create"] == ["health_checks.py"]
        assert d["files_to_modify"] == ["routes.py"]
        assert d["test_criteria"] == ["GET /health returns 200"]
        assert d["depends_on"] == []
        assert d["status"] == "PENDING"

    def test_to_dict_reflects_status_change(self):
        from src.director.models import VerticalSlice, SliceStatus
        vs = VerticalSlice(id=1, title="test")
        vs.status = SliceStatus.COMPLETED
        assert vs.to_dict()["status"] == "COMPLETED"


class TestDirectorPlan:
    """DirectorPlan is the output of the PLAN phase."""

    def test_create_empty(self):
        from src.director.models import DirectorPlan
        plan = DirectorPlan()
        assert plan.slices == []
        assert plan.context is None
        assert plan.summary == ""

    def test_total_slices(self):
        from src.director.models import DirectorPlan, VerticalSlice
        plan = DirectorPlan(slices=[
            VerticalSlice(id=1, title="s1"),
            VerticalSlice(id=2, title="s2"),
            VerticalSlice(id=3, title="s3"),
        ])
        assert plan.total_slices == 3

    def test_completed_slices(self):
        from src.director.models import DirectorPlan, VerticalSlice, SliceStatus
        s1 = VerticalSlice(id=1, title="s1")
        s2 = VerticalSlice(id=2, title="s2")
        s3 = VerticalSlice(id=3, title="s3")
        s1.status = SliceStatus.COMPLETED
        s3.status = SliceStatus.COMPLETED
        plan = DirectorPlan(slices=[s1, s2, s3])
        assert plan.completed_slices == 2

    def test_to_dict_roundtrip(self):
        from src.director.models import DirectorPlan, VerticalSlice, ContextDocument
        now = datetime(2026, 2, 13, 10, 0, 0)
        ctx = ContextDocument(task_description="task")
        plan = DirectorPlan(
            slices=[VerticalSlice(id=1, title="s1")],
            context=ctx,
            summary="One-slice plan",
            created_at=now,
        )
        d = plan.to_dict()
        assert d["summary"] == "One-slice plan"
        assert len(d["slices"]) == 1
        assert d["slices"][0]["title"] == "s1"
        assert d["context"]["task_description"] == "task"
        assert d["created_at"] == "2026-02-13T10:00:00"

    def test_to_dict_with_none_context(self):
        from src.director.models import DirectorPlan
        plan = DirectorPlan()
        d = plan.to_dict()
        assert d["context"] is None
        assert d["created_at"] is None


class TestPhaseResult:
    """PhaseResult stores output from a completed phase."""

    def test_create_success(self):
        from src.director.models import PhaseResult, DirectorPhase
        result = PhaseResult(
            phase=DirectorPhase.UNDERSTAND,
            success=True,
            output={"key": "value"},
        )
        assert result.phase == DirectorPhase.UNDERSTAND
        assert result.success is True
        assert result.output == {"key": "value"}
        assert result.error is None

    def test_create_failure(self):
        from src.director.models import PhaseResult, DirectorPhase
        result = PhaseResult(
            phase=DirectorPhase.PLAN,
            success=False,
            error="Could not decompose task",
        )
        assert result.success is False
        assert result.error == "Could not decompose task"
        assert result.output is None

    def test_duration_defaults_to_zero(self):
        from src.director.models import PhaseResult, DirectorPhase
        result = PhaseResult(phase=DirectorPhase.UNDERSTAND, success=True)
        assert result.duration_seconds == 0.0
