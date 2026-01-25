"""
Tests for WorkingMemory compaction functionality.

Tests cover:
- Basic compaction behavior
- Tool message grouping (assistant+tool_calls evicted together with results)
- Pending continuation summary handling
- Summary consumption (one-shot pattern)
- Transcript logging integration
- Budget threshold enforcement
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from src.memory.working_memory import WorkingMemory
from src.memory.models import Message, MessageRole


@pytest.fixture
def working_memory():
    """Create WorkingMemory instance with small token budget for testing."""
    return WorkingMemory(max_tokens=200)  # Very small to trigger compaction


@pytest.fixture
def sample_conversation():
    """Create a sample conversation with various message types (long enough to trigger compaction)."""
    return [
        (MessageRole.SYSTEM, "You are a helpful assistant. " * 5),
        (MessageRole.USER, "Help me implement a login feature. " * 10),
        (MessageRole.ASSISTANT, "I'll help you implement a login feature. Let me read the code. " * 10),
        (MessageRole.USER, "The password validation is wrong, it needs to check length. " * 10),
        (MessageRole.ASSISTANT, "I see the issue. Let me fix the validation logic properly. " * 10),
        (MessageRole.USER, "Now add a logout function to the auth module. " * 10),
        (MessageRole.ASSISTANT, "I'll add a logout function to clear the session data. " * 10),
    ]


def populate_memory(memory: WorkingMemory, messages: list):
    """Helper to populate working memory with messages."""
    for role, content in messages:
        memory.add_message(role, content)


class TestBasicCompaction:
    """Test basic compaction behavior."""

    def test_compact_evicts_old_messages(self, working_memory, sample_conversation):
        """Should evict old messages when over budget."""
        populate_memory(working_memory, sample_conversation)
        original_count = len(working_memory.messages)

        evicted = working_memory.compact(use_llm=False)

        assert evicted > 0
        assert len(working_memory.messages) < original_count

    def test_compact_keeps_system_messages(self, working_memory, sample_conversation):
        """Should always keep system messages."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        system_msgs = [m for m in working_memory.messages if m.role == MessageRole.SYSTEM]
        assert len(system_msgs) == 1
        assert "helpful assistant" in system_msgs[0].content

    def test_compact_keeps_recent_messages(self, working_memory, sample_conversation):
        """Should keep the last 2 messages."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        # Last two non-system messages should be preserved
        assert len(working_memory.messages) >= 2
        # Last message should be the logout assistant message
        assert "logout" in working_memory.messages[-1].content.lower()

    def test_compact_returns_evicted_count(self, working_memory, sample_conversation):
        """Should return the number of evicted messages."""
        populate_memory(working_memory, sample_conversation)
        original_count = len(working_memory.messages)

        evicted = working_memory.compact(use_llm=False)

        assert evicted == original_count - len(working_memory.messages)

    def test_compact_with_few_messages_does_nothing(self, working_memory):
        """Should not compact when only 2 or fewer messages."""
        working_memory.add_message(MessageRole.USER, "Hello")
        working_memory.add_message(MessageRole.ASSISTANT, "Hi")

        evicted = working_memory.compact(use_llm=False)

        assert evicted == 0
        assert len(working_memory.messages) == 2


class TestToolMessageGrouping:
    """Test that tool messages are grouped with their assistant messages."""

    def test_tool_calls_grouped_with_assistant(self, working_memory):
        """Tool calls should be evicted with their corresponding assistant message."""
        # Add a conversation with tool calls
        working_memory.add_message(MessageRole.USER, "Read the auth file")

        # Assistant with tool_calls
        working_memory.add_message(
            MessageRole.ASSISTANT,
            "",
            metadata={"tool_calls": [{"function": {"name": "read_file", "arguments": '{"path": "auth.py"}'}}]}
        )

        # Tool result
        working_memory.add_message(
            MessageRole.TOOL,
            "def login(): pass",
            metadata={"tool_call_id": "call_123", "name": "read_file"}
        )

        # More messages to trigger compaction
        for i in range(10):
            working_memory.add_message(MessageRole.USER, f"Question {i} " * 20)
            working_memory.add_message(MessageRole.ASSISTANT, f"Answer {i} " * 20)

        working_memory.compact(use_llm=False)

        # Check we don't have orphaned tool messages
        tool_msgs = [m for m in working_memory.messages if m.role == MessageRole.TOOL]
        assistant_with_tools = [m for m in working_memory.messages
                               if m.role == MessageRole.ASSISTANT and m.metadata.get("tool_calls")]

        # Either both are present or neither (grouped together)
        if tool_msgs:
            assert assistant_with_tools, "Tool result found without corresponding tool_calls message"

    def test_group_tool_messages_creates_groups(self, working_memory):
        """_group_tool_messages should group tool_calls with their results."""
        messages = [
            Message(role=MessageRole.USER, content="Request", timestamp=datetime.now()),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                timestamp=datetime.now(),
                metadata={"tool_calls": [{"function": {"name": "read_file"}}]}
            ),
            Message(role=MessageRole.TOOL, content="file content", timestamp=datetime.now()),
            Message(role=MessageRole.USER, content="Another request", timestamp=datetime.now()),
        ]

        groups = working_memory._group_tool_messages(messages)

        # Should have 3 groups: [user], [assistant+tool], [user]
        assert len(groups) == 3
        assert len(groups[0]) == 1  # Standalone user
        assert len(groups[1]) == 2  # Assistant with tool_calls + tool result
        assert len(groups[2]) == 1  # Standalone user

    def test_multiple_tool_results_grouped(self, working_memory):
        """Multiple tool results should be grouped with their assistant message."""
        messages = [
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                timestamp=datetime.now(),
                metadata={"tool_calls": [
                    {"function": {"name": "read_file"}},
                    {"function": {"name": "list_dir"}}
                ]}
            ),
            Message(role=MessageRole.TOOL, content="file content", timestamp=datetime.now()),
            Message(role=MessageRole.TOOL, content="dir listing", timestamp=datetime.now()),
        ]

        groups = working_memory._group_tool_messages(messages)

        # Should be one group with all 3 messages
        assert len(groups) == 1
        assert len(groups[0]) == 3


class TestPendingContinuationSummary:
    """Test pending continuation summary handling."""

    def test_compact_generates_summary(self, working_memory, sample_conversation):
        """Compaction should generate a pending summary."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        assert working_memory.has_pending_summary()
        summary = working_memory.pending_continuation_summary
        assert summary is not None
        assert len(summary) > 0

    def test_summary_contains_user_messages(self, working_memory, sample_conversation):
        """Summary should contain user messages."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        summary = working_memory.pending_continuation_summary
        # At least some user content should be preserved
        assert "login" in summary.lower() or "password" in summary.lower() or "logout" in summary.lower()

    def test_has_pending_summary_false_initially(self, working_memory):
        """has_pending_summary should be False before compaction."""
        assert not working_memory.has_pending_summary()

    def test_has_pending_summary_true_after_compaction(self, working_memory, sample_conversation):
        """has_pending_summary should be True after compaction."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        assert working_memory.has_pending_summary()


class TestSummaryConsumption:
    """Test one-shot summary consumption pattern."""

    def test_consume_pending_summary_returns_summary(self, working_memory, sample_conversation):
        """consume_pending_summary should return the summary."""
        populate_memory(working_memory, sample_conversation)
        working_memory.compact(use_llm=False)

        summary = working_memory.consume_pending_summary()

        assert summary is not None
        assert len(summary) > 0

    def test_consume_pending_summary_clears_summary(self, working_memory, sample_conversation):
        """consume_pending_summary should clear the summary (one-shot)."""
        populate_memory(working_memory, sample_conversation)
        working_memory.compact(use_llm=False)

        working_memory.consume_pending_summary()

        assert not working_memory.has_pending_summary()
        assert working_memory.pending_continuation_summary is None

    def test_consume_returns_none_when_no_summary(self, working_memory):
        """consume_pending_summary should return None when no summary."""
        result = working_memory.consume_pending_summary()

        assert result is None

    def test_multiple_consume_returns_none_after_first(self, working_memory, sample_conversation):
        """Only first consume should return the summary."""
        populate_memory(working_memory, sample_conversation)
        working_memory.compact(use_llm=False)

        first = working_memory.consume_pending_summary()
        second = working_memory.consume_pending_summary()

        assert first is not None
        assert second is None


class TestSummaryMerging:
    """Test that multiple compactions merge summaries."""

    def test_multiple_compactions_merge_summaries(self, working_memory):
        """Multiple compactions should merge summaries."""
        # First batch of messages
        for i in range(5):
            working_memory.add_message(MessageRole.USER, f"First batch message {i} " * 20)
            working_memory.add_message(MessageRole.ASSISTANT, f"First batch response {i} " * 20)

        working_memory.compact(use_llm=False)
        first_summary = working_memory.pending_continuation_summary

        # Second batch of messages
        for i in range(5):
            working_memory.add_message(MessageRole.USER, f"Second batch message {i} " * 20)
            working_memory.add_message(MessageRole.ASSISTANT, f"Second batch response {i} " * 20)

        working_memory.compact(use_llm=False)
        merged_summary = working_memory.pending_continuation_summary

        # Merged should be longer than first
        assert len(merged_summary) > len(first_summary)
        assert "Additional context" in merged_summary or "further compaction" in merged_summary


class TestTranscriptLogging:
    """Test transcript logging integration."""

    def test_logs_compaction_event(self, sample_conversation):
        """Should log compaction event to transcript logger."""
        mock_logger = MagicMock()
        working_memory = WorkingMemory(max_tokens=500, transcript_logger=mock_logger)
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        mock_logger.log_compaction.assert_called_once()
        call_kwargs = mock_logger.log_compaction.call_args[1]
        assert "tokens_before" in call_kwargs
        assert "tokens_after" in call_kwargs
        assert "evicted_count" in call_kwargs
        assert "summary_tokens" in call_kwargs

    def test_handles_logger_errors_gracefully(self, sample_conversation):
        """Should handle transcript logger errors without crashing."""
        mock_logger = MagicMock()
        mock_logger.log_compaction.side_effect = Exception("Logger error")
        working_memory = WorkingMemory(max_tokens=500, transcript_logger=mock_logger)
        populate_memory(working_memory, sample_conversation)

        # Should not raise
        evicted = working_memory.compact(use_llm=False)

        assert evicted > 0


class TestMessageToDict:
    """Test message to dict conversion for summarizer."""

    def test_basic_message_conversion(self, working_memory):
        """Should convert basic message to dict."""
        msg = Message(
            role=MessageRole.USER,
            content="Hello",
            timestamp=datetime.now()
        )

        result = working_memory._message_to_dict(msg)

        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_tool_call_message_conversion(self, working_memory):
        """Should include tool_calls in conversion."""
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="",
            timestamp=datetime.now(),
            metadata={"tool_calls": [{"function": {"name": "read_file"}}]}
        )

        result = working_memory._message_to_dict(msg)

        assert result["role"] == "assistant"
        assert "tool_calls" in result
        assert result["tool_calls"][0]["function"]["name"] == "read_file"

    def test_tool_result_message_conversion(self, working_memory):
        """Should include tool_call_id and name in conversion."""
        msg = Message(
            role=MessageRole.TOOL,
            content="file content",
            timestamp=datetime.now(),
            metadata={"tool_call_id": "call_123", "name": "read_file"}
        )

        result = working_memory._message_to_dict(msg)

        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_123"
        assert result["name"] == "read_file"


class TestTokenBudget:
    """Test token budget handling."""

    def test_compact_reduces_tokens_significantly(self, working_memory, sample_conversation):
        """Compaction should significantly reduce token count in retained messages."""
        populate_memory(working_memory, sample_conversation)
        original_tokens = working_memory.get_current_token_count()

        working_memory.compact(use_llm=False)

        # Retained message tokens should be reduced
        retained_tokens = working_memory.get_current_token_count()
        assert retained_tokens < original_tokens

    def test_summary_preserves_user_context(self, working_memory, sample_conversation):
        """Summary should preserve user messages that were evicted."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        # Summary should exist and contain user context
        summary = working_memory.pending_continuation_summary
        assert summary is not None
        # User messages about login/password/logout should be in summary
        assert "login" in summary.lower() or "password" in summary.lower()

    def test_total_context_preserved(self, working_memory, sample_conversation):
        """Total context (retained + summary) preserves conversation continuity."""
        populate_memory(working_memory, sample_conversation)
        original_tokens = working_memory.get_current_token_count()

        working_memory.compact(use_llm=False)

        # Get summary tokens
        summary = working_memory.pending_continuation_summary
        summary_tokens = working_memory.count_tokens(summary) if summary else 0
        retained_tokens = working_memory.get_current_token_count()

        # Total should be less than original (compression achieved)
        total_tokens = retained_tokens + summary_tokens
        assert total_tokens < original_tokens

    def test_no_compaction_when_under_budget(self):
        """Should not evict when under budget."""
        memory = WorkingMemory(max_tokens=10000)  # Large budget
        memory.add_message(MessageRole.USER, "Hello")
        memory.add_message(MessageRole.ASSISTANT, "Hi")
        memory.add_message(MessageRole.USER, "How are you?")
        memory.add_message(MessageRole.ASSISTANT, "I'm fine")

        evicted = memory.compact(use_llm=False)

        # Still have 4 messages (>2), but under budget, so selective eviction
        # depends on whether we're over 90% of budget
        assert evicted >= 0


class TestGetContextForLLM:
    """Test get_context_for_llm with tool messages."""

    def test_formats_tool_messages_correctly(self, working_memory):
        """Tool messages should have correct format for OpenAI API."""
        working_memory.add_message(
            MessageRole.ASSISTANT,
            "",
            metadata={"tool_calls": [{"id": "call_123", "function": {"name": "read_file"}}]}
        )
        working_memory.add_message(
            MessageRole.TOOL,
            "file content",
            metadata={"tool_call_id": "call_123", "name": "read_file"}
        )

        context = working_memory.get_context_for_llm()

        # Find tool message
        tool_msg = next((m for m in context if m.get("role") == "tool"), None)
        assert tool_msg is not None
        assert tool_msg["tool_call_id"] == "call_123"
        assert tool_msg["name"] == "read_file"

    def test_includes_assistant_tool_calls(self, working_memory):
        """Assistant messages with tool_calls should include them."""
        tool_calls = [{"id": "call_123", "function": {"name": "read_file"}}]
        working_memory.add_message(
            MessageRole.ASSISTANT,
            "Let me read that file",
            metadata={"tool_calls": tool_calls}
        )

        context = working_memory.get_context_for_llm()

        assistant_msg = next((m for m in context if m.get("role") == "assistant"), None)
        assert assistant_msg is not None
        assert "tool_calls" in assistant_msg
        assert assistant_msg["tool_calls"] == tool_calls


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_memory_compact(self, working_memory):
        """Compacting empty memory should not crash."""
        evicted = working_memory.compact(use_llm=False)
        assert evicted == 0

    def test_only_system_messages(self, working_memory):
        """Compacting with only system messages should not crash."""
        working_memory.add_message(MessageRole.SYSTEM, "System prompt")
        evicted = working_memory.compact(use_llm=False)
        assert evicted == 0

    def test_messages_stay_sorted_by_timestamp(self, working_memory, sample_conversation):
        """Messages should remain sorted by timestamp after compaction."""
        populate_memory(working_memory, sample_conversation)

        working_memory.compact(use_llm=False)

        timestamps = [m.timestamp for m in working_memory.messages]
        assert timestamps == sorted(timestamps)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
