"""Tests for turn deletion feature (user-initiated context cleanup).

Coverage:
- MessageMeta.deleted field: serialization, deserialization, default behavior
- Message.should_include_in_context: deleted flag integration
- MessageStore.get_turn_uuids(): turn boundary detection across various scenarios
- MessageStore.delete_turn(): marking messages, notification emission
- MessageStore.restore_turn(): restoration, notification emission
- MessageStore LLM context: deleted messages excluded from get_llm_context()
- Hydration: turn_deleted/turn_restored events replayed via add_message()
- MemoryManager: delegation, persistence, empty-store guard
- Serializers: TURN_DELETED/TURN_RESTORED notification serialization,
  system message suppression

Total: 34 tests
"""

import json

import pytest

from src.memory.memory_manager import MemoryManager
from src.server.serializers import serialize_store_notification
from src.session.models import Message, MessageMeta, ToolCall, ToolCallFunction
from src.session.store import MessageStore, StoreEvent, StoreNotification


# =============================================================================
# Helpers
# =============================================================================


def _make_tool_call(tc_id: str = "tc_001", name: str = "read_file") -> ToolCall:
    """Create a minimal ToolCall for testing."""
    return ToolCall(
        id=tc_id,
        function=ToolCallFunction(name=name, arguments='{"path": "test.py"}'),
    )


def _build_simple_turn(store: MessageStore, session_id: str = "sess1"):
    """Build a simple turn: user -> assistant -> tool.

    Returns (user_msg, assistant_msg, tool_msg).
    """
    user_msg = Message.create_user("Fix the bug", session_id, None, store.next_seq())
    store.add_message(user_msg)

    tc = _make_tool_call("tc_001")
    assistant_msg = Message.create_assistant(
        "I will fix it", session_id, user_msg.uuid, store.next_seq(), tool_calls=[tc]
    )
    store.add_message(assistant_msg)

    tool_msg = Message.create_tool(
        "tc_001", "Done", session_id, assistant_msg.uuid, store.next_seq()
    )
    store.add_message(tool_msg)

    return user_msg, assistant_msg, tool_msg


def _capture_notifications(store: MessageStore) -> list[StoreNotification]:
    """Subscribe and return a list that accumulates notifications."""
    notifications: list[StoreNotification] = []
    store.subscribe(lambda n: notifications.append(n))
    return notifications


# =============================================================================
# 1. MessageMeta `deleted` field
# =============================================================================


class TestMessageMetaDeleted:
    """Tests for the MessageMeta.deleted field serialization and defaults."""

    def test_deleted_defaults_to_false(self):
        """MessageMeta.deleted defaults to False."""
        meta = MessageMeta()
        assert meta.deleted is False

    def test_deleted_true_serializes_to_dict(self):
        """When deleted=True, it appears in to_dict() output."""
        meta = MessageMeta(uuid="test-uuid", deleted=True)
        d = meta.to_dict()
        assert "deleted" in d
        assert d["deleted"] is True

    def test_deleted_false_not_in_dict(self):
        """When deleted=False (default), 'deleted' does NOT appear in to_dict().

        This keeps JSONL compact -- only serialize when the flag is actually set.
        """
        meta = MessageMeta(uuid="test-uuid", deleted=False)
        d = meta.to_dict()
        assert "deleted" not in d

    def test_from_dict_with_deleted_true(self):
        """from_dict with deleted: true sets the field."""
        meta = MessageMeta.from_dict({"uuid": "test-uuid", "deleted": True})
        assert meta.deleted is True

    def test_from_dict_without_deleted_defaults_false(self):
        """from_dict without 'deleted' key defaults to False."""
        meta = MessageMeta.from_dict({"uuid": "test-uuid"})
        assert meta.deleted is False

    def test_from_dict_with_deleted_false_explicit(self):
        """from_dict with explicit deleted: false."""
        meta = MessageMeta.from_dict({"uuid": "test-uuid", "deleted": False})
        assert meta.deleted is False


# =============================================================================
# 1b. Message.should_include_in_context with deleted flag
# =============================================================================


class TestShouldIncludeInContext:
    """Tests for Message.should_include_in_context with deleted flag."""

    def test_deleted_message_excluded_from_context(self):
        """A deleted message should NOT be included in LLM context."""
        msg = Message.create_user("Hello", "sess1", None, 1)
        msg.meta.deleted = True
        assert msg.should_include_in_context is False

    def test_non_deleted_message_included_in_context(self):
        """A normal (non-deleted) message should be included in LLM context."""
        msg = Message.create_user("Hello", "sess1", None, 1)
        assert msg.should_include_in_context is True

    def test_deleted_takes_precedence_over_include_in_llm_context(self):
        """deleted=True overrides include_in_llm_context=True."""
        msg = Message.create_user("Hello", "sess1", None, 1)
        msg.meta.deleted = True
        msg.meta.include_in_llm_context = True
        assert msg.should_include_in_context is False

    def test_deleted_assistant_excluded(self):
        """Deleted assistant messages are excluded."""
        msg = Message.create_assistant("Reply", "sess1", None, 1)
        msg.meta.deleted = True
        assert msg.should_include_in_context is False

    def test_deleted_tool_excluded(self):
        """Deleted tool messages are excluded."""
        msg = Message.create_tool("tc_001", "result", "sess1", None, 1)
        msg.meta.deleted = True
        assert msg.should_include_in_context is False


# =============================================================================
# 2. MessageStore.get_turn_uuids()
# =============================================================================


class TestGetTurnUuids:
    """Tests for MessageStore.get_turn_uuids() turn boundary detection."""

    def test_simple_turn(self):
        """Simple turn: user + assistant + tool."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        uuids = store.get_turn_uuids(user_msg.uuid)

        assert len(uuids) == 3
        assert uuids[0] == user_msg.uuid
        assert uuids[1] == assistant_msg.uuid
        assert uuids[2] == tool_msg.uuid

    def test_multi_iteration_turn(self):
        """Multi-iteration turn: user + assistant + tool + assistant + tool."""
        store = MessageStore()
        session_id = "sess1"

        user_msg = Message.create_user("Do something", session_id, None, store.next_seq())
        store.add_message(user_msg)

        # First iteration
        tc1 = _make_tool_call("tc_001", "read_file")
        asst1 = Message.create_assistant(
            "Reading file", session_id, user_msg.uuid, store.next_seq(), tool_calls=[tc1]
        )
        store.add_message(asst1)

        tool1 = Message.create_tool(
            "tc_001", "file contents", session_id, asst1.uuid, store.next_seq()
        )
        store.add_message(tool1)

        # Second iteration (same turn -- no user message in between)
        tc2 = _make_tool_call("tc_002", "write_file")
        asst2 = Message.create_assistant(
            "Writing file", session_id, tool1.uuid, store.next_seq(), tool_calls=[tc2]
        )
        store.add_message(asst2)

        tool2 = Message.create_tool(
            "tc_002", "written", session_id, asst2.uuid, store.next_seq()
        )
        store.add_message(tool2)

        uuids = store.get_turn_uuids(user_msg.uuid)

        assert len(uuids) == 5
        assert uuids[0] == user_msg.uuid
        assert uuids[1] == asst1.uuid
        assert uuids[2] == tool1.uuid
        assert uuids[3] == asst2.uuid
        assert uuids[4] == tool2.uuid

    def test_stops_at_next_user_message(self):
        """Turn stops at the next user message."""
        store = MessageStore()
        session_id = "sess1"

        user1 = Message.create_user("First question", session_id, None, store.next_seq())
        store.add_message(user1)

        asst1 = Message.create_assistant(
            "First answer", session_id, user1.uuid, store.next_seq()
        )
        store.add_message(asst1)

        user2 = Message.create_user("Second question", session_id, asst1.uuid, store.next_seq())
        store.add_message(user2)

        asst2 = Message.create_assistant(
            "Second answer", session_id, user2.uuid, store.next_seq()
        )
        store.add_message(asst2)

        # Turn 1: user1 + asst1 only
        uuids = store.get_turn_uuids(user1.uuid)
        assert len(uuids) == 2
        assert uuids[0] == user1.uuid
        assert uuids[1] == asst1.uuid

    def test_last_turn_includes_remaining_messages(self):
        """Last turn includes all remaining messages through end of conversation."""
        store = MessageStore()
        session_id = "sess1"

        user1 = Message.create_user("First", session_id, None, store.next_seq())
        store.add_message(user1)
        asst1 = Message.create_assistant("Reply 1", session_id, user1.uuid, store.next_seq())
        store.add_message(asst1)

        # Second turn (last)
        user2 = Message.create_user("Second", session_id, asst1.uuid, store.next_seq())
        store.add_message(user2)
        asst2 = Message.create_assistant("Reply 2", session_id, user2.uuid, store.next_seq())
        store.add_message(asst2)

        tc = _make_tool_call("tc_last")
        asst3 = Message.create_assistant(
            "More work", session_id, asst2.uuid, store.next_seq(), tool_calls=[tc]
        )
        store.add_message(asst3)

        tool_result = Message.create_tool(
            "tc_last", "done", session_id, asst3.uuid, store.next_seq()
        )
        store.add_message(tool_result)

        uuids = store.get_turn_uuids(user2.uuid)
        assert len(uuids) == 4
        assert uuids[0] == user2.uuid
        assert tool_result.uuid in uuids

    def test_skips_system_events_within_turn(self):
        """System events (e.g., compact_boundary) within a turn are skipped."""
        store = MessageStore()
        session_id = "sess1"

        user_msg = Message.create_user("Hello", session_id, None, store.next_seq())
        store.add_message(user_msg)

        # System event in the middle of the turn
        system_msg = Message.create_system(
            "[Turn duration: 5s]",
            session_id,
            store.next_seq(),
            event_type="turn_duration",
            include_in_llm_context=False,
        )
        store.add_message(system_msg)

        asst_msg = Message.create_assistant(
            "Response", session_id, user_msg.uuid, store.next_seq()
        )
        store.add_message(asst_msg)

        uuids = store.get_turn_uuids(user_msg.uuid)

        # System event should NOT be included
        assert system_msg.uuid not in uuids
        assert len(uuids) == 2
        assert uuids[0] == user_msg.uuid
        assert uuids[1] == asst_msg.uuid

    def test_compact_summary_not_treated_as_turn_boundary(self):
        """Compact summary (role=user, is_compact_summary=True) is NOT a turn boundary."""
        store = MessageStore()
        session_id = "sess1"

        user_msg = Message.create_user("Question", session_id, None, store.next_seq())
        store.add_message(user_msg)

        asst_msg = Message.create_assistant(
            "Answer", session_id, user_msg.uuid, store.next_seq()
        )
        store.add_message(asst_msg)

        # Compact summary is role=user but should NOT break the turn
        compact_summary = Message.create_user(
            "[Conversation summary]",
            session_id,
            None,
            store.next_seq(),
            is_compact_summary=True,
        )
        store.add_message(compact_summary)

        # More assistant work after compaction
        asst_msg2 = Message.create_assistant(
            "Continuing", session_id, compact_summary.uuid, store.next_seq()
        )
        store.add_message(asst_msg2)

        uuids = store.get_turn_uuids(user_msg.uuid)

        # The turn should continue past the compact summary
        assert asst_msg.uuid in uuids
        assert asst_msg2.uuid in uuids

    def test_raises_for_nonexistent_uuid(self):
        """Raises ValueError for UUID not found in store."""
        store = MessageStore()
        with pytest.raises(ValueError, match="Message not found"):
            store.get_turn_uuids("nonexistent-uuid-12345")

    def test_raises_for_non_user_message(self):
        """Raises ValueError for non-user message UUID."""
        store = MessageStore()
        asst_msg = Message.create_assistant("Reply", "sess1", None, store.next_seq())
        store.add_message(asst_msg)

        with pytest.raises(ValueError, match="Not a user message"):
            store.get_turn_uuids(asst_msg.uuid)


# =============================================================================
# 3. MessageStore.delete_turn() and restore_turn()
# =============================================================================


class TestDeleteTurn:
    """Tests for MessageStore.delete_turn()."""

    def test_marks_all_turn_messages_as_deleted(self):
        """delete_turn marks every message in the turn as deleted."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        store.delete_turn(user_msg.uuid)

        assert user_msg.meta.deleted is True
        assert assistant_msg.meta.deleted is True
        assert tool_msg.meta.deleted is True

    def test_emits_turn_deleted_notification(self):
        """delete_turn emits a TURN_DELETED notification with correct metadata."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        notifications = _capture_notifications(store)
        store.delete_turn(user_msg.uuid)

        # Find the TURN_DELETED notification
        turn_deleted_notifs = [
            n for n in notifications if n.event == StoreEvent.TURN_DELETED
        ]
        assert len(turn_deleted_notifs) == 1

        notif = turn_deleted_notifs[0]
        assert notif.metadata["turn_anchor_uuid"] == user_msg.uuid
        assert notif.metadata["count"] == 3
        assert set(notif.metadata["affected_uuids"]) == {
            user_msg.uuid,
            assistant_msg.uuid,
            tool_msg.uuid,
        }

    def test_notification_includes_preview(self):
        """TURN_DELETED notification includes a content preview from the user message."""
        store = MessageStore()
        user_msg = Message.create_user(
            "Fix the critical authentication bug in login.py", "sess1", None, store.next_seq()
        )
        store.add_message(user_msg)
        asst_msg = Message.create_assistant(
            "On it", "sess1", user_msg.uuid, store.next_seq()
        )
        store.add_message(asst_msg)

        notifications = _capture_notifications(store)
        store.delete_turn(user_msg.uuid)

        notif = [n for n in notifications if n.event == StoreEvent.TURN_DELETED][0]
        assert "Fix the critical authentication bug" in notif.metadata["preview"]

    def test_long_preview_truncated(self):
        """Preview is truncated to 80 characters with ellipsis for long messages."""
        store = MessageStore()
        long_content = "A" * 200
        user_msg = Message.create_user(long_content, "sess1", None, store.next_seq())
        store.add_message(user_msg)
        asst_msg = Message.create_assistant(
            "Ok", "sess1", user_msg.uuid, store.next_seq()
        )
        store.add_message(asst_msg)

        notifications = _capture_notifications(store)
        store.delete_turn(user_msg.uuid)

        notif = [n for n in notifications if n.event == StoreEvent.TURN_DELETED][0]
        preview = notif.metadata["preview"]
        assert len(preview) == 83  # 80 chars + "..."
        assert preview.endswith("...")

    def test_deleted_messages_excluded_from_llm_context(self):
        """Deleted messages are excluded from get_llm_context()."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        # Verify messages are in context before deletion
        context_before = store.get_llm_context()
        assert len(context_before) == 3

        store.delete_turn(user_msg.uuid)

        context_after = store.get_llm_context()
        assert len(context_after) == 0

    def test_returns_affected_uuids(self):
        """delete_turn returns the list of affected UUIDs."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        result = store.delete_turn(user_msg.uuid)

        assert len(result) == 3
        assert user_msg.uuid in result
        assert assistant_msg.uuid in result
        assert tool_msg.uuid in result


class TestRestoreTurn:
    """Tests for MessageStore.restore_turn()."""

    def test_restores_deleted_messages(self):
        """restore_turn marks messages as not-deleted."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        store.delete_turn(user_msg.uuid)
        assert user_msg.meta.deleted is True

        store.restore_turn(user_msg.uuid)

        assert user_msg.meta.deleted is False
        assert assistant_msg.meta.deleted is False
        assert tool_msg.meta.deleted is False

    def test_emits_turn_restored_notification(self):
        """restore_turn emits a TURN_RESTORED notification."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        store.delete_turn(user_msg.uuid)

        notifications = _capture_notifications(store)
        store.restore_turn(user_msg.uuid)

        turn_restored_notifs = [
            n for n in notifications if n.event == StoreEvent.TURN_RESTORED
        ]
        assert len(turn_restored_notifs) == 1

        notif = turn_restored_notifs[0]
        assert notif.metadata["turn_anchor_uuid"] == user_msg.uuid
        assert notif.metadata["count"] == 3

    def test_restored_messages_back_in_llm_context(self):
        """Restored messages re-appear in get_llm_context()."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        store.delete_turn(user_msg.uuid)
        assert len(store.get_llm_context()) == 0

        store.restore_turn(user_msg.uuid)
        context = store.get_llm_context()
        assert len(context) == 3

    def test_delete_restore_delete_last_wins(self):
        """delete -> restore -> delete: last event wins (messages end up deleted)."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        store.delete_turn(user_msg.uuid)
        assert user_msg.meta.deleted is True

        store.restore_turn(user_msg.uuid)
        assert user_msg.meta.deleted is False

        store.delete_turn(user_msg.uuid)
        assert user_msg.meta.deleted is True
        assert len(store.get_llm_context()) == 0

    def test_restore_returns_affected_uuids(self):
        """restore_turn returns the list of affected UUIDs."""
        store = MessageStore()
        user_msg, assistant_msg, tool_msg = _build_simple_turn(store)

        store.delete_turn(user_msg.uuid)
        result = store.restore_turn(user_msg.uuid)

        assert len(result) == 3
        assert user_msg.uuid in result


# =============================================================================
# 4. Hydration: turn_deleted/turn_restored events replayed via add_message()
# =============================================================================


class TestTurnDeletionHydration:
    """Tests for turn deletion/restoration hydration during session replay."""

    def test_turn_deleted_event_marks_messages(self):
        """A turn_deleted system event in add_message() marks affected messages."""
        store = MessageStore()
        session_id = "sess1"

        user_msg, assistant_msg, tool_msg = _build_simple_turn(store, session_id)

        # Simulate replaying a turn_deleted event (as would happen during session hydration)
        deletion_event = Message.create_system(
            content="[Turn deleted by user]",
            session_id=session_id,
            seq=store.next_seq(),
            event_type="turn_deleted",
            include_in_llm_context=False,
            extra={
                "turn_anchor_uuid": user_msg.uuid,
                "affected_uuids": [user_msg.uuid, assistant_msg.uuid, tool_msg.uuid],
            },
        )
        store.add_message(deletion_event)

        # Messages should now be marked as deleted
        assert user_msg.meta.deleted is True
        assert assistant_msg.meta.deleted is True
        assert tool_msg.meta.deleted is True

    def test_turn_restored_event_clears_deletion(self):
        """A turn_restored event after turn_deleted reverses the deletion."""
        store = MessageStore()
        session_id = "sess1"

        user_msg, assistant_msg, tool_msg = _build_simple_turn(store, session_id)
        affected = [user_msg.uuid, assistant_msg.uuid, tool_msg.uuid]

        # Replay turn_deleted
        del_event = Message.create_system(
            content="[Turn deleted by user]",
            session_id=session_id,
            seq=store.next_seq(),
            event_type="turn_deleted",
            include_in_llm_context=False,
            extra={"turn_anchor_uuid": user_msg.uuid, "affected_uuids": affected},
        )
        store.add_message(del_event)
        assert user_msg.meta.deleted is True

        # Replay turn_restored
        restore_event = Message.create_system(
            content="[Turn restored by user]",
            session_id=session_id,
            seq=store.next_seq(),
            event_type="turn_restored",
            include_in_llm_context=False,
            extra={"turn_anchor_uuid": user_msg.uuid, "affected_uuids": affected},
        )
        store.add_message(restore_event)

        # Messages should be restored
        assert user_msg.meta.deleted is False
        assert assistant_msg.meta.deleted is False
        assert tool_msg.meta.deleted is False

    def test_hydration_last_event_wins(self):
        """Multiple delete/restore events during hydration: last event wins."""
        store = MessageStore()
        session_id = "sess1"

        user_msg, assistant_msg, tool_msg = _build_simple_turn(store, session_id)
        affected = [user_msg.uuid, assistant_msg.uuid, tool_msg.uuid]

        # delete -> restore -> delete
        for event_type in ("turn_deleted", "turn_restored", "turn_deleted"):
            evt = Message.create_system(
                content=f"[Turn {event_type.replace('turn_', '')} by user]",
                session_id=session_id,
                seq=store.next_seq(),
                event_type=event_type,
                include_in_llm_context=False,
                extra={"turn_anchor_uuid": user_msg.uuid, "affected_uuids": affected},
            )
            store.add_message(evt)

        # Last event was turn_deleted, so messages should be deleted
        assert user_msg.meta.deleted is True
        assert assistant_msg.meta.deleted is True

    def test_hydration_skips_missing_uuids(self):
        """Hydration gracefully skips affected UUIDs not found in the store."""
        store = MessageStore()
        session_id = "sess1"

        user_msg = Message.create_user("Hello", session_id, None, store.next_seq())
        store.add_message(user_msg)

        # Affected list includes a UUID not in the store (e.g., message was purged)
        del_event = Message.create_system(
            content="[Turn deleted by user]",
            session_id=session_id,
            seq=store.next_seq(),
            event_type="turn_deleted",
            include_in_llm_context=False,
            extra={
                "turn_anchor_uuid": user_msg.uuid,
                "affected_uuids": [user_msg.uuid, "nonexistent-uuid-12345"],
            },
        )
        # Should not raise
        store.add_message(del_event)
        assert user_msg.meta.deleted is True


# =============================================================================
# 5. MemoryManager integration
# =============================================================================


class TestMemoryManagerTurnDeletion:
    """Tests for MemoryManager.delete_turn() and restore_turn()."""

    def _make_manager_with_store(self) -> tuple[MemoryManager, MessageStore]:
        """Create a MemoryManager with a MessageStore configured."""
        manager = MemoryManager(load_file_memories=False)
        store = MessageStore()
        session_id = "sess-mgr-test"
        manager.set_message_store(store, session_id)
        return manager, store

    def test_delete_turn_delegates_to_store(self):
        """MemoryManager.delete_turn() delegates to MessageStore.delete_turn()."""
        manager, store = self._make_manager_with_store()

        user_msg, asst_msg, tool_msg = _build_simple_turn(store, "sess-mgr-test")

        affected = manager.delete_turn(user_msg.uuid)

        assert len(affected) == 3
        assert user_msg.meta.deleted is True

    def test_delete_turn_persists_system_event(self):
        """MemoryManager.delete_turn() persists a turn_deleted system event."""
        manager, store = self._make_manager_with_store()

        user_msg, asst_msg, tool_msg = _build_simple_turn(store, "sess-mgr-test")

        notifications = _capture_notifications(store)
        manager.delete_turn(user_msg.uuid)

        # Should have: TURN_DELETED (from store.delete_turn) + MESSAGE_ADDED (system event)
        added_notifs = [n for n in notifications if n.event == StoreEvent.MESSAGE_ADDED]
        system_events = [
            n
            for n in added_notifs
            if n.message and n.message.meta.event_type == "turn_deleted"
        ]
        assert len(system_events) == 1

        sys_msg = system_events[0].message
        assert sys_msg.meta.extra["turn_anchor_uuid"] == user_msg.uuid
        assert set(sys_msg.meta.extra["affected_uuids"]) == {
            user_msg.uuid,
            asst_msg.uuid,
            tool_msg.uuid,
        }

    def test_restore_turn_delegates_to_store(self):
        """MemoryManager.restore_turn() delegates to MessageStore.restore_turn()."""
        manager, store = self._make_manager_with_store()

        user_msg, asst_msg, tool_msg = _build_simple_turn(store, "sess-mgr-test")

        manager.delete_turn(user_msg.uuid)
        affected = manager.restore_turn(user_msg.uuid)

        assert len(affected) == 3
        assert user_msg.meta.deleted is False

    def test_restore_turn_persists_system_event(self):
        """MemoryManager.restore_turn() persists a turn_restored system event."""
        manager, store = self._make_manager_with_store()

        user_msg, asst_msg, tool_msg = _build_simple_turn(store, "sess-mgr-test")

        manager.delete_turn(user_msg.uuid)

        notifications = _capture_notifications(store)
        manager.restore_turn(user_msg.uuid)

        added_notifs = [n for n in notifications if n.event == StoreEvent.MESSAGE_ADDED]
        system_events = [
            n
            for n in added_notifs
            if n.message and n.message.meta.event_type == "turn_restored"
        ]
        assert len(system_events) == 1

    def test_delete_turn_returns_empty_without_store(self):
        """MemoryManager.delete_turn() returns [] when no MessageStore is set."""
        manager = MemoryManager(load_file_memories=False)
        # Do NOT call set_message_store
        result = manager.delete_turn("some-uuid")
        assert result == []

    def test_restore_turn_returns_empty_without_store(self):
        """MemoryManager.restore_turn() returns [] when no MessageStore is set."""
        manager = MemoryManager(load_file_memories=False)
        result = manager.restore_turn("some-uuid")
        assert result == []


# =============================================================================
# 6. Serializers
# =============================================================================


class TestTurnDeletionSerializers:
    """Tests for TURN_DELETED/TURN_RESTORED notification serialization."""

    def test_turn_deleted_serializes_correctly(self):
        """TURN_DELETED notification serializes to the expected wire format."""
        notification = StoreNotification(
            event=StoreEvent.TURN_DELETED,
            metadata={
                "turn_anchor_uuid": "uuid-user-123",
                "affected_uuids": ["uuid-user-123", "uuid-asst-456", "uuid-tool-789"],
                "count": 3,
                "preview": "Fix the bug in login...",
            },
        )

        result = serialize_store_notification(notification)

        assert result is not None
        assert result["type"] == "store"
        assert result["event"] == "turn_deleted"
        assert result["data"]["anchor_uuid"] == "uuid-user-123"
        assert len(result["data"]["affected_uuids"]) == 3
        assert result["data"]["count"] == 3
        assert result["data"]["preview"] == "Fix the bug in login..."

    def test_turn_restored_serializes_correctly(self):
        """TURN_RESTORED notification serializes to the expected wire format."""
        notification = StoreNotification(
            event=StoreEvent.TURN_RESTORED,
            metadata={
                "turn_anchor_uuid": "uuid-user-123",
                "affected_uuids": ["uuid-user-123", "uuid-asst-456"],
                "count": 2,
            },
        )

        result = serialize_store_notification(notification)

        assert result is not None
        assert result["type"] == "store"
        assert result["event"] == "turn_restored"
        assert result["data"]["anchor_uuid"] == "uuid-user-123"
        assert len(result["data"]["affected_uuids"]) == 2
        assert result["data"]["count"] == 2

    def test_turn_deleted_system_message_suppressed(self):
        """turn_deleted system message (MESSAGE_ADDED) returns None (suppressed)."""
        sys_msg = Message.create_system(
            content="[Turn deleted by user]",
            session_id="sess1",
            seq=1,
            event_type="turn_deleted",
            include_in_llm_context=False,
        )

        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=sys_msg,
        )

        result = serialize_store_notification(notification)
        assert result is None

    def test_turn_restored_system_message_suppressed(self):
        """turn_restored system message (MESSAGE_ADDED) returns None (suppressed)."""
        sys_msg = Message.create_system(
            content="[Turn restored by user]",
            session_id="sess1",
            seq=1,
            event_type="turn_restored",
            include_in_llm_context=False,
        )

        notification = StoreNotification(
            event=StoreEvent.MESSAGE_ADDED,
            message=sys_msg,
        )

        result = serialize_store_notification(notification)
        assert result is None
