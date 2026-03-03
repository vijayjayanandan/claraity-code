"""Tests for the Anthropic native backend.

All tests use mocked Anthropic SDK -- no real API calls.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# Prime import chain (see conftest.py)
import src.core  # noqa: F401

from src.llm.base import LLMConfig, LLMBackendType, ToolDefinition, ProviderDelta, ToolCallDelta
from src.session.models.message import ToolCall, ToolCallFunction


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def llm_config():
    """Create a basic LLMConfig for testing."""
    return LLMConfig(
        backend_type=LLMBackendType.ANTHROPIC,
        model_name="claude-sonnet-4-5-20250929",
        base_url="https://api.anthropic.com",
        context_window=200000,
        temperature=0.2,
        max_tokens=16384,
        top_p=0.95,
    )


@pytest.fixture
def mock_anthropic(llm_config):
    """Create an AnthropicBackend with mocked SDK clients."""
    with patch("src.llm.anthropic_backend.Anthropic") as MockSync, \
         patch("src.llm.anthropic_backend.AsyncAnthropic") as MockAsync:
        from src.llm.anthropic_backend import AnthropicBackend
        backend = AnthropicBackend(llm_config, api_key="test-key")
        backend.client = MockSync.return_value
        backend.async_client = MockAsync.return_value
        yield backend


@pytest.fixture
def sample_tools():
    """Sample tool definitions for testing."""
    return [
        ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"],
            },
        ),
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
    ]


# ============================================================================
# Message Translation Tests
# ============================================================================

class TestTranslateMessages:
    """Tests for _translate_messages()."""

    def test_system_message_extracted(self, mock_anthropic):
        """System messages should be extracted to separate parameter."""
        messages = [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Hello"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert system == "You are a coding agent."
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_multiple_system_messages_concatenated(self, mock_anthropic):
        """Multiple system messages should be joined with double newline."""
        messages = [
            {"role": "system", "content": "Rule 1"},
            {"role": "system", "content": "Rule 2"},
            {"role": "user", "content": "Hello"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert system == "Rule 1\n\nRule 2"
        assert len(msgs) == 1

    def test_simple_user_assistant_preserved(self, mock_anthropic):
        """Basic conversation should be preserved."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert system == ""
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"

    def test_assistant_tool_calls_converted(self, mock_anthropic):
        """Assistant tool_calls should become tool_use content blocks."""
        messages = [
            {"role": "user", "content": "Read main.py"},
            {
                "role": "assistant",
                "content": "Let me read that.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "main.py"}',
                        },
                    }
                ],
            },
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert len(msgs) == 2
        assistant_msg = msgs[1]
        assert assistant_msg["role"] == "assistant"

        content = assistant_msg["content"]
        assert isinstance(content, list)

        # First block: text
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Let me read that."

        # Second block: tool_use
        assert content[1]["type"] == "tool_use"
        assert content[1]["id"] == "call_123"
        assert content[1]["name"] == "read_file"
        assert content[1]["input"] == {"path": "main.py"}

    def test_tool_result_converted_to_user(self, mock_anthropic):
        """Tool results (role:tool) should become user messages with tool_result blocks."""
        messages = [
            {"role": "user", "content": "Read it"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "read_file", "arguments": '{"path": "x.py"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "file contents here",
            },
        ]
        system, msgs = mock_anthropic._translate_messages(messages)

        # Tool result should be converted to user role
        tool_result_msg = msgs[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "call_1"
        assert tool_result_msg["content"][0]["content"] == "file contents here"

    def test_consecutive_user_messages_merged(self, mock_anthropic):
        """Consecutive same-role messages should be merged."""
        messages = [
            {"role": "user", "content": "First"},
            {"role": "user", "content": "Second"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        # Content should be merged as blocks
        content = msgs[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2

    def test_tool_results_merged_into_single_user(self, mock_anthropic):
        """Multiple consecutive tool results become one user message."""
        messages = [
            {"role": "user", "content": "Do both"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}},
                    {"id": "c2", "function": {"name": "read_file", "arguments": '{"path": "b.py"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "content a"},
            {"role": "tool", "tool_call_id": "c2", "content": "content b"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)

        # Two tool results (both converted to user) should merge
        # msgs: [user, assistant, user(merged tool results)]
        assert len(msgs) == 3
        merged_user = msgs[2]
        assert merged_user["role"] == "user"
        assert len(merged_user["content"]) == 2
        assert merged_user["content"][0]["type"] == "tool_result"
        assert merged_user["content"][1]["type"] == "tool_result"

    def test_thinking_round_tripped(self, mock_anthropic):
        """Thinking blocks should be preserved in assistant messages."""
        messages = [
            {"role": "user", "content": "Think about this"},
            {
                "role": "assistant",
                "content": "My answer",
                "thinking": "I need to consider...",
                "thinking_signature": "sig123",
            },
            {"role": "user", "content": "Continue"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assistant_content = msgs[1]["content"]

        # Should have thinking block first, then text
        assert assistant_content[0]["type"] == "thinking"
        assert assistant_content[0]["thinking"] == "I need to consider..."
        assert assistant_content[0]["signature"] == "sig123"
        assert assistant_content[1]["type"] == "text"
        assert assistant_content[1]["text"] == "My answer"

    def test_conversation_starts_with_user(self, mock_anthropic):
        """If conversation starts with assistant, prepend synthetic user message."""
        messages = [
            {"role": "assistant", "content": "Resuming..."},
            {"role": "user", "content": "Continue"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Continue."

    def test_empty_messages(self, mock_anthropic):
        """Empty message list should produce a default user message."""
        system, msgs = mock_anthropic._translate_messages([])
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_system_with_content_blocks(self, mock_anthropic):
        """System messages with list content should be handled."""
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "Be helpful."}]},
            {"role": "user", "content": "Hi"},
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert system == "Be helpful."

    def test_image_url_converted_to_anthropic_format(self, mock_anthropic):
        """OpenAI image_url blocks should be converted to Anthropic image blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,iVBORw0KGgoAAAANS"
                        },
                    },
                ],
            },
        ]
        system, msgs = mock_anthropic._translate_messages(messages)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        assert len(content) == 2
        # Text block preserved
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "What is in this image?"
        # image_url converted to Anthropic image block
        assert content[1]["type"] == "image"
        assert content[1]["source"]["type"] == "base64"
        assert content[1]["source"]["media_type"] == "image/png"
        assert content[1]["source"]["data"] == "iVBORw0KGgoAAAANS"

    def test_image_url_jpeg_converted(self, mock_anthropic):
        """JPEG image_url should preserve correct media_type."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64,/9j/4AAQ"
                        },
                    },
                ],
            },
        ]
        _, msgs = mock_anthropic._translate_messages(messages)
        img_block = msgs[0]["content"][0]
        assert img_block["type"] == "image"
        assert img_block["source"]["media_type"] == "image/jpeg"
        assert img_block["source"]["data"] == "/9j/4AAQ"

    def test_text_block_extra_fields_stripped(self, mock_anthropic):
        """Text blocks with extra filename/mime fields should be sanitized."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Check this file"},
                    {
                        "type": "text",
                        "text": "--- BEGIN FILE: config.py ---\nDEBUG=True\n--- END FILE ---",
                        "filename": "config.py",
                        "mime": "text/x-python",
                    },
                ],
            },
        ]
        _, msgs = mock_anthropic._translate_messages(messages)
        content = msgs[0]["content"]
        assert len(content) == 2
        # Both blocks should only have 'type' and 'text' - no extra fields
        for block in content:
            assert set(block.keys()) == {"type", "text"}
        assert "filename" not in content[1]
        assert "mime" not in content[1]

    def test_image_block_extra_fields_stripped(self, mock_anthropic):
        """Image blocks with extra filename/mime fields should be sanitized."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc123"},
                        "filename": "screenshot.png",
                        "mime": "image/png",
                    },
                ],
            },
        ]
        _, msgs = mock_anthropic._translate_messages(messages)
        img_block = msgs[0]["content"][0]
        assert img_block["type"] == "image"
        assert "filename" not in img_block
        assert "mime" not in img_block
        assert img_block["source"]["data"] == "abc123"


# ============================================================================
# Tool Conversion Tests
# ============================================================================

class TestToolConversion:
    """Tests for tool definition and tool_choice conversion."""

    def test_convert_tools_format(self, mock_anthropic, sample_tools):
        """ToolDefinition should convert to Anthropic format."""
        result = mock_anthropic._convert_tools(sample_tools)
        assert len(result) == 2
        assert result[0]["name"] == "read_file"
        assert result[0]["description"] == "Read a file"
        assert "input_schema" in result[0]
        assert result[0]["input_schema"]["type"] == "object"

    def test_convert_tool_choice_auto(self, mock_anthropic):
        assert mock_anthropic._convert_tool_choice("auto") == {"type": "auto"}

    def test_convert_tool_choice_required(self, mock_anthropic):
        assert mock_anthropic._convert_tool_choice("required") == {"type": "any"}

    def test_convert_tool_choice_none(self, mock_anthropic):
        assert mock_anthropic._convert_tool_choice("none") == {"type": "none"}

    def test_convert_empty_tools(self, mock_anthropic):
        result = mock_anthropic._convert_tools([])
        assert result == []


# ============================================================================
# Response Parsing Tests
# ============================================================================

class TestResponseParsing:
    """Tests for parsing Anthropic responses."""

    def test_parse_text_response(self, mock_anthropic):
        """Text-only response should extract content."""
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "Hello world"

        result = mock_anthropic._parse_tool_use_blocks([mock_block])
        assert result == []  # No tool calls

    def test_parse_tool_use_blocks(self, mock_anthropic):
        """tool_use blocks should be parsed into ToolCall objects."""
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.id = "toolu_123"
        mock_block.name = "read_file"
        mock_block.input = {"path": "main.py"}

        result = mock_anthropic._parse_tool_use_blocks([mock_block])
        assert len(result) == 1
        assert result[0].id.startswith("tc_")
        assert len(result[0].id) == 35
        assert result[0].meta.get("provider_tool_id") == "toolu_123"
        assert result[0].function.name == "read_file"
        assert json.loads(result[0].function.arguments) == {"path": "main.py"}

    def test_parse_multiple_tool_use_blocks(self, mock_anthropic):
        """Multiple tool_use blocks should all be parsed."""
        blocks = []
        for i in range(3):
            block = MagicMock()
            block.type = "tool_use"
            block.id = f"toolu_{i}"
            block.name = f"tool_{i}"
            block.input = {"arg": i}
            blocks.append(block)

        result = mock_anthropic._parse_tool_use_blocks(blocks)
        assert len(result) == 3
        assert result[2].function.name == "tool_2"

    def test_parse_tool_use_from_dict(self, mock_anthropic):
        """Should handle dict-format blocks too."""
        blocks = [
            {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "x.py"}},
            {"type": "text", "text": "some text"},
        ]
        result = mock_anthropic._parse_tool_use_blocks(blocks)
        assert len(result) == 1
        assert result[0].id.startswith("tc_")
        assert result[0].meta.get("provider_tool_id") == "t1"

    def test_stop_reason_mapping(self, mock_anthropic):
        """All Anthropic stop reasons should map correctly."""
        assert mock_anthropic._map_stop_reason("end_turn") == "stop"
        assert mock_anthropic._map_stop_reason("tool_use") == "tool_calls"
        assert mock_anthropic._map_stop_reason("max_tokens") == "length"
        assert mock_anthropic._map_stop_reason("stop_sequence") == "stop"
        assert mock_anthropic._map_stop_reason(None) == "stop"
        assert mock_anthropic._map_stop_reason("unknown") == "stop"

    def test_build_usage_dict_from_object(self, mock_anthropic):
        """Usage dict should be built from SDK usage object."""
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.cache_read_input_tokens = 80
        usage.cache_creation_input_tokens = 20

        result = mock_anthropic._build_usage_dict(usage)
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cached_tokens"] == 80
        assert result["cache_read_tokens"] == 80
        assert result["cache_write_tokens"] == 20

    def test_build_usage_dict_none(self, mock_anthropic):
        """None usage should return empty dict."""
        assert mock_anthropic._build_usage_dict(None) == {}


# ============================================================================
# Cache Control Tests
# ============================================================================

class TestCacheControl:
    """Tests for prompt caching breakpoints."""

    def test_cache_control_on_system(self, mock_anthropic):
        """System prompt should get cache_control breakpoint."""
        system_param, msgs = mock_anthropic._apply_cache_control(
            "You are helpful.", [{"role": "user", "content": "Hi"}]
        )
        assert len(system_param) == 1
        assert system_param[0]["type"] == "text"
        assert system_param[0]["text"] == "You are helpful."
        assert system_param[0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_control_on_second_to_last(self, mock_anthropic):
        """Second-to-last message should get cache_control (BP2)."""
        messages = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Second"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Third"},
        ]
        _, result = mock_anthropic._apply_cache_control("system", messages)

        # BP2 should be on messages[-2] which is "Response 2"
        bp2_msg = result[3]
        assert isinstance(bp2_msg["content"], list)
        assert bp2_msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_control_short_conversation(self, mock_anthropic):
        """Short conversations (<3 messages) should not get BP2."""
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        _, result = mock_anthropic._apply_cache_control("sys", messages)
        # Messages should be unchanged (no BP2 applied)
        assert result[0]["content"] == "Hi"
        assert result[1]["content"] == "Hello"

    def test_cache_control_empty_system(self, mock_anthropic):
        """Empty system text should produce empty system param."""
        system_param, _ = mock_anthropic._apply_cache_control(
            "", [{"role": "user", "content": "Hi"}]
        )
        assert system_param == []


# ============================================================================
# Non-Streaming Generate Tests
# ============================================================================

class TestGenerate:
    """Tests for generate() and generate_with_tools()."""

    def test_generate_basic(self, mock_anthropic):
        """Basic generate should return LLMResponse with content."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Hello!")]
        mock_response.model = "claude-sonnet-4-5-20250929"
        mock_response.stop_reason = "end_turn"
        mock_response.id = "msg_123"
        mock_response.usage = _make_usage(input_tokens=10, output_tokens=5)
        mock_anthropic.client.messages.create.return_value = mock_response

        result = mock_anthropic.generate([
            {"role": "user", "content": "Hi"},
        ])

        assert result.content == "Hello!"
        assert result.finish_reason == "stop"
        assert result.prompt_tokens == 10

    def test_generate_with_tools_returns_tool_calls(self, mock_anthropic, sample_tools):
        """generate_with_tools should parse tool_use blocks into ToolCall objects."""
        mock_response = MagicMock()
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_abc"
        tool_block.name = "read_file"
        tool_block.input = {"path": "test.py"}

        mock_response.content = [tool_block]
        mock_response.model = "claude-sonnet-4-5-20250929"
        mock_response.stop_reason = "tool_use"
        mock_response.id = "msg_456"
        mock_response.usage = _make_usage(input_tokens=20, output_tokens=10)
        mock_anthropic.client.messages.create.return_value = mock_response

        result = mock_anthropic.generate_with_tools(
            [{"role": "user", "content": "Read test.py"}],
            tools=sample_tools,
        )

        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id.startswith("tc_")
        assert result.tool_calls[0].meta.get("provider_tool_id") == "toolu_abc"
        assert result.tool_calls[0].function.name == "read_file"
        assert json.loads(result.tool_calls[0].function.arguments) == {"path": "test.py"}

    def test_generate_api_error_raises_runtime(self, mock_anthropic):
        """API errors should be wrapped in RuntimeError."""
        mock_anthropic.client.messages.create.side_effect = Exception("API down")

        with pytest.raises(RuntimeError, match="Anthropic API error"):
            mock_anthropic.generate([{"role": "user", "content": "Hi"}])


# ============================================================================
# Streaming Tests
# ============================================================================

class TestStreaming:
    """Tests for streaming methods."""

    def test_stream_text_deltas_yielded(self, mock_anthropic, sample_tools):
        """Text deltas should be yielded as StreamChunk during streaming."""
        # Create mock events
        events = [
            _make_event("content_block_start", index=0, content_block=MagicMock(type="text")),
            _make_event("content_block_delta", delta=MagicMock(type="text_delta", text="Hello ")),
            _make_event("content_block_delta", delta=MagicMock(type="text_delta", text="world")),
            _make_event("content_block_stop"),
            _make_event("message_delta", delta=MagicMock(stop_reason="end_turn"), usage=None),
        ]

        mock_stream = _make_mock_stream(events, mock_anthropic)

        chunks = list(mock_anthropic.generate_with_tools_stream(
            [{"role": "user", "content": "Hi"}],
            tools=sample_tools,
        ))

        # Should have text chunks + final chunk
        text_chunks = [c for c, _ in chunks if not c.done]
        assert len(text_chunks) == 2
        assert text_chunks[0].content == "Hello "
        assert text_chunks[1].content == "world"

        # Final chunk
        final = chunks[-1]
        assert final[0].done is True

    def test_stream_tool_calls_accumulated(self, mock_anthropic, sample_tools):
        """Tool use deltas should be accumulated and returned on completion."""
        tool_block = _make_tool_block("toolu_1", "read_file")
        events = [
            _make_event("content_block_start", index=0, content_block=tool_block),
            _make_event("content_block_delta", index=0, delta=MagicMock(type="input_json_delta", partial_json='{"path":')),
            _make_event("content_block_delta", index=0, delta=MagicMock(type="input_json_delta", partial_json=' "x.py"}')),
            _make_event("content_block_stop"),
            _make_event("message_delta", delta=MagicMock(stop_reason="tool_use"), usage=None),
        ]

        _make_mock_stream(events, mock_anthropic)

        chunks = list(mock_anthropic.generate_with_tools_stream(
            [{"role": "user", "content": "Read x.py"}],
            tools=sample_tools,
        ))

        final_chunk, tool_calls = chunks[-1]
        assert final_chunk.done is True
        assert tool_calls is not None
        assert len(tool_calls) == 1
        assert tool_calls[0].id.startswith("tc_")
        assert tool_calls[0].meta.get("provider_tool_id") == "toolu_1"
        assert tool_calls[0].function.name == "read_file"
        assert json.loads(tool_calls[0].function.arguments) == {"path": "x.py"}


# ============================================================================
# ProviderDelta Tests
# ============================================================================

class TestProviderDeltas:
    """Tests for generate_provider_deltas()."""

    def test_text_delta_emitted(self, mock_anthropic, sample_tools):
        """Text content should emit ProviderDelta with text_delta."""
        events = [
            _make_event("content_block_start", index=0, content_block=MagicMock(type="text")),
            _make_event("content_block_delta", delta=MagicMock(type="text_delta", text="Hi")),
            _make_event("content_block_stop"),
            _make_event("message_delta", delta=MagicMock(stop_reason="end_turn"), usage=None),
        ]

        _make_mock_stream(events, mock_anthropic)

        deltas = list(mock_anthropic.generate_provider_deltas(
            [{"role": "user", "content": "Hi"}],
            tools=sample_tools,
            stream_id="test-stream",
        ))

        text_deltas = [d for d in deltas if d.text_delta]
        assert len(text_deltas) == 1
        assert text_deltas[0].text_delta == "Hi"
        assert text_deltas[0].stream_id == "test-stream"

    def test_tool_call_delta_emitted(self, mock_anthropic, sample_tools):
        """Tool use should emit ProviderDelta with tool_call_delta."""
        tool_block = _make_tool_block("toolu_1", "read_file")
        events = [
            _make_event("content_block_start", index=0, content_block=tool_block),
            _make_event("content_block_delta", index=0, delta=MagicMock(type="input_json_delta", partial_json='{"path":"x"}')),
            _make_event("content_block_stop"),
            _make_event("message_delta", delta=MagicMock(stop_reason="tool_use"), usage=None),
        ]

        _make_mock_stream(events, mock_anthropic)

        deltas = list(mock_anthropic.generate_provider_deltas(
            [{"role": "user", "content": "Read it"}],
            tools=sample_tools,
            stream_id="test-stream",
        ))

        tc_deltas = [d for d in deltas if d.tool_call_delta]
        assert len(tc_deltas) == 2  # start (id+name) + arguments

        # First: start with canonical id and name
        assert tc_deltas[0].tool_call_delta.id.startswith("tc_")
        assert tc_deltas[0].tool_call_delta.name == "read_file"
        assert tc_deltas[0].tool_call_delta.index == 0

        # Second: arguments
        assert tc_deltas[1].tool_call_delta.arguments_delta == '{"path":"x"}'

    def test_finish_delta_emitted(self, mock_anthropic, sample_tools):
        """Final delta should have finish_reason."""
        events = [
            _make_event("content_block_start", index=0, content_block=MagicMock(type="text")),
            _make_event("content_block_delta", delta=MagicMock(type="text_delta", text="Done")),
            _make_event("content_block_stop"),
            _make_event("message_delta", delta=MagicMock(stop_reason="end_turn"), usage=None),
        ]

        _make_mock_stream(events, mock_anthropic)

        deltas = list(mock_anthropic.generate_provider_deltas(
            [{"role": "user", "content": "Hi"}],
            tools=sample_tools,
            stream_id="test-stream",
        ))

        final = deltas[-1]
        assert final.finish_reason == "stop"  # end_turn -> stop

    def test_thinking_delta_emitted(self, mock_anthropic, sample_tools):
        """Thinking content should emit ProviderDelta with thinking_delta."""
        events = [
            _make_event("content_block_start", index=0, content_block=MagicMock(type="thinking")),
            _make_event("content_block_delta", delta=MagicMock(type="thinking_delta", thinking="Let me think...")),
            _make_event("content_block_stop"),
            _make_event("content_block_start", index=1, content_block=MagicMock(type="text")),
            _make_event("content_block_delta", delta=MagicMock(type="text_delta", text="Answer")),
            _make_event("content_block_stop"),
            _make_event("message_delta", delta=MagicMock(stop_reason="end_turn"), usage=None),
        ]

        _make_mock_stream(events, mock_anthropic)

        deltas = list(mock_anthropic.generate_provider_deltas(
            [{"role": "user", "content": "Think"}],
            tools=sample_tools,
            stream_id="test-stream",
        ))

        thinking_deltas = [d for d in deltas if d.thinking_delta]
        assert len(thinking_deltas) == 1
        assert thinking_deltas[0].thinking_delta == "Let me think..."


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Tests for error handling."""

    def test_tool_calling_error_raises_runtime(self, mock_anthropic, sample_tools):
        """Streaming errors should raise RuntimeError."""
        mock_anthropic.client.messages.stream.side_effect = Exception("Connection failed")

        with pytest.raises(RuntimeError, match="Anthropic streaming tool calling error"):
            list(mock_anthropic.generate_with_tools_stream(
                [{"role": "user", "content": "Hi"}],
                tools=sample_tools,
            ))

    def test_provider_delta_error_raises_runtime(self, mock_anthropic):
        """ProviderDelta errors should raise RuntimeError."""
        mock_anthropic.client.messages.stream.side_effect = Exception("Timeout")

        with pytest.raises(RuntimeError, match="Anthropic provider delta error"):
            list(mock_anthropic.generate_provider_deltas(
                [{"role": "user", "content": "Hi"}],
                stream_id="test",
            ))


# ============================================================================
# CacheTracker Integration Test
# ============================================================================

class TestCacheTrackerIntegration:
    """Test CacheTracker works with Anthropic usage format."""

    def test_anthropic_usage_recorded(self):
        """CacheTracker should handle Anthropic-style usage fields."""
        from src.llm.cache_tracker import CacheTracker

        tracker = CacheTracker()
        usage = MagicMock()
        usage.prompt_tokens = 0  # Not set in Anthropic style
        usage.prompt_tokens_details = None
        usage.input_tokens = 100
        usage.cache_read_input_tokens = 80
        usage.cache_creation_input_tokens = 20

        tracker.record(usage)

        assert tracker.total_calls == 1
        assert tracker.cache_read_tokens == 80
        assert tracker.cache_write_tokens == 20
        assert tracker.cache_hits == 1


# ============================================================================
# Helpers
# ============================================================================

def _make_tool_block(block_id, block_name):
    """Create a mock tool_use content block.

    MagicMock(name="read_file") sets the mock's internal name, NOT an attribute.
    Use a SimpleNamespace to avoid this pitfall.
    """
    from types import SimpleNamespace
    return SimpleNamespace(type="tool_use", id=block_id, name=block_name)


def _make_usage(input_tokens=100, output_tokens=50, cache_read=0, cache_write=0):
    """Create a mock Anthropic usage object with real integer attributes.

    MagicMock auto-attributes return MagicMock objects which break
    comparisons (e.g., max(int, MagicMock)). This helper ensures all
    attributes are real integers.
    """
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_write
    # OpenAI-style attrs (to avoid MagicMock leaking through)
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens
    usage.total_tokens = input_tokens + output_tokens
    usage.prompt_tokens_details = None
    return usage


def _make_event(event_type, **kwargs):
    """Create a mock streaming event."""
    event = MagicMock()
    event.type = event_type

    for key, value in kwargs.items():
        setattr(event, key, value)

    # Ensure missing attrs return None
    for attr in ("delta", "content_block", "index", "usage"):
        if attr not in kwargs:
            setattr(event, attr, None if attr != "index" else 0)

    return event


def _make_mock_stream(events, backend):
    """Set up the backend's client.messages.stream to yield events.

    Returns the mock stream context manager.
    """
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=mock_stream)
    mock_stream.__exit__ = MagicMock(return_value=False)
    mock_stream.__iter__ = MagicMock(return_value=iter(events))

    # Mock get_final_message with proper usage
    final_msg = MagicMock()
    final_msg.usage = _make_usage()
    mock_stream.get_final_message.return_value = final_msg

    backend.client.messages.stream.return_value = mock_stream
    return mock_stream
