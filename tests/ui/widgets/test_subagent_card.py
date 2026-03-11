"""Tests for the awaiting_approval header state in SubAgentCard.

Coverage:
- HEADER_ICONS dict: awaiting_approval entry presence and values
- _SubagentHeader.render(): icon, text, and blink styling per status
- SubAgentCard._refresh_header(): promotion to awaiting_approval,
  non-promotion when done/failed, and revert after approval

Total: 10 tests across 3 test classes
"""

import pytest
from unittest.mock import MagicMock, patch

from src.core.events import ToolStatus
from src.ui.widgets.subagent_card import HEADER_ICONS, _SubagentHeader, SubAgentCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_header(subagent_id="test-123", **kwargs):
    """Instantiate a _SubagentHeader outside of a Textual app context."""
    return _SubagentHeader(subagent_id=subagent_id, **kwargs)


def _make_mock_tool_card(status: ToolStatus):
    """Return a lightweight mock that looks like a ToolCard with a .status."""
    card = MagicMock()
    card.status = status
    return card


# ---------------------------------------------------------------------------
# 1. HEADER_ICONS dict
# ---------------------------------------------------------------------------

class TestHeaderIcons:
    """Verify the HEADER_ICONS dict contains the awaiting_approval entry."""

    def test_awaiting_approval_key_present(self):
        """HEADER_ICONS must have an 'awaiting_approval' key."""
        assert "awaiting_approval" in HEADER_ICONS

    def test_awaiting_approval_values(self):
        """awaiting_approval entry should have icon='?', fg='#1e1e1e', bg='#ff8c00'."""
        icon, fg, bg = HEADER_ICONS["awaiting_approval"]
        assert icon == "?"
        assert fg == "#1e1e1e"
        assert bg == "#ff8c00"

    def test_all_expected_statuses_present(self):
        """All four header statuses must exist."""
        expected = {"running", "awaiting_approval", "done", "failed"}
        assert expected == set(HEADER_ICONS.keys())


# ---------------------------------------------------------------------------
# 2. _SubagentHeader.render() output
# ---------------------------------------------------------------------------

class TestSubagentHeaderRender:
    """Test the Rich Text produced by _SubagentHeader.render() for each status."""

    def test_render_awaiting_approval_contains_question_mark_icon(self):
        """When status is 'awaiting_approval', rendered text must contain '?' icon."""
        header = _make_header()
        header.update_status("awaiting_approval", tool_count=3)
        text = header.render()
        rendered = str(text)

        assert "?" in rendered, "Icon '?' missing from awaiting_approval render"

    def test_render_awaiting_approval_contains_approval_label(self):
        """Awaiting approval status should show 'awaiting approval' text."""
        header = _make_header()
        header.update_status("awaiting_approval", tool_count=3)
        text = header.render()
        rendered = str(text)

        assert "awaiting approval" in rendered

    def test_render_awaiting_approval_has_blink_style(self):
        """The icon badge and status label must include 'blink' in their style."""
        header = _make_header()
        header.update_status("awaiting_approval", tool_count=2)
        text = header.render()

        # Collect all style strings from spans
        blink_spans = [
            span for span in text._spans
            if "blink" in str(span.style)
        ]
        assert len(blink_spans) >= 1, (
            "Expected at least one span with 'blink' style for awaiting_approval"
        )

    def test_render_running_shows_asterisk_and_live_status(self):
        """Regression: 'running' status must show '*' icon and live status info."""
        header = _make_header()
        header.update_status("running", tool_count=1)
        text = header.render()
        rendered = str(text)

        assert "*" in rendered, "Icon '*' missing from running render"
        assert "1 tools" in rendered, "Tool count missing from running render"
        assert "s" in rendered, "Elapsed time missing from running render"

    def test_render_running_has_no_blink_style(self):
        """Running status must NOT apply blink style to any span."""
        header = _make_header()
        header.update_status("running", tool_count=1)
        text = header.render()

        blink_spans = [
            span for span in text._spans
            if "blink" in str(span.style)
        ]
        assert len(blink_spans) == 0, (
            "Running status should not have any blink-styled spans"
        )


# ---------------------------------------------------------------------------
# 3. SubAgentCard._refresh_header() logic
# ---------------------------------------------------------------------------

class TestRefreshHeader:
    """Test _refresh_header promotion/demotion of the header status.

    We bypass Textual's compose/mount lifecycle by directly setting
    _header, _status, and _tool_cards on a SubAgentCard instance, then
    calling _refresh_header() and inspecting the mock header's calls.
    """

    @staticmethod
    def _make_card_with_mock_header(
        card_status="running",
        tool_cards=None,
    ):
        """Build a SubAgentCard with a mocked header, skipping Textual mount.

        Patches __init__ to avoid Textual Container initialisation, then
        manually sets the attributes that _refresh_header() reads.
        """
        with patch.object(SubAgentCard, "__init__", lambda self, **kw: None):
            card = SubAgentCard.__new__(SubAgentCard)

        card._status = card_status
        card._tool_count = len(tool_cards) if tool_cards else 0
        card._duration_ms = None
        card._tool_cards = tool_cards or {}
        card._header = MagicMock()

        return card

    def test_promotes_to_awaiting_approval_when_running(self):
        """When card is running and a tool has AWAITING_APPROVAL, header gets
        'awaiting_approval' status."""
        card = self._make_card_with_mock_header(
            card_status="running",
            tool_cards={
                "tc-1": _make_mock_tool_card(ToolStatus.SUCCESS),
                "tc-2": _make_mock_tool_card(ToolStatus.AWAITING_APPROVAL),
            },
        )
        card._refresh_header()

        card._header.update_status.assert_called_once_with(
            "awaiting_approval", card._tool_count, None
        )

    def test_stays_running_when_no_tools_awaiting(self):
        """When card is running but no tool is AWAITING_APPROVAL, header stays
        'running'."""
        card = self._make_card_with_mock_header(
            card_status="running",
            tool_cards={
                "tc-1": _make_mock_tool_card(ToolStatus.RUNNING),
                "tc-2": _make_mock_tool_card(ToolStatus.SUCCESS),
            },
        )
        card._refresh_header()

        card._header.update_status.assert_called_once_with(
            "running", card._tool_count, None
        )

    def test_does_not_promote_when_status_is_done(self):
        """Even if a tool has AWAITING_APPROVAL, a 'done' card stays 'done'."""
        card = self._make_card_with_mock_header(
            card_status="done",
            tool_cards={
                "tc-1": _make_mock_tool_card(ToolStatus.AWAITING_APPROVAL),
            },
        )
        card._refresh_header()

        card._header.update_status.assert_called_once_with(
            "done", card._tool_count, None
        )

    def test_does_not_promote_when_status_is_failed(self):
        """Even if a tool has AWAITING_APPROVAL, a 'failed' card stays 'failed'."""
        card = self._make_card_with_mock_header(
            card_status="failed",
            tool_cards={
                "tc-1": _make_mock_tool_card(ToolStatus.AWAITING_APPROVAL),
            },
        )
        card._refresh_header()

        card._header.update_status.assert_called_once_with(
            "failed", card._tool_count, None
        )

    def test_reverts_to_running_after_approval(self):
        """After a tool transitions from AWAITING_APPROVAL to RUNNING, the
        header should revert to 'running'."""
        tool_card = _make_mock_tool_card(ToolStatus.AWAITING_APPROVAL)
        card = self._make_card_with_mock_header(
            card_status="running",
            tool_cards={"tc-1": tool_card},
        )

        # First call: should promote to awaiting_approval
        card._refresh_header()
        card._header.update_status.assert_called_with(
            "awaiting_approval", card._tool_count, None
        )

        # Simulate the tool being approved and starting execution
        tool_card.status = ToolStatus.RUNNING
        card._header.reset_mock()

        # Second call: should revert to running
        card._refresh_header()
        card._header.update_status.assert_called_once_with(
            "running", card._tool_count, None
        )

    def test_empty_tool_cards_stays_running(self):
        """A running card with no tool cards should stay 'running'."""
        card = self._make_card_with_mock_header(
            card_status="running",
            tool_cards={},
        )
        card._refresh_header()

        card._header.update_status.assert_called_once_with(
            "running", 0, None
        )
