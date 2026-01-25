"""Tests for provider translators (OpenAI and Anthropic)."""

import pytest
from src.session.providers import from_openai, to_openai, from_anthropic, to_anthropic
from src.session.providers.anthropic import get_system_prompt
from src.session.models import Message


class TestOpenAIProvider:
    """Tests for OpenAI response translation."""

    def test_from_openai_simple_response(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Hello!"
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5
            }
        }

        msg = from_openai(response, "sess-1", "parent-1", seq=1)

        assert msg.role == "assistant"
        assert msg.content == "Hello!"
        assert msg.meta.provider == "openai"
        assert msg.meta.model == "gpt-4"
        assert msg.meta.stop_reason == "complete"
        assert msg.meta.usage.input_tokens == 10
        assert msg.meta.usage.output_tokens == 5

    def test_from_openai_with_tool_calls(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Let me read that file.",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {
                                "name": "Read",
                                "arguments": "{\"file_path\": \"test.py\"}"
                            }
                        }
                    ]
                },
                "finish_reason": "tool_calls"
            }]
        }

        msg = from_openai(response, "sess-1", "parent-1", seq=1)

        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "call_abc"
        assert msg.tool_calls[0].function.name == "Read"
        assert msg.meta.stop_reason == "tool_use"
        # Should have segments since both content and tool_calls
        assert msg.meta.segments is not None
        assert len(msg.meta.segments) == 2

    def test_from_openai_tool_calls_none(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                    "tool_calls": None
                },
                "finish_reason": "stop"
            }]
        }

        msg = from_openai(response, "sess-1", "parent-1", seq=1)

        assert len(msg.tool_calls) == 0

    def test_from_openai_stores_raw_response(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {"role": "assistant", "content": "Hi"},
                "finish_reason": "stop"
            }]
        }

        msg = from_openai(response, "sess-1", None, seq=1)

        assert msg._raw_response is not None
        assert msg._raw_response["id"] == "chatcmpl-123"

    def test_from_openai_with_stream_id(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {"role": "assistant", "content": "Hi"},
                "finish_reason": "stop"
            }]
        }

        msg = from_openai(response, "sess-1", None, seq=1, stream_id="custom_stream")

        assert msg.stream_id == "custom_stream"

    def test_from_openai_generates_stream_id(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {"role": "assistant", "content": "Hi"},
                "finish_reason": "stop"
            }]
        }

        msg = from_openai(response, "sess-1", None, seq=1)

        assert msg.stream_id is not None
        assert msg.stream_id.startswith("stream_")

    def test_from_openai_max_tokens_stop_reason(self):
        response = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {"role": "assistant", "content": "Truncated..."},
                "finish_reason": "length"
            }]
        }

        msg = from_openai(response, "sess-1", None, seq=1)

        assert msg.meta.stop_reason == "max_tokens"

    def test_to_openai_strips_meta(self):
        msg = Message.create_assistant(
            content="Hello",
            session_id="sess-1",
            parent_uuid=None,
            seq=1
        )

        result = to_openai([msg])

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Hello"
        assert "meta" not in result[0]

    def test_to_openai_multiple_messages(self):
        messages = [
            Message.create_user("Hello", "sess-1", None, 1),
            Message.create_assistant("Hi!", "sess-1", "u1", 2),
        ]

        result = to_openai(messages)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"


class TestAnthropicProvider:
    """Tests for Anthropic response translation."""

    def test_from_anthropic_text_only(self):
        response = {
            "id": "msg_123",
            "model": "claude-3-opus",
            "content": [
                {"type": "text", "text": "Hello there!"}
            ],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50
            }
        }

        msg = from_anthropic(response, "sess-1", "parent-1", seq=1)

        assert msg.role == "assistant"
        assert msg.content == "Hello there!"
        assert msg.meta.provider == "anthropic"
        assert msg.meta.stop_reason == "complete"
        assert msg.meta.usage.input_tokens == 100

    def test_from_anthropic_with_tool_use(self):
        response = {
            "id": "msg_123",
            "model": "claude-3-opus",
            "content": [
                {"type": "text", "text": "Let me read that file."},
                {
                    "type": "tool_use",
                    "id": "tool_abc",
                    "name": "Read",
                    "input": {"file_path": "test.py"}
                }
            ],
            "stop_reason": "tool_use"
        }

        msg = from_anthropic(response, "sess-1", "parent-1", seq=1)

        assert msg.content == "Let me read that file."
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "tool_abc"
        assert msg.tool_calls[0].function.name == "Read"
        assert msg.meta.stop_reason == "tool_use"
        # Should have segments for interleaving
        assert msg.meta.segments is not None

    def test_from_anthropic_with_thinking(self):
        response = {
            "id": "msg_123",
            "model": "claude-3-opus",
            "content": [
                {"type": "thinking", "thinking": "Let me reason through this..."},
                {"type": "text", "text": "The answer is 42."}
            ],
            "stop_reason": "end_turn"
        }

        msg = from_anthropic(response, "sess-1", "parent-1", seq=1)

        assert msg.content == "The answer is 42."
        assert msg.meta.thinking == "Let me reason through this..."
        assert msg.meta.segments is not None
        assert len(msg.meta.segments) == 2

    def test_from_anthropic_multiple_text_blocks(self):
        response = {
            "id": "msg_123",
            "model": "claude-3-opus",
            "content": [
                {"type": "text", "text": "First part."},
                {"type": "text", "text": "Second part."}
            ],
            "stop_reason": "end_turn"
        }

        msg = from_anthropic(response, "sess-1", "parent-1", seq=1)

        # Text parts are concatenated
        assert msg.content == "First part.\nSecond part."

    def test_from_anthropic_with_cache_tokens(self):
        response = {
            "id": "msg_123",
            "model": "claude-3-opus",
            "content": [{"type": "text", "text": "Hello"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 20
            }
        }

        msg = from_anthropic(response, "sess-1", "parent-1", seq=1)

        assert msg.meta.usage.cache_read_tokens == 30
        assert msg.meta.usage.cache_write_tokens == 20

    def test_to_anthropic_simple_messages(self):
        messages = [
            Message.create_user("Hello", "sess-1", None, 1),
            Message.create_assistant("Hi!", "sess-1", "u1", 2),
        ]

        result = to_anthropic(messages)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert result[1]["role"] == "assistant"

    def test_to_anthropic_with_tool_calls(self):
        from src.session.models import ToolCall, ToolCallFunction

        tc = ToolCall(
            id="call_123",
            function=ToolCallFunction(name="Read", arguments='{"file_path": "test.py"}')
        )
        msg = Message.create_assistant(
            content="Reading file",
            session_id="sess-1",
            parent_uuid=None,
            seq=1,
            tool_calls=[tc]
        )

        result = to_anthropic([msg])

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        content_blocks = result[0]["content"]
        assert len(content_blocks) == 2  # text + tool_use
        assert content_blocks[0]["type"] == "text"
        assert content_blocks[1]["type"] == "tool_use"
        assert content_blocks[1]["name"] == "Read"

    def test_to_anthropic_tool_result(self):
        msg = Message.create_tool(
            tool_call_id="call_123",
            content="File content here",
            session_id="sess-1",
            parent_uuid=None,
            seq=1
        )

        result = to_anthropic([msg])

        assert len(result) == 1
        assert result[0]["role"] == "user"  # Tool results are user role in Anthropic
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "call_123"

    def test_to_anthropic_skips_system(self):
        messages = [
            Message.create_system("System prompt", "sess-1", 1),
            Message.create_user("Hello", "sess-1", None, 2),
        ]

        result = to_anthropic(messages)

        # System message should be skipped
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_get_system_prompt(self):
        messages = [
            Message.create_system("You are a helpful assistant.", "sess-1", 1),
            Message.create_user("Hello", "sess-1", None, 2),
        ]

        system = get_system_prompt(messages)

        assert system == "You are a helpful assistant."

    def test_get_system_prompt_none(self):
        messages = [
            Message.create_user("Hello", "sess-1", None, 1),
        ]

        system = get_system_prompt(messages)

        assert system is None

    def test_to_anthropic_with_thinking(self):
        from src.session.models import MessageMeta

        # Create message with thinking in meta
        meta = MessageMeta(
            uuid="m1",
            seq=1,
            timestamp="2024-01-01T00:00:00Z",
            session_id="sess-1",
            parent_uuid=None,
            is_sidechain=False,
            thinking="My reasoning here"
        )
        msg = Message(role="assistant", content="The answer", meta=meta)

        result = to_anthropic([msg])

        content_blocks = result[0]["content"]
        assert len(content_blocks) == 2
        assert content_blocks[0]["type"] == "thinking"
        assert content_blocks[0]["thinking"] == "My reasoning here"
        assert content_blocks[1]["type"] == "text"
