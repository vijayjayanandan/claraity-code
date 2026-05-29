"""Tests for src.llm.openai_native_backend -- OpenAINativeBackend.

Covers the contract violations found in code review:
  1. generate_provider_deltas_async() didn't exist (wrong method name)
  2. stream_id was required instead of optional
  3. Responses API never emitted tool-call first delta with id/name
  4. LLMFailureHandler was never called
  5. CacheTracker never recorded events
  6. **kwargs overrides were ignored
  7. tool_choice was dropped on Responses API path

All tests mock the OpenAI client -- no real API calls.
"""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Prime import chain (see conftest.py)
import src.core  # noqa: F401

from src.llm.base import LLMBackendType, LLMConfig, ProviderDelta, ToolCallDelta, ToolDefinition


# ===========================================================================
# Helpers
# ===========================================================================

def _make_config(
    model_name: str = "gpt-4o",
    reasoning_effort: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    top_p: float = 0.95,
) -> LLMConfig:
    """Build a minimal LLMConfig for OpenAINativeBackend tests."""
    return LLMConfig(
        backend_type=LLMBackendType.OPENAI_NATIVE,
        model_name=model_name,
        base_url="https://api.openai.com/v1",
        context_window=131072,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        reasoning_effort=reasoning_effort,
    )


def _make_backend(config: LLMConfig, mock_sync: MagicMock, mock_async: MagicMock):
    """Instantiate OpenAINativeBackend with pre-built mock clients."""
    with patch("src.llm.openai_native_backend.OpenAI", return_value=mock_sync), \
         patch("src.llm.openai_native_backend.AsyncOpenAI", return_value=mock_async):
        from src.llm.openai_native_backend import OpenAINativeBackend
        backend = OpenAINativeBackend(config, api_key="test-key")
    # Replace clients with the mocks directly (constructor already ran)
    backend.client = mock_sync
    backend.async_client = mock_async
    return backend


def _make_chat_response(
    content: str = "Hello",
    model: str = "gpt-4o",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    tool_calls=None,
) -> MagicMock:
    """Build a mock chat completions response object.

    All numeric attributes are set to real integers so that CacheTracker.record()
    can call max() on them without TypeError.
    """
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    usage.prompt_tokens_details = None
    # Anthropic-style cache fields -- must be integers for CacheTracker.record()
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0

    response = MagicMock()
    response.choices = [choice]
    response.model = model
    response.usage = usage
    # id and created are accessed in _normalise_chat_response raw_response dict
    response.id = "chatcmpl-test"
    response.created = 0
    response.model_dump = MagicMock(return_value={})
    return response


def _make_responses_api_response(
    text: str = "Hello",
    model: str = "o1-pro",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> MagicMock:
    """Build a mock Responses API response object."""
    text_block = MagicMock()
    text_block.type = "output_text"
    text_block.text = text

    content_item = MagicMock()
    content_item.type = "message"
    content_item.content = [text_block]

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.total_tokens = input_tokens + output_tokens
    usage.prompt_tokens = input_tokens
    usage.prompt_tokens_details = None
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    usage.output_tokens_details = None

    response = MagicMock()
    response.output = [content_item]
    response.model = model
    response.usage = usage
    response.finish_reason = "stop"
    return response


def _collect_async_gen(coro_or_agen):
    """Collect all items from an async generator into a list."""
    async def _collect():
        results = []
        async for item in coro_or_agen:
            results.append(item)
        return results
    return asyncio.run(_collect())


class _FakeAsyncStreamCtx:
    def __init__(self, events):
        self._events = list(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    # For synchronous context manager usage in generate_stream
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        return self

    def __next__(self):
        if not self._events:
            raise StopIteration
        return self._events.pop(0)



def _make_text_chunk(text: str, finish_reason=None):
    """Build a Responses API text delta event."""
    return SimpleNamespace(
        type="response.output_text.delta",
        delta=text
    )


def _make_finish_chunk(finish_reason: str = "stop"):
    """Build a Responses API completion event."""
    return SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=8,
                total_tokens=28,
                output_tokens_details=None
            )
        )
    )


def _make_tool_call_chunk(index: int, tc_id: str | None, name: str | None, args_delta: str):
    """Build a Responses API tool call start/delta event."""
    if tc_id or name:
        return SimpleNamespace(
            type="response.function_call_arguments.start",
            output_index=index,
            call_id=tc_id,
            name=name
        )
    return SimpleNamespace(
        type="response.function_call_arguments.delta",
        output_index=index,
        delta=args_delta
    )


def _make_usage_chunk(prompt_tokens: int = 20, completion_tokens: int = 8):
    """Build a Responses API completion event with specific usage."""
    usage = SimpleNamespace(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        output_tokens_details=None,
    )
    return SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def mock_clients():
    """Return (mock_sync_client, mock_async_client) pair."""
    return MagicMock(), MagicMock()


@pytest.fixture
def gpt4o_backend(mock_clients):
    """OpenAINativeBackend configured for gpt-4o (standard model)."""
    config = _make_config(model_name="gpt-4o")
    sync_client, async_client = mock_clients
    return _make_backend(config, sync_client, async_client)


@pytest.fixture
def o3mini_backend(mock_clients):
    """OpenAINativeBackend configured for o3-mini (o-series model)."""
    config = _make_config(model_name="o3-mini")
    sync_client, async_client = mock_clients
    return _make_backend(config, sync_client, async_client)


@pytest.fixture
def o3mini_with_effort_backend(mock_clients):
    """OpenAINativeBackend for o3-mini with reasoning_effort='high'."""
    config = _make_config(model_name="o3-mini", reasoning_effort="high")
    sync_client, async_client = mock_clients
    return _make_backend(config, sync_client, async_client)


@pytest.fixture
def o1pro_backend(mock_clients):
    """OpenAINativeBackend configured for o1-pro (Responses API model)."""
    config = _make_config(model_name="o1-pro")
    sync_client, async_client = mock_clients
    return _make_backend(config, sync_client, async_client)


@pytest.fixture
def sample_messages():
    return [{"role": "user", "content": "Hello"}]


@pytest.fixture
def sample_tools():
    return [
        ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path"}},
                "required": ["path"],
            },
        )
    ]


# ===========================================================================
# Class 1: TestMethodSurface
# Verify the contract -- required methods exist with correct signatures.
# ===========================================================================

class TestMethodSurface:
    """Verify the public API surface of OpenAINativeBackend."""

    def test_has_generate_provider_deltas_async(self, gpt4o_backend):
        """generate_provider_deltas_async must exist and be an async generator function."""
        assert hasattr(gpt4o_backend, "generate_provider_deltas_async"), (
            "generate_provider_deltas_async() is missing -- "
            "the old name was async_generate_with_tools_stream which is wrong"
        )
        method = gpt4o_backend.generate_provider_deltas_async
        assert inspect.isasyncgenfunction(method) or asyncio.iscoroutinefunction(method), (
            "generate_provider_deltas_async must be an async generator or coroutine"
        )

    def test_generate_provider_deltas_async_stream_id_optional(
        self, gpt4o_backend, sample_messages, sample_tools, mock_clients
    ):
        """generate_provider_deltas_async must accept calls WITHOUT stream_id."""
        _, async_client = mock_clients
        chunks = [_make_text_chunk("Hi"), _make_finish_chunk()]
        # .create(stream=True) is awaitable -- use AsyncMock returning _FakeAsyncStreamCtx
        async_client.responses.stream = MagicMock(
            return_value=_FakeAsyncStreamCtx(chunks)
        )

        # Must not raise TypeError about missing stream_id
        try:
            deltas = _collect_async_gen(
                gpt4o_backend.generate_provider_deltas_async(
                    sample_messages,
                    tools=sample_tools,
                    # stream_id intentionally omitted
                )
            )
        except TypeError as exc:
            pytest.fail(
                f"generate_provider_deltas_async raised TypeError when stream_id omitted: {exc}"
            )

        assert len(deltas) > 0, "Should yield at least one ProviderDelta"

    def test_has_generate_with_tools(self, gpt4o_backend):
        """generate_with_tools must exist."""
        assert hasattr(gpt4o_backend, "generate_with_tools"), (
            "generate_with_tools() is missing"
        )

    def test_has_log_cache_summary(self, gpt4o_backend):
        """log_cache_summary must exist."""
        assert hasattr(gpt4o_backend, "log_cache_summary"), (
            "log_cache_summary() is missing"
        )

    def test_has_list_models(self, gpt4o_backend):
        """list_models must exist."""
        assert hasattr(gpt4o_backend, "list_models")

    def test_has_count_tokens(self, gpt4o_backend):
        """count_tokens must exist."""
        assert hasattr(gpt4o_backend, "count_tokens")

    def test_has_is_available(self, gpt4o_backend):
        """is_available must exist."""
        assert hasattr(gpt4o_backend, "is_available")


# ===========================================================================
# Class 2: TestOSeriesParamMapping
# ===========================================================================

class TestOSeriesParamMapping:
    """Tests for _build_chat_params() with o-series vs standard models."""

    def test_o_series_drops_temperature(self, o3mini_backend, sample_messages):
        """o3-mini params must NOT include temperature or top_p."""
        mock_response = _make_responses_api_response(model="o3-mini")
        o3mini_backend.client.responses.create.return_value = mock_response

        o3mini_backend.generate(sample_messages)

        call_kwargs = o3mini_backend.client.responses.create.call_args.kwargs
        assert "temperature" not in call_kwargs, (
            "o-series models reject temperature -- must be omitted"
        )
        assert "top_p" not in call_kwargs, (
            "o-series models reject top_p -- must be omitted"
        )

    def test_o_series_uses_max_output_tokens(self, o3mini_backend, sample_messages):
        """o3-mini params should use max_output_tokens, not max_tokens."""
        mock_response = _make_responses_api_response(model="o3-mini")
        o3mini_backend.client.responses.create.return_value = mock_response

        o3mini_backend.generate(sample_messages)

        call_kwargs = o3mini_backend.client.responses.create.call_args.kwargs
        assert "max_output_tokens" in call_kwargs, (
            "o-series models require max_output_tokens"
        )
        assert "max_tokens" not in call_kwargs, (
            "max_tokens must be absent for o-series models"
        )
        assert call_kwargs["max_output_tokens"] == 4096

    def test_o_series_maps_reasoning_effort(self, o3mini_with_effort_backend, sample_messages):
        """reasoning_effort='high' should produce params['reasoning']={'effort': 'high'}.

        summary is absent by default -- it is opt-in via reasoning_summary=True.
        """
        mock_response = _make_responses_api_response(model="o3-mini")
        o3mini_with_effort_backend.client.responses.create.return_value = mock_response

        o3mini_with_effort_backend.generate(sample_messages)

        call_kwargs = o3mini_with_effort_backend.client.responses.create.call_args.kwargs
        assert "reasoning" in call_kwargs
        assert call_kwargs["reasoning"]["effort"] == "high"
        assert "summary" not in call_kwargs["reasoning"], (
            "summary must be absent by default -- opt-in via reasoning_summary=True"
        )

    def test_o_series_no_reasoning_key_when_effort_none(self, o3mini_backend, sample_messages):
        """When reasoning_effort is None, both 'reasoning' and 'reasoning_effort' must be absent."""
        mock_response = _make_responses_api_response(model="o3-mini")
        o3mini_backend.client.responses.create.return_value = mock_response

        o3mini_backend.generate(sample_messages)

        call_kwargs = o3mini_backend.client.responses.create.call_args.kwargs
        assert "reasoning" not in call_kwargs, (
            "reasoning dict must be absent when reasoning_effort is None"
        )
        assert "reasoning_effort" not in call_kwargs, (
            "reasoning_effort must be absent when reasoning_effort is None"
        )

    def test_standard_model_keeps_temperature(self, gpt4o_backend, sample_messages):
        """gpt-4o (sampling-capable) params should include temperature and top_p."""
        mock_response = _make_responses_api_response(model="gpt-4o")
        gpt4o_backend.client.responses.create.return_value = mock_response

        gpt4o_backend.generate(sample_messages)

        call_kwargs = gpt4o_backend.client.responses.create.call_args.kwargs
        assert "temperature" in call_kwargs, "temperature must be present for gpt-4o"
        assert "top_p" in call_kwargs, "top_p must be present for gpt-4o"
        assert call_kwargs["temperature"] == pytest.approx(0.2)
        assert call_kwargs["top_p"] == pytest.approx(0.95)

    def test_gpt5_model_omits_sampling_params(self, mock_clients, sample_messages):
        """gpt-5.x must NOT receive temperature or top_p (fail-safe default)."""
        config = _make_config(model_name="gpt-5.4-mini")
        sync_client, async_client = mock_clients
        backend = _make_backend(config, sync_client, async_client)

        mock_response = _make_responses_api_response(model="gpt-5.4-mini")
        backend.client.responses.create.return_value = mock_response

        backend.generate(sample_messages)

        call_kwargs = backend.client.responses.create.call_args.kwargs
        assert "temperature" not in call_kwargs, (
            "gpt-5.x must NOT receive temperature -- confirmed unsupported by API"
        )
        assert "top_p" not in call_kwargs, (
            "gpt-5.x must NOT receive top_p -- confirmed unsupported by API"
        )

    def test_unknown_model_omits_sampling_params(self, mock_clients, sample_messages):
        """Unknown model families must omit sampling params (fail-safe default)."""
        config = _make_config(model_name="gpt-7-turbo")
        sync_client, async_client = mock_clients
        backend = _make_backend(config, sync_client, async_client)

        mock_response = _make_responses_api_response(model="gpt-7-turbo")
        backend.client.responses.create.return_value = mock_response

        backend.generate(sample_messages)

        call_kwargs = backend.client.responses.create.call_args.kwargs
        assert "temperature" not in call_kwargs, (
            "Unknown model must omit temperature -- fail-safe not fail-open"
        )
        assert "top_p" not in call_kwargs, (
            "Unknown model must omit top_p -- fail-safe not fail-open"
        )

    def test_standard_model_uses_max_output_tokens(self, gpt4o_backend, sample_messages):
        """gpt-4o params must use max_output_tokens, not max_tokens.

        max_output_tokens is used for all models in the native backend.
        max_tokens is the legacy alias that newer models (gpt-5.x+) reject.
        """
        mock_response = _make_responses_api_response(model="gpt-4o")
        gpt4o_backend.client.responses.create.return_value = mock_response

        gpt4o_backend.generate(sample_messages)

        call_kwargs = gpt4o_backend.client.responses.create.call_args.kwargs
        assert "max_output_tokens" in call_kwargs, (
            "All models in native backend must use max_output_tokens"
        )
        assert "max_tokens" not in call_kwargs, (
            "max_tokens is the legacy alias -- must not be sent by native backend"
        )
        assert call_kwargs["max_output_tokens"] == 4096


# ===========================================================================
# Class 3: TestProviderDeltaContract
# Critical tests that catch ProviderDelta shape violations.
# ===========================================================================

class TestProviderDeltaContract:
    """Tests for generate_provider_deltas_async() ProviderDelta shape."""

    def _setup_stream(self, backend, chunks):
        """Wire up async_client.responses.create to yield raw chunks.

        .create(stream=True) is awaitable -- use AsyncMock returning _FakeAsyncStreamCtx.
        The backend iterates the result directly as 'async for chunk in stream'.
        """
        backend.async_client.responses.stream = MagicMock(
            return_value=_FakeAsyncStreamCtx(chunks)
        )

    def test_text_delta_has_stream_id(self, gpt4o_backend, sample_messages, sample_tools):
        """Text delta must include a non-empty stream_id."""
        chunks = [_make_text_chunk("Hello"), _make_finish_chunk()]
        self._setup_stream(gpt4o_backend, chunks)

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-abc",
            )
        )

        text_deltas = [d for d in deltas if d.text_delta]
        assert len(text_deltas) >= 1, "Expected at least one text delta"
        for d in text_deltas:
            assert d.stream_id, "stream_id must be a non-empty string"
            assert d.stream_id == "sid-abc"

    def test_text_delta_has_text_content(self, gpt4o_backend, sample_messages, sample_tools):
        """Text delta must have text_delta field set to the chunk content."""
        chunks = [_make_text_chunk("world"), _make_finish_chunk()]
        self._setup_stream(gpt4o_backend, chunks)

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-text",
            )
        )

        text_deltas = [d for d in deltas if d.text_delta]
        assert len(text_deltas) >= 1
        assert text_deltas[0].text_delta == "world"

    def test_tool_call_first_delta_has_id_and_name(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """First delta for a tool call must have id and name fields set (not None).

        This was the critical bug: the first chunk carried id/name from the provider
        but the backend emitted them as None in the ProviderDelta.
        """
        chunks = [
            _make_tool_call_chunk(index=0, tc_id="call_abc123", name="read_file", args_delta=""),
            _make_tool_call_chunk(index=0, tc_id=None, name=None, args_delta='{"path":'),
            _make_tool_call_chunk(index=0, tc_id=None, name=None, args_delta='"x.py"}'),
            _make_finish_chunk("tool_calls"),
        ]
        self._setup_stream(gpt4o_backend, chunks)

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-tc",
            )
        )

        tc_deltas = [d for d in deltas if d.tool_call_delta]
        assert len(tc_deltas) >= 1, "Expected at least one tool-call delta"

        # The first tool-call delta must carry id and name
        first_tc = tc_deltas[0]
        assert first_tc.tool_call_delta.id is not None, (
            "First tool-call delta must have id set -- was None (the bug)"
        )
        assert first_tc.tool_call_delta.name is not None, (
            "First tool-call delta must have name set -- was None (the bug)"
        )
        assert first_tc.tool_call_delta.name == "read_file"

    def test_tool_call_argument_delta_has_arguments(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """Subsequent tool-call deltas must carry arguments_delta."""
        chunks = [
            _make_tool_call_chunk(index=0, tc_id="call_xyz", name="read_file", args_delta=""),
            _make_tool_call_chunk(index=0, tc_id=None, name=None, args_delta='{"path":"a.py"}'),
            _make_finish_chunk("tool_calls"),
        ]
        self._setup_stream(gpt4o_backend, chunks)

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-args",
            )
        )

        tc_deltas = [d for d in deltas if d.tool_call_delta]
        # Find a delta that carries arguments
        arg_deltas = [d for d in tc_deltas if d.tool_call_delta.arguments_delta]
        assert len(arg_deltas) >= 1, "Expected at least one delta with arguments_delta"
        assert '{"path":"a.py"}' in arg_deltas[0].tool_call_delta.arguments_delta

    def test_finish_delta_emitted(self, gpt4o_backend, sample_messages, sample_tools):
        """A finish delta with finish_reason must be emitted at stream end."""
        chunks = [_make_text_chunk("Done"), _make_finish_chunk("stop")]
        self._setup_stream(gpt4o_backend, chunks)

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-finish",
            )
        )

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert len(finish_deltas) >= 1, "Expected at least one finish delta"
        assert finish_deltas[-1].finish_reason in ("stop", "tool_calls", "length"), (
            f"Unexpected finish_reason: {finish_deltas[-1].finish_reason}"
        )

    def test_stream_id_auto_generated_when_none(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """If stream_id is not passed, all deltas must still have a non-empty stream_id."""
        chunks = [_make_text_chunk("Hi"), _make_finish_chunk()]
        self._setup_stream(gpt4o_backend, chunks)

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                # stream_id intentionally omitted
            )
        )

        assert len(deltas) > 0
        for d in deltas:
            assert d.stream_id, (
                f"stream_id must be auto-generated when not provided, got: {d.stream_id!r}"
            )
        # All deltas in the same stream must share the same stream_id
        stream_ids = {d.stream_id for d in deltas}
        assert len(stream_ids) == 1, (
            f"All deltas must share the same auto-generated stream_id, got: {stream_ids}"
        )

    def test_kwargs_temperature_applied(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """Passing temperature=0.5 via kwargs must override the config default."""
        chunks = [_make_text_chunk("Hi"), _make_finish_chunk()]
        self._setup_stream(gpt4o_backend, chunks)

        _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-temp",
                temperature=0.5,
            )
        )

        # Verify .stream was called with temperature=0.5
        call_kwargs = gpt4o_backend.async_client.responses.stream.call_args.kwargs
        assert "temperature" in call_kwargs, "temperature kwarg must be forwarded to API call"
        assert call_kwargs["temperature"] == pytest.approx(0.5), (
            f"Expected temperature=0.5 but got {call_kwargs['temperature']}"
        )

    def test_kwargs_max_tokens_applied(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """Passing max_tokens=100 via kwargs must be reflected in the API call params."""
        chunks = [_make_text_chunk("Hi"), _make_finish_chunk()]
        self._setup_stream(gpt4o_backend, chunks)

        _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-maxtok",
                max_tokens=100,
            )
        )

        call_kwargs = gpt4o_backend.async_client.responses.stream.call_args.kwargs
        # The kwarg may appear as max_tokens or max_output_tokens depending on model
        token_limit = call_kwargs.get("max_tokens") or call_kwargs.get("max_output_tokens")
        assert token_limit == 100, (
            f"Expected max_tokens=100 from kwargs override, got {token_limit}"
        )


# ===========================================================================
# Class 4: TestResponsesAPIContract
# Drive the Responses API path (model="o1-pro").
# ===========================================================================

class TestResponsesAPIContract:
    """Tests for the Responses API streaming path (o1-pro and similar)."""

    def _setup_responses_stream(self, backend, events):
        """Wire up async_client.responses.stream to yield events.

        .stream() is NOT awaitable -- use MagicMock, not AsyncMock.
        """
        backend.async_client.responses.stream = MagicMock(
            return_value=_FakeAsyncStreamCtx(events)
        )

    def _make_responses_text_event(self, text: str):
        return SimpleNamespace(type="response.output_text.delta", delta=text)

    def _make_responses_function_call_start_event(self, output_index: int, call_id: str, name: str):
        """First event for a function call -- carries id and name."""
        return SimpleNamespace(
            type="response.function_call_arguments.start",
            output_index=output_index,
            call_id=call_id,
            name=name,
        )

    def _make_responses_function_call_delta_event(self, output_index: int, delta: str):
        return SimpleNamespace(
            type="response.function_call_arguments.delta",
            output_index=output_index,
            delta=delta,
        )

    def _make_responses_completed_event(self):
        return SimpleNamespace(type="response.completed")

    def test_responses_api_routing(self, o1pro_backend, sample_messages, sample_tools):
        """o1-pro generate_provider_deltas_async() must call responses.stream, not chat.completions."""
        events = [
            self._make_responses_text_event("Hello"),
            self._make_responses_completed_event(),
        ]
        self._setup_responses_stream(o1pro_backend, events)

        _collect_async_gen(
            o1pro_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-resp",
            )
        )

        o1pro_backend.async_client.responses.stream.assert_called_once()
        o1pro_backend.async_client.responses.create.assert_not_called()

    def test_responses_api_tool_call_first_delta_has_id_and_name(
        self, o1pro_backend, sample_messages, sample_tools
    ):
        """Responses API: first tool-call delta must carry id and name.

        The bug: _stream_responses_api emitted ToolCallDelta with no id/name
        on the arguments.delta event, and never emitted a start event at all.
        """
        events = [
            self._make_responses_function_call_start_event(
                output_index=0, call_id="fc_abc", name="read_file"
            ),
            self._make_responses_function_call_delta_event(
                output_index=0, delta='{"path":"x.py"}'
            ),
            self._make_responses_completed_event(),
        ]
        self._setup_responses_stream(o1pro_backend, events)

        deltas = _collect_async_gen(
            o1pro_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-resp-tc",
            )
        )

        tc_deltas = [d for d in deltas if d.tool_call_delta]
        assert len(tc_deltas) >= 1, "Expected at least one tool-call delta from Responses API"

        # The first tool-call delta must carry id and name
        first_tc = tc_deltas[0]
        assert first_tc.tool_call_delta.id is not None, (
            "Responses API first tool-call delta must have id set"
        )
        assert first_tc.tool_call_delta.name is not None, (
            "Responses API first tool-call delta must have name set"
        )
        assert first_tc.tool_call_delta.name == "read_file"

    def test_responses_api_tool_choice_passed(
        self, o1pro_backend, sample_messages, sample_tools
    ):
        """tool_choice must be included in the Responses API call params.

        The bug: _build_responses_params() never added tool_choice to params.
        """
        events = [self._make_responses_completed_event()]
        self._setup_responses_stream(o1pro_backend, events)

        _collect_async_gen(
            o1pro_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-tc-choice",
                tool_choice="required",
            )
        )

        call_kwargs = o1pro_backend.async_client.responses.stream.call_args.kwargs
        assert "tool_choice" in call_kwargs, (
            "tool_choice must be forwarded to Responses API -- was dropped (the bug)"
        )
        assert call_kwargs["tool_choice"] == "required"


# ===========================================================================
# Class 5: TestRetryAndCaching
# ===========================================================================

class TestRetryAndCaching:
    """Tests for LLMFailureHandler and CacheTracker integration."""

    def test_failure_handler_used_in_generate(self, gpt4o_backend, sample_messages):
        """LLMFailureHandler.execute_with_retry must be called during generate().

        The bug: generate() called client.responses.create directly,
        bypassing the failure handler entirely.
        """
        mock_response = _make_responses_api_response(model="gpt-4o")
        gpt4o_backend.client.responses.create.return_value = mock_response

        with patch.object(
            gpt4o_backend.failure_handler,
            "execute_with_retry",
            wraps=gpt4o_backend.failure_handler.execute_with_retry,
        ) as mock_retry:
            gpt4o_backend.generate(sample_messages)

        mock_retry.assert_called_once(), (
            "failure_handler.execute_with_retry must be called in generate() -- was never called (the bug)"
        )

    def test_usage_dict_includes_reasoning_tokens(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """usage_dict emitted in finish delta must include reasoning_tokens key.

        Even when completion_tokens_details is absent (most models), the key
        must be present with value None so downstream consumers can rely on it.
        """
        usage_chunk = _make_usage_chunk(prompt_tokens=100, completion_tokens=40)
        chunks = [_make_text_chunk("Answer"), _make_finish_chunk(), usage_chunk]
        gpt4o_backend.async_client.responses.stream = MagicMock(
            return_value=_FakeAsyncStreamCtx(chunks)
        )

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-reasoning",
            )
        )

        finish_delta = next((d for d in deltas if d.finish_reason), None)
        assert finish_delta is not None, "No finish delta emitted"
        assert finish_delta.usage is not None, "Finish delta has no usage"
        assert "reasoning_tokens" in finish_delta.usage, (
            "reasoning_tokens key missing from usage_dict -- downstream ThinkingEnd will have no token count"
        )

    def test_usage_dict_reasoning_tokens_value_when_present(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """When completion_tokens_details.reasoning_tokens is set, it must be forwarded."""
        usage_chunk = _make_usage_chunk(prompt_tokens=100, completion_tokens=250)
        # Attach output_tokens_details with reasoning_tokens (Responses API field name)
        from types import SimpleNamespace as SN
        usage_chunk.response.usage.output_tokens_details = SN(reasoning_tokens=180)
        # Only one completion event -- the usage_chunk carries the final usage with reasoning_tokens
        chunks = [_make_text_chunk("Answer"), usage_chunk]
        gpt4o_backend.async_client.responses.stream = MagicMock(
            return_value=_FakeAsyncStreamCtx(chunks)
        )

        deltas = _collect_async_gen(
            gpt4o_backend.generate_provider_deltas_async(
                sample_messages,
                tools=sample_tools,
                stream_id="sid-reasoning-val",
            )
        )

        finish_delta = next((d for d in deltas if d.finish_reason), None)
        assert finish_delta is not None
        assert finish_delta.usage["reasoning_tokens"] == 180

    def test_cache_tracker_records_usage(
        self, gpt4o_backend, sample_messages, sample_tools
    ):
        """After a streaming call, CacheTracker.record must be called with usage data.

        The bug: generate_provider_deltas_async() never called cache_tracker.record().
        """
        usage_chunk = _make_usage_chunk(prompt_tokens=50, completion_tokens=10)
        chunks = [_make_text_chunk("Hi"), _make_finish_chunk(), usage_chunk]
        # .create(stream=True) is awaitable -- use AsyncMock returning _FakeAsyncStreamCtx
        gpt4o_backend.async_client.responses.stream = MagicMock(
            return_value=_FakeAsyncStreamCtx(chunks)
        )

        with patch.object(
            gpt4o_backend.cache_tracker,
            "record",
            wraps=gpt4o_backend.cache_tracker.record,
        ) as mock_record:
            _collect_async_gen(
                gpt4o_backend.generate_provider_deltas_async(
                    sample_messages,
                    tools=sample_tools,
                    stream_id="sid-cache",
                )
            )

        mock_record.assert_called(), (
            "cache_tracker.record() must be called with usage data -- was never called (the bug)"
        )

    def test_log_cache_summary_callable(self, gpt4o_backend):
        """log_cache_summary() must exist and be callable without error."""
        assert hasattr(gpt4o_backend, "log_cache_summary"), (
            "log_cache_summary() method is missing"
        )
        # Must not raise
        try:
            gpt4o_backend.log_cache_summary()
        except Exception as exc:
            pytest.fail(f"log_cache_summary() raised unexpectedly: {exc}")


# ===========================================================================
# Class 6: TestModelClassification
# Direct unit tests for _is_o_series() and _supports_sampling_params().
# These guard against prefix typos and logic inversions in the capability map.
# ===========================================================================


class TestModelClassification:
    """Direct unit tests for model classification helper functions."""

    # ------------------------------------------------------------------
    # _is_o_series
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("model", ["o1", "o1-mini", "o1-pro", "o3", "o3-mini", "o4", "o4-mini"])
    def test_o_series_detected(self, model: str):
        """All o-series model names must be classified as o-series."""
        from src.llm.openai_native_backend import _is_o_series
        assert _is_o_series(model), f"{model!r} must be detected as o-series"

    @pytest.mark.parametrize("model", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-5.4-mini", "chatgpt-4o-latest"])
    def test_non_o_series_not_detected(self, model: str):
        """GPT and chatgpt models must NOT be classified as o-series."""
        from src.llm.openai_native_backend import _is_o_series
        assert not _is_o_series(model), f"{model!r} must NOT be detected as o-series"

    def test_o_series_case_insensitive(self):
        """_is_o_series must be case-insensitive."""
        from src.llm.openai_native_backend import _is_o_series
        assert _is_o_series("O4-mini")
        assert _is_o_series("O1-PRO")

    # ------------------------------------------------------------------
    # _supports_sampling_params
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("model", ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "gpt-3.5-turbo", "chatgpt-4o-latest"])
    def test_sampling_capable_models(self, model: str):
        """GPT-4.x, GPT-3.5, and chatgpt- models must support sampling params."""
        from src.llm.openai_native_backend import _supports_sampling_params
        assert _supports_sampling_params(model), f"{model!r} must support sampling params"

    @pytest.mark.parametrize("model", ["o1", "o3", "o4-mini", "gpt-5.4-mini", "gpt-5.4-2026-03-05"])
    def test_non_sampling_capable_models(self, model: str):
        """o-series and gpt-5.x must NOT support sampling params (fail-safe)."""
        from src.llm.openai_native_backend import _supports_sampling_params
        assert not _supports_sampling_params(model), f"{model!r} must NOT support sampling params"

    def test_unknown_model_fails_safe(self):
        """Unknown model families must default to NOT supporting sampling params."""
        from src.llm.openai_native_backend import _supports_sampling_params
        assert not _supports_sampling_params("gpt-7-turbo"), (
            "Unknown model must fail-safe: omit sampling params rather than risk a 400"
        )

    def test_sampling_params_case_insensitive(self):
        """_supports_sampling_params must be case-insensitive."""
        from src.llm.openai_native_backend import _supports_sampling_params
        assert _supports_sampling_params("GPT-4o")
        assert _supports_sampling_params("GPT-3.5-TURBO")

