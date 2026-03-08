"""Native Anthropic Messages API backend.

Uses the official Anthropic Python SDK for direct API access, enabling:
- Native prompt caching (cache_control breakpoints)
- Extended thinking (thinking blocks with signatures)
- Native tool_use content blocks
- Streaming with typed events
"""

import json
import logging
from copy import deepcopy
from typing import List, Dict, Any, Iterator, Optional, AsyncIterator

import httpx

try:
    import anthropic
    from anthropic import Anthropic, AsyncAnthropic
except ImportError:
    raise ImportError(
        "Anthropic SDK not installed. Install with: pip install anthropic"
    )

# Try to import structured logging with get_logger
try:
    from src.observability import get_logger, ErrorCategory
    logger = get_logger("llm.anthropic_backend")
    STRUCTURED_LOGGING = True
except ImportError:
    # Fallback to stdlib logger
    logger = logging.getLogger(__name__)
    STRUCTURED_LOGGING = False
    class ErrorCategory:
        PROVIDER_TIMEOUT = 'provider_timeout'
        PROVIDER_ERROR = 'provider_error'

# Timeout constants (in seconds)
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_WRITE_TIMEOUT = 10.0
DEFAULT_POOL_TIMEOUT = 10.0

from .base import (
    LLMBackend, LLMConfig, LLMResponse, StreamChunk, ToolDefinition,
    ProviderDelta, ToolCallDelta
)
from src.session.models.message import ToolCall, ToolCallFunction
from src.session.models.base import generate_tool_call_id
from .failure_handler import LLMFailureHandler
from .cache_tracker import CacheTracker

# Known Claude models (Anthropic has no list models endpoint)
KNOWN_CLAUDE_MODELS = [
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]

# Stop reason mapping: Anthropic -> OpenAI-compatible
STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
}


class AnthropicBackend(LLMBackend):
    """Native Anthropic Messages API backend.

    Implements the LLMBackend interface using the Anthropic Python SDK directly.
    Handles message format translation (OpenAI format -> Anthropic format),
    tool calling, prompt caching, extended thinking, and streaming.
    """

    def __init__(
        self,
        config: LLMConfig,
        api_key: Optional[str] = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
    ):
        """Initialize Anthropic backend.

        Args:
            config: LLM configuration
            api_key: Optional API key (overrides env var)
            api_key_env: Environment variable name for API key
        """
        import os
        super().__init__(config)

        self.api_key = api_key or os.getenv(api_key_env, "")
        if not self.api_key:
            raise ValueError(
                f"Anthropic API key not found. Set {api_key_env} environment variable "
                f"or pass api_key parameter."
            )

        # Configure granular timeouts (matching OpenAI backend pattern)
        timeout = httpx.Timeout(
            connect=DEFAULT_CONNECT_TIMEOUT,
            read=config.timeout,
            write=DEFAULT_WRITE_TIMEOUT,
            pool=DEFAULT_POOL_TIMEOUT,
        )

        # Build client kwargs (base_url is optional -- SDK defaults to api.anthropic.com)
        client_kwargs: Dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": timeout,
        }
        if config.base_url:
            # Strip /v1 suffix — Anthropic SDK adds its own /v1/messages path
            base = config.base_url.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            client_kwargs["base_url"] = base

        # Sync client
        self.client = Anthropic(**client_kwargs)

        # Async client (for TUI)
        self.async_client = AsyncAnthropic(**client_kwargs)

        # Error handling and retry logic
        self.failure_handler = LLMFailureHandler(logger_instance=logger)

        # Prompt caching metrics
        self.cache_tracker = CacheTracker()

    # =========================================================================
    # Message Translation (OpenAI format -> Anthropic format)
    # =========================================================================

    def _translate_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple:
        """Convert OpenAI-format messages to Anthropic API format.

        Handles:
        1. Extracting system messages to separate parameter
        2. Converting assistant tool_calls to tool_use content blocks
        3. Converting tool results (role:tool) to user messages with tool_result blocks
        4. Merging consecutive same-role messages (Anthropic requires alternation)
        5. Ensuring conversation starts with user role

        Args:
            messages: OpenAI-format message list

        Returns:
            Tuple of (system_prompt_string, anthropic_messages_list)
        """
        system_parts = []
        translated = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content")

            # 1. Extract system messages
            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            system_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            system_parts.append(block)
                continue

            # 2. Convert assistant messages with tool_calls
            if role == "assistant":
                content_blocks = []

                # Include thinking blocks if present (round-tripping)
                thinking = msg.get("thinking")
                thinking_signature = msg.get("thinking_signature")
                if thinking and thinking_signature:
                    content_blocks.append({
                        "type": "thinking",
                        "thinking": thinking,
                        "signature": thinking_signature,
                    })

                # Add text content
                if isinstance(content, str) and content:
                    content_blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            content_blocks.append(block)

                # Convert tool_calls to tool_use blocks
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        # Handle both dict and object-style tool calls
                        if isinstance(tc, dict):
                            tc_id = tc.get("id", "")
                            func = tc.get("function", {})
                            tc_name = func.get("name", "")
                            tc_args = func.get("arguments", "{}")
                        else:
                            tc_id = getattr(tc, "id", "")
                            func = getattr(tc, "function", None)
                            tc_name = getattr(func, "name", "") if func else ""
                            tc_args = getattr(func, "arguments", "{}") if func else "{}"

                        # Parse arguments from JSON string to dict
                        try:
                            input_dict = json.loads(tc_args) if isinstance(tc_args, str) else tc_args
                        except (json.JSONDecodeError, TypeError):
                            input_dict = {}

                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc_id,
                            "name": tc_name,
                            "input": input_dict,
                        })

                # Anthropic requires non-empty content
                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})

                translated.append({"role": "assistant", "content": content_blocks})
                continue

            # 3. Convert tool result messages
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                result_content = content if content is not None else ""

                # Build tool_result content block
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": str(result_content),
                }

                # Check if we have an error status
                if msg.get("is_error"):
                    tool_result_block["is_error"] = True

                translated.append({
                    "role": "user",
                    "content": [tool_result_block],
                })
                continue

            # 4. Regular user messages
            if role == "user":
                if isinstance(content, str):
                    translated.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    # Convert OpenAI multimodal format to Anthropic format
                    anthropic_blocks = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "image_url":
                            # Convert OpenAI image_url -> Anthropic image block
                            image_info = block.get("image_url", {})
                            url = image_info.get("url", "")
                            # Parse data URL: data:<media_type>;base64,<data>
                            if url.startswith("data:") and ";base64," in url:
                                header, b64_data = url.split(";base64,", 1)
                                media_type = header.replace("data:", "")
                                anthropic_blocks.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64_data,
                                    },
                                })
                            else:
                                # URL-based image (not data URL) - use url source
                                anthropic_blocks.append({
                                    "type": "image",
                                    "source": {
                                        "type": "url",
                                        "url": url,
                                    },
                                })
                        elif isinstance(block, dict) and block.get("type") == "text":
                            anthropic_blocks.append({
                                "type": "text",
                                "text": block.get("text", ""),
                            })
                        elif isinstance(block, dict):
                            # Pass through other block types (e.g. already in Anthropic format)
                            anthropic_blocks.append(block)
                    translated.append({"role": "user", "content": anthropic_blocks})
                else:
                    translated.append({"role": "user", "content": str(content or "")})
                continue

        # 5. Merge consecutive same-role messages
        merged = self._merge_consecutive_roles(translated)

        # 6. Ensure conversation starts with user
        if merged and merged[0].get("role") != "user":
            merged.insert(0, {"role": "user", "content": "Continue."})

        # Handle empty messages
        if not merged:
            merged = [{"role": "user", "content": "Hello."}]

        system_text = "\n\n".join(system_parts)
        return system_text, merged

    @staticmethod
    def _merge_consecutive_roles(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge consecutive messages with the same role.

        Anthropic strictly requires alternating user/assistant messages.
        This combines consecutive same-role messages into one.
        """
        if not messages:
            return []

        merged = [deepcopy(messages[0])]

        for msg in messages[1:]:
            if msg["role"] == merged[-1]["role"]:
                # Same role - merge content
                prev = merged[-1]
                prev_content = prev.get("content", "")
                new_content = msg.get("content", "")

                # Normalize both to list format for merging
                prev_blocks = AnthropicBackend._to_content_blocks(prev_content)
                new_blocks = AnthropicBackend._to_content_blocks(new_content)

                prev["content"] = prev_blocks + new_blocks
            else:
                merged.append(deepcopy(msg))

        return merged

    @staticmethod
    def _to_content_blocks(content) -> List[Dict[str, Any]]:
        """Convert content to list of content blocks."""
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        elif isinstance(content, list):
            return list(content)
        return []

    # =========================================================================
    # Tool Conversion
    # =========================================================================

    @staticmethod
    def _convert_tools(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Convert ToolDefinition list to Anthropic tool format.

        OpenAI uses "parameters", Anthropic uses "input_schema" -- same JSON Schema.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    @staticmethod
    def _convert_tool_choice(tool_choice: str) -> Dict[str, str]:
        """Convert OpenAI tool_choice string to Anthropic format."""
        mapping = {
            "auto": {"type": "auto"},
            "required": {"type": "any"},
            "none": {"type": "none"},
        }
        return mapping.get(tool_choice, {"type": "auto"})

    @staticmethod
    def _parse_tool_use_blocks(content_blocks: list) -> List[ToolCall]:
        """Extract ToolCall objects from Anthropic content blocks.

        Anthropic returns tool_use as content blocks with input as dict.
        ToolCallFunction.arguments expects a JSON string.
        """
        tool_calls = []
        for block in content_blocks:
            block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)

            if block_type == "tool_use":
                # Handle both SDK objects and dicts
                if isinstance(block, dict):
                    tc_id = block.get("id", "")
                    tc_name = block.get("name", "")
                    tc_input = block.get("input", {})
                else:
                    tc_id = getattr(block, "id", "")
                    tc_name = getattr(block, "name", "")
                    tc_input = getattr(block, "input", {})

                tool_calls.append(
                    ToolCall.from_provider(
                        provider_id=tc_id,
                        function=ToolCallFunction(
                            name=tc_name,
                            arguments=json.dumps(tc_input),
                        ),
                    )
                )
        return tool_calls

    @staticmethod
    def _map_stop_reason(stop_reason: Optional[str]) -> str:
        """Map Anthropic stop_reason to OpenAI-compatible finish_reason."""
        if not stop_reason:
            return "stop"
        return STOP_REASON_MAP.get(stop_reason, "stop")

    # =========================================================================
    # Prompt Caching
    # =========================================================================

    def _apply_cache_control(
        self, system_text: str, messages: List[Dict[str, Any]]
    ) -> tuple:
        """Apply Anthropic prompt caching breakpoints.

        BP1: System prompt (static across session)
        BP2: Second-to-last message (caches conversation history prefix)

        Args:
            system_text: System prompt string
            messages: Translated Anthropic-format messages

        Returns:
            Tuple of (system_param, messages) with cache_control applied
        """
        # BP1: Convert system to blocks format with cache_control
        if system_text:
            system_param = [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_param = []

        # BP2: Add cache_control to second-to-last message
        if len(messages) >= 3:
            result = [m for m in messages]
            for i in range(len(result) - 2, 0, -1):
                msg_content = result[i].get("content")
                if msg_content is not None:
                    result[i] = self._add_cache_control_to_message(result[i])
                    break
            messages = result

        return system_param, messages

    @staticmethod
    def _add_cache_control_to_message(message: Dict[str, Any]) -> Dict[str, Any]:
        """Add cache_control to the last content block of a message."""
        msg = message.copy()
        content = msg.get("content")

        if content is None:
            return msg

        if isinstance(content, str):
            msg["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and len(content) > 0:
            blocks = list(content)
            last_block = dict(blocks[-1])
            last_block["cache_control"] = {"type": "ephemeral"}
            blocks[-1] = last_block
            msg["content"] = blocks

        return msg

    # =========================================================================
    # Usage Helpers
    # =========================================================================

    @staticmethod
    def _build_usage_dict(usage) -> Dict[str, Any]:
        """Build usage dict from Anthropic usage object for CacheTracker."""
        if not usage:
            return {}

        if isinstance(usage, dict):
            return {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cached_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
            }

        return {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cached_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }

    # =========================================================================
    # Non-Streaming Methods
    # =========================================================================

    def generate(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion from messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional generation parameters

        Returns:
            LLM response
        """
        self.validate_messages(messages)

        # Translate to Anthropic format
        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
        }
        if system_param:
            params["system"] = system_param

        def api_call():
            return self.client.messages.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(
                api_call, max_attempts=3, backoff_base=2.0
            )

            # Extract text content
            content = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    content += getattr(block, "text", "")

            # Validate response quality
            if content:
                self.failure_handler.validate_response(content)

            # Track cache metrics
            usage_dict = self._build_usage_dict(response.usage)
            self.cache_tracker.record(response.usage)
            logger.info(
                f"[CACHE] prompt={usage_dict.get('input_tokens', 0)} "
                f"cached={usage_dict.get('cached_tokens', 0)}"
            )

            return LLMResponse(
                content=content or None,
                model=response.model,
                finish_reason=self._map_stop_reason(response.stop_reason),
                prompt_tokens=usage_dict.get("input_tokens"),
                completion_tokens=usage_dict.get("output_tokens"),
                total_tokens=(
                    (usage_dict.get("input_tokens", 0) or 0)
                    + (usage_dict.get("output_tokens", 0) or 0)
                ),
                cached_tokens=usage_dict.get("cached_tokens"),
                raw_response={"id": response.id},
            )

        except Exception as e:
            raise RuntimeError(f"Anthropic API error: {str(e)}") from e

    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """Generate streaming completion.

        Args:
            messages: List of message dicts
            **kwargs: Additional parameters

        Yields:
            Stream chunks
        """
        self.validate_messages(messages)

        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
            "stream": True,
        }
        if system_param:
            params["system"] = system_param

        try:
            with self.client.messages.stream(**{k: v for k, v in params.items() if k != "stream"}) as stream:
                for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", "") == "text_delta":
                            yield StreamChunk(
                                content=getattr(delta, "text", ""),
                                done=False,
                                model=self.config.model_name,
                            )

                # Get final message for usage
                final_message = stream.get_final_message()
                if final_message and final_message.usage:
                    self.cache_tracker.record(final_message.usage)

                yield StreamChunk(
                    content="",
                    done=True,
                    model=self.config.model_name,
                    finish_reason=self._map_stop_reason(
                        getattr(final_message, "stop_reason", None) if final_message else None
                    ),
                )

        except Exception as e:
            raise RuntimeError(f"Anthropic streaming error: {str(e)}") from e

    def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion with tool calling support.

        Args:
            messages: List of message dicts
            tools: List of available tools
            tool_choice: "auto", "required", "none"
            **kwargs: Additional generation parameters

        Returns:
            LLMResponse with tool_calls field populated if LLM chose to call tools
        """
        self.validate_messages(messages)

        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
            "tools": self._convert_tools(tools),
            "tool_choice": self._convert_tool_choice(tool_choice),
        }
        if system_param:
            params["system"] = system_param

        # Extended thinking support
        thinking_budget = kwargs.get("thinking_budget")
        if thinking_budget:
            max_tok = params.get("max_tokens", self.config.max_tokens)
            if thinking_budget >= max_tok:
                clamped = max(max_tok - 1024, max_tok // 2)
                logger.warning(
                    "thinking_budget_clamped",
                    original=thinking_budget,
                    clamped=clamped,
                    max_tokens=max_tok,
                    model=params.get("model"),
                )
                thinking_budget = clamped
            params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            # Anthropic requires temperature=1 and no top_p with extended thinking
            params["temperature"] = 1
            # top_p already omitted from params

        def api_call():
            return self.client.messages.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(
                api_call, max_attempts=3, backoff_base=2.0
            )

            # Extract text content and tool calls from content blocks
            text_parts = []
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text_parts.append(getattr(block, "text", ""))

            content = "\n".join(text_parts) if text_parts else None
            tool_calls = self._parse_tool_use_blocks(response.content)

            # Validate response quality
            if content:
                self.failure_handler.validate_response(content)

            # Track cache metrics
            usage_dict = self._build_usage_dict(response.usage)
            self.cache_tracker.record(response.usage)
            logger.info(
                f"[CACHE] prompt={usage_dict.get('input_tokens', 0)} "
                f"cached={usage_dict.get('cached_tokens', 0)}"
            )

            # Detect truncation
            finish_reason = self._map_stop_reason(response.stop_reason)
            if finish_reason == "length":
                logger.warning(
                    f"[TRUNCATION DETECTED] Response exceeded max_tokens limit."
                )

            return LLMResponse(
                content=content,
                model=response.model,
                finish_reason=finish_reason,
                prompt_tokens=usage_dict.get("input_tokens"),
                completion_tokens=usage_dict.get("output_tokens"),
                total_tokens=(
                    (usage_dict.get("input_tokens", 0) or 0)
                    + (usage_dict.get("output_tokens", 0) or 0)
                ),
                cached_tokens=usage_dict.get("cached_tokens"),
                tool_calls=tool_calls if tool_calls else None,
                raw_response={"id": response.id},
            )

        except Exception as e:
            raise RuntimeError(f"Anthropic tool calling API error: {str(e)}") from e

    # =========================================================================
    # Legacy Streaming with Tools
    # =========================================================================

    def generate_with_tools_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> Iterator[tuple]:
        """Generate streaming completion with tool calling support.

        Yields:
            Tuple of (StreamChunk, Optional[List[ToolCall]]):
            - During streaming: (chunk with done=False, None)
            - On completion: (chunk with done=True, tool_calls or None)
        """
        self.validate_messages(messages)

        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
            "tools": self._convert_tools(tools),
            "tool_choice": self._convert_tool_choice(tool_choice),
        }
        if system_param:
            params["system"] = system_param

        # Extended thinking support
        thinking_budget = kwargs.get("thinking_budget")
        if thinking_budget:
            max_tok = params.get("max_tokens", self.config.max_tokens)
            if thinking_budget >= max_tok:
                clamped = max(max_tok - 1024, max_tok // 2)
                logger.warning(
                    "thinking_budget_clamped",
                    original=thinking_budget,
                    clamped=clamped,
                    max_tokens=max_tok,
                    model=params.get("model"),
                )
                thinking_budget = clamped
            params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            params["temperature"] = 1
            # top_p already omitted from params

        try:
            # Accumulators
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            model_name = self.config.model_name
            usage_dict = None

            with self.client.messages.stream(**params) as stream:
                for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        idx = getattr(event, "index", 0)
                        if block and getattr(block, "type", "") == "tool_use":
                            tool_calls_acc[idx] = {
                                "id": generate_tool_call_id(),
                                "provider_id": getattr(block, "id", ""),
                                "name": getattr(block, "name", ""),
                                "arguments": "",
                            }

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue

                        delta_type = getattr(delta, "type", "")

                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                yield (
                                    StreamChunk(
                                        content=text,
                                        done=False,
                                        model=model_name,
                                    ),
                                    None,
                                )

                        elif delta_type == "input_json_delta":
                            idx = getattr(event, "index", 0)
                            partial = getattr(delta, "partial_json", "")
                            if idx in tool_calls_acc:
                                tool_calls_acc[idx]["arguments"] += partial

                        # thinking_delta - accumulate but don't yield as StreamChunk

                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            finish_reason = getattr(delta, "stop_reason", None)
                        msg_usage = getattr(event, "usage", None)
                        if msg_usage:
                            usage_dict = self._build_usage_dict(msg_usage)

                # Get final message for complete usage
                final_message = stream.get_final_message()
                if final_message and final_message.usage:
                    usage_dict = self._build_usage_dict(final_message.usage)
                    self.cache_tracker.record(final_message.usage)
                    logger.info(
                        f"[CACHE] prompt={usage_dict.get('input_tokens', 0)} "
                        f"cached={usage_dict.get('cached_tokens', 0)}"
                    )

            # Build final tool calls (sync)
            tool_calls = None
            if tool_calls_acc:
                tool_calls = []
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    try:
                        parsed = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Failed to parse tool arguments for {tc['name']}: "
                            f"{tc['arguments'][:200]}"
                        )
                        parsed = {}
                    tool_calls.append(
                        ToolCall(
                            id=tc["id"],
                            function=ToolCallFunction(
                                name=tc["name"],
                                arguments=json.dumps(parsed),
                            ),
                            meta={"provider_tool_id": tc["provider_id"]},
                        )
                    )

            # Yield final chunk
            yield (
                StreamChunk(
                    content="",
                    done=True,
                    model=model_name,
                    finish_reason=self._map_stop_reason(finish_reason),
                    prompt_tokens=usage_dict.get("input_tokens") if usage_dict else None,
                    completion_tokens=usage_dict.get("output_tokens") if usage_dict else None,
                    total_tokens=(
                        (usage_dict.get("input_tokens", 0) or 0)
                        + (usage_dict.get("output_tokens", 0) or 0)
                    ) if usage_dict else None,
                    cached_tokens=usage_dict.get("cached_tokens") if usage_dict else None,
                ),
                tool_calls,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            is_timeout = "timeout" in error_type.lower()
            category = ErrorCategory.PROVIDER_TIMEOUT if is_timeout else ErrorCategory.PROVIDER_ERROR

            root_cause = e
            while root_cause.__cause__ is not None:
                root_cause = root_cause.__cause__

            logger.exception(
                "anthropic_streaming_error",
                category=category,
                error_type=error_type,
                model=self.config.model_name,
                backend="anthropic",
                operation="generate_with_tools_stream",
                root_cause_type=type(root_cause).__name__,
                root_cause_message=str(root_cause).strip()[:500],
            )
            raise RuntimeError(
                f"Anthropic streaming tool calling error: {error_type}: {error_msg}"
            ) from e

    async def generate_with_tools_stream_async(
        self,
        messages: List[Dict[str, str]],
        tools: List[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> AsyncIterator[tuple]:
        """Async version of generate_with_tools_stream for TUI."""
        self.validate_messages(messages)

        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
            "tools": self._convert_tools(tools),
            "tool_choice": self._convert_tool_choice(tool_choice),
        }
        if system_param:
            params["system"] = system_param

        thinking_budget = kwargs.get("thinking_budget")
        if thinking_budget:
            max_tok = params.get("max_tokens", self.config.max_tokens)
            if thinking_budget >= max_tok:
                clamped = max(max_tok - 1024, max_tok // 2)
                logger.warning(
                    "thinking_budget_clamped",
                    original=thinking_budget,
                    clamped=clamped,
                    max_tokens=max_tok,
                    model=params.get("model"),
                )
                thinking_budget = clamped
            params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            params["temperature"] = 1
            # top_p already omitted from params

        try:
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            model_name = self.config.model_name
            usage_dict = None

            async with self.async_client.messages.stream(**params) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        idx = getattr(event, "index", 0)
                        if block and getattr(block, "type", "") == "tool_use":
                            tool_calls_acc[idx] = {
                                "id": generate_tool_call_id(),
                                "provider_id": getattr(block, "id", ""),
                                "name": getattr(block, "name", ""),
                                "arguments": "",
                            }

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue

                        delta_type = getattr(delta, "type", "")

                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                yield (
                                    StreamChunk(
                                        content=text,
                                        done=False,
                                        model=model_name,
                                    ),
                                    None,
                                )

                        elif delta_type == "input_json_delta":
                            idx = getattr(event, "index", 0)
                            partial = getattr(delta, "partial_json", "")
                            if idx in tool_calls_acc:
                                tool_calls_acc[idx]["arguments"] += partial

                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            finish_reason = getattr(delta, "stop_reason", None)
                        msg_usage = getattr(event, "usage", None)
                        if msg_usage:
                            usage_dict = self._build_usage_dict(msg_usage)

                final_message = await stream.get_final_message()
                if final_message and final_message.usage:
                    usage_dict = self._build_usage_dict(final_message.usage)
                    self.cache_tracker.record(final_message.usage)
                    logger.info(
                        f"[CACHE] prompt={usage_dict.get('input_tokens', 0)} "
                        f"cached={usage_dict.get('cached_tokens', 0)}"
                    )

            # Build final tool calls (async)
            tool_calls = None
            if tool_calls_acc:
                tool_calls = []
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    try:
                        parsed = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Failed to parse tool arguments for {tc['name']}: "
                            f"{tc['arguments'][:200]}"
                        )
                        parsed = {}
                    tool_calls.append(
                        ToolCall(
                            id=tc["id"],
                            function=ToolCallFunction(
                                name=tc["name"],
                                arguments=json.dumps(parsed),
                            ),
                            meta={"provider_tool_id": tc["provider_id"]},
                        )
                    )

            yield (
                StreamChunk(
                    content="",
                    done=True,
                    model=model_name,
                    finish_reason=self._map_stop_reason(finish_reason),
                    prompt_tokens=usage_dict.get("input_tokens") if usage_dict else None,
                    completion_tokens=usage_dict.get("output_tokens") if usage_dict else None,
                    total_tokens=(
                        (usage_dict.get("input_tokens", 0) or 0)
                        + (usage_dict.get("output_tokens", 0) or 0)
                    ) if usage_dict else None,
                    cached_tokens=usage_dict.get("cached_tokens") if usage_dict else None,
                ),
                tool_calls,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            is_timeout = "timeout" in error_type.lower()
            category = ErrorCategory.PROVIDER_TIMEOUT if is_timeout else ErrorCategory.PROVIDER_ERROR

            root_cause = e
            while root_cause.__cause__ is not None:
                root_cause = root_cause.__cause__

            logger.exception(
                "anthropic_async_streaming_error",
                category=category,
                error_type=error_type,
                model=self.config.model_name,
                backend="anthropic",
                operation="generate_with_tools_stream_async",
                root_cause_type=type(root_cause).__name__,
                root_cause_message=str(root_cause).strip()[:500],
            )
            raise RuntimeError(
                f"Anthropic async streaming tool calling error: {error_type}: {error_msg}"
            ) from e

    # =========================================================================
    # ProviderDelta Methods (Unified Persistence Architecture)
    # =========================================================================

    def generate_provider_deltas(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: str = "auto",
        stream_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[ProviderDelta]:
        """Generate streaming completion as ProviderDelta objects.

        Canonical interface for the Unified Persistence Architecture.
        Emits raw deltas consumed by StreamingPipeline.

        Args:
            messages: List of message dicts
            tools: Optional list of tools
            tool_choice: "auto", "required", "none"
            stream_id: Optional stream ID (auto-generated if not provided)
            **kwargs: Additional generation parameters

        Yields:
            ProviderDelta objects
        """
        from src.session.models.base import generate_stream_id

        self.validate_messages(messages)
        sid = stream_id or generate_stream_id()

        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
        }
        if system_param:
            params["system"] = system_param
        if tools:
            params["tools"] = self._convert_tools(tools)
            params["tool_choice"] = self._convert_tool_choice(tool_choice)

        thinking_budget = kwargs.get("thinking_budget")
        if thinking_budget:
            max_tok = params.get("max_tokens", self.config.max_tokens)
            # Guard: budget_tokens must be < max_tokens (Anthropic/Bedrock requirement)
            if thinking_budget >= max_tok:
                clamped = max(max_tok - 1024, max_tok // 2)
                logger.warning(
                    "thinking_budget_clamped",
                    original=thinking_budget,
                    clamped=clamped,
                    max_tokens=max_tok,
                    model=params.get("model"),
                )
                thinking_budget = clamped
            params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            params["temperature"] = 1
            # top_p already omitted from params

        try:
            # Track tool call ordinal (not content block index) - sync
            tool_call_ordinal = 0
            finish_reason = None
            usage_dict = None

            with self.client.messages.stream(**params) as stream:
                for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "tool_use":
                            yield ProviderDelta(
                                stream_id=sid,
                                tool_call_delta=ToolCallDelta(
                                    index=tool_call_ordinal,
                                    id=generate_tool_call_id(),
                                    name=getattr(block, "name", ""),
                                    arguments_delta="",
                                ),
                            )
                            tool_call_ordinal += 1

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue

                        delta_type = getattr(delta, "type", "")

                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                yield ProviderDelta(
                                    stream_id=sid,
                                    text_delta=text,
                                )

                        elif delta_type == "input_json_delta":
                            partial = getattr(delta, "partial_json", "")
                            if partial:
                                # tool_call_ordinal was incremented on start,
                                # so current tool is ordinal - 1
                                yield ProviderDelta(
                                    stream_id=sid,
                                    tool_call_delta=ToolCallDelta(
                                        index=tool_call_ordinal - 1,
                                        arguments_delta=partial,
                                    ),
                                )

                        elif delta_type == "thinking_delta":
                            thinking_text = getattr(delta, "thinking", "")
                            if thinking_text:
                                yield ProviderDelta(
                                    stream_id=sid,
                                    thinking_delta=thinking_text,
                                )

                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            finish_reason = getattr(delta, "stop_reason", None)
                        msg_usage = getattr(event, "usage", None)
                        if msg_usage:
                            usage_dict = self._build_usage_dict(msg_usage)

                # Get final usage from complete message
                final_message = stream.get_final_message()
                if final_message and final_message.usage:
                    usage_dict = self._build_usage_dict(final_message.usage)
                    self.cache_tracker.record(final_message.usage)
                    logger.info(
                        f"[CACHE] prompt={usage_dict.get('input_tokens', 0)} "
                        f"cached={usage_dict.get('cached_tokens', 0)}"
                    )

            # Extract thinking signature from final message for round-tripping
            thinking_signature = None
            if final_message and hasattr(final_message, 'content'):
                for block in final_message.content:
                    if getattr(block, 'type', '') == 'thinking':
                        thinking_signature = getattr(block, 'signature', None)
                        break

            # Emit final delta with finish_reason and usage
            yield ProviderDelta(
                stream_id=sid,
                finish_reason=self._map_stop_reason(finish_reason),
                usage=usage_dict,
                thinking_signature=thinking_signature,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            logger.exception(
                "anthropic_provider_delta_error",
                error_type=error_type,
                model=self.config.model_name,
            )
            raise RuntimeError(
                f"Anthropic provider delta error: {error_type}: {error_msg}"
            ) from e

    async def generate_provider_deltas_async(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: str = "auto",
        stream_id: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProviderDelta]:
        """Async version of generate_provider_deltas for TUI."""
        from src.session.models.base import generate_stream_id

        self.validate_messages(messages)
        sid = stream_id or generate_stream_id()

        system_text, api_messages = self._translate_messages(messages)
        system_param, api_messages = self._apply_cache_control(system_text, api_messages)

        params = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            # Note: top_p omitted — Claude rejects temperature + top_p together.
            # Temperature takes precedence since it's always configured.
        }
        if system_param:
            params["system"] = system_param
        if tools:
            params["tools"] = self._convert_tools(tools)
            params["tool_choice"] = self._convert_tool_choice(tool_choice)

        thinking_budget = kwargs.get("thinking_budget")
        if thinking_budget:
            max_tok = params.get("max_tokens", self.config.max_tokens)
            # Guard: budget_tokens must be < max_tokens (Anthropic/Bedrock requirement)
            if thinking_budget >= max_tok:
                clamped = max(max_tok - 1024, max_tok // 2)
                logger.warning(
                    "thinking_budget_clamped",
                    original=thinking_budget,
                    clamped=clamped,
                    max_tokens=max_tok,
                    model=params.get("model"),
                )
                thinking_budget = clamped
            params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            params["temperature"] = 1
            # top_p already omitted from params

        try:
            tool_call_ordinal = 0
            finish_reason = None
            usage_dict = None

            async with self.async_client.messages.stream(**params) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "tool_use":
                            yield ProviderDelta(
                                stream_id=sid,
                                tool_call_delta=ToolCallDelta(
                                    index=tool_call_ordinal,
                                    id=generate_tool_call_id(),
                                    name=getattr(block, "name", ""),
                                    arguments_delta="",
                                ),
                            )
                            tool_call_ordinal += 1

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if not delta:
                            continue

                        delta_type = getattr(delta, "type", "")

                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                yield ProviderDelta(
                                    stream_id=sid,
                                    text_delta=text,
                                )

                        elif delta_type == "input_json_delta":
                            partial = getattr(delta, "partial_json", "")
                            if partial:
                                yield ProviderDelta(
                                    stream_id=sid,
                                    tool_call_delta=ToolCallDelta(
                                        index=tool_call_ordinal - 1,
                                        arguments_delta=partial,
                                    ),
                                )

                        elif delta_type == "thinking_delta":
                            thinking_text = getattr(delta, "thinking", "")
                            if thinking_text:
                                yield ProviderDelta(
                                    stream_id=sid,
                                    thinking_delta=thinking_text,
                                )

                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            finish_reason = getattr(delta, "stop_reason", None)
                        msg_usage = getattr(event, "usage", None)
                        if msg_usage:
                            usage_dict = self._build_usage_dict(msg_usage)

                final_message = await stream.get_final_message()
                if final_message and final_message.usage:
                    usage_dict = self._build_usage_dict(final_message.usage)
                    self.cache_tracker.record(final_message.usage)
                    logger.info(
                        f"[CACHE] prompt={usage_dict.get('input_tokens', 0)} "
                        f"cached={usage_dict.get('cached_tokens', 0)}"
                    )

            # Extract thinking signature from final message for round-tripping
            thinking_signature = None
            if final_message and hasattr(final_message, 'content'):
                for block in final_message.content:
                    if getattr(block, 'type', '') == 'thinking':
                        thinking_signature = getattr(block, 'signature', None)
                        break

            yield ProviderDelta(
                stream_id=sid,
                finish_reason=self._map_stop_reason(finish_reason),
                usage=usage_dict,
                thinking_signature=thinking_signature,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            logger.exception(
                "anthropic_async_provider_delta_error",
                error_type=error_type,
                model=self.config.model_name,
            )
            raise RuntimeError(
                f"Anthropic async provider delta error: {error_type}: {error_msg}"
            ) from e

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def count_tokens(self, text: str) -> int:
        """Approximate token count (~4 chars per token)."""
        return len(text) // 4

    def is_available(self) -> bool:
        """Check if Anthropic API is reachable."""
        try:
            # Quick test: create a minimal message
            self.client.messages.create(
                model=self.config.model_name,
                max_tokens=1,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return True
        except Exception as e:
            logger.error(f"Backend availability check failed: {type(e).__name__}: {str(e)}")
            return False

    def list_models(self) -> List[str]:
        """Return known Claude model IDs (Anthropic has no list endpoint)."""
        return list(KNOWN_CLAUDE_MODELS)

    def log_cache_summary(self) -> None:
        """Log prompt caching performance summary."""
        if self.cache_tracker.total_calls > 0:
            logger.info(self.cache_tracker.format_summary())
