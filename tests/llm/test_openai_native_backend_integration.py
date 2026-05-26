"""Real-API integration tests for OpenAINativeBackend.

These tests hit api.openai.com with a real API key.  They are the last line of
defence against SDK contract violations that mocks and respx smoke tests cannot
catch (e.g. OpenAI rejecting a parameter name, stream iteration breaking on a
new SDK version, o-series rejecting temperature).

HOW TO RUN
----------
Set OPENAI_API_KEY in your environment, then:

    pytest tests/llm/test_openai_native_backend_integration.py -m integration -v

Without -m integration the tests are skipped automatically by the skip guard,
so normal 'pytest tests/' runs are unaffected and cost nothing.

MODELS USED
-----------
- gpt-4o-mini  : standard (non-o-series) model -- cheap, always available
- o4-mini      : o-series model -- uses max_completion_tokens + reasoning dict

WHAT IS TESTED
--------------
1. Standard model non-streaming  -- basic connection + tool parameter acceptance
2. Standard model streaming      -- ProviderDelta contract end-to-end via real SSE
3. O-series model streaming      -- o-series param mapping (no temp, reasoning dict)
"""

import asyncio
import os

import pytest

# Prime import chain (mirrors conftest.py pattern)
import src.core  # noqa: F401

from src.llm.base import LLMBackendType, LLMConfig, ToolDefinition

# ---------------------------------------------------------------------------
# Skip guard -- skip all tests in this module unless:
#   (a) OPENAI_API_KEY is set in the environment, AND
#   (b) the test is collected via '-m integration'
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_SKIP_REASON = (
    "OPENAI_API_KEY not set -- run with 'export OPENAI_API_KEY=sk-...' "
    "then 'pytest -m integration'"
)

skip_if_no_key = pytest.mark.skipif(not _API_KEY, reason=_SKIP_REASON)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STANDARD_MODEL = "gpt-4o-mini"
O_SERIES_MODEL = "o4-mini"

# A realistic tool that mirrors what the agent sends -- tests that our tool
# schema shape is accepted by the OpenAI API without strict=True.
_SAMPLE_TOOL = ToolDefinition(
    name="read_file",
    description=(
        "Read file contents with line-range support. Returns content with "
        "line numbers. Reads up to 1000 lines by default."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read",
            },
            "start_line": {
                "type": "integer",
                "description": "Start line number (1-indexed, inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "End line number (1-indexed, EXCLUSIVE).",
            },
        },
        "required": ["file_path"],
    },
)

_MESSAGES = [{"role": "user", "content": "Say hello in exactly three words."}]


def _make_config(model: str, reasoning_effort: str | None = None) -> LLMConfig:
    # o-series models reason internally before producing output -- they need
    # enough token budget to complete the reasoning phase. 64 is sufficient
    # for gpt-4o-mini but causes response.incomplete for o4-mini.
    max_tokens = 1024 if model.startswith(("o1", "o3", "o4")) else 64
    return LLMConfig(
        backend_type=LLMBackendType.OPENAI_NATIVE,
        model_name=model,
        base_url="https://api.openai.com/v1",
        context_window=131072,
        temperature=0.2,
        max_tokens=max_tokens,
        top_p=0.95,
        reasoning_effort=reasoning_effort,
    )


def _make_backend(config: LLMConfig):
    from src.llm.openai_native_backend import OpenAINativeBackend
    return OpenAINativeBackend(config, api_key=_API_KEY)


async def _collect(agen):
    result = []
    async for item in agen:
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_if_no_key
class TestStandardModelNonStreaming:
    """Non-streaming generate() against gpt-4o-mini.

    Validates that:
    - Our tool schema (without strict=True) is accepted
    - The response comes back with content
    - Usage data is populated
    """

    def test_generate_returns_content(self):
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        result = backend.generate(_MESSAGES, tools=[_SAMPLE_TOOL])

        assert result is not None, "generate() returned None"
        assert result.content or result.tool_calls, (
            "Expected either content or tool_calls in response"
        )

    def test_generate_usage_populated(self):
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        result = backend.generate(_MESSAGES, tools=[_SAMPLE_TOOL])

        # LLMResponse stores token counts as flat fields, not a usage dict
        assert result.prompt_tokens is not None, "prompt_tokens missing from LLMResponse"
        assert result.prompt_tokens > 0, "prompt_tokens must be > 0"
        assert result.completion_tokens is not None, "completion_tokens missing from LLMResponse"
        assert result.completion_tokens > 0, "completion_tokens must be > 0"

    def test_tool_schema_accepted_without_strict(self):
        """The API must accept our tool schema even though strict=True is absent.

        This is the exact bug that broke the agent before we switched from
        .stream() (enforces strict validation) to .create(stream=True).
        """
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        # Should not raise any OpenAI API error about strict tool validation
        try:
            backend.generate(_MESSAGES, tools=[_SAMPLE_TOOL])
        except Exception as exc:
            pytest.fail(
                f"API rejected our tool schema: {exc}\n"
                "This likely means strict=True enforcement crept back in."
            )


@skip_if_no_key
class TestStandardModelStreaming:
    """Streaming generate_provider_deltas_async() against gpt-4o-mini.

    Validates that:
    - Real SSE chunks produce ProviderDelta objects
    - stream_id is populated on every delta
    - A finish delta is emitted
    - Tool schema is accepted (same as non-streaming -- but in the stream path)
    """

    def test_streaming_yields_deltas(self):
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-sid-1",
                )
            )
        )

        assert len(deltas) > 0, "No ProviderDelta objects were yielded"

    def test_streaming_deltas_have_stream_id(self):
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-sid-2",
                )
            )
        )

        for d in deltas:
            assert d.stream_id == "integ-sid-2", (
                f"delta.stream_id mismatch: expected 'integ-sid-2', got {d.stream_id!r}"
            )

    def test_streaming_emits_finish_delta(self):
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-sid-3",
                )
            )
        )

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert len(finish_deltas) >= 1, (
            "No finish delta was emitted -- stream ended without finish_reason"
        )
        assert finish_deltas[-1].finish_reason in ("stop", "tool_calls", "length"), (
            f"Unexpected finish_reason: {finish_deltas[-1].finish_reason}"
        )

    def test_streaming_text_content_received(self):
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-sid-4",
                )
            )
        )

        text_deltas = [d for d in deltas if d.text_delta]
        full_text = "".join(d.text_delta for d in text_deltas)
        assert len(full_text) > 0, (
            "No text content received in streaming response -- "
            "the model should have replied with at least a few words"
        )

    def test_streaming_tool_schema_accepted(self):
        """Streaming path must also accept tools without strict=True."""
        config = _make_config(STANDARD_MODEL)
        backend = _make_backend(config)

        try:
            asyncio.get_event_loop().run_until_complete(
                _collect(
                    backend.generate_provider_deltas_async(
                        _MESSAGES,
                        tools=[_SAMPLE_TOOL],
                        stream_id="integ-sid-strict",
                    )
                )
            )
        except Exception as exc:
            pytest.fail(
                f"Streaming API rejected our tool schema: {exc}\n"
                "Likely .stream() strict validation crept back in -- must use .create(stream=True)."
            )


@skip_if_no_key
class TestOSeriesModelStreaming:
    """Streaming against o4-mini.

    Validates that:
    - max_completion_tokens is used (not max_tokens)
    - temperature / top_p are NOT sent (API rejects them for o-series)
    - Streaming still yields ProviderDelta objects
    - reasoning_effort='medium' is accepted without error
    """

    def test_o_series_streaming_yields_deltas(self):
        config = _make_config(O_SERIES_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-oseries-1",
                )
            )
        )

        assert len(deltas) > 0, f"No deltas from {O_SERIES_MODEL} streaming"

    def test_o_series_with_reasoning_effort_accepted(self):
        """reasoning_effort='medium' must be accepted by o4-mini without error."""
        config = _make_config(O_SERIES_MODEL, reasoning_effort="medium")
        backend = _make_backend(config)

        try:
            deltas = asyncio.get_event_loop().run_until_complete(
                _collect(
                    backend.generate_provider_deltas_async(
                        _MESSAGES,
                        tools=[_SAMPLE_TOOL],
                        stream_id="integ-oseries-effort",
                    )
                )
            )
        except Exception as exc:
            pytest.fail(
                f"o-series with reasoning_effort='medium' raised: {exc}\n"
                "Check that _build_chat_params sends reasoning={{'effort': 'medium'}} "
                "not a bare reasoning_effort= kwarg."
            )

        assert len(deltas) > 0, "No deltas returned for o-series with reasoning_effort"

    def test_o_series_finish_delta_emitted(self):
        config = _make_config(O_SERIES_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-oseries-finish",
                )
            )
        )

        finish_deltas = [d for d in deltas if d.finish_reason]
        assert len(finish_deltas) >= 1, (
            f"{O_SERIES_MODEL} stream ended without a finish delta"
        )


    def test_o_series_reasoning_tokens_in_usage(self):
        """Usage delta must include reasoning_tokens for o-series with reasoning_effort."""
        config = _make_config(O_SERIES_MODEL, reasoning_effort="medium")
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    _MESSAGES,
                    tools=[_SAMPLE_TOOL],
                    stream_id="integ-oseries-usage",
                )
            )
        )

        usage_deltas = [d for d in deltas if d.usage]
        assert usage_deltas, "No usage delta emitted for o-series stream"
        usage = usage_deltas[-1].usage
        assert "reasoning_tokens" in usage, (
            f"reasoning_tokens missing from usage dict: {usage}"
        )
        # reasoning_tokens may be 0 if the model skipped reasoning, but key must exist
        assert usage["reasoning_tokens"] is not None, (
            "reasoning_tokens is None -- extraction from output_tokens_details failed"
        )


@skip_if_no_key
class TestReasoningSummary:
    """Test reasoning summary streaming for gpt-5.4 and o-series models.

    These tests print all received event types and thinking delta counts
    to help diagnose whether summary events are actually firing.
    """

    GPT54_MODEL = "gpt-5.4-2026-03-05"
    REASONING_MESSAGES = [{"role": "user", "content": "What is 17 * 23? Think step by step."}]

    def _make_summary_config(self, model: str) -> LLMConfig:
        max_tokens = 2048
        return LLMConfig(
            backend_type=LLMBackendType.OPENAI_NATIVE,
            model_name=model,
            base_url="https://api.openai.com/v1",
            context_window=131072,
            temperature=0.2,
            max_tokens=max_tokens,
            top_p=0.95,
            reasoning_effort="medium",
            reasoning_summary=True,
        )

    def test_gpt54_reasoning_summary_yields_thinking_deltas(self):
        """gpt-5.4 with reasoning_effort + reasoning_summary should yield thinking_delta."""
        config = self._make_summary_config(self.GPT54_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    self.REASONING_MESSAGES,
                    stream_id="integ-summary-gpt54",
                )
            )
        )

        thinking_deltas = [d for d in deltas if d.thinking_delta]
        text_deltas = [d for d in deltas if d.text_delta]
        usage_deltas = [d for d in deltas if d.usage]

        print(f"\n[gpt-5.4] thinking_deltas={len(thinking_deltas)}, "
              f"text_deltas={len(text_deltas)}, "
              f"usage={usage_deltas[-1].usage if usage_deltas else None}")

        assert len(text_deltas) > 0, "No text content received -- model may have failed"
        assert len(thinking_deltas) > 0, (
            "No thinking_delta received for gpt-5.4 with reasoning_summary=True. "
            "Either the model does not support summary events, the org is not verified, "
            "or the reasoning param is not reaching the API."
        )

    def test_o4mini_reasoning_summary_yields_thinking_deltas(self):
        """o4-mini with reasoning_summary should yield thinking_delta."""
        config = self._make_summary_config(O_SERIES_MODEL)
        backend = _make_backend(config)

        deltas = asyncio.get_event_loop().run_until_complete(
            _collect(
                backend.generate_provider_deltas_async(
                    self.REASONING_MESSAGES,
                    stream_id="integ-summary-o4mini",
                )
            )
        )

        thinking_deltas = [d for d in deltas if d.thinking_delta]
        text_deltas = [d for d in deltas if d.text_delta]
        usage_deltas = [d for d in deltas if d.usage]

        print(f"\n[o4-mini] thinking_deltas={len(thinking_deltas)}, "
              f"text_deltas={len(text_deltas)}, "
              f"usage={usage_deltas[-1].usage if usage_deltas else None}")

        assert len(text_deltas) > 0, "No text content received -- model may have failed"
        assert len(thinking_deltas) > 0, (
            "No thinking_delta received for o4-mini with reasoning_summary=True. "
            "Either org is not verified for summary access, "
            "or the reasoning.summary param is not reaching the API."
        )
