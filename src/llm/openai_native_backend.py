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
            api="responses",
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
    # Message format translation
    # ------------------------------------------------------------------

    @staticmethod
    def _translate_content_blocks(content: "str | list | None", role: str) -> "str | list | None":
        """Translate Chat Completions content blocks to Responses API format.

        Chat Completions uses:
          - {"type": "text",      "text": "..."}
          - {"type": "image_url", "image_url": {"url": "data:..."}}

        Responses API uses (for user/system input):
          - {"type": "input_text",  "text": "..."}
          - {"type": "input_image", "image_url": "data:..."}

        For assistant output content the types are output_text / refusal (already correct
        when we build them ourselves; leave them alone).
        """
        if not isinstance(content, list):
            return content  # plain string -- SDK accepts it as-is

        translated = []
        for block in content:
            if not isinstance(block, dict):
                translated.append(block)
                continue
            btype = block.get("type")
            if btype == "text" and role in ("user", "system"):
                translated.append({"type": "input_text", "text": block.get("text", "")})
            elif btype == "image_url" and role in ("user", "system"):
                url = (block.get("image_url") or {}).get("url", "")
                translated.append({"type": "input_image", "image_url": url})
            else:
                translated.append(block)
        return translated

    @staticmethod
    def _prepare_responses_input(messages: list[dict]) -> list[dict]:
        """Convert Chat Completions message history to Responses API input format.

        The agent's canonical history uses Chat Completions schema:
          - role="tool"  with tool_call_id + content  (tool results)
          - role="assistant" with tool_calls list      (tool requests)
          - role="system" / "user" with content        (unchanged)

        Responses API expects ALL items to be top-level in the input array:
          - Tool result:    {"type": "function_call_output", "call_id": ..., "output": ...}
          - Tool call:      {"type": "function_call", "call_id": ..., "name": ..., "arguments": ...}
          - Assistant text: {"role": "assistant", "content": [{"type": "output_text", "text": ...}]}
          - User/system:    pass through with content blocks translated to input_text / input_image
        """
        translated: list[dict] = []
        for msg in messages:
            role = msg.get("role")

            # Tool result: {"role": "tool", "tool_call_id": "...", "content": "..."}
            # -> top-level function_call_output item
            if role == "tool":
                translated.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": msg.get("content", ""),
                })

            # Assistant with tool_calls: each call becomes a top-level function_call item.
            # Any text content becomes a separate assistant message before the calls.
            elif role == "assistant" and msg.get("tool_calls"):
                text = msg.get("content")
                if text:
                    translated.append({
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    })
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    translated.append({
                        "type": "function_call",
                        "call_id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    })

            # User / system / plain assistant: translate content blocks, pass through
            else:
                new_msg = dict(msg)
                new_msg["content"] = OpenAINativeBackend._translate_content_blocks(
                    msg.get("content"), role or ""
                )
                translated.append(new_msg)

        return translated

    # ------------------------------------------------------------------
    # Parameter building
    # ------------------------------------------------------------------

    def _build_responses_params(
        self,
        messages: list[dict],
        tools: list[ToolDefinition] | None = None,
        tool_choice: str = "auto",
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build request params for /v1/responses API."""
        model = self.config.model_name
        params: dict[str, Any] = {
            "model": model,
            "input": self._prepare_responses_input(messages),
            "max_output_tokens": self.config.max_tokens,
            "store": False,
        }

        # Handle M5 overrides from kwargs
        if "max_tokens" in kwargs:
            params["max_output_tokens"] = kwargs.pop("max_tokens")

        # Sampling params (if supported)
        if _supports_sampling_params(model):
            params["temperature"] = kwargs.pop("temperature", self.config.temperature)
            params["top_p"] = kwargs.pop("top_p", self.config.top_p)

        if self.config.reasoning_effort:
            reasoning: dict = {"effort": self.config.reasoning_effort}
            if self.config.reasoning_summary:
                # summary="auto" streams reasoning text back as thinking blocks.
                # Requires OpenAI org verification -- opt-in only.
                reasoning["summary"] = "auto"
            params["reasoning"] = reasoning
        
        # Responses API uses `stream` at the top level
        if stream:
            params["stream"] = True

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
                
        # Strip Anthropic-only kwargs that must not reach the Responses API
        kwargs.pop("thinking_budget", None)

        # Pass any remaining kwargs
        params.update(kwargs)
        return params

    # ------------------------------------------------------------------
    # Response normalisation
    # ------------------------------------------------------------------

    def _normalise_responses_response(self, response: Any) -> LLMResponse:
        """Convert a Responses API response to LLMResponse."""
        text_parts: list[str] = []
        tool_calls = None

        for item in getattr(response, "output", []):
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for block in getattr(item, "content", []):
                    if getattr(block, "type", None) == "output_text":
                        text = getattr(block, "text", None)
                        if text:
                            text_parts.append(text)
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
            content="".join(text_parts) or None,
            model=getattr(response, "model", self.config.model_name),
            finish_reason=getattr(response, "finish_reason", None) or "stop",
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            cached_tokens=self._extract_cached_tokens(usage),
            tool_calls=tool_calls,
        )

    # ------------------------------------------------------------------
    # LLMBackend interface -- synchronous
    # ------------------------------------------------------------------

    def generate(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Synchronous non-streaming completion."""
        self.validate_messages(messages)
        params = self._build_responses_params(messages, **kwargs)

        def api_call():
            return self.client.responses.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(api_call, max_attempts=3, backoff_base=2.0)
            return self._normalise_responses_response(response)
        except Exception as e:
            raise RuntimeError(f"OpenAI Responses API error: {e}") from e

    def generate_stream(self, messages: list[dict], **kwargs: Any) -> Iterator[StreamChunk]:
        """Synchronous streaming completion."""
        self.validate_messages(messages)
        params = self._build_responses_params(messages, stream=True, **kwargs)

        try:
            # Note: Responses stream API is a context manager
            with self.client.responses.stream(**params) as stream:
                for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type == "response.output_text.delta":
                        yield StreamChunk(
                            content=getattr(event, "delta", ""),
                            done=False,
                            model=self.config.model_name,
                            finish_reason=None,
                        )
                    elif event_type in {"response.completed", "response.done"}:
                        response = getattr(event, "response", None)
                        usage = getattr(response, "usage", None) if response else None
                        if usage:
                            self.cache_tracker.record(usage)
                        finish_reason = (
                            getattr(response, "finish_reason", None)
                            or getattr(event, "finish_reason", None)
                            or "stop"
                        )
                        yield StreamChunk(
                            content="",
                            done=True,
                            model=getattr(response, "model", self.config.model_name) if response else self.config.model_name,
                            finish_reason=finish_reason,
                            prompt_tokens=getattr(usage, "input_tokens", None),
                            completion_tokens=getattr(usage, "output_tokens", None),
                            total_tokens=getattr(usage, "total_tokens", None),
                            cached_tokens=self._extract_cached_tokens(usage),
                        )
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
        params = self._build_responses_params(messages, tools=tools, tool_choice=tool_choice, **kwargs)

        def api_call():
            return self.client.responses.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(api_call, max_attempts=3, backoff_base=2.0)
            return self._normalise_responses_response(response)
        except Exception as e:
            raise RuntimeError(f"OpenAI Responses API tool error: {e}") from e

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

        async for delta in self._stream_responses_api(messages, tools or [], sid, tool_choice, **kwargs):
            yield delta

    async def _stream_responses_api(
        self,
        messages: list[dict],
        tools: list[ToolDefinition],
        stream_id: str,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> AsyncIterator[ProviderDelta]:
        """Stream from Responses API.

        Emits a first ToolCallDelta with id+name, then subsequent deltas with
        arguments_delta only -- matching the chat completions pattern (C3).
        """
        params = self._build_responses_params(messages, tools=tools, tool_choice=tool_choice, **kwargs)

        # Track whether we have emitted the id+name header for each output_index
        tool_headers_emitted: dict[int, bool] = {}
        # Map output_index -> (call_id, name) gathered from response.output_item.added events
        tool_call_meta: dict[int, dict[str, str]] = {}

        # NOTE: .stream() returns an async context manager directly -- do NOT await it.
        logger.debug(
            "responses_api_stream_params",
            model=params.get("model"),
            reasoning=params.get("reasoning"),
            has_tools=bool(params.get("tools")),
        )
        try:
            async with self.async_client.responses.stream(**params) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "response.output_text.delta":
                        delta_text = getattr(event, "delta", "")
                        if delta_text:
                            yield ProviderDelta(stream_id=stream_id, text_delta=delta_text)

                    elif event_type == "response.reasoning_summary_text.delta":
                        delta_text = getattr(event, "delta", "")
                        logger.debug("reasoning_summary_delta", chars=len(delta_text))
                        if delta_text:
                            yield ProviderDelta(stream_id=stream_id, thinking_delta=delta_text)

                    elif event_type == "response.output_item.added":
                        # Capture tool call metadata (id, name) when the item is announced
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", None) == "function_call":
                            idx = getattr(event, "output_index", 0)
                            tool_call_meta[idx] = {
                                "id": getattr(item, "call_id", None) or generate_tool_call_id(),
                                "name": getattr(item, "name", "") or "",
                            }

                    elif event_type == "response.function_call_arguments.start":
                        # Start event carries call_id and name for this tool call (C3)
                        idx = getattr(event, "output_index", 0)
                        call_id = getattr(event, "call_id", None)
                        name = getattr(event, "name", "") or ""
                        tool_call_meta[idx] = {
                            "id": call_id or generate_tool_call_id(),
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

                    elif event_type in {"response.completed", "response.done", "response.incomplete"}:
                        # Capture usage from the completed/incomplete response
                        response = getattr(event, "response", None)
                        usage = getattr(response, "usage", None) if response else None
                        usage_dict = None
                        if usage:
                            self.cache_tracker.record(usage)
                            usage_dict = {
                                "input_tokens": getattr(usage, "input_tokens", None),
                                "output_tokens": getattr(usage, "output_tokens", None),
                                "cached_tokens": self._extract_cached_tokens(usage),
                                "reasoning_tokens": getattr(
                                    getattr(usage, "output_tokens_details", None),
                                    "reasoning_tokens",
                                    None,
                                ),
                            }
                        if event_type == "response.incomplete":
                            finish_reason = "length"
                        else:
                            finish_reason = (
                                getattr(response, "finish_reason", None)
                                or getattr(event, "finish_reason", None)
                                or "stop"
                            )
                        yield ProviderDelta(
                            stream_id=stream_id,
                            finish_reason=finish_reason,
                            usage=usage_dict,
                        )
        except Exception as e:
            from src.llm.failure_handler import classify_provider_error

            raise classify_provider_error(e) from e

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
