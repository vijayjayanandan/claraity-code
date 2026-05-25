"""Native OpenAI API backend.

Dedicated backend for api.openai.com only. Unlike the generic OpenAIBackend
(which targets any OpenAI-compatible endpoint), this backend:

  - Detects o-series models and applies the correct parameter schema:
      max_completion_tokens (not max_tokens), no temperature/top_p,
      reasoning.effort for thinking budget.
  - Routes models that require the Responses API to /v1/responses.
  - Routes standard GPT models to /v1/chat/completions as usual.

Requires openai>=2.34.0 (client.responses surface is available).
"""

import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    raise ImportError(
        "OpenAI SDK not installed or too old. Install with: pip install 'openai>=2.34.0'"
    )

import httpx

try:
    from src.observability import get_logger

    logger = get_logger("llm.openai_native_backend")
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from src.llm.base import (
    LLMBackend,
    LLMConfig,
    LLMResponse,
    ProviderDelta,
    StreamChunk,
    ToolCallDelta,
    ToolDefinition,
)
from src.llm.cache_tracker import CacheTracker
from src.llm.failure_handler import LLMFailureHandler
from src.session.models.base import generate_stream_id, generate_tool_call_id
from src.session.models.message import ToolCall, ToolCallFunction

# Timeout constants (match openai_backend.py)
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_WRITE_TIMEOUT = 10.0
DEFAULT_POOL_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# Model classification
# ---------------------------------------------------------------------------

# Models confirmed to support temperature/top_p sampling params.
# Conservative fail-safe default: unknown models are assumed NOT to support them.
# Reasoning: gpt-4.x confirmed supported; o-series and gpt-5.x confirmed unsupported.
# A new unrecognised model (gpt-7, etc.) will silently omit sampling params rather
# than sending params that cause a 400 error -- fail-safe, not fail-open.
# Update this list when OpenAI confirms a new family supports sampling params.
_SAMPLING_CAPABLE_PREFIXES = ("gpt-4", "gpt-3.5", "chatgpt-")

# o-series models: use reasoning_effort for thinking control.
O_SERIES_PREFIXES = ("o1", "o3", "o4")

# Models that only support the Responses API (/v1/responses), not Chat Completions.
RESPONSES_API_ONLY_PREFIXES = ("o1-pro",)


def _supports_sampling_params(model: str) -> bool:
    """True if model accepts temperature and top_p.

    Conservative fail-safe: unknown models return False.
    gpt-4.x and earlier are confirmed supported.
    o-series and gpt-5.x are confirmed unsupported.
    Any new unrecognised model omits sampling params rather than risking a 400.
    """
    lower = model.lower()
    return any(lower.startswith(p) for p in _SAMPLING_CAPABLE_PREFIXES)


def _is_o_series(model: str) -> bool:
    """True if model uses o-series parameter schema (reasoning_effort etc.)."""
    lower = model.lower()
    return any(lower.startswith(p) for p in O_SERIES_PREFIXES)


def _requires_responses_api(model: str) -> bool:
    """True if model must use /v1/responses instead of /v1/chat/completions."""
    lower = model.lower()
    return any(lower.startswith(p) for p in RESPONSES_API_ONLY_PREFIXES)


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class OpenAINativeBackend(LLMBackend):
    """Native OpenAI API backend (api.openai.com).

    Handles model-specific parameter routing for o-series and Responses API
    models transparently. All responses are normalised to LLMResponse /
    ProviderDelta so the rest of the agent is backend-agnostic.
    """

    def __init__(
        self,
        config: LLMConfig,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
    ):
        import os

        super().__init__(config)

        self.api_key = api_key or os.getenv(api_key_env) or "not-configured"

        timeout = httpx.Timeout(
            connect=DEFAULT_CONNECT_TIMEOUT,
            read=config.timeout,
            write=DEFAULT_WRITE_TIMEOUT,
            pool=DEFAULT_POOL_TIMEOUT,
        )

        # Always point at api.openai.com (base_url intentionally not set)
        self.client = OpenAI(api_key=self.api_key, timeout=timeout)
        self.async_client = AsyncOpenAI(api_key=self.api_key, timeout=timeout)

        self.failure_handler = LLMFailureHandler(logger_instance=logger)
        self.cache_tracker = CacheTracker()

        logger.info(
            "OpenAINativeBackend init",
            model=config.model_name,
            o_series=_is_o_series(config.model_name),
            responses_api=_requires_responses_api(config.model_name),
        )

        if not _supports_sampling_params(config.model_name) and not _is_o_series(config.model_name):
            logger.warning(
                "unknown_model_sampling_params_omitted",
                model=config.model_name,
                note="Fail-safe default active: omitting temperature/top_p for unknown model family. Add prefix to _SAMPLING_CAPABLE_PREFIXES if supported.",
            )

    # ------------------------------------------------------------------
    # Cache summary (M3)
    # ------------------------------------------------------------------

    def log_cache_summary(self) -> None:
        """Log the session-level cache summary to the application log."""
        summary = self.cache_tracker.summary()
        if summary["total_calls"] > 0:
            logger.info(self.cache_tracker.format_summary())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_cached_tokens(usage) -> int | None:
        """Extract cached prompt tokens from usage object."""
        if not usage:
            return None
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            val = getattr(details, "cached_tokens", None)
            if val is not None and val > 0:
                return val
        return None

    @staticmethod
    def _parse_tool_arguments(arguments_str: str, tool_name: str) -> dict[str, Any]:
        """Parse tool arguments JSON with basic error recovery."""
        if not arguments_str or arguments_str.strip() == "":
            return {}
        try:
            return json.loads(arguments_str)
        except json.JSONDecodeError:
            pass
        # Fix common issues: unterminated strings, missing closing braces
        try:
            fixed = arguments_str
            if fixed.count('"') % 2 != 0:
                fixed = fixed + '"'
            open_braces = fixed.count("{")
            close_braces = fixed.count("}")
            if open_braces > close_braces:
                fixed = fixed + ("}" * (open_braces - close_braces))
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        logger.warning("tool_args_parse_failed", tool=tool_name, raw=arguments_str[:200])
        return {}

    # ------------------------------------------------------------------
    # Parameter building
    # ------------------------------------------------------------------

    def _build_chat_params(
        self,
        messages: list[dict],
        tools: list[ToolDefinition] | None = None,
        tool_choice: str = "auto",
        stream: bool = False,
        **overrides: Any,
    ) -> dict[str, Any]:
        """Build request params for /v1/chat/completions."""
        model = self.config.model_name
        params: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}

        # max_completion_tokens is correct for all current OpenAI models.
        # max_tokens is a legacy alias that newer models (gpt-5.x+) reject at the API level.
        params["max_completion_tokens"] = overrides.get("max_tokens", self.config.max_tokens)

        if _supports_sampling_params(model):
            # Confirmed sampling-capable model (gpt-4.x, gpt-3.5, chatgpt-*).
            params["temperature"] = overrides.get("temperature", self.config.temperature)
            params["top_p"] = overrides.get("top_p", self.config.top_p)

        if _is_o_series(model) and self.config.reasoning_effort:
            # /v1/chat/completions uses reasoning_effort as a flat string kwarg
            params["reasoning_effort"] = self.config.reasoning_effort

        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            params["tool_choice"] = tool_choice

        if stream:
            params["stream_options"] = {"include_usage": True}

        return params

    def _build_responses_params(
        self,
        messages: list[dict],
        tools: list[ToolDefinition] | None = None,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Build request params for /v1/responses API."""
        model = self.config.model_name
        params: dict[str, Any] = {
            "model": model,
            "input": messages,
            "max_output_tokens": self.config.max_tokens,
            "store": False,
        }
        if self.config.reasoning_effort:
            params["reasoning"] = {"effort": self.config.reasoning_effort}
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ]
            # Responses API uses tool_choice differently; pass through if not "auto"
            if tool_choice != "auto":
                params["tool_choice"] = tool_choice
        return params

    # ------------------------------------------------------------------
    # Response normalisation
    # ------------------------------------------------------------------

    def _normalise_chat_response(self, response: Any) -> LLMResponse:
        """Convert a chat completions response to LLMResponse."""
        choice = response.choices[0]
        msg = choice.message
        usage = response.usage

        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                parsed_args = self._parse_tool_arguments(
                    tc.function.arguments or "", tc.function.name
                )
                args_json = json.dumps(parsed_args) if isinstance(parsed_args, dict) else str(parsed_args)
                tool_calls.append(
                    ToolCall.from_provider(
                        provider_id=tc.id,
                        function=ToolCallFunction(name=tc.function.name, arguments=args_json),
                    )
                )

        cached = self._extract_cached_tokens(usage)
        if usage:
            self.cache_tracker.record(usage)

        return LLMResponse(
            content=msg.content,
            model=response.model,
            finish_reason=choice.finish_reason,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            cached_tokens=cached,
            tool_calls=tool_calls,
            raw_response={"id": response.id, "created": response.created},
        )

    def _normalise_responses_response(self, response: Any) -> LLMResponse:
        """Convert a Responses API response to LLMResponse."""
        text_content = None
        tool_calls = None

        for item in getattr(response, "output", []):
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for block in getattr(item, "content", []):
                    if getattr(block, "type", None) == "output_text":
                        text_content = block.text
            elif item_type == "function_call":
                if tool_calls is None:
                    tool_calls = []
                parsed_args = self._parse_tool_arguments(
                    getattr(item, "arguments", "") or "", item.name
                )
                args_json = json.dumps(parsed_args) if isinstance(parsed_args, dict) else str(parsed_args)
                tool_calls.append(
                    ToolCall.from_provider(
                        provider_id=getattr(item, "call_id", None) or generate_tool_call_id(),
                        function=ToolCallFunction(name=item.name, arguments=args_json),
                    )
                )

        usage = getattr(response, "usage", None)
        if usage:
            self.cache_tracker.record(usage)

        return LLMResponse(
            content=text_content,
            model=getattr(response, "model", self.config.model_name),
            finish_reason="stop",
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            tool_calls=tool_calls,
        )

    # ------------------------------------------------------------------
    # LLMBackend interface -- synchronous
    # ------------------------------------------------------------------

    def generate(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Synchronous non-streaming completion."""
        self.validate_messages(messages)
        model = self.config.model_name

        if _requires_responses_api(model):
            def api_call():
                return self.client.responses.create(**self._build_responses_params(messages))
            try:
                response = self.failure_handler.execute_with_retry(api_call, max_attempts=3, backoff_base=2.0)
                return self._normalise_responses_response(response)
            except Exception as e:
                raise RuntimeError(f"OpenAI Responses API error: {e}") from e

        params = self._build_chat_params(messages, stream=False, **kwargs)

        def api_call():
            return self.client.chat.completions.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(api_call, max_attempts=3, backoff_base=2.0)
            return self._normalise_chat_response(response)
        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

    def generate_stream(self, messages: list[dict], **kwargs: Any) -> Iterator[StreamChunk]:
        """Synchronous streaming completion."""
        self.validate_messages(messages)
        params = self._build_chat_params(messages, stream=True, **kwargs)
        try:
            stream = self.client.chat.completions.create(**params)
            try:
                for chunk in stream:
                    if hasattr(chunk, "usage") and chunk.usage:
                        self.cache_tracker.record(chunk.usage)
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish = chunk.choices[0].finish_reason
                    yield StreamChunk(
                        content=delta.content or "",
                        done=bool(finish),
                        model=chunk.model,
                        finish_reason=finish,
                    )
            finally:
                if hasattr(stream, "close"):
                    stream.close()
        except Exception as e:
            raise RuntimeError(f"OpenAI streaming error: {e}") from e

    def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous tool-calling completion."""
        self.validate_messages(messages)
        model = self.config.model_name

        if _requires_responses_api(model):
            def api_call():
                return self.client.responses.create(
                    **self._build_responses_params(messages, tools=tools, tool_choice=tool_choice)
                )
            try:
                response = self.failure_handler.execute_with_retry(api_call, max_attempts=3, backoff_base=2.0)
                return self._normalise_responses_response(response)
            except Exception as e:
                raise RuntimeError(f"OpenAI Responses API tool error: {e}") from e

        params = self._build_chat_params(
            messages, tools=tools, tool_choice=tool_choice, stream=False, **kwargs
        )

        def api_call():
            return self.client.chat.completions.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(api_call, max_attempts=3, backoff_base=2.0)
            return self._normalise_chat_response(response)
        except Exception as e:
            raise RuntimeError(f"OpenAI tool calling API error: {e}") from e

    # ------------------------------------------------------------------
    # LLMBackend interface -- async streaming (primary agent path)
    # ------------------------------------------------------------------

    async def generate_provider_deltas_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        tool_choice: str = "auto",
        stream_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProviderDelta]:
        """Async streaming tool-calling -- primary path used by CodingAgent.

        Signature matches OpenAIBackend.generate_provider_deltas_async exactly.
        """
        self.validate_messages(messages)
        sid = stream_id or generate_stream_id()
        model = self.config.model_name

        if _requires_responses_api(model):
            async for delta in self._stream_responses_api(messages, tools or [], sid, tool_choice):
                yield delta
            return

        # Extract kwargs overrides (M5)
        overrides: dict[str, Any] = {}
        for key in ("temperature", "max_tokens", "top_p"):
            if key in kwargs:
                overrides[key] = kwargs[key]

        params = self._build_chat_params(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            **overrides,
        )

        # thinking_budget not applicable to native OpenAI (o-series uses reasoning.effort)
        # but accept it silently for interface parity

        _t0 = time.monotonic()
        _chunk_count = 0
        try:
            logger.debug("llm_stream_phase", phase="http_request_start", model=model)

            # Track canonical tool call IDs by index (generated on first delta)
            tool_call_ids: dict[int, str] = {}
            finish_reason = None
            usage_dict = None

            # Use .create(stream=True) -- same as OpenAIBackend. Avoids the SDK's
            # strict tool validation that .stream() enforces (which rejects our tools
            # because they don't have strict=True in their schemas).
            stream = await self.async_client.chat.completions.create(**params)
            logger.debug(
                "llm_stream_phase",
                phase="http_request_done",
                model=model,
                elapsed_ms=round((time.monotonic() - _t0) * 1000),
            )
            try:
                async for chunk in stream:
                    _chunk_count += 1

                    # Capture usage (comes in final chunk with stream_options)
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage_dict = {
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                            "cached_tokens": self._extract_cached_tokens(chunk.usage),
                            "reasoning_tokens": getattr(
                                getattr(chunk.usage, "completion_tokens_details", None),
                                "reasoning_tokens",
                                None,
                            ),
                        }
                        self.cache_tracker.record(chunk.usage)

                    # Skip usage-only chunks
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    # Text delta
                    if delta.content:
                        yield ProviderDelta(stream_id=sid, text_delta=delta.content)

                    # Reasoning content from o-series (if exposed as a dedicated field)
                    _extra = getattr(delta, "model_extra", None) or {}
                    reasoning_text = _extra.get("reasoning") or _extra.get("reasoning_content")
                    if reasoning_text:
                        yield ProviderDelta(stream_id=sid, thinking_delta=reasoning_text)

                    # Tool call deltas -- emit id+name on first delta, args on subsequent
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            # Generate canonical ID on first delta for this index
                            if tc_delta.id and idx not in tool_call_ids:
                                tool_call_ids[idx] = generate_tool_call_id()

                            tc_id = tool_call_ids.get(idx) if tc_delta.id else None
                            tc_name = (
                                tc_delta.function.name
                                if tc_delta.function and tc_delta.function.name
                                else None
                            )
                            args_delta = (
                                tc_delta.function.arguments
                                if tc_delta.function and tc_delta.function.arguments
                                else ""
                            )

                            yield ProviderDelta(
                                stream_id=sid,
                                tool_call_delta=ToolCallDelta(
                                    index=idx,
                                    id=tc_id,
                                    name=tc_name,
                                    arguments_delta=args_delta,
                                ),
                            )

            finally:
                if hasattr(stream, "close"):
                    await stream.close()

            # Emit finish delta with usage
            logger.debug(
                "llm_stream_phase",
                phase="stream_complete",
                total_chunks=_chunk_count,
                finish_reason=finish_reason,
                elapsed_ms=round((time.monotonic() - _t0) * 1000),
            )
            yield ProviderDelta(
                stream_id=sid,
                finish_reason=finish_reason or "stop",
                usage=usage_dict,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            logger.exception(
                "openai_native_async_provider_delta_error",
                error_type=error_type,
                model=model,
            )
            raise RuntimeError(
                f"OpenAI native async provider delta error: {error_type}: {error_msg}"
            ) from e

    async def _stream_responses_api(
        self,
        messages: list[dict],
        tools: list[ToolDefinition],
        stream_id: str,
        tool_choice: str = "auto",
    ) -> AsyncIterator[ProviderDelta]:
        """Stream from Responses API for models that require it (e.g. o1-pro).

        Emits a first ToolCallDelta with id+name, then subsequent deltas with
        arguments_delta only -- matching the chat completions pattern (C3).
        """
        params = self._build_responses_params(messages, tools=tools, tool_choice=tool_choice)

        # Track whether we have emitted the id+name header for each output_index
        tool_headers_emitted: dict[int, bool] = {}
        # Map output_index -> (call_id, name) gathered from response.output_item.added events
        tool_call_meta: dict[int, dict[str, str]] = {}

        # NOTE: .stream() returns an async context manager directly -- do NOT await it.
        async with self.async_client.responses.stream(**params) as stream:
            async for event in stream:
                event_type = getattr(event, "type", None)

                if event_type == "response.output_text.delta":
                    delta_text = getattr(event, "delta", "")
                    if delta_text:
                        yield ProviderDelta(stream_id=stream_id, text_delta=delta_text)

                elif event_type == "response.output_item.added":
                    # Capture tool call metadata (id, name) when the item is announced
                    item = getattr(event, "item", None)
                    if item and getattr(item, "type", None) == "function_call":
                        idx = getattr(event, "output_index", 0)
                        tool_call_meta[idx] = {
                            "id": generate_tool_call_id(),
                            "name": getattr(item, "name", "") or "",
                        }

                elif event_type == "response.function_call_arguments.start":
                    # Start event carries call_id and name for this tool call (C3)
                    idx = getattr(event, "output_index", 0)
                    call_id = getattr(event, "call_id", None)
                    name = getattr(event, "name", "") or ""
                    tool_call_meta[idx] = {
                        "id": generate_tool_call_id(),
                        "name": name,
                    }

                elif event_type == "response.function_call_arguments.delta":
                    args_delta = getattr(event, "delta", "")
                    idx = getattr(event, "output_index", 0)

                    meta = tool_call_meta.get(idx)

                    if not tool_headers_emitted.get(idx):
                        # First delta for this tool call: emit id + name (C3)
                        tool_headers_emitted[idx] = True
                        yield ProviderDelta(
                            stream_id=stream_id,
                            tool_call_delta=ToolCallDelta(
                                index=idx,
                                id=meta["id"] if meta else generate_tool_call_id(),
                                name=meta["name"] if meta else "",
                                arguments_delta=args_delta,
                            ),
                        )
                    else:
                        # Subsequent deltas: arguments only
                        yield ProviderDelta(
                            stream_id=stream_id,
                            tool_call_delta=ToolCallDelta(
                                index=idx,
                                arguments_delta=args_delta,
                            ),
                        )

                elif event_type == "response.completed":
                    # Capture usage from the completed response
                    response = getattr(event, "response", None)
                    usage = getattr(response, "usage", None) if response else None
                    usage_dict = None
                    if usage:
                        self.cache_tracker.record(usage)
                        usage_dict = {
                            "input_tokens": getattr(usage, "input_tokens", None),
                            "output_tokens": getattr(usage, "output_tokens", None),
                            "cached_tokens": None,
                            "reasoning_tokens": getattr(
                                getattr(usage, "output_tokens_details", None),
                                "reasoning_tokens",
                                None,
                            ),
                        }
                    yield ProviderDelta(
                        stream_id=stream_id,
                        finish_reason="stop",
                        usage=usage_dict,
                    )

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        """Approximate token count using tiktoken if available."""
        try:
            import tiktoken

            enc = tiktoken.encoding_for_model("gpt-4o")
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4

    def is_available(self) -> bool:
        """Check if the OpenAI API is reachable."""
        try:
            self.client.models.list(timeout=10.0)
            return True
        except Exception as e:
            logger.error(
                "openai_native_availability_check_failed",
                error_type=type(e).__name__,
                error=str(e)[:200],
            )
            return False

    def list_models(self) -> list[str]:
        """Return available OpenAI models (GPT and o-series only)."""
        try:
            models = self.client.models.list(timeout=10.0)
            return sorted(
                [
                    m.id
                    for m in models.data
                    if m.id.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))
                ],
                key=str.lower,
            )
        except Exception as exc:
            exc_name = type(exc).__name__
            if "Auth" in exc_name or "Permission" in exc_name or "Connection" in exc_name:
                raise
            logger.warning("list_models_failed", error=str(exc))
            return []
