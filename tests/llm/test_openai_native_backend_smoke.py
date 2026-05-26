"""HTTP-level smoke tests for OpenAINativeBackend using respx.

These tests let the real OpenAI SDK run -- including its parameter validation --
but intercept at the HTTP layer so no request reaches the internet.

WHY THESE TESTS EXIST
---------------------
Previous mock-based tests replaced the SDK client object entirely, so the SDK's
own parameter validation never ran.  This caused a bug where:

  1. _build_responses_params() returned stream=True in the params dict.
  2. generate_provider_deltas_async() passed that dict directly to .stream(**params).
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

ARCHITECTURE DECISION: ALL MODELS USE /v1/responses
----------------------------------------------------
As of the unified Responses API migration, ALL OpenAI models (including gpt-4o,
gpt-3.5-turbo, etc.) are routed to /v1/responses -- NOT /v1/chat/completions.
The Responses API is OpenAI's strategic surface and supports all models.
TestChatCompletionsWireFormat (formerly present here) was removed because the
backend no longer routes any model to /v1/chat/completions.

SSE RESPONSE FORMAT
-------------------
The Responses API streaming uses Server-Sent Events (SSE).  The SDK parses
the SSE body and yields typed event objects.  The backend filters for:
  - response.output_text.delta -> text content
  - response.reasoning_summary_text.delta -> thinking/reasoning content
  - response.function_call_arguments.delta -> tool call arguments
  - response.completed / response.done -> usage + finish
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

# Minimal valid SSE body for Responses API streaming with a text message.
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
    '"output_tokens_details":{"reasoning_tokens":3}},'
    '"error":null,"incomplete_details":null,"instructions":null,'
    '"max_output_tokens":null,"metadata":{},"parallel_tool_calls":true,'
    '"temperature":null,"tool_choice":"auto","tools":[],"top_p":null,'
    '"truncation":"disabled","background":false,"previous_response_id":null,'
    '"reasoning":null,"service_tier":"default","store":false,'
    '"text":{"format":{"type":"text"}},"voice":null}}\n\n'
    "data: [DONE]\n\n"
)

# SSE body for Responses API streaming with reasoning summary text.
# reasoning_tokens=180, text delta="After thinking...", finish_reason="stop".
#
# IMPORTANT: The reasoning_summary_text.delta event does NOT trigger
# response.output_item.added in the SDK snapshot accumulator, so it does NOT
# occupy a slot in snapshot.output.  The message item must use output_index=0
# (its position in snapshot.output after the output_item.added appends it).
# Using output_index=1 would cause an IndexError because the snapshot only has
# one item (the message) after the output_item.added event.
_RESPONSES_SSE_WITH_REASONING = (
    'data: {"type":"response.created","sequence_number":0,"response":{'
    '"id":"resp_002","object":"response","created_at":0,"status":"in_progress",'
    '"model":"o3","output":[],"usage":null,"error":null,'
    '"incomplete_details":null,"instructions":null,"max_output_tokens":null,'
    '"metadata":{},"parallel_tool_calls":true,"temperature":null,'
    '"tool_choice":"auto","tools":[],"top_p":null,"truncation":"disabled",'
    '"background":false,"previous_response_id":null,'
    '"reasoning":{"effort":"high","summary":"auto"},'
    '"service_tier":"default","store":false,'
    '"text":{"format":{"type":"text"}},"voice":null}}\n\n'
    'data: {"type":"response.reasoning_summary_text.delta","sequence_number":1,'
    '"item_id":"rs_001","output_index":0,"content_index":0,'
    '"delta":"I need to think carefully."}\n\n'
    'data: {"type":"response.output_item.added","sequence_number":2,'
    '"output_index":0,"item":{"id":"msg_002","type":"message",'
    '"status":"in_progress","role":"assistant","content":[]}}\n\n'
    'data: {"type":"response.content_part.added","sequence_number":3,'
    '"item_id":"msg_002","output_index":0,"content_index":0,'
    '"part":{"type":"output_text","text":"","annotations":[],"logprobs":null}}\n\n'
    'data: {"type":"response.output_text.delta","sequence_number":4,'
    '"item_id":"msg_002","output_index":0,"content_index":0,'
    '"delta":"After thinking...","logprobs":null}\n\n'
    'data: {"type":"response.output_text.done","sequence_number":5,'
    '"item_id":"msg_002","output_index":0,"content_index":0,'
    '"text":"After thinking...","logprobs":null}\n\n'
    'data: {"type":"response.output_item.done","sequence_number":6,'
    '"output_index":0,"item":{"id":"msg_002","type":"message",'
    '"status":"completed","role":"assistant","content":[{"type":"output_text",'
    '"text":"After thinking...","annotations":[],"logprobs":null}]}}\n\n'
    'data: {"type":"response.completed","sequence_number":7,"response":{'
    '"id":"resp_002","object":"response","created_at":0,"status":"completed",'
    '"model":"o3","output":[],'
    '"usage":{"input_tokens":20,"output_tokens":10,"total_tokens":30,'
    '"input_tokens_details":{"cached_tokens":0},'
    '"output_tokens_details":{"reasoning_tokens":180}},'
    '"error":null,"incomplete_details":null,"instructions":null,'
    '"max_output_tokens":null,"metadata":{},"parallel_tool_calls":true,'
    '"temperature":null,"tool_choice":"auto","tools":[],"top_p":null,'
    '"truncation":"disabled","background":false,"previous_response_id":null,'
    '"reasoning":{"effort":"high","summary":"auto"},'
    '"service_tier":"default","store":false,'
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


def _responses_api_response(sse_text: str = _RESPONSES_SSE_TEXT) -> httpx.Response:
    """Return a minimal valid SSE httpx.Response for the Responses API."""
    return httpx.Response(
        200,
        content=sse_text.encode(),
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
# Class 1: TestResponsesAPIAllModels
# Verify all models route to /v1/responses and send the correct wire format.
# ===========================================================================


class TestResponsesAPIAllModels:
    """All models (gpt-4o, o3, o1-pro, etc.) must POST to /v1/responses.

    The backend uses the unified Responses API for every model.
    /v1/chat/completions is never called.
    """

    async def test_gpt4o_hits_responses_endpoint(self):
        """gpt-4o must POST to /v1/responses, NOT /v1/chat/completions."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            responses_route = respx.post(_RESPONSES_URL).mock(
                return_value=_responses_api_response()
            )
            respx.post(_CHAT_URL).mock(
                return_value=httpx.Response(500, content=b"must not be called")
            )
            await _drain(backend, _SAMPLE_MESSAGES)

        assert responses_route.called, "gpt-4o must call /v1/responses"
        assert responses_route.call_count == 1

    async def test_o3_hits_responses_endpoint(self):
        """o3 must POST to /v1/responses."""
        backend = _make_backend("o3")
        with respx.mock:
            route = respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            await _drain(backend, _SAMPLE_MESSAGES)
        assert route.called

    async def test_o1_pro_hits_responses_endpoint(self):
        """o1-pro must POST to /v1/responses."""
        backend = _make_backend("o1-pro")
        with respx.mock:
            route = respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            await _drain(backend, _SAMPLE_MESSAGES)
        assert route.called

    async def test_no_model_hits_chat_completions(self):
        """No model must call /v1/chat/completions -- Responses API is universal."""
        for model in ("gpt-4o", "gpt-3.5-turbo", "o3-mini", "o1-pro", "gpt-5.4-mini"):
            backend = _make_backend(model)
            with respx.mock:
                respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
                chat_route = respx.post(_CHAT_URL).mock(
                    return_value=httpx.Response(500, content=b"must not be called")
                )
                await _drain(backend, _SAMPLE_MESSAGES)

            assert not chat_route.called, (
                f"Model {model!r} must NOT call /v1/chat/completions"
            )

    async def test_no_stream_kwarg_error(self):
        """generate_provider_deltas_async() must not raise TypeError from stream= kwarg.

        The Responses API .stream() rejects stream= as a positional kwarg.
        This test verifies the backend strips it before calling .stream().
        """
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)  # must not raise

        assert len(deltas) >= 1


# ===========================================================================
# Class 2: TestResponsesAPIRequestBody
# Verify the exact HTTP request body for various model/config combinations.
# ===========================================================================


class TestResponsesAPIRequestBody:
    """Verify the Responses API request body for model/config combinations."""

    async def _get_body(self, model: str, reasoning_effort: str | None = None) -> dict:
        backend = _make_backend(model, reasoning_effort)
        with respx.mock:
            route = respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            await _drain(backend, _SAMPLE_MESSAGES)
        return json.loads(route.calls[0].request.content)

    async def test_uses_input_not_messages(self):
        """Request body must use 'input' key (Responses API), never 'messages' (Chat API)."""
        body = await self._get_body("gpt-4o")
        assert "input" in body, "Responses API must use 'input' not 'messages'"
        assert "messages" not in body, "Responses API must NOT contain 'messages' key"

    async def test_uses_max_output_tokens_not_max_tokens(self):
        """Request body must use 'max_output_tokens' (Responses API), never 'max_tokens'."""
        body = await self._get_body("gpt-4o")
        assert "max_output_tokens" in body, (
            "Responses API requires 'max_output_tokens' (not 'max_tokens')"
        )
        assert "max_tokens" not in body, (
            "'max_tokens' is Chat Completions format -- must not appear in Responses API body"
        )
        assert "max_completion_tokens" not in body, (
            "'max_completion_tokens' is Chat Completions format -- must not appear"
        )
        assert body["max_output_tokens"] == 4096

    async def test_gpt4o_includes_temperature(self):
        """gpt-4o request body must include temperature (sampling-capable model)."""
        body = await self._get_body("gpt-4o")
        assert "temperature" in body, "gpt-4o must include temperature"
        assert body["temperature"] == pytest.approx(0.2)

    async def test_gpt4o_includes_top_p(self):
        """gpt-4o request body must include top_p."""
        body = await self._get_body("gpt-4o")
        assert "top_p" in body, "gpt-4o must include top_p"
        assert body["top_p"] == pytest.approx(0.95)

    async def test_o3_omits_temperature(self):
        """o-series request body must NOT include temperature (o-series rejects it)."""
        body = await self._get_body("o3")
        assert "temperature" not in body, "o-series must omit temperature"
        assert "top_p" not in body, "o-series must omit top_p"

    async def test_gpt5_omits_temperature(self):
        """gpt-5.x request body must NOT include temperature (fail-safe capability map)."""
        body = await self._get_body("gpt-5.4-mini")
        assert "temperature" not in body, "gpt-5.x must omit temperature (fail-safe)"
        assert "top_p" not in body, "gpt-5.x must omit top_p"

    async def test_unknown_model_omits_temperature(self):
        """Unknown model family must omit temperature -- fail-safe, not fail-open."""
        body = await self._get_body("gpt-7-turbo")
        assert "temperature" not in body, "Unknown model must omit temperature (fail-safe)"
        assert "top_p" not in body, "Unknown model must omit top_p (fail-safe)"

    async def test_reasoning_effort_nested_format(self):
        """When reasoning_effort is set, body must use nested reasoning={...}.

        Responses API format:  reasoning={"effort": "high"}
        NOT flat:              reasoning_effort="high"
        The nested format is required by /v1/responses; flat kwarg is Chat Completions only.
        By default, summary is omitted -- it requires OpenAI org verification (opt-in only).
        """
        body = await self._get_body("o3", reasoning_effort="high")
        assert "reasoning" in body, "reasoning param must be nested dict in Responses API"
        assert "reasoning_effort" not in body, (
            "Flat 'reasoning_effort' is Chat Completions format -- must NOT appear in body"
        )
        assert body["reasoning"]["effort"] == "high"
        assert "summary" not in body["reasoning"], (
            "reasoning.summary must be absent by default -- it requires OpenAI org verification. "
            "Use reasoning_summary=True config flag to opt in."
        )

    async def test_reasoning_summary_included_when_opted_in(self):
        """When reasoning_summary=True, body must include reasoning.summary='auto'.

        This is an opt-in feature requiring OpenAI organization verification.
        Users who have verified their org can enable it via the reasoning_summary config flag.
        """
        config = _make_config(model_name="o3", reasoning_effort="high")
        config_with_summary = config.model_copy(update={"reasoning_summary": True})
        backend = OpenAINativeBackend(config_with_summary, api_key="test-key")
        with respx.mock:
            route = respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            await _drain(backend, _SAMPLE_MESSAGES)
        body = json.loads(route.calls[0].request.content)
        assert body["reasoning"]["summary"] == "auto", (
            "reasoning.summary='auto' must be sent when reasoning_summary=True"
        )

    async def test_no_reasoning_when_effort_not_configured(self):
        """When reasoning_effort is not set, 'reasoning' key must be absent."""
        body = await self._get_body("o3")
        assert "reasoning" not in body, (
            "reasoning must not appear when reasoning_effort is not configured"
        )

    async def test_model_name_in_body(self):
        """Request body must contain the correct model name."""
        body = await self._get_body("gpt-4o")
        assert body.get("model") == "gpt-4o"

    async def test_store_false(self):
        """Requests must set store=false to avoid server-side conversation storage."""
        body = await self._get_body("gpt-4o")
        assert body.get("store") is False, "store must be False (privacy/cost)"


# ===========================================================================
# Class 3: TestResponsesAPIStreamOutput
# Verify ProviderDelta output from the streaming response.
# ===========================================================================


class TestResponsesAPIStreamOutput:
    """Verify ProviderDelta output yielded by generate_provider_deltas_async."""

    async def test_yields_text_delta(self):
        """Must yield at least one ProviderDelta with text_delta='Hello'."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        text_deltas = [d for d in deltas if d.text_delta]
        assert len(text_deltas) >= 1, "Expected at least one text ProviderDelta"
        assert text_deltas[0].text_delta == "Hello"

    async def test_yields_finish_delta(self):
        """Must yield a ProviderDelta with finish_reason='stop'."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert len(finish_deltas) >= 1, "Expected at least one finish ProviderDelta"
        assert finish_deltas[-1].finish_reason == "stop"

    async def test_all_deltas_share_stream_id(self):
        """All ProviderDeltas must share a single non-empty stream_id."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        assert len(deltas) > 0
        stream_ids = {d.stream_id for d in deltas}
        assert len(stream_ids) == 1, f"Expected one stream_id, got: {stream_ids}"
        assert all(d.stream_id for d in deltas)

    async def test_yields_usage_in_finish_delta(self):
        """Finish delta must include usage (input_tokens, output_tokens, reasoning_tokens)."""
        backend = _make_backend("gpt-4o")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(return_value=_responses_api_response())
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert finish_deltas, "Expected finish delta"
        usage = finish_deltas[-1].usage
        assert usage is not None, "Finish delta must carry usage dict"
        assert usage.get("input_tokens") == 10
        assert usage.get("output_tokens") == 5
        assert usage.get("reasoning_tokens") == 3

    async def test_yields_reasoning_delta_when_present(self):
        """When model streams reasoning summary, must yield ProviderDelta with thinking_delta."""
        backend = _make_backend("o3", reasoning_effort="high")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(
                return_value=_responses_api_response(_RESPONSES_SSE_WITH_REASONING)
            )
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        thinking_deltas = [d for d in deltas if d.thinking_delta]
        assert len(thinking_deltas) >= 1, (
            "Must yield at least one ProviderDelta with thinking_delta when model reasons"
        )
        assert thinking_deltas[0].thinking_delta == "I need to think carefully."

    async def test_reasoning_usage_reasoning_tokens(self):
        """Finish delta must report reasoning_tokens=180 from the response usage."""
        backend = _make_backend("o3", reasoning_effort="high")
        with respx.mock:
            respx.post(_RESPONSES_URL).mock(
                return_value=_responses_api_response(_RESPONSES_SSE_WITH_REASONING)
            )
            deltas = await _drain(backend, _SAMPLE_MESSAGES)

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert finish_deltas, "Expected finish delta"
        usage = finish_deltas[-1].usage
        assert usage is not None
        assert usage.get("reasoning_tokens") == 180, (
            f"Expected reasoning_tokens=180, got {usage.get('reasoning_tokens')!r}"
        )


# ===========================================================================
# Class 4: TestResponsesAPIInputTranslation
# Verify _prepare_responses_input() converts Chat Completions history correctly.
# These are unit tests on the translation method, not HTTP wire tests.
# ===========================================================================


class TestResponsesAPIInputTranslation:
    """Verify _prepare_responses_input() converts message history to Responses API format.

    Chat Completions (input) format:
      - tool results: {"role": "tool", "tool_call_id": "...", "content": "..."}
      - assistant tool_calls: {"role": "assistant", "tool_calls": [...]}

    Responses API (output) format -- top-level items, NOT nested in role messages:
      - tool results: {"type": "function_call_output", "call_id": "...", "output": "..."}
      - tool calls: {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."}
      - assistant text (separate message before tool calls when present):
            {"role": "assistant", "content": [{"type": "output_text", "text": "..."}]}
    """

    def _translate(self, messages: list[dict]) -> list[dict]:
        """Call the static translation method directly."""
        return OpenAINativeBackend._prepare_responses_input(messages)

    def test_plain_user_message_passthrough(self):
        """Plain user messages must pass through unchanged."""
        msgs = [{"role": "user", "content": "Hello"}]
        result = self._translate(msgs)
        assert result == msgs

    def test_plain_assistant_message_passthrough(self):
        """Plain assistant messages (no tool_calls) must pass through unchanged."""
        msgs = [{"role": "assistant", "content": "Hi there"}]
        result = self._translate(msgs)
        assert result == msgs

    def test_system_message_passthrough(self):
        """System messages must pass through unchanged."""
        msgs = [{"role": "system", "content": "You are helpful."}]
        result = self._translate(msgs)
        assert result == msgs

    def test_tool_result_becomes_top_level_function_call_output(self):
        """Tool result must become a top-level function_call_output item (no role key)."""
        msgs = [{"role": "tool", "tool_call_id": "call_abc", "content": "file content"}]
        result = self._translate(msgs)
        assert len(result) == 1
        item = result[0]
        assert item["type"] == "function_call_output", (
            "Tool result must use type='function_call_output'"
        )
        assert item["call_id"] == "call_abc", "tool_call_id must map to call_id"
        assert item["output"] == "file content", "content must map to output"
        assert "role" not in item, "function_call_output must NOT have a role key"
        assert "tool_call_id" not in item, "old Chat Completions key must be removed"
        assert "content" not in item, "old Chat Completions key must be removed"

    def test_assistant_with_tool_calls_becomes_top_level_function_call(self):
        """Assistant tool call must become a top-level function_call item (no role key)."""
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"/tmp/f"}'},
                    }
                ],
            }
        ]
        result = self._translate(msgs)
        assert len(result) == 1
        item = result[0]
        assert item["type"] == "function_call", (
            "Assistant tool call must use type='function_call'"
        )
        assert item["call_id"] == "call_xyz"
        assert item["name"] == "read_file"
        assert item["arguments"] == '{"path":"/tmp/f"}'
        assert "role" not in item, "function_call must NOT have a role key"

    def test_assistant_text_plus_tool_call_splits_into_two_items(self):
        """Assistant with text + tool_calls splits into text message then function_call item."""
        msgs = [
            {
                "role": "assistant",
                "content": "Let me check that file.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"/a"}'},
                    }
                ],
            }
        ]
        result = self._translate(msgs)
        # Text becomes a separate assistant message; tool call becomes a top-level item
        assert len(result) == 2, "Expected text message + function_call item"
        text_item = result[0]
        assert text_item["role"] == "assistant"
        assert text_item["content"][0]["type"] == "output_text"
        assert text_item["content"][0]["text"] == "Let me check that file."
        func_item = result[1]
        assert func_item["type"] == "function_call"
        assert func_item["call_id"] == "call_1"

    def test_multi_turn_tool_use_conversation(self):
        """Full multi-turn conversation translates all messages correctly."""
        msgs = [
            {"role": "user", "content": "What's in /tmp/file.txt?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"/tmp/file.txt"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Hello from file."},
            {"role": "assistant", "content": "The file says: Hello from file."},
        ]
        result = self._translate(msgs)
        # user(1) + function_call(1) + function_call_output(1) + assistant(1) = 4
        assert len(result) == 4

        # User pass-through
        assert result[0] == {"role": "user", "content": "What's in /tmp/file.txt?"}

        # Assistant with tool_calls -> top-level function_call
        assert result[1]["type"] == "function_call"
        assert result[1]["call_id"] == "call_1"
        assert result[1]["name"] == "read_file"

        # Tool result -> top-level function_call_output
        assert result[2]["type"] == "function_call_output"
        assert result[2]["call_id"] == "call_1"
        assert result[2]["output"] == "Hello from file."

        # Plain assistant -> pass-through
        assert result[3] == {"role": "assistant", "content": "The file says: Hello from file."}

    def test_multiple_tool_calls_in_one_assistant_message(self):
        """Multiple tool_calls produce multiple top-level function_call items."""
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"/a"}'},
                    },
                    {
                        "id": "call_b",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"/b"}'},
                    },
                ],
            }
        ]
        result = self._translate(msgs)
        assert len(result) == 2, "Two tool calls must produce two top-level function_call items"
        assert result[0]["type"] == "function_call"
        assert result[0]["call_id"] == "call_a"
        assert result[1]["type"] == "function_call"
        assert result[1]["call_id"] == "call_b"
