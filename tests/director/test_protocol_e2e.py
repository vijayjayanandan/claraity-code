"""End-to-end tests for the Director Protocol.

Slice 5: The dress rehearsal — full lifecycle scenarios testing
all pieces working together as one system.
"""

import pytest


class TestImports:
    """The front door lets you access everything."""

    def test_core_imports(self):
        from src.director import DirectorProtocol, VALID_TRANSITIONS
        assert DirectorProtocol is not None
        assert isinstance(VALID_TRANSITIONS, dict)

    def test_model_imports(self):
        from src.director import (
            DirectorPhase, SliceStatus, FileMapping,
            ContextDocument, VerticalSlice, DirectorPlan, PhaseResult,
        )
        # All importable from the top-level package
        assert len(DirectorPhase) == 8
        assert len(SliceStatus) == 4

    def test_error_imports(self):
        from src.director import DirectorError, InvalidTransitionError, PhaseError
        assert issubclass(InvalidTransitionError, DirectorError)
        assert issubclass(PhaseError, DirectorError)

    def test_phase_handler_imports(self):
        from src.director import PhaseHandler, UnderstandPhaseHandler, PlanPhaseHandler
        assert issubclass(UnderstandPhaseHandler, PhaseHandler)
        assert issubclass(PlanPhaseHandler, PhaseHandler)


class TestHappyPath:
    """Full scenario: task -> understand -> plan -> approve -> EXECUTE."""

    def test_full_happy_path(self):
        from src.director import (
            DirectorProtocol, DirectorPhase,
            ContextDocument, DirectorPlan, VerticalSlice, FileMapping,
        )

        protocol = DirectorProtocol()
        assert protocol.phase == DirectorPhase.IDLE

        # 1. Start
        protocol.start("Add /health endpoint to the API")
        assert protocol.phase == DirectorPhase.UNDERSTAND
        assert protocol.is_active is True

        # 2. Complete UNDERSTAND with a context document
        context = ContextDocument(
            task_description="Add /health endpoint to the API",
            affected_files=[
                FileMapping(path="src/api/routes.py", role="modify", description="API routes"),
                FileMapping(path="tests/test_routes.py", role="modify", description="Route tests"),
            ],
            existing_patterns=["Flask blueprint pattern"],
            dependencies=["flask"],
            constraints=["no emojis in Python"],
        )
        result = protocol.complete_understand(context)
        assert result.success is True
        assert protocol.phase == DirectorPhase.PLAN
        assert protocol.context is context

        # 3. Complete PLAN with vertical slices
        plan = DirectorPlan(
            summary="Two vertical slices for health endpoint",
            slices=[
                VerticalSlice(
                    id=1,
                    title="Basic /health returns ok",
                    files_to_modify=["src/api/routes.py", "tests/test_routes.py"],
                    test_criteria=["GET /health returns 200 with status ok"],
                ),
                VerticalSlice(
                    id=2,
                    title="DB connectivity check",
                    files_to_create=["src/api/health_checks.py"],
                    files_to_modify=["src/api/routes.py", "tests/test_routes.py"],
                    test_criteria=["GET /health includes db status"],
                    depends_on=[1],
                ),
            ],
        )
        result = protocol.complete_plan(plan)
        assert result.success is True
        assert protocol.phase == DirectorPhase.AWAITING_APPROVAL
        assert protocol.plan is plan
        assert protocol.plan.total_slices == 2

        # 4. Approve
        protocol.approve_plan()
        assert protocol.phase == DirectorPhase.EXECUTE

        # 5. Verify history captured both phases
        history = protocol.phase_history
        assert len(history) == 2
        assert history[0].phase == DirectorPhase.UNDERSTAND
        assert history[1].phase == DirectorPhase.PLAN

        # 6. Status reflects final state
        status = protocol.get_status()
        assert status["phase"] == "EXECUTE"
        assert status["task"] == "Add /health endpoint to the API"
        assert status["has_context"] is True
        assert status["has_plan"] is True
        assert status["total_slices"] == 2


class TestRejectionCycle:
    """Scenario: plan rejected, revised, then approved."""

    def test_reject_revise_approve(self):
        from src.director import (
            DirectorProtocol, DirectorPhase,
            ContextDocument, DirectorPlan, VerticalSlice,
        )

        protocol = DirectorProtocol()
        protocol.start("Add authentication")

        # UNDERSTAND
        context = ContextDocument(task_description="Add authentication")
        protocol.complete_understand(context)

        # PLAN v1 — submitted
        plan_v1 = DirectorPlan(
            summary="Single slice auth",
            slices=[VerticalSlice(id=1, title="Add login route")],
        )
        protocol.complete_plan(plan_v1)
        assert protocol.phase == DirectorPhase.AWAITING_APPROVAL

        # REJECTED — "needs more slices"
        protocol.reject_plan("Too coarse — break into smaller slices")
        assert protocol.phase == DirectorPhase.PLAN
        assert protocol.rejection_feedback == "Too coarse — break into smaller slices"

        # PLAN v2 — revised with feedback
        plan_v2 = DirectorPlan(
            summary="Three-slice auth",
            slices=[
                VerticalSlice(id=1, title="User model + registration"),
                VerticalSlice(id=2, title="Login + token generation", depends_on=[1]),
                VerticalSlice(id=3, title="Protected route middleware", depends_on=[2]),
            ],
        )
        protocol.complete_plan(plan_v2)
        assert protocol.phase == DirectorPhase.AWAITING_APPROVAL
        assert protocol.plan.total_slices == 3

        # APPROVED
        protocol.approve_plan()
        assert protocol.phase == DirectorPhase.EXECUTE
        assert protocol.rejection_feedback is None

        # History has UNDERSTAND + PLAN v1 + PLAN v2
        assert len(protocol.phase_history) == 3


class TestFailurePath:
    """Scenario: understand fails, reset, start fresh."""

    def test_fail_reset_restart(self):
        from src.director import DirectorProtocol, DirectorPhase, ContextDocument

        protocol = DirectorProtocol()

        # Attempt 1 — fails
        protocol.start("Migrate database")
        result = protocol.fail_understand("No database config found")
        assert protocol.phase == DirectorPhase.FAILED
        assert protocol.is_active is False
        assert result.success is False
        assert result.error == "No database config found"

        # Reset
        protocol.reset()
        assert protocol.phase == DirectorPhase.IDLE
        assert protocol.task_description is None
        assert protocol.context is None

        # Attempt 2 — succeeds
        protocol.start("Migrate database (with config path)")
        assert protocol.phase == DirectorPhase.UNDERSTAND
        context = ContextDocument(task_description="Migrate database (with config path)")
        protocol.complete_understand(context)
        assert protocol.phase == DirectorPhase.PLAN


class TestPlanSerialization:
    """Plan.to_dict() produces valid JSON-serializable output."""

    def test_full_plan_serializes(self):
        import json
        from src.director import (
            DirectorPlan, VerticalSlice, ContextDocument,
        )

        plan = DirectorPlan(
            summary="Test plan",
            slices=[
                VerticalSlice(id=1, title="s1", test_criteria=["test passes"]),
                VerticalSlice(id=2, title="s2", depends_on=[1]),
            ],
            context=ContextDocument(task_description="task"),
        )
        d = plan.to_dict()

        # Must be JSON serializable (no datetime, no enums, no custom objects)
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

        # Roundtrip
        parsed = json.loads(json_str)
        assert parsed["summary"] == "Test plan"
        assert len(parsed["slices"]) == 2
        assert parsed["slices"][0]["test_criteria"] == ["test passes"]
        assert parsed["slices"][1]["depends_on"] == [1]
