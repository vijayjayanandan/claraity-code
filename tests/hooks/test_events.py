"""Unit tests for hook events and decision types."""

import pytest
from src.hooks.events import HookEvent, HookDecision, HookContinue, HookApproval


class TestHookEvent:
    """Test HookEvent enum."""

    def test_all_events_defined(self):
        """Test that all 9 hook events are defined."""
        expected_events = [
            "PRE_TOOL_USE",
            "POST_TOOL_USE",
            "USER_PROMPT_SUBMIT",
            "NOTIFICATION",
            "SESSION_START",
            "SESSION_END",
            "PRE_COMPACT",
            "STOP",
            "SUBAGENT_STOP",
        ]

        for event_name in expected_events:
            assert hasattr(HookEvent, event_name), f"Missing event: {event_name}"

    def test_event_values(self):
        """Test that event values match expected format."""
        assert HookEvent.PRE_TOOL_USE.value == "PreToolUse"
        assert HookEvent.POST_TOOL_USE.value == "PostToolUse"
        assert HookEvent.USER_PROMPT_SUBMIT.value == "UserPromptSubmit"
        assert HookEvent.SESSION_START.value == "SessionStart"

    def test_event_uniqueness(self):
        """Test that all event values are unique."""
        values = [event.value for event in HookEvent]
        assert len(values) == len(set(values)), "Duplicate event values found"

    def test_event_count(self):
        """Test that we have exactly 9 events."""
        assert len(list(HookEvent)) == 9


class TestHookDecision:
    """Test HookDecision enum."""

    def test_all_decisions_defined(self):
        """Test that all 3 decisions are defined."""
        assert hasattr(HookDecision, "PERMIT")
        assert hasattr(HookDecision, "DENY")
        assert hasattr(HookDecision, "BLOCK")

    def test_decision_values(self):
        """Test decision values."""
        assert HookDecision.PERMIT.value == "permit"
        assert HookDecision.DENY.value == "deny"
        assert HookDecision.BLOCK.value == "block"

    def test_decision_comparison(self):
        """Test that decisions can be compared."""
        assert HookDecision.PERMIT == HookDecision.PERMIT
        assert HookDecision.PERMIT != HookDecision.DENY


class TestHookContinue:
    """Test HookContinue enum."""

    def test_all_continues_defined(self):
        """Test that continue decisions are defined."""
        assert hasattr(HookContinue, "CONTINUE")
        assert hasattr(HookContinue, "BLOCK")

    def test_continue_values(self):
        """Test continue values."""
        assert HookContinue.CONTINUE.value == "continue"
        assert HookContinue.BLOCK.value == "block"


class TestHookApproval:
    """Test HookApproval enum."""

    def test_all_approvals_defined(self):
        """Test that approval decisions are defined."""
        assert hasattr(HookApproval, "APPROVE")
        assert hasattr(HookApproval, "DENY")

    def test_approval_values(self):
        """Test approval values."""
        assert HookApproval.APPROVE.value == "approve"
        assert HookApproval.DENY.value == "deny"


class TestEnumIntegration:
    """Test enum integration and usage."""

    def test_event_iteration(self):
        """Test that we can iterate over events."""
        events = list(HookEvent)
        assert len(events) == 9
        assert HookEvent.PRE_TOOL_USE in events

    def test_decision_string_conversion(self):
        """Test that decisions convert to strings correctly."""
        assert str(HookDecision.PERMIT.value) == "permit"
        assert f"{HookDecision.DENY.value}" == "deny"

    def test_enum_access_by_name(self):
        """Test that enums can be accessed by name."""
        event = HookEvent["PRE_TOOL_USE"]
        assert event == HookEvent.PRE_TOOL_USE

        decision = HookDecision["PERMIT"]
        assert decision == HookDecision.PERMIT
