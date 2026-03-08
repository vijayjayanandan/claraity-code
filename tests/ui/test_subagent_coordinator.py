"""Tests for src.ui.subagent_coordinator - subagent lifecycle management."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from src.ui.subagent_coordinator import SubagentCoordinator


# ---- Helpers ----

def make_coordinator(tool_cards=None):
    """Create a SubagentCoordinator with mock dependencies."""
    tool_cards = tool_cards if tool_cards is not None else {}
    mount_callback = MagicMock()
    coord = SubagentCoordinator(
        tool_cards=tool_cards,
        mount_callback=mount_callback,
    )
    return coord, mount_callback


# ---- Registration / Unregistration ----

class TestRegistration:
    def test_on_subagent_registered_stores_subscription(self):
        coord, _ = make_coordinator()
        coord.on_subagent_registered(
            subagent_id="sub-1",
            store=MagicMock(),
            transcript_path=Path("/tmp/sub.jsonl"),
            parent_tool_call_id="tc-1",
            model_name="test-model",
            subagent_name="planner",
        )
        assert "sub-1" in coord.subscriptions
        assert coord.subscriptions["sub-1"]["parent_tool_call_id"] == "tc-1"
        assert coord.subscriptions["sub-1"]["model_name"] == "test-model"

    def test_on_subagent_unregistered_removes_subscription(self):
        coord, _ = make_coordinator()
        # Register first
        coord.on_subagent_registered(
            subagent_id="sub-1",
            store=None,
            transcript_path=Path("/tmp/sub.jsonl"),
            parent_tool_call_id="tc-1",
        )
        assert "sub-1" in coord.subscriptions

        # Unregister
        coord.on_subagent_unregistered("sub-1")
        assert "sub-1" not in coord.subscriptions

    def test_unregister_marks_card_completed(self):
        coord, _ = make_coordinator()
        card = MagicMock()
        coord._subagent_subscriptions["sub-1"] = {"card": card}

        coord.on_subagent_unregistered("sub-1")
        card.mark_completed.assert_called_once()

    def test_unregister_nonexistent_is_safe(self):
        coord, _ = make_coordinator()
        # Should not raise
        coord.on_subagent_unregistered("nonexistent")


# ---- Card Mounting ----

class TestCardMounting:
    def test_mounts_card_when_parent_exists(self):
        parent_card = MagicMock()
        tool_cards = {"tc-1": parent_card}
        coord, mount_cb = make_coordinator(tool_cards=tool_cards)

        with patch("src.ui.widgets.subagent_card.SubAgentCard") as MockCard:
            mock_card_instance = MagicMock()
            MockCard.return_value = mock_card_instance

            coord.on_subagent_registered(
                subagent_id="sub-1",
                store=MagicMock(),
                transcript_path=Path("/tmp/sub.jsonl"),
                parent_tool_call_id="tc-1",
                model_name="model-x",
            )

            # Should call mount_callback (call_later) with parent_card.mount
            mount_cb.assert_called_once()
            assert coord.subscriptions["sub-1"]["card"] is mock_card_instance

    def test_queues_mount_when_parent_missing(self):
        coord, mount_cb = make_coordinator(tool_cards={})

        coord.on_subagent_registered(
            subagent_id="sub-1",
            store=None,
            transcript_path=Path("/tmp/sub.jsonl"),
            parent_tool_call_id="tc-1",
        )

        # Should not try to mount
        mount_cb.assert_not_called()
        # Should be in pending queue
        assert "tc-1" in coord._pending_subagent_mounts

    def test_on_tool_card_created_flushes_pending(self):
        parent_card = MagicMock()
        tool_cards = {}
        coord, mount_cb = make_coordinator(tool_cards=tool_cards)

        # Queue a pending mount
        coord._pending_subagent_mounts["tc-1"] = {
            "subagent_id": "sub-1",
            "transcript_path": Path("/tmp/sub.jsonl"),
            "model_name": "model-x",
            "subagent_name": "",
        }
        coord._subagent_subscriptions["sub-1"] = {"card": None, "store": None}

        # Now the parent card arrives
        tool_cards["tc-1"] = parent_card

        with patch("src.ui.widgets.subagent_card.SubAgentCard"):
            coord.on_tool_card_created("tc-1", parent_card)

        # Pending should be consumed
        assert "tc-1" not in coord._pending_subagent_mounts

    def test_on_tool_card_created_no_pending_is_noop(self):
        coord, _ = make_coordinator()
        # Should not raise
        coord.on_tool_card_created("tc-nonexistent", MagicMock())


# ---- Notification Handling ----

class TestNotificationHandling:
    def test_handle_notification_calls_mount_callback(self):
        coord, mount_cb = make_coordinator()
        notification = MagicMock()

        coord.handle_subagent_notification("sub-1", notification)
        mount_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_handle_routes_to_card(self):
        coord, _ = make_coordinator()
        card = AsyncMock()
        coord._subagent_subscriptions["sub-1"] = {"card": card}

        notification = MagicMock()
        await coord.async_handle_subagent_notification("sub-1", notification)
        card.update_from_notification.assert_called_once_with(notification)

    @pytest.mark.asyncio
    async def test_async_handle_buffers_when_no_card(self):
        coord, _ = make_coordinator()
        coord._subagent_subscriptions["sub-1"] = {"card": None}

        notification = MagicMock()
        await coord.async_handle_subagent_notification("sub-1", notification)

        assert len(coord._buffered_subagent_notifications["sub-1"]) == 1

    @pytest.mark.asyncio
    async def test_buffer_capped_at_500(self):
        coord, _ = make_coordinator()
        coord._subagent_subscriptions["sub-1"] = {"card": None}
        coord._buffered_subagent_notifications["sub-1"] = [MagicMock()] * 500

        notification = MagicMock()
        await coord.async_handle_subagent_notification("sub-1", notification)

        # Should not exceed 500
        assert len(coord._buffered_subagent_notifications["sub-1"]) == 500


# ---- find_subagent_tool_card ----

class TestFindSubagentToolCard:
    def test_finds_card(self):
        coord, _ = make_coordinator()
        sa_card = MagicMock()
        sa_card._tool_cards = {"tc-inner": MagicMock()}
        coord._subagent_subscriptions["sub-1"] = {"card": sa_card}

        result = coord.find_subagent_tool_card("tc-inner")
        assert result is sa_card._tool_cards["tc-inner"]

    def test_returns_none_when_not_found(self):
        coord, _ = make_coordinator()
        assert coord.find_subagent_tool_card("tc-missing") is None


# ---- Cleanup ----

class TestCleanup:
    def test_cleanup_calls_unsubscribe(self):
        coord, _ = make_coordinator()
        unsub_reg = MagicMock()
        unsub_unreg = MagicMock()
        unsub_notif = MagicMock()
        coord._unsubscribe_registry_reg = unsub_reg
        coord._unsubscribe_registry_unreg = unsub_unreg
        coord._unsubscribe_registry_notif = unsub_notif

        coord.cleanup()
        unsub_reg.assert_called_once()
        unsub_unreg.assert_called_once()
        unsub_notif.assert_called_once()

    def test_cleanup_safe_with_no_subscriptions(self):
        coord, _ = make_coordinator()
        # Should not raise
        coord.cleanup()
