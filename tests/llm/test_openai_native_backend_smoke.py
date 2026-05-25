"""HTTP-level smoke tests for OpenAINativeBackend using respx.

These tests let the real OpenAI SDK run -- including its parameter validation --
but intercept at the HTTP layer so no request reaches the internet.

WHY THESE TESTS EXIST
---------------------
Previous mock-based tests replaced the SDK client object entirely, so the SDK's
own parameter validation never ran.  This caused a bug where:

  1. _build_chat_params() returned a dict containing stream=True and
     stream_options={...}.
  2. generate_provider_deltas_async() passed that dict directly to
     .stream(**params).
  3. The real SDK raises TypeError: "got an unexpected keyword argument 'stream'"
     because .stream() does not accept stream= as a kwarg.
  4. The mock-based tests silently swallowed the TypeError because AsyncMock
     accepted any kwargs.

respx intercepts httpx so the real SDK runs and validates params first.

HOW respx WORKS WITH THE OPENAI SDK
------------------------------------
AsyncOpenAI uses httpx.AsyncClient internally.  respx patches all httpx clients
globally within a respx.mock context, so the real SDK code runs (including param
validation) but the HTTP request is intercepted before it reaches the network.

The SDK's .stream() context manager:
  - Is NOT awaitable (do NOT use "await" with it)
  - Sends stream=true in the HTTP request body automatically
  - Does NOT accept stream= or stream_options= as kwargs
  - Does NOT accept reasoning={...} as a kwarg; use reasoning_effort= instead

SSE RESPONSE FORMAT
-------------------
Chat completions streaming uses Server-Sent Events (SSE).  The SDK parses the
SSE body and yields typed event objects.  The backend filters for events with
.type == 'chunk' and reads .chunk for the raw SSE data.
"""

import json

import httpx
import pytest
import respx

# Prime the import chain to avoid circular import errors (see tests/llm/conftest.py)
import src.core  # noqa: F401

from src.llm.base import LLMBackendType, LLMConfig, ToolDefinition
from src.llm.openai_native_backend import OpenAINativeBackend

# ---------------------------------------------------------------------------
# SSE body constants
# ---------------------------------------------------------------------------

# Minimal valid SSE body for chat completions streaming.
# The SDK parses this and yields ChunkEvent objects.
_CHAT_SSE_TEXT = (
    'data: {"id":"c1","object":"chat.completion.chunk",'
    '"choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
    'data: {"id":"c1","object":"chat.completion.chunk",'
    '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,'
    '"prompt_tokens_details":{"cached_tokens":0}}}\n\n'
    "data: [DONE]\n\n"
)

# Minimal valid SSE body for Responses API streaming.
# The SDK requires response.created as the first event, then output item events,
# then response.completed.  The snapshot accumulator validates this ordering.
_RESPONSES_SSE_TEXT = (
    'data: {"type":"response.created","sequence_number":0,"response":{'
    '"id":"resp_001","object":"response","created_at":0,"status":"in_progress",'
    '"model":"o1-pro","output":[],"usage":null,"error":null,'
    '"incomplete_details":null,"instructions":null,"max_output_tokens":null,'
    '"metadata":{},"parallel_tool_calls":true,"temperature":null,'
    '"tool_choice":"auto","tools":[],"top_p":null,"truncation":"disabled",'
    '"background":false,"previous_response_id":null,"reasoning":null,'
    '"service_tier":"default","store":false,'
    '"text":{"format":{"type":"text"}},"voice":null}}\n\n'
    'data: {"type":"response.output_item.added","sequence_number":1,'
    '"output_index":0,"item":{"id":"msg_001","type":"message",'
    '"status":"in_progress","role":"assistant","content":[]}}\n\n'
    'data: {"type":"response.content_part.added","sequence_number":2,'
    '"item_id":"msg_001","output_index":0,"content_index":0,'
    '"part":{"type":"output_text","text":"","annotations":[],"logprobs":null}}\n\n'
    'data: {"type":"response.output_text.delta","sequence_number":3,'
    '"item_id":"msg_001","output_index":0,"content_index":0,'
    '"delta":"Hello","logprobs":null}\n\n'
    'data: {"type":"response.output_text.done","sequence_number":4,'
    '"item_id":"msg_001","output_index":0,"content_index":0,'
    '"text":"Hello","logprobs":null}\n\n'
    'data: {"type":"response.output_item.done","sequence_number":5,'
    '"output_index":0,"item":{"id":"msg_001","type":"message",'
    '"status":"completed","role":"assistant","content":[{"type":"output_text",'
    '"text":"Hello","annotations":[],"logprobs":null}]}}\n\n'
    'data: {"type":"response.completed","sequence_number":6,"response":{'
    '"id":"resp_001","object":"response","created_at":0,"status":"completed",'
    '"model":"o1-pro","output":[{"id":"msg_001","type":"message",'
    '"status":"completed","role":"assistant","content":[{"type":"output_text",'
    '"text":"Hello","annotations":[],"logprobs":null}]}],'
    '"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15,'
    '"input_tokens_details":{"cached_tokens":0},'
    '"output_tokens_details":{"reasoning_tokens":0}},'
    '"error":null,"incomplete_details":null,"instructions":null,'
    '"max_output_tokens":null,"metadata":{},"parallel_tool_calls":true,'
    '"temperature":null,"tool_choice":"auto","tools":[],"top_p":null,'
    '"truncation":"disabled","background":false,"previous_response_id":null,'
    '"reasoning":null,"service_tier":"default","store":false,'
    '"text":{"format":{"type":"text"}},"voice":null}}\n\n'
    "data: [DONE]\n\n"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _make_config(
    model_name: str = "gpt-4o",
    reasoning_effort: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    top_p: float = 0.95,
) -> LLMConfig:
    """Build a minimal LLMConfig for smoke tests."""
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


def _make_backend(model_name: str, reasoning_effort: str | None = None) -> OpenAINativeBackend:
    """Instantiate a real OpenAINativeBackend with a test API key."""
    config = _make_config(model_name=model_name, reasoning_effort=reasoning_effort)
    return OpenAINativeBackend(config, api_key="test-key")


def _chat_response() -> httpx.Response:
    """Return a minimal valid SSE httpx.Response for chat completions."""
    return httpx.Response(
        200,
        content=_CHAT_SSE_TEXT.encode(),
        headers={"content-type": "text/event-stream"},
    )


def _responses_api_response() -> httpx.Response:
    """Return a minimal valid SSE httpx.Response for the Responses API."""
    return httpx.Response(
        200,
        content=_RESPONSES_SSE_TEXT.encode(),
        headers={"content-type": "text/event-stream"},
    )


async def _drain(backend: OpenAINativeBackend, messages: list[dict]) -> list:
    """Consume all ProviderDeltas from generate_provider_deltas_async."""
    deltas = []
    async for delta in backend.generate_provider_deltas_async(messages):
        deltas.append(delta)
    return deltas


_SAMPLE_MESSAGES = [{"role": "user", "content": "Hello"}]

_SAMPLE_TOOL = ToolDefinition(
    name="read_file",
    description="Read a file",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path"}},
        "required": ["path"],
    },
)


# ===========================================================================
# Class 1: TestChatCompletionsWireFormat
# Verify the actual HTTP request body sent by the SDK for chat completions.
# ===========================================================================


class TestChatCompletionsWireFormat:
    """Verify the HTTP wire format for /v1/chat/completions requests.

    These tests intercept at the HTTP layer so the real SDK runs fully,
    including its parameter validation.  Any TypeError from bad kwargs
    (e.g. stream=True passed to .stream()) will surface here as a test
    failure -- unlike mock-based tests that silently accept any kwargs.
    """

    async def test_standard_model_no_stream_kwarg_error(self):
        """generate_provider_deltas_async() must not raise TypeError from stream= kwarg.

        THE BUG THIS CATCHES:
        _build_chat_params() returns stream=True in the params dict.
        If that dict is passed directly to .stream(**params), the SDK raises:
            TypeError: AsyncCompletions.stream() got an unexpected keyword argument 'stream'
        The fix strips 'stream' and 'stream_options' before calling .stream().

        This test would have FAILED with the broken implementation and PASSES
        with the fixed one.
        """
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_CHAT_URL).mock(return_value=_chat_response())
            # Must not raise TypeError -- if it does, the stream=True bug is present
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        assert len(deltas) >= 1, "Expected at least one ProviderDelta"

    async def test_standard_model_hits_chat_completions_endpoint(self):
        """gpt-4o must POST to /v1/chat/completions, not /v1/responses."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            chat_route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            # /v1/responses must NOT be called
            respx.post(_RESPONSES_URL).mock(
                return_value=httpx.Response(500, content=b"should not be called")
            )
            await _drain(backend, _SAMPLE_MESSAGES)

        assert chat_route.called, "gpt-4o must call /v1/chat/completions"
        assert chat_route.call_count == 1

    async def test_standard_model_request_body_has_model(self):
        """Request body must contain the correct model name."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert body.get("model") == "gpt-4o", (
            f"Expected model='gpt-4o' in request body, got: {body.get('model')!r}"
        )

    async def test_standard_model_request_body_has_temperature(self):
        """Standard model request body must include temperature."""
        backend = _make_backend("gpt-4o", )
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "temperature" in body, (
            "Standard model (gpt-4o) request body must include 'temperature'"
        )
        assert body["temperature"] == pytest.approx(0.2)

    async def test_standard_model_request_body_has_max_completion_tokens(self):
        """All native backend models must use max_completion_tokens, not max_tokens.

        max_tokens is the legacy alias that newer models (gpt-5.x+) reject at the API level.
        The native backend always sends max_completion_tokens regardless of model family.
        """
        backend = _make_backend("gpt-4o")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "max_completion_tokens" in body, (
            "Native backend must always send max_completion_tokens (not max_tokens)"
        )
        assert "max_tokens" not in body, (
            "max_tokens must never appear -- it is the legacy alias newer models reject"
        )
        assert body["max_completion_tokens"] == 4096

    async def test_o_series_no_temperature_in_request_body(self):
        """o3-mini request body must NOT contain temperature or top_p.

        o-series models reject temperature/top_p at the API level.
        The backend must omit them for o-series models.
        """
        backend = _make_backend("o3-mini")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "temperature" not in body, (
            "o-series models reject temperature -- must be omitted from request body"
        )
        assert "top_p" not in body, (
            "o-series models reject top_p -- must be omitted from request body"
        )

    async def test_gpt5_no_temperature_in_request_body(self):
        """gpt-5.x request body must NOT contain temperature or top_p.

        This is the test that would have caught the gpt-5.4-mini production bug.
        gpt-5.x is not o-series but also rejects sampling params.
        The fail-safe capability map (_SAMPLING_CAPABLE_PREFIXES) must handle this.
        """
        backend = _make_backend("gpt-5.4-mini")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "temperature" not in body, (
            "gpt-5.x rejects temperature -- fail-safe map must omit it"
        )
        assert "top_p" not in body, (
            "gpt-5.x rejects top_p -- fail-safe map must omit it"
        )

    async def test_unknown_model_no_temperature_in_request_body(self):
        """Unknown model families must also omit temperature/top_p (fail-safe default).

        A model not in _SAMPLING_CAPABLE_PREFIXES must be treated conservatively.
        This prevents future gpt-6 / gpt-7 breakage without code changes.
        """
        backend = _make_backend("gpt-7-turbo")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "temperature" not in body, (
            "Unknown model must omit temperature -- fail-safe not fail-open"
        )
        assert "top_p" not in body, (
            "Unknown model must omit top_p -- fail-safe not fail-open"
        )

    async def test_o_series_uses_max_completion_tokens_in_request_body(self):
        """o3-mini request body must use max_completion_tokens, not max_tokens."""
        backend = _make_backend("o3-mini")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "max_completion_tokens" in body, (
            "o-series models require max_completion_tokens in request body"
        )
        assert "max_tokens" not in body, (
            "max_tokens must be absent for o-series models"
        )
        assert body["max_completion_tokens"] == 4096

    async def test_o_series_reasoning_effort_in_request_body(self):
        """o3-mini with reasoning_effort='high' must send reasoning_effort in request body.

        /v1/chat/completions accepts reasoning_effort as a flat string kwarg.
        The backend passes it directly; the SDK serialises it into the HTTP body.
        NOTE: The Responses API uses reasoning={'effort': ...} (different param shape).
        """
        backend = _make_backend("o3-mini", reasoning_effort="high")
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "reasoning_effort" in body, (
            "reasoning_effort must appear in request body when configured"
        )
        assert body["reasoning_effort"] == "high", (
            f"Expected reasoning_effort='high', got: {body.get('reasoning_effort')!r}"
        )

    async def test_o_series_no_reasoning_effort_when_not_configured(self):
        """o3-mini without reasoning_effort must NOT send reasoning_effort in body."""
        backend = _make_backend("o3-mini")  # no reasoning_effort
        with respx.mock:
            route = respx.post(_CHAT_URL).mock(return_value=_chat_response())
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "reasoning_effort" not in body, (
            "reasoning_effort must be absent when not configured"
        )

    async def test_stream_yields_text_delta(self):
        """generate_provider_deltas_async() must yield a text ProviderDelta."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_CHAT_URL).mock(return_value=_chat_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        text_deltas = [d for d in deltas if d.text_delta]
        assert len(text_deltas) >= 1, "Expected at least one text ProviderDelta"
        assert text_deltas[0].text_delta == "Hello"

    async def test_stream_yields_finish_delta(self):
        """generate_provider_deltas_async() must yield a finish ProviderDelta."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_CHAT_URL).mock(return_value=_chat_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert len(finish_deltas) >= 1, "Expected at least one finish ProviderDelta"
        assert finish_deltas[-1].finish_reason == "stop"

    async def test_stream_all_deltas_have_stream_id(self):
        """All ProviderDeltas must share a non-empty stream_id."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_CHAT_URL).mock(return_value=_chat_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        assert len(deltas) > 0
        stream_ids = {d.stream_id for d in deltas}
        assert len(stream_ids) == 1, (
            f"All deltas must share one stream_id, got multiple: {stream_ids}"
        )
        assert all(d.stream_id for d in deltas), "stream_id must be non-empty"


# ===========================================================================
# Class 2: TestResponsesAPIWireFormat
# Verify the HTTP wire format for /v1/responses requests.
# ===========================================================================


class TestResponsesAPIWireFormat:
    """Verify the HTTP wire format for /v1/responses requests (o1-pro model).

    o1-pro requires the Responses API (/v1/responses) instead of chat completions.
    The backend must route these models correctly and build the right request body.
    """

    async def test_responses_api_model_hits_responses_endpoint(self):
        """o1-pro must POST to /v1/responses, not /v1/chat/completions."""
        backend = _make_backend("o1-pro")
        with respx.mock:
            responses_route = respx.post(_RESPONSES_URL).mock(
                return_value=_responses_api_response()
            )
            # /v1/chat/completions must NOT be called
            respx.post(_CHAT_URL).mock(
                return_value=httpx.Response(500, content=b"should not be called")
            )
            await _drain(backend, _SAMPLE_MESSAGES)

        assert responses_route.called, "o1-pro must call /v1/responses"
        assert responses_route.call_count == 1

    async def test_responses_api_uses_input_not_messages(self):
        """Responses API request body must use 'input' key, not 'messages'.

        The Responses API uses a different schema from chat completions:
        - 'input' instead of 'messages'
        - 'max_output_tokens' instead of 'max_tokens'
        """
        backend = _make_backend("o1-pro")
        with respx.mock:
            route = respx.post(_RESPONSES_URL).mock(
                return_value=_responses_api_response()
            )
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert "input" in body, (
            "Responses API request body must use 'input' key (not 'messages')"
        )
        assert "messages" not in body, (
            "Responses API must NOT use 'messages' key -- that is chat completions format"
        )

    async def test_responses_api_no_stream_kwarg_error(self):
        """o1-pro generate_provider_deltas_async() must not raise TypeError.

        The Responses API path uses .stream() which also does not accept stream=
        as a kwarg.  This test verifies the call succeeds end-to-end.
        """
        backend = _make_backend("o1-pro")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            # Must not raise
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        assert len(deltas) >= 1, "Expected at least one ProviderDelta from Responses API"

    async def test_responses_api_yields_text_delta(self):
        """o1-pro generate_provider_deltas_async() must yield a text ProviderDelta."""
        backend = _make_backend("o1-pro")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        text_deltas = [d for d in deltas if d.text_delta]
        assert len(text_deltas) >= 1, "Expected at least one text ProviderDelta from Responses API"
        assert text_deltas[0].text_delta == "Hello"

    async def test_responses_api_yields_finish_delta(self):
        """o1-pro generate_provider_deltas_async() must yield a finish ProviderDelta."""
        backend = _make_backend("o1-pro")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert len(finish_deltas) >= 1, "Expected at least one finish ProviderDelta"
        assert finish_deltas[-1].finish_reason == "stop"

    async def test_responses_api_request_body_has_model(self):
        """Responses API request body must contain the correct model name."""
        backend = _make_backend("o1-pro")
        with respx.mock:
            route = respx.post(_RESPONSES_URL).mock(
                return_value=_responses_api_response()
            )
            await _drain(backend, _SAMPLE_MESSAGES)

        body = json.loads(route.calls[0].request.content)
        assert body.get("model") == "o1-pro", (
            f"Expected model='o1-pro' in Responses API request body, got: {body.get('model')!r}"
        )
