"""Tests for MCP policy gate: annotation-based classification, blocklist, approval."""

import pytest

from src.integrations.mcp.policy import McpPolicyGate, ToolPolicy
from src.integrations.jira.tools import create_jira_policy_gate


# ---------------------------------------------------------------------------
# ToolPolicy.from_annotations
# ---------------------------------------------------------------------------

class TestToolPolicyFromAnnotations:
    def test_read_only_tool(self):
        annotations = {"readOnlyHint": True, "destructiveHint": False}
        policy = ToolPolicy.from_annotations(annotations)
        assert policy.allowed is True
        assert policy.is_write is False
        assert policy.requires_approval is False
        assert policy.is_destructive is False

    def test_write_tool(self):
        annotations = {"readOnlyHint": False, "destructiveHint": False}
        policy = ToolPolicy.from_annotations(annotations)
        assert policy.allowed is True
        assert policy.is_write is True
        assert policy.requires_approval is True

    def test_destructive_tool(self):
        annotations = {"readOnlyHint": False, "destructiveHint": True}
        policy = ToolPolicy.from_annotations(annotations)
        assert policy.is_write is True
        assert policy.is_destructive is True
        assert policy.requires_approval is True

    def test_destructive_read_only_still_requires_approval(self):
        """Edge case: readOnly=True but destructive=True -> approve."""
        annotations = {"readOnlyHint": True, "destructiveHint": True}
        policy = ToolPolicy.from_annotations(annotations)
        assert policy.is_write is False
        assert policy.is_destructive is True
        assert policy.requires_approval is True

    def test_missing_annotations_assumes_write(self):
        """Conservative default: no annotations -> assume write."""
        policy = ToolPolicy.from_annotations({})
        assert policy.is_write is True
        assert policy.requires_approval is True

    def test_blocked_tool(self):
        annotations = {"readOnlyHint": True, "destructiveHint": False}
        policy = ToolPolicy.from_annotations(annotations, blocked=True)
        assert policy.allowed is False
        assert policy.is_write is False  # classification still correct


# ---------------------------------------------------------------------------
# McpPolicyGate: registration and queries
# ---------------------------------------------------------------------------

class TestPolicyGateRegistration:
    def test_register_read_tool(self):
        gate = McpPolicyGate()
        policy = gate.register_tool(
            "jira_getJiraIssue",
            {"readOnlyHint": True, "destructiveHint": False},
        )
        assert gate.is_allowed("jira_getJiraIssue") is True
        assert gate.requires_approval("jira_getJiraIssue") is False
        assert gate.is_write_tool("jira_getJiraIssue") is False

    def test_register_write_tool(self):
        gate = McpPolicyGate()
        gate.register_tool(
            "jira_createJiraIssue",
            {"readOnlyHint": False, "destructiveHint": False},
        )
        assert gate.is_allowed("jira_createJiraIssue") is True
        assert gate.requires_approval("jira_createJiraIssue") is True
        assert gate.is_write_tool("jira_createJiraIssue") is True

    def test_blocklisted_tool_not_allowed(self):
        gate = McpPolicyGate(blocklist={"jira_admin_danger"})
        gate.register_tool(
            "jira_admin_danger",
            {"readOnlyHint": True, "destructiveHint": False},
        )
        assert gate.is_allowed("jira_admin_danger") is False

    def test_unregistered_tool_not_allowed(self):
        gate = McpPolicyGate()
        assert gate.is_allowed("jira_never_seen") is False

    def test_unregistered_tool_requires_approval(self):
        gate = McpPolicyGate()
        assert gate.requires_approval("jira_never_seen") is True

    def test_unregistered_tool_assumed_write(self):
        gate = McpPolicyGate()
        assert gate.is_write_tool("jira_never_seen") is True


# ---------------------------------------------------------------------------
# Filter and description
# ---------------------------------------------------------------------------

class TestFilterAndDescription:
    def test_filter_allowed(self):
        gate = McpPolicyGate(blocklist={"jira_blocked"})
        gate.register_tool("jira_allowed", {"readOnlyHint": True})
        gate.register_tool("jira_blocked", {"readOnlyHint": True})

        filtered = gate.filter_allowed(["jira_allowed", "jira_blocked", "jira_unknown"])
        assert filtered == ["jira_allowed"]

    def test_description_override_empty_by_default(self):
        gate = McpPolicyGate()
        gate.register_tool("jira_tool", {"readOnlyHint": True})
        assert gate.get_description_override("jira_tool") == ""
        assert gate.get_description_override("jira_unknown") == ""


# ---------------------------------------------------------------------------
# Gate lifecycle
# ---------------------------------------------------------------------------

class TestGateLifecycle:
    def test_clear_removes_all_policies(self):
        gate = McpPolicyGate()
        gate.register_tool("jira_a", {"readOnlyHint": True})
        gate.register_tool("jira_b", {"readOnlyHint": False})
        assert len(gate.policies) == 2

        gate.clear()
        assert len(gate.policies) == 0
        assert gate.is_allowed("jira_a") is False

    def test_policies_property_is_copy(self):
        gate = McpPolicyGate()
        gate.register_tool("a", {"readOnlyHint": True})
        copy = gate.policies
        copy["b"] = ToolPolicy()
        assert "b" not in gate.policies


# ---------------------------------------------------------------------------
# Jira factory
# ---------------------------------------------------------------------------

class TestJiraFactory:
    def test_create_jira_policy_gate(self):
        gate = create_jira_policy_gate()
        # Starts empty, policies are built during discovery
        assert len(gate.policies) == 0
        # Should be a McpPolicyGate instance
        assert isinstance(gate, McpPolicyGate)
