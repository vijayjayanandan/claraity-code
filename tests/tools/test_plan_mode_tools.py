"""Tests for Plan Mode tools."""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.tools.plan_mode_tools import EnterPlanModeTool, RequestPlanApprovalTool
from src.tools.base import ToolStatus
from src.core.plan_mode import PlanModeState


class TestEnterPlanModeTool:
    """Test EnterPlanModeTool class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def plan_state(self, temp_dir):
        """Create a PlanModeState instance."""
        return PlanModeState(claraity_dir=temp_dir / ".claraity")

    @pytest.fixture
    def enter_tool(self, plan_state):
        """Create an EnterPlanModeTool instance."""
        return EnterPlanModeTool(
            plan_mode_state=plan_state,
            session_id="test-session-123"
        )

    def test_tool_name(self, enter_tool):
        """Test tool has correct name."""
        assert enter_tool.name == "enter_plan_mode"

    def test_tool_description(self, enter_tool):
        """Test tool has description."""
        assert "plan mode" in enter_tool.description.lower()

    def test_execute_success(self, enter_tool, plan_state):
        """Test successful execution enters plan mode."""
        result = enter_tool.execute(reason="Complex refactoring")

        assert result.status == ToolStatus.SUCCESS
        assert result.is_success()
        assert plan_state.is_active is True
        assert "plan_path" in result.metadata
        assert "PLAN MODE" in result.output

    def test_execute_with_reason(self, enter_tool):
        """Test execution records reason in metadata."""
        result = enter_tool.execute(reason="Complex refactoring")

        assert result.metadata.get("reason") == "Complex refactoring"

    def test_execute_creates_plan_file(self, enter_tool, temp_dir):
        """Test execution creates plan file."""
        result = enter_tool.execute()

        plan_path = Path(result.metadata["plan_path"])
        assert plan_path.exists()
        assert plan_path.suffix == ".md"

    def test_execute_fails_without_plan_state(self):
        """Test execution fails without plan_mode_state."""
        tool = EnterPlanModeTool(plan_mode_state=None, session_id="test")
        result = tool.execute()

        assert result.status == ToolStatus.ERROR
        assert "not initialized" in result.error

    def test_execute_fails_without_session_id(self, plan_state):
        """Test execution fails without session_id."""
        tool = EnterPlanModeTool(plan_mode_state=plan_state, session_id=None)
        result = tool.execute()

        assert result.status == ToolStatus.ERROR
        assert "Session ID" in result.error

    def test_execute_fails_when_already_active(self, enter_tool, plan_state):
        """Test execution fails when already in plan mode."""
        # First entry succeeds
        enter_tool.execute()

        # Second entry fails
        result = enter_tool.execute()

        assert result.status == ToolStatus.ERROR
        assert "Already in plan mode" in result.error

    def test_get_parameters(self, enter_tool):
        """Test get_parameters returns valid schema."""
        params = enter_tool._get_parameters()

        assert params["type"] == "object"
        assert "reason" in params["properties"]
        assert params["required"] == []


class TestExitPlanModeTool:
    """Test ExitPlanModeTool class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def plan_state(self, temp_dir):
        """Create a PlanModeState instance in active mode."""
        state = PlanModeState(claraity_dir=temp_dir / ".claraity")
        state.enter("test-session-123")
        return state

    @pytest.fixture
    def exit_tool(self, plan_state):
        """Create a RequestPlanApprovalTool instance."""
        return RequestPlanApprovalTool(plan_mode_state=plan_state)

    def test_tool_name(self, exit_tool):
        """Test tool has correct name."""
        assert exit_tool.name == "request_plan_approval"

    def test_tool_description(self, exit_tool):
        """Test tool has description."""
        assert "approval" in exit_tool.description.lower()

    def test_execute_success(self, exit_tool):
        """Test successful execution submits for approval."""
        result = exit_tool.execute()

        assert result.status == ToolStatus.SUCCESS
        assert result.is_success()
        assert "plan_hash" in result.metadata
        assert result.metadata.get("requires_user_approval") is True

    def test_execute_returns_plan_hash(self, exit_tool):
        """Test execution returns plan hash."""
        result = exit_tool.execute()

        plan_hash = result.metadata.get("plan_hash")
        assert plan_hash is not None
        assert len(plan_hash) == 64  # Full SHA256 hex digest

    def test_execute_returns_excerpt(self, exit_tool):
        """Test execution returns plan excerpt."""
        result = exit_tool.execute()

        excerpt = result.metadata.get("excerpt")
        assert excerpt is not None
        assert "Plan:" in excerpt  # From template

    def test_execute_indicates_truncation(self, exit_tool, plan_state):
        """Test execution indicates if content was truncated."""
        # Write large content
        plan_state.plan_file_path.write_text("x" * 10000, encoding="utf-8")

        result = exit_tool.execute()

        assert result.metadata.get("truncated") is True

    def test_execute_fails_without_plan_state(self):
        """Test execution fails without plan_mode_state."""
        tool = RequestPlanApprovalTool(plan_mode_state=None)
        result = tool.execute()

        assert result.status == ToolStatus.ERROR
        assert "not initialized" in result.error

    def test_execute_fails_when_not_active(self, temp_dir):
        """Test execution fails when not in plan mode."""
        state = PlanModeState(claraity_dir=temp_dir / ".claraity")
        tool = RequestPlanApprovalTool(plan_mode_state=state)

        result = tool.execute()

        assert result.status == ToolStatus.ERROR
        assert "Not currently in plan mode" in result.error

    def test_get_parameters(self, exit_tool):
        """Test get_parameters returns valid schema."""
        params = exit_tool._get_parameters()

        assert params["type"] == "object"
        assert params["required"] == []


class TestPlanModeToolIntegration:
    """Integration tests for plan mode tools."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp, ignore_errors=True)

    def test_enter_then_exit_workflow(self, temp_dir):
        """Test complete enter -> exit workflow."""
        plan_state = PlanModeState(claraity_dir=temp_dir / ".claraity")
        enter_tool = EnterPlanModeTool(plan_mode_state=plan_state, session_id="test")
        exit_tool = RequestPlanApprovalTool(plan_mode_state=plan_state)

        # Enter plan mode
        enter_result = enter_tool.execute(reason="Test workflow")
        assert enter_result.is_success()
        assert plan_state.is_active

        # Exit plan mode
        exit_result = exit_tool.execute()
        assert exit_result.is_success()
        assert exit_result.metadata.get("requires_user_approval")

        # Approve the plan
        plan_hash = exit_result.metadata["plan_hash"]
        approved = plan_state.approve(plan_hash)
        assert approved
        assert not plan_state.is_active

    def test_modify_plan_then_exit(self, temp_dir):
        """Test modifying plan before exit changes hash."""
        plan_state = PlanModeState(claraity_dir=temp_dir / ".claraity")
        enter_tool = EnterPlanModeTool(plan_mode_state=plan_state, session_id="test")
        exit_tool = RequestPlanApprovalTool(plan_mode_state=plan_state)

        # Enter and get initial hash
        enter_tool.execute()
        exit_result1 = exit_tool.execute()
        hash1 = exit_result1.metadata["plan_hash"]

        # Reject to go back to plan mode (resets hash, sets is_active=True)
        plan_state.reject()

        # Modify plan content
        original = plan_state.plan_file_path.read_text()
        plan_state.plan_file_path.write_text(original + "\nModified!", encoding="utf-8")

        # Exit again - hash should be different
        exit_result2 = exit_tool.execute()
        hash2 = exit_result2.metadata["plan_hash"]

        assert hash1 != hash2
