"""Tests for LiteLLM placeholder sanitization in OpenAIBackend.

Covers:
- _strip_litellm_placeholder: inbound response content stripping
- _sanitize_outbound_messages: outbound history cleaning
- _prepare_messages: integration of sanitization + cache control
"""

from unittest.mock import patch

import pytest

from src.llm.base import LLMBackendType, LLMConfig
from src.llm.openai_backend import OpenAIBackend

PLACEHOLDER_PROTOCOL = "[System: Empty message content sanitised to satisfy protocol]"
PLACEHOLDER_PROTOTYPE = "[System: Empty message content sanitised to satisfy prototype]"


@pytest.fixture
def backend():
    with patch("src.llm.openai_backend.OpenAI"), \
         patch("src.llm.openai_backend.AsyncOpenAI"):
        config = LLMConfig(
            backend_type=LLMBackendType.OPENAI,
            model_name="claude-sonnet-4-6",
            base_url="https://test.example.com/v1",
            temperature=0.2,
            max_tokens=4096,
            top_p=0.95,
            context_window=200000,
        )
        return OpenAIBackend(config, api_key="test-key")


# ---------------------------------------------------------------------------
# _strip_litellm_placeholder
# ---------------------------------------------------------------------------

class TestStripLitellmPlaceholder:
    def test_none_passthrough(self):
        assert OpenAIBackend._strip_litellm_placeholder(None) is None

    def test_empty_string_passthrough(self):
        assert OpenAIBackend._strip_litellm_placeholder("") == ""

    def test_normal_content_unchanged(self):
        text = "Here is the analysis of your code."
        assert OpenAIBackend._strip_litellm_placeholder(text) == text

    def test_strips_protocol_variant(self):
        assert OpenAIBackend._strip_litellm_placeholder(PLACEHOLDER_PROTOCOL) is None

    def test_strips_prototype_variant(self):
        assert OpenAIBackend._strip_litellm_placeholder(PLACEHOLDER_PROTOTYPE) is None

    def test_strips_repeated_placeholders(self):
        content = PLACEHOLDER_PROTOCOL * 3
        assert OpenAIBackend._strip_litellm_placeholder(content) is None

    def test_strips_mixed_variants(self):
        content = PLACEHOLDER_PROTOCOL + PLACEHOLDER_PROTOTYPE
        assert OpenAIBackend._strip_litellm_placeholder(content) is None

    def test_preserves_real_content_around_placeholder(self):
        content = f"Hello {PLACEHOLDER_PROTOCOL} world"
        result = OpenAIBackend._strip_litellm_placeholder(content)
        assert result == "Hello  world"

    def test_strips_placeholder_with_surrounding_whitespace(self):
        content = f"  {PLACEHOLDER_PROTOCOL}  "
        assert OpenAIBackend._strip_litellm_placeholder(content) is None

    def test_space_only_chunk_preserved(self):
        """Streaming deltas that are just whitespace must pass through."""
        assert OpenAIBackend._strip_litellm_placeholder(" ") == " "
        assert OpenAIBackend._strip_litellm_placeholder("  ") == "  "
        assert OpenAIBackend._strip_litellm_placeholder("\n") == "\n"


# ---------------------------------------------------------------------------
# _sanitize_outbound_messages
# ---------------------------------------------------------------------------

class TestSanitizeOutboundMessages:
    def test_user_messages_unchanged(self):
        messages = [{"role": "user", "content": "hello"}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result == messages

    def test_system_messages_unchanged(self):
        messages = [{"role": "system", "content": "You are helpful."}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result == messages

    def test_assistant_with_real_content_unchanged(self):
        messages = [{"role": "assistant", "content": "I'll help you with that."}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] == "I'll help you with that."

    def test_assistant_empty_string_becomes_none(self):
        messages = [{"role": "assistant", "content": ""}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None

    def test_assistant_whitespace_becomes_none(self):
        messages = [{"role": "assistant", "content": "   "}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None

    def test_assistant_placeholder_becomes_none(self):
        messages = [{"role": "assistant", "content": PLACEHOLDER_PROTOCOL}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None

    def test_assistant_repeated_placeholders_becomes_none(self):
        messages = [{"role": "assistant", "content": PLACEHOLDER_PROTOCOL * 3}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None

    def test_assistant_none_content_unchanged(self):
        messages = [{"role": "assistant", "content": None}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None

    def test_assistant_structured_content_empty_text_removed(self):
        messages = [{
            "role": "assistant",
            "content": [
                {"type": "text", "text": ""},
                {"type": "text", "text": PLACEHOLDER_PROTOCOL},
            ]
        }]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None

    def test_assistant_structured_content_preserves_real_text(self):
        messages = [{
            "role": "assistant",
            "content": [
                {"type": "text", "text": PLACEHOLDER_PROTOCOL},
                {"type": "text", "text": "Real content here"},
            ]
        }]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert len(result[0]["content"]) == 1
        assert result[0]["content"][0]["text"] == "Real content here"

    def test_assistant_structured_content_preserves_non_text_blocks(self):
        messages = [{
            "role": "assistant",
            "content": [
                {"type": "text", "text": ""},
                {"type": "tool_use", "id": "tc_1", "name": "read_file"},
            ]
        }]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert len(result[0]["content"]) == 1
        assert result[0]["content"][0]["type"] == "tool_use"

    def test_tool_messages_unchanged(self):
        messages = [{"role": "tool", "content": "File contents here", "tool_call_id": "tc_1"}]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result == messages

    def test_preserves_other_message_fields(self):
        messages = [{
            "role": "assistant",
            "content": PLACEHOLDER_PROTOCOL,
            "tool_calls": [{"id": "tc_1"}],
        }]
        result = OpenAIBackend._sanitize_outbound_messages(messages)
        assert result[0]["content"] is None
        assert result[0]["tool_calls"] == [{"id": "tc_1"}]

    def test_does_not_mutate_original(self):
        original_content = PLACEHOLDER_PROTOCOL
        messages = [{"role": "assistant", "content": original_content}]
        OpenAIBackend._sanitize_outbound_messages(messages)
        assert messages[0]["content"] == original_content


# ---------------------------------------------------------------------------
# _prepare_messages (integration)
# ---------------------------------------------------------------------------

class TestPrepareMessages:
    def test_sanitizes_then_applies_cache_control(self, backend):
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "assistant", "content": PLACEHOLDER_PROTOCOL},
            {"role": "user", "content": "Hello"},
        ]
        result = backend._prepare_messages(messages)
        # Assistant placeholder should be cleaned to None
        assert result[1]["content"] is None
        # Cache control should be applied (Claude model)
        assert result[0]["content"][0].get("cache_control") is not None
