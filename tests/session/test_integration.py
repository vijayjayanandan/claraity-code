"""Integration tests for session persistence (Schema v2.1).

Tests end-to-end workflows:
- Message lifecycle (create -> persist -> resume)
- Provider translation roundtrips
- Streaming message collapse
- Store + Writer + Parser integration
"""

import pytest
import asyncio
import json
import tempfile
from pathlib import Path

from src.session.models import (
    Message,
    MessageMeta,
    ToolCall,
    ToolCallFunction,
    FileHistorySnapshot,
)
from src.session.store import MessageStore
from src.session.persistence import (
    parse_line,
    load_session,
    SessionWriter,
    create_session_file,
    append_to_session,
)
from src.session.providers import (
    from_openai,
    to_openai,
    from_anthropic,
    to_anthropic,
)
from src.session.manager import SessionManager


class TestMessageLifecycle:
    """End-to-end tests for message lifecycle."""

    @pytest.mark.asyncio
    async def test_create_persist_resume_verify(self):
        """Test full lifecycle: create message, persist, resume, verify."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "lifecycle.jsonl"

            # Create and persist
            writer = SessionWriter(file_path)
            await writer.open()

            msg = Message.create_user("Hello world!", "sess-1", None, 1)
            await writer.write_message(msg)
            await writer.close()

            # Resume and verify
            store = load_session(file_path)
            assert store.message_count == 1

            loaded = store.get_message(msg.uuid)
            assert loaded.content == "Hello world!"
            assert loaded.role == "user"
            assert loaded.seq == 1

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        """Test persisting and resuming a multi-turn conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "conversation.jsonl"

            # Create conversation
            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            # User message
            user_msg = Message.create_user("What is 2+2?", "sess-1", None, store.next_seq())
            store.add_message(user_msg)

            # Assistant response
            assistant_msg = Message.create_assistant(
                "2+2 equals 4.", "sess-1", user_msg.uuid, store.next_seq()
            )
            store.add_message(assistant_msg)

            # Tool call
            tc = ToolCall(
                id="call_calc",
                function=ToolCallFunction(name="Calculator", arguments='{"expr": "2+2"}')
            )
            tool_call_msg = Message.create_assistant(
                "Let me calculate that.", "sess-1", assistant_msg.uuid, store.next_seq(),
                tool_calls=[tc]
            )
            store.add_message(tool_call_msg)

            # Tool result
            tool_result = Message.create_tool(
                tool_call_id="call_calc",
                content="4",
                session_id="sess-1",
                parent_uuid=tool_call_msg.uuid,
                seq=store.next_seq(),
                status="success"
            )
            store.add_message(tool_result)

            # Wait for writes
            await asyncio.sleep(0.2)
            await writer.close()

            # Resume and verify
            resumed_store = load_session(file_path)
            assert resumed_store.message_count == 4

            # Verify order
            messages = resumed_store.get_ordered_messages()
            assert messages[0].role == "user"
            assert messages[1].role == "assistant"
            assert messages[2].has_tool_calls()
            assert messages[3].role == "tool"


class TestProviderRoundtrip:
    """Tests for provider translation roundtrips."""

    @pytest.mark.asyncio
    async def test_openai_roundtrip(self):
        """Test OpenAI response -> Message -> persist -> reload -> to_openai."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "openai_roundtrip.jsonl"

            # Simulate OpenAI response
            openai_response = {
                "id": "chatcmpl-test",
                "model": "gpt-4",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Hello from OpenAI!",
                        "tool_calls": [{
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "Read",
                                "arguments": '{"file_path": "test.py"}'
                            }
                        }]
                    },
                    "finish_reason": "tool_calls"
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}
            }

            # Convert to Message
            msg = from_openai(openai_response, "sess-1", None, 1)

            # Persist
            await append_to_session(file_path, msg)

            # Reload
            store = load_session(file_path)
            loaded = store.get_ordered_messages()[0]

            # Convert back to OpenAI format
            openai_msgs = to_openai([loaded])

            assert len(openai_msgs) == 1
            assert openai_msgs[0]["role"] == "assistant"
            assert openai_msgs[0]["content"] == "Hello from OpenAI!"
            assert len(openai_msgs[0]["tool_calls"]) == 1

    @pytest.mark.asyncio
    async def test_anthropic_roundtrip(self):
        """Test Anthropic response -> Message -> persist -> reload -> to_anthropic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "anthropic_roundtrip.jsonl"

            # Simulate Anthropic response with thinking
            anthropic_response = {
                "id": "msg_test",
                "model": "claude-3-opus",
                "content": [
                    {"type": "thinking", "thinking": "Let me consider this..."},
                    {"type": "text", "text": "The answer is 42."},
                    {
                        "type": "tool_use",
                        "id": "tool_calc",
                        "name": "Calculator",
                        "input": {"expr": "6*7"}
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 100, "output_tokens": 50}
            }

            # Convert to Message
            msg = from_anthropic(anthropic_response, "sess-1", None, 1)

            # Verify thinking preserved
            assert msg.meta.thinking == "Let me consider this..."
            assert msg.content == "The answer is 42."

            # Persist
            await append_to_session(file_path, msg)

            # Reload
            store = load_session(file_path)
            loaded = store.get_ordered_messages()[0]

            # Verify thinking survived roundtrip
            assert loaded.meta.thinking == "Let me consider this..."

            # Convert back to Anthropic format
            anthropic_msgs = to_anthropic([loaded])

            assert len(anthropic_msgs) == 1
            content_blocks = anthropic_msgs[0]["content"]
            assert content_blocks[0]["type"] == "thinking"
            assert content_blocks[1]["type"] == "text"
            assert content_blocks[2]["type"] == "tool_use"


class TestStreamingCollapse:
    """Tests for streaming message collapse."""

    @pytest.mark.asyncio
    async def test_streaming_collapse_by_stream_id(self):
        """Test that assistant messages with same stream_id are collapsed.

        Architecture note: With boundary-only persistence:
        - Store collapses streaming updates (multiple adds with same stream_id -> 1 message)
        - SessionWriter only persists MESSAGE_ADDED and MESSAGE_FINALIZED
        - MESSAGE_UPDATED events are skipped to reduce JSONL bloat

        This means the file only has the initial add (1 line), not all 5 updates.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "streaming.jsonl"

            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            stream_id = "stream_abc123"

            # Simulate streaming updates (same stream_id)
            for i in range(5):
                msg = Message.create_assistant(
                    content=f"Partial content {i}",
                    session_id="sess-1",
                    parent_uuid=None,
                    seq=store.next_seq(),
                    stream_id=stream_id
                )
                store.add_message(msg)

            # Wait for writes
            await asyncio.sleep(0.1)
            await writer.close()

            # Should only have 1 message in store (collapsed by stream_id)
            assert store.message_count == 1
            final_msg = store.get_ordered_messages()[0]
            assert final_msg.content == "Partial content 4"  # Last update

            # Boundary-only persistence: only MESSAGE_ADDED is persisted
            # (MESSAGE_UPDATED events are skipped to reduce JSONL bloat)
            # File should have 1 entry (the initial add)
            with open(file_path, 'r') as f:
                lines = f.readlines()
            assert len(lines) == 1


class TestSnapshotIntegration:
    """Tests for file snapshot integration."""

    @pytest.mark.asyncio
    async def test_snapshot_persist_and_load(self):
        """Test persisting and loading file snapshots."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "with_snapshot.jsonl"

            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            # Add message
            msg = Message.create_user("Edit test.py", "sess-1", None, store.next_seq())
            store.add_message(msg)

            # Add snapshot
            from src.session.models import Snapshot, FileBackup
            snapshot = FileHistorySnapshot.create("sess-1")
            snapshot.snapshots.append(Snapshot(
                file_path="/test.py",
                content="print('hello')",
                hash="abc123"
            ))
            snapshot.backups.append(FileBackup(
                file_path="/test.py",
                existed=True,
                content="print('old')"
            ))
            store.add_snapshot(snapshot)

            await asyncio.sleep(0.1)
            await writer.close()

            # Reload
            resumed = load_session(file_path)
            assert resumed.message_count == 1

            # Verify snapshot
            loaded_snap = resumed.get_snapshot(snapshot.uuid)
            assert loaded_snap is not None
            assert len(loaded_snap.snapshots) == 1
            assert loaded_snap.snapshots[0].content == "print('hello')"


class TestCompactionBoundary:
    """Tests for compaction boundary handling."""

    def test_compact_boundary_excluded_from_context(self):
        """Test that compact_boundary messages AND messages before it are excluded from LLM context.

        This is by design: after compaction, only messages AFTER the compaction boundary
        should be sent to the LLM. The compacted history is summarized.
        """
        store = MessageStore()

        # Message before compaction
        msg1 = Message.create_user("Before compaction", "sess-1", None, store.next_seq())
        store.add_message(msg1)

        # Compact boundary (marks end of compacted content)
        boundary = Message.create_system(
            "Conversation compacted", "sess-1", store.next_seq(),
            event_type="compact_boundary"
        )
        store.add_message(boundary)

        # Message after compaction - only this should be in LLM context
        msg2 = Message.create_user("After compaction", "sess-1", None, store.next_seq())
        store.add_message(msg2)

        # Get LLM context (should only include messages AFTER the boundary)
        context = store.get_llm_context_messages()

        # Only msg2 (after compaction) should be in context
        assert len(context) == 1
        assert context[0].content == "After compaction"
        assert boundary not in context
        assert msg1 not in context

    @pytest.mark.asyncio
    async def test_compact_boundary_persisted_and_loaded(self):
        """Test that compact boundaries are persisted and loaded correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "compaction.jsonl"

            store = MessageStore()
            writer = SessionWriter(file_path)
            await writer.open()
            writer.bind_to_store(store)

            # Add messages with compaction boundary
            msg = Message.create_user("Before", "sess-1", None, store.next_seq())
            store.add_message(msg)

            boundary = Message.create_system(
                "Compacted", "sess-1", store.next_seq(),
                event_type="compact_boundary"
            )
            store.add_message(boundary)

            # Add message after boundary (so we have something in context)
            msg_after = Message.create_user("After", "sess-1", None, store.next_seq())
            store.add_message(msg_after)

            await asyncio.sleep(0.1)
            await writer.close()

            # Reload
            resumed = load_session(file_path)

            # All messages should be loaded (for transcript view)
            assert resumed.message_count == 3

            # But only post-compaction messages in LLM context
            context = resumed.get_llm_context_messages()
            assert len(context) == 1
            assert context[0].content == "After"


class TestSessionManagerE2E:
    """End-to-end tests using SessionManager."""

    @pytest.mark.asyncio
    async def test_full_session_workflow_with_manager(self):
        """Test complete workflow using SessionManager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            # Create session
            info = manager.create_session(slug="e2e-test")
            session_id = info.session_id

            await manager.start_writer()

            # Add conversation
            store = manager.store

            user_msg = Message.create_user(
                "Hello!", session_id, None, store.next_seq()
            )
            store.add_message(user_msg)

            assistant_msg = Message.create_assistant(
                "Hi there! How can I help?",
                session_id, user_msg.uuid, store.next_seq()
            )
            store.add_message(assistant_msg)

            await asyncio.sleep(0.2)
            await manager.close()

            # Resume and verify
            manager2 = SessionManager(sessions_dir=tmpdir)
            resumed = manager2.resume_session(session_id)

            assert resumed.message_count == 2
            messages = manager2.store.get_ordered_messages()
            assert messages[0].content == "Hello!"
            assert messages[1].content == "Hi there! How can I help?"

    @pytest.mark.asyncio
    async def test_session_list_after_multiple_sessions(self):
        """Test listing sessions after creating multiple."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(sessions_dir=tmpdir)

            session_ids = []
            for i in range(3):
                info = manager.create_session(slug=f"session-{i}")
                session_ids.append(info.session_id)

                await manager.start_writer()
                msg = Message.create_user(f"Msg in session {i}", info.session_id, None, 1)
                manager.store.add_message(msg)
                await asyncio.sleep(0.1)
                await manager.close()

            # List sessions
            sessions = manager.list_sessions()
            assert len(sessions) == 3

            # Each has 1 message
            for session_info in sessions:
                assert session_info.message_count == 1


class TestErrorRecovery:
    """Tests for error handling and recovery."""

    @pytest.mark.asyncio
    async def test_partial_write_recovery(self):
        """Test loading session with incomplete last line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "partial.jsonl"

            # Write valid message
            msg = Message.create_user("Valid message", "sess-1", None, 1)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(msg.to_dict()) + "\n")
                f.write('{"incomplete": "json')  # Truncated line

            # Load with tolerance
            store = load_session(file_path)

            # Should have loaded the valid message
            assert store.message_count == 1
            assert store.get_ordered_messages()[0].content == "Valid message"

    def test_unknown_role_skipped(self):
        """Test that unknown roles are gracefully skipped."""
        line = json.dumps({"role": "unknown_role", "content": "test", "meta": {}})
        result = parse_line(line, 1)
        assert result is None  # Unknown roles return None


class TestLLMContextFormat:
    """Tests for LLM context export format."""

    def test_llm_context_format_openai_compatible(self):
        """Test that LLM context is OpenAI-compatible."""
        store = MessageStore()

        # Add messages
        user = Message.create_user("Hello", "sess-1", None, store.next_seq())
        store.add_message(user)

        assistant = Message.create_assistant("Hi!", "sess-1", user.uuid, store.next_seq())
        store.add_message(assistant)

        # Get context
        context = store.get_llm_context()

        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"
        assert "meta" not in context[0]  # Meta stripped

        assert context[1]["role"] == "assistant"
        assert context[1]["content"] == "Hi!"
        assert "meta" not in context[1]
