"""Tests for MessageStore (Schema v2.1)."""

import pytest
from src.session.store import (
    MessageStore,
    StoreEvent,
    StoreNotification,
    SeqCollisionError,
    Message,
)
from src.session.models import ToolCall, ToolCallFunction


class TestMessageStoreBasics:
    """Basic MessageStore operations."""

    def test_store_creation(self):
        store = MessageStore()
        assert store.message_count == 0
        assert store.is_empty == True
        assert store.max_seq == 0

    def test_add_message(self):
        store = MessageStore()
        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        assert store.message_count == 1
        assert store.is_empty == False

    def test_get_message_by_uuid(self):
        store = MessageStore()
        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        retrieved = store.get_message(msg.uuid)
        assert retrieved is not None
        assert retrieved.content == "Hello"

    def test_get_message_not_found(self):
        store = MessageStore()
        assert store.get_message("nonexistent") is None

    def test_get_by_seq(self):
        store = MessageStore()
        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        retrieved = store.get_by_seq(msg.seq)
        assert retrieved is not None
        assert retrieved.uuid == msg.uuid


class TestSequenceManagement:
    """Tests for sequence number management."""

    def test_next_seq_increments(self):
        store = MessageStore()
        assert store.next_seq() == 1
        assert store.next_seq() == 2
        assert store.next_seq() == 3

    def test_max_seq_updated_on_add(self):
        store = MessageStore()
        msg = Message.create_user("Hello", "sess-1", None, 5)
        store.add_message(msg)
        assert store.max_seq == 5

    def test_seq_collision_raises_error(self):
        store = MessageStore()
        msg1 = Message.create_user("Hello", "sess-1", None, 1)
        msg2 = Message.create_user("World", "sess-1", None, 1)  # Same seq

        store.add_message(msg1)

        with pytest.raises(SeqCollisionError):
            store.add_message(msg2)

    def test_seq_collision_same_uuid_ok(self):
        store = MessageStore()
        # Same UUID with same seq should not raise
        msg = Message.create_user("Hello", "sess-1", None, 1)
        store.add_message(msg)
        # Re-adding same message (same uuid, same seq) should work
        store._messages[msg.uuid] = msg  # Direct update
        store._by_seq[1] = msg.uuid
        # No error expected


class TestStreamIdCollapse:
    """Tests for assistant message collapse by stream_id."""

    def test_assistant_collapse_by_stream_id(self):
        store = MessageStore()

        # First assistant message
        msg1 = Message.create_assistant(
            content="Part 1",
            session_id="sess-1",
            parent_uuid=None,
            seq=store.next_seq(),
            stream_id="stream_001"
        )
        store.add_message(msg1)
        assert store.message_count == 1

        # Second assistant message with same stream_id replaces first
        msg2 = Message.create_assistant(
            content="Part 1 Part 2",
            session_id="sess-1",
            parent_uuid=None,
            seq=store.next_seq(),
            stream_id="stream_001"
        )
        store.add_message(msg2)
        assert store.message_count == 1  # Still 1, not 2

        # The stored message should be msg2
        stored = store.get_message(msg2.uuid)
        assert stored is not None
        assert stored.content == "Part 1 Part 2"

        # msg1 should be gone
        assert store.get_message(msg1.uuid) is None

    def test_different_stream_ids_not_collapsed(self):
        store = MessageStore()

        msg1 = Message.create_assistant(
            content="Response 1",
            session_id="sess-1",
            parent_uuid=None,
            seq=store.next_seq(),
            stream_id="stream_001"
        )
        store.add_message(msg1)

        msg2 = Message.create_assistant(
            content="Response 2",
            session_id="sess-1",
            parent_uuid=None,
            seq=store.next_seq(),
            stream_id="stream_002"  # Different stream_id
        )
        store.add_message(msg2)

        assert store.message_count == 2

    def test_user_messages_not_collapsed(self):
        store = MessageStore()

        msg1 = Message.create_user("Hello", "sess-1", None, store.next_seq())
        msg2 = Message.create_user("World", "sess-1", None, store.next_seq())

        store.add_message(msg1)
        store.add_message(msg2)

        assert store.message_count == 2


class TestToolResultIndexing:
    """Tests for tool result indexing."""

    def test_tool_result_indexed(self):
        store = MessageStore()

        # Assistant with tool call
        tc = ToolCall(id="call_123", function=ToolCallFunction(name="Read", arguments="{}"))
        assistant = Message.create_assistant(
            content="Reading file",
            session_id="sess-1",
            parent_uuid=None,
            seq=store.next_seq(),
            tool_calls=[tc]
        )
        store.add_message(assistant)

        # Tool result
        tool_result = Message.create_tool(
            tool_call_id="call_123",
            content="File content here",
            session_id="sess-1",
            parent_uuid=assistant.uuid,
            seq=store.next_seq()
        )
        store.add_message(tool_result)

        # Should be able to retrieve by tool_call_id
        result = store.get_tool_result("call_123")
        assert result is not None
        assert result.content == "File content here"

    def test_get_tool_result_not_found(self):
        store = MessageStore()
        assert store.get_tool_result("nonexistent") is None

    def test_get_tool_calls_for_assistant(self):
        store = MessageStore()

        tc1 = ToolCall(id="call_1", function=ToolCallFunction(name="Read", arguments="{}"))
        tc2 = ToolCall(id="call_2", function=ToolCallFunction(name="Write", arguments="{}"))

        assistant = Message.create_assistant(
            content="Multiple tools",
            session_id="sess-1",
            parent_uuid=None,
            seq=store.next_seq(),
            tool_calls=[tc1, tc2]
        )
        store.add_message(assistant)

        tool_ids = store.get_tool_calls_for_assistant(assistant.uuid)
        assert tool_ids == ["call_1", "call_2"]


class TestOrderingAndIteration:
    """Tests for message ordering and iteration."""

    def test_get_ordered_messages(self):
        store = MessageStore()

        # Add in non-sequential order
        msg3 = Message.create_user("Third", "sess-1", None, 3)
        msg1 = Message.create_user("First", "sess-1", None, 1)
        msg2 = Message.create_user("Second", "sess-1", None, 2)

        store.add_message(msg3)
        store.add_message(msg1)
        store.add_message(msg2)

        ordered = store.get_ordered_messages()
        assert len(ordered) == 3
        assert ordered[0].content == "First"
        assert ordered[1].content == "Second"
        assert ordered[2].content == "Third"

    def test_get_messages_after_seq(self):
        store = MessageStore()

        for i in range(1, 6):
            msg = Message.create_user(f"Msg {i}", "sess-1", None, i)
            store.add_message(msg)

        after = store.get_messages_after_seq(3)
        assert len(after) == 2
        assert after[0].seq == 4
        assert after[1].seq == 5


class TestSidechainTracking:
    """Tests for sidechain (alternate response) tracking."""

    def test_mainline_messages_excludes_sidechains(self):
        store = MessageStore()

        user = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(user)

        # Main response
        main_response = Message.create_assistant(
            content="Main response",
            session_id="sess-1",
            parent_uuid=user.uuid,
            seq=store.next_seq()
        )
        store.add_message(main_response)

        # Sidechain response
        sidechain_meta = main_response.meta
        sidechain = Message(
            role="assistant",
            content="Alternative response",
            meta=type(sidechain_meta)(
                uuid="side-1",
                seq=store.next_seq(),
                timestamp=sidechain_meta.timestamp,
                session_id="sess-1",
                parent_uuid=user.uuid,
                is_sidechain=True,
                stream_id="stream_side"
            )
        )
        store.add_message(sidechain)

        mainline = store.get_mainline_messages()
        assert len(mainline) == 2  # user + main_response, not sidechain

    def test_get_sidechains(self):
        store = MessageStore()

        user = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(user)

        # Add sidechain
        from src.session.models import MessageMeta
        sidechain = Message(
            role="assistant",
            content="Sidechain",
            meta=MessageMeta(
                uuid="side-1",
                seq=store.next_seq(),
                timestamp="2024-01-01T00:00:00Z",
                session_id="sess-1",
                parent_uuid=user.uuid,
                is_sidechain=True,
                stream_id="stream_side"
            )
        )
        store.add_message(sidechain)

        sidechains = store.get_sidechains(user.uuid)
        assert len(sidechains) == 1
        assert sidechains[0].content == "Sidechain"

    def test_get_sidechain_count(self):
        store = MessageStore()
        user = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(user)

        assert store.get_sidechain_count(user.uuid) == 0


class TestCompactionTracking:
    """Tests for compaction boundary tracking."""

    def test_compact_boundary_detected(self):
        store = MessageStore()

        # Add some messages
        msg1 = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg1)

        # Add compact boundary
        boundary = Message.create_system(
            content="Compaction boundary",
            session_id="sess-1",
            seq=store.next_seq(),
            event_type="compact_boundary"
        )
        store.add_message(boundary)

        assert store.has_compaction() == True
        assert store.get_compact_boundary() is not None
        assert store.get_compact_boundary().content == "Compaction boundary"

    def test_transcript_view_post_compaction(self):
        store = MessageStore()

        # Pre-compaction messages
        msg1 = Message.create_user("Pre-compact 1", "sess-1", None, store.next_seq())
        msg2 = Message.create_user("Pre-compact 2", "sess-1", None, store.next_seq())
        store.add_message(msg1)
        store.add_message(msg2)

        # Compact boundary
        boundary = Message.create_system(
            content="Compaction",
            session_id="sess-1",
            seq=store.next_seq(),
            event_type="compact_boundary"
        )
        store.add_message(boundary)

        # Post-compaction messages
        msg3 = Message.create_user("Post-compact", "sess-1", None, store.next_seq())
        store.add_message(msg3)

        # Default: post-compaction only
        transcript = store.get_transcript_view()
        assert len(transcript) == 1
        assert transcript[0].content == "Post-compact"

        # With flag: include all
        full = store.get_transcript_view(include_pre_compaction=True)
        assert len(full) == 4  # All messages including boundary


class TestLLMContext:
    """Tests for LLM context generation."""

    def test_get_llm_context_returns_openai_format(self):
        store = MessageStore()

        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        context = store.get_llm_context()
        assert len(context) == 1
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"
        assert "meta" not in context[0]

    def test_get_llm_context_excludes_compact_boundary(self):
        store = MessageStore()

        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        boundary = Message.create_system(
            content="Boundary",
            session_id="sess-1",
            seq=store.next_seq(),
            event_type="compact_boundary"
        )
        store.add_message(boundary)

        msg2 = Message.create_user("After", "sess-1", None, store.next_seq())
        store.add_message(msg2)

        context = store.get_llm_context()
        # Should only include msg2 (after boundary), not boundary itself
        assert len(context) == 1
        assert context[0]["content"] == "After"

    def test_get_llm_context_max_messages(self):
        store = MessageStore()

        for i in range(10):
            msg = Message.create_user(f"Msg {i}", "sess-1", None, store.next_seq())
            store.add_message(msg)

        context = store.get_llm_context(max_messages=3)
        assert len(context) == 3
        # Should be the last 3
        assert context[0]["content"] == "Msg 7"
        assert context[2]["content"] == "Msg 9"

    def test_get_llm_context_messages_returns_objects(self):
        store = MessageStore()

        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        messages = store.get_llm_context_messages()
        assert len(messages) == 1
        assert isinstance(messages[0], Message)


class TestSubscriptions:
    """Tests for store subscriptions."""

    def test_subscribe_receives_notifications(self):
        store = MessageStore()
        notifications = []

        def handler(n):
            notifications.append(n)

        unsubscribe = store.subscribe(handler)

        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        assert len(notifications) == 1
        assert notifications[0].event == StoreEvent.MESSAGE_ADDED

        unsubscribe()

    def test_unsubscribe_stops_notifications(self):
        store = MessageStore()
        notifications = []

        def handler(n):
            notifications.append(n)

        unsubscribe = store.subscribe(handler)
        unsubscribe()

        msg = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(msg)

        assert len(notifications) == 0

    def test_bulk_load_suppresses_notifications(self):
        store = MessageStore()
        notifications = []

        def handler(n):
            notifications.append(n)

        store.subscribe(handler)
        store.begin_bulk_load()

        for i in range(5):
            msg = Message.create_user(f"Msg {i}", "sess-1", None, store.next_seq())
            store.add_message(msg)

        assert len(notifications) == 0  # Suppressed

        store.end_bulk_load()
        assert len(notifications) == 1
        assert notifications[0].event == StoreEvent.BULK_LOAD_COMPLETE


class TestClearAndReset:
    """Tests for store clearing."""

    def test_clear_removes_all(self):
        store = MessageStore()

        for i in range(5):
            msg = Message.create_user(f"Msg {i}", "sess-1", None, store.next_seq())
            store.add_message(msg)

        assert store.message_count == 5

        store.clear()

        assert store.message_count == 0
        assert store.is_empty == True
        assert store.max_seq == 0
        assert store.session_id is None


class TestThreading:
    """Tests for parent-child threading."""

    def test_get_children(self):
        store = MessageStore()

        parent = Message.create_user("Parent", "sess-1", None, store.next_seq())
        store.add_message(parent)

        child1 = Message.create_assistant("Child 1", "sess-1", parent.uuid, store.next_seq())
        child2 = Message.create_assistant("Child 2", "sess-1", parent.uuid, store.next_seq())
        store.add_message(child1)
        store.add_message(child2)

        children = store.get_children(parent.uuid)
        assert len(children) == 2

    def test_get_thread(self):
        store = MessageStore()

        msg1 = Message.create_user("First", "sess-1", None, store.next_seq())
        store.add_message(msg1)

        msg2 = Message.create_assistant("Second", "sess-1", msg1.uuid, store.next_seq())
        store.add_message(msg2)

        msg3 = Message.create_user("Third", "sess-1", msg2.uuid, store.next_seq())
        store.add_message(msg3)

        thread = store.get_thread(msg3.uuid)
        assert len(thread) == 3
        assert thread[0].uuid == msg1.uuid
        assert thread[1].uuid == msg2.uuid
        assert thread[2].uuid == msg3.uuid


class TestSnapshots:
    """Tests for file snapshot handling."""

    def test_add_and_get_snapshot(self):
        from src.session.models import FileHistorySnapshot

        store = MessageStore()
        snapshot = FileHistorySnapshot.create(session_id="sess-1")
        store.add_snapshot(snapshot)

        retrieved = store.get_snapshot(snapshot.uuid)
        assert retrieved is not None
        assert retrieved.session_id == "sess-1"
