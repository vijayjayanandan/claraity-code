"""
Tests for PermissionManager.

Covers:
- Permission mode initialization
- Mode changing
- Approval decision logic for all modes
- Custom approval callbacks
- Console approval (mocked)
- String parsing
- Mode descriptions
"""

import pytest
from unittest.mock import Mock, patch
from src.workflow.permission_manager import (
    PermissionManager,
    PermissionMode,
    ApprovalDecision
)
from src.workflow.task_planner import ExecutionPlan, PlanStep
from src.workflow.task_analyzer import TaskAnalysis, TaskType, TaskComplexity


class TestPermissionModeEnum:
    """Test PermissionMode enum."""

    def test_permission_mode_values(self):
        """Test that permission modes have correct values."""
        assert PermissionMode.PLAN.value == "plan"
        assert PermissionMode.NORMAL.value == "normal"
        assert PermissionMode.AUTO.value == "auto"

    def test_all_modes_exist(self):
        """Test that all expected modes are defined."""
        modes = list(PermissionMode)
        assert len(modes) == 3
        assert PermissionMode.PLAN in modes
        assert PermissionMode.NORMAL in modes
        assert PermissionMode.AUTO in modes


class TestApprovalDecision:
    """Test ApprovalDecision data class."""

    def test_no_approval_required(self):
        """Test decision when no approval required."""
        decision = ApprovalDecision(
            requires_approval=False,
            reason="Low risk operation"
        )

        assert not decision.requires_approval
        assert decision.approved is None
        assert "No approval required" in str(decision)

    def test_approval_required_not_yet_asked(self):
        """Test decision when approval required but not yet asked."""
        decision = ApprovalDecision(
            requires_approval=True,
            reason="High risk operation",
            approval_type="risk_assessment"
        )

        assert decision.requires_approval
        assert decision.approved is None
        assert "Approval required" in str(decision)
        assert "risk_assessment" in str(decision)

    def test_approval_granted(self):
        """Test decision when approval granted."""
        decision = ApprovalDecision(
            requires_approval=True,
            reason="High risk",
            approved=True
        )

        assert decision.approved
        assert "Approved" in str(decision)

    def test_approval_rejected(self):
        """Test decision when approval rejected."""
        decision = ApprovalDecision(
            requires_approval=True,
            reason="High risk",
            approved=False
        )

        assert not decision.approved
        assert "Rejected" in str(decision)


class TestPermissionManagerInit:
    """Test PermissionManager initialization."""

    def test_default_init(self):
        """Test default initialization (NORMAL mode)."""
        pm = PermissionManager()

        assert pm.get_mode() == PermissionMode.NORMAL
        assert pm.approval_callback is None

    def test_init_with_plan_mode(self):
        """Test initialization with PLAN mode."""
        pm = PermissionManager(mode=PermissionMode.PLAN)

        assert pm.get_mode() == PermissionMode.PLAN

    def test_init_with_auto_mode(self):
        """Test initialization with AUTO mode."""
        pm = PermissionManager(mode=PermissionMode.AUTO)

        assert pm.get_mode() == PermissionMode.AUTO

    def test_init_with_custom_callback(self):
        """Test initialization with custom approval callback."""
        callback = Mock(return_value=True)
        pm = PermissionManager(approval_callback=callback)

        assert pm.approval_callback == callback


class TestPermissionManagerModeChange:
    """Test changing permission modes."""

    def test_set_mode(self):
        """Test setting permission mode."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        pm.set_mode(PermissionMode.PLAN)
        assert pm.get_mode() == PermissionMode.PLAN

        pm.set_mode(PermissionMode.AUTO)
        assert pm.get_mode() == PermissionMode.AUTO

    def test_get_mode(self):
        """Test getting current mode."""
        pm = PermissionManager(mode=PermissionMode.AUTO)

        mode = pm.get_mode()
        assert isinstance(mode, PermissionMode)
        assert mode == PermissionMode.AUTO


class TestPermissionManagerApprovalDecisions:
    """Test approval decision logic."""

    @pytest.fixture
    def low_risk_plan(self):
        """Create a low-risk execution plan."""
        plan = ExecutionPlan(
            task_description="Simple read operation",
            task_type=TaskType.EXPLAIN,
            steps=[
                PlanStep(id=1, description="Read file", action_type="read", arguments={}, risk="low")
            ],
            total_estimated_time="1 minute",
            overall_risk="low",
            requires_approval=False
        )
        return plan

    @pytest.fixture
    def high_risk_plan(self):
        """Create a high-risk execution plan."""
        plan = ExecutionPlan(
            task_description="Delete all files",
            task_type=TaskType.REFACTOR,
            steps=[
                PlanStep(id=1, description="Delete files", action_type="run", arguments={}, risk="high")
            ],
            total_estimated_time="5 minutes",
            overall_risk="high",
            requires_approval=True
        )
        return plan

    @pytest.fixture
    def low_risk_analysis(self):
        """Create low-risk task analysis."""
        return TaskAnalysis(
            task_type=TaskType.EXPLAIN,
            complexity=TaskComplexity.SIMPLE,
            risk_level="low",
            estimated_files=1,
            estimated_iterations=1,
            requires_planning=False,
            requires_approval=False,
            requires_git=False,
            requires_tests=False
        )

    @pytest.fixture
    def high_risk_analysis(self):
        """Create high-risk task analysis."""
        return TaskAnalysis(
            task_type=TaskType.REFACTOR,
            complexity=TaskComplexity.VERY_COMPLEX,
            risk_level="high",
            estimated_files=10,
            estimated_iterations=8,
            requires_planning=True,
            requires_approval=True,
            requires_git=False,
            requires_tests=False
        )

    # ===== AUTO Mode Tests =====

    def test_auto_mode_never_requires_approval(self, low_risk_plan, high_risk_plan):
        """Test that AUTO mode never requires approval."""
        pm = PermissionManager(mode=PermissionMode.AUTO)

        # Low risk
        decision = pm.check_approval_required(low_risk_plan)
        assert not decision.requires_approval
        assert "AUTO mode" in decision.reason

        # High risk
        decision = pm.check_approval_required(high_risk_plan)
        assert not decision.requires_approval
        assert "AUTO mode" in decision.reason

    def test_auto_mode_always_approves(self, high_risk_plan, high_risk_analysis):
        """Test that AUTO mode always returns True for approval."""
        pm = PermissionManager(mode=PermissionMode.AUTO)

        approved = pm.get_approval(high_risk_plan, high_risk_analysis)
        assert approved

    # ===== PLAN Mode Tests =====

    def test_plan_mode_always_requires_approval(self, low_risk_plan, high_risk_plan):
        """Test that PLAN mode always requires approval."""
        pm = PermissionManager(mode=PermissionMode.PLAN)

        # Low risk
        decision = pm.check_approval_required(low_risk_plan)
        assert decision.requires_approval
        assert decision.approval_type == "plan_review"

        # High risk
        decision = pm.check_approval_required(high_risk_plan)
        assert decision.requires_approval
        assert decision.approval_type == "plan_review"

    def test_plan_mode_uses_callback(self, low_risk_plan):
        """Test that PLAN mode calls approval callback."""
        callback = Mock(return_value=True)
        pm = PermissionManager(mode=PermissionMode.PLAN, approval_callback=callback)

        approved = pm.get_approval(low_risk_plan)

        assert approved
        callback.assert_called_once_with(low_risk_plan, None)

    # ===== NORMAL Mode Tests =====

    def test_normal_mode_low_risk_no_approval(self, low_risk_plan, low_risk_analysis):
        """Test that NORMAL mode doesn't require approval for low risk."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        decision = pm.check_approval_required(low_risk_plan, low_risk_analysis)

        assert not decision.requires_approval
        assert "normal risk parameters" in decision.reason

    def test_normal_mode_high_risk_requires_approval(self, high_risk_plan):
        """Test that NORMAL mode requires approval for high risk plans."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        decision = pm.check_approval_required(high_risk_plan)

        assert decision.requires_approval
        assert decision.approval_type == "risk_assessment"
        assert "high" in decision.reason.lower()

    def test_normal_mode_analysis_requires_approval(self, low_risk_plan, high_risk_analysis):
        """Test that NORMAL mode respects analysis.requires_approval."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        decision = pm.check_approval_required(low_risk_plan, high_risk_analysis)

        assert decision.requires_approval
        assert decision.approval_type == "task_analysis"

    def test_normal_mode_uses_callback_when_needed(self, high_risk_plan):
        """Test that NORMAL mode calls callback for high risk."""
        callback = Mock(return_value=False)
        pm = PermissionManager(mode=PermissionMode.NORMAL, approval_callback=callback)

        approved = pm.get_approval(high_risk_plan)

        assert not approved
        callback.assert_called_once()

    def test_normal_mode_no_callback_for_low_risk(self, low_risk_plan):
        """Test that NORMAL mode doesn't call callback for low risk."""
        callback = Mock(return_value=True)
        pm = PermissionManager(mode=PermissionMode.NORMAL, approval_callback=callback)

        approved = pm.get_approval(low_risk_plan)

        assert approved
        callback.assert_not_called()


class TestPermissionManagerConsoleApproval:
    """Test console approval functionality."""

    @pytest.fixture
    def plan(self):
        """Create a test plan."""
        return ExecutionPlan(
            task_description="Test task",
            task_type=TaskType.FEATURE,
            steps=[
                PlanStep(id=1, description="Step 1", action_type="write", arguments={}, risk="medium")
            ],
            total_estimated_time="2 minutes",
            overall_risk="medium",
            requires_approval=True,
            rollback_strategy="Use git reset"
        )

    @pytest.fixture
    def analysis(self):
        """Create a test analysis."""
        return TaskAnalysis(
            task_type=TaskType.FEATURE,
            complexity=TaskComplexity.MODERATE,
            risk_level="medium",
            estimated_files=3,
            estimated_iterations=5,
            requires_planning=True,
            requires_approval=True,
            requires_git=False,
            requires_tests=False
        )

    @patch('builtins.input', return_value='yes')
    @patch('builtins.print')
    def test_console_approval_yes(self, mock_print, mock_input, plan, analysis):
        """Test console approval with 'yes' response."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        approved = pm.get_approval(plan, analysis)

        assert approved
        mock_input.assert_called_once()

    @patch('builtins.input', return_value='y')
    @patch('builtins.print')
    def test_console_approval_y(self, mock_print, mock_input, plan, analysis):
        """Test console approval with 'y' response."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        approved = pm.get_approval(plan, analysis)

        assert approved

    @patch('builtins.input', return_value='no')
    @patch('builtins.print')
    def test_console_approval_no(self, mock_print, mock_input, plan, analysis):
        """Test console approval with 'no' response."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        approved = pm.get_approval(plan, analysis)

        assert not approved

    @patch('builtins.input', return_value='n')
    @patch('builtins.print')
    def test_console_approval_n(self, mock_print, mock_input, plan, analysis):
        """Test console approval with 'n' response."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        approved = pm.get_approval(plan, analysis)

        assert not approved

    @patch('builtins.input', side_effect=EOFError())
    @patch('builtins.print')
    def test_console_approval_eof(self, mock_print, mock_input, plan, analysis):
        """Test console approval handles EOF error."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        approved = pm.get_approval(plan, analysis)

        assert not approved

    @patch('builtins.input', side_effect=KeyboardInterrupt())
    @patch('builtins.print')
    def test_console_approval_interrupt(self, mock_print, mock_input, plan, analysis):
        """Test console approval handles keyboard interrupt."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        approved = pm.get_approval(plan, analysis)

        assert not approved


class TestPermissionManagerStringParsing:
    """Test string to PermissionMode parsing."""

    def test_parse_plan(self):
        """Test parsing 'plan' string."""
        mode = PermissionManager.from_string("plan")
        assert mode == PermissionMode.PLAN

    def test_parse_normal(self):
        """Test parsing 'normal' string."""
        mode = PermissionManager.from_string("normal")
        assert mode == PermissionMode.NORMAL

    def test_parse_auto(self):
        """Test parsing 'auto' string."""
        mode = PermissionManager.from_string("auto")
        assert mode == PermissionMode.AUTO

    def test_parse_case_insensitive(self):
        """Test parsing is case insensitive."""
        assert PermissionManager.from_string("PLAN") == PermissionMode.PLAN
        assert PermissionManager.from_string("Normal") == PermissionMode.NORMAL
        assert PermissionManager.from_string("AuTo") == PermissionMode.AUTO

    def test_parse_with_whitespace(self):
        """Test parsing handles whitespace."""
        assert PermissionManager.from_string("  plan  ") == PermissionMode.PLAN
        assert PermissionManager.from_string("\tnormal\n") == PermissionMode.NORMAL

    def test_parse_invalid_string(self):
        """Test parsing invalid string raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PermissionManager.from_string("invalid")

        assert "Invalid permission mode" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)
        assert "plan" in str(exc_info.value)


class TestPermissionManagerDescriptions:
    """Test mode description formatting."""

    def test_plan_mode_description(self):
        """Test PLAN mode description."""
        pm = PermissionManager(mode=PermissionMode.PLAN)

        description = pm.format_mode_description()

        assert "PLAN" in description.upper()
        assert "Always shows" in description or "always" in description.lower()

    def test_normal_mode_description(self):
        """Test NORMAL mode description."""
        pm = PermissionManager(mode=PermissionMode.NORMAL)

        description = pm.format_mode_description()

        assert "NORMAL" in description.upper()
        assert "high-risk" in description.lower() or "risky" in description.lower()

    def test_auto_mode_description(self):
        """Test AUTO mode description."""
        pm = PermissionManager(mode=PermissionMode.AUTO)

        description = pm.format_mode_description()

        assert "AUTO" in description.upper()
        assert "autonomous" in description.lower() or "never" in description.lower()


class TestPermissionManagerIntegration:
    """Integration tests combining multiple features."""

    def test_mode_switching_during_execution(self):
        """Test switching modes affects approval behavior."""
        plan = ExecutionPlan(
            task_description="Test",
            task_type=TaskType.FEATURE,
            steps=[PlanStep(id=1, description="Test", action_type="write", arguments={}, risk="low")],
            total_estimated_time="1 min",
            overall_risk="low",
            requires_approval=False
        )

        pm = PermissionManager(mode=PermissionMode.AUTO)

        # AUTO: No approval needed
        assert pm.get_approval(plan)

        # Switch to PLAN: Approval needed
        pm.set_mode(PermissionMode.PLAN)
        callback = Mock(return_value=False)
        pm.approval_callback = callback

        assert not pm.get_approval(plan)
        callback.assert_called_once()

    def test_callback_override_works_in_all_modes(self):
        """Test that callback is used when provided in all modes."""
        plan = ExecutionPlan(
            task_description="Test",
            task_type=TaskType.FEATURE,
            steps=[PlanStep(id=1, description="Test", action_type="write", arguments={}, risk="high")],
            total_estimated_time="1 min",
            overall_risk="high",
            requires_approval=True
        )

        callback = Mock(return_value=True)

        # PLAN mode with callback
        pm = PermissionManager(mode=PermissionMode.PLAN, approval_callback=callback)
        assert pm.get_approval(plan)
        assert callback.call_count == 1

        # NORMAL mode with callback
        pm.set_mode(PermissionMode.NORMAL)
        assert pm.get_approval(plan)
        assert callback.call_count == 2

        # AUTO mode doesn't call callback (no approval needed)
        pm.set_mode(PermissionMode.AUTO)
        callback.reset_mock()
        assert pm.get_approval(plan)
        callback.assert_not_called()

    def test_permission_mode_persistence(self):
        """Test that permission mode persists across operations."""
        pm = PermissionManager(mode=PermissionMode.PLAN)

        # Create multiple plans
        plans = [
            ExecutionPlan(
                task_description=f"Task {i}",
                task_type=TaskType.EXPLAIN,
                steps=[PlanStep(id=1, description="Test", action_type="read", arguments={}, risk="low")],
                total_estimated_time="1 min",
                overall_risk="low",
                requires_approval=False
            )
            for i in range(3)
        ]

        # All should require approval in PLAN mode
        for plan in plans:
            decision = pm.check_approval_required(plan)
            assert decision.requires_approval
            assert pm.get_mode() == PermissionMode.PLAN
