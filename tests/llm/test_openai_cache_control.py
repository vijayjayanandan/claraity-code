"""Tests for OpenAIBackend prompt caching logic.

Covers:
- _add_cache_control_to_message (static): format for each message role
- _apply_cache_control: BP1 (system) and BP2 (last message) placement
- _is_anthropic_model: gating for cache control
- _extract_cached_tokens: usage field extraction
"""

import pytest
from unittest.mock import patch, MagicMock
from src.llm.openai_backend import OpenAIBackend
from src.llm.base import LLMConfig, LLMBackendType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(model_name="claude-sonnet-4-6"):
    return LLMConfig(
        backend_type=LLMBackendType.OPENAI,
        model_name=model_name,
        base_url="https://test.example.com/v1",
        temperature=0.2,
        max_tokens=4096,
        top_p=0.95,
        context_window=200000,
    )


@pytest.fixture
def claude_backend():
    """OpenAIBackend configured with a Claude model name."""
    with patch("src.llm.openai_backend.OpenAI"), \
         patch("src.llm.openai_backend.AsyncOpenAI"):
        return OpenAIBackend(_make_config("claude-sonnet-4-6"), api_key="test-key")


@pytest.fixture
def gpt_backend():
    """OpenAIBackend configured with a non-Claude model name."""
    with patch("src.llm.openai_backend.OpenAI"), \
         patch("src.llm.openai_backend.AsyncOpenAI"):
        return OpenAIBackend(_make_config("gpt-4o"), api_key="test-key")


# ---------------------------------------------------------------------------
# _is_anthropic_model
# ---------------------------------------------------------------------------

class TestIsAnthropicModel:
    def test_claude_model_detected(self, claude_backend):
        assert claude_backend._is_anthropic_model() is True

    def test_gpt_model_not_detected(self, gpt_backend):
        assert gpt_backend._is_anthropic_model() is False

    def test_claude_case_insensitive(self):
        with patch("src.llm.openai_backend.OpenAI"), \
             patch("src.llm.openai_backend.AsyncOpenAI"):
            backend = OpenAIBackend(_make_config("Claude-Sonnet-4-6"), api_key="k")
        assert backend._is_anthropic_model() is True


# ---------------------------------------------------------------------------
# _add_cache_control_to_message
# ---------------------------------------------------------------------------

class TestAddCacheControlToMessage:
    """Tests for the static method that adds cache_control to a single message."""

    def test_user_message_string_content(self):
        msg = {"role": "user", "content": "Hello"}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello"
        assert result["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_assistant_message_string_content(self):
        msg = {"role": "assistant", "content": "Hi there"}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        assert isinstance(result["content"], list)
        assert result["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_system_message_string_content(self):
        msg = {"role": "system", "content": "You are helpful."}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        assert isinstance(result["content"], list)
        assert result["content"][0]["text"] == "You are helpful."
        assert result["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_tool_message_uses_sibling_field(self):
        """Tool messages must use cache_control as sibling, not in content blocks."""
        msg = {"role": "tool", "tool_call_id": "call_1", "content": "file contents"}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        # Content stays as plain string
        assert result["content"] == "file contents"
        # cache_control is a top-level sibling field
        assert result["cache_control"] == {"type": "ephemeral"}

    def test_content_none_returns_unchanged(self):
        """Assistant tool-call-only messages have content=None."""
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        assert result["content"] is None
        assert "cache_control" not in result

    def test_content_blocks_adds_to_last_block(self):
        """Messages already in content blocks format get cache_control on last block."""
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
        }
        result = OpenAIBackend._add_cache_control_to_message(msg)
        # First block unchanged
        assert "cache_control" not in result["content"][0]
        # Last block gets cache_control
        assert result["content"][1]["cache_control"] == {"type": "ephemeral"}

    def test_empty_content_blocks_unchanged(self):
        msg = {"role": "user", "content": []}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        assert result["content"] == []

    def test_original_message_not_mutated(self):
        msg = {"role": "user", "content": "Original"}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        # Original message is untouched
        assert msg["content"] == "Original"
        assert isinstance(result["content"], list)

    def test_tool_message_original_not_mutated(self):
        msg = {"role": "tool", "tool_call_id": "c1", "content": "data"}
        result = OpenAIBackend._add_cache_control_to_message(msg)
        assert "cache_control" not in msg
        assert "cache_control" in result


# ---------------------------------------------------------------------------
# _apply_cache_control
# ---------------------------------------------------------------------------

class TestApplyCacheControl:
    """Tests for the method that places BP1 and BP2 on messages."""

    def test_bp1_on_system_message(self, claude_backend):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = claude_backend._apply_cache_control(messages)
        # BP1: system message converted to content blocks with cache_control
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_bp2_on_last_message(self, claude_backend):
        """BP2 should land on the LAST message, not second-to-last."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Second"},
        ]
        result = claude_backend._apply_cache_control(messages)
        # BP2 on last message (index 3 = "Second")
        assert isinstance(result[3]["content"], list)
        assert result[3]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # Second-to-last (index 2) should NOT have cache_control
        assert result[2]["content"] == "Response 1"

    def test_bp2_skips_content_none(self, claude_backend):
        """BP2 walks backwards past assistant messages with content=None."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Read file"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        ]
        result = claude_backend._apply_cache_control(messages)
        # Last message (index 2) has content=None, skip it
        assert result[2]["content"] is None
        # BP2 lands on index 1 (user message)
        assert isinstance(result[1]["content"], list)
        assert result[1]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_bp2_on_tool_result(self, claude_backend):
        """BP2 on a tool result uses sibling cache_control."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Read file"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "file data"},
        ]
        result = claude_backend._apply_cache_control(messages)
        # BP2 on last message (index 3 = tool result)
        assert result[3]["content"] == "file data"  # content stays string
        assert result[3]["cache_control"] == {"type": "ephemeral"}

    def test_bp2_with_two_messages(self, claude_backend):
        """BP2 applies even with just 2 messages (system + user)."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
        ]
        result = claude_backend._apply_cache_control(messages)
        # BP1 on system
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # BP2 on user (last message)
        assert isinstance(result[1]["content"], list)
        assert result[1]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_single_message_no_bp2(self, claude_backend):
        """Single message gets no BP2 (only BP1 if system)."""
        messages = [{"role": "system", "content": "System"}]
        result = claude_backend._apply_cache_control(messages)
        assert len(result) == 1

    def test_non_anthropic_model_unchanged(self, gpt_backend):
        """Non-Claude models get messages returned unchanged."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = gpt_backend._apply_cache_control(messages)
        for i, msg in enumerate(result):
            assert result[i]["content"] == messages[i]["content"]

    def test_tool_loop_bp2_progression(self, claude_backend):
        """Simulate a 3-call tool loop - BP2 should always be on the last message."""
        # Call 1: [system, user]
        msgs1 = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Read src/cli.py"},
        ]
        r1 = claude_backend._apply_cache_control(msgs1)
        # BP2 on user (index 1)
        assert isinstance(r1[1]["content"], list)

        # Call 2: [system, user, assistant(tc), tool_result]
        msgs2 = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Read src/cli.py"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "def main(): pass"},
        ]
        r2 = claude_backend._apply_cache_control(msgs2)
        # BP2 on tool_result (index 3) - last with content
        assert r2[3].get("cache_control") == {"type": "ephemeral"}
        assert r2[3]["content"] == "def main(): pass"

        # Call 3: [system, user, asst(tc), tool, asst(text), user2]
        msgs3 = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Read src/cli.py"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "def main(): pass"},
            {"role": "assistant", "content": "main() is the entry point."},
            {"role": "user", "content": "Now edit it."},
        ]
        r3 = claude_backend._apply_cache_control(msgs3)
        # BP2 on last user (index 5) - last message
        assert isinstance(r3[5]["content"], list)
        assert r3[5]["content"][0]["text"] == "Now edit it."
        assert r3[5]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # Earlier messages unchanged (no stale cache_control)
        assert r3[3]["content"] == "def main(): pass"
        assert "cache_control" not in r3[3]

    def test_original_messages_not_mutated(self, claude_backend):
        """_apply_cache_control must not mutate the input list or messages."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
        ]
        original_content = messages[1]["content"]
        claude_backend._apply_cache_control(messages)
        # Original message content untouched
        assert messages[1]["content"] == original_content
        assert isinstance(messages[1]["content"], str)


# ---------------------------------------------------------------------------
# _extract_cached_tokens
# ---------------------------------------------------------------------------

class TestExtractCachedTokens:

    def test_returns_cached_value(self):
        usage = MagicMock()
        usage.prompt_tokens_details = MagicMock(cached_tokens=5000)
        assert OpenAIBackend._extract_cached_tokens(usage) == 5000

    def test_returns_none_when_zero(self):
        usage = MagicMock()
        usage.prompt_tokens_details = MagicMock(cached_tokens=0)
        assert OpenAIBackend._extract_cached_tokens(usage) is None

    def test_returns_none_when_no_details(self):
        usage = MagicMock()
        usage.prompt_tokens_details = None
        assert OpenAIBackend._extract_cached_tokens(usage) is None

    def test_returns_none_when_no_usage(self):
        assert OpenAIBackend._extract_cached_tokens(None) is None
