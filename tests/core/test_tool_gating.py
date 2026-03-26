"""
Unit tests for ToolGatingService.

Tests all four gating checks and the combined evaluate() method.
No API calls needed - all dependencies are mocked.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from src.core.tool_gating import ToolGatingService, GateAction, GateResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plan_mode_state():
    """Mock PlanModeState that is inactive by default."""
    mock = MagicMock()
    mock.is_active = False
    mock.plan_file_path = None
    # Default: gate_tool returns ALLOW
    from src.core.plan_mode import PlanGateDecision
    mock.gate_tool.return_value = PlanGateDecision.ALLOW
    return mock


@pytest.fixture
def director_adapter():
    """Mock DirectorAdapter that is inactive by default."""
    mock = MagicMock()
    mock.is_active = False
    return mock


@pytest.fixture
def permission_manager():
    """Mock PermissionManager in NORMAL mode."""
    from src.core.permission_mode import PermissionMode
    mock = MagicMock()
    mock.get_mode.return_value = PermissionMode.NORMAL
    mock.mode = PermissionMode.NORMAL
    return mock


@pytest.fixture
def error_tracker():
    """Mock ErrorRecoveryTracker - no repeats by default."""
    mock = MagicMock()
    mock.is_repeated_failed_call.return_value = (False, None)
    return mock


@pytest.fixture
def mcp_manager():
    """Mock McpConnectionManager - no MCP tools by default."""
    mock = MagicMock()
    mock.is_mcp_tool.return_value = False
    mock.requires_approval.return_value = False
    return mock


@pytest.fixture
def gating(plan_mode_state, director_adapter, permission_manager, error_tracker, mcp_manager):
    """Build a ToolGatingService with all mock dependencies."""
    return ToolGatingService(
        plan_mode_state=plan_mode_state,
        director_adapter=director_adapter,
        permission_manager=permission_manager,
        error_tracker=error_tracker,
        mcp_manager=mcp_manager,
    )


# ---------------------------------------------------------------------------
# Test: check_repeat
# ---------------------------------------------------------------------------

class TestCheckRepeat:

    def test_no_repeat_returns_none(self, gating):
        result = gating.check_repeat("read_file", {"file_path": "/tmp/a.txt"})
        assert result is None

    def test_repeated_call_returns_blocked(self, gating, error_tracker):
        error_tracker.is_repeated_failed_call.return_value = (True, "read_file(/tmp/a.txt)")
        result = gating.check_repeat("read_file", {"file_path": "/tmp/a.txt"})
        assert result is not None
        assert result.action == GateAction.BLOCKED_REPEAT
        assert "BLOCKED" in result.message
        assert result.call_summary == "read_file(/tmp/a.txt)"


# ---------------------------------------------------------------------------
# Test: check_plan_mode_gate
# ---------------------------------------------------------------------------

class TestCheckPlanModeGate:

    def test_allowed_returns_none(self, gating):
        result = gating.check_plan_mode_gate("read_file", {"file_path": "/tmp/a.txt"})
        assert result is None

    def test_denied_returns_gate_result(self, gating, plan_mode_state):
        from src.core.plan_mode import PlanGateDecision
        plan_mode_state.gate_tool.return_value = PlanGateDecision.DENY
        plan_mode_state.plan_file_path = "/tmp/plan.md"

        result = gating.check_plan_mode_gate("write_file", {"file_path": "/tmp/x.txt"})

        assert result is not None
        assert result.action == GateAction.DENY
        assert "PLAN_MODE_GATED" in result.gate_response["error_code"]
        assert "not allowed in plan mode" in result.message

    def test_require_approval_returns_gate_result(self, gating, plan_mode_state):
        from src.core.plan_mode import PlanGateDecision
        plan_mode_state.gate_tool.return_value = PlanGateDecision.REQUIRE_APPROVAL
        plan_mode_state.plan_file_path = "/tmp/plan.md"

        result = gating.check_plan_mode_gate("write_file", {"file_path": "/tmp/x.txt"})

        assert result is not None
        assert result.action == GateAction.DENY
        assert "PLAN_APPROVAL_REQUIRED" in result.gate_response["error_code"]


# ---------------------------------------------------------------------------
# Test: check_director_gate
# ---------------------------------------------------------------------------

class TestCheckDirectorGate:

    def test_inactive_returns_none(self, gating):
        result = gating.check_director_gate("write_file", {"file_path": "/tmp/x.txt"})
        assert result is None

    def test_active_allowed_returns_none(self, gating, director_adapter):
        director_adapter.is_active = True
        from src.director.adapter import DirectorGateDecision
        director_adapter.gate_tool.return_value = DirectorGateDecision.ALLOW

        result = gating.check_director_gate("read_file", {"file_path": "/tmp/a.txt"})
        assert result is None

    def test_active_denied_returns_gate_result(self, gating, director_adapter):
        director_adapter.is_active = True
        from src.director.adapter import DirectorGateDecision
        director_adapter.gate_tool.return_value = DirectorGateDecision.DENY
        director_adapter.phase.name = "UNDERSTAND"

        result = gating.check_director_gate("write_file", {"file_path": "/tmp/x.txt"})

        assert result is not None
        assert result.action == GateAction.DENY
        assert "DIRECTOR_MODE_GATED" in result.gate_response["error_code"]
        assert "UNDERSTAND" in result.message


# ---------------------------------------------------------------------------
# Test: needs_approval
# ---------------------------------------------------------------------------

class TestNeedsApproval:

    def test_auto_mode_never_needs_approval(self, gating, permission_manager):
        from src.core.permission_mode import PermissionMode
        permission_manager.get_mode.return_value = PermissionMode.AUTO

        assert gating.needs_approval("write_file", {"file_path": "/tmp/x"}) is False
        assert gating.needs_approval("run_command", {"command": "ls"}) is False

    def test_normal_mode_risky_tools_need_approval(self, gating):
        assert gating.needs_approval("write_file", {"file_path": "/tmp/x"}) is True
        assert gating.needs_approval("edit_file", {"file_path": "/tmp/x"}) is True
        assert gating.needs_approval("run_command", {"command": "ls"}) is True
        assert gating.needs_approval("git_commit", {}) is True

    def test_normal_mode_safe_tools_no_approval(self, gating):
        assert gating.needs_approval("read_file", {"file_path": "/tmp/x"}) is False
        assert gating.needs_approval("grep", {"pattern": "foo"}) is False
        assert gating.needs_approval("list_directory", {"path": "/tmp"}) is False

    def test_plan_mode_no_approval_for_builtin(self, gating, permission_manager):
        from src.core.permission_mode import PermissionMode
        permission_manager.get_mode.return_value = PermissionMode.PLAN

        assert gating.needs_approval("write_file", {"file_path": "/tmp/x"}) is False

    def test_plan_mode_mcp_tool_delegates(self, gating, permission_manager, mcp_manager):
        from src.core.permission_mode import PermissionMode
        permission_manager.get_mode.return_value = PermissionMode.PLAN
        mcp_manager.is_mcp_tool.return_value = True
        mcp_manager.requires_approval.return_value = True

        assert gating.needs_approval("mcp_write_tool", {}) is True

    def test_agent_internal_write_bypasses_approval(self, gating):
        """Agent-internal writes (plan files, sessions) bypass approval."""
        # is_agent_internal_write is imported inside needs_approval; patch at source
        with patch("src.core.plan_mode.is_agent_internal_write", return_value=True):
            result = gating.needs_approval(
                "write_file",
                {"file_path": ".clarity/sessions/test.jsonl"}
            )
        assert result is False


# ---------------------------------------------------------------------------
# Test: evaluate (combined)
# ---------------------------------------------------------------------------

class TestEvaluate:

    def test_allow_when_no_gates_triggered(self, gating):
        result = gating.evaluate("read_file", {"file_path": "/tmp/a.txt"})
        assert result.action == GateAction.ALLOW

    def test_repeat_takes_priority(self, gating, error_tracker, plan_mode_state):
        """Repeat check runs before plan/director gates."""
        error_tracker.is_repeated_failed_call.return_value = (True, "write_file(/tmp/x)")
        from src.core.plan_mode import PlanGateDecision
        plan_mode_state.gate_tool.return_value = PlanGateDecision.DENY

        result = gating.evaluate("write_file", {"file_path": "/tmp/x"})
        assert result.action == GateAction.BLOCKED_REPEAT

    def test_plan_mode_gate_before_director(self, gating, plan_mode_state, director_adapter):
        """Plan mode gate runs before director gate."""
        from src.core.plan_mode import PlanGateDecision
        plan_mode_state.gate_tool.return_value = PlanGateDecision.DENY
        plan_mode_state.plan_file_path = "/tmp/plan.md"
        director_adapter.is_active = True

        result = gating.evaluate("write_file", {"file_path": "/tmp/x"})
        assert result.action == GateAction.DENY
        assert "PLAN_MODE_GATED" in result.gate_response["error_code"]

    def test_needs_approval_when_risky(self, gating):
        result = gating.evaluate("write_file", {"file_path": "/tmp/x"})
        assert result.action == GateAction.NEEDS_APPROVAL

    def test_allow_safe_tool_normal_mode(self, gating):
        result = gating.evaluate("read_file", {"file_path": "/tmp/a.txt"})
        assert result.action == GateAction.ALLOW


# ---------------------------------------------------------------------------
# Test: format_gate_response
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Test: Auto-approve categories
# ---------------------------------------------------------------------------

class TestAutoApproveCategories:

    def test_default_categories(self, gating):
        cats = gating.get_auto_approve_categories()
        assert cats == {"browser": False, "edit": False, "execute": False, "read": True}

    def test_set_and_get_categories(self, gating):
        result = gating.set_auto_approve_categories({"edit": True})
        assert result["edit"] is True
        assert result["execute"] is False
        assert result["browser"] is False
        assert result["read"] is True

    def test_unknown_category_ignored(self, gating):
        result = gating.set_auto_approve_categories({"edit": True, "unknown_cat": True})
        assert result == {"browser": False, "edit": True, "execute": False, "read": True}

    def test_is_category_auto_approved_edit(self, gating):
        gating.set_auto_approve_categories({"edit": True})
        assert gating.is_category_auto_approved("write_file") is True
        assert gating.is_category_auto_approved("edit_file") is True
        assert gating.is_category_auto_approved("append_to_file") is True

    def test_is_category_auto_approved_execute(self, gating):
        gating.set_auto_approve_categories({"execute": True})
        assert gating.is_category_auto_approved("run_command") is True
        assert gating.is_category_auto_approved("git_commit") is True
        assert gating.is_category_auto_approved("run_tests") is True

    def test_is_category_auto_approved_browser(self, gating):
        gating.set_auto_approve_categories({"browser": True})
        assert gating.is_category_auto_approved("web_search") is True
        assert gating.is_category_auto_approved("web_fetch") is True

    def test_uncategorized_tool_not_auto_approved(self, gating):
        gating.set_auto_approve_categories({"edit": True, "execute": True, "browser": True})
        assert gating.is_category_auto_approved("some_unknown_tool") is False

    def test_read_category_auto_approved_by_default(self, gating):
        assert gating.is_category_auto_approved("read_file") is True
        assert gating.is_category_auto_approved("list_directory") is True
        assert gating.is_category_auto_approved("search_code") is True

    def test_read_category_can_be_disabled(self, gating):
        gating.set_auto_approve_categories({"read": False})
        assert gating.is_category_auto_approved("read_file") is False


# ---------------------------------------------------------------------------
# Test: needs_approval with categories
# ---------------------------------------------------------------------------

class TestNeedsApprovalWithCategories:

    def test_edit_approved_skips_write_file(self, gating):
        gating.set_auto_approve_categories({"edit": True})
        assert gating.needs_approval("write_file", {"file_path": "/tmp/x"}) is False

    def test_execute_approved_skips_run_command(self, gating):
        gating.set_auto_approve_categories({"execute": True})
        assert gating.needs_approval("run_command", {"command": "ls"}) is False

    def test_mixed_categories(self, gating):
        gating.set_auto_approve_categories({"edit": True, "execute": False})
        assert gating.needs_approval("write_file", {"file_path": "/tmp/x"}) is False
        assert gating.needs_approval("run_command", {"command": "ls"}) is True

    def test_evaluate_allows_with_category(self, gating):
        gating.set_auto_approve_categories({"edit": True})
        result = gating.evaluate("write_file", {"file_path": "/tmp/x"})
        assert result.action == GateAction.ALLOW

    def test_evaluate_needs_approval_without_category(self, gating):
        result = gating.evaluate("write_file", {"file_path": "/tmp/x"})
        assert result.action == GateAction.NEEDS_APPROVAL

    def test_plan_mode_still_gates(self, gating, plan_mode_state):
        """Plan mode DENY takes priority over category approve."""
        from src.core.plan_mode import PlanGateDecision
        plan_mode_state.gate_tool.return_value = PlanGateDecision.DENY
        plan_mode_state.plan_file_path = "/tmp/plan.md"
        gating.set_auto_approve_categories({"edit": True})

        result = gating.evaluate("write_file", {"file_path": "/tmp/x"})
        assert result.action == GateAction.DENY


# ---------------------------------------------------------------------------
# Test: format_gate_response
# ---------------------------------------------------------------------------

class TestFormatGateResponse:

    def test_formats_as_json(self, gating):
        response = {"status": "denied", "error_code": "TEST", "message": "test msg"}
        formatted = gating.format_gate_response(response)
        parsed = json.loads(formatted)
        assert parsed["error_code"] == "TEST"
