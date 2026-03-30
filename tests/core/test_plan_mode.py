"""Tests for Plan Mode state management."""

import pytest
from pathlib import Path
import tempfile
import shutil
import os

from src.core.plan_mode import (
    PlanModeState,
    PlanGateDecision,
    READ_ONLY_TOOLS,
    PLAN_MODE_TOOLS,
)


class TestPlanGateDecision:
    """Test PlanGateDecision enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert PlanGateDecision.ALLOW.value == "allow"
        assert PlanGateDecision.DENY.value == "deny"
        assert PlanGateDecision.REQUIRE_APPROVAL.value == "require_approval"


class TestReadOnlyTools:
    """Test READ_ONLY_TOOLS constant."""

    def test_contains_file_reading_tools(self):
        """Verify file reading tools are in READ_ONLY_TOOLS."""
        assert "read_file" in READ_ONLY_TOOLS
        assert "list_directory" in READ_ONLY_TOOLS

    def test_contains_search_tools(self):
        """Verify search tools are in READ_ONLY_TOOLS."""
        assert "grep" in READ_ONLY_TOOLS
        assert "glob" in READ_ONLY_TOOLS
        assert "search_code" in READ_ONLY_TOOLS

    def test_does_not_contain_write_tools(self):
        """Verify write tools are NOT in READ_ONLY_TOOLS."""
        assert "write_file" not in READ_ONLY_TOOLS
        assert "edit_file" not in READ_ONLY_TOOLS
        assert "run_command" not in READ_ONLY_TOOLS


class TestPlanModeTools:
    """Test PLAN_MODE_TOOLS constant."""

    def test_contains_plan_tools(self):
        """Verify plan mode tools are listed."""
        assert "enter_plan_mode" in PLAN_MODE_TOOLS
        assert "request_plan_approval" in PLAN_MODE_TOOLS


class TestPlanModeState:
    """Test PlanModeState class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def plan_state(self, temp_dir):
        """Create a PlanModeState instance with temp directory."""
        return PlanModeState(claraity_dir=temp_dir / ".claraity")

    def test_initial_state(self, plan_state):
        """Test initial state is inactive."""
        assert plan_state.is_active is False
        assert plan_state.plan_file_path is None
        assert plan_state.session_id is None
        assert plan_state.plan_hash is None
        assert plan_state.approved_hash is None

    def test_enter_creates_plan_file(self, plan_state, temp_dir):
        """Test entering plan mode creates plan file."""
        result = plan_state.enter("test-session-123")

        assert plan_state.is_active is True
        assert plan_state.session_id == "test-session-123"
        assert "plan_path" in result

        # Verify file was created
        plan_path = Path(result["plan_path"])
        assert plan_path.exists()
        assert plan_path.name == "test-session-123.md"

    def test_enter_creates_template(self, plan_state):
        """Test entering plan mode creates template content."""
        plan_state.enter("test-session")

        content = plan_state.get_plan_content()
        assert content is not None
        assert "# Plan: test-session" in content
        assert "## Summary" in content
        assert "## Implementation Steps" in content
        assert "## Verification" in content

    def test_enter_does_not_overwrite_existing(self, plan_state):
        """Test entering doesn't overwrite existing plan file."""
        plan_state.enter("test-session")

        # Modify the plan file
        plan_state.plan_file_path.write_text("Custom content", encoding="utf-8")

        # Enter again (simulating re-entry)
        plan_state.is_active = False
        plan_state.enter("test-session")

        # Content should be preserved
        content = plan_state.get_plan_content()
        assert content == "Custom content"

    def test_exit_for_approval_computes_hash(self, plan_state):
        """Test exiting for approval computes plan hash."""
        plan_state.enter("test-session")

        result = plan_state.exit_for_approval()

        assert "plan_hash" in result
        assert len(result["plan_hash"]) == 64  # Full SHA256 hex digest
        assert plan_state.plan_hash == result["plan_hash"]

    def test_exit_for_approval_returns_excerpt(self, plan_state):
        """Test exiting for approval returns excerpt."""
        plan_state.enter("test-session")

        result = plan_state.exit_for_approval()

        assert "excerpt" in result
        assert "truncated" in result
        assert result["truncated"] is False  # Template is small

    def test_exit_for_approval_truncates_large_content(self, plan_state):
        """Test exiting truncates content over 8000 chars."""
        plan_state.enter("test-session")

        # Write large content
        large_content = "x" * 10000
        plan_state.plan_file_path.write_text(large_content, encoding="utf-8")

        result = plan_state.exit_for_approval()

        assert result["truncated"] is True
        assert len(result["excerpt"]) == 8003  # 8000 + "..."
        assert result["excerpt"].endswith("...")

    def test_exit_for_approval_error_when_not_active(self, plan_state):
        """Test exiting when not active returns error."""
        result = plan_state.exit_for_approval()

        assert "error" in result
        assert "Not in plan mode" in result["error"]

    def test_approve_with_matching_hash(self, plan_state):
        """Test approving with matching hash succeeds."""
        plan_state.enter("test-session")
        result = plan_state.exit_for_approval()
        plan_hash = result["plan_hash"]

        approved = plan_state.approve(plan_hash)

        assert approved is True
        assert plan_state.approved_hash == plan_hash
        assert plan_state.is_active is False

    def test_approve_with_wrong_hash(self, plan_state):
        """Test approving with wrong hash fails."""
        plan_state.enter("test-session")
        plan_state.exit_for_approval()

        approved = plan_state.approve("wrong-hash")

        assert approved is False
        assert plan_state.approved_hash is None

    def test_reject_stays_in_plan_mode(self, plan_state):
        """Test rejecting stays in plan mode."""
        plan_state.enter("test-session")
        plan_state.exit_for_approval()

        plan_state.reject()

        # Should be back in plan mode with hash cleared (for revisions)
        assert plan_state.plan_file_path is not None
        assert plan_state.is_active is True
        assert plan_state.plan_hash is None
        assert plan_state._awaiting_approval is False

    def test_reset_clears_all_state(self, plan_state):
        """Test reset clears all state."""
        plan_state.enter("test-session")
        plan_state.exit_for_approval()

        plan_state.reset()

        assert plan_state.is_active is False
        assert plan_state.plan_file_path is None
        assert plan_state.session_id is None
        assert plan_state.plan_hash is None
        assert plan_state.approved_hash is None

    def test_is_awaiting_approval(self, plan_state):
        """Test is_awaiting_approval method."""
        plan_state.enter("test-session")
        assert plan_state.is_awaiting_approval() is False

        plan_state.exit_for_approval()
        assert plan_state.is_awaiting_approval() is True

        plan_state.approve(plan_state.plan_hash)
        assert plan_state.is_awaiting_approval() is False


class TestPlanModeGating:
    """Test tool gating in plan mode."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def plan_state(self, temp_dir):
        """Create a PlanModeState in active plan mode."""
        state = PlanModeState(claraity_dir=temp_dir / ".claraity")
        state.enter("test-session")
        return state

    def test_all_tools_allowed_when_not_active(self, temp_dir):
        """Test all tools allowed when not in plan mode."""
        state = PlanModeState(claraity_dir=temp_dir / ".claraity")

        assert state.gate_tool("write_file", "/some/path.py") == PlanGateDecision.ALLOW
        assert state.gate_tool("run_command") == PlanGateDecision.ALLOW

    def test_read_only_tools_allowed(self, plan_state):
        """Test read-only tools allowed in plan mode."""
        for tool in READ_ONLY_TOOLS:
            decision = plan_state.gate_tool(tool)
            assert decision == PlanGateDecision.ALLOW, f"{tool} should be allowed"

    def test_plan_mode_tools_allowed(self, plan_state):
        """Test plan mode tools allowed in plan mode."""
        for tool in PLAN_MODE_TOOLS:
            decision = plan_state.gate_tool(tool)
            assert decision == PlanGateDecision.ALLOW, f"{tool} should be allowed"

    def test_write_tools_denied(self, plan_state):
        """Test write tools denied in plan mode."""
        assert plan_state.gate_tool("write_file", "/other/file.py") == PlanGateDecision.DENY
        assert plan_state.gate_tool("edit_file", "/other/file.py") == PlanGateDecision.DENY
        assert plan_state.gate_tool("run_command") == PlanGateDecision.DENY

    def test_write_to_plan_file_allowed(self, plan_state):
        """Test writing to plan file is allowed."""
        plan_path = str(plan_state.plan_file_path)

        assert plan_state.gate_tool("write_file", plan_path) == PlanGateDecision.ALLOW
        assert plan_state.gate_tool("edit_file", plan_path) == PlanGateDecision.ALLOW
        assert plan_state.gate_tool("append_to_file", plan_path) == PlanGateDecision.ALLOW

    def test_write_to_other_file_denied(self, plan_state, temp_dir):
        """Test writing to other files is denied."""
        other_path = str(temp_dir / "other.py")

        assert plan_state.gate_tool("write_file", other_path) == PlanGateDecision.DENY
        assert plan_state.gate_tool("edit_file", other_path) == PlanGateDecision.DENY

    def test_path_traversal_blocked(self, plan_state, temp_dir):
        """Test path traversal attempts are blocked."""
        # Try to write to a file with same name in different directory
        fake_plan = str(temp_dir / "fake" / "test-session.md")

        assert plan_state.gate_tool("write_file", fake_plan) == PlanGateDecision.DENY

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-specific test")
    def test_case_insensitive_path_on_windows(self, plan_state):
        """Test case-insensitive path comparison on Windows."""
        plan_path = str(plan_state.plan_file_path)
        upper_path = plan_path.upper()

        # On Windows, both should be allowed
        assert plan_state.gate_tool("write_file", upper_path) == PlanGateDecision.ALLOW

    def test_unknown_tool_denied(self, plan_state):
        """Test unknown tools are denied in plan mode."""
        assert plan_state.gate_tool("unknown_tool") == PlanGateDecision.DENY
        assert plan_state.gate_tool("malicious_tool") == PlanGateDecision.DENY


class TestAgentPlanModeIntegration:
    """Integration tests verifying plan mode works with CodingAgent."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set up minimal environment for agent creation."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        monkeypatch.setenv("LLM_BACKEND", "openai")
        monkeypatch.setenv("LLM_HOST", "https://api.openai.com/v1")
        monkeypatch.setenv("MAX_CONTEXT_TOKENS", "8000")
        # Embedding config (required by MemoryManager)
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")

    def test_agent_has_plan_mode_state(self, mock_env, tmp_path):
        """Test CodingAgent initializes with plan_mode_state attribute."""
        from src.core.agent import CodingAgent

        agent = CodingAgent(
            model_name="gpt-4",
            backend="openai",
            base_url="https://api.openai.com/v1",
            context_window=8000,
            working_directory=str(tmp_path),
            api_key="test-key",
        )

        # Verify plan_mode_state exists and is properly initialized
        assert hasattr(agent, 'plan_mode_state')
        assert agent.plan_mode_state is not None
        assert agent.plan_mode_state.is_active is False

    def test_agent_plan_mode_tools_registered(self, mock_env, tmp_path):
        """Test plan mode tools are registered with the agent."""
        from src.core.agent import CodingAgent

        agent = CodingAgent(
            model_name="gpt-4",
            backend="openai",
            base_url="https://api.openai.com/v1",
            context_window=8000,
            working_directory=str(tmp_path),
            api_key="test-key",
        )

        # Verify plan mode tools are registered
        assert hasattr(agent, '_enter_plan_mode_tool')
        assert hasattr(agent, '_request_plan_approval_tool')
        assert agent._enter_plan_mode_tool.plan_mode_state is agent.plan_mode_state
        assert agent._request_plan_approval_tool.plan_mode_state is agent.plan_mode_state

    def test_set_permission_mode_activates_plan_state(self, mock_env, tmp_path):
        """Test set_permission_mode('plan') activates plan_mode_state."""
        from src.core.agent import CodingAgent

        agent = CodingAgent(
            model_name="gpt-4",
            backend="openai",
            base_url="https://api.openai.com/v1",
            context_window=8000,
            working_directory=str(tmp_path),
            api_key="test-key",
        )

        # Initially not in plan mode
        assert agent.plan_mode_state.is_active is False
        assert agent.get_permission_mode() == "normal"

        # Set to plan mode
        agent.set_permission_mode("plan")
        assert agent.get_permission_mode() == "plan"
        assert agent.plan_mode_state.is_active is True
        assert agent.plan_mode_state.plan_file_path is not None

        # Set back to normal mode
        agent.set_permission_mode("normal")
        assert agent.get_permission_mode() == "normal"
        assert agent.plan_mode_state.is_active is False

    def test_plan_mode_gates_write_tools(self, mock_env, tmp_path):
        """Test that plan mode actually gates write tools."""
        from src.core.agent import CodingAgent
        from src.core.plan_mode import PlanGateDecision

        agent = CodingAgent(
            model_name="gpt-4",
            backend="openai",
            base_url="https://api.openai.com/v1",
            context_window=8000,
            working_directory=str(tmp_path),
            api_key="test-key",
        )

        # In normal mode, write_file is allowed
        assert agent.plan_mode_state.gate_tool("write_file", "/some/path.py") == PlanGateDecision.ALLOW

        # Enter plan mode
        agent.set_permission_mode("plan")

        # Now write_file is denied (unless writing to plan file)
        assert agent.plan_mode_state.gate_tool("write_file", "/some/path.py") == PlanGateDecision.DENY

        # But read_file is still allowed
        assert agent.plan_mode_state.gate_tool("read_file", "/some/path.py") == PlanGateDecision.ALLOW

        # Writing to plan file is allowed
        plan_path = str(agent.plan_mode_state.plan_file_path)
        assert agent.plan_mode_state.gate_tool("write_file", plan_path) == PlanGateDecision.ALLOW
